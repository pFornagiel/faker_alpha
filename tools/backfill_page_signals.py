#!/usr/bin/env python
"""Add the page-structure signals to materials analysed before they existed, without re-running OCR or models.

Recomputed from the saved pages and capture metadata of each material:
  vectors   css (class-name MinHash), js (script-skeleton MinHash)
  features  text.lang, text.lang_ocr, indicators.cert_batch, per-page class / shingle counts
For urlscan cases `dns_ssl.json` is first refreshed from `urlscan_result.json`, which adds the certificate's
name list (`tls_san`) that the certificate-batch identifier needs.

    FTF_STORE=data/store/ftf_harvest.sqlite python tools/backfill_page_signals.py [--workers 8]

Run it from the directory the stored paths are relative to. The store is written by the parent process only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))


def refresh_dns_ssl(folder: Path) -> bool:
    """Rewrite dns_ssl.json of a urlscan case with the certificate name list; True when it changed."""
    res, out = folder / "urlscan_result.json", folder / "dns_ssl.json"
    if not res.exists() or not out.exists():
        return False
    from harvest_urlscan import dns_ssl

    old = json.loads(out.read_text(encoding="utf-8"))
    if "tls_san" in old:
        return False
    result = json.loads(res.read_text(encoding="utf-8"))
    new = {**old, "tls_san": dns_ssl(result.get("page") or {}, result)["tls_san"]}
    out.write_text(json.dumps(new, ensure_ascii=False), encoding="utf-8")
    return True


def _work(mid: str, material: dict, feats: dict):
    try:
        from ftf import ingest, lang, pipeline

        m = ingest.Material.from_dict(material)
        if m.source_ref and Path(m.source_ref).is_dir():
            refresh_dns_ssl(Path(m.source_ref))
        meta = ingest.read_meta(m)
        web_s = pipeline._stage_web(m, meta, lambda s: None)
        titles = list(dict.fromkeys(web_s.titles))
        page_text = ("\n".join(titles) + "\n" + "\n".join(web_s.page_texts)).strip()[:40000]
        meta_text = " ".join(f"{a.get('title') or ''} {a.get('description') or ''} {a.get('advertiser') or ''}"
                             for a in meta.get("ad_library", []))
        ocr_text = " ".join(im.get("ocr_text", "") for im in feats.get("images", []))
        creative_text = (ocr_text + "\n" + "\n".join(m.texts) + "\n" + meta_text).strip()
        return mid, {"css": web_s.css_sigs, "js": web_s.js_sigs,
                     "lang": lang.language(page_text), "lang_ocr": lang.language(creative_text),
                     "cert_batch": sorted(web_s.indicators.get("cert_batch", ())),
                     "pages": {p["file"]: (p.get("n_classes"), p.get("n_script_shingles")) for p in web_s.page_info
                               if "n_classes" in p}}, None
    except Exception:
        return mid, None, traceback.format_exc(limit=4)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[var] = "1"
    if hasattr(os, "sched_setaffinity"):
        os.sched_setaffinity(0, set(sorted(os.sched_getaffinity(0))[-a.workers:]))

    from ftf.store import Store, _np_to_blob

    store = Store()
    items = list(store.all().items())[: a.limit or None]
    print(f"materials: {len(items)} | store: {store.path}", flush=True)
    t0, done, failed, stats = time.time(), 0, 0, {"css": 0, "js": 0, "lang": 0, "cert_batch": 0}
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(_work, mid, f["_material"], {"images": f.get("images", [])}) for mid, (f, _) in items]
        for fut in as_completed(futs):
            mid, r, err = fut.result()
            if err:
                failed += 1
                print(f"FAILED {mid}: {err.strip().splitlines()[-1]}", flush=True)
                continue
            row = store.db.execute("SELECT features FROM materials WHERE id=?", (mid,)).fetchone()
            f = json.loads(row[0])
            f.setdefault("text", {}).update(lang=r["lang"], lang_ocr=r["lang_ocr"])
            ind = f.setdefault("indicators", {})
            ind.pop("cert_batch", None)
            if r["cert_batch"]:
                ind["cert_batch"] = r["cert_batch"]
            for p in (f.get("web") or {}).get("pages", []):
                if p.get("file") in r["pages"]:
                    p["n_classes"], p["n_script_shingles"] = r["pages"][p["file"]]
            store.db.execute("UPDATE materials SET features=? WHERE id=?", (json.dumps(f, ensure_ascii=False, default=str), mid))
            for kind in ("css", "js"):
                store.db.execute("DELETE FROM vectors WHERE material_id=? AND kind=?", (mid, kind))
                if r[kind]:
                    store.db.execute("INSERT INTO vectors VALUES(?,?,?)", (mid, kind, _np_to_blob(r[kind])))
                    stats[kind] += 1
            stats["lang"] += r["lang"] != "und"
            stats["cert_batch"] += bool(r["cert_batch"])
            done += 1
            if done % 200 == 0:
                store.db.commit()
                print(f"[{time.time() - t0:5.0f}s] {done}/{len(items)} {stats}", flush=True)
    store.db.commit()
    print(f"done: ok {done}, failed {failed} | materials with {stats}", flush=True)


if __name__ == "__main__":
    main()
