"""Command line:  python -m ftf.cli <command>

  ingest <dataset_dir> [--no-llm] [--force]   analyse every case folder and store features
  add <path|url|text>                         analyse one new material and assign it (open-set)
  campaigns                                   print campaigns with shared indicators
  links [--min 0.1]                           print explained links (p = 1 - D)
  export                                      write data/exports/{graph.html,graph.cypher,campaigns.json,links.csv}
  eval <labels.csv>                           pairwise P/R/F1, ARI, B-cubed vs ground truth (id_or_name,label)
  serve [--host 127.0.0.1] [--port 8765]      web UI + API (build the UI first: cd web && npm ci && npm run build)
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from pathlib import Path

from . import config, ingest
from .engine import Engine


def _print_campaigns(eng: Engine):
    cl = eng.clustering(refresh=True)
    items = eng.store.all()
    for ci, prof in enumerate(cl["profiles"]):
        names = [items[m][0]["name"] for m in prof["members"]]
        print(f"\n=== C{ci + 1} ({prof['size']}) {prof['name']}  members={names}")
        print(f"    scam={prof['scam_types']} products={prof['products']} domains={list(prof['domains'])[:6]}")
        print(f"    persons={prof['persons']}  dates={prof['date_range']}  shared_groups={prof['shared_groups']}")
        for s in prof["shared_indicators"][:8]:
            print(f"      shared {s['group']:12s} {s['type']:16s} x{s['count']}  {s['value'][:90]}")
    print("\nduplicates:", [[items[m][0]["name"] for m in g] for g in cl["duplicates"]])
    print("families:", [[items[m][0]["name"] for m in f] for f in cl["families"]])
    print("hdbscan baseline:", {items[m][0]["name"]: l for m, l in cl["hdbscan"].items()})


def _print_links(eng: Engine, min_p: float):
    cl = eng.clustering()
    items = eng.store.all()
    for l in sorted(cl["links"], key=lambda l: -l.p):
        if l.p < min_p:
            continue
        print(f"{items[l.a][0]['name']:>6} — {items[l.b][0]['name']:<6} p={l.p:.2f} d={l.distance:.2f} {l.relation:13s} {l.explain(5)}")


def evaluate(eng: Engine, labels_csv: str) -> dict:
    from itertools import combinations

    from sklearn.metrics import adjusted_rand_score

    items = eng.store.all()
    name2id = {f["name"]: mid for mid, (f, _) in items.items()}
    gold = {}
    with open(labels_csv, encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if len(row) >= 2 and not row[0].startswith("#"):
                key = row[0].strip()
                mid = key if key in items else name2id.get(key)
                if mid:
                    gold[mid] = row[1].strip()
    cl = eng.clustering(refresh=True)
    pred = {m: cl["campaign_of"][m] for m in gold}
    ids = sorted(gold)
    tp = fp = fn = 0
    for a, b in combinations(ids, 2):
        g, p = gold[a] == gold[b], pred[a] == pred[b]
        tp += g and p
        fp += (not g) and p
        fn += g and (not p)
    prec = tp / (tp + fp) if tp + fp else 1.0
    rec = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    # B-cubed
    bp = br = 0.0
    for m in ids:
        same_p = [x for x in ids if pred[x] == pred[m]]
        same_g = [x for x in ids if gold[x] == gold[m]]
        inter = len([x for x in same_p if gold[x] == gold[m]])
        bp += inter / len(same_p)
        br += inter / len(same_g)
    bp, br = bp / len(ids), br / len(ids)
    res = {"n": len(ids), "pairwise_precision": round(prec, 3), "pairwise_recall": round(rec, 3), "pairwise_f1": round(f1, 3),
           "bcubed_precision": round(bp, 3), "bcubed_recall": round(br, 3),
           "ARI": round(adjusted_rand_score([gold[m] for m in ids], [pred[m] for m in ids]), 3)}
    hd = cl.get("hdbscan") or {}
    if hd:
        res["ARI_hdbscan_baseline"] = round(adjusted_rand_score([gold[m] for m in ids], [hd.get(m, -1) if hd.get(m, -1) >= 0 else 1000 + i for i, m in enumerate(ids)]), 3)
    return res


def main(argv=None):
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="ftf")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("ingest"); s.add_argument("root"); s.add_argument("--no-llm", action="store_true"); s.add_argument("--force", action="store_true")
    s = sub.add_parser("add"); s.add_argument("target"); s.add_argument("--no-llm", action="store_true"); s.add_argument("--dry", action="store_true")
    sub.add_parser("campaigns")
    s = sub.add_parser("links"); s.add_argument("--min", type=float, default=0.1)
    sub.add_parser("export")
    s = sub.add_parser("eval"); s.add_argument("labels")
    s = sub.add_parser("serve"); s.add_argument("--host", default="127.0.0.1"); s.add_argument("--port", type=int, default=8765)
    a = ap.parse_args(argv)
    if a.cmd == "serve":
        import uvicorn

        if not (config.ROOT / "web" / "dist" / "index.html").exists():
            print("web UI not built — run: cd web && npm ci && npm run build   (API alone is still served under /api)")
        print(f"FakeTrace UI: http://{a.host}:{a.port}")
        uvicorn.run("ftf.api:app", host=a.host, port=a.port, log_level="warning")
        return 0
    eng = Engine()
    if a.cmd == "ingest":
        n = eng.add_dataset(a.root, use_llm=not a.no_llm, progress=lambda s: print(s, flush=True), force=a.force)
        print(f"ingested {n} materials; store has {eng.store.count()}")
        _print_campaigns(eng)
    elif a.cmd == "add":
        t = a.target
        if Path(t).exists():
            p = Path(t)
            m = ingest.load_folder(p, source="upload") if p.is_dir() else ingest.from_upload(p.name, p.read_bytes())
        elif t.startswith("http"):
            from .capture import capture_url

            m = ingest.from_url(t, capture_url(t))
        else:
            m = ingest.from_text(t)
        r = eng.analyse_new(m, use_llm=not a.no_llm, keep=not a.dry, progress=lambda s: print(" ", s, flush=True))
        items = eng.store.all()
        print("decision:", r["decision"], "campaign:", r["campaign"], "nearest:", r["nearest"],
              "similar_family:", r["similar_family"], "scores:", r["campaign_scores"])
        for l in r["links"][:8]:
            nm = items[l.b][0]["name"] if l.b in items else l.b
            print(f"  vs {nm:>8}: p={l.p:.2f} d={l.distance:.2f} {l.relation:13s} {l.explain(4)}")
    elif a.cmd == "campaigns":
        _print_campaigns(eng)
    elif a.cmd == "links":
        _print_links(eng, a.min)
    elif a.cmd == "export":
        cl = eng.clustering(refresh=True)
        items = eng.store.all()
        print(eng.graph_html())
        print(eng.export_cypher())
        out = config.EXPORTS / "campaigns.json"
        out.write_text(json.dumps([{**p, "members": [items[m][0]["name"] for m in p["members"]]} for p in cl["profiles"]],
                                  ensure_ascii=False, indent=1, default=str))
        with open(config.EXPORTS / "links.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["a", "b", "p", "distance", "relation", "views", "explanation"])
            for l in sorted(cl["links"], key=lambda l: (-l.p, l.distance)):
                if l.relation != "none":
                    w.writerow([items[l.a][0]["name"], items[l.b][0]["name"], round(l.p, 3), round(l.distance, 3), l.relation,
                                json.dumps({k: round(v, 3) for k, v in l.views.items()}), l.explain(8)])
        print(out)
    elif a.cmd == "eval":
        print(json.dumps(evaluate(eng, a.labels), indent=1))


if __name__ == "__main__":
    sys.exit(main())
