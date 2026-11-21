# FakeTrace — End-to-End Pipeline Walkthrough

> A step-by-step engineering guide tracing **what happens to a material from raw input to campaign decision**, including an explicit audit log of **fixed bugs, heuristics, weird design choices, and known limitations**.
>
> Companion deep-dives:
> - [`docs/WEB_FETCHING_METHODOLOGY.md`](WEB_FETCHING_METHODOLOGY.md) — SSRF safety, multi-profile capture, semantic cloaking classification, OSINT enrichment & external sources
> - [`docs/FEATURES_AND_ML_METHODOLOGY.md`](FEATURES_AND_ML_METHODOLOGY.md) — feature taxonomy, ML models, inverse-density centering, Noisy-OR scoring & 3-level clustering
> - [`docs/METHODOLOGY.md`](METHODOLOGY.md) — concise Polish summary

---

## 1. High-Level Architecture

Every suspicious ad, landing page, archive, screenshot, video, URL, or free-text lead passes through five phases:

```text
+------------------------------------------------------------------------------+
| PHASE A: ACQUISITION & SAFE WEB FETCHING                                     |
|   ftf/sources.py · ftf/scheduler.py · ftf/net.py · ftf/capture.py            |
|                                                                              |
|   Public feeds (CERT PL, MS AdLib, Google ATC, Meta API/yt-dlp, LinkedIn)    |
|   or user-submitted URL                                                      |
|     -> SSRF/scheme guard (net.validate_public_url + safe_get)                |
|     -> 3-profile HTTP redirect chase (bot / desktop_pl / fb_mobile+fbclid)   |
|     -> Semantic/structural cloaking classifier (5 verdicts)                  |
|     -> Optional sandboxed Playwright Chromium render (HAR + DOM + shot)      |
+--------------------------------------+---------------------------------------+
                                       |
                                       v
+------------------------------------------------------------------------------+
| PHASE B: ARTIFACT NORMALIZATION & SAFE INGESTION                             |
|   ftf/ingest.py                                                              |
|                                                                              |
|   Folder / ZIP (anti zip-slip/bomb) / Single file / URL capture / Free text  |
|     -> Magic-byte sniffing for Chrome .pobrane/.pobierz & extensionless assets|
|     -> Sibling MHTML deduplication preserving Snapshot-Content-Location URLs |
|     -> Unified `Material` dataclass (pages, images, assets, scripts, videos, |
|        meta, texts, urls, notes)                                             |
+--------------------------------------+---------------------------------------+
                                       |
                                       v
+------------------------------------------------------------------------------+
| PHASE C: 6-STAGE FEATURE EXTRACTION  (ftf/pipeline.py: analyze)              |
|                                                                              |
|   Stage 1 (_stage_web)              HTML/MHTML/HAR/URLs/scripts -> trackers, |
|                                     TDS params, API templates, DOM MinHash,  |
|                                     non-CDN IPs                              |
|   Stage 2 (_stage_visual_and_faces) Video keyframes (anti-black-frame),      |
|                                     creative crop, UI filter, pHash, CLIP,   |
|                                     DINOv2, RapidOCR, QR, SCRFD+ArcFace      |
|   Stage 3 (_stage_text)             Polish folding, gazetteer, YAKE/amounts, |
|                                     MinHash (raw/masked/OCR), title template,|
|                                     e5-small (+ optional EmbeddingGemma-2)   |
|   Stage 4 (_stage_llm)              Closed-enum JSON (Claude CLI / Gemini /  |
|                                     deterministic rule fallback) + cache     |
|   Stage 5 (_stage_enrich)           Concurrent RDAP (RFC 9224), DNS, crt.sh, |
|                                     CERT Polska -> ns_pair, reg_burst        |
|   Stage 6 (_assemble_features)      JSON feature summary + NumPy vector dict |
+--------------------------------------+---------------------------------------+
                                       |
                                       v
+------------------------------------------------------------------------------+
| PHASE D: EXPLAINABLE PAIRWISE SIMILARITY  (ftf/similarity.py)                |
|                                                                              |
|   Corpus statistics: DF rarity, hub suppression, inverse-density centering   |
|   Candidate blocking (all pairs for N<=400; inverted index + kNN for N>400)  |
|   Pair scoring: discrete indicators + continuous ramps + persons + LLM       |
|     -> Noisy-OR within each family -> Noisy-OR across families -> `p`        |
|     -> Guards: weak-only cap (0.45), scam-type conflict (x0.60), comparable  |
|     -> Output: `Link(p, relation, playbook, families, evidence[])`           |
+--------------------------------------+---------------------------------------+
                                       |
                                       v
+------------------------------------------------------------------------------+
| PHASE E: 3-LEVEL CLUSTERING, OPEN-SET ASSIGNMENT & GRAPH EXPORT              |
|   ftf/cluster.py · ftf/graph.py · ftf/engine.py                              |
|                                                                              |
|   Batch build():                                                             |
|     L0 Duplicates       Union-Find on `duplicate` links                      |
|     L1 Campaigns        Operator cores (S >= 0.60) + comparable avg-linkage  |
|     L1.5 Variants       Sub-clusters inside L1 sharing narrative/creative    |
|     L2 Playbook Fam.    Merge campaigns on playbook score (>= 0.40)          |
|     Baseline            HDBSCAN on (1 - p) for ablation                      |
|   Incremental assign(): duplicate / known_campaign / merge_proposal /        |
|                         candidate_review / new_campaign (+ similar_playbook) |
|   Exports: FastAPI/React UI · NetworkX/pyvis HTML · Neo4j Cypher · JSON/CSV  |
+------------------------------------------------------------------------------+
```

---

## 2. Step-by-Step Lifecycle Trace

### Phase A — Acquisition & Safe Web Fetching

