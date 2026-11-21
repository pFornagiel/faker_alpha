"""Visual preprocessing: perceptual hash (pHash, Zauner 2010), creative cropping, OCR (RapidOCR,
Polish-capable PP-OCRv6), QR decoding, URL extraction and video keyframes. `_session` is the shared
CPU-only ONNX loader used by the e5 text embedder and the face models."""
from __future__ import annotations

import hashlib
import io
import logging
import re
import subprocess
from functools import lru_cache
from pathlib import Path

import cv2
import imagehash
import numpy as np
from PIL import Image

from . import config

log = logging.getLogger(__name__)
Image.MAX_IMAGE_PIXELS = 200_000_000
logging.getLogger("RapidOCR").setLevel(logging.WARNING)

URL_RX = re.compile(r"\b((?:https?://)?(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:[a-z]{2,24})(?:/[^\s\"'<>]*)?)", re.I)
TLD_HINT = re.compile(
    r"\.(com|pl|net|org|info|online|site|top|xyz|live|click|pro|shop|store|icu|sbs|cfd|life|"
    r"io|co|eu|biz|app|club|fun|website|space|today|news|ink|digital|rest|bond|cyou|vip|me|tv)$", re.I)


def load_rgb(src) -> Image.Image | None:
    try:
        if isinstance(src, (bytes, bytearray)):
            im = Image.open(io.BytesIO(src))
        elif isinstance(src, Image.Image):
            im = src
        else:
            im = Image.open(src)
        im.load()
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            return bg
        return im.convert("RGB")
    except Exception as exc:
        log.debug("cannot load image %s: %s", str(src)[:80], exc)
        return None


def file_sha(path_or_bytes) -> str:
    h = hashlib.sha256()
    if isinstance(path_or_bytes, (bytes, bytearray)):
        h.update(path_or_bytes)
    else:
        with open(path_or_bytes, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()


def hashes(im: Image.Image) -> dict:
    return {"phash": str(imagehash.phash(im))}


def hamming_hex(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def crop_content(im: Image.Image) -> Image.Image:
    """Trim uniform borders (status bars, letterboxing) so hashes focus on the creative."""
    a = np.asarray(im.convert("L"), dtype=np.int16)
    if a.size == 0:
        return im
    bg = np.median(np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]]))
    mask = np.abs(a - bg) > 12
    rows, cols = np.where(mask.any(1))[0], np.where(mask.any(0))[0]
    if len(rows) < 10 or len(cols) < 10:
        return im
    return im.crop((cols[0], rows[0], cols[-1] + 1, rows[-1] + 1))


