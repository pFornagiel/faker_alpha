# 05 — EmbeddingGemma-2 vs multilingual-e5-small (evaluation, 2026-11-21)

Question: is `google/embeddinggemma-2` a better narrative-similarity embedder for FakerAlpha than the
current `intfloat/multilingual-e5-small` (ONNX int8, `ftf.text.embed_text`)?

**Short answer:** it is available without credentials, runs on our CPU through onnxruntime (no PyTorch),
and is clearly better on Polish STS and on separating our known same-narrative pages — at roughly 4–6x the
CPU time per text. Recommendation: keep e5 as the default for the bulk ingest, use Gemma as an opt-in
second signal (`ftf/text_gemma.py`), and switch fully only if the corpus stays small (hundreds of pages).

The benchmark was cut short at the coordinator's request (it was starving the main ingest), so some cells
are missing; they are marked "not run". All timings were taken on a machine with load average 10–15.

## 1. Model card facts

| | |
|---|---|
| Repo | `google/embeddinggemma-2` (sha `f9972ac`, last modified 2026-10-28) |
| Gating | **Not gated** (`gated: false`), no HF login needed |
| Licence | Apache-2.0 (card also points to the Gemma Prohibited Use Policy) |
| Size | 740M params total = 270M text model (130M transformer + 140M embedding table) + 170M vision + 300M audio encoders; `model.safetensors` 1.49 GB (bf16) |
| Architecture | 24 layers, width 512, sliding-window attention with a full-attention layer every 6th, mean pooling, 512→768 projection |
| Dimensions | 768 native; Matryoshka truncation to 512 / 256 / 128 (re-normalise after slicing) |
| Max sequence | 8,192 tokens (shared across modalities) |
| Languages | "100+ languages", tagged `multilingual`; no per-language list. Polish is not named, but works (see STS below). Polish costs ~2.15 tokens per word |
| Precision | fp32 or bf16; the card warns **not** to use fp16 (NaN / silent degradation) |

Prompts (text only; `config_sentence_transformers.json`):

| Use | Prefix |
|---|---|
| Similarity (symmetric) — **used here** | `task: sentence similarity \| query: ` |
| Clustering (symmetric) | `task: clustering \| query: ` |
| Classification | `task: classification \| query: ` |
| Search query | `task: search result \| query: ` |
| Document | `title: {title or "none"} \| text: ` |
| Fact checking query | `task: fact checking \| query: ` |

ONNX / quantised variants found:

* **`onnx-community/embeddinggemma-2-ONNX`** (not gated, Apache-2.0, sha `daa72c5`) — used here. Text model
  as `model.onnx` fp32 (1084 MB), `model_fp16` (543 MB), `model_quantized` int8 (314 MB), `model_q4` (175 MB),
  `model_q4f16` (157 MB), plus separate vision/audio encoders. Inputs `input_ids`, `attention_mask` and three
  media feature inputs that must be passed as empty `[0, 512]` float arrays for text-only use. Output
  `sentence_embedding` is already pooled, projected and L2-normalised. Runs on our onnxruntime 1.32.
* Third-party text-only int8 exports (not tested): `digital-creature/embeddinggemma-2-text-onnx-int8`
  (674 MB, embedding table kept fp32), `arankays/embeddinggemma-2-text-int8-cw-onnx` (274 MB).
* Also GGUF (`ggml-org`, `unsloth`), LiteRT, MLX, CoreML builds — not relevant to our stack.

Downloaded to `models/embeddinggemma2/`: `tokenizer.json`, `config.json`, `config_sentence_transformers.json`,
`model_q4.onnx(+_data)`, `model_quantized.onnx(+_data)` — 521 MB. The fp32 reference (1.08 GB) is only in
the scratch directory and will not survive a cleanup.

## 2. Polish STS (Spearman, cosine vs gold score)

PL-MTEB test splits: `sickr-pl-sts` (1000 pairs sampled with seed 0) and `cdscr-sts` (all 998 pairs).
e5 is the production path (`query: ` prefix); Gemma uses the similarity prefix.