#### A1. Discovery & Triage (`ftf/sources.py`, `ftf/scheduler.py`)
- **Input**: Keyword list (`DEFAULT_KEYWORDS`, 10 Polish scam terms) + SQLite watermark (`cert_pl_last_id`).
- **What it does**:
  - Polls CERT Polska warning list (`hole.cert.pl/domains/v2/domains.json`, ETag-cached, delta by `RegisterPositionId`, boundary-aware stem matching via `_match_domain_stems`), Microsoft Ad Library (`countryCodes=151`), Google Ads Transparency Center (`PL=2616`), and optionally Meta Ad Library Graph API (`v27.0`, requires `META_ACCESS_TOKEN`). Each source records explicit status in `sources.LAST_STATUS`.
  - Scores each discovered item with `scheduler.suspicion()` (CERT listing `+0.35`, impersonated persons `+0.30`, brands `+0.15`, scam lexicon `>= 2` hits `+0.20`, risky TLD `+0.15`; capped at `1.0`).
  - Deduplicates against `scheduler_found` via `_dedup_key` (handling URL, domain, `ad_id`, and advertiser-only hits).
  - For items scoring `>= 0.5` (up to `max_analyse`), downloads Meta ad creatives via `yt-dlp` (`facebook:ads`) or captures live URLs via `capture.capture_url(url, render=False)`.
- **Output**: Deduplicated lead records + captured artifacts handed to `Engine.analyse_new()`.
- **Why it exists**: Scam ads live hours to days; automated triage prioritizes high-signal Polish ad-scam leads without triggering on plain banking/OLX phishing (`0.35 < 0.50`).
- **Incomplete-data resilience**: Failed or rate-limited external sources log into `errors` and `LAST_STATUS` without aborting the run. Dead/empty captures are logged as `capture_empty` and skipped rather than poisoning the store with blank materials.

#### A2. Safe Live URL Capture (`ftf/net.py`, `ftf/capture.py`)
- **Input**: Raw URL string + `render: bool` flag.
- **What it does** (5 explicit steps in `capture_url`):
  1. **SSRF & scheme validation** (`net.validate_public_url`): Permits only `http://` and `https://`, resolves DNS, unwraps IPv4-mapped IPv6, and rejects any non-global IP (loopback, RFC1918 private, link-local/cloud metadata `169.254.169.254`, multicast, reserved).
  2. **3-profile redirect chase** (`follow_profile`): Fetches the URL under `bot`, `desktop_pl`, and `fb_mobile` (Android Chrome with `FB_IAB`, `Referer: https://l.facebook.com/`, `X-Requested-With: com.facebook.katana`, and a deterministic synthetic `fbclid`). Follows up to 12 hops across HTTP 3xx, `<meta http-equiv="refresh">`, and small JS redirect stubs (`< 3500` bytes, `< 300` visible chars), re-validating every hop via `net.validate_public_url` and capping reads at `MAX_HTML_BYTES = 3 MB` via `net.safe_get`.
  3. **Semantic & structural cloaking classification** (`classify_cloaking`): Compares 2xx profiles by final registrable domain, normalized `<title>`, visible-text token Jaccard, and 4-gram DOM tag-shingle Jaccard -> outputs verdict in `{cloaking_suspected, bot_blocked, responsive_variant, none, unreachable}`.
  4. **Optional sandboxed Playwright render** (`render_browser`): Launches mobile Polish Chromium (`412x915`, `pl-PL`, `Europe/Warsaw`, `accept_downloads=False`, `service_workers="block"`) with a `ctx.route("**/*", _route_guard)` SSRF interceptor, saving `page.har`, `screenshot.png`, and `rendered.html` (prepended with `<!-- saved from url=... -->`).
  5. **Manifest persistence**: Writes `capture_manifest.json` with resolved IPs, profile summaries, redirect chain, and cloaking verdict/metrics.
- **Output**: Capture dict (`html`, `rendered_html`, `har`, `screenshot`, `meta=[manifest]`, `cloaking`, `cloaking_verdict`, `cloaking_reasons`, `notes`).
- **Why it exists**: Scam landing pages frequently serve a benign white page to datacenter bots and only reveal the offer to Facebook mobile visitors with an `fbclid`.
- **Incomplete-data resilience**: Dead domains produce `verdict="unreachable"` gracefully; if Playwright is unavailable or fails, the HTTP snapshot + manifest still flow downstream.

---

### Phase B — Artifact Normalization & Safe Ingestion (`ftf/ingest.py`)

- **Input**: Incident folder (`load_folder` / `load_dataset`), uploaded file/ZIP (`from_upload`), live URL capture (`from_url`), or pasted text (`from_text`).
- **What it does**:
  - **Zip safety** (`_extract_zip_safely`): Rejects symlinks, blocks zip-slip path traversal (`target.is_relative_to(dest_root)`), enforces `MAX_FILES = 500`, `MAX_FILE_BYTES = 50 MB`, and `MAX_TOTAL_BYTES = 250 MB`.
  - **File classification** (`load_folder`): Walks the incident folder and routes files into `pages` (`.html`/`.htm`, `.har` including dotfile `.har`, `.mhtml`), `images` (creatives/screenshots), `assets` (embedded images under `_files/`, `_pliki/`, `/resources/`, `/assets/`, `/screenshots/viewport`), `scripts` (`.js`, `.mjs`, `.js.pobrane`, `.js.pobierz`), `videos`, `meta` (`*info.json`, `*manifest*`, `*archive_info*`, `*metadata*`, `*dns_ssl*`), `texts`, and `notes` (e.g., `video_deleted.txt` -> `"missing material: ..."`).
  - **Magic-byte sniffing** (`_is_image_file`): For Polish Chrome "Save as" downloads (`.pobrane` / `.pobierz`) or extensionless asset files, reads the first 16 bytes (PNG, JPEG, GIF, BMP, WebP, ICO, AVIF/HEIC) so JS/CSS files are never misrouted into `assets` and scripts are routed to `scripts`.
  - **Sibling MHTML deduplication**: When a directory has both `.html` and `.mhtml`, extracts `Snapshot-Content-Location` from the first 8 KB of the MHTML header and attaches it to `m.urls` and sibling HTML records before dropping the duplicate MHTML parse.
  - **Metadata parsing** (`read_meta`): Normalizes yt-dlp `.info.json`, `capture_manifest.json`, and archiver DNS/SSL JSON into `{ad_library, capture, dns}`.
