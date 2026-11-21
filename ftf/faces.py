"""Face detection (SCRFD det_10g) + ArcFace (w600k_r50) embeddings + reference gallery matching.

Implemented directly on onnxruntime (no `insightface` package / Cython build needed).
Model weights: InsightFace buffalo_l — non-commercial research licence (fine for the hackathon POC).
Face quality: we weight matches by a simple quality proxy (detector score x face size x sharpness),
in the spirit of MagFace/eDifFIQA suggested by the organisers.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from . import config
from .vision import _session

log = logging.getLogger(__name__)

ARC_TEMPLATE = np.array([[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
                         [41.5493, 92.3655], [70.7299, 92.2041]], dtype=np.float32)


def _distance2bbox(points, distance):
    return np.stack([points[:, 0] - distance[:, 0], points[:, 1] - distance[:, 1],
                     points[:, 0] + distance[:, 2], points[:, 1] + distance[:, 3]], axis=-1)


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


def embed(img_bgr: np.ndarray, kps: np.ndarray) -> np.ndarray | None:
    p = config.MODELS / "faces" / "w600k_r50.onnx"
    if not p.exists():
        return None
    M, _ = cv2.estimateAffinePartial2D(kps.astype(np.float32), ARC_TEMPLATE, method=cv2.LMEDS)
    if M is None:
        return None
    crop = cv2.warpAffine(img_bgr, M, (112, 112), borderValue=0.0)
    blob = cv2.dnn.blobFromImage(crop, 1.0 / 127.5, (112, 112), (127.5, 127.5, 127.5), swapRB=True)
    sess = _session(str(p))
    v = sess.run(None, {sess.get_inputs()[0].name: blob})[0][0]
    return (v / (np.linalg.norm(v) + 1e-9)).astype(np.float32), crop


def faces_in_image(im: Image.Image, min_side: int = 36) -> list[dict]:
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
        sharp = float(cv2.Laplacian(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())
        quality = float(np.clip(score, 0, 1) * np.clip(side / 112, 0.2, 1.0) * np.clip(sharp / 150, 0.3, 1.0))
        out.append({"box": [float(v) for v in box], "box_rel": [float(x0 / W), float(y0 / H), float(x1 / W), float(y1 / H)],
                    "det_score": round(score, 3), "side": round(float(side), 1), "quality": round(quality, 3),
                    "embedding": vec, "crop": crop})
    return out


# ----------------------------------------------------------------------------- reference gallery
@lru_cache(maxsize=1)
def gallery() -> tuple[list[str], np.ndarray, dict]:
    """Reference DB: data/reference_faces/<Person Name>/*.jpg -> mean ArcFace embedding per person."""
    names, vecs, meta = [], [], {}
    root = config.REFERENCE_FACES
    cache = root / "_gallery_cache.npz"
    files = sorted(p for p in root.glob("*/*") if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))
    sig = str([(str(p), p.stat().st_size) for p in files])
    if cache.exists():
        d = np.load(cache, allow_pickle=True)
        if str(d["sig"]) == sig:
            return list(d["names"]), d["vecs"], json.loads(str(d["meta"]))
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
        vecs.append(m / np.linalg.norm(m))
        meta[name] = {"n_images": len(vs)}
    arr = np.stack(vecs) if vecs else np.zeros((0, 512), np.float32)
    if files:
        np.savez(cache, names=np.array(names, dtype=object), vecs=arr, meta=json.dumps(meta), sig=sig)
    return names, arr, meta


def identify(vec: np.ndarray, thresh: float = config.FACE_MATCH_THRESHOLD) -> tuple[str | None, float]:
    names, vecs, _ = gallery()
    if len(names) == 0:
        return None, 0.0
    sims = vecs @ vec
    i = int(np.argmax(sims))
    return (names[i] if sims[i] >= thresh else None), float(sims[i])
