"""Evaluation without ground-truth labels, mirroring the organiser's test plan
("new variants of known campaigns" + "materials that must NOT be linked").

  1. leave-one-out : remove each material, rebuild campaigns, assign it back (open-set decision)
  2. synthetic variants per material (written to data/eval/variants/<case>/<variant>/):
       creative_only   - only screenshots / video (landing page 'dead')
       landing_only    - only HTML/HAR (creative missing)
       recompressed    - screenshots cropped 8 %, downscaled x0.6, JPEG q=55
       domain_swap     - landing HTML with every occurrence of its domain replaced by a fresh one
       person_swap     - landing HTML with the main impersonated person's surname replaced
     expected: assigned to the source material's campaign (known_campaign / duplicate / candidate)
  3. labels (optional): --labels data/labels.csv -> pairwise P/R/F1, B-cubed, ARI

    .venv/bin/python tools/evaluate.py [--variants creative_only,recompressed,...] [--no-llm] [--labels ...]
"""
from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ftf import config, ingest  # noqa: E402
from ftf.cluster import assign, build  # noqa: E402
from ftf.engine import Engine  # noqa: E402
from ftf.pipeline import analyze  # noqa: E402

OK = {"known_campaign", "duplicate", "merge_proposal"}
SOFT = OK | {"candidate_review"}
SWAP = {"Brzosk": "Kulczyk", "Olejnik": "Wellman", "Stanowsk": "Rymanowsk", "Sekielsk": "Kraśk", "Glapińsk": "Sołowow"}


def leave_one_out(items: dict) -> list[dict]:
    full = build(items)
    out = []
    for mid in items:
        rest = {k: v for k, v in items.items() if k != mid}
        cl = build(rest)
        f, v = items[mid]
        r = assign(mid, f, v, rest, cl)
        mates = [m for m in full["campaigns"][full["campaign_of"][mid]] if m != mid]
        if mates:
            target = Counter(cl["campaign_of"][m] for m in mates).most_common(1)[0][0]
            ok = r["decision"] in OK and r["campaign"] == target
            soft = r["decision"] in SOFT and r["campaign"] == target
            exp = "known_campaign"
        else:
            ok = soft = r["decision"] in ("new_campaign", "candidate_review")
            ok = r["decision"] == "new_campaign"
            exp = "new_campaign"
        out.append({"material": f["name"], "expected": exp, "decision": r["decision"], "ok": ok, "soft_ok": soft,
                    "best": r["campaign_scores"][:2]})
    return out


def _copy(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    dst.symlink_to(Path(src).resolve())      # no duplication of large videos


def make_variants(m: ingest.Material, kinds: list[str], root: Path, f: dict) -> list[tuple[str, ingest.Material]]:
    out = []
    base = root / m.name
    pages = [Path(p["path"]) for p in m.pages if p["kind"] in ("html", "har")]
    shots = [Path(p) for p in m.images] + [Path(p) for p in m.videos]
    doms = f.get("web", {}).get("landing_domains", [])
    for k in kinds:
        d = base / k
        shutil.rmtree(d, ignore_errors=True)
        if k == "creative_only" and shots and pages:
            for s in shots:
                _copy(s, d / s.name)
        elif k == "landing_only" and pages and shots:
            for p in pages:
                _copy(p, d / p.name)
        elif k == "recompressed" and m.images:
            for s in m.images:
                im = Image.open(s).convert("RGB")
                w, h = im.size
                im = im.crop((int(w * .08), int(h * .08), int(w * .92), int(h * .92)))
                im = im.resize((int(im.width * .6), int(im.height * .6)))
                d.mkdir(parents=True, exist_ok=True)
                im.save(d / (Path(s).stem + ".jpg"), quality=55)
        elif k in ("domain_swap", "person_swap"):
            htmls = [p for p in pages if p.suffix.lower() in (".html", ".htm")]
            if not htmls:
                continue
            for p in htmls:
                txt = p.read_text(encoding="utf-8", errors="replace")
                if k == "domain_swap":
                    if not doms:
                        continue
                    new = "x" + "".join(random.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(9)) + ".click"
                    for dm in doms:
                        txt = txt.replace(dm, new)
                    txt = re.sub(r"(utm_[a-z]+|fbclid|pxl|fbpx|ad_id)=[^&\"'\s]+", r"\1=REDACTED", txt)  # also drop IDs
                else:
                    hit = next((s for s in SWAP if s in txt), None)
                    if not hit:
                        continue
                    txt = txt.replace(hit, SWAP[hit])
                d.mkdir(parents=True, exist_ok=True)
                (d / p.name).write_text(txt, encoding="utf-8")
        if d.exists() and any(d.iterdir()):
            out.append((k, ingest.load_folder(d, source="eval", name=f"{m.name}~{k}")))
    return out


def run_variants(items: dict, kinds: list[str], use_llm: bool, only: list[str] | None = None) -> list[dict]:
    cl = build(items)
    root = config.DATA / "eval" / "variants"
    res = []
    for mid, (f, v) in items.items():
        if only and f["name"] not in only:
            continue
        mat = ingest.Material.from_dict(f["_material"])
        for kind, vm in make_variants(mat, kinds, root, f):
            vf, vv = analyze(vm, use_llm=use_llm)
            r = assign(vm.id, vf, vv, items, cl)
            target = cl["campaign_of"][mid]
            src_link = next((l for l in r["links"] if l.b == mid), None)
            res.append({"variant": vm.name, "kind": kind, "decision": r["decision"], "campaign": r["campaign"],
                        "expected_campaign": target, "ok": r["decision"] in OK and r["campaign"] == target,
                        "soft_ok": r["decision"] in SOFT and r["campaign"] == target,
                        "p_to_source": round(src_link.p, 3) if src_link else None,
                        "why": src_link.explain(4) if src_link else ""})
            print(json.dumps(res[-1], ensure_ascii=False), flush=True)
    return res


def summary(rows: list[dict], key: str = "kind") -> dict:
    by = {}
    for r in rows:
        k = r.get(key, "all")
        b = by.setdefault(k, {"n": 0, "ok": 0, "soft_ok": 0})
        b["n"] += 1
        b["ok"] += int(r["ok"])
        b["soft_ok"] += int(r["soft_ok"])
    return {k: {**v, "acc": round(v["ok"] / v["n"], 3), "soft_acc": round(v["soft_ok"] / v["n"], 3)} for k, v in by.items()}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", default="creative_only,landing_only,recompressed,domain_swap,person_swap")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--skip-variants", action="store_true")
    ap.add_argument("--labels")
    ap.add_argument("--only", help="comma-separated case names for the variant test")
    a = ap.parse_args()
    random.seed(7)
    eng = Engine()
    items = eng.store.all()
    items = {k: v for k, v in items.items() if v[0].get("source") == "organizer"} or items
    report = {}
    loo = leave_one_out(items)
    for r in loo:
        print("LOO", json.dumps(r, ensure_ascii=False))
    report["leave_one_out"] = {"rows": loo, "summary": summary(loo, "expected")}
    if not a.skip_variants:
        var = run_variants(items, a.variants.split(","), use_llm=not a.no_llm, only=a.only.split(",") if a.only else None)
        report["variants"] = {"rows": var, "summary": summary(var)}
    if a.labels:
        from ftf.cli import evaluate

        report["labels"] = evaluate(eng, a.labels)
    out = config.DATA / "eval" / (f"report_only_{a.only.replace(',', '_')}.json" if a.only else "report.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    print(json.dumps({k: v.get("summary", v) for k, v in report.items()}, indent=1, ensure_ascii=False))
