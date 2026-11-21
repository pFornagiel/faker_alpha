# FakeTrace — Feature Extraction, ML Models, Similarity & Clustering Methodology

> Scientific and engineering reference for FakeTrace's multimodal feature extraction, CPU-only ONNX models, rarity-weighted Noisy-OR evidence fusion, 3-level hierarchical clustering, and open-set campaign assignment (`ftf/config.py`, `ftf/pipeline.py`, `ftf/web.py`, `ftf/vision.py`, `ftf/faces.py`, `ftf/text.py`, `ftf/text_gemma.py`, `ftf/gazetteer.py`, `ftf/llm.py`, `ftf/similarity.py`, `ftf/cluster.py`).
>
> See also: [`docs/PIPELINE_WALKTHROUGH.md`](PIPELINE_WALKTHROUGH.md) · [`docs/WEB_FETCHING_METHODOLOGY.md`](WEB_FETCHING_METHODOLOGY.md) · [`docs/METHODOLOGY.md`](METHODOLOGY.md)

---

## 1. Design Philosophy: Hierarchy of Campaign Signals

Published threat-intelligence investigations of social-media scam-ad ecosystems (Bitdefender 2026; CSIRT KNF 2026; KommAustria 2025; Starov et al. 2018; Kotzias et al. 2025) converge on the same empirical hierarchy:

1. **Operator-level artifacts (Tier S)** — tracking pixels, analytics/ad-account IDs, landing-builder tenant UUIDs, lead-form endpoints, advertiser IDs, registrable domains, and bulk registration bursts — are high-precision proofs of a shared operator even when creative narratives and spoofed celebrities rotate completely.
2. **Kit, creative & narrative artifacts (Tier M)** — templated backend API paths, TDS query-parameter shapes, DOM tag-shingle templates, embedded landing-page images, perceptual creative hashes, entity-masked text templates, and promoted fake-platform names — bridge sub-campaigns when domains and pixels rotate.
3. **Contextual & thematic artifacts (Tier W)** — impersonated public figures, LLM-inferred scam category / narrative template, and non-CDN hosting IPs — describe a *shared playbook* rather than a shared operator. Famous celebrities (e.g., Rafał Brzoska, Robert Lewandowski) are natural **hubs** targeted by dozens of independent criminal groups and must never link a campaign alone.

Every model in FakeTrace runs **locally on CPU via ONNX Runtime** (~460 MB total for default models; no GPU or PyTorch required), keeping deployment portable and inference predictable.

---

## 2. Complete Feature Taxonomy

### 2.1 Discrete Indicator Signals (`config.INDICATOR_WEIGHT`)

| Family | Tier | Signal Key(s) | Extraction Method & Filtering | Prior Weight | Empirical Utility (Real Data) |
|---|---|---|---|---|---|
| `duplicate` | **S** | `file_sha`, `near_duplicate` | Exact SHA-256 of HTML/screenshot (`0.99`); or `text_minhash >= 0.93` + (`phash >= 0.95` or absent) + shared `landing_domain` (`0.97`) | `0.99` / `0.97` | Deduplicates repeated reports & identical captures cleanly. |
| `infra_ids` | **S** | `fb_pixel`, `tiktok_pixel`, `ga`, `gtm`, `gads`, `ym`, `clarity`, `hotjar`, `sentry_key`, `recaptcha`, `adsense`, `phone`, `email`, `telegram`, `whatsapp`, `wallet`, `form_endpoint` | Regex extraction across HTML, HAR bodies, saved `.js`/`.js.pobrane` scripts, and URL query params (`pxl`, `fbpx`, etc.). Canonicalized to bare IDs (`fb_pixel`: 14–17 digits). `form_endpoint` strips per-visit session UUIDs via `template_path()`. | `0.80–0.95` (`fb_pixel`: `0.92`, `wallet`: `0.95`, `form_endpoint`: `0.90`) | **Highest-precision operator linkers** (e.g., shared FB Pixel `2012165449475163` links Case 1 ↔ Case 2). |
| `tracking` | **S** | `ad_id`, `adset`, `affiliate`, `tds_host`, `tenant_uuid`, `campaign_param` | Extracted from URL params, HAR redirects, `info.json`, and OCR `"Identyfikator biblioteki"`. `ad_id` canonicalized to bare ID; per-visit `session_uuids` subtracted from `tenant_uuid`. | `0.60–0.95` (`ad_id`: `0.95`, `tenant_uuid`: `0.90`, `affiliate`: `0.85`) | Links multi-creative ads and shared landing-builder workspaces across domains. |
| `domain` | **S** | `landing_domain`, `redirect_domain`, `page_host`, `ocr_domain`, `reg_burst` | Offline PSL (`include_psl_private_domains=True`), generic/CDN/decoy filtered. `page_host` suppressed when `landing_domain` already matches. `ocr_domain` cross-matched against `landing_domain`. `reg_burst` (`registrar\|ns_pair\|YYYY-MM-DD`) emitted only for non-generic NS. | `0.60–0.90` (`landing_domain`: `0.90`, `ocr_domain`: `0.85`, `reg_burst`: `0.75`) | Bridges dead pages, cross-narrative domains (Case 2 ↔ Case 3 on `healthlinkq.pro` + NICENIC/Cloudflare burst), and screenshot-only leads. |
| `advertiser` | **S** | `advertiser_id`, `advertiser_name` | From yt-dlp `.info.json` and tightened OCR proximity heuristic strictly above standalone `"Sponsorowane"`/`"Sponsored"`. | `0.95` / `0.80` | Links multiple creatives from the same Facebook Page / advertiser account. |
| `kit` | **M** | `build_id`, `api_template`, `script_hash`, `script_name`, `path_template`, `favicon`, `param_signature`, `css_name`, `form_fields` | Host-agnostic POST API templates (`POST /api/v1/trigger/field/{id}/`), canonical TDS `param_signature` (volatile click params removed, sorted `k=shape`), first-party JS SHA-1 & normalized names (generic libs filtered), Shodan `mmh3` favicon (blank hashes filtered). | `0.35–0.75` (`build_id`: `0.75`, `api_template`: `0.65`, `script_hash`: `0.65`, `param_signature`: `0.45`) | **Primary cross-narrative bridge** (links Case 1/2 ↔ Case 48/61 despite rotated celebrities, domains, and platform names). |
| `assets` | **M** | `asset_phash` | 64-bit pHash of up to 60 SHA-256-deduplicated landing-page images (`>= 6 KB`, `>= 120 px`), matched at Hamming distance `<= 4`. Blank hashes filtered. | `0.70` | Strong signal on cloned fake-news templates (5+ shared page images in Case 48 ↔ Case 61). |
| `offer` | **M** | `product` | Folded `product_or_platform_name` (`> 2` chars) from Stage 4 LLM / rule fallback. | `0.75` | Links rotating domains promoting the same invented brand (*"Orzeł Fundaris"* links Case 3 ↔ Case 48). |
| `narrative` | **M** | `phrase` | Normalized LLM `distinctive_phrases` (`>= 15` chars, `>= 3` words, excluding `GENERIC_PHRASES` like `"dowiedz sie wiecej"`). | `0.55` | Useful secondary signal for verbatim boilerplate slogans. |
| `hosting` | **W** | `ip`, `ns_pair` | Non-CDN IPv4/IPv6 (`net.is_cdn_ip` exact CIDRs); sorted top-2 non-generic nameservers (`GENERIC_NS_RX` filtered). | `0.45` / `0.35` | Supporting signal; account-scoped Cloudflare NS pairs reinforce `reg_burst` without over-weighting alone. |

