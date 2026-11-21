# 03 — Content-level feature extraction and models (CPU-only POC)

Research date: 2026-11-21. Scope: which models/libraries to use to turn an ad (image, video, screenshot, text) into features that link ads into campaigns.

## 0. Ground rules for reading this document

**Target machine (checked on the box):** Intel i5-8365U (4 cores / 8 threads, 15 W laptop CPU, AVX2 only, **no AVX-512/VNNI**), 15 GB RAM (~7 GB available), **9.5 GB free disk**, Linux, `uv 0.10`, Python 3.11 and 3.12 already installed via uv. System binaries present: `ffmpeg`/`ffprobe` n9.0.2, `fpcalc` (Chromaprint), `zbarimg` (so libzbar is present), `gcc`/`g++`/`cmake`. **Not present:** `tesseract`.

**What is verified and what is not:**

- **Verified today** (HF API, PyPI JSON, GitHub, release assets, vendor docs): file sizes, licences, package versions, release dates, Polish diacritics in OCR dictionaries, PL-MTEB scores, Whisper per-language WER table.
- **Not verified — estimates:** every latency figure. Nothing was installed or benchmarked (disk constraint). Latencies are extrapolated from published desktop/server numbers to this laptop CPU and given as ranges. Treat them as order-of-magnitude; run a 10-minute benchmark before committing.
- Rule of thumb used: this CPU is roughly 4–5x slower multi-threaded than the i7-12700K used in most published CPU benchmarks. Set ONNX Runtime `intra_op_num_threads=4` (physical cores), not 8.

**Sizes** are download sizes of the files you actually need, not whole repos (HF repos often hold 5–10 redundant variants; always download single files with `hf_hub_download`, never `snapshot_download`).

---

## 1. Recommended CPU POC stack (opinionated)

### 1.1 Core stack — ONNX-only, no PyTorch (about 3.2 GB on disk)

| Modality | Choice | Model ID / package | Size | Licence |
|---|---|---|---|---|
| Exact/near-dup images | PDQ + pHash/dHash | `pdqhash` 0.2.8, `ImageHash` 4.3.2 | <1 MB | MIT / BSD-2 |
| Global image embedding | SigLIP 2 B/16-224, **vision tower only** | `immich-app/ViT-B-16-SigLIP2__webli` → `visual/model.onnx` (same weights also at `onnx-community/siglip2-base-patch16-224-ONNX` → `onnx/vision_model.onnx`) | 372 MB | Apache-2.0 (upstream `google/siglip2-base-patch16-224`) |
| Layout/template embedding | DINOv2-small | `Xenova/dinov2-small` → `onnx/model.onnx` | 88 MB | Apache-2.0 |
| Faces: detect + embed | InsightFace `buffalo_l` (SCRFD-10GF + ArcFace R50 WebFace600K) | `insightface` 2.1 | 275 MB zip / 326 MB unpacked (191 MB if you keep only `det_10g.onnx` + `w600k_r50.onnx`) | code MIT; **weights non-commercial research only** |
| Face quality | eDifFIQA(T) + ArcFace embedding norm + size/blur heuristics | `opencv/opencv_zoo` → `models/face_image_quality_assessment_ediffiqa/ediffiqa_tiny_jun2024.onnx` | 7.3 MB | CC-BY-4.0 |
| OCR | RapidOCR, PP-OCRv6 small (the 3.10 default) | `rapidocr` 3.10.0 + `onnxruntime` | det 9.9 MB + rec 21.2 MB | Apache-2.0 |
| QR / barcodes | zxing-cpp, OpenCV fallback | `zxing-cpp` 3.1.1 | 1 MB | Apache-2.0 |
| Keyframes | ffmpeg scene filter + 1 fps sampling; PySceneDetect optional | system `ffmpeg`; `scenedetect` 0.7.3 | – | BSD-3 |
| Video near-dup | DIY "vPDQ-style": PDQ per keyframe + set matching | `pdqhash` | – | – |
| ASR (Polish) | NVIDIA Parakeet-TDT 0.6B v3, int8 ONNX | `onnx-asr` 0.12.0 + `istupakov/parakeet-tdt-0.6b-v3-onnx` (`encoder-model.int8.onnx`, `decoder_joint-model.int8.onnx`, `nemo128.onnx`, `vocab.txt`, `config.json`) | 670 MB | MIT (lib) / CC-BY-4.0 (model) |
| Audio fingerprint | Chromaprint | system `fpcalc` + `pyacoustid` 1.3.1 | – | MIT wrapper |
| Speaker embedding | WeSpeaker ResNet34-LM ONNX | `Wespeaker/wespeaker-voxceleb-resnet34-LM` → `voxceleb_resnet34_LM.onnx` (+ `kaldi-native-fbank` for features, or run via `sherpa-onnx`) | 26.5 MB | CC-BY-4.0 |
| Text embedding | multilingual-e5-small (ONNX in the official repo) | `intfloat/multilingual-e5-small` → `onnx/model.onnx` + `tokenizer.json` | 487 MB | MIT |
| Near-dup text | MinHash/LSH + RapidFuzz verification | `datasketch` 2.0.0, `rapidfuzz` | – | MIT |
| Lemmas + NER | spaCy Polish medium | `spacy` 3.8 + `pl_core_news_md` 3.8.0 | 49 MB | lib MIT; **model GPL-3.0** |
| Phones / amounts / URLs | regex + `phonenumbers` + `tldextract` | – | – | Apache-2.0 / BSD |