- **Output**: A `Material` dataclass with deterministic SHA-1 `id`.
- **Why it exists**: Real analyst submissions arrive in wildly inconsistent formats (Polish Chrome "Save Page Complete", Playwright archivers, HAR dumps, bare mobile screenshots, yt-dlp folders, or a single pasted ad caption).
- **Incomplete-data resilience**: Every list field on `Material` may be empty. A material with only a single screenshot, only a HAR, or only two lines of text is first-class and proceeds cleanly through Phase C.

---

### Phase C — 6-Stage Feature Extraction (`ftf/pipeline.py: analyze`)

`pipeline.analyze(m, use_llm=True, progress=None, enrich_online=None)` runs six typed stages in sequence and returns `(feats: dict, vectors: dict[str, np.ndarray | list])`.

#### Stage 1 — Web & Infrastructure (`_stage_web` -> `WebStage`)
- **Input**: `m.pages`, `m.scripts`, `m.urls`, `meta`.
- **What it does**:
  - **HAR** (`web.parse_har`): Parses all HTTP entries using **untruncated full URLs in memory** for redirect-chain chasing; picks the true landing GET document (`_pick_landing_url`, skipping `POST 404` telemetry endpoints); strips volatile click params (`VOLATILE_PARAMS`) to compute canonical `param_signature`; identifies per-visit session UUIDs (`SESSION_PARAM_HINTS`, `/trigger/`, `session` POSTs) and removes them from `tenant_uuid`; templates POST paths (`template_path` -> `form_endpoint`, `api_template`); scans JS/JSON/HTML bodies for trackers (`TRACKER_RX`) and hashes non-generic first-party scripts (`script_hash`); computes Shodan-compatible `mmh3` favicon hashes (`favicon`, filtering `GENERIC_FAVICON_HASHES`); extracts embedded images (`> 4 KB`) for Stage 2.
  - **HTML / MHTML** (`web.extract_html`, `web.parse_mhtml`): Extracts `saved from url=`, canonical/`og:url`, `<title>`, visible text, `<form>` endpoints & field lists, non-generic script/CSS names (after stripping Chrome `.pobrane` and `(1)` suffixes), tracker & contact regexes, and a 128-permutation MinHash of 5-gram DOM tag sequences (`dom_sigs`, `seed=11`).
  - **Saved local scripts** (`web.extract_script_indicators`): Scans `m.scripts` for trackers, `script_name`, and `script_hash`.
  - **Canonical IDs**: Emits bare numeric Facebook pixel IDs (`fb_pixel`), bare Meta ad IDs (`ad_id`) across URL params, `info.json`, and later OCR so all layers intersect cleanly.
  - **IP / CDN filtering** (`net.is_cdn_ip`, `net.is_cloudflare_ip`): Emits `ip` only for non-CDN IPs using exact CIDRs (not broad `/8` blocks) and sets `behind_cloudflare` based on landing-domain IPs (falling back to all HAR IPs if no landing IP is recorded).
- **Output**: `WebStage` (`indicators`, `titles`, `page_texts`, `landing_urls`, `chains`, `ips`, `landing_ips`, `dom_sigs`, `file_shas`, `har_images`, `behind_cloudflare`).
- **Why it exists**: Infrastructure and tracking artifacts are the highest-precision (Tier S / M) campaign linkers because operators reuse pixels, TDS setups, landing builders, and backend APIs even when they rotate domains, celebrities, and headlines.
- **Incomplete-data resilience**: If `m.pages` and `m.urls` are empty (e.g., screenshot-only submission), Stage 1 returns an empty `WebStage` with zero errors.

#### Stage 2 — Visual, OCR & Faces (`_stage_visual_and_faces` -> `VisualStage`)
- **Input**: `m.images`, `m.videos`, `m.assets`, `web_s.har_images`.
- **What it does**:
  - **Video keyframes** (`vision.video_keyframes`): Extracts up to `MAX_VIDEO_KEYFRAMES = 8` evenly spaced frames via `ffmpeg`/`ffprobe`, validating every frame (including cached frames!) with `_is_nonblack_frame` (`mean > 12`, `std > 8`, `> 2 KB`) to defeat black-frame padding evasion.
  - **Creative cropping** (`vision.crop_content`, `vision.creative_crop`): Trims uniform borders on all images; on portrait screenshots (`kind == "screenshot"` and `H/W > 1.35`), isolates the dominant picture band (never cropping below `35%` of original area) so phone/feed UI chrome does not dominate embeddings. Square/landscape video keyframes are never cropped.
  - **Visual features & UI filtering**: Computes 64-bit `phash`, L2-normalized `CLIP ViT-B/32` (512-d) and `DINOv2-small` (768-d, concatenated L2-normalized CLS + mean-patch) embeddings, `RapidOCR` (Polish-capable PP-OCRv6, `score >= 0.6`, reading-order sorted), and OpenCV QR decoding. Screenshots matching `UI_MARKERS` (Meta Ad Library details chrome — intentionally *excluding* `"komentarze"`) are tagged `kind = "ui_screenshot"` and excluded from visual embeddings/pHash while retaining OCR, QR, and faces.
  - **Face detection & identity** (`faces.faces_in_image`, `faces.identify`): Runs `SCRFD det_10g` -> closed-form 2D Umeyama 5-point similarity alignment (`_umeyama_2d`) -> `ArcFace w600k_r50` (512-d). Computes quality proxy (`det_score * size_factor * Laplacian_sharpness`). Matches against the 29-person reference gallery (`data/reference_faces/`) requiring `quality >= 0.22`, cosine `>= 0.42`, and top-1 minus top-2 margin `>= 0.06`. Unmatched faces still keep their embeddings for recurring-persona matching.
  - **Deduplicated landing-page assets**: Combines `m.assets` and `har_images` (`>= 6 KB`), sorts largest-first, deduplicates by SHA-256 **before** decoding (up to 60 unique assets, `min_side >= 120`), computes `asset_phash` (filtering blank hashes), and runs face detection on the top 10 largest unique assets.
  - **OCR ad facts** (`_extract_ocr_ad_facts`): Extracts canonical bare `ad_id` from `"Identyfikator biblioteki"` / `"Library ID"`, advertiser names strictly above standalone `"Sponsorowane"`/`"Sponsored"` (tight vertical gap `[-0.01, 0.035]`, horizontal alignment `<= 0.10`, no sentence punctuation), QR URLs, and decoy-filtered `ocr_domain` (excluding `interia.pl`, `onet.pl`, `fb.me`, etc.).
