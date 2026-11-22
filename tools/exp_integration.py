#!/usr/bin/env python
"""Effect of the integrated signals on the research corpus, one change at a time.

The corpus is re-analysed with the current code into its own store. Pairwise comparison then runs twice:
  raw      language rule switched off and the certificate-batch identifier removed (all seven views as computed)
  product  the code as shipped
From the raw matrices each change is applied on its own, so its contribution can be read off, and the sum of all
changes is checked against the product run. `new` counts pairs the grouping before the integration did not have.

    FTF_ROOT=<checkout with data/> FTF_HARVEST_STORE=<re-analysed store> FTF_EXP_BASE_CACHE=<cache of the old product> \
        FTF_EXP_CACHE=<new cache dir> python tools/exp_integration.py
"""
from __future__ import annotations

import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import exp_harness as H  # noqa: E402
from exp_harness import VIEWS, Bench  # noqa: E402

WORKERS = int(os.environ.get("FTF_EXP_WORKERS", "6"))
BASE_CACHE = Path(os.environ.get("FTF_EXP_BASE_CACHE", H.DATA_ROOT / "data" / "harvest" / "exp_cache"))
OLD_VIEWS = ("text", "ocr", "semantic", "html", "images")
STRUCTURE = ("html", "css", "js")


def bench(cache: Path, raw: bool) -> Bench:
    from ftf import config, lang

    H.CACHE = cache
    cache.mkdir(parents=True, exist_ok=True)
    for name in ("cases.pkl", "refs.npz"):                      # references do not depend on the product
        if not (cache / name).exists():
            (cache / name).write_bytes((BASE_CACHE / name).read_bytes())
    differ, groups = lang.differ, dict(config.IDENTIFIER_GROUP)
    if raw:
        lang.differ = lambda a, b: False
        config.IDENTIFIER_GROUP.pop("cert_batch", None)
    try:
        return Bench(workers=WORKERS, verbose=False)
    finally:
        lang.differ = differ
        config.IDENTIFIER_GROUP.clear()
        config.IDENTIFIER_GROUP.update(groups)


def gower(stack: list[np.ndarray], min_views: int = 1) -> np.ndarray:
    V = np.stack(stack)
    k = (~np.isnan(V)).sum(0)
    return np.where(k >= min_views, 1.0 - np.nansum(V, 0) / np.maximum(k, 1), 1.0)


def grouped(b: Bench, label: str, d: np.ndarray, must: np.ndarray, cut: float = 0.6) -> tuple[dict, np.ndarray]:
    d = np.clip(np.fmin(d, d.T), 0.0, 1.0)
    lab = b.cluster(d, must | must.T, cut=cut)
    M = (lab[:, None] == lab[None, :]) & b.iu
    sizes = sorted(Counter(lab).values(), reverse=True)
    return {"label": label, "largest": sizes[0], "groups": sum(1 for s in sizes if s >= 2),
            "singletons": sum(1 for s in sizes if s == 1), **b.score(M)}, M