### 2.2 Continuous & Special Signals (`config.CONTINUOUS`, `persons`, `concept`)

| Family | Tier | Signal Key | Representation & Matching Metric | Ramp `(lo, hi, w_max)` / Weight | Empirical Utility |
|---|---|---|---|---|---|
| `narrative` | **M** | `text_minhash` | 128-perm MinHash (`seed=7`) over 4-word shingles; max of narrative text and OCR text (`> 80` chars) | `(0.30, 0.80, 0.85)` | High precision for copied/lightly edited scam articles (`0.99` on Case 1 ↔ Case 2). |
| `narrative` | **M** | `masked_minhash` | 128-perm MinHash after `gazetteer.mask_entities()` replaces known persons & first names with `<per>` | `(0.35, 0.80, 0.75)` | Detects *"same article template, swapped celebrity"* variants (`5/5` on synthetic swap benchmark). |
| `narrative` | **M** | `title_template` | 3-char n-gram Jaccard on person/number/media-masked titles (`len > 15`) | `(0.80, 0.97, 0.70)` | Links identical sensationalist clickbait headline patterns (`1.00` on Case 48 ↔ Case 61). |
| `narrative` | **M** | `text_embedding` | Max centered cosine of `multilingual-e5-small` (384-d) and optional `EmbeddingGemma-2` (768-d) | `(0.45, 0.85, 0.55)` | Captures paraphrased Polish narratives once inverse-density centering removes anisotropy. |
| `visual` | **M** | `phash` | `1 - Hamming(64-bit pHash) / 64` across non-UI creative screenshots & keyframes | `(0.80, 0.97, 0.80)` | Robust near-duplicate / re-compressed creative matching. |
| `visual` | **M** | `clip` | Max centered cosine of `CLIP ViT-B/32` (512-d, ONNX int8) on cropped creatives | `(0.55, 0.85, 0.60)` | Secondary creative-look backup; limited separation on visually heterogeneous creatives. |
| `visual` | **M** | `dinov2` | Max centered cosine of `DINOv2-small` (768-d: `L2(CLS) \|\| L2(mean_patch)`) on cropped creatives | `(0.55, 0.85, 0.55)` | Secondary layout/template backup; strongest on shared graphic templates. |
| `visual` | **M** | `same_face_image` | Raw ArcFace cosine `>= 0.80` between any two high-quality faces (`quality >= 0.22`) | Fixed `+0.45` | Detects reuse of the exact same portrait photograph across two ads/pages (`cos = 1.00` on Case 2 ↔ Case 3). |
| `kit` | **M** | `dom_template` | 128-perm MinHash (`seed=11`) over 5-gram HTML tag sequences | `(0.45, 0.90, 0.60)` | Captures identical HTML skeleton even when copy and images are swapped (`1.00` on Case 1 ↔ Case 2). |
| `persons` | **W** | `face_unknown` | Max ArcFace cosine across **unidentified** (non-gallery) high-quality faces (`quality >= 0.22`) | `(0.45, 0.65, 0.60)` | Links recurring fictional personas ("doctor" / stock actor) across ads. |
| `persons` | **W** | `face_identity`, `person_named` | Gallery-matched visual person (`0.30`) or text-named person (`0.22`), rarity-discounted | `0.30` / `0.22` (rarity-scaled) | Contextual signal only; weak-only cap prevents celebrity hubs from linking campaigns. |
| `concept` | **W** | `scam_type`, `narrative_template`, `creative_format`, `media`, `llm_extra:*` | Closed-enum agreement from LLM/rules; `scam_type` disagreement triggers `×0.60` penalty | `0.15` / `0.30` / `0.15` / `0.20` / `0.25·r` | Groups playbook families at L2 and provides negative contradiction evidence against false merges. |