- **Output**: `VisualStage` (`img_feats`, `asset_faces`, `videos`, `clip_vecs`, `dino_vecs`, `face_vecs`, `file_shas`, `qr_urls`, `indicators`).
- **Why it exists**: Links materials when the landing page is dead (`404`) or when only ad screenshots/videos exist; also bridges screenshot-only cases to HTML-only cases via `ocr_domain`, `ad_id`, `advertiser_name`, and faces.
- **Incomplete-data resilience**: Missing videos or screenshots leave visual vectors empty; missing ONNX model files gracefully return `None` rather than crashing.

#### Stage 3 — Text & Narrative (`_stage_text` -> `TextStage`)
- **Input**: `web_s.titles`, `web_s.page_texts`, `vis_s.img_feats` (OCR), `meta` (ad-library copy), `m.texts`.
- **What it does**:
  - **Normalization** (`gazetteer.fold`, `text.normalize`): NFKC + lowercase + `ł -> l` + diacritic stripping + zero-width character removal (defeats homoglyph / invisible-joiner evasion).
  - **Gazetteer extraction** (`gazetteer.py`): Finds Polish impersonated persons (with word-boundary inflected regexes and disambiguation so `"Agnieszka Lewandowska"` or `"Tomasz Lewandowski"` does not trigger `"Robert Lewandowski"`), spoofed brands, and spoofed media outlets.
  - **Near-duplicate & template signatures**:
    - `minhash`: 128-perm MinHash (`seed=7`) over 4-word shingles of narrative text.
    - `minhash_masked`: Same after `gazetteer.mask_entities()` replaces all known person names (including 4-char surnames like `Tusk`/`Duda` and common Polish first names) with `<per>` — detects *"same article template, swapped celebrity"*.
    - `minhash_ocr`: Separate MinHash on OCR text (`> 80` chars) for screenshot-only items.
    - `title_templates`: Person-, number-, and media-masked titles for 3-char n-gram Jaccard.
  - **Semantic embeddings** (`text.embed_text`, optional `text_gemma.embed_text_gemma`): `multilingual-e5-small` (384-d ONNX int8) over up to 3 balanced 220-word windows (lead, middle, end), each L2-normalized before averaging. Optional `FTF_GEMMA=1` adds `EmbeddingGemma-2` (768-d, single 1024-token pass).
  - **Keywords & amounts**: Polish `YAKE` top-15 keywords + regex extraction of currency amounts (`zł`, `PLN`, `EUR`, `USD`).
- **Output**: `TextStage` (`text_summary`, `ocr_text`, `meta_text`, `text_vecs`, `gemma_vecs`).
- **Why it exists**: Captures copy-pasted articles, swapped-celebrity templates, and paraphrased Polish scam narratives across rotating domains.
- **Incomplete-data resilience**: Short texts (`< 6` tokens) return `minhash = None`; if `web_s.page_texts` is empty, embeddings fall back to OCR + ad-library metadata + free text.

#### Stage 4 — Structured LLM Augmentation (`_stage_llm` -> `LlmStage`)
- **Input**: Structured prompt combining titles, up to 3 landing/QR URLs, ad-library metadata, OCR text (`<= 2500` chars), page text (`<= 5000` chars), and free text (`<= 1500` chars), plus `use_llm: bool`.
- **What it does**:
  - When `use_llm=True` and `FTF_LLM` permits, invokes `claude -p --model haiku --json-schema ...` (or Gemini 2.5 Flash if `GEMINI_API_KEY` is set) with disk caching by content + model + extra-schema hash (`data/cache/llm/`).
  - Enforces a closed-enum JSON schema (`SCAM_TYPES`, `NARRATIVES`, `FORMATS`), normalizes extracted persons/brands onto gazetteer canonical names, and validates every enum field against its own allowed set (`_ENUM_BY_FIELD`).
  - Merges precomputed attributes from `data/cache/llm_extra_values.json` **only when `use_llm=True`**.
  - When `use_llm=False` (or LLM unavailable/text `< 30` chars), runs deterministic `llm.rules()` (gazetteer + lexicons + CTA-filtered product regex).
  - Promotes `product_or_platform_name` (`> 2` chars) to discrete indicator `product` and `distinctive_phrases` (`> 12` chars) to `phrase`.
- **Output**: `LlmStage` (`attrs`, `indicators`).
- **Why it exists**: Extracts structured high-level concepts ("fake platform name = Orzeł Fundaris", "scam_type = investment_fake_platform") that link two materials sharing a promoted scam brand even when their HTML templates differ, and supplies negative evidence when two materials have contradicting scam types.
- **Incomplete-data resilience**: Offline/no-API environments seamlessly fall back to `llm.rules()` with zero runtime errors.

#### Stage 5 — Concurrent Public OSINT Enrichment (`_stage_enrich` -> `EnrichStage`)
- **Input**: Deduplicated non-generic registrable domains from `landing_urls + qr_urls` (up to 6 per material), `enabled: bool` (controlled dynamically by `FTF_ENRICH`).
- **What it does**:
  - Calls `enrich.enrich_domains()` (up to 4 worker threads) to collect RDAP (IANA RFC 9224 bootstrap -> authoritative registry server, `rdap.org` fallback), DNS (`A`/`NS`/`MX`, 2s/4s timeout), Certificate Transparency (`crt.sh`), and CERT Polska warning-list membership (parent-domain aware).
  - Caches valid responses for 7 days and partial/transient errors for 15 minutes (`PARTIAL_TTL_S = 900`).
  - Emits `ns_pair` (sorted top-2 nameservers) and `reg_burst` (`normalized_registrar|ns_pair|YYYY-MM-DD`) **only when the nameserver pair is non-generic** (filtering `dyna-ns.net`, `registrar-servers.com`, `ovh.net`, `home.pl`, `nazwa.pl`, etc. via `GENERIC_NS_RX`).
  - Updates `behind_cloudflare` if DNS `A` records fall in `CLOUDFLARE_CIDRS` or NS ends in `.cloudflare.com`.