| Model | SICK-R-PL | CDSC-R |
|---|---|---|
| e5-small int8 (384-d) | 0.695 | 0.895 |
| Gemma-2 fp32, 768-d | **0.772** | **0.926** |
| Gemma-2 fp32, 256-d | 0.770 | 0.926 |
| Gemma-2 int8 (q8), 768-d | 0.772 | 0.926 |
| Gemma-2 q4, 768-d | 0.761 | 0.922 |
| Gemma-2 q4, 256-d | 0.760 | 0.920 |

Prefix matters (fp32, CDSC-R only): similarity 0.926, no prefix 0.914, clustering 0.856. Truncating to
256-d costs nothing measurable here.

## 3. Organiser sample pages (our data proxy)

13 saved pages from `data/organizer/dane/do_udostępnienia/` (title + text via `ftf.web.extract_html`).
Positives: case 1 ↔ 2 and case 48 ↔ 61/strona_1. Negatives: the other 70 cross-case pairs. Same-case pairs
(the three case-14 files, the three case-61 pages) are excluded.

Caveat that limits how much this proves: there are **two** positive pairs, and 1 ↔ 2 is a near-identical
text (cosine ~1.0 for every model), so the comparison effectively rests on one pair, 48 ↔ 61/strona_1.

| Model / input | 1 ↔ 2 | 48 ↔ 61/1 | neg mean ± sd | neg max | margin (min pos − max neg) | z of weakest positive |
|---|---|---|---|---|---|---|
| e5, 3×220-word windows (production) | 0.9995 | 0.9595 | 0.912 ± 0.020 | 0.956 | 0.003 | 2.4 |
| Gemma fp32, same 3 windows, similarity prefix | 1.000 | 0.927 | 0.832 ± 0.032 | 0.921 | 0.007 | 3.0 |
| Gemma q4, same 3 windows, similarity prefix | 1.000 | 0.927 | 0.829 ± 0.031 | 0.914 | 0.012 | 3.1 |
| Gemma fp32, same 3 windows, clustering prefix | 1.000 | 0.965 | 0.848 ± 0.043 | 0.952 | 0.014 | 2.7 |
| **Gemma fp32, one pass, first 1024 tokens, similarity prefix** | 1.000 | 0.920 | 0.739 ± 0.036 | 0.831 | **0.089** | **5.0** |
| Gemma fp32, one pass, first 2048 tokens, similarity prefix | 1.000 | 0.913 | 0.746 ± 0.039 | 0.835 | 0.078 | 4.3 |
| Gemma q4, one pass, first 2048 tokens, similarity prefix | 1.000 | 0.917 | 0.747 ± 0.039 | 0.853 | 0.065 | 4.3 |
| Gemma fp32, one pass, 2048 tokens, `title: … \| text: …` | 1.000 | 0.866 | 0.680 ± 0.047 | 0.795 | 0.071 | 4.0 |

Readings:

* With e5 the true pair sits 0.003 above the nearest unrelated pair — no usable threshold. Gemma with the
  same windowing is only slightly better. The gain comes from feeding **one long passage** (≤ 1024 tokens)
  instead of averaging three windows: margin 0.089. Going to 2048 tokens does not help and costs 2.5x more.
* Matryoshka 256-d on the windowed config gave the same margins as 768-d (0.006 vs 0.007 fp32).
* The hardest "negatives" are the same for both models and are arguably related material: case 14 ↔ 47
  (two supplement landing pages, Metabo RX / Uromexil Forte) and case 3 ↔ 48 / 61/strona_1 (celebrity-scandal
  fake articles). They are a different narrative but the same genre, so a high score there is not purely an error.
* q4 single-pass at 1024 tokens was not run on the full set; a spot check through `ftf/text_gemma.py`
  gave 48 ↔ 61/1 = 0.920 and 48 ↔ 47 = 0.699.

