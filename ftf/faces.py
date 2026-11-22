"""Face detection (SCRFD det_10g) + ArcFace (w600k_r50) embeddings + reference gallery matching.

Implemented directly on onnxruntime (no `insightface` package / Cython build needed).
Model weights: InsightFace buffalo_l — non-commercial research licence (fine for the hackathon POC).
A face is used when the SCRFD detector score >= config.FACE_DET_THRESHOLD (Guo et al. 2021) and its side
>= config.FACE_MIN_SIDE px; it is named when the ArcFace cosine (Deng et al. 2019) to the nearest reference
identity >= config.FACE_MATCH_THRESHOLD. Persons are descriptive only (never used for linking).
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image

from . import config
from .vision import _session

log = logging.getLogger(__name__)

ARC_TEMPLATE = np.array(
    [[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
     [41.5493, 92.3655], [70.7299, 92.2041]],
    dtype=np.float32,
)


def _umeyama_2d(src: np.ndarray, dst: np.ndarray) -> np.ndarray | None:
    """Closed-form deterministic 2D similarity transform (Umeyama 1991) mapping src (N,2) -> dst (N,2).

    Returns a (2, 3) float32 affine matrix for cv2.warpAffine, or None if degenerate.
    """
    src = np.asarray(src, dtype=np.float64)
    dst = np.asarray(dst, dtype=np.float64)
    n = src.shape[0]
    if n < 2 or src.shape != dst.shape:
        return None
    src_mean = src.mean(axis=0)
    dst_mean = dst.mean(axis=0)
    src_demean = src - src_mean
    dst_demean = dst - dst_mean
    var_src = float(np.sum(src_demean ** 2) / n)
    if var_src < 1e-12:
        return None
    cov = (dst_demean.T @ src_demean) / n
    U, S, Vt = np.linalg.svd(cov)
    d = np.ones(2, dtype=np.float64)
    if np.linalg.det(cov) < 0:
        d[1] = -1.0
    R = U @ np.diag(d) @ Vt
    if np.linalg.det(R) < 0:
        d[1] *= -1.0
        R = U @ np.diag(d) @ Vt
    scale = float(np.sum(S * d) / var_src)
    t = dst_mean - scale * (R @ src_mean)
    return np.hstack([scale * R, t[:, None]]).astype(np.float32)


def _distance2bbox(points, distance):
    return np.stack([
        points[:, 0] - distance[:, 0], points[:, 1] - distance[:, 1],
        points[:, 0] + distance[:, 2], points[:, 1] + distance[:, 3],
    ], axis=-1)


def _distance2kps(points, distance):
    preds = []
    for i in range(0, distance.shape[1], 2):
        preds.append(points[:, i % 2] + distance[:, i])
        preds.append(points[:, i % 2 + 1] + distance[:, i + 1])
    return np.stack(preds, axis=-1)


def _nms(dets, thresh=0.4):
    x1, y1, x2, y2, scores = dets[:, 0], dets[:, 1], dets[:, 2], dets[:, 3], dets[:, 4]
    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        xx1, yy1 = np.maximum(x1[i], x1[order[1:]]), np.maximum(y1[i], y1[order[1:]])
        xx2, yy2 = np.minimum(x2[i], x2[order[1:]]), np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0.0, xx2 - xx1 + 1) * np.maximum(0.0, yy2 - yy1 + 1)
        ovr = inter / (areas[i] + areas[order[1:]] - inter)
        order = order[np.where(ovr <= thresh)[0] + 1]
    return keep


def detect(img_bgr: np.ndarray, thresh: float = config.FACE_DET_THRESHOLD, size: int = 640):
    p = config.MODELS / "faces" / "det_10g.onnx"
    if not p.exists():
        return []
    sess = _session(str(p))
    h, w = img_bgr.shape[:2]
    scale = size / max(h, w)
    nh, nw = int(h * scale), int(w * scale)
    det_img = np.zeros((size, size, 3), np.uint8)
    det_img[:nh, :nw] = cv2.resize(img_bgr, (nw, nh))
    blob = cv2.dnn.blobFromImage(det_img, 1.0 / 128, (size, size), (127.5, 127.5, 127.5), swapRB=True)
    outs = sess.run(None, {sess.get_inputs()[0].name: blob})
    scores_l, boxes_l, kps_l = [], [], []
    for idx, stride in enumerate((8, 16, 32)):
        scores, bbox, kps = outs[idx][:, 0], outs[idx + 3] * stride, outs[idx + 6] * stride
        fh = fw = size // stride
        centers = np.stack(np.mgrid[:fh, :fw][::-1], axis=-1).astype(np.float32)
        centers = (centers * stride).reshape(-1, 2)
        centers = np.stack([centers] * 2, axis=1).reshape(-1, 2)
        pos = np.where(scores >= thresh)[0]
        if pos.size == 0:
            continue
        scores_l.append(scores[pos])
        boxes_l.append(_distance2bbox(centers, bbox)[pos])
        kps_l.append(_distance2kps(centers, kps).reshape(-1, 5, 2)[pos])
    if not scores_l:
        return []
    scores = np.concatenate(scores_l)
    boxes = np.concatenate(boxes_l) / scale
    kpss = np.concatenate(kps_l) / scale
    dets = np.hstack([boxes, scores[:, None]]).astype(np.float32)
    keep = _nms(dets)
    return [(dets[i, :4], float(dets[i, 4]), kpss[i]) for i in keep]


def embed(img_bgr: np.ndarray, kps: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    p = config.MODELS / "faces" / "w600k_r50.onnx"
    if not p.exists():
        return None
    M = _umeyama_2d(kps.astype(np.float32), ARC_TEMPLATE)
    if M is None:
        return None
    crop = cv2.warpAffine(img_bgr, M, (112, 112), borderValue=0.0)
    blob = cv2.dnn.blobFromImage(crop, 1.0 / 127.5, (112, 112), (127.5, 127.5, 127.5), swapRB=True)
    sess = _session(str(p))
    v = sess.run(None, {sess.get_inputs()[0].name: blob})[0][0]
    return (v / (np.linalg.norm(v) + 1e-9)).astype(np.float32), crop


def faces_in_image(im: Image.Image, min_side: int = config.FACE_MIN_SIDE) -> list[dict]:
    bgr = cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)
    H, W = bgr.shape[:2]
    out = []
    for box, score, kps in detect(bgr):
        x0, y0, x1, y1 = box
        side = min(x1 - x0, y1 - y0)
        if side < min_side:
            continue
        r = embed(bgr, kps)
        if r is None:
            continue
        vec, crop = r
        out.append({
            "box": [float(v) for v in box],
            "box_rel": [float(x0 / W), float(y0 / H), float(x1 / W), float(y1 / H)],
            "det_score": round(score, 3),
            "side": round(float(side), 1),
            "embedding": vec,
            "crop": crop,
        })
    return out


# ----------------------------------------------------------------------------- reference gallery
def shipped_gallery() -> tuple[list[str], np.ndarray, dict]:
    """Precomputed reference embeddings shipped with the code (ftf/assets/face_gallery.*): one mean ArcFace vector
    per person, made by `tools/build_face_gallery.py --export`. No photos and no network are needed to use them."""
    try:
        j = json.loads(config.FACE_GALLERY_JSON.read_text(encoding="utf-8"))
        with np.load(config.FACE_GALLERY_NPZ, allow_pickle=False) as d:
            vecs = d["vecs"].astype(np.float32)
        names = list(j["names"])
        if vecs.ndim != 2 or vecs.shape != (len(names), 512):
            raise ValueError(f"shape {vecs.shape} for {len(names)} names")
        return names, vecs, j.get("meta", {})
    except FileNotFoundError:
        pass
    except Exception as exc:
        log.warning("shipped face gallery unreadable: %s", exc)
    return [], np.zeros((0, 512), np.float32), {}


def _photo_gallery() -> tuple[list[str], np.ndarray, dict]:
    """data/reference_faces/<Person Name>/*.jpg -> mean ArcFace embedding per person.

    Cached safely as numeric .npz (allow_pickle=False) + JSON metadata sidecar (with mtime/size sig).
    """
    names, vecs, meta = [], [], {}
    root = config.REFERENCE_FACES
    cache_npz = root / "_gallery_cache.npz"
    cache_json = root / "_gallery_cache.json"
    files = sorted(p for p in root.glob("*/*") if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))
    if not files:
        return [], np.zeros((0, 512), np.float32), {}
    sig = [[str(p.relative_to(root)), p.stat().st_size, int(p.stat().st_mtime_ns)] for p in files]

    if cache_npz.exists() and cache_json.exists():
        try:
            j = json.loads(cache_json.read_text(encoding="utf-8"))
            if j.get("sig") == sig:
                with np.load(cache_npz, allow_pickle=False) as d:
                    return list(j["names"]), d["vecs"].astype(np.float32), j.get("meta", {})
        except Exception as exc:
            log.debug("rebuilding face gallery cache: %s", exc)

    by_person: dict[str, list[np.ndarray]] = {}
    for p in files:
        im = Image.open(p).convert("RGB")
        fs = faces_in_image(im, min_side=24)
        if not fs:
            continue
        best = max(fs, key=lambda f: f["side"])
        by_person.setdefault(p.parent.name, []).append(best["embedding"])
    for name, vs in sorted(by_person.items()):
        m = np.mean(vs, axis=0)
        names.append(name)
        vecs.append((m / (np.linalg.norm(m) + 1e-9)).astype(np.float32))
        meta[name] = {"n_images": len(vs)}
    arr = np.stack(vecs) if vecs else np.zeros((0, 512), np.float32)
    np.savez(cache_npz, vecs=arr)
    cache_json.write_text(
        json.dumps({"names": names, "meta": meta, "sig": sig}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return names, arr, meta


@lru_cache(maxsize=1)
def gallery() -> tuple[list[str], np.ndarray, dict]:
    """Reference DB = the shipped embeddings plus the local photos in data/reference_faces/.

    A person with local photos uses the embedding computed from them; everyone else comes from the shipped file.
    So the tool identifies the reference persons right after installation, and `tools/build_face_gallery.py`
    is only needed to add persons or rebuild the file (a partial photo download never shrinks the gallery).
    """
    names, vecs, meta = _photo_gallery()
    names, rows, meta = list(names), list(vecs), dict(meta)
    s_names, s_vecs, s_meta = shipped_gallery()
    for i, name in enumerate(s_names):
        if name not in meta and name not in names:
            names.append(name)
            rows.append(s_vecs[i])
            meta[name] = {**s_meta.get(name, {}), "shipped": True}
    order = sorted(range(len(names)), key=lambda i: names[i])
    arr = np.stack([rows[i] for i in order]).astype(np.float32) if order else np.zeros((0, 512), np.float32)
    return [names[i] for i in order], arr, meta


def identify(vec: np.ndarray, thresh: float = config.FACE_MATCH_THRESHOLD) -> tuple[str | None, float]:
    """Nearest reference identity by ArcFace cosine; named only when the cosine >= thresh."""
    names, vecs, _ = gallery()
    if len(names) == 0:
        return None, 0.0
    sims = vecs @ vec
    i = int(np.argmax(sims))
    best = float(sims[i])
    return (names[i] if best >= thresh else None), best
