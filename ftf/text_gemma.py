"""EmbeddingGemma-2 text embeddings (ONNX, CPU) - opt-in alternative to `ftf.text.embed_text` (e5-small).

Model files (Apache-2.0, not gated) come from `onnx-community/embeddinggemma-2-ONNX` and live in
`models/embeddinggemma2/`: `tokenizer.json` plus one of `model.onnx` (fp32, 1.08 GB), `model_q4.onnx`
(175 MB) or `model_quantized.onnx` (int8, 314 MB), each with its `*.onnx_data` sidecar next to it.
Evaluation and rationale: research/05_embeddinggemma2_eval.md.

Differences from the e5 wrapper (do not mix the two in one index):
  * 768-d vectors (Matryoshka: set DIM to 512/256/128 to truncate + re-normalise), e5 is 384-d;
  * cosine scale differs (unrelated Polish landing pages ~0.74 here vs ~0.91 with e5) -> thresholds must be re-tuned;
  * prompt is the model's symmetric similarity prefix `task: sentence similarity | query: `;
  * one pass over the first MAX_TOKENS tokens instead of 3 averaged 220-word windows (separated our known
    same-narrative pairs much better at about the same CPU cost).
"""
from __future__ import annotations

import os
from functools import lru_cache

import numpy as np

from . import config

PROMPT = "task: sentence similarity | query: "
MAX_TOKENS = 1024            # model limit is 8192, but CPU cost grows faster than linearly (~2 s per 512 tokens)
DIM = 768                    # 768 | 512 | 256 | 128
_DIR = config.MODELS / "embeddinggemma2"
_VARIANTS = ("model.onnx", "model_q4.onnx", "model_quantized.onnx")   # fastest/most accurate first; int8 is slowest on CPU
_EOS = 1


def _model_path():
    forced = os.environ.get("FTF_GEMMA_MODEL")
    for name in ((forced,) if forced else _VARIANTS):
        p = _DIR / name
        if p.exists() and (_DIR / "tokenizer.json").exists():
            return p
    return None


@lru_cache(maxsize=1)
def _tok():
    from tokenizers import Tokenizer

    return Tokenizer.from_file(str(_DIR / "tokenizer.json"))     # adds <bos>/<eos> itself; no padding needed (batch of 1)


def embed_text_gemma(text: str) -> np.ndarray | None:
    p = _model_path()
    if p is None or not text or len(text.strip()) < 10:
        return None
    from .vision import _session

    ids = _tok().encode(PROMPT + text.strip()).ids
    if len(ids) > MAX_TOKENS:
        ids = ids[:MAX_TOKENS - 1] + [_EOS]
    x = np.array([ids], dtype=np.int64)
    empty = np.zeros((0, 512), dtype=np.float32)                  # text-only: no image / video / audio features
    v = _session(str(p)).run(["sentence_embedding"], {
        "input_ids": x, "attention_mask": np.ones_like(x),
        "image_features": empty, "video_features": empty, "audio_features": empty})[0][0]   # mean-pooled, projected to 768-d
    v = v[:DIM]
    return (v / (np.linalg.norm(v) + 1e-9)).astype(np.float32)