def creative_crop(im: Image.Image, min_frac: float = 0.15, min_area_frac: float = 0.35) -> Image.Image:
    """Isolate the ad creative inside a portrait phone/feed screenshot: the tallest band of rows that look
    like a picture (many non-background pixels, high variance). Only runs on portrait screenshots
    (H/W > 1.35) and never crops down below 35% of the original area."""
    a = np.asarray(im.convert("L"), dtype=np.float32)
    H, W = a.shape
    if H < 200 or W < 200 or (H / W) <= 1.35:
        return im
    rgb = np.asarray(im, dtype=np.float32)
    sat = rgb.max(2) - rgb.min(2)
    nonbg = (np.abs(a - np.median(a)) > 25) | (sat > 40)
    row_fill = nonbg.mean(1)
    row_std = a.std(1)
    pic = (row_fill > 0.55) & (row_std > 18)
    gap = max(2, H // 100)
    best, cur_start, last_true = (0, 0, 0), None, -10 ** 9
    for y in range(H):
        if pic[y]:
            if cur_start is None or y - last_true > gap:
                cur_start = y
            last_true = y
            if last_true - cur_start > best[0]:
                best = (last_true - cur_start, cur_start, last_true)
    length, y0, y1 = best
    if length < min_frac * H:
        return im
    cols = np.where(nonbg[y0:y1 + 1].mean(0) > 0.3)[0]
    x0, x1 = (int(cols[0]), int(cols[-1])) if len(cols) > W * 0.3 else (0, W - 1)
    area = (x1 - x0 + 1) * (y1 - y0 + 1)
    if area < min_area_frac * W * H:
        return im
    return im.crop((x0, int(y0), x1 + 1, int(y1) + 1))


# ----------------------------------------------------------------------------- ONNX runtime
@lru_cache(maxsize=None)
def _session(path: str):
    import onnxruntime as ort

    so = ort.SessionOptions()
    so.intra_op_num_threads = 4
    so.log_severity_level = 3
    return ort.InferenceSession(path, so, providers=["CPUExecutionProvider"])


# ----------------------------------------------------------------------------- OCR / QR / URLs
@lru_cache(maxsize=1)
def _ocr_engine():
    from rapidocr import RapidOCR

    return RapidOCR()


def ocr(im: Image.Image, max_side: int = 1600) -> dict:
    """OCR with layout: returns text (reading order) and boxes (normalised) for template analysis."""
    w, h = im.size
    scale = min(1.0, max_side / max(w, h))
    if scale < 1.0:
        im = im.resize((int(w * scale), int(h * scale)), Image.BICUBIC)
    arr = cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)
    try:
        r = _ocr_engine()(arr)
    except Exception as exc:
        log.warning("OCR failed: %s", exc)
        return {"text": "", "lines": []}
    if r is None or r.txts is None:
        return {"text": "", "lines": []}
    W, H = im.size
    lines = []
    for box, txt, sc in zip(r.boxes, r.txts, r.scores):
        if sc < 0.6 or not txt.strip():
            continue
        b = np.asarray(box)
        x0, y0, x1, y1 = b[:, 0].min() / W, b[:, 1].min() / H, b[:, 0].max() / W, b[:, 1].max() / H
        lines.append({"text": txt, "box": [round(float(v), 4) for v in (x0, y0, x1, y1)], "score": round(float(sc), 3)})
    lines.sort(key=lambda l: (round(l["box"][1], 2), l["box"][0]))
    return {"text": " ".join(l["text"] for l in lines), "lines": lines}


def decode_qr(im: Image.Image) -> list[str]:
    arr = cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)
    out = []
    try:
        det = cv2.QRCodeDetector()
        ok, vals, _, _ = det.detectAndDecodeMulti(arr)
        if ok:
            out = [v for v in vals if v]
    except Exception:
        pass
    return out


def urls_in_text(text: str) -> list[str]:
    """URLs/domains visible in OCR text (e.g. 'WWW.SUPEROFERTA.PL' under a sponsored post)."""
    found = []
    for m in URL_RX.finditer(text or ""):
        u = m.group(1).rstrip(".,;:)")
        host = re.sub(r"^https?://", "", u).split("/")[0].lower()
        if TLD_HINT.search(host) and "." in host and not re.fullmatch(r"[\d.]+", host):
            found.append(u if u.startswith("http") else "https://" + u)
    return list(dict.fromkeys(found))


# ----------------------------------------------------------------------------- video
def _is_nonblack_frame(path: Path) -> bool:
    """Reject tiny or near-black padding frames (CSIRT KNF: black-frame padding evasion)."""
    if not path.exists() or path.stat().st_size <= 2000:
        return False
    try:
        with Image.open(path) as im:
            a = np.asarray(im.convert("L"))
        return bool(a.mean() > 12 and a.std() > 8)
    except Exception:
        return False


def video_keyframes(path: str | Path, out_dir: Path, n: int = config.MAX_VIDEO_KEYFRAMES) -> list[Path]:
    """Evenly spaced keyframes (robust for screen recordings and padded ads)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(out_dir.glob("kf_*.jpg"))
    if existing:
        valid = []
        for f in existing:
            if _is_nonblack_frame(f):
                valid.append(f)
            else:
                f.unlink(missing_ok=True)
        if len(valid) >= min(n, 2):
            return valid
    try:
        dur = float(
            subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
                capture_output=True, text=True, timeout=60,
            ).stdout.strip() or 0
        )
    except Exception:
        dur = 0
    if dur <= 0:
        return []
    keep = []
    for i in range(n):
        t = dur * (i + 0.5) / n
        dst = out_dir / f"kf_{i:02d}.jpg"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1",
             "-vf", "scale='min(960,iw)':-2", "-q:v", "3", str(dst)],
            capture_output=True, timeout=120,
        )
        if _is_nonblack_frame(dst):
            keep.append(dst)
        else:
            dst.unlink(missing_ok=True)
    return keep