def main() -> None:
    from ftf import lang
    from ftf.store import Store

    cache = Path(os.environ.get("FTF_EXP_CACHE", H.DATA_ROOT / "data" / "harvest" / "exp_cache_signals"))
    raw = bench(cache / "raw", raw=True)
    prod = bench(cache / "product", raw=False)
    z = np.load(BASE_CACHE / "product.npz")
    old = Bench.cluster(z["d"], z["ML"])
    OLD = (old[:, None] == old[None, :]) & raw.iu
    for b in (raw, prod):                                        # "new" = not grouped before the integration
        b.CAMP, b.HARD = OLD, b.REF2 & ~OLD & ~b.KIT6
    b = raw
    v = {name: raw.views[k] for k, name in enumerate(VIEWS)}

    by_name = {n: i for i, n in enumerate(b.names)}
    page_lang, creative_lang, cert = ["und"] * b.N, ["und"] * b.N, [set() for _ in range(b.N)]
    have = {name: np.zeros(b.N, bool) for name in ("css", "js", "html")}
    for f, vec in Store(H.STORE).all().values():
        i = by_name.get(f.get("name"))
        if i is None:
            continue
        t = f.get("text") or {}
        page_lang[i] = t.get("lang") or "und"
        creative_lang[i] = t.get("lang_ocr") if (t.get("lang_ocr") or "und") != "und" else page_lang[i]
        cert[i] = set((f.get("indicators") or {}).get("cert_batch", []))
        for name, kind in (("css", "css"), ("js", "js"), ("html", "dom")):
            have[name][i] = vec.get(kind) is not None and len(vec[kind]) > 0
    differ = lambda langs: np.array([[lang.differ(x, y) for y in langs] for x in langs])   # noqa: E731
    XL_page, XL_creative = differ(page_lang), differ(creative_lang)
    CERT = np.zeros((b.N, b.N), bool)
    inv = defaultdict(list)
    for i, s in enumerate(cert):
        for val in s:
            inv[val].append(i)
    for members in inv.values():
        CERT[np.ix_(members, members)] = True
    CERT &= b.iu
    print(f"pages: {b.N} | html {int(have['html'].sum())}, css {int(have['css'].sum())}, js {int(have['js'].sum())} | "
          f"language known {sum(x != 'und' for x in page_lang)} | certificate batch value {sum(bool(s) for s in cert)}, "
          f"pairs sharing one {int(CERT.sum())} | cross-language pairs {int((XL_page & b.iu).sum())}")

    out: dict = {"auc": {}}
    for name in VIEWS:
        out["auc"][name] = {**b.auc(v[name], ok=None), "available": round(float((~np.isnan(v[name]))[b.iu].mean()), 3)}
        print(f"view {name:<9}", out["auc"][name])
    rows = [{"label": "before: old code, old store", "largest": int(max(Counter(old).values())),
             "groups": sum(1 for s in Counter(old).values() if s >= 2), "singletons": sum(1 for s in Counter(old).values() if s == 1),
             **b.score(OLD)}]
    ruled = {**v, "text": np.where(XL_page, np.nan, v["text"]), "ocr": np.where(XL_creative, np.nan, v["ocr"])}
    five = [v[n] for n in OLD_VIEWS]
    ML = raw.ML
    for label, d, must in (
            ("re-analysed (parse fix), 5 views", gower(five), ML),
            ("  + css view", gower(five + [v["css"]]), ML),
            ("  + js view", gower(five + [v["js"]]), ML),
            ("  + css + js views", gower(five + [v["css"], v["js"]]), ML),
            ("  + language rule", gower([ruled[n] for n in OLD_VIEWS]), ML),
            ("  + certificate batch", gower(five), ML | CERT),
            ("all changes (from raw matrices)", gower([ruled[n] for n in VIEWS]), ML | CERT)):
        rows.append(grouped(b, label, d, must)[0])
    r, M_prod = grouped(prod, "all changes (product code path)", prod.d, prod.ML)
    rows.append(r)
    _, M_all = grouped(b, "", gower([ruled[n] for n in VIEWS]), ML | CERT)
    print(f"\nproduct code path vs sum of changes: {int((M_prod ^ M_all).sum())} pairs differ")
    print(b.table(rows, width=36))

    # ---- fusion on top of everything: is a structure group worth it, and at which cut?
    d_all = gower([ruled[n] for n in VIEWS])
    one_slot = gower([ruled[n] for n in ("text", "ocr", "semantic", "images")] + [1.0 - gower([v[n] for n in STRUCTURE])
                     + np.where(np.isnan(np.stack([v[n] for n in STRUCTURE])).all(0), np.nan, 0.0)])
    fus = [grouped(b, "all changes", d_all, ML | CERT)[0],
           grouped(b, "structure views as one slot", one_slot, ML | CERT)[0]]
    for names in (("html", "css"), STRUCTURE):
        for need in (2, 3) if len(names) == 3 else (2,):
            for cut in (0.6, 0.5, 0.4):
                ds = gower([v[n] for n in names], need)
                d = np.minimum(d_all, np.where(ds <= cut, ds * 0.6 / cut, 1.0)) if cut != 0.6 else np.minimum(d_all, ds)
                fus.append(grouped(b, f"min(all, {'+'.join(names)} >= {need} views), structure cut {cut}", d, ML | CERT)[0])
    print("\nSTRUCTURE GROUP on top of all changes (campaign cut stays 0.6; a structure distance above its own cut is ignored)")
    print(b.table(fus, width=58))
    ex = b.examples(M_all, 12)
    print("\nEXAMPLES: grouped after the integration, not before")
    print("\n".join(ex))
    print("\nEXAMPLES: the same, presumed-unrelated pairs")
    print("\n".join(b.examples(M_all & b.NEG_L, 12)))
    Bench.save("integration", {"rows": rows, "fusion": fus, **out})


if __name__ == "__main__":
    main()