- **Output**: `EnrichStage` (`infra`, `indicators`, `behind_cloudflare`).
- **Why it exists**: Links rotating domains registered in bulk under the same Cloudflare account or registrar burst even when the landing page has already been taken down (`404`).
- **Incomplete-data resilience**: Disabled cleanly with `FTF_ENRICH=0`; transient API failures return partial dicts without blocking pipeline completion.

#### Stage 6 — Feature Assembly (`_assemble_features`)
- **Input**: Outputs of Stages 1–5 + `meta` + elapsed time.
- **What it does**: Merges indicator dicts, unions visual and named persons, extracts filename/capture/ad-library dates, collects `file_shas`, and packs vectors into stacked `np.ndarray`s (`clip`, `dino`, `faces`, `text`, optional `text_gemma`) plus `dom` MinHash lists.
- **Output**: `(feats: dict, vectors: dict)` stored in SQLite (`ftf/store.py`).

---

### Phase D — Explainable Pairwise Similarity (`ftf/similarity.py`)

- **Input**: Corpus of all materials `{mid: (feats, vectors)}`.
- **What it does**:
  1. **Corpus stats (`Corpus.__init__`)**:
     - Counts document frequency `df` for every `(type, value)` indicator, visual/named person, and LLM extra attribute.
     - Computes **inverse-density weighted background means** for `text`, `text_gemma`, `clip`, and `dino` (`_CENTRE_CLUSTER_THR = {text: 0.95, clip: 0.75, dino: 0.75}`) whenever at least `_CENTRE_MIN_REPS = 5.0` effective distinct clusters exist, correcting anisotropy without letting one dominant campaign pull the mean into itself.
  2. **Blocking (`candidate_pairs`)**: Evaluates all \(\binom{N}{2}\) pairs when \(N \le 400\); for \(N > 400\), generates candidates via an indicator inverted index (skipping values in \(> \max(50, 0.02 N)\) materials) plus top-15 kNN in `text` and `clip` spaces.
  3. **Per-pair evidence collection (`pair`)**:
     - *Duplicates*: Shared `file_shas` (`0.99`), or `text_minhash >= 0.93` + (`phash >= 0.95` or missing) + shared `landing_domain` (`0.97`).
     - *Discrete indicators*: Prior weight (`config.INDICATOR_WEIGHT[t]`) \(\times (0.35 + 0.65 \cdot \text{rarity})\). Hubs (`N >= 15`, `df >= 6`, `df/N > 0.5`, with S-tier operator IDs exempt when `N < 30`) get `weight = 0.0, ignored = True` and are **kept in the explanation list** so analysts see why they were skipped. Cross-layer `ocr_domain == landing_domain` matches are also scored (decoy-filtered).
     - *Continuous signals*: Piecewise-linear `ramp(val, lo, hi) * max_weight` for `text_minhash` (or `minhash_ocr`), `masked_minhash`, `title_template`, `text_embedding` (max of e5 & Gemma), `clip`, `dinov2`, `phash`, `dom_template`, and `face_unknown` (non-reference faces with `quality >= 0.22`). High-quality face pairs with raw ArcFace cosine `>= 0.80` also emit `same_face_image` (`+0.45`, family `visual`).
     - *Persons & Concept*: Shared gallery persons (`0.30` visual, `0.22` named, rarity-weighted); LLM enum agreements (`scam_type 0.15`, `narrative_template 0.30`, `creative_format 0.15`, `spoofed_media_outlet 0.20`, rarity-weighted `extra` `0.25`); contradicting `scam_type` sets `conflict = True`.
  4. **Combination & Guards**:
     - Per-family score: `families[f] = noisy_or(weights_in_f)`.
     - Overall probability: `p = noisy_or(families.values())`.
     - **Weak-only cap**: If no Tier S or M family reaches `0.25`, `p = min(p, 0.45)`. (A famous face + same scam type can never link a campaign on its own.)
     - **Contradiction guard**: If `conflict` and no Tier S family reaches `0.50`, `p *= 0.60`.
     - **Comparability**: `comparable = True` iff at least one continuous modality or discrete indicator type is present on both sides.
     - **Playbook score**: `noisy_or` over `narrative`, `concept`, `visual`, `persons`, `offer`.
     - **Edge relation**: `duplicate` (`dup >= 0.97`) -> `same_campaign` (`p >= 0.55` and `[s_tier >= 0.5 or strong >= 0.7 or >= 2 S/M families >= 0.3]`) -> `similar` (`p >= 0.30` or `playbook >= 0.45`) -> `none`.
- **Output**: `Link(a, b, p, relation, families, evidence, comparable, playbook)`.
- **Incomplete-data resilience**: Missing modalities simply produce `None` (never `0.0`), and incomparable pairs are excluded from average-linkage denominators in Phase E.

---

### Phase E — 3-Level Clustering, Open-Set Assignment & Graph Export (`ftf/cluster.py`, `ftf/graph.py`)

- **Input**: All materials + `Link` list.
- **What it does**:
  - **L0 Duplicates**: Union-Find on `relation == "duplicate"`.
  - **L1 Campaigns**:
    1. *Operator cores*: Union-Find on `duplicate` or `(s_tier >= 0.60 and p >= 0.55)`.
    2. *Comparable average-linkage agglomeration* (`agglomerate`): Iteratively merges the pair of cores maximizing `max(mean_comparable_p, mx if mx >= 0.85 else 0)` while `>= 0.55`.
  - **L1.5 Message Variants**: Inside each L1 campaign, Union-Find on `duplicate` or any strong content signal (`text_minhash`, `masked_minhash`, `title_template`, `phash` with `weight >= 0.45`).
  - **L2 Playbook Families**: Agglomerates L1 campaigns using `playbook` score (`FAMILY_MERGE = 0.40`, `strong = 0.75`) — explicitly separated from L1 so analysts see *"same scam recipe, unconfirmed operator"*.
  - **Baseline**: `HDBSCAN(min_cluster_size=2, metric="precomputed")` on distance matrix `1 - p` for side-by-side ablation.
  - **Incremental Open-Set Assignment (`cluster.assign`)**: Compares one new material against existing campaigns using `score = max(mean(top_2_comparable), mx if mx >= 0.75 else 0, min(mx, 0.54) if mx >= 0.55 else 0)`:
    - `duplicate` (if any `duplicate` link and not a merge proposal),
    - `merge_proposal` (`>= 2` campaigns with `score >= 0.55`),
    - `known_campaign` (top campaign `score >= 0.55`),
    - `candidate_review` (`0.40 <= score < 0.55` **and** at least one non-weak S/M family excluding `concept` reaches `>= 0.30`),
    - `new_campaign` (otherwise; attaches `similar_playbook` if top `score >= 0.30`).
  - **Graph & Exports (`ftf/graph.py`)**: Builds a NetworkX heterogeneous graph (`Material`, `Campaign`, `Family`, `Domain`, `Indicator`, `Person`, `Product`), prunes degree-1 entity nodes, and exports interactive `pyvis` HTML, Neo4j Cypher (`graph.cypher`), and FastAPI JSON for the React + Cytoscape.js UI.