---

## 3. Modality Deep Dive

### 3.1 Web & Infrastructure Indicators (`ftf/web.py`, `ftf/enrich.py`, `ftf/net.py`)

- **Canonicalization**: Cross-layer mismatches (e.g., `pxl=2012...` in URLs vs bare `2012...` in HTML `fbq('init')`, or `library=123` in OCR vs bare `123` in `.info.json`) are eliminated by normalizing `fb_pixel` and `ad_id` to bare IDs at extraction time.
- **TDS Parameter Shape (`param_signature`)**: Volatile per-click tokens (`VOLATILE_PARAMS`: `fbclid`, `gclid`, `clickid`, `utm_visit`, `access_token`, `_trk`, `key`, etc.) are stripped; remaining parameters are sorted alphabetically and abstractly typed (`U` = UUID, `D<n>` = digit string of length `n`, `A<n>` = alphanumeric of length `n`, `S` = string). Two domains running the same Traffic Distribution System produce identical signatures (e.g., `utm_campaign=A10&utm_content=A10&utm_id=A20&utm_medium=A10`).
- **Session vs. Tenant UUID Disambiguation**: In HAR logs, per-visit UUIDs (e.g., UUIDv7 in `utm_visit` or `/trigger/` POST URLs) are collected into `session_uuids` and subtracted from `tenant_uuid`, preserving genuine landing-builder workspace UUIDs found in static asset paths (`/_cdn/production/landing-cdn/<uuid>/...`).
- **DOM Tag-Shingle MinHash**: Extracts the ordered sequence of HTML tag names, builds 5-grams (`tag_shingles(tags, k=5)`), and computes a 128-permutation MinHash (`seed=11`). Resilient to text edits, celebrity swaps, and dynamic attributes while remaining sensitive to template reuse.
- **Exact CDN Filtering**: `net.is_cdn_ip()` filters Cloudflare, Fastly, Google, Meta, CloudFront, and Akamai edge prefixes via exact CIDRs so only origin/dedicated IPs emit the `ip` indicator.

### 3.2 Visual & OCR (`ftf/vision.py`)

- **Black-Frame Evasion Filtering (`_is_nonblack_frame`)**: CSIRT KNF documented scam video ads padded with black frames to evade moderation hashing. `video_keyframes()` extracts `MAX_VIDEO_KEYFRAMES = 8` evenly spaced frames via `ffmpeg`, rejecting any frame with size `<= 2000` bytes, grayscale mean `<= 12`, or standard deviation `<= 8` — and re-validates cached frames on disk so stale black frames never leak across runs.
- **Aspect-Aware Creative Cropping (`crop_content`, `creative_crop`)**: Uniform margins are trimmed on all images. On **portrait screenshots only** (`kind == "screenshot"` and `H/W > 1.35`), `creative_crop()` locates the tallest contiguous vertical band of picture-like rows (`nonbg > 55%` and `std > 18`), refusing to crop below `35%` of original area. This strips Facebook/Instagram mobile feed chrome without slicing square/landscape video keyframes.
- **UI Screenshot Exclusion (`is_ui_screenshot`)**: Platform ad-library details pages (containing `"identyfikator biblioteki"`, `"szczegoly reklamy"`, `"library id"`, etc.) have identical UI layout across unrelated campaigns. They are tagged `kind = "ui_screenshot"` so they are excluded from `clip`, `dino`, and `phash` comparisons while still yielding OCR text, `ad_id`, `advertiser_name`, QR URLs, and faces. Crucially, `"komentarze"` is *not* in `UI_MARKERS` because fake-news landing pages routinely contain fabricated comment sections.
- **Embeddings & OCR**:
  - `CLIP ViT-B/32` (Xenova ONNX int8, 512-d) and `DINOv2-small` (Xenova ONNX, 768-d via concatenated L2-normalized CLS token and L2-normalized mean patch token, then L2-normalized again) operate on white-square-padded `224x224` bicubic crops.
  - `RapidOCR` (PP-OCRv6, Apache-2.0) runs at up to `1600 px` max side, keeping detections with confidence `>= 0.6` sorted in reading order.

### 3.3 Face Recognition & Identity (`ftf/faces.py`)

