#!/usr/bin/env python
"""Experiment: an image match that survives cropping, rescaling and recompression.

pHash (the product's `images` view) hashes the DCT of the whole picture, so an 8 % crop changes it completely.
This script measures three candidates on the same images:

  orb      ORB keypoints + ratio test + RANSAC affine fit; inlier count and how much of the images the inliers
           span (ftf.vision.local_match_detail)
  sift     SIFT keypoints, ratio test + RANSAC (reference: 128 float descriptors instead of 32 bytes)
  cphash   pHash of four concentric centre crops (100 / 84 / 70 / 58 %), any-to-any within Hamming <= 4

Parts (each merges its numbers into research/experiments/crop-robust-images.json):
  a      organiser creatives: every creative vs seven transformed copies of itself (true pairs) and vs transformed
         copies of creatives from other labelled campaigns (different pairs)
  b      urlscan corpus: ~300 page screenshots, at most 8 per kit family; presumed-unrelated pairs (NEG), pairs with
         near-identical screenshots, same-kit pairs whose screenshots differ; effect on the product grouping
  rules  grid over (minimum inliers, minimum extent) from the per-pair values saved by a and b with --raw
  ocr    word 4-gram vs character 5-gram shingles for the `ocr` view: organiser recompressed variants, and the
         corpus when FTF_ROOT is set
  cost   wall time of all links of the stored organiser materials with and without the keypoint test
  gate   how many corpus pairs need the keypoint test if it runs only where it can change the campaign decision

    # a, cost and the organiser half of ocr: in a checkout whose data/ holds the organiser set and store
    .venv/bin/python tools/exp_crop_robust_images.py --part a --raw /tmp/raw_a.npz
    # b, rules, gate and the corpus half of ocr: FTF_ROOT = checkout with data/harvest (corpus, harness cache)
    FTF_ROOT=<checkout> .venv/bin/python tools/exp_crop_robust_images.py --part b --workers 8 --raw /tmp/raw_b.npz
    FTF_ROOT=<checkout> .venv/bin/python tools/exp_crop_robust_images.py --part rules --raw-a /tmp/raw_a.npz --raw-b /tmp/raw_b.npz
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import imagehash
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "research" / "experiments" / "crop-robust-images.json"
cv2.setNumThreads(2)


# ------------------------------------------------------------------------------------------ transforms
def _jpeg(im: Image.Image, q: int) -> Image.Image:
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=q)
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")


def _crop(im, l, t, r, b):
    w, h = im.size
    return im.crop((int(w * l), int(h * t), int(w * (1 - r)), int(h * (1 - b))))


def _scale(im, fx, fy=None):
    return im.resize((max(8, int(im.width * fx)), max(8, int(im.height * (fy or fx)))))


def t_eval(im):          # the transform of tools/evaluate.py ("recompressed")
    return _jpeg(_scale(_crop(im, .08, .08, .08, .08), .6), 55)


def t_harsh(im):
    return _jpeg(_scale(_crop(im, .2, .2, .2, .2), .4), 35)


def t_asym(im):
    return _jpeg(_scale(_crop(im, .15, .05, 0, .25), .7), 60)


def t_overlay(im):
    im = _scale(im.copy(), .8)
    d = ImageDraw.Draw(im)
    w, h = im.size
    d.rectangle([0, int(h * .85), w, h], fill=(20, 20, 120))
    d.text((int(w * .05), int(h * .9)), "KLIKNIJ TUTAJ  >>>  OFERTA TYLKO DZIS", fill=(255, 255, 0))
    d.ellipse([int(w * .8), int(h * .03), int(w * .97), int(h * .03) + int(w * .17)], fill=(220, 30, 30))
    return _jpeg(im, 70)


def t_aspect(im):
    return _jpeg(_scale(im, .8, .6), 60)


def t_embed(im):
    """The same creative shown inside a different, larger frame (another feed / another device)."""
    small = _scale(im, .55)
    W, H = int(small.width * 1.5), int(small.height * 1.7)
    rng = np.random.default_rng(int(np.asarray(small.convert("L")).sum()) % (2 ** 32))   # a different frame per picture
    canvas = Image.fromarray((rng.integers(225, 255, (H, W, 1)) * np.ones((1, 1, 3))).astype(np.uint8))
    d = ImageDraw.Draw(canvas)
    for y in range(10, int(H * .2), 22):
        d.rectangle([20, y, int(W * rng.uniform(.4, .9)), y + 10], fill=(90, 90, 90))
    canvas.paste(small, (int(W * .25), int(H * .22)))
    return _jpeg(canvas, 65)


def t_tone(im):
    a = np.asarray(im.convert("RGB"), np.float32) / 255.0
    a = np.clip((a ** 1.25) * 1.1 + 0.03, 0, 1)
    return _jpeg(Image.fromarray((cv2.GaussianBlur(a, (0, 0), 1.0) * 255).astype(np.uint8)), 45)


TRANSFORMS = {"eval_crop8_x0.6_q55": t_eval, "crop20_x0.4_q35": t_harsh, "asym_crop_x0.7_q60": t_asym,
              "overlay_band_logo": t_overlay, "aspect_0.8x0.6": t_aspect, "embedded_in_other_frame": t_embed,
              "tone_blur_q45": t_tone}


# ------------------------------------------------------------------------------------------ matchers
def sift_desc(im: Image.Image, max_side: int = 640, n: int = 800):
    g = np.asarray(im.convert("L"))
    s = max_side / max(g.shape)
    if s < 1:
        g = cv2.resize(g, (max(8, int(g.shape[1] * s)), max(8, int(g.shape[0] * s))), interpolation=cv2.INTER_AREA)
    kp, des = cv2.SIFT_create(nfeatures=n).detectAndCompute(g, None)
    if des is None:
        return np.zeros((0, 2), np.float32), np.zeros((0, 128), np.float32)
    return np.float32([k.pt for k in kp]), des


def sift_match(a, b, ratio: float = 0.75) -> int:
    (pa, da), (pb, db) = a, b
    if len(da) < 8 or len(db) < 8:
        return 0
    m = cv2.BFMatcher(cv2.NORM_L2).knnMatch(da, db, k=2)
    good = [x[0] for x in m if len(x) == 2 and x[0].distance < ratio * x[1].distance]
    if len(good) < 6:
        return 0
    src, dst = np.float32([pa[g.queryIdx] for g in good]), np.float32([pb[g.trainIdx] for g in good])
    _, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=4.0)
    return int(inl.sum()) if inl is not None else 0


def cphash(im: Image.Image) -> list[int]:
    out = []
    for f in (1.0, .84, .70, .58):
        w, h = im.size
        c = im.crop((int(w * (1 - f) / 2), int(h * (1 - f) / 2), int(w * (1 + f) / 2), int(h * (1 + f) / 2)))
        out.append(int(str(imagehash.phash(c)), 16))
    return out


def cphash_match(a: list[int], b: list[int]) -> int:
    """Smallest Hamming distance between any two centre-crop hashes."""
    return min(bin(x ^ y).count("1") for x in a for y in b)


def summarise(vals) -> dict:
    v = np.asarray(sorted(vals), dtype=float)
    if not len(v):
        return {"n": 0}
    q = lambda p: float(np.quantile(v, p))  # noqa: E731
    return {"n": int(len(v)), "min": float(v[0]), "p05": q(.05), "p25": q(.25), "median": q(.5), "p75": q(.75),
            "p95": q(.95), "p99": q(.99), "max": float(v[-1])}


# ------------------------------------------------------------------------------------------ decision rules
RULES = [(15, 0, 0), (20, 0, 0), (25, 0, 0), (30, 0, 0), (40, 0, 0), (60, 0, 0), (25, .25, 0), (25, .375, 0), (40, .375, 0),
         (25, 0, .05), (25, 0, .1), (25, 0, .15), (25, 0, .2), (25, 0, .3), (30, 0, .1), (30, 0, .15), (40, 0, .1), (40, 0, .15), (40, 0, .2)]
RAW: dict[str, list] = {}       # group -> (inliers, grid coverage, extent) per pair, saved next to the JSON for re-analysis


def rule_name(inl: int, cov: float, ext: float = 0) -> str:
    return f"inl>={inl}" + (f",cover>={cov:g}" if cov else "") + (f",extent>={ext:g}" if ext else "")


def rates(pairs: list[tuple[int, float, float]]) -> dict:
    """pairs: (inliers, grid coverage, extent) -> share accepted under each rule."""
    if not pairs:
        return {}
    a = np.array(pairs, dtype=float)
    return {rule_name(i, c, e): round(float(((a[:, 0] >= i) & (a[:, 1] >= c) & (a[:, 2] >= e)).mean()), 5) for i, c, e in RULES}


def orb_pair(a, b) -> tuple[int, float, float]:
    from ftf import vision

    d = vision.local_match_detail(a, b)
    return d["inliers"], max(d["cover_a"], d["cover_b"]), max(d["extent_a"], d["extent_b"])


# ------------------------------------------------------------------------------------------ part A
def part_a(keypoints: int) -> dict:
    from ftf import vision
    from ftf.store import Store

    labels = {}
    for line in (ROOT / "data" / "labels_dane.csv").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            k, v = line.split(",")
            labels[k.strip()] = v.strip()
    imgs = []                                  # (case, label, kind, path)
    for f, _ in Store().all().values():
        if f.get("source") != "organizer":
            continue
        for im in f.get("images", []):
            if im.get("kind") == "ui_screenshot":
                continue
            p = Path(im["src"]) if Path(im["src"]).is_absolute() else ROOT / im["src"]
            if p.exists():
                imgs.append((f["name"], labels.get(f["name"], "?"), im["kind"], p))
    print(f"organiser creatives: {len(imgs)} images from {len({c for c, *_ in imgs})} cases "
          f"({Counter(k for _, _, k, _ in imgs).most_common()}), {keypoints} keypoints")
    desc = lambda im: vision.local_descriptors(im, n=keypoints)  # noqa: E731

    orig, t_desc = [], 0.0
    for case, lab, kind, p in imgs:
        im = vision.load_rgb(p)
        c = vision.creative_view(im, kind)
        t0 = time.time()
        d = desc(c)
        t_desc += time.time() - t0
        orig.append({"case": case, "label": lab, "kind": kind, "file": p.name, "im": im, "orb": d, "sift": sift_desc(c),
                     "cph": cphash(c), "ph": int(str(imagehash.phash(c)), 16)})
    res: dict = {"n_images": len(imgs), "keypoints_requested": keypoints, "descriptor_ms": round(1000 * t_desc / max(len(imgs), 1), 1),
                 "descriptor_bytes": int(np.mean([o["orb"][0].nbytes + o["orb"][1].nbytes for o in orig])),
                 "keypoints_mean": float(np.mean([len(o["orb"][1]) for o in orig])), "transforms": {}}

    # different pictures as they are (no transform)
    plain_diff, plain_same_case = [], []
    for i, o in enumerate(orig):
        for j in range(i + 1, len(orig)):
            x = orb_pair(o["orb"], orig[j]["orb"])
            if o["case"] == orig[j]["case"]:
                plain_same_case.append(x)
            elif o["label"] != orig[j]["label"]:
                plain_diff.append(x)
    res["untransformed"] = {"different_campaign": {"n": len(plain_diff), "inliers": summarise([x[0] for x in plain_diff]), "accepted": rates(plain_diff)},
                            "same_case_other_image": {"n": len(plain_same_case), "inliers": summarise([x[0] for x in plain_same_case]),
                                                      "accepted": rates(plain_same_case)}}
    RAW["a_plain_diff"], RAW["a_plain_same_case"] = plain_diff, plain_same_case
    print(f"  untransformed, different campaign n={len(plain_diff)}: max inliers {max(x[0] for x in plain_diff)}; "
          f"same case, other image n={len(plain_same_case)}: accepted {rates(plain_same_case)}")

    neg_all, sift_neg, cph_neg = [], [], []
    t_match, n_match = 0.0, 0
    for tname, tf in TRANSFORMS.items():
        var = []
        for o in orig:
            c = vision.creative_view(tf(o["im"]), o["kind"])
            var.append({"orb": desc(c), "sift": sift_desc(c), "cph": cphash(c), "ph": int(str(imagehash.phash(c)), 16)})
        true, neg, tops = [], [], []
        other = defaultdict(list)
        for i, o in enumerate(orig):
            for j, v in enumerate(var):
                same = i == j
                if not same and orig[j]["label"] == o["label"]:
                    continue                    # same campaign, different picture: neither a true nor a clean different pair
                t0 = time.time()
                x = orb_pair(o["orb"], v["orb"])
                t_match += time.time() - t0
                n_match += 1
                if same:
                    true.append(x)
                    other["sift"].append(sift_match(o["sift"], v["sift"]))
                    other["cphash"].append(cphash_match(o["cph"], v["cph"]))
                    other["phash"].append(bin(o["ph"] ^ v["ph"]).count("1"))
                else:
                    neg.append(x)
                    tops.append((x[0], round(x[1], 2), round(x[2], 2), f"{o['case']}/{o['file']}", f"{orig[j]['case']}/{orig[j]['file']}"))
                    cph_neg.append(cphash_match(o["cph"], v["cph"]))
                    if (i + j) % 7 == 0:
                        sift_neg.append(sift_match(o["sift"], v["sift"]))
        neg_all += neg
        RAW[f"a_true_{tname}"], RAW[f"a_diff_{tname}"] = true, neg
        tops.sort(reverse=True)
        res["transforms"][tname] = {
            "true": {"n": len(true), "inliers": summarise([x[0] for x in true]), "cover": summarise([x[1] for x in true]), "extent": summarise([x[2] for x in true]), "recall": rates(true),
                     "recall_sift>=25": round(float(np.mean(np.array(other["sift"]) >= 25)), 3),
                     "recall_cphash<=4": round(float(np.mean(np.array(other["cphash"]) <= 4)), 3),
                     "recall_phash<=4": round(float(np.mean(np.array(other["phash"]) <= 4)), 3)},
            "different_campaign": {"n": len(neg), "inliers": summarise([x[0] for x in neg]), "accepted": rates(neg), "top": tops[:5]}}
        r = res["transforms"][tname]
        print(f"  {tname:<26} true: inliers median {np.median([x[0] for x in true]):.0f} min {min(x[0] for x in true)} "
              f"extent p05 {np.quantile([x[2] for x in true], .05):.2f} | recall inl>=25 {r['true']['recall']['inl>=25']:.2f} "
              f"+extent>=.1 {r['true']['recall']['inl>=25,extent>=0.1']:.2f} +extent>=.2 {r['true']['recall']['inl>=25,extent>=0.2']:.2f} "
              f"sift {r['true']['recall_sift>=25']:.2f} cphash {r['true']['recall_cphash<=4']:.2f} phash {r['true']['recall_phash<=4']:.2f} "
              f"|| different: max {tops[0][:3]} {tops[0][3]} vs {tops[0][4]} accepted inl>=25 {r['different_campaign']['accepted']['inl>=25']:.4f} "
              f"+extent>=.1 {r['different_campaign']['accepted']['inl>=25,extent>=0.1']:.4f}")
    res["different_campaign_all_transforms"] = {"n": len(neg_all), "inliers": summarise([x[0] for x in neg_all]), "accepted": rates(neg_all),
                                                "sift>=25": round(float(np.mean(np.array(sift_neg) >= 25)), 5), "sift_n": len(sift_neg),
                                                "cphash<=4": round(float(np.mean(np.array(cph_neg) <= 4)), 5)}
    res["match_ms"] = round(1000 * t_match / max(n_match, 1), 2)
    print("  different campaign, all transforms:", res["different_campaign_all_transforms"]["accepted"],
          "| sift>=25", res["different_campaign_all_transforms"]["sift>=25"], "| cphash<=4", res["different_campaign_all_transforms"]["cphash<=4"])
    print(f"  descriptors {res['descriptor_ms']} ms / image, {res['descriptor_bytes']} bytes / image; match {res['match_ms']} ms / pair")
    return res


# ------------------------------------------------------------------------------------------ part B
_DESCS: list = []


def _shot(b, i: int) -> Path:
    """Screenshot of corpus page i; the cache may hold the absolute path of another machine."""
    from exp_harness import CORPUS

    p = Path(b.cases[i]["shot"])
    return p if p.exists() else CORPUS / b.names[i] / p.name


def _describe(args):
    from ftf import vision

    cv2.setNumThreads(1)
    path, keypoints = args
    im = vision.load_rgb(path)
    if im is None or np.asarray(im.convert("L")).std() < 8:
        return None
    return vision.local_descriptors(vision.creative_view(im, "screenshot"), n=keypoints)      # as the pipeline does


def _match_row(x: int):
    cv2.setNumThreads(1)
    t0 = time.time()
    row = [orb_pair(_DESCS[x], _DESCS[y]) for y in range(x + 1, len(_DESCS))]
    return x, row, time.time() - t0


def part_b(n_pages: int, keypoints: int, workers: int = 1) -> dict:
    from multiprocessing import get_context

    from exp_harness import Bench

    b = Bench(verbose=False)
    rng = np.random.default_rng(3)
    okshot = np.array([_shot(b, i).exists() for i in range(b.N)])
    has_vis = (b.VIS | b.VIS.T).any(1)
    per_fam = Counter()
    pick = []
    for i in rng.permutation(b.N):
        if not okshot[i]:
            continue
        fam = int(b.kitfam[i])
        if fam >= 0 and per_fam[fam] >= 8 and not (has_vis[i] and per_fam[fam] < 14):
            continue
        per_fam[fam] += 1
        pick.append(int(i))
        if len(pick) >= n_pages:
            break
    global _DESCS
    t0 = time.time()
    ctx = get_context("fork")
    with ctx.Pool(workers) as pool:
        got = pool.map(_describe, [(str(_shot(b, i)), keypoints) for i in pick], chunksize=4)
    keep = [i for i, d in zip(pick, got) if d is not None]
    _DESCS = [d for d in got if d is not None]
    t_desc = (time.time() - t0) * workers / max(len(keep), 1)
    idx = np.array(keep)
    n = len(idx)
    S = np.zeros((n, n), np.int32)
    C = np.zeros((n, n), np.float32)
    E = np.zeros((n, n), np.float32)
    t_cpu = 0.0
    with ctx.Pool(workers) as pool:               # forked after _DESCS is set
        for x, row, dt in pool.imap_unordered(_match_row, range(n), chunksize=2):
            t_cpu += dt
            for y, v in enumerate(row, start=x + 1):
                S[x, y], C[x, y], E[x, y] = v
    t_pair = t_cpu / max(n * (n - 1) / 2, 1)
    up = np.triu(np.ones((n, n), bool), 1)
    sub = lambda M: (M | M.T)[np.ix_(idx, idx)] & up  # noqa: E731
    groups = {"NEG (presumed unrelated)": sub(b.NEG), "NEG_L (no reference, different network)": sub(b.NEG_L),
              "no reference at all": sub(~b.POS & b.iu), "VIS (screenshots near-identical by pHash)": sub(b.VIS),
              "same kit family, pHash differs": sub(b.KITFAM & ~b.VIS), "REF2, pHash differs": sub(b.REF2 & ~b.VIS)}
    res = {"pages": n, "pairs": int(up.sum()), "keypoints_requested": keypoints, "descriptor_ms": round(1000 * t_desc, 1),
           "match_ms": round(1000 * t_pair, 2), "kit_families_covered": len({int(b.kitfam[i]) for i in keep}), "groups": {}}
    print(f"corpus screenshots: {n} pages, {int(up.sum())} pairs; match {res['match_ms']} ms / pair")
    for name, G in groups.items():
        pairs = list(zip(S[G].tolist(), C[G].tolist(), E[G].tolist()))
        RAW["b_" + name.split(" (")[0].replace(" ", "_").replace(",", "")] = pairs
        res["groups"][name] = {"pairs": len(pairs), "accepted": rates(pairs), "inliers": summarise([p[0] for p in pairs])}
        acc = res["groups"][name]["accepted"]
        print(f"  {name:<42} n={len(pairs):>6}  " + "  ".join(f"{k} {acc.get(k)}" for k in ("inl>=25", "inl>=25,extent>=0.1", "inl>=25,extent>=0.2", "inl>=40", "inl>=40,extent>=0.1")))
    RAW["b_matrix_inliers"], RAW["b_matrix_extent"], RAW["b_index"] = S, E, idx
    res["product_grouping_on_sample"] = product_effect(b, idx, S, E)
    hits = np.argwhere(sub(~b.POS & b.iu) & (S >= 25))
    order = np.argsort(-S[hits[:, 0], hits[:, 1]]) if len(hits) else []
    res["unreferenced_hits"] = []
    NEGs = b.NEG | b.NEG.T
    for k in order[:40]:
        x, y = hits[k]
        i, j = int(idx[x]), int(idx[y])
        res["unreferenced_hits"].append({"inliers": int(S[x, y]), "cover": round(float(C[x, y]), 2), "extent": round(float(E[x, y]), 2), "a": b.names[i], "title_a": b.cases[i]["title"][:60],
                                         "b": b.names[j], "title_b": b.cases[j]["title"][:60], "kit": round(float(b.KIT[i, j]), 2),
                                         "neg": bool(NEGs[i, j])})
        print(f"    no-reference hit {S[x, y]:>4} inl cover {C[x, y]:.2f} extent {E[x, y]:.2f} kit {b.KIT[i, j]:.2f} neg {bool(NEGs[i, j])} | {b.names[i][:28]:<28} {b.cases[i]['title'][:34]!r:<36} | "
              f"{b.names[j][:28]:<28} {b.cases[j]['title'][:34]!r}")
    return res


# ------------------------------------------------------------------------------------------ part OCR
def _word_shingles(t: str, k: int = 4) -> set:
    from ftf.text import tokens

    w = tokens(t)
    return {" ".join(w[i:i + k]) for i in range(len(w) - k + 1)}


def _char_shingles(t: str, k: int = 5) -> set:
    from ftf.text import normalize

    t = normalize(t)
    return {t[i:i + k] for i in range(len(t) - k + 1)}


def _jac(a: set, b: set) -> float | None:
    return len(a & b) / len(a | b) if a and b else None


def part_ocr() -> dict:
    """Would character n-gram shingles serve the `ocr` view better than word 4-grams when OCR runs on a small,
    recompressed copy? True pairs: organiser material vs the OCR of its recompressed variant
    (data/eval/variants/<case>/recompressed, written by tools/evaluate.py). Different pairs: organiser materials of
    different campaigns, and presumed-unrelated corpus pages (NEG)."""
    from ftf import vision
    from ftf.gazetteer import mask_entities
    from ftf.store import Store

    measures = {"word4": lambda t: _word_shingles(t, 4), "word2": lambda t: _word_shingles(t, 2), "char4": lambda t: _char_shingles(t, 4),
                "char5": lambda t: _char_shingles(t, 5)}
    if os.environ.get("FTF_ROOT"):
        return _ocr_corpus(measures)
    labels = {}
    for line in (ROOT / "data" / "labels_dane.csv").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            k, v = line.split(",")
            labels[k.strip()] = v.strip()
    org = {f["name"]: (f.get("text") or {}).get("ocr_text", "") for f, _ in Store().all().values() if f.get("source") == "organizer"}
    res: dict = {"true_pairs": {}, "measures": list(measures)}
    for d in sorted((ROOT / "data" / "eval" / "variants").glob("*/recompressed")):
        case = d.parent.name
        if case not in org:
            continue
        vt = " ".join(vision.ocr(vision.load_rgb(p))["text"] for p in sorted(d.iterdir()) if p.suffix.lower() in (".jpg", ".png"))
        a, b = mask_entities(org[case]), mask_entities(vt)
        res["true_pairs"][case] = {"chars_original": len(org[case]), "chars_variant": len(vt),
                                   **{m: (round(j, 3) if (j := _jac(fn(a), fn(b))) is not None else None) for m, fn in measures.items()}}
        print(f"  case {case:>3}: OCR chars {len(org[case]):>5} -> {len(vt):>5} | " + "  ".join(f"{m} {res['true_pairs'][case][m]}" for m in measures))
    diff = defaultdict(list)
    names = sorted(org)
    for i, x in enumerate(names):
        for y in names[i + 1:]:
            if labels.get(x) != labels.get(y):
                for m, fn in measures.items():
                    j = _jac(fn(mask_entities(org[x])), fn(mask_entities(org[y])))
                    if j is not None:
                        diff[m].append(j)
    res["organiser_different_campaign"] = {m: summarise(v) for m, v in diff.items()}
    print("  organiser, different campaigns:", {m: (round(float(np.max(v)), 3), round(float(np.mean(v)), 3)) for m, v in diff.items()}, "(max, mean)")

    return res


def _ocr_corpus(measures: dict) -> dict:
    """The same two measures on the OCR text of presumed-unrelated corpus pages (run with FTF_ROOT=<main checkout>)."""
    from datasketch import MinHash

    import sqlite3

    from exp_harness import STORE, Bench
    from ftf.gazetteer import mask_entities
    from ftf.text import tokens

    res: dict = {}

    b = Bench(verbose=False)
    by = {n: i for i, n in enumerate(b.names)}
    texts = [""] * b.N
    con = sqlite3.connect(f"file:{STORE}?mode=ro", uri=True)
    for name, feats in con.execute("SELECT name, features FROM materials"):
        if name in by:
            texts[by[name]] = mask_entities(((json.loads(feats).get("text") or {}).get("ocr_text") or "")[:4000])
    sig = {}
    for m in ("word4", "char5"):
        M = np.zeros((b.N, 128), np.uint64)
        ok = np.zeros(b.N, bool)
        for i, t in enumerate(texts):
            sh = measures[m](t)
            if len(tokens(t)) >= 6:                 # the product's rule: a text needs k + 2 = 6 words for a signature
                mh = MinHash(num_perm=128, seed=7)
                for x in sh:
                    mh.update(x.encode())
                M[i], ok[i] = mh.hashvalues, True
        J = np.zeros((b.N, b.N), np.float32)
        for i in range(b.N):
            J[i] = (M[i][None, :] == M).mean(1)
        J[~ok] = np.nan
        J[:, ~ok] = np.nan
        sig[m] = J
    res["corpus"] = {}
    NEG, POS2 = b.NEG | b.NEG.T, b.REF2 | b.REF2.T
    for m, J in sig.items():
        av = ~np.isnan(J)
        neg, pos = J[NEG & av], J[POS2 & av]
        res["corpus"][m] = {"neg_pairs": int(len(neg)), "neg_mean": round(float(neg.mean()), 4),
                            **{f"neg>={t}": round(float((neg >= t).mean()), 5) for t in (0.1, 0.2, 0.3, 0.5)},
                            "ref2_pairs": int(len(pos)), "ref2_mean": round(float(pos.mean()), 4),
                            **{f"ref2>={t}": round(float((pos >= t).mean()), 4) for t in (0.2, 0.5)}}
        print(f"  corpus {m}: ", res["corpus"][m])
    keys = ("largest", "groups", "singletons", "pairs", "prec", "fpr", "R_ref2", "new", "new_prec", "R_miss")
    res["corpus_product_grouping"] = {"product (stored ocr view)": {k: v for k, v in b.product_with().items() if k in keys}}
    for m, J in sig.items():
        r = b.product_with(replace={"ocr": J.astype(np.float32)}, label=m)
        res["corpus_product_grouping"][f"ocr view recomputed with {m}"] = {k: v for k, v in r.items() if k in keys}
    for k, v in res["corpus_product_grouping"].items():
        print(f"  product grouping, {k}: {v}")
    return res


def part_rules(raw_a: str, raw_b: str) -> dict:
    """Grid over (minimum inliers, minimum extent) on the per-pair values saved by parts a and b (--raw):
    recall on transformed organiser creatives, false accepts on different-campaign creatives and on corpus
    screenshots, and the effect on the product grouping of the corpus sample."""
    from exp_harness import Bench

    za, zb = np.load(raw_a), np.load(raw_b)
    T = [k[len("a_true_"):] for k in za.files if k.startswith("a_true_")]
    diff = np.concatenate([za["a_diff_" + t] for t in T])
    b = Bench(verbose=False)
    grid = [(i, e) for i in (20, 25, 30, 40, 50, 60) for e in (0, .02, .03, .05, .08, .1)]
    eff = product_effect(b, zb["b_index"], zb["b_matrix_inliers"], zb["b_matrix_extent"], grid, quiet=True)
    out = {"transforms": T, "rows": []}
    print("  rule".ljust(24) + "recall per transform".ljust(8 * len(T)) + " creat_FP  NEG      no_ref   samekit  | grouping: new POS NEG lost  NEG_total REF2_recall")
    for i, e in grid:
        ok = lambda a: (a[:, 0] >= i) & (a[:, 2] >= e)  # noqa: E731
        g = eff[rule_name(i, 0, e)]
        row = {"min_inliers": i, "min_extent": e, "recall": {t: round(float(ok(za["a_true_" + t]).mean()), 3) for t in T},
               "creatives_false_accepts": int(ok(diff).sum()), "creatives_different_pairs": int(len(diff)),
               "corpus_NEG_rate": round(float(ok(zb["b_NEG"]).mean()), 5), "corpus_NEG_accepts": int(ok(zb["b_NEG"]).sum()),
               "corpus_no_reference_accepts": int(ok(zb["b_no_reference_at_all"]).sum()),
               "corpus_same_kit_phash_differs_rate": round(float(ok(zb["b_same_kit_family_pHash_differs"]).mean()), 3), "grouping": g}
        out["rows"].append(row)
        print(f"  {rule_name(i, 0, e):<22}" + "".join(f"{row['recall'][t]:<8.2f}" for t in T)
              + f" {row['creatives_false_accepts']:<9} {row['corpus_NEG_accepts']:<8} {row['corpus_no_reference_accepts']:<8} "
                f"{row['corpus_same_kit_phash_differs_rate']:<8} | {g['new_pairs']:>4} {g['new_in_POS']:>4} {g['new_in_NEG']:>3} {g['lost_pairs']:>4} "
                f"{g['in_NEG']:>6} {g['REF2_recall']:>8}")
    out["pairs"] = {"corpus_NEG": int(len(zb["b_NEG"])), "corpus_no_reference": int(len(zb["b_no_reference_at_all"])),
                    "grouping_baseline": eff["baseline"]}
    return out


def part_cost() -> dict:
    """Wall time of all pairwise links of the stored organiser materials with and without the keypoint test, and
    which material pairs it changes. Run in a checkout whose data/store holds the organiser materials."""
    from ftf import config, similarity
    from ftf.store import Store

    items = {k: v for k, v in Store().all().items() if v[0].get("source") == "organizer"}
    res: dict = {"materials": len(items), "creative_images": sum(len(similarity.local_features(f, v)) for f, v in items.values())}
    for on in (False, True):
        config.LOCAL_MATCH = on
        similarity._LOCAL_PAIRS.clear()
        similarity._local_from_file.cache_clear()
        t0 = time.time()
        links = similarity.all_links(items)
        cold = time.time() - t0
        t0 = time.time()
        similarity.all_links(items)
        res["keypoints_on" if on else "phash_only"] = {
            "seconds_cold": round(cold, 2), "seconds_warm": round(time.time() - t0, 3), "material_pairs": len(links),
            "image_pairs_verified": len(similarity._LOCAL_PAIRS),
            "links_changed": [{"a": items[l.a][0]["name"], "b": items[l.b][0]["name"], "images": round(l.views.get("images", 0), 3),
                               "matched_by_keypoints": l.local_images, "distance": round(l.distance, 3), "relation": l.relation}
                              for l in links if l.local_images]}
        print(f"  {'keypoints on' if on else 'pHash only':<13} {res['keypoints_on' if on else 'phash_only']}")
    return res


def part_gate() -> dict:
    """How many corpus pairs would need the keypoint test, and how many remain if it is run only where a full image
    match could bring the pair within the campaign cut (d <= 0.6 with images = 1)."""
    from exp_harness import Bench

    b = Bench(verbose=False)
    V = np.asarray(b.views, dtype=np.float64)
    up = np.triu(np.ones((b.N, b.N), bool), 1)
    k = (~np.isnan(V)).sum(0)
    img = V[4]
    cand = up & ~np.isnan(img) & (img < 1.0)
    d_best = 1.0 - (np.nansum(V, 0) - np.where(np.isnan(img), 0.0, img) + 1.0) / np.maximum(k, 1)
    gate = cand & (d_best <= 0.6) & (b.d > 0.6) & ~(b.ML | b.ML.T)
    res = {"pages": int(b.N), "pairs": int(up.sum()), "pairs_with_images_on_both_sides_and_no_full_phash_match": int(cand.sum()),
           "pairs_where_a_full_image_match_would_cross_the_campaign_cut": int(gate.sum()),
           "of_those_images_is_the_only_view": int((gate & (k == 1)).sum()),
           "of_those_with_another_view_above_zero": int((gate & (np.nansum(V, 0) - np.where(np.isnan(img), 0.0, img) > 0)).sum())}
    print(" ", res)
    return res


def product_effect(b, idx: np.ndarray, S: np.ndarray, E: np.ndarray, rules=((25, 0), (25, .05), (40, 0), (40, .05), (60, 0)),
                   quiet: bool = False) -> dict:
    """The product grouping (must-link + Gower mean + average linkage, cut 0.6) on the sampled pages, before and after
    the `images` view of every screenshot pair that passes the keypoint rule is set to 1.0. This is an upper bound of the
    effect: in the product a pair of image sets scores hits / |smaller set|."""
    ix = np.ix_(idx, idx)
    V = np.stack([b.views[k][ix] for k in range(b.views.shape[0])]).astype(np.float64)
    must = b.ML[ix]
    up = np.triu(np.ones((len(idx), len(idx)), bool), 1)
    POS, NEG, REF2 = (((M | M.T)[ix]) & up for M in (b.POS, b.NEG, b.REF2))

    def group(V):
        k = (~np.isnan(V)).sum(0)
        d = np.where(k > 0, 1.0 - np.nansum(V, 0) / np.maximum(k, 1), 1.0)
        lab = b.cluster(d, must)
        return (lab[:, None] == lab[None, :]) & up, max(Counter(lab.tolist()).values()), d

    base, largest0, d0 = group(V)
    out = {"baseline": {"same_campaign_pairs": int(base.sum()), "largest_campaign": int(largest0), "in_POS": int((base & POS).sum()),
                        "in_NEG": int((base & NEG).sum()), "REF2_recall": round(float((base & REF2).sum() / max(REF2.sum(), 1)), 4)}}
    print(f"  product grouping on the sample: baseline {out['baseline']}")
    for inl, ext in rules:
        H = (S >= inl) & (E >= ext)
        H = H | H.T
        W = V.copy()
        changed = H & ~(W[4] >= 1.0)
        W[4] = np.where(H, 1.0, W[4])
        M, largest, d1 = group(W)
        new = M & ~base
        out[rule_name(inl, 0, ext)] = {
            "screenshot_pairs_passing": int((H & up).sum()), "pairs_whose_images_view_rises": int((changed & up).sum()),
            "pairs_moved_below_cut": int(((d1 <= 0.6) & (d0 > 0.6) & up).sum()),
            "same_campaign_pairs": int(M.sum()), "largest_campaign": int(largest), "new_pairs": int(new.sum()),
            "new_in_POS": int((new & POS).sum()), "new_in_NEG": int((new & NEG).sum()), "lost_pairs": int((base & ~M).sum()),
            "in_NEG": int((M & NEG).sum()), "REF2_recall": round(float((M & REF2).sum() / max(REF2.sum(), 1)), 4)}
        if not quiet:
            print(f"    {rule_name(inl, 0, ext):<22} {out[rule_name(inl, 0, ext)]}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", default="a", choices=["a", "b", "ocr", "rules", "cost", "gate"])
    ap.add_argument("--raw-a", default="", help="part rules: the .npz written by --part a --raw")
    ap.add_argument("--raw-b", default="", help="part rules: the .npz written by --part b --raw")
    ap.add_argument("--pages", type=int, default=300)
    ap.add_argument("--workers", type=int, default=1, help="processes for part b")
    ap.add_argument("--raw", default="", help="optional .npz path for the per-pair (inliers, coverage, extent) values")
    ap.add_argument("--keypoints", type=int, default=0, help="ORB keypoints per image (default: config.LOCAL_KEYPOINTS)")
    a = ap.parse_args()
    from ftf import config

    kp = a.keypoints or config.LOCAL_KEYPOINTS
    if a.part == "ocr":
        key, val = "ocr_shingles", part_ocr()
    elif a.part == "rules":
        key, val = "rule_grid", part_rules(a.raw_a, a.raw_b)
    elif a.part == "cost":
        key, val = "cost_organiser_store", part_cost()
    elif a.part == "gate":
        key, val = "corpus_candidate_gate", part_gate()
    else:
        key = ("organiser_creatives" if a.part == "a" else "corpus_screenshots") + ("" if kp == config.LOCAL_KEYPOINTS else f"_{kp}kp")
        val = part_a(kp) if a.part == "a" else part_b(a.pages, kp, a.workers)
    report = json.loads(OUT.read_text()) if OUT.exists() else {}      # read late: parts may run side by side
    report[key] = {**report.get(key, {}), **val} if key == "ocr_shingles" else val
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    if RAW and a.raw:
        np.savez_compressed(a.raw, **{k: (np.asarray(v) if "matrix" in k or k == "b_index" else np.array(v, dtype=np.float32).reshape(-1, 3))
                                      for k, v in RAW.items()})
    print("written", OUT)