---

## 3. Worked Concrete Example (Polish Fake-News Investment Network)

Consider two materials from the dominant Polish fake-news investment network observed in the organizer sample (the **Case 1 ↔ Case 2** and **Case 1 ↔ Case 48** patterns: spoofed Polish news articles routing through a TDS to rotating fake investment platforms such as *"Świtowin Zyskarnia"* and *"Orzeł Fundaris"*):

### Pair 1: Same narrative + shared operator infrastructure (Case 1 ↔ Case 2)
1. **Stage 1 (Web)**: Both saved pages yield the same canonical bare Facebook Pixel `fb_pixel = 2012165449475163` (Tier S, prior `0.92`), two shared landing-builder tenant UUIDs (`tenant_uuid`, prior `0.90`), identical DOM tag-shingle MinHash (`1.00`), and identical canonical `param_signature` (`utm_id=A20&utm_medium=A10&...`).
2. **Stage 2 (Visual & Faces)**: Embedded page images share exact `asset_phash` values; SCRFD + ArcFace detects the same public-figure portrait frame (`ArcFace cos = 1.00` -> `same_face_image +0.45`, gallery identity `Rafał Brzoska`).
3. **Stage 3 (Text)**: `text_minhash = 0.99`, `masked_minhash = 0.99`, `title_template = 1.00`, inverse-density centered `e5` cosine `= 0.993`.
4. **Stage 4 (LLM)**: Both extract `scam_type = investment_fake_platform`, `creative_format = fake_news_article`, `product_or_platform_name = "Świtowin Zyskarnia"` -> `product = "switowin zyskarnia"`.
5. **Phase D (Similarity on `N = 10` corpus)**:
   - Rarity for `df = 2, N = 10`: \(r = \frac{\ln(11/3)}{\ln(11/2)} = 0.762 \implies \text{scale} = 0.35 + 0.65 \times 0.762 = 0.845\).
   - `fb_pixel`: \(0.92 \times 0.845 = 0.78\) (`infra_ids = 0.78`).
   - Two `tenant_uuid`s: each \(0.90 \times 0.845 = 0.76 \implies \text{tracking} = 1 - (1-0.76)^2 = 0.94\).
   - `narrative = 1.00`, `kit = 0.91`, `assets = 1.00`, `offer = 0.63`, `visual = 0.45`, `persons = 0.85`, `concept = 0.49`.
   - Combined `p = 1.000`, `relation = "same_campaign"`, placed into the **same L1 operator core** and **same L1.5 variant**.

### Pair 2: Different celebrity, different headline, different domain — same operator kit (Case 1 ↔ Case 48)
1. **Why naive text/visual models fail**: Case 1 is a *"Brzoska"* article promoting *"Świtowin Zyskarnia"*; Case 48 is a *"37 minut po emisji"* article promoting *"Orzeł Fundaris"*. Centered e5 cosine is low, headlines differ, and domains differ.
2. **What fires in Stage 1 (HAR + URL)**:
   - Both HARs POST lead-capture telemetry to the exact same templated backend paths (`POST /api/v1/agent/persist-session-record/{id}/{id}` and `POST /api/v1/trigger/field/{id}/`, `api_template`, `df = 4/10` -> `+0.42` each).
   - Both URLs share the same canonical TDS `param_signature` (`df = 4/10` -> `+0.29`).
3. **Phase D & E**:
   - `kit = 1 - (1 - 0.42)(1 - 0.42)(1 - 0.29) = 0.76`, plus `concept = 0.28` (`investment_fake_platform`, `fake_news_article`) and `persons = 0.22` -> combined **`p = 0.867`**, `relation = "same_campaign"`.
   - Because `p = 0.867 >= STRONG_MERGE (0.85)`, Phase E merges Case 48's core into Case 1's L1 campaign, while keeping them in **separate L1.5 message variants** so the analyst immediately sees *"same operator kit, two different narratives"*.

### Pair 3: Same playbook, no operator trace (Case 14 ↔ Case 47)
- Both are Polish miracle-health supplement landing pages (*Metabo RX* vs *Uromexil Forte*).
- Inverse-density centered e5 cosine is `0.411` (below the `0.45` ramp floor); only `concept` fires (`miracle_cure_testimonial +0.30`, `health_miracle_product +0.15` -> `concept = 0.41`).
- Weak-only guard caps `p = 0.405 < 0.55` -> `relation = "similar"`, `playbook = 0.405`.
- Phase E keeps them in **separate L1 campaigns** (`C2` and `C5`) and links them only at **L2 (Playbook Family)** — preventing false operator attribution.

---

## 4. Flagged Decisions, Heuristics & Known Limitations

In the spirit of transparent engineering, every bug found during the codebase audit is documented alongside every remaining heuristic or fragile design choice.

### 4.1 Issues Found in Audit & Fixed

