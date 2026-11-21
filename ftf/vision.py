"""Visual features: perceptual hashes, CLIP (ad look) and DINOv2 (layout/template) embeddings,
OCR (RapidOCR, Polish-capable PP-OCRv6), QR decoding, URL extraction and video keyframes.
CPU-only ONNX; models are loaded lazily and cached."""
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
TLD_HINT = re.compile(r"\.(com|pl|net|org|info|online|site|top|xyz|live|click|pro|shop|store|icu|sbs|cfd|life|"
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
    return {"phash": str(imagehash.phash(im)), "dhash": str(imagehash.dhash(im)),
            "colorhash": str(imagehash.colorhash(im, binbits=3))}


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


def creative_crop(im: Image.Image, min_frac: float = 0.15) -> Image.Image:
    """Isolate the ad creative inside a phone/desktop feed screenshot: the tallest band of rows that look
    like a picture (many non-background pixels, high variance). Removes app UI chrome (status bar,
    buttons, comment boxes) which otherwise dominates CLIP/DINO similarity between unrelated screenshots."""
    a = np.asarray(im.convert("L"), dtype=np.float32)
    H, W = a.shape
    if H < 200 or W < 200:
        return im
    rgb = np.asarray(im, dtype=np.float32)
    sat = (rgb.max(2) - rgb.min(2))
    nonbg = (np.abs(a - np.median(a)) > 25) | (sat > 40)
    row_fill = nonbg.mean(1)
    row_std = a.std(1)
    pic = (row_fill > 0.55) & (row_std > 18)
    # close small gaps (1 % of height)
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
    x0, x1 = (cols[0], cols[-1]) if len(cols) > W * 0.3 else (0, W - 1)
    return im.crop((int(x0), int(y0), int(x1) + 1, int(y1) + 1))


# ----------------------------------------------------------------------------- ONNX embedders
@lru_cache(maxsize=None)
def _session(path: str):
    import onnxruntime as ort

    so = ort.SessionOptions()
    so.intra_op_num_threads = 4
    so.log_severity_level = 3
    return ort.InferenceSession(path, so, providers=["CPUExecutionProvider"])


def _square_pad(im: Image.Image, fill=(255, 255, 255)) -> Image.Image:
    w, h = im.size
    s = max(w, h)
    canvas = Image.new("RGB", (s, s), fill)
    canvas.paste(im, ((s - w) // 2, (s - h) // 2))
    return canvas


def _prep(im: Image.Image, mean, std, size=224) -> np.ndarray:
    im = _square_pad(im).resize((size, size), Image.BICUBIC)
    a = np.asarray(im, dtype=np.float32) / 255.0
    a = (a - np.array(mean, np.float32)) / np.array(std, np.float32)
    return a.transpose(2, 0, 1)[None]


def clip_embed(im: Image.Image) -> np.ndarray | None:
    p = config.MODELS / "clip" / "vision_model.onnx"
    if not p.exists():
        return None
    x = _prep(im, (0.48145466, 0.4578275, 0.40821073), (0.26862954, 0.26130258, 0.27577711))
    v = _session(str(p)).run(["image_embeds"], {"pixel_values": x})[0][0]
    return (v / (np.linalg.norm(v) + 1e-9)).astype(np.float32)


def dino_embed(im: Image.Image) -> np.ndarray | None:
    p = config.MODELS / "dinov2" / "model.onnx"
    if not p.exists():
        return None
    x = _prep(im, (0.485, 0.456, 0.406), (0.229, 0.224, 0.225))
    h = _session(str(p)).run(["last_hidden_state"], {"pixel_values": x})[0][0]
    v = np.concatenate([h[0], h[1:].mean(0)])            # CLS (semantics) + mean patch (layout/texture)
    return (v / (np.linalg.norm(v) + 1e-9)).astype(np.float32)


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
def video_keyframes(path: str | Path, out_dir: Path, n: int = config.MAX_VIDEO_KEYFRAMES) -> list[Path]:
    """Evenly spaced keyframes (robust for screen recordings and padded ads)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(out_dir.glob("kf_*.jpg"))
    if len(existing) >= min(n, 2):
        return existing
    try:
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                    "default=nw=1:nk=1", str(path)], capture_output=True, text=True, timeout=60).stdout.strip() or 0)
    except Exception:
        dur = 0
    if dur <= 0:
        return []
    frames = []
    for i in range(n):
        t = dur * (i + 0.5) / n
        dst = out_dir / f"kf_{i:02d}.jpg"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1",
                        "-vf", "scale='min(960,iw)':-2", "-q:v", "3", str(dst)], capture_output=True, timeout=120)
        if dst.exists() and dst.stat().st_size > 2000:
            frames.append(dst)
    # drop near-black padding frames (CSIRT KNF: black-frame padding evasion)
    keep = []
    for f in frames:
        a = np.asarray(Image.open(f).convert("L"))
        if a.mean() > 12 and a.std() > 8:
            keep.append(f)
    return keep


def video_meta(path: str | Path) -> dict:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
                            "-of", "json", str(path)], capture_output=True, text=True, timeout=60)
        import json

        d = json.loads(r.stdout or "{}")
        v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), {})
        return {"duration": float(d.get("format", {}).get("duration", 0) or 0), "width": v.get("width"),
                "height": v.get("height"), "has_audio": any(s.get("codec_type") == "audio" for s in d.get("streams", []))}
    except Exception:
        return {}


def layout_signature(lines: list[dict], faces: list[dict], grid: int = 4) -> np.ndarray:
    """Production-template descriptor: where text and faces sit on the creative (grid occupancy)."""
    v = np.zeros((2, grid, grid), np.float32)
    for l in lines:
        x0, y0, x1, y1 = l["box"]
        cx, cy = min(grid - 1, int((x0 + x1) / 2 * grid)), min(grid - 1, int((y0 + y1) / 2 * grid))
        v[0, cy, cx] += (x1 - x0) * (y1 - y0) * 10
    for f in faces:
        x0, y0, x1, y1 = f["box_rel"]
        cx, cy = min(grid - 1, int((x0 + x1) / 2 * grid)), min(grid - 1, int((y0 + y1) / 2 * grid))
        v[1, cy, cx] += 1
    v = v.flatten()
    n = np.linalg.norm(v)
    return v / n if n else v
