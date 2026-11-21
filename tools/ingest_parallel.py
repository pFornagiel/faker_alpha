#!/usr/bin/env python
"""Parallel ingest of a folder of case directories into a store (research corpora).

`ftf.cli ingest` analyses one material at a time, which is fine for the 11-case demo set but not for a
few thousand harvested pages. This driver runs feature extraction in worker processes and writes to
SQLite from the parent only, so the store is never touched concurrently.

    FTF_STORE=data/store/ftf_harvest.sqlite python tools/ingest_parallel.py data/harvest/urlscan \
        --source urlscan --workers 16 --require page.html

Resumable: materials already in the store are skipped unless --force is given. LLM attribute extraction
and online enrichment are off by default (no network use during analysis).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


THREAD_VARS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")


def _init(threads: int) -> None:
    """Cap every thread pool in the worker.

    onnxruntime sizes its pool to the machine's core count per session unless told otherwise, and the OCR
    engine opens three sessions with defaults. On a many-core host that means hundreds of spinning threads
    per worker, so the cap is forced on every session created in this process, before any model is loaded.
    """
    for var in THREAD_VARS:
        os.environ[var] = str(threads)
    import onnxruntime as ort

    original = ort.InferenceSession

    class CappedSession(original):
        def __init__(self, path_or_bytes, sess_options=None, *args, **kwargs):
            so = sess_options or ort.SessionOptions()
            so.intra_op_num_threads = threads
            so.inter_op_num_threads = 1
            so.add_session_config_entry("session.intra_op.allow_spinning", "0")
            super().__init__(path_or_bytes, so, *args, **kwargs)

    ort.InferenceSession = CappedSession
    try:
        import cv2

        cv2.setNumThreads(threads)
    except Exception:
        pass


def _work(folder: str, source: str, use_llm: bool, enrich: bool):
    try:
        from ftf import ingest
        from ftf.pipeline import analyze

        t0 = time.time()
        m = ingest.load_folder(folder, source=source, name=Path(folder).name)
        f, v = analyze(m, use_llm=use_llm, progress=lambda s: None, enrich_online=enrich)
        return folder, m, f, v, time.time() - t0, None
    except Exception:
        return folder, None, None, None, 0.0, traceback.format_exc(limit=4)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", help="folder whose immediate sub-folders are cases")
    ap.add_argument("--source", default="urlscan", help="Material.source value (default: urlscan)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--threads", type=int, default=2, help="BLAS/OpenMP threads per worker")
    ap.add_argument("--require", action="append", default=[], help="skip cases missing this file (repeatable)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--llm", action="store_true", help="use the configured LLM backend")
    ap.add_argument("--enrich", action="store_true", help="allow online enrichment (RDAP/DNS/CT)")
    ap.add_argument("--force", action="store_true", help="re-analyse materials already in the store")
    ap.add_argument("--cores", type=int, default=0,
                    help="pin the whole job to this many CPU cores (default: workers * threads); a hard ceiling "
                         "on what it can take from a shared machine")
    a = ap.parse_args()

    for var in THREAD_VARS:
        os.environ[var] = str(a.threads)
    if hasattr(os, "sched_setaffinity"):
        allowed = sorted(os.sched_getaffinity(0))
        want = a.cores or a.workers * a.threads
        os.sched_setaffinity(0, set(allowed[-want:]))      # inherited by the workers

    from ftf import ingest
    from ftf.store import Store

    store = Store()
    root = Path(a.root)
    folders = [p for p in sorted(root.iterdir()) if p.is_dir() and not p.name.startswith(("_", "."))]
    todo, skipped = [], {"in_store": 0, "incomplete": 0}
    for p in folders:
        if any(not (p / r).exists() for r in a.require):
            skipped["incomplete"] += 1
        elif not a.force and store.has(ingest._mid(a.source, str(p.resolve()))):
            skipped["in_store"] += 1
        else:
            todo.append(str(p))
    if a.limit:
        todo = todo[: a.limit]
    print(f"cases: {len(folders)} | to analyse: {len(todo)} | skipped: {skipped} | store: {store.path}",
          flush=True)

    t0, done, failed, secs = time.time(), 0, 0, 0.0
    with ProcessPoolExecutor(max_workers=a.workers, initializer=_init, initargs=(a.threads,),
                             max_tasks_per_child=200) as ex:
        futs = [ex.submit(_work, f, a.source, a.llm, a.enrich) for f in todo]
        for fut in as_completed(futs):
            folder, m, f, v, dt, err = fut.result()
            if err:
                failed += 1
                print(f"FAILED {Path(folder).name}: {err.strip().splitlines()[-1]}", flush=True)
            else:
                store.upsert(m, f, v)
                done += 1
                secs += dt
            n = done + failed
            if n % 25 == 0 or n == len(todo):
                el = time.time() - t0
                print(f"[{el:6.0f}s] {n}/{len(todo)} | ok {done} failed {failed} | "
                      f"{secs / max(done, 1):.1f}s per case | {n / max(el, 1) * 60:.0f} cases/min", flush=True)
    print(f"done: ok {done}, failed {failed}, store now holds {store.count()} materials", flush=True)


if __name__ == "__main__":
    main()