Disk: models ≈ 2.1 GB, Python environment ≈ 1.1 GB (onnxruntime, opencv, numpy, scipy, scikit-image, scikit-learn, onnx, spacy, tokenizers — estimate) → **≈ 3.2 GB total**, leaving ~6 GB for data, a headless browser (other agents' scope) and caches.

RAM if everything is loaded at once: roughly 3.5–4.5 GB (estimate). Lazy-load ASR; it is the biggest single consumer.

### 1.2 Optional add-ons (pick by remaining disk)

| Add-on | What it buys | Extra disk |
|---|---|---|
| SigLIP 2 text tower (`textual/model.onnx` + tokenizer) | Polish/English text→image search and zero-shot tags in the same space as the image embeddings | +1.16 GB |
| **PyTorch CPU pack** (`torch` 2.13 CPU wheel 192 MB download, ~0.7 GB installed; `transformers`, `sentence-transformers`, `timm`) | prerequisite for everything below | +0.9 GB |
| `sdadas/mmlw-roberta-base` | best <150M-param Polish sentence embedder on PL-MTEB (STS 85.2 vs 78.4 for e5-small) | +498 MB |
| `facetorch` (RetinaFace + MagFace + DFDC EfficientNet-B7 only) | the organisers' named tool: MagFace quality norm and a deepfake score | +650 MB |
| SSCD copy-detection descriptor (`sscd_disc_mixup.torchscript.pt`) | edited-copy detection that survives crops and overlays | +99 MB |
| Community Forensics ViT-S (`OwensLab/commfor-model-384`) | AI-generated-image likelihood | +87 MB |

Everything together is ≈ 6.6 GB — it fits but leaves under 3 GB. Recommendation: core stack first; add the torch pack only once the core pipeline works end to end.

### 1.3 Install sketch

```bash
uv init --python 3.12 && uv add \
  onnxruntime insightface rapidocr imagehash pdqhash zxing-cpp \
  onnx-asr[cpu,hub] pyacoustid kaldi-native-fbank scenedetect \
  tokenizers huggingface_hub datasketch rapidfuzz spacy phonenumbers tldextract \
  scikit-learn networkx numpy pillow
uv pip install https://github.com/explosion/spacy-models/releases/download/pl_core_news_md-3.8.0/pl_core_news_md-3.8.0-py3-none-any.whl
```

If (and only if) adding the torch pack, pin the CPU index in `pyproject.toml` first — **the default PyPI torch wheel on Linux pulls several GB of CUDA libraries and would fill the disk**:

```toml
[[tool.uv.index]]
name = "pytorch-cpu"
url = "https://download.pytorch.org/whl/cpu"
explicit = true

[tool.uv.sources]
torch = { index = "pytorch-cpu" }
torchvision = { index = "pytorch-cpu" }
```

Packages that silently depend on torch: `sentence-transformers`, `easyocr`, `facetorch`, `open-clip-torch`, `timm`, `gliner`, `speechbrain`, `qreader`, `ultralytics`, `stanza`.

### 1.4 Key caveats (the short list)

1. **All latencies are unmeasured estimates.** Benchmark before the demo.
2. **`pdqhash` has no Linux wheel** (macOS/Windows wheels only + sdist). It compiles from source; `g++` is present so it should build, but test it early. Fallback: `imagehash.phash(hash_size=16)`.
3. **InsightFace pretrained weights are non-commercial research only** (library is MIT). Fine for the hackathon; say so on a slide. A fully permissive alternative is OpenCV Zoo YuNet (MIT, 0.23 MB) + SFace (Apache-2.0, 38.7 MB), at lower accuracy.
4. **RapidOCR downloads models from `modelscope.cn`** on first use. Pre-download before the event; do not rely on venue Wi-Fi.
5. **spaCy Polish models are GPL-3.0.** OK for a hackathon; swap for `simplemma` (MIT) + regex/gazetteers if licence matters.
6. **Do not present AI-generated/deepfake scores as verdicts.** Open detectors perform near chance on in-the-wild material (Section 7–8). Campaign linking does not need them.
7. The InsightFace runtime docs state that recent ONNX Runtime builds have a telemetry uploader on non-Windows platforms and that InsightFace sets `ORT_DISABLE_TELEMETRY=1` itself. I could not confirm this against ONNX Runtime's own docs; setting `ORT_DISABLE_TELEMETRY=1` in the environment is free insurance.

---

## 2. Images

### 2.1 Perceptual hashes (exact and near-duplicate creatives)

| Tool | pip | Size | Licence | CPU latency (est.) | Use and notes |
|---|---|---|---|---|---|
| PDQ (Meta) | `pdqhash` 0.2.8 | sdist build | MIT (binding) | 5–15 ms/img | 256-bit hash + quality score 0–100. Meta's guidance: drop hashes with quality < 50; **match at Hamming ≤ 31**. Survives resize, recompression, mild colour/brightness edits, small watermark. Does **not** survive crops beyond ~10%, rotation, big overlays. `compute_dihedral` gives the 8 flips/rotations (mirrored re-uploads are a common evasion). |
| pHash / dHash / wHash | `ImageHash` 4.3.2 | 0.3 MB | BSD-2 | 1–5 ms/img | 64-bit default. Starting thresholds: pHash ≤ 8–10, dHash ≤ 10 (of 64). Use `hash_size=16` (256-bit) for fewer false positives on text-heavy ads, which all look alike at 8×8. |
| `crop_resistant_hash` | `ImageHash` | – | BSD-2 | 50–300 ms/img | Segment-based; handles crops in principle but is slow and unstable on ads with text overlays. Not recommended as primary. |
| `colorhash` | `ImageHash` | – | BSD-2 | ~2 ms | Coarse palette hash; cheap extra signal for template similarity only. |

**Crop/resize/overlay-robust duplicate detection — recommended recipe (no extra model):**

1. Candidate generation: kNN on SigLIP 2 embeddings (cos ≥ ~0.85) and on DINOv2 embeddings.
2. Verification: ORB or SIFT keypoints + RANSAC homography in OpenCV (already installed as an InsightFace dependency). ≥ 25–30 inliers ⇒ "same base image, cropped/re-framed/overlaid". 30–80 ms per pair, so only run on shortlisted pairs.
3. Also hash sub-regions: PDQ of the image with OCR text boxes inpainted/blurred, and PDQ of each detected face crop expanded 2x. The same stock photo of a "doctor" with a different caption then still collides.

Optional upgrade (needs torch): **SSCD** (`facebookresearch/sscd-copy-detection`, MIT code, repo archived 2022; `sscd_disc_mixup.torchscript.pt` 98.8 MB, ResNet-50, 512-d). It is trained specifically for edited-copy detection; the README states cos > 0.75 ≈ copies at 90% precision. Est. 150–300 ms/img here. This is the single best "same creative, different overlay" signal if torch is installed.

### 2.2 Global embeddings (ad look, semantics, concept)

| Model | HF id (file) | Size | Licence | Polish text? | CPU latency (est., per image) | Use |
|---|---|---|---|---|---|---|
| **SigLIP 2 B/16-224** (recommended) | `immich-app/ViT-B-16-SigLIP2__webli` (`visual/model.onnx`); text: `textual/model.onnx` | 372 MB vision; 1,129 MB text + 34 MB tokenizer | Apache-2.0 | Yes — multilingual text tower (Gemma tokenizer, 256k vocab); on XM3600 it nearly matches mSigLIP per the paper. No Polish-only figure found. | 150–350 ms | Main "visual/conceptual similarity" vector (768-d). SigLIP models read text in images noticeably better than OpenAI CLIP, which helps on text-heavy ads. Preprocess: 224×224 **squash** resize, bicubic, mean/std 0.5. |
| SigLIP 2 B/16-224 int8 | `onnx-community/siglip2-base-patch16-224-ONNX` (`onnx/vision_model_quantized.onnx`) | 94.6 MB | Apache-2.0 upstream | – | 80–200 ms | Disk/latency saver. Int8 ViT quality loss is unmeasured; without VNNI the speed-up is modest. Only if disk gets tight. |
| OpenAI CLIP ViT-B/32 | `Qdrant/clip-ViT-B-32-vision` + `Qdrant/clip-ViT-B-32-text` (both loadable through `fastembed`) | 352 MB + 254 MB | MIT | No (English) | 50–120 ms | Fastest sane option (4x fewer tokens than B/16). Weaker embeddings than SigLIP 2. |
| Multilingual text tower for CLIP B/32 | `sentence-transformers/clip-ViT-B-32-multilingual-v1` | 539 MB | Apache-2.0 | Yes (distilled multilingual DistilBERT, 50+ languages incl. `pl`) | 15–30 ms/text | Polish text → CLIP B/32 image space. The ONNX file covers only the transformer; mean pooling + the dense projection must be applied by hand (or use sentence-transformers with torch). |
| XLM-R + ViT-B/32 (LAION-5B) | `immich-app/XLM-Roberta-Base-ViT-B-32__laion5b_s13b_b90k` | 352 MB + 1,113 MB | MIT (upstream `laion/CLIP-ViT-B-32-xlm-roberta-base-laion5B-s13B-b90k`) | Yes | 50–120 ms | Ready-made ONNX multilingual CLIP; older (2022) and weaker than SigLIP 2. |
| MobileCLIP-S0 / S2 | `Xenova/mobileclip_s0` (45.5 MB vision + 170 MB text), `Xenova/mobileclip_s2` (143 MB + 254 MB) | see left | **Apple AMLR (research-only)** | No | 25–60 ms / 60–130 ms | Speed option. Licence and English-only text make it second choice. |
| jina-clip-v2 | `jinaai/jina-clip-v2` | 874 MB (int8) – 3.4 GB | **CC-BY-NC-4.0** | Yes (89 languages) | 1–3 s | Too heavy for this CPU. Skip. |
| DINOv2-small | `Xenova/dinov2-small` (`onnx/model.onnx`) | 88 MB | Apache-2.0 | n/a | 80–200 ms | Self-supervised, structure-oriented: layout/template similarity (Section 2.4). 384-d CLS + 256 patch tokens. |
| DINOv3 ViT-S/16 | `facebook/dinov3-vits16-pretrain-lvd1689m` | 86 MB | custom DINOv3 licence, gated | n/a | similar | No clear gain for the POC; licence friction. Skip. |

Why vision-only is enough for the core: campaign linking is image↔image. The 1.1 GB text tower is only needed for text→image search or zero-shot tagging ("screenshot of a news site", "medicine bottle", "trading app"). If you want zero-shot tags cheaply, compute them once per ad with the text tower loaded temporarily, or skip tags and rely on OCR/ASR text.

### 2.3 Logo and brand detection

| Approach | Model / package | Size | Licence | CPU latency (est.) | Verdict |
|---|---|---|---|---|---|
| **OCR + brand gazetteer** (recommended) | RapidOCR output + `rapidfuzz` against a list of Polish brands/media/banks (PKO BP, Orlen, mBank, InPost, Allegro, TVN24, TVP Info, Onet, WP, gov.pl, NBP, Baltic Pipe…) | 0 | – | ~0 | Most impersonated brands are wordmarks. Catches the majority at zero model cost. |
| **Crop → embedding → logo gallery** (recommended second step) | SigLIP 2 vision on candidate crops (OCR boxes expanded, corners of the frame, any high-contrast compact region) vs a small gallery of reference logos | 0 extra | – | 150–350 ms/crop | This is Phishpedia's idea (detect, then Siamese-match to a reference list) without detectron2. Threshold by calibration; start at cos ≥ 0.80. |
| ORB/SIFT template matching | OpenCV | 0 | Apache-2.0 | 20–80 ms/logo | Works well for the 10–20 logos that matter (e.g., TV-station lower-thirds). |
| OWL-ViT B/32 | `google/owlvit-base-patch32`; ONNX `Xenova/owlvit-base-patch32` | 613 MB (155 MB int8) | Apache-2.0 | 1–3 s/img | Open-vocabulary "logo" proposals. Usable if you really need boxes. |
| OWLv2 B/16 ensemble | `google/owlv2-base-patch16-ensemble` | 620 MB | Apache-2.0 | 8–20 s/img (960×960 input) | Best quality, too slow on this CPU. |
| Grounding DINO tiny | `IDEA-Research/grounding-dino-tiny`; `onnx-community/grounding-dino-tiny-ONNX` | 690 MB (204 MB int8) | Apache-2.0 | 5–12 s/img | Too slow. |
| OmDet-Turbo tiny | `omlab/omdet-turbo-swin-tiny-hf` | 462 MB | Apache-2.0 | 1.5–4 s/img | Needs torch + transformers. |
| YOLO-World / YOLOE | `ultralytics` | 30–110 MB | **AGPL-3.0 / GPL-3.0** | 0.15–0.5 s/img | Fast, but copyleft and pulls torch. |
| Phishpedia | `lindsey98/Phishpedia` | several hundred MB (not verified) | code CC0-1.0 | seconds | Faster-RCNN (detectron2) + Siamese matcher over ~277 mostly global brands. Reference list lacks Polish brands; detectron2 is a painful install. Borrow the idea, not the code. |

### 2.4 "Production template" similarity — how to represent it

Build a small, explicit **template descriptor** per image/keyframe from things already computed (OCR boxes, face boxes, pixels). No new model required.

| Component | Representation | Comparison |
|---|---|---|
| Layout grid | Rasterise OCR text boxes, face boxes and logo boxes onto a 12×12 (or 16×16) grid, one channel each; flatten, L2-normalise. Store aspect-ratio bucket separately (1:1, 4:5, 9:16, 16:9). | Cosine, or IoU of binarised masks. Only compare within the same aspect bucket. |
| Text statistics | Number of text blocks; text-area ratio; median text-line height / image height (font-size proxy); share of ALL-CAPS; left/centre alignment histogram; presence of a bottom subtitle band. | Normalised L1 distance. |
| Colour palette | k-means (k=5) in CIELAB on a 64×64 downscale → colours sorted by weight; plus a coarse Lab histogram (4×8×8 bins). Sample **text colour and text-box background colour** inside OCR boxes (yellow captions with black stroke, red "PILNE" banners are strong template markers). | Hellinger/chi² on histograms; ΔE between sorted palette entries. |
| Typography | Crop the 3 largest OCR text lines, embed each with DINOv2-small, average. | Cosine. A cheap "font style" vector without a font classifier. |
| Structure embedding | DINOv2-small CLS on the full image, squash-resized (do not centre-crop — layout lives at the edges). Variant: DINOv2 on the image with text boxes blurred and faces masked, so the vector describes the frame, not the content. | Cosine ≥ ~0.6–0.7 as a candidate edge (calibrate). |
| Edge/structure hash | pHash (16×16) of the Canny edge map after heavy Gaussian blur. | Hamming. |
| Video container fingerprint | `ffprobe -show_format -show_streams`: encoder tag (`Lavf…`, CapCut/Canva signatures), resolution, fps, audio sample rate/codec, bitrate ladder, duration bucket. | Exact/partial match. Cheap and surprisingly discriminative for "same production pipeline". Platforms re-encode, so it is strongest on files obtained from landing pages or direct uploads. |
| Video rhythm | Shot-length histogram from scene cuts; subtitle-band position across frames; PDQ of first/last keyframes (shared intro/outro cards). | Histogram distance; Hamming. |
| Audio template | Chromaprint of the track (same music bed / voice-over), speaker embedding of the narrator. | Section 5. |

Fuse these as separate edge types in the campaign graph rather than one blended score, so the demo can explain *why* two ads were linked ("same layout grid + same caption style + same narrator voice").

---

## 3. Faces

### 3.1 Detection and recognition

| Option | Package / model | Size | Licence | CPU latency (est.) | Notes |
|---|---|---|---|---|---|
| **InsightFace `buffalo_l`** (recommended) | `insightface` 2.1 (2026-10-03; pure-Python wheel, **no compiler needed since 1.0**, Python ≥ 3.10) | 275 MB zip; unpacked: `det_10g.onnx` 17 MB, `w600k_r50.onnx` 174 MB, `1k3d68.onnx` 144 MB, `2d106det.onnx` 5 MB, `genderage.onnx` 1.3 MB | lib MIT; **weights non-commercial research** | detection 80–200 ms/frame at 640×640; embedding 40–90 ms/face | SCRFD-10GF + ArcFace ResNet-50 @ WebFace600K, 512-d. Official accuracy: MR-ALL 91.25, IJB-C(E4) 97.25, LFW 99.83. Load only what you need: `FaceAnalysis(name="buffalo_l", allowed_modules=["detection","recognition"], providers=["CPUExecutionProvider"])`. Keep `2d106det` if you want mouth landmarks for lip heuristics. |
| InsightFace `buffalo_s` / `buffalo_sc` | same | 122 MB / **14.3 MB** zip (`buffalo_sc` = detector + recogniser only; `buffalo_s` is big only because of the 144 MB 3D-landmark model) | same | detection 15–40 ms; embedding 8–20 ms | SCRFD-500MF + MobileFaceNet. LFW 99.70 looks close, but **MR-ALL drops to 71.87 and IJB-C to 95.02** — i.e. much weaker exactly on small, compressed, off-angle faces typical of ads. Use only as a fast pre-filter for dense video sampling. |
| InsightFace `raccoon_s/_l`, `cheetah_s/_l` | new in 2.0/2.1 | 35 / 243 MB; 26 / 202 MB | non-commercial | – | Per the model-zoo docs, Cheetah's face models are byte-identical to `buffalo_s`/`buffalo_l` and match the Raccoon recognition entries, so there is no recognition gain over `buffalo_l` (my reading of the docs, not independently tested). Cheetah adds body detection/ReID — irrelevant here. |
| InsightFace liveness add-on | `FaceAnalysis(addons=["liveness"])` | separate download | see add-on repo | – | RGB presentation-attack (print/replay) detection for access control. **Not** a deepfake detector; not useful for ads. |
| OpenCV Zoo YuNet + SFace | `opencv/opencv_zoo` (`face_detection_yunet_2023mar.onnx` 0.23 MB, `face_recognition_sface_2021dec.onnx` 38.7 MB) | 39 MB | MIT / Apache-2.0 | 10–30 ms + 20–40 ms | Fully permissive fallback, runs through `cv2.FaceDetectorYN` / `cv2.FaceRecognizerSF`. Clearly less accurate than ArcFace R50. |
| `uniface` | `uniface` 4.3.0 (MIT lib, Python ≥ 3.11, ONNX Runtime) | per model | "some pretrained weights are not" MIT — check its licence-attribution page | similar to above | One-stop ONNX toolkit: RetinaFace/SCRFD/YOLO-Face, ArcFace/AdaFace/EdgeFace, BYTETracker, **eDifFIQA quality (T/S/M/L)**, MiniFASNet. Good alternative wrapper if InsightFace's API gets in the way. |
| facetorch | `facetorch` 0.6.2 stable (1.0.0rc5 beta); Python 3.11–3.12; torch 2.6–2.13 | default set ≈ 1.2 GB; selective: RetinaFace 118 MB, MagFace+UNPG 262 MB, DFDC EfficientNet-B7 270 MB, FER EfficientNet-B0/B2 small, AU Swin-B (94M params), VA AlexNet, SynergyNet align | code Apache-2.0; weights MIT/Apache-2.0 per model | RetinaFace-R50 0.5–1.5 s/frame; MagFace iResNet100 300–600 ms/face; B7 0.5–1.2 s/face | The organisers' hint. CPU-feasible at POC volumes if you run only `include_predictors=["verify","deepfake"]`. Value: one pipeline giving MagFace quality + deepfake score + emotions. Cost: torch + 650 MB + slow detector. Use it as a nice-to-have on top of InsightFace, not instead of it. |
| DeepFace | `deepface` 0.0.105 (MIT) | 0.1–0.6 GB models + **TensorFlow/Keras** (~1.5–2 GB) | mixed | slow | Convenience wrapper; the TF dependency alone disqualifies it on this disk. |
| face_recognition / dlib | `face-recognition` 1.3.0 (last release 2020), `dlib` 20.0.1 (**sdist only** → 5–10 min C++ build) | ~100 MB models | MIT / Boost | HOG detect 100–300 ms; 128-d embed 30–60 ms | Legacy. HOG detector misses small/angled faces; embeddings well below ArcFace. Skip. |

### 3.2 Face quality (weighting weak faces lower)

| Method | Availability | Size | Licence | CPU cost | Assessment |
|---|---|---|---|---|---|
| **ArcFace embedding norm** | free: `face.embedding_norm` in InsightFace | 0 | – | 0 | The un-normalised feature norm of margin-softmax models drops on blurry/occluded/tiny faces. Not calibrated like MagFace, but a useful zero-cost proxy. Calibrate on your data (plot norm vs. match correctness). |
| **Heuristics** | DIY | 0 | – | <1 ms | Detector score, inter-ocular distance in px (reject < ~20 px, down-weight < 40 px), Laplacian variance on the aligned 112×112 crop (blur), yaw from 5-point landmarks, mean brightness. Robust and explainable. |
| **eDifFIQA(T)** (recommended learned score) | `opencv/opencv_zoo` ONNX; also via `uniface` | 7.3 MB | CC-BY-4.0 | 5–15 ms/face | MobileFaceNet backbone + quality head, input = aligned 112×112, range [-1,1] normalisation. State-of-the-art FIQA family, tiny, ONNX — the practical MagFace substitute on CPU. |
| MagFace | `IrvingMeng/MagFace` (Apache-2.0, PyTorch checkpoints on Google Drive/Baidu, no official ONNX); packaged as facetorch "verify" (`tomas-gajarsky/facetorch-verify-magface`, 262 MB, iResNet100) | 262 MB | Apache-2.0 | 300–600 ms/face | Embedding magnitude is trained to encode quality (bounded roughly 10–110; higher = better). Elegant because one forward pass gives identity + quality, but it means a second, heavy recognition model next to ArcFace. Only via the torch pack. |
| SER-FIQ | `pterhoer/FaceImageQuality` (no licence file, MXNet-era) | – | unclear | ~100 stochastic forward passes per face | Not CPU-friendly; skip. |
| CR-FIQA | `fdbtrs/CR-FIQA` (no licence file on GitHub; PyTorch iResNet50/100) | 170–260 MB | unclear | 150–500 ms/face | Good research method, no convenient packaging; skip. |

Suggested combined weight per face observation: `w = det_score × clip((iod_px − 20)/40, 0, 1) × sigmoid(k·(q − q0))`, where `q` is eDifFIQA (or ArcFace norm) and `q0` is calibrated at the quality below which matches start failing.

### 3.3 Reference gallery of impersonated people

- **Who:** 30–100 people most abused in Polish scam ads (politicians, TV presenters, footballers, well-known doctors, business figures). Keep `person_id`, canonical name, name variants and **inflected forms** (Lewandowski/Lewandowskiego/Lewandowskim) for text matching.
- **Images:** 5–10 per person, deliberately diverse: frontal and 3/4, different years, glasses/no glasses, TV-studio lighting (this is what scam footage is cut from). Wikimedia Commons is the licence-safe source. Reject gallery images with low quality score — a bad template poisons every comparison.
- **Storage:** L2-normalised 512-d embeddings for every template **plus** a quality-weighted mean per person (re-normalised). A NumPy matrix is enough; no vector DB needed at this scale.
- **Query aggregation for video:** track faces across sampled frames (IoU or embedding continuity), compute a quality-weighted mean embedding per track, match the track — not single frames. This is where quality weighting pays off.
- **Scoring:** `score = max(cos(q, centroid), mean of top-3 cos(q, templates))`.
- **Thresholds (starting points for ArcFace R50 cosine similarity; calibrate on 100+ real ad faces with labelled negatives):**
  - ≥ 0.50: confident match
  - 0.38–0.50: candidate — show as "possible", require a second signal (name in OCR/ASR text)
  - < 0.35: unknown
  - Also require a margin: best − second-best person ≥ 0.08.
- **Unknown faces matter too:** cluster unmatched track embeddings across ads (agglomerative, cos ≥ 0.5). The same anonymous "doctor"/AI avatar/stock actor recurring across ads is a strong campaign link even without a name.
- **Deepfakes and recognition:** face-swap and lip-sync fakes are built to preserve identity, and lip-sync fakes reuse real footage, so ArcFace generally still matches the impersonated person. Fully synthetic look-alikes score lower (often in the "candidate" band) — which is why the text cross-check matters.

---

## 4. OCR, QR codes, URLs

| Engine | pip | Model size | Licence | Polish diacritics | CPU latency (est., one 1080p screenshot) | Assessment |
|---|---|---|---|---|---|---|
| **RapidOCR + PP-OCRv6 small** (recommended; it is the `rapidocr` 3.10 default) | `rapidocr` 3.10.0, `onnxruntime` | det 9.9 MB + rec 21.2 MB | Apache-2.0 | **Yes — verified:** all 18 Polish letters (ąćęłńóśźż + capitals) are in `ppocrv6_dict.txt`; `pl` is in the model's supported-language list. One unified model for 50 languages (Chinese, English, Japanese + 46 Latin-script). | 1–2.5 s (vendor: 0.61 s/img on Xeon 8350C with ONNX Runtime) | Best accuracy/size/speed trade-off; torch-free. Vendor in-house benchmark: det Hmean 84.1, rec 81.3 (vs 75.2 / 73.7 for PP-OCRv5 mobile). No per-language Latin numbers published, so sanity-check on 20 real Polish ads. |
| RapidOCR + PP-OCRv6 tiny | same; `model_type: tiny` | det 1.8 MB + rec 4.5 MB | Apache-2.0 | Yes (verified in `ppocrv6_tiny_dict.txt`) | 0.4–0.9 s (vendor 0.22 s) | For per-frame video OCR (burned-in subtitles). Rec accuracy 73.5 vs 81.3 for small. |
| RapidOCR + PP-OCRv6 medium | `model_type: medium` | 62 MB + 77 MB | Apache-2.0 | Yes | 5–12 s (vendor 3.31 s on ORT) | Slow under ONNX Runtime; not worth it on this CPU. |
| RapidOCR + PP-OCRv5 mobile det + `latin` rec | `Rec.lang_type: latin`, `ocr_version: PP-OCRv5` | 4.8 MB + 7.9 MB | Apache-2.0 | Yes (verified in `ppocrv5_latin_dict.txt`) | 1–2.5 s | Proven fallback if v6 misbehaves on some input. |
| PaddleOCR | `paddleocr` 3.7.0 + `paddlepaddle` | same models + ~200 MB framework | Apache-2.0 | Yes | similar | Same models with a heavier runtime. No reason to prefer it here. |
| EasyOCR | `easyocr` 1.7.2 (last PyPI release 2024-09) | CRAFT 79 MB + latin rec ~15 MB + torch | Apache-2.0 | Yes (`['pl','en']`) | 3–10 s | Works, slower and generally less accurate than PP-OCRv5/v6; needs torch. |
| Tesseract 5 `pol` | `pytesseract` 0.3.13 + system `tesseract` + `pol.traineddata` | a few MB | Apache-2.0 | Yes | 0.5–2 s | **Not installed on the machine** (needs a system package). Good on clean dark-on-light documents; poor on scene text, coloured backgrounds, stylised captions — i.e. ads. Skip. |
| docTR / OnnxTR | `python-doctr` 1.1.0 / `onnxtr` 0.9.0 (torch-free) | 10–100 MB | Apache-2.0 | Depends on the recognition vocab; default vocabs are French-centric. Multilingual vocab models exist but Polish coverage is **not verified**. | 1–3 s | Reasonable second engine; verify diacritics before relying on it. |
| Surya, VLM-based OCR (PaddleOCR-VL, Florence-2, etc.) | – | 0.5–2 GB | mixed | Yes | 10 s – minutes | Too slow on this CPU. Skip. |

OCR tips for ads and screenshots:

- Upscale small inputs so the short side is ≥ 736 px; for the browser address bar, crop the top ~12% of the screenshot and upscale 2–3x before OCR.
- Keep boxes and confidences — the boxes feed the layout descriptor (Section 2.4) and the text-inpainted hashes (Section 2.1).
- Post-correct with a Polish word list only on low-confidence tokens; do not "correct" brand names, URLs or amounts.
- For video, OCR only keyframes plus one frame per second in the subtitle band; dedupe lines with RapidFuzz.

**QR codes and URL extraction**

| Tool | pip | Licence | Notes |
|---|---|---|---|
| **zxing-cpp** (recommended) | `zxing-cpp` 3.1.1 (wheels for cp310–cp314, 1.1 MB) | Apache-2.0 | `zxingcpp.read_barcodes(img)`; robust, multi-code, also DataMatrix/Aztec/EAN. 5–30 ms. |
| OpenCV | `cv2.QRCodeDetector().detectAndDecodeMulti` (or `QRCodeDetectorAruco`) | Apache-2.0 | Already installed; weaker on small/blurred codes. Fallback. |
| WeChatQRCode | `opencv-contrib-python` + `opencv_zoo/models/qrcode_wechatqrcode` (1 MB) | Apache-2.0 | Best on tiny codes (CNN detector + super-resolution), but needs the contrib build, which conflicts with the plain `opencv-python` InsightFace pulls in. Only if QR recall becomes a problem. |
| pyzbar | `pyzbar` 0.1.9 (2022) | MIT | libzbar is present on the machine; unmaintained. Third fallback. |
| qreader | `qreader` 3.16 | MIT | YOLOv8 + pyzbar; pulls ultralytics + torch. Skip. |

URL extraction from OCR text: regex for scheme-less domains (`[a-z0-9-]+(\.[a-z0-9-]+)+(/\S*)?`), validate the suffix with `tldextract`, then generate OCR-confusion variants (`l/1/I`, `O/0`, `rn/m`, missing dot) and keep the ones that resolve. Flag punycode/homoglyph domains (`idna`, Unicode script mixing) — that is itself a campaign feature.

---

## 5. Video and audio

### 5.1 Keyframes and video hashing

| Tool | How | Licence | CPU cost (est.) | Notes |
|---|---|---|---|---|
| **ffmpeg scene filter** (recommended) | `ffmpeg -i in.mp4 -vf "select='gt(scene,0.3)',scale=640:-2" -vsync vfr kf_%04d.jpg` plus a uniform pass `-vf fps=1` | LGPL/GPL (system binary) | 20–60x real time | Scene threshold 0.3–0.4 for ads. Cap at ~30 frames per video. `-skip_frame nokey` (I-frames only) is the cheapest possible sampler. |
| PySceneDetect | `scenedetect` 0.7.3 (released 2026-11-08) | BSD-3 | 10–40x real time | `AdaptiveDetector` handles fast cuts/flash better; gives shot boundaries → shot-length histogram (template feature). |
| **DIY vPDQ-style video signature** (recommended) | PDQ for each keyframe (quality ≥ 50), dedupe within video; video↔video similarity = share of frames in A with a match in B at Hamming ≤ 31 | – | ms per frame | Handles trims, re-ordered scenes, and clips embedded in longer videos, which fixed-length video hashes do not. |
| vPDQ (Meta) | `vpdq` 0.2.5 — **sdist only**, needs CMake + FFmpeg dev libraries to compile | BSD (ThreatExchange) | – | Same idea as the DIY version; the build is a risk with no benefit at POC scale. |
| TMK+PDQF (Meta) | C++ only in `meta/ThreatExchange`; no pip package | BSD | – | Fixed-length, FAISS-friendly, but designed for same-length videos. Skip. |
| videohash | `videohash` 3.0.1 (last release 2022) | MIT | 1–3 s/video | 64-bit hash from a frame collage + wavelet hash. Breaks under trims, added intros, aspect changes. At most a cheap bonus signal. |
| Embedding pooling | mean of SigLIP 2 keyframe embeddings + keep the per-frame set | – | – | Mean vector for coarse kNN; frame-set max-matching for verification. |

### 5.2 ASR for Polish

Published accuracy (WER %, Polish):

| Model | FLEURS | Common Voice 9 | VoxPopuli | MLS | Source |
|---|---|---|---|---|---|
| Whisper tiny | 45.6 | 45.3 | 31.4 | 34.2 | Whisper paper, App. D |
| Whisper base | 30.8 | 32.8 | 22.1 | 22.8 | same |
| Whisper small | 14.7 | 16.9 | 13.3 | 11.2 | same |
| Whisper medium | 8.0 | 10.1 | 10.1 | 6.5 | same |
| Whisper large-v2 | 5.4 | 7.6 | 7.8 | 5.0 | same |
| Whisper large-v3 | – | – | – | 8.88 | Parakeet/Canary paper (different text normalisation — not comparable with the row above) |
| **Parakeet-TDT 0.6B v3** | – | – | – | **7.28** | same paper; HF card lists 7.31 |

(The Whisper figures were extracted from the paper's appendix tables by automated reading; spot-check before quoting them on a slide.)

| Engine | Model ID | Size | Licence | Speed on this CPU (est., x real time) | Assessment |
|---|---|---|---|---|---|
| **onnx-asr + Parakeet-TDT 0.6B v3 int8** (recommended) | `istupakov/parakeet-tdt-0.6b-v3-onnx`; `onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v3", quantization="int8")` | 652 MB encoder + 18 MB decoder | lib MIT; model CC-BY-4.0 | **10–17x** (third-party report: ~17x on an i7-4790, ~30x on i7-12700KF; onnx-asr's own table: 36x on a 9800X3D) | 25 European languages incl. Polish; accuracy in Whisper-large territory at a fraction of the cost; punctuation and casing; token timestamps; transducer, so far fewer hallucinations on music/silence than Whisper. Torch-free, FFmpeg-free (WAV/NumPy in — extract audio with `ffmpeg -ar 16000 -ac 1`). Most models are limited to 20–30 s per call; onnx-asr has built-in VAD chunking for longer audio. No language tag in the output. |
| faster-whisper small int8 | `Systran/faster-whisper-small` | 484 MB | MIT | 1.5–3x (beam 5); 3–5x (beam 1 + VAD). Reference: 7.6x on i7-12700K, 8 threads, beam 5 | Fallback and language-ID provider. WER 11–17% on Polish: fine for keywords and embeddings, shaky on names. `WhisperModel("small", device="cpu", compute_type="int8", cpu_threads=4)`, `language="pl"`, `vad_filter=True`. |
| faster-whisper base / tiny int8 | `Systran/faster-whisper-base` / `-tiny` | 145 / 75 MB | MIT | 6–10x / 12–20x | Polish WER 23–33% / 31–46%: too noisy for narrative similarity. Only for language ID. |
| faster-whisper medium / large-v3-turbo | `Systran/faster-whisper-medium`, `deepdml/faster-whisper-large-v3-turbo-ct2` | 1.53 / 1.62 GB | MIT | 0.4–0.8x / 0.5–1x | Slower than real time here and 1.5 GB each. Not for this machine. |
| whisper.cpp | `pywhispercpp` 1.5.1 (GGML models: small ≈ 466 MB, quantised ≈ 180 MB) | – | MIT | similar to or slightly slower than faster-whisper int8 (README: 2m05 vs 1m42 on the same 13-min clip) | No advantage over faster-whisper here. |

### 5.3 Audio fingerprinting and speaker embeddings

| Signal | Tool | Size | Licence | CPU cost (est.) | Notes |
|---|---|---|---|---|---|
| **Same audio track reused** | Chromaprint: `fpcalc -raw -json -length 0 file` (binary already installed) + `pyacoustid` 1.3.1 | – | MIT wrapper; Chromaprint LGPL/MIT | 50–200x real time | Compare raw 32-bit sub-fingerprints with a sliding offset and bit-error rate (match when BER < ~0.35 over ≥ 10 s). Survives re-encoding and volume changes; **fails** on tempo/pitch shift and when a different music bed is mixed under the same voice — hence the speaker embedding below. |
| **Same narrator / same cloned voice** | WeSpeaker ResNet34-LM ONNX (`Wespeaker/wespeaker-voxceleb-resnet34-LM`), 256-d, features via `kaldi-native-fbank`; or load it through `sherpa-onnx` 2.0.2's speaker-embedding API | 26.5 MB | CC-BY-4.0 | 50–200 ms per 10 s | Use VAD speech segments ≥ 3 s, average embeddings per video. Start at cos ≥ 0.55 for "same voice" and calibrate. Trained on VoxCeleb; speaker verification transfers across languages reasonably well, but this is unverified for Polish TTS output. |
| alternative | SpeechBrain ECAPA-TDNN `speechbrain/spkrec-ecapa-voxceleb` | 83 MB + torch + speechbrain | Apache-2.0 | 100–300 ms per 10 s | Equivalent quality; only if torch is installed anyway. |
| alternative | Resemblyzer (GE2E) `Resemblyzer` 0.1.4 (2023) | 17 MB + torch | Apache-2.0 | fast | Old and markedly less accurate than ResNet34/ECAPA. Skip. |

What a voice match means: a clone of celebrity X sits close to X's real voice, so speaker embeddings mostly link ads by **impersonated person** (add reference voice clips to the gallery to get a second identity channel besides the face). A stock TTS narrator reused across unrelated creatives links ads by **operator/toolchain**. Both are useful edges; label them differently.

---

## 6. Text (Polish)

### 6.1 Sentence embeddings

PL-MTEB (Poświata et al., Table 2; 30 tasks; verified from the paper):

| Model | Params | Avg (30) | Clustering (5) | Pair-class. (4) | Retrieval (11) | STS (3) |
|---|---|---|---|---|---|---|
| paraphrase-multilingual-MiniLM-L12-v2 | 118M | 48.91 | 40.68 | 83.40 | 30.40 | 78.68 |
| multilingual-e5-small | 118M | 55.21 | 43.99 | 81.70 | 46.00 | 78.41 |
| multilingual-e5-base | 278M | 56.59 | 44.10 | 82.08 | 47.63 | 79.13 |
| multilingual-e5-large | 560M | 59.06 | 40.60 | 84.57 | 52.43 | 81.41 |
| LaBSE | 471M | 48.52 | 42.40 | 79.27 | 27.36 | 74.67 |
| st-polish-paraphrase-from-mpnet | 124M | 54.80 | 44.53 | 87.06 | 38.33 | 82.83 |
| mmlw-e5-small | 118M | 58.97 | **48.91** | 86.67 | 46.43 | 82.05 |
| **mmlw-roberta-base** | 124M | **62.52** | 48.00 | 88.16 | 53.60 | **85.20** |
| mmlw-roberta-large | 435M | 61.58 | 44.58 | 89.15 | 49.91 | 85.23 |

| Model | HF id | Size on disk | Licence | Polish | CPU latency (est., ~128 tokens) | Use |
|---|---|---|---|---|---|---|
| **multilingual-e5-small** (core pick) | `intfloat/multilingual-e5-small` (`onnx/model.onnx`) | 470 MB + 17 MB tokenizer | MIT | Yes (100 languages) | 20–45 ms | Torch-free via `tokenizers` + `onnxruntime` + mean pooling (15 lines). Prefix **both** sides with `"query: "` for similarity/clustering. Multilingual, so it also links the same scam script translated into Czech/Romanian/German. The repo's `model_qint8_avx512_vnni.onnx` (118 MB) is tuned for VNNI CPUs — use the fp32 file on this machine. |
| **mmlw-roberta-base** (best Polish quality; torch pack) | `sdadas/mmlw-roberta-base` | 498 MB | Apache-2.0 | Yes (Polish-specific) | 50–100 ms | +7 STS points and +4 clustering points over e5-small on PL-MTEB. No official ONNX export (needs sentence-transformers + torch, or a one-off `optimum` export). Mostly Polish-only: cross-language linking will be weaker. |
| mmlw-e5-small | `sdadas/mmlw-e5-small` | 471 MB | Apache-2.0 | Yes | 20–45 ms | Best PL-MTEB clustering score at MiniLM cost; safetensors only (torch or self-export). Good middle ground if exporting to ONNX once. |
| paraphrase-multilingual-MiniLM-L12-v2 | via `fastembed` 0.9.1 (Qdrant ONNX export, ~220 MB) or HF `onnx/model.onnx` 470 MB | 0.22–0.47 GB | Apache-2.0 | Yes | 20–45 ms | Easiest possible install (`fastembed.TextEmbedding`). Similar STS to e5-small, weaker clustering/retrieval. Acceptable fallback. |
| multilingual-e5-base | `intfloat/multilingual-e5-base` (`onnx/model.onnx`) | 1.11 GB | MIT | Yes | 60–130 ms | +1.4 avg over small for 2.4x the disk. Not worth it. |
| BGE-M3 | `BAAI/bge-m3` (`onnx/model.onnx_data`) | 2.27 GB | MIT | Yes | 400–900 ms | Strong and long-context (8k), but heavy for this box. Not in the PL-MTEB table I could verify. Nice-to-have only. |
| EmbeddingGemma 300M | `onnx-community/embeddinggemma-300m-ONNX` (q4 197 MB; fp32 1.23 GB) | 0.2–1.2 GB | **Gemma licence** | Yes (100+ languages) | 80–200 ms | Modern small multilingual model; no Polish benchmark verified. Candidate to A/B if time allows. |
| stella-pl / stella-pl-retrieval | `sdadas/stella-pl` (6.2 GB), `sdadas/stella-pl-retrieval-mini-8k` (1.74 GB, Gemma licence) | 1.7–6.2 GB | MIT / Gemma | Yes | seconds | Top of Polish leaderboards but far too large here. |
| Silver Retriever | `ipipan/silver-retriever-base-v1.1` | 498 MB | CC-BY-SA-4.0 | Yes | 50–100 ms | Retrieval-tuned (question→passage); not the right tool for symmetric narrative similarity. |
| jina-embeddings-v3 | `jinaai/jina-embeddings-v3` | 1.15–2.3 GB | **CC-BY-NC-4.0** | Yes | 300–700 ms | Heavy + NC. Skip. |

What to embed: (a) cleaned OCR text of the creative, (b) ASR transcript (chunked to ~200 tokens, mean-pooled), (c) landing-page headline + first paragraphs. Keep them as separate vectors and separate edge types — OCR overlay text and voice-over often tell different halves of the story.

### 6.2 Near-duplicate text

| Tool | pip | Licence | Notes |
|---|---|---|---|
| **MinHash + LSH** | `datasketch` 2.0.0 | MIT | Shingle on **character 5-grams** of normalised text (robust to OCR noise and Polish inflection), 128 permutations, LSH threshold 0.5–0.6 Jaccard. Microseconds per query. |
| SimHash | `simhash` 2.1.2 (2022) or 20 lines of NumPy | MIT | 64-bit, Hamming ≤ 3–6 for near-exact copies. Good as a cheap blocking key. |
| Pairwise verification | `rapidfuzz` 3.14 (`token_set_ratio`, `partial_ratio`) | MIT | Confirms LSH candidates and finds shared boilerplate ("Tylko dziś", "Zarejestruj się w 2 minuty"). |

Normalisation before hashing (this matters more than the algorithm): Unicode NFKC; lower-case; map homoglyphs (Cyrillic а/е/о/р/с → Latin) and strip zero-width characters — scammers use both to dodge filters; make a second variant with Polish diacritics stripped (many ads are typed without them); replace numbers/amounts with `<NUM>`, URLs with `<URL>`, celebrity names with `<PERSON>` (templates get re-skinned with a different celebrity and payout). The **masked template** is the campaign signal; the masked-out values are per-ad attributes.

### 6.3 Keywords, lemmatisation, NER

| Task | Tool | Size | Licence | Polish | Notes |
|---|---|---|---|---|---|
| Lemmas + POS + NER | **spaCy `pl_core_news_md`** 3.8.0 | 49 MB | lib MIT; **model GPL-3.0** | Yes | Lemma acc 0.936, NER F1 0.827 (3.7 model card). Labels: `persName`, `orgName`, `placeName`, `geogName`, `date`, `time`. ~5–15 ms per ad. `sm` (20 MB): 0.931 / 0.801. `lg` (573 MB): 0.942 / 0.841 — not worth the disk. |
| Lemmas only, permissive | `simplemma` 2.0.0 | small | MIT | Yes | Dictionary-based, context-free, very fast. Good enough for keyword normalisation. |
| Morphological analysis | `morfeusz2` 1.99.15 (9 MB manylinux wheel) | 9 MB | BSD-2-style (SGJP) | Yes — the reference analyser | Returns all analyses (no disambiguation). Best use here: **generate inflected forms of celebrity/brand names** for the gazetteer. |
| Full NLP pipeline | `stanza` 1.15 `pl` | ~0.3–0.5 GB + torch | Apache-2.0 | Yes | More accurate tagging/lemmas than spaCy md, much slower. Skip. |
| Keywords (statistical) | `yake` 0.7.3 (`lan="pl"`) | small | **LGPL-3.0** | Yes (built-in stoplist) | No model, <10 ms. Works on short, noisy ad text. |
| Keywords (embedding) | `keybert` 0.9.0 with the same e5/mmlw encoder | 0 extra | MIT | Yes (via the multilingual encoder) | Pass Polish stopwords (`spacy.lang.pl.STOP_WORDS`) and lemmatised candidates. As a dependency it pulls sentence-transformers → torch; if staying torch-free, re-implement (candidate n-grams → embed → cosine to document → MMR) in ~30 lines. |
| Cluster labels | c-TF-IDF over lemmas per campaign (scikit-learn) | 0 | BSD | – | **Recommended for naming campaigns in the UI**: top distinctive lemmas per cluster. |
| Zero-shot NER (brands, products, amounts, drugs) | GLiNER: `urchade/gliner_multi-v2.1` (1.16 GB; ONNX int8 349 MB at `onnx-community/gliner_multi-v2.1`), `knowledgator/gliner-x-small` (ONNX int8 173 MB) | 0.17–1.2 GB | Apache-2.0 | Multilingual; Polish quality unverified | Nice-to-have for open label sets ("produkt", "lek", "bank", "platforma inwestycyjna"). `gliner` pulls torch. |
| Polish NER (transformer) | `clarin-pl/FastPDN` (HerBERT, 496 MB) | 496 MB | CC-BY-4.0 | Yes (fine-grained NKJP/KPWr classes) | More accurate than spaCy md; needs torch + transformers. Optional. |
| Phones | `phonenumbers` 9.0 (`PhoneNumberMatcher(text, "PL")`) | small | Apache-2.0 | Yes | Normalises to E.164 — a hard linking key. |
| Amounts, promises | regex: `\d[\d\s.,]*\s?(zł|złotych|PLN|tys\.?|mln|EUR|€|USD|\$)`, percentages, "dziennie/tygodniowo/miesięcznie" | – | – | – | Mask for templating; keep values as attributes. |
| Other hard identifiers | regex for URLs/domains, e-mail, Telegram/WhatsApp handles, IBAN (`PL\d{26}`), crypto addresses, promo codes | – | – | – | Exact-match edges; highest precision of all text features. |
| Language ID | `lingua-language-detector` or fastText `lid.176.ftz` (<1 MB) | small | Apache-2.0 / CC-BY-SA | – | Tag non-Polish ads; cross-language duplicates are a campaign signal. |

`ipipan/pl_nask` exists on HF (spaCy transformer pipeline, GPL-3.0, 475 MB wheel, last updated 2023, 2 downloads). Interesting given the organiser, but it is undocumented and transformer-based (needs torch); not recommended without a closer look.

Person names: do not rely on NER alone. Match lemmatised/fuzzy tokens against the **same reference list used for faces** — that gives the cross-modal check "face says X, text says X" (or face says X while text says nothing: a silent impersonation).

---

## 7. AI-generated content detection (extra feature, low weight)

### 7.1 AI-generated text

| Method | Requirements | CPU feasibility | Polish | Honest assessment |
|---|---|---|---|---|
| Binoculars (`ahans30/Binoculars`, BSD-3, last commit 2024) | Two LLMs (default Falcon-7B pair, ~28 GB) | No | English models by default. The PolEval 2025 machine-generated-text task was won by a Binoculars variant with Polish LMs (models not named in the abstract). | The right idea, wrong hardware. |
| Fast-DetectGPT (`baoguangsheng/fast-detect-gpt`, MIT) | One or two causal LMs for token log-probs | Feasible only with small LMs: `sdadas/polish-gpt2-small` (554 MB, LGPL) ≈ 0.3–1 s per ad; `speakleash/Bielik-1.5B-v3.0-Instruct` (3.2 GB, Apache-2.0) ≈ 5–20 s per ad | No published Polish validation for small-LM scoring | Zero-shot curvature degrades with weak scoring models, short texts (< ~100 tokens), and OCR/ASR noise — which is exactly this data. |
| RADAR (`TrustSafeAI/RADAR-Vicuna-7B`, 1.42 GB RoBERTa-large classifier) | torch | 0.5–1.5 s per ad | English-trained | Not validated for Polish. |
| HF classifiers: `openai-community/roberta-base-openai-detector` (GPT-2 era), `fakespot-ai/roberta-base-ai-text-detection-v1` (499 MB, Apache-2.0), `desklib/ai-text-detector-v1.01` (1.74 GB, MIT), `yaya36095/xlm-roberta-text-detector` (1.1 GB, MIT, multilingual claim) | torch | 0.1–1.5 s per ad | English-centric; the multilingual one has no verifiable Polish evaluation | Expect high false-positive and false-negative rates out of domain; literature (CEAID benchmark, 2026 fine-tuning studies) confirms detectors are weaker outside English. |

**Recommendation:** do not ship an AI-text verdict. It is unreliable on short Polish ad copy, and it is also weakly informative: legitimate advertisers use LLM copy too. If a score is wanted for the demo, compute Polish-GPT-2 perplexity as an "experimental" attribute and never let it drive linking. More useful and cheaper text signals: machine-translation artefacts, missing diacritics, homoglyphs, recurring boilerplate — all captured in Section 6.2. If there were more time: fine-tune HerBERT on the PolEval 2025 ŚMIGIEL dataset.

### 7.2 AI-generated images

| Detector | HF id | Size | Licence | CPU latency (est.) | Evidence |
|---|---|---|---|---|---|
| **Community Forensics ViT-S** (best open option) | `OwensLab/commfor-model-384` (also `-224`) | 87 MB | MIT | 150–400 ms (384 px); needs torch + timm | CVPR 2025; trained on 2.7M images from 4,803 generators. In an independent 2026 out-of-the-box benchmark of 16 open detectors it ranked first: mean accuracy 0.75–0.78 (the paper's abstract and table disagree), median 0.82 — while the worst (CNNSpot) scored 0.375 and UnivFD 0.407. The same study: "no universal winner", thresholds poorly calibrated, and **JPEG/resize/social-media robustness was not tested**. |
| UniversalFakeDetect (CLIP ViT-L/14 + linear) | original repo | ~1.7 GB backbone | MIT | 2–5 s | 0.41 mean accuracy in the same benchmark. Skip. |
| CNNDetection (ResNet-50, ProGAN-trained, 2020) | original repo | ~100 MB | – | 100–250 ms | 0.375 mean accuracy; blind to diffusion output. Skip. |
| HF community classifiers: `Ateeqq/ai-vs-human-image-detector` (SigLIP-based, 372 MB, Apache-2.0), `haywoodsloan/ai-image-detector-deploy` (781 MB, Apache-2.0), `Organika/sdxl-detector` (348 MB, **CC-BY-NC-3.0**), `umm-maybe/AI-image-detector` (348 MB, CC-BY-4.0, 2022-era) | see left | 0.35–0.8 GB | mixed | 150–600 ms | Self-reported in-distribution accuracy only; no independent generalisation evidence found. Treat as unvalidated. |
| Provenance metadata | `c2pa-python` (Apache-2.0), PNG text chunks / EXIF / XMP "Software" fields | tiny | – | ms | Zero false positives when present (C2PA manifest, Stable Diffusion/ComfyUI parameters). Usually stripped by social platforms, but landing-page assets often keep it. **Do this first — it is free.** |

**Assessment:** on ad creatives (heavy JPEG, screenshots of screenshots, text overlays, composites of real photo + generated background) expect far lower accuracy than benchmarks. Show at most a low-weight "synthetic-likelihood" attribute with the caveat on screen; never a verdict.

---

## 8. Video deepfake and lip-sync artefacts (low priority)

- **Evidence against relying on open detectors:** Deepfake-Eval-2024 (in-the-wild deepfakes from 2024, incl. lip-sync, face-swap, diffusion; 52 languages) reports that open-source detectors lose roughly 50% (video), 48% (audio) and 45% (image) AUC versus their academic-benchmark results, with many off-the-shelf models near chance. Models tested include GenConViT, FTCN, AASIST, RawNet2, UFD, NPR.
- **facetorch deepfake head:** EfficientNet-B7 from the 2020 DFDC-winning solution (`selimsef/dfdc_deepfake_challenge`, MIT; 270 MB; 66M params; 0.5–1.2 s per face here). Trained on DFDC face-swaps; it predates Wav2Lip-era lip-sync and modern avatar generators. It is the organiser-hinted option, so including it as a per-face score costs little politically — but it should be labelled "DFDC-2020 detector, indicative only".
- **HF frame classifiers** (`prithivMLmods/Deep-Fake-Detector-v2-Model`, `dima806/deepfake_vs_real_image_detection`, ~343 MB ViT-B each, Apache-2.0): self-reported accuracy on their own datasets; no in-the-wild evidence. Skip.
- **Audio deepfake classifiers** (e.g., `MelodyMachine/Deepfake-audio-detection-V2`, wav2vec2-base, 378 MB): same generalisation problem per Deepfake-Eval-2024. Skip.
- **SyncNet** (`joonson/syncnet_python`, MIT): measures audio-visual offset/confidence. Lip-sync generators are trained against a SyncNet-style loss, so their output tends to score *well*; it mainly catches crude dubbing. Needs torch and face tracks. Not worth the time.
- **LipFD** (`AaronComo/LipFD`, NeurIPS 2024; no licence file): research code; skip for a POC.

**Practical, cheap heuristics that are honest about what they are:**

1. **Mouth-region sharpness ratio:** Laplacian variance of the mouth ROI divided by that of the upper face (ROIs from InsightFace's 106 landmarks), averaged over frames. Wav2Lip-style pipelines paste a low-resolution mouth patch; a persistently low ratio is an artefact indicator. Compression can also cause it — indicator only.
2. **Dubbing mismatch:** VAD speech activity vs. mouth-opening signal (landmark distance) correlation over time. Low correlation ⇒ voice-over on unrelated footage (very common in scam ads; technically not a deepfake but the same deception).
3. **Identity/context rule (most reliable):** recognised public figure (face or voice) + investment/medical/giveaway narrative (text) + non-official destination domain ⇒ "likely impersonation". This rule-based flag is far more dependable than pixel forensics and is fully explainable.
4. **Source-footage reuse:** the same real interview clip (PDQ/SSCD match on keyframes, same face track) appearing with *different* audio across ads ⇒ manipulated re-dubs from one source — also a first-class campaign link.

---

## 9. Feature record per ad (what the extractors should emit)

```json
{
  "ad_id": "...",
  "image": {"pdq": "...", "pdq_quality": 87, "phash16": "...", "pdq_text_masked": "...",
            "siglip2": [768], "dinov2": [384], "template": {"grid": [432], "palette_lab": [...], "text_style": {...}}},
  "faces": [{"track_id": 0, "embedding": [512], "quality": 0.71, "n_frames": 14,
             "match": {"person_id": "…", "score": 0.58, "margin": 0.21}}],
  "ocr": {"text": "...", "boxes": [...], "embedding": [384], "minhash": [...], "urls": [...], "qr": [...]},
  "video": {"frame_pdqs": [...], "shot_lengths": [...], "container": {"encoder": "Lavf60.16.100", "fps": 30, "res": "720x1280"}},
  "audio": {"chromaprint": [...], "speaker_embedding": [256], "transcript": "...", "transcript_embedding": [384]},
  "entities": {"persons": [...], "orgs": [...], "amounts": [...], "phones": [...], "domains": [...]},
  "experimental": {"synthetic_image_score": null, "dfdc_face_score": null, "text_perplexity": null}
}
```

Starting thresholds for candidate edges (all to be calibrated on real data):

| Edge type | Metric | Start at |
|---|---|---|
| Same creative | PDQ Hamming | ≤ 31 / 256 (quality ≥ 50) |
| Same creative, edited | ORB+RANSAC inliers; SSCD cosine | ≥ 25–30; ≥ 0.75 |
| Similar look/concept | SigLIP 2 cosine | ≥ 0.85 candidate; ≥ 0.92 strong |
| Same template | DINOv2 cosine + layout-grid cosine | ≥ 0.65 and ≥ 0.8 |
| Same person | ArcFace R50 cosine | ≥ 0.50 (0.38–0.50 with text confirmation) |
| Same text template | MinHash Jaccard (char 5-grams, masked) | ≥ 0.5 |
| Same narrative | e5/mmlw cosine | ≥ 0.85 (e5 scores are compressed into a high range; mmlw ≥ ~0.75) |
| Same audio track | Chromaprint BER | < 0.35 over ≥ 10 s |
| Same voice | WeSpeaker cosine | ≥ 0.55 |
| Hard identifiers | exact match (domain, phone, IBAN, handle) | – |

---

## 10. Nice-to-have list (in priority order)

1. SSCD copy-detection descriptor (best "same base creative" signal; 99 MB + torch).
2. `sdadas/mmlw-roberta-base` for Polish narrative similarity (keep e5-small for cross-language).
3. SigLIP 2 text tower for Polish text→image search and zero-shot tags in the demo UI.
4. facetorch with MagFace + DFDC head — mainly because the organisers named it.
5. Community Forensics ViT-S "synthetic-likelihood" attribute + C2PA/metadata check.
6. GLiNER zero-shot NER for products/brands; FastPDN for fine-grained Polish NER.
7. OWL-ViT B/32 logo proposals if OCR + crop matching misses graphic-only logos.
8. Mouth-sharpness and speech/mouth-correlation heuristics.

## 11. Open risks and things to test first (1–2 hours)

1. `uv add pdqhash` compiles on this machine (no Linux wheel).
2. `rapidocr` default models download and read a real Polish ad screenshot with diacritics intact; time it.
3. `insightface` 2.1 with `buffalo_l` on CPU: time detection at 640×640 and check that `allowed_modules` behaves as in 0.7 (the 2.x line changed defaults — e.g. dual-resolution "Auto" detection size).
4. SigLIP 2 ONNX vision tower: confirm output tensor name/shape and that embeddings of near-duplicate images are close (preprocessing mistakes are the usual failure).
5. `onnx-asr` Parakeet v3 int8: transcribe one 60-s Polish clip, measure real-time factor and eyeball names/brands.
6. e5-small ONNX: confirm mean pooling + `"query: "` prefix reproduce sentence-transformers scores on 3 sentence pairs.
7. Disk after all downloads: `du -sh ~/.cache/huggingface ~/.insightface ~/.cache/uv` — clear `uv cache` if short.

---

## Sources

- Hugging Face model API (`/api/models/<id>?blobs=true`) for every model ID above — sizes, licences, dates (queried 2026-11-21)
- PyPI JSON API for package versions, wheels and release dates (queried 2026-11-21)
- InsightFace: https://pypi.org/project/insightface/ ; https://github.com/deepinsight/insightface/blob/master/python-package/docs/model_zoo.md ; https://github.com/deepinsight/insightface/blob/master/python-package/CHANGELOG.md ; https://github.com/deepinsight/insightface/releases/tag/model-zoo
- facetorch: https://github.com/tomas-gajarsky/facetorch
- OpenCV Zoo (YuNet, SFace, eDifFIQA): https://huggingface.co/opencv/opencv_zoo
- MagFace: https://github.com/IrvingMeng/MagFace ; eDifFIQA: https://github.com/LSIbabnikz/eDifFIQA ; uniface: https://github.com/yakhyo/uniface
- RapidOCR: https://github.com/RapidAI/RapidOCR (`python/rapidocr/default_models.yaml`, `config.yaml`); PP-OCRv6: https://www.paddleocr.ai/v3.7.0/en/version3.x/algorithm/PP-OCRv6/PP-OCRv6.html ; https://arxiv.org/abs/2606.13108
- SigLIP 2: https://arxiv.org/abs/2502.14786 ; https://huggingface.co/google/siglip2-base-patch16-224 ; https://huggingface.co/immich-app/ViT-B-16-SigLIP2__webli
- SSCD: https://github.com/facebookresearch/sscd-copy-detection ; PDQ/vPDQ/TMK: https://github.com/facebook/ThreatExchange ; https://pypi.org/project/pdqhash/ ; https://pypi.org/project/vpdq/
- Phishpedia: https://github.com/lindsey98/Phishpedia
- Whisper per-language WER: https://arxiv.org/abs/2212.04356 (Appendix D) ; faster-whisper benchmarks: https://github.com/SYSTRAN/faster-whisper
- Parakeet-TDT 0.6B v3: https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3 ; https://arxiv.org/abs/2509.14128 ; onnx-asr: https://github.com/istupakov/onnx-asr ; https://huggingface.co/istupakov/parakeet-tdt-0.6b-v3-onnx ; third-party CPU figures: https://github.com/groxaxo/parakeet-tdt-0.6b-v3-fastapi-openai
- WeSpeaker: https://huggingface.co/Wespeaker/wespeaker-voxceleb-resnet34-LM ; SpeechBrain ECAPA: https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb
- PL-MTEB: https://arxiv.org/abs/2405.10138 ; sdadas models: https://huggingface.co/sdadas
- spaCy Polish models: https://huggingface.co/spacy/pl_core_news_md ; https://github.com/explosion/spacy-models/releases
- AI-text detection: https://github.com/ahans30/Binoculars ; https://github.com/baoguangsheng/fast-detect-gpt ; PolEval 2025: https://aclanthology.org/2025.poleval-main.4/ ; CEAID: https://arxiv.org/abs/2509.26051
- AI-image detection: https://arxiv.org/abs/2411.04125 (Community Forensics) ; https://arxiv.org/abs/2602.07814 (out-of-the-box benchmark)
- Deepfake-Eval-2024: https://arxiv.org/abs/2503.02857 ; DFDC winner: https://github.com/selimsef/dfdc_deepfake_challenge ; SyncNet: https://github.com/joonson/syncnet_python
