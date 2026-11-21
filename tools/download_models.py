"""Download the ONNX models used by the pipeline (CPU-only, no PyTorch).

Total ~ 460 MB. Run once:  python tools/download_models.py
Models (licences):
  * intfloat/multilingual-e5-small (MIT) - ONNX int8 export by Xenova  -> text/narrative embeddings
  * openai/clip-vit-base-patch32 (MIT) - ONNX int8 vision tower by Xenova -> "look" of the ad
  * facebook/dinov2-small (Apache-2.0) - ONNX int8 by Xenova            -> layout/template similarity
  * InsightFace buffalo_l: SCRFD det_10g + ArcFace w600k_r50 (code MIT, weights NON-COMMERCIAL research only)
"""
from __future__ import annotations

import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"
HF = "https://huggingface.co/{repo}/resolve/main/{path}"

FILES = {
    "e5/model.onnx": ("Xenova/multilingual-e5-small", "onnx/model_int8.onnx"),
    "e5/tokenizer.json": ("Xenova/multilingual-e5-small", "tokenizer.json"),
    "clip/vision_model.onnx": ("Xenova/clip-vit-base-patch32", "onnx/vision_model_int8.onnx"),
    "dinov2/model.onnx": ("Xenova/dinov2-small", "onnx/model_quantized.onnx"),
    "faces/det_10g.onnx": ("deepghs/insightface", "buffalo_l/det_10g.onnx"),
    "faces/w600k_r50.onnx": ("deepghs/insightface", "buffalo_l/w600k_r50.onnx"),
}


def fetch(dst: Path, repo: str, path: str) -> None:
    if dst.exists() and dst.stat().st_size > 0:
        print(f"[skip] {dst.relative_to(ROOT)}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    url = HF.format(repo=repo, path=path)
    tmp = dst.with_suffix(dst.suffix + ".part")
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                done += len(chunk)
        print(f"[ok]   {dst.relative_to(ROOT)} {done / 1e6:.1f} MB (expected {total / 1e6:.1f})")
    tmp.rename(dst)


def main(only: list[str] | None = None) -> None:
    for name, (repo, path) in FILES.items():
        if only and not any(name.startswith(o) for o in only):
            continue
        fetch(MODELS / name, repo, path)
    # RapidOCR fetches its own small models (~30 MB) on first use; trigger it here.
    try:
        from rapidocr import RapidOCR  # noqa: F401

        RapidOCR()
        print("[ok]   rapidocr models ready")
    except Exception as exc:  # pragma: no cover
        print("[warn] rapidocr not initialised:", exc)


if __name__ == "__main__":
    main(sys.argv[1:] or None)