- **Detection & Alignment**: Pure-ONNX implementation of **SCRFD `det_10g`** (strides 8/16/32, `FACE_DET_THRESHOLD = 0.6`, NMS `0.4`, min side `36 px` for creatives / `48 px` for page assets), followed by **closed-form deterministic 2D Umeyama similarity alignment** (`_umeyama_2d`, Umeyama 1991) mapping 5 facial landmarks onto the standard `112x112` ArcFace template (`ARC_TEMPLATE`).
- **Embedding & Quality Gating**: **ArcFace `w600k_r50`** produces L2-normalized 512-d embeddings. Inspired by MagFace (Meng et al. 2021) and eDifFIQA (Babnik et al. 2024), each face receives a lightweight quality proxy:
  \[
  q = \operatorname{clip}(\text{det\_score}, 0, 1) \cdot \operatorname{clip}\!\left(\frac{\text{side}}{112}, 0.2, 1.0\right) \cdot \operatorname{clip}\!\left(\frac{\operatorname{Var}(\nabla^2 I_{\text{gray}})}{150}, 0.3, 1.0\right)
  \]
- **Reference Gallery & Margin Guard (`identify`)**: The gallery (`data/reference_faces/<Person>/*.jpg`, 29 Polish public figures compiled from NASK/CSIRT KNF/Demagog reports via `tools/build_face_gallery.py`) stores one mean-normalized ArcFace vector per person in a safe numeric `.npz` (`allow_pickle=False`) + JSON sidecar cache. Identification requires:
  1. \(q \ge \text{FACE\_QUALITY\_MIN} = 0.22\),
  2. \(\cos_{\text{top-1}} \ge \text{FACE\_MATCH\_THRESHOLD} = 0.42\), and
  3. \(\cos_{\text{top-1}} - \cos_{\text{top-2}} \ge \text{FACE\_MARGIN\_MIN} = 0.06\) (when \(\ge 2\) gallery identities exist).
- **Celebrity Hubness vs. Recurring Unknown Personas**: Recognized celebrities enter `persons` (Tier W, `0.30` prior, hub-discounted), whereas **unmatched** high-quality faces are compared directly across materials via `face_unknown` (ramp `0.45..0.65 -> 0.60`), detecting recurring fictional actors/doctors without needing them in the gallery.

### 3.4 Text, Polish Gazetteer & Narrative Embeddings (`ftf/text.py`, `ftf/text_gemma.py`, `ftf/gazetteer.py`)

- **Unicode Folding & Confusable Resistance (`gazetteer.fold`)**: Applies NFKC normalization, lowercasing, explicit Polish `ł -> l` mapping, NFKD combining-mark stripping, and zero-width character removal (`U+200B..U+200F`, `U+2060`, `U+FEFF`), defeating Unicode homoglyph and invisible-joiner obfuscation documented by Gen Digital (2026) and UTS #39.
- **Polish Entity Extraction & Masking**: `PERSONS` (47 public figures), `BRANDS` (22 Polish/global brands), and `MEDIA` (14 spoofed news outlets) use compiled word-boundary inflected regexes (`_alias_regex`) supporting Polish declensions (e.g., `andrzeju dudzie`). Dedicated logic (`_matches_robert_lewandowski`) prevents feminine `"Lewandowska"` and unrelated masculine first names (`"Tomasz Lewandowski"`) from false-matching `"Robert Lewandowski"`. `mask_entities()` replaces all aliases (including 4-char surnames `Tusk`/`Duda`) and common Polish first names with `<per>` prior to `masked_minhash` and `title_template`.
- **Windowed `multilingual-e5-small` (default)**: ONNX int8 (384-d). Because `e5-small` truncates at 512 tokens while fake-news landing pages can exceed 1,500 words, `embed_text()` extracts up to 3 balanced 220-word windows (**lead, middle, end**), prepends `"query: "`, mean-pools each window, **L2-normalizes every window**, averages them, and re-normalizes.
- **Optional `EmbeddingGemma-2` (`FTF_GEMMA=1`)**: `google/embeddinggemma-2` (Apache-2.0, ONNX q4 175 MB, 768-d, single pass up to `MAX_TOKENS = 1024`, prefix `"task: sentence similarity | query: "`). In our Polish STS benchmark (`research/05_embeddinggemma2_eval.md`), Gemma-2 outperforms e5-small (Spearman `0.772` vs `0.695` on SICK-R-PL; `0.926` vs `0.895` on CDSC-R; raw separation margin `0.089` vs `0.003` on organizer pages) at ~4–6× higher CPU cost, so it is integrated as an opt-in max-fused second narrative signal.

### 3.5 LLM Structured Feature Augmentation (`ftf/llm.py`, `tools/llm_refine.py`)

Following the LLM feature-augmentation literature (CAAFE — Hollmann et al. 2023; FeatLLM — Han et al. 2024; Viswanathan et al. 2024; TnT-LLM — Wan et al. 2024), Stage 4 asks an LLM (`claude -p --model haiku --json-schema ...`, fallback `gemini-2.5-flash` at `temperature=0`, fallback deterministic `llm.rules()`) to derive structured, closed-vocabulary attributes from combined titles, URLs, ad-library metadata, OCR, and page text:

- **Closed enums** (per-field validated via `_ENUM_BY_FIELD` in `normalise()`): `scam_type` (13 values), `narrative_template` (16 values), `creative_format` (10 values).
- **Entity & offer extraction**: `impersonated_persons`, `impersonated_brands` (normalized onto gazetteer canonical names), `spoofed_media_outlet`, `product_or_platform_name` (promoted to Tier M `product`), `fictional_persona`, `distinctive_phrases` (promoted to Tier M `phrase`, filtered against `GENERIC_PHRASES`), `evidence` (verbatim quotes).
- **Negative evidence**: Disagreeing non-`"other"` `scam_type` values activate a multiplicative contradiction penalty (`× 0.60`) unless overridden by Tier S operator evidence.
- **Caching & isolation**: Cached on disk in `data/cache/llm/<sha1[:20]>.json` keyed by `(backend, model, extra_schema, input_text)`. Precomputed attributes discovered by the iterative refinement script `tools/llm_refine.py` (`data/cache/llm_extra_values.json`) are loaded **strictly when `use_llm=True`**.

---

## 4. Mathematical Formulation of Similarity, Clustering & Open-Set Assignment

### 4.1 Smooth Rarity Weighting & Hub Suppression (`Corpus.is_hub`, `Corpus.rarity`)

Inspired by Fellegi–Sunter (1969) term-frequency adjustment (as implemented in Splink — Linacre et al. 2022), sharing a rare indicator value (appearing in 2 of 1,000 ads) is far stronger evidence than sharing a value appearing in half the corpus.

Let \(N = \max(1, |\mathcal{D}|)\) be the corpus size and \(df(k)\) be the document frequency of key \(k = (\text{type}, \text{value})\).

**Hub predicate (`is_hub`)**: A key \(k\) is treated as a hub (`weight = 0.0, ignored = True`) if and only if **all** of the following hold:
1. \(N \ge \text{HUB\_MIN\_CORPUS} = 15\) (prevents hub dropping on tiny corpora where one real campaign can exceed 50%),
2. \(df(k) \ge \text{HUB\_MIN\_COUNT} = 6\) and \(df(k) / N > \text{HUB\_FRACTION} = 0.50\), and
3. Not exempt: when \(N < 30\), keys whose family is in `HUB_EXEMPT_FAMILIES = ("duplicate", "infra_ids", "tracking", "advertiser")` are exempt from hub suppression.

**Smooth rarity factor (`rarity`)**: For non-hub keys with \(n = \max(2, df(k))\):
\[
r(k) =
\begin{cases}
0 & \text{if } \text{is\_hub}(k) \\
1 & \text{if } N \le 3 \\
\operatorname{clip}\!\left(\dfrac{\ln\!\left(\frac{N + 1}{n + 1}\right)}{\ln\!\left(\frac{N + 1}{2}\right)},\; 0.15,\; 1.0\right) & \text{otherwise.}
\end{cases}
\]

The effective evidence weight of a matched discrete indicator \(t\) with value \(v\) is:
\[
w(t, v) = \text{prior}(t) \cdot \bigl(0.35 + 0.65 \cdot r(t, v)\bigr)
\]
The `0.35` floor ensures that a genuinely repeated campaign-specific indicator shared across a moderate subset (e.g., 4 of 10 items) still retains meaningful signal, while truly rare values (`df = 2`) approach full prior weight as \(N\) grows. Ignored hubs are **retained in `Link.evidence` with `ignored=True`** so analysts can audit every suppressed signal.

### 4.2 Inverse-Density Embedding Centering (Anisotropy Correction)

Pretrained transformer embeddings such as `multilingual-e5-small` suffer from severe **anisotropy** — vectors occupy a narrow cone on the unit sphere (Ethayarajh 2019; Mu & Viswanath 2018). On Polish scam landing pages, raw e5 cosines between completely unrelated pages sit at `0.89–0.93`, leaving virtually zero dynamic range.

Subtracting the **unweighted** corpus mean \(\bar{\mu} = \frac{1}{M}\sum_i x_i\) fails whenever one campaign dominates the corpus (e.g., C1 represents 5 of 10 materials in the organizer dataset): \(\bar{\mu}\) gets pulled into C1, pushing true C1 pairs (`48 ↔ 61`) below the similarity threshold!

FakeTrace solves this with **inverse-density weighted centering** (`Corpus.__init__`, `ftf/similarity.py:140-168`):
1. Normalize per-material mean vectors \(m_i \in \mathbb{R}^d\) to unit length (`M`), compute the pairwise cosine matrix \(S = M M^\top\).
2. Compute each item's local cluster degree at modality threshold \(\tau\) (`0.95` for `text`/`text_gemma`, `0.75` for `clip`/`dino`):
   \[
   \text{deg}_i = \sum_{j=1}^{M} \mathbb{I}[S_{ij} \ge \tau], \qquad w_i = \frac{1}{\max(\text{deg}_i, 1)}, \qquad N_{\text{eff}} = \sum_{i=1}^{M} w_i
   \]
3. Only if \(N_{\text{eff}} \ge 5.0\) (`_CENTRE_MIN_REPS`), compute the cluster-balanced background mean and center each vector:
   \[
   \mu = \frac{\sum_{i=1}^{M} w_i m_i}{N_{\text{eff}}}, \qquad \tilde{x} = \frac{x - \mu}{\|x - \mu\|_2 + 10^{-9}}
   \]
   If \(N_{\text{eff}} < 5.0\), centering returns `None` rather than emitting noisy uncentered cosines.

#### Empirical Comparison on the 10-Case Organizer Corpus (`multilingual-e5-small`)