Split-half test (first half of each page vs second half; 17 positive, 140 negative pairs, 3-window input):

| Model | pos mean | neg mean | AUC | d′ |
|---|---|---|---|---|
| e5 | 0.948 | 0.905 | 0.952 | 2.2 |
| Gemma q4 | 0.901 | 0.823 | 0.960 | 2.5 |
| Gemma fp32, q8 | not run | | | |

A small improvement only.

## 4. Latency, RAM, disk

Timings with batch size 1, load average 10–15 from other jobs, so treat absolute numbers as pessimistic
and the ratios as the result. "Short" = 20 CDSC sentences (~13 words); "page" = 3 pages, 3×220-word windows.

| Model | Disk (model + tokenizer) | Short text, 2 threads | Page (3 windows), 2 threads | RSS added by model |
|---|---|---|---|---|
| e5-small int8 | 118 + 17 MB | 19 ms (14 ms at 4 threads, n=60) | 0.85 s (0.60 s at 4 threads, n=13) | ~0.5 GB |
| Gemma-2 fp32 | 1084 + 32 MB | 72 ms | 4.0 s | ~0.7 GB |
| Gemma-2 q4 | 175 + 32 MB | 113 ms | 4.8 s | ~0.35 GB |
| Gemma-2 int8 (q8) | 314 + 32 MB | 338 ms | 7.5 s | ~0.3 GB |

* Gemma is about 4–6x slower than e5 per text. The int8 build is the slowest on this CPU: it carries a
  fixed ~0.3–0.45 s per call regardless of length, so it is a poor choice here despite matching fp32 quality.
* One 1024-token pass through q4 took ~3.0 s per page at 4 threads (n=3) — about the cost of the three windows.
* Cost grows faster than linearly with length (int8, 4 threads: 512 tokens 2.3 s, 1024 → 5.1 s, 2048 → 12 s,
  4096 → 36–42 s), so the 8K context is not practical on this laptop.
* RSS figures are approximate (measured as deltas in one process). Whole-process peaks: e5 run 0.81 GB,
  Gemma q4 run 1.11 GB (including 2048-token passes).

## 5. Recommendation

1. **Keep e5 as the default for the running ingest.** Vectors already in the store are 384-d e5; Gemma's are
   768-d on a different cosine scale (unrelated pages ~0.74 vs ~0.91), so the two cannot share an index or
   thresholds, and switching means re-embedding everything.
2. **Add Gemma as a second, opt-in narrative signal** via `ftf/text_gemma.py`: it is the only configuration
   tested that puts a usable gap between the known same-narrative pair and everything else. At ~3–5 s per
   page it is affordable for hundreds of pages, not for tens of thousands.
3. A full switch is reasonable after the hackathon ingest, once thresholds are re-tuned on more than two
   positive pairs.

### Drop-in function

`ftf/text_gemma.py` → `embed_text_gemma(text: str) -> np.ndarray | None`

* Prompt: `task: sentence similarity | query: ` + text, one pass, truncated to the first 1024 tokens (`<eos>` kept).
* Returns the model's `sentence_embedding`, L2-normalised float32, 768-d (`DIM` can be set to 512/256/128);
  `None` if the model files are missing or the text is under 10 characters.
* Picks the first file present in `models/embeddinggemma2/`: `model.onnx` (fp32), `model_q4.onnx`,
  `model_quantized.onnx`; override with `FTF_GEMMA_MODEL`. Only q4 and int8 are in place now, so it uses q4.
  For fp32 (+1 pt STS, somewhat faster) download `onnx/model.onnx` and `onnx/model.onnx_data` from
  `onnx-community/embeddinggemma-2-ONNX` into that directory.
* Uses `ftf.vision._session` (4 threads, cached), like `embed_text`. No existing file was modified.

Scripts and raw outputs: `/tmp/claude-1000/-home-pawel/c47d1afe-7feb-4ed9-b69b-483c2e110a3d/scratchpad/gemma/`
(`bench.py`, `lat2.py`, `out/`).