| # | Bug / Flaw Found in Audit | Before | After (Current Code) | Location |
|---|---|---|---|---|
| 1 | **Raw HTML SHA-1 cloaking false positives** | Hashing raw HTML bytes flagged CSP nonces (`nask.pl`) and responsive mobile HTML (`onet.pl`) as `"cloaking"`. | Replaced with structural & semantic `classify_cloaking()` comparing final registrable domain, `<title>`, visible-text token Jaccard, and 4-gram DOM tag-shingle Jaccard (`cloaking_suspected` / `bot_blocked` / `responsive_variant` / `none` / `unreachable`). | `ftf/capture.py:255-378` |
| 2 | **Missing SSRF / LFI guard in `capture.py`** | Arbitrary schemes (`file:///etc/passwd`) and loopback/private/metadata IPs could reach `requests` and Playwright Chromium. | Added `net.validate_public_url()`, byte-capped `net.safe_get()`, per-hop redirect validation, and Playwright `ctx.route("**/*", _route_guard)` + `accept_downloads=False`, `service_workers="block"`. | `ftf/net.py:112-215`, `ftf/capture.py:394-427` |
| 3 | **`.pl` RDAP HTTP 403** | Custom `User-Agent: FakeTrace/0.1` triggered 403 on NASK's `.pl` RDAP endpoint and bypassed authoritative TLD servers. | Implemented IANA RFC 9224 DNS bootstrap (`https://data.iana.org/rdap/dns.json`, 7-day cache) with `rdap.org` fallback and standard browser UA + `Accept: application/rdap+json`. | `ftf/enrich.py:39-48, 93-179` |
| 4 | **`reg_burst` on generic registrar NS & trailing-dot mismatch** | Unrelated domains parked on `ns1.dyna-ns.net` emitted fake `reg_burst` links; DNS NS had trailing dots (`ns1.foo.`) while RDAP did not. | Expanded `GENERIC_NS_RX`, suppressed both `ns_pair` and `reg_burst` for generic NS pairs, and stripped trailing dots + lowercased NS before pairing. | `ftf/enrich.py:50-60, 376-399` |
| 5 | **Cross-layer indicator format mismatch** | URL params emitted `fb_pixel = "pxl=123..."` and `ad_id = "ad_id=999"` while HTML/OCR/info.json emitted bare IDs or `library=999`, preventing cross-layer matches. | Canonicalized `fb_pixel` and `ad_id` to bare IDs across `web.url_indicators`, `pipeline._stage_web`, and `pipeline._extract_ocr_ad_facts`. | `ftf/web.py:182-189`, `ftf/pipeline.py:229, 260` |
| 6 | **Four HAR parsing bugs** | (a) Missed dotfile `.har` in Case 61; (b) picked `POST 404` as landing URL in Case 48; (c) truncated URLs to 500 chars before following 3xx redirects; (d) classified per-visit UUIDv7 (`utm_visit` / `/trigger/`) as `tenant_uuid`. | (a) Match `ext == ".har" or low == ".har"`; (b) `_pick_landing_url` requires GET 2xx/3xx HTML on non-generic domain; (c) chase redirects on untruncated `full_reqs`; (d) collect `session_uuids` and subtract them from `tenant_uuid`. | `ftf/ingest.py:137`, `ftf/web.py:386-522` |
| 7 | **81 JS/CSS files misclassified as image assets** | Polish Chrome `.pobrane` / `.pobierz` and extensionless `_files/` entries were dumped into `m.assets` regardless of content. | Added 16-byte magic-byte sniffer `_is_image_file()` (PNG/JPEG/GIF/BMP/WebP/ICO/AVIF); `.js.pobrane` and non-image `.pobrane` scripts now route to `m.scripts` and are scanned for trackers/hashes. | `ftf/ingest.py:73-96, 164-171`, `ftf/web.py:243-261` |
| 8 | **`"komentarze"` falsely excluded landing screenshots** | `"komentarze"` in `UI_MARKERS` flagged normal fake-news landing pages (which contain fake comment sections) as platform UI screenshots. | Removed `"komentarze"` / `"zostaw komentarz"` from `UI_MARKERS`, restricting it to true Ad Library chrome (`"identyfikator biblioteki"`, `"szczegoly reklamy"`, etc.). | `ftf/pipeline.py:33-37` |
| 9 | **`creative_crop` slicing keyframes & black-frame cache leak** | `creative_crop` sliced square/landscape video keyframes; `video_keyframes` returned stale cached black frames without re-checking. | Restricted `creative_crop` to `kind == "screenshot"` with `H/W > 1.35` and `min_area_frac = 0.35`; `_is_nonblack_frame` now validates both freshly extracted and cached keyframes (unlinking invalid ones). | `ftf/vision.py:83-114, 224-248`, `ftf/pipeline.py:121-123` |
| 10 | **Small-corpus / dominant-campaign hub-drop bug** | On tiny corpora (`N = 4`) or when one campaign exceeded 50% of the corpus, shared operator indicators were dropped as "hubs", splitting `{1, 2, 48, 61}`. | Added `HUB_MIN_CORPUS = 15` (no hub dropping on tiny corpora) and `HUB_EXEMPT_FAMILIES = ("duplicate", "infra_ids", "tracking", "advertiser")` exempt when `N < 30`. | `ftf/config.py:83-86`, `ftf/similarity.py:170-181` |
| 11 | **Unweighted corpus-mean centering collapsed `48 ↔ 61`** | Dominant campaign C1 (5/10 items) pulled the unweighted e5 mean into itself, pushing `48 ↔ 61` centered cosine down to `0.440` (below `0.45`). | Replaced with inverse-density weighted mean (`w_i = 1 / deg_i` at cosine `>= 0.95` for text, `0.75` for vision; requires `>= 5` effective reps). `48 ↔ 61` recovered to `0.501` while `14 ↔ 47` stayed `0.411`. | `ftf/similarity.py:53-54, 140-156` |
| 12 | **Import-time monkey-patching & dead features** | `similarity.py` mutated `config` at import time; unused `dhash`, `colorhash`, `layout_signature`, `platform_name`, and `registrar` indicator added noise and CPU overhead. | Moved all scoring/clustering constants into `ftf/config.py` as single source of truth; removed dead hashes, layout grid, and unused indicators. | `ftf/config.py:111-122`, `ftf/vision.py:62-63` |
| 13 | **Gazetteer short-surname & Lewandowski bugs** | `mask_entities` skipped 4-char surnames (`Tusk`, `Duda`); `"Agnieszka Lewandowska"` / `"Tomasz Lewandowski"` false-matched `"Robert Lewandowski"`. | Compiled word-boundary inflected regexes for all aliases (including `Tusk`/`Duda`), added dedicated `_matches_robert_lewandowski()` excluding feminine forms and other first names. | `ftf/gazetteer.py:143-177, 230-242` |
| 14 | **LLM cross-enum bug & `llm_extra_values.json` leak** | `llm.normalise()` checked enum values against the union of all enums instead of per-field enums; cached `llm_extra_values.json` leaked into `use_llm=False` runs. | Per-field validation via `_ENUM_BY_FIELD`; gated `llm_extra_values.json` strictly behind `if use_llm:`. | `ftf/llm.py:165, 236-238`, `ftf/pipeline.py:436-444` |