| Pair | Ground-Truth Relationship | Raw Cosine | Unweighted Centered | **Inverse-Density Centered** | Effect vs. `0.45` Ramp Floor |
|---|---|---:|---:|---:|---|
| **1 ↔ 2** | Same narrative (C1 Brzoska) | `1.000` | `0.991` | **`0.993`** | Strong match (`+0.55`) |
| **48 ↔ 61** | Same narrative (C1 *"37 minut"*) | `0.959` | `0.440` *(dropped!)* | **`0.501`** *(recovered!)* | Recovered above `0.45` floor |
| **3 ↔ 48** | Different narrative in C1 (Olejnik vs 37 min) | `0.937` | `0.143` | **`0.201`** | Cleanly below `0.45` |
| **14 ↔ 47** | Unrelated health supplements (Metabo RX vs Uromexil) | `0.953` | `0.395` | **`0.411`** | Cleanly below `0.45` |
| **1 ↔ 10** | Unrelated (Brzoska investment vs Ronaldo casino) | `0.904` | `-0.314` | **`-0.303`** | Strongly negative (clean separation) |

### 4.3 Piecewise-Linear Continuous Ramps & Noisy-OR Evidence Fusion

Each continuous similarity \(x \in \mathbb{R}\) for signal \(s\) with parameters \((lo, hi, w_{\max}, f)\) maps to an evidence weight via:
\[
w_s(x) = w_{\max} \cdot \operatorname{clip}\!\left(\frac{x - lo}{hi - lo},\; 0,\; 1\right)
\]

Evidence items are grouped into their evidence family \(f \in \mathcal{F}\) and combined in two stages using the **Noisy-OR** operator:
\[
\operatorname{NoisyOR}(W) = 1 - \prod_{w \in W} \bigl(1 - \operatorname{clip}(w, 0, 0.999)\bigr)
\]
\[
s_f = \operatorname{NoisyOR}\!\bigl(\{w_e : e \in E_f,\; \neg e.\text{ignored},\; w_e > 0\}\bigr), \qquad
p_{\text{raw}} = \operatorname{NoisyOR}\!\bigl(\{s_f : f \in \mathcal{F}\}\bigr)
\]

Two domain guards produce the final link score \(p\):
1. **Weak-only cap**: Let \(s_{\text{SM}} = \max_{f \in \text{Tier S} \cup \text{Tier M}} s_f\). If \(s_{\text{SM}} < 0.25\), then \(p \leftarrow \min(p_{\text{raw}}, 0.45)\).
2. **Contradiction guard**: Let \(s_{\text{S}} = \max_{f \in \text{Tier S}} s_f\). If both materials have non-`"other"` disagreeing `scam_type` and \(s_{\text{S}} < 0.50\), then \(p \leftarrow 0.60 \cdot p\).

Alongside \(p\), FakeTrace computes:
- **Comparability**: \(\text{comparable} = (\exists \text{ shared continuous modality}) \lor (\exists \text{ shared indicator type})\).
- **Playbook score**: \(\text{playbook} = \operatorname{NoisyOR}\bigl(s_{\text{narrative}}, s_{\text{concept}}, s_{\text{visual}}, s_{\text{persons}}, s_{\text{offer}}\bigr)\).
- **Edge relation**:
  - `duplicate` if \(s_{\text{duplicate}} \ge 0.97\);
  - `same_campaign` if \(p \ge 0.55\) and \((s_{\text{S}} \ge 0.50 \lor s_{\text{SM}} \ge 0.70 \lor |\{f \in \text{S}\cup\text{M} : s_f \ge 0.30\}| \ge 2)\);
  - `similar` if \(p \ge 0.30 \lor \text{playbook} \ge 0.45\);
  - `none` otherwise.

### 4.4 3-Level Clustering & HDBSCAN Baseline (`ftf/cluster.py`)

Given all pairwise `Link` objects:

1. **L0 — Duplicates**: Union-Find over edges with `relation == "duplicate"`.
2. **L1 — Campaigns**:
   - *Step 1 (Operator Cores)*: Union-Find over `relation == "duplicate"` or \((s_{\text{S}} \ge \text{CORE\_S\_MIN} = 0.60 \land p \ge 0.55)\).
   - *Step 2 (Comparable Average-Linkage Agglomeration)*: Iteratively merges the pair of clusters \((C_i, C_j)\) maximizing
     \[
     \operatorname{score}(C_i, C_j) = \max\!\left(
       \frac{1}{|K_{ij}|}\sum_{(a,b) \in K_{ij}} p(a,b),\quad
       \mathbb{I}\!\left[\max_{(a,b) \in C_i \times C_j} p(a,b) \ge 0.85\right] \cdot \max_{(a,b)} p(a,b)
     \right)
     \]
     where \(K_{ij} = \{(a,b) \in C_i \times C_j : \text{comparable}(a,b)\}\), stopping when \(\max \operatorname{score} < 0.55\). Averaging strictly over comparable pairs prevents incomplete materials (e.g., screenshot-only vs. HAR-only) from dragging down cluster cohesion.
3. **L1.5 — Message Variants**: Inside each L1 campaign, Union-Find over `duplicate` or any strong content signal (`text_minhash`, `masked_minhash`, `title_template`, `phash` with `weight >= 0.45`), cleanly separating sub-narratives operated by the same actor.
4. **L2 — Playbook Families**: Runs `agglomerate()` on L1 campaigns using `playbook` scores (`FAMILY_MERGE = 0.40`, `strong = 0.75`), surfacing *"same scam recipe, unconfirmed operator"* as a distinct graph layer.
5. **Ablation Baseline (`hdbscan_baseline`)**: Runs `sklearn.cluster.HDBSCAN(min_cluster_size=2, metric="precomputed", allow_single_cluster=True)` on distance matrix \(D_{ab} = 1 - p(a,b)\) (on the 10-case organizer corpus, FakeTrace L1 achieves ARI `1.00` vs HDBSCAN ARI `0.35`, because HDBSCAN's density criterion struggles with singleton campaigns and mixed-size clusters).

### 4.5 Open-Set Assignment & Scale Blocking (`cluster.assign`, `similarity.candidate_pairs`)

- **Open-Set Assignment (`cluster.assign`)**: For a new material \(x\) compared against existing L1 campaigns \(\{C_k\}\), each campaign \(C_k\) is scored from its links \(L_k\):
  - Let \(\text{top2}_k\) be the top-2 comparable \(p\) values in \(L_k\) and \(m_k = \max_{l \in L_k} l.p\).
  - \(\text{score}(x, C_k) = \max\bigl(\operatorname{mean}(\text{top2}_k),\; m_k \text{ if } m_k \ge 0.75 \text{ else } 0,\; \min(m_k, 0.54) \text{ if } m_k \ge 0.55 \text{ else } 0\bigr)\).
  - Decisions:
    - `duplicate` (if any `duplicate` link and not a merge proposal),
    - `merge_proposal` (`>= 2` campaigns with `score >= 0.55`),
    - `known_campaign` (top campaign `score >= 0.55`),
    - `candidate_review` (`0.40 <= top_score < 0.55` **and** at least one Tier S/M family excluding `concept` reaches `>= 0.30`),
    - `new_campaign` (otherwise; records `similar_playbook` if `top_score >= 0.30`).
- **Scale Blocking (`candidate_pairs`)**: Exact all-pairs for \(N \le 400\). For \(N > 400\), generates candidate pairs in sub-quadratic time via (a) an inverted index over discrete indicators (skipping values occurring in \(> \max(50, 0.02 N)\) materials) and (b) top-\(k\) (\(k = 15\)) cosine nearest neighbors in `text` and `clip` spaces.

---

## 5. Verification, Regression & Evaluation Protocol

```bash
# Unit tests for features, centering, hub guards, gazetteer, LLM, similarity & clustering
.venv/bin/pytest tests/test_feature_extraction_and_ml.py

# Real-data regression tests (when organizer dataset is present locally)
.venv/bin/pytest tests/test_real_data_regression.py

# Full leave-one-out + 37 synthetic variant stress tests + supervised metrics
.venv/bin/python tools/evaluate.py --labels data/labels_dane.csv
```

On the 10-case organizer sample (`docs/RESULTS.md`), the pipeline achieves pairwise P/R/F1 = `1.00`, B-cubed P/R = `1.00`, ARI = `1.00` (vs HDBSCAN `0.35`), `10/10` leave-one-out accuracy, and `35/37` strict (`37/37` including `candidate_review`) across missing-page, missing-creative, domain-rotated, celebrity-swapped, and cropped/recompressed variants.

---

## 6. Authoritative Academic & Standards References

### Record Linkage, Probabilistic Fusion & Hashing
1. **Fellegi, I. P., & Sunter, A. B.** (1969). *A Theory for Record Linkage*. **Journal of the American Statistical Association (JASA)**, 64(328), 1183–1210. <https://doi.org/10.1080/01621459.1969.10501049>
2. **Linacre, R., Lindsay, S., Manassis, T., Slade, Z., Hepworth, T., Kennedy, R., & Bond, A.** (2022). *Splink: Free software for probabilistic record linkage at scale*. **International Journal of Population Data Science**, 7(3). <https://doi.org/10.23889/ijpds.v7i3.1794> · <https://github.com/moj-analytical-services/splink>
3. **Broder, A. Z.** (1997). *On the resemblance and containment of documents*. **Compression and Complexity of Sequences (SEQUENCES 1997)**, pp. 21–29. <https://doi.org/10.1109/SEQUEN.1997.666900>

### Text Embeddings, Polish Benchmarks & Anisotropy
4. **Wang, L., Yang, N., Huang, X., Yang, L., Majumder, R., & Wei, F.** (2024). *Multilingual E5 Text Embeddings: A Technical Report*. **arXiv:2402.05672**. <https://arxiv.org/abs/2402.05672>
5. **Poświata, R., Dadas, S., & Perełkiewicz, M.** (2024). *PL-MTEB: Polish Massive Text Embedding Benchmark*. **arXiv:2405.10138**. <https://arxiv.org/abs/2405.10138>
6. **Mu, J., & Viswanath, P.** (2018). *All-but-the-Top: Simple and Effective Postprocessing for Word Representations*. **ICLR 2018**. <https://arxiv.org/abs/1702.01417>
7. **Ethayarajh, K.** (2019). *How Contextual are Contextualized Word Representations? Comparing the Geometry of BERT, ELMo, and GPT-2 Embeddings*. **EMNLP-IJCNLP 2019**, pp. 55–65. <https://aclanthology.org/D19-1006/>

### Vision, Copy Detection & Face Recognition
8. **Radford, A., Kim, J. W., Hallacy, C., Ramesh, A., Goh, G., Agarwal, S., et al.** (2021). *Learning Transferable Visual Models From Natural Language Supervision (CLIP)*. **ICML 2021**, PMLR 139, pp. 8748–8763. <https://arxiv.org/abs/2103.00020>
9. **Oquab, M., Darcet, T., Moutakanni, T., Vo, H., Szafraniec, M., Khalidov, V., et al.** (2023). *DINOv2: Learning Robust Visual Features without Supervision*. **TMLR 2024 / arXiv:2304.07193**. <https://arxiv.org/abs/2304.07193>
10. **Pizzi, E., Roy, S. D., Ravindra, S. N., Goyal, P., & Douze, M.** (2022). *A Self-Supervised Descriptor for Image Copy Detection (SSCD)*. **CVPR 2022**, pp. 14532–14542. <https://arxiv.org/abs/2202.10261>
11. **Guo, J., Deng, J., Lattas, A., & Zafeiriou, S.** (2021). *Sample and Computation Redistribution for Efficient Face Detection (SCRFD)*. **ICLR 2022 / arXiv:2105.04714**. <https://arxiv.org/abs/2105.04714>
12. **Deng, J., Guo, J., Xue, N., & Zafeiriou, S.** (2019). *ArcFace: Additive Angular Margin Loss for Deep Face Recognition*. **CVPR 2019**, pp. 4690–4699. <https://arxiv.org/abs/1801.07698>
13. **Umeyama, S.** (1991). *Least-Squares Estimation of Transformation Parameters Between Two Point Patterns*. **IEEE Transactions on Pattern Analysis and Machine Intelligence (TPAMI)**, 13(4), 376–380. <https://doi.org/10.1109/34.88573>
14. **Meng, Q., Zhao, S., Huang, Z., & Zhou, F.** (2021). *MagFace: A Universal Representation for Face Recognition and Quality Assessment*. **CVPR 2021**, pp. 14225–14234. <https://arxiv.org/abs/2103.06627>
15. **Babnik, Ž., Peer, P., & Štruc, V.** (2024). *eDifFIQA: Towards Efficient Face Image Quality Assessment Based on Denoising Diffusion Probabilistic Models*. **IEEE Transactions on Biometrics, Behavior, and Identity Science (TBIOM)**. <https://arxiv.org/abs/2401.10666>

### LLM Feature Augmentation & Text Clustering
16. **Hollmann, N., Müller, S., & Hutter, F.** (2023). *Large Language Models for Automated Data Science: Introducing CAAFE for Context-Aware Automated Feature Engineering*. **NeurIPS 2023**. <https://arxiv.org/abs/2305.03403>
17. **Han, S., Yoon, J., Arik, S. Ö., & Pfister, T.** (2024). *Large Language Models Can Automatically Engineer Features for Few-Shot Tabular Learning (FeatLLM)*. **ICML 2024**. <https://arxiv.org/abs/2404.09491>
18. **Viswanathan, V., Gashteovski, K., Gashteovski, K., Lawrence, C., Wu, T., & Neubig, G.** (2024). *Large Language Models Enable Few-Shot Clustering*. **Transactions of the Association for Computational Linguistics (TACL)**, 12, 321–333. <https://aclanthology.org/2024.tacl-1.18/>
19. **Wan, M., Safavi, T., Jauhar, S. K., Kim, Y., Counts, S., Neville, J., et al.** (2024). *TnT-LLM: Text Mining at Scale with Large Language Models*. **KDD 2024**. <https://arxiv.org/abs/2403.12173>

### Clustering, Threat Intelligence & Standards
20. **Campello, R. J. G. B., Moulavi, D., & Sander, J.** (2013). *Density-Based Clustering Based on Hierarchical Density Estimates (HDBSCAN)*. **PAKDD 2013**, LNCS 7819, pp. 160–172. <https://doi.org/10.1007/978-3-642-37456-2_14>
21. **Traag, V. A., Waltman, L., & van Eck, N. J.** (2019). *From Louvain to Leiden: guaranteeing well-connected communities*. **Scientific Reports**, 9, 5233. <https://doi.org/10.1038/s41598-019-41695-z>
22. **Starov, O., Zhou, Y., Zhang, J., Miramirkhani, N., & Nikiforakis, N.** (2018). *Betrayed by Your Dashboard: Discovering Malicious Campaigns via Web Analytics*. **WWW 2018**, pp. 227–236. <https://doi.org/10.1145/3178876.3186089>
23. **Kotzias, P., et al.** (2025). *Ctrl+Alt+Deceive: Quantifying User Exposure to Online Scams*. **NDSS 2025**. <https://www.ndss-symposium.org/wp-content/uploads/2025-1816-paper.pdf>
24. **Unicode Consortium.** *Unicode Technical Standard #39: Unicode Security Mechanisms (Confusables & Skeletons)*. <https://unicode.org/reports/tr39/>
25. **OASIS.** *STIX Version 2.1 — Structured Threat Information Expression*. <https://docs.oasis-open.org/cti/stix/v2.1/stix-v2.1.html>