---

### 4.2 Remaining Weird, Heuristic & Open Design Decisions (Explicitly Flagged)

| # | Decision / Heuristic | Why It's Weird or Fragile | Concrete Upgrade Path |
|---|---|---|---|
| 1 | **Noisy-OR instead of calibrated Fellegi–Sunter log-odds** | Noisy-OR (`1 - Π(1 - w_i)`) is intuitive and bounded in `[0, 1]`, but assumes **conditional independence**. Correlated signals inside one family (e.g., 5 shared `asset_phash` images on cloned pages, or `text_minhash` + `masked_minhash` + `title_template` + `text_embedding`) saturate toward `1.0` faster than true posterior odds. | Once `>= 50` labeled campaigns exist, fit a regularized logistic regression (or Splink/Fellegi–Sunter EM) on family scores / log-odds with monotonic non-negative constraints to retain full per-feature explainability. |
| 2 | **Expert prior weights & linear ramps (`config.py`)** | All `INDICATOR_WEIGHT` priors and `CONTINUOUS` `(lo, hi, max_weight)` ramps are calibrated heuristics based on OSINT domain knowledge and the 10-case organizer set, not MLE-fitted probabilities. | Learn `(lo, hi, w_max)` via weak supervision (pairs sharing a rare Tier S pixel = positives; cross-scam-type pairs = negatives) and cross-validate on held-out campaigns. |
| 3 | **Open-set `assign()` multi-creative asymmetry** | In `cluster.assign()` (`ftf/cluster.py:179-185`), a new material compared against a 5-creative campaign is scored by the mean of its **top-2** comparable links, so matching only 1 creative requires `mx >= SINGLE_ASSIGN (0.75)` to trigger `known_campaign`. Against a singleton campaign, `top-2` has length 1, so `mx >= 0.55` suffices. A moderate match (`0.65`) to one narrative variant of a multi-narrative campaign is therefore demoted to `candidate_review` (`0.54`). | Score incoming materials against **L1.5 message-variant sub-clusters** (taking the max over variant means) rather than the flat L1 campaign list. |
| 4 | **L1 `STRONG_MERGE = 0.85` single-link override** | `agglomerate()` merges two cores if *any single cross-pair* reaches `p >= 0.85`. This is essential for linking cross-narrative sub-campaigns (e.g., `1 ↔ 48` via shared API template + TDS signature), but introduces single-link **chaining risk** if a third-party landing kit shared by two distinct operators saturates `p >= 0.85`. | Require `s_tier >= 0.60` (operator-level evidence) for the single-link override, or switch L1 to Leiden community detection (`leidenalg`, CPM objective) once corpora reach hundreds of materials. |
| 5 | **Embedding anisotropy on tiny corpora (`N < 5`)** | `Corpus.centre()` disables embedding similarity completely when fewer than `_CENTRE_MIN_REPS = 5.0` effective distinct clusters exist, because raw `multilingual-e5-small` cosines between unrelated Polish scam pages are `0.89–0.93`. Thus semantic text/visual embeddings contribute nothing until the store holds `>= 5` distinct campaigns. | Bundle a fixed, precomputed Polish web-page background mean vector (e.g., from ~200 diverse Polish pages) as a fallback prior when `eff_reps < 5`. |
| 6 | **Low visual-embedding signal on heterogeneous creatives** | Square white padding (`_square_pad`) + int8 ONNX quantization on CPU makes CLIP/DINOv2 effective mostly as near-copy / graphic-template backup rather than primary campaign linkers across visually distinct creatives of the same operator. | Add a dedicated copy-detection backbone (**SSCD**, CVPR 2022) and logo/brand detector (Phishpedia/KnowPhish) for spoofed media/bank mastheads. |
| 7 | **Live external source fragility** | Google Ads Transparency Center internal RPC currently triggers HTTP `429` (`/sorry/index`) from datacenter/automated IPs; LinkedIn Ad Library returns HTTP `403`; Meta Ad Library API requires an identity-verified Facebook account token (`META_ACCESS_TOKEN`). | Treat `sources.LAST_STATUS` as a first-class UI health indicator; integrate official DSA/platform APIs as credentials become available; use `urlscan.io` keyless search (`filename:` / `hash:` pivots) as an additional stable source. |
| 8 | **Residential/mobile geo-cloaking limits** | Server-side cloakers that verify Polish mobile carrier ASNs (Play/Orange/Plus/T-Mobile) or live single-use click tokens (`banReason: empty_redirect_hash`) cannot be bypassed from a datacenter IP with a synthetic `fbclid`. | Preserve full ad URLs immediately at sighting time; optionally route `capture.py` through a consented Polish residential/mobile proxy pool; rely on infrastructure signals (RDAP bursts, NS pairs, kit hashes) when content is cloaked. |
| 9 | **InsightFace `buffalo_l` non-commercial weight license** | SCRFD `det_10g` and ArcFace `w600k_r50` weights are licensed for **non-commercial research only** (acceptable for a hackathon POC, blocking for commercial/production deployment). | Swap weights to an Apache-2.0 / MIT-licensed face detector + embedder before production rollout. |
| 10 | **LLM non-determinism & `llm_extra_values.json` transductive loop** | Even with temperature `0` and disk caching, upstream LLM outputs can drift across model updates. Additionally, `tools/llm_refine.py` proposes and fills extra attributes transductively on the current store without held-out validation, risking overfitting to small datasets. | Version-pin prompts/models in cache keys, and gate `tools/llm_refine.py` attributes behind a cross-validated acceptance check (following CAAFE) before adding them to `llm_extra_schema.json`. |
