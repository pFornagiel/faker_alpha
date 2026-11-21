# FakeTrace — End-to-End Pipeline Walkthrough

> A step-by-step engineering guide tracing **what happens to a material from raw input to campaign decision**, including an explicit audit log of **fixed bugs, heuristics, weird design choices, and known limitations**.
>
> Companion deep-dives:
> - [`docs/WEB_FETCHING_METHODOLOGY.md`](WEB_FETCHING_METHODOLOGY.md) — SSRF safety, multi-profile capture, semantic cloaking classification, OSINT enrichment & external sources
> - [`docs/FEATURES_AND_ML_METHODOLOGY.md`](FEATURES_AND_ML_METHODOLOGY.md) — features (identifiers, content views, descriptive), Gower similarity, average-linkage clustering, open-set assignment
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
|   Stage 1 (_stage_web)              HTML/MHTML/HAR/URLs/scripts -> domains,  |
|                                     tracking IDs, contacts, kit files,       |
|                                     DOM MinHash                              |
|   Stage 2 (_stage_visual_and_faces) Video keyframes (anti-black-frame),      |
|                                     creative crop, UI filter, pHash,         |
|                                     RapidOCR, QR, SCRFD+ArcFace              |
|   Stage 3 (_stage_text)             Polish folding, gazetteer, YAKE/amounts, |
|                                     masked MinHash (page / creative), e5     |
|   Stage 4 (_stage_llm)              Small closed-enum JSON (Claude CLI /     |
|                                     Gemini / rule fallback) + cache          |
|   Stage 5 (_stage_enrich)           RDAP (RFC 9224), DNS, crt.sh, CERT PL    |
|                                     -> display-only domain metadata          |
|   Stage 6 (_assemble_features)      JSON feature summary + vector dict       |
+--------------------------------------+---------------------------------------+
                                       |
                                       v
+------------------------------------------------------------------------------+
| PHASE D: EXPLAINABLE PAIRWISE SIMILARITY  (ftf/similarity.py)                |
|                                                                              |
|   Identifiers (config.IDENTIFIER_GROUP), df/N <= MAX_DF  -> must-link        |
|   Views text/ocr/semantic/html/images  -> d = 1 - mean(available sim_v)     |
|   D = 0 inside a must-link component, else d                                 |
|   Output: Link(distance, p, relation, shared_ids, views, comparable)         |
+--------------------------------------+---------------------------------------+
                                       |
                                       v
+------------------------------------------------------------------------------+
| PHASE E: CLUSTERING, OPEN-SET ASSIGNMENT & GRAPH EXPORT                      |
|   ftf/cluster.py · ftf/graph.py · ftf/engine.py                              |
|                                                                              |
|   Batch build():                                                             |
|     Duplicates          file_sha / ad_id / d <= DUPLICATE_CUT (union-find)   |
|     Dendrogram          average linkage (UPGMA) on D                         |
|     Campaigns           cut at CAMPAIGN_CUT                                  |
|     Families            cut of the same dendrogram at FAMILY_CUT             |
|     Baseline            HDBSCAN on D                                         |
|   Incremental assign(): identifiers, else 1-NN with rejection ->             |
|                         duplicate / known_campaign / merge_proposal /        |
|                         new_campaign (+ nearest material, similar_family)    |
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

`pipeline.analyze(m, use_llm=True, progress=None, enrich_online=None)` runs six typed stages in sequence and returns
`(feats: dict, vectors: dict)`. What each extracted feature is used for (identifier, content view, or description
only) is defined in [`FEATURES_AND_ML_METHODOLOGY.md`](FEATURES_AND_ML_METHODOLOGY.md) § 1.

#### Stage 1 — Web & Infrastructure (`_stage_web` -> `WebStage`)
- **Input**: `m.pages`, `m.scripts`, `m.urls`, `meta`.
- **What it does**:
  - **HAR** (`web.parse_har`): Parses all HTTP entries using **untruncated full URLs in memory** for redirect-chain chasing; picks the true landing GET document (`_pick_landing_url`, skipping `POST 404` telemetry endpoints); identifies per-visit session UUIDs (`SESSION_PARAM_HINTS`, `/trigger/`, `session` POSTs) and removes them from `tenant_uuid`; templates POST paths (`template_path` -> `form_endpoint`, `api_template`, `path_template`); scans JS/JSON/HTML bodies for trackers (`TRACKER_RX`) and hashes non-generic first-party scripts (`script_hash`); extracts embedded images (`> 4 KB`) for Stage 2.
  - **HTML / MHTML** (`web.extract_html`, `web.parse_mhtml`): Extracts `saved from url=`, canonical/`og:url`, `<title>`, visible text, `<form>` endpoints, tracker & contact regexes, and a 128-permutation MinHash of 5-gram HTML tag sequences (the `html` view, stored as vector kind `"dom"`).
  - **Saved local scripts** (`web.extract_script_indicators`): Scans `m.scripts` for trackers and `script_hash`.
  - **Canonical IDs**: Emits bare numeric Facebook pixel IDs (`fb_pixel`) and bare Meta ad IDs (`ad_id`) across URL params, `info.json`, and later OCR so all layers intersect cleanly.
  - **IP / CDN filtering** (`net.is_cdn_ip`, `net.is_cloudflare_ip`): Records only non-CDN IPs (exact CIDRs) as display metadata and sets `behind_cloudflare`.
- **Output**: `WebStage` (`indicators`, `titles`, `page_texts`, `landing_urls`, `chains`, `ips`, `landing_ips`, `server_hdrs`, `dom_sigs`, `page_info`, `file_shas`, `har_images`, `notes`, `behind_cloudflare`).
- **Why it exists**: Operators reuse pixels, tenant workspaces, backend APIs and domains even when they rotate celebrities and headlines — these become the `domains`, `tracking_ids`, `contacts` and `kit_files` identifier groups.
- **Incomplete-data resilience**: If `m.pages` and `m.urls` are empty (e.g., screenshot-only submission), Stage 1 returns an empty `WebStage` with zero errors.

#### Stage 2 — Visual, OCR & Faces (`_stage_visual_and_faces` -> `VisualStage`)
- **Input**: `m.images`, `m.videos`, `m.assets`, `web_s.har_images`.
- **What it does**:
  - **Video keyframes** (`vision.video_keyframes`): Extracts up to `MAX_VIDEO_KEYFRAMES = 8` evenly spaced frames via `ffmpeg`/`ffprobe`, validating every frame (including cached frames) with `_is_nonblack_frame` (`mean > 12`, `std > 8`, `> 2 KB`) to defeat black-frame padding evasion.
  - **Creative cropping** (`vision.crop_content`, `vision.creative_crop`): Trims uniform borders on all images; on portrait screenshots (`kind == "screenshot"` and `H/W > 1.35`), isolates the dominant picture band (never below `35%` of the original area) so phone/feed UI chrome does not dominate the hash. Square/landscape video keyframes are never cropped.
  - **pHash, OCR, QR & UI filtering**: Computes a 64-bit `phash` per creative, `RapidOCR` (PP-OCRv6, `score >= 0.6`, reading order) and OpenCV QR decoding. Screenshots matching `UI_MARKERS` (Meta Ad Library details chrome — intentionally *excluding* `"komentarze"`) are tagged `kind = "ui_screenshot"` and excluded from the `images` view while retaining OCR, QR and faces.
  - **Landing-page images**: Combines `m.assets` and `har_images` (`>= 6 KB`), deduplicates by SHA-256 **before** decoding (up to 60 unique assets, `min_side >= 120`) and computes `asset_phash` (blank hashes filtered). Creative pHashes + `asset_phash` form the `images` view.
  - **Faces (descriptive only)** (`faces.faces_in_image`, `faces.identify`): `SCRFD det_10g` -> 5-point similarity alignment -> `ArcFace w600k_r50` (512-d). A face is kept if detector score `>= FACE_DET_THRESHOLD` and face side `>= FACE_MIN_SIDE`; it is named if its cosine to the 29-person reference gallery (`data/reference_faces/`) is `>= FACE_MATCH_THRESHOLD`.
  - **OCR ad facts** (`_extract_ocr_ad_facts`): Extracts canonical bare `ad_id` from `"Identyfikator biblioteki"` / `"Library ID"`, advertiser names strictly above standalone `"Sponsorowane"`/`"Sponsored"`, QR URLs, and `ocr_domain` (filtered by `web.is_decoy_or_generic_domain`, e.g. `interia.pl`, `onet.pl`, `fb.me`).
- **Output**: `VisualStage` (`img_feats`, `asset_faces`, `videos`, `face_vecs`, `file_shas`, `qr_urls`, `indicators`).
- **Why it exists**: Links materials when the landing page is dead (`404`) or only ad screenshots/videos exist — via exact image reuse, OCR text, and `ocr_domain` / `ad_id` identifiers.
- **Incomplete-data resilience**: Missing videos or screenshots leave the image set empty (`images` view unavailable); missing ONNX model files return `None` rather than crashing.

#### Stage 3 — Text & Narrative (`_stage_text` -> `TextStage`)
- **Input**: `web_s.titles`, `web_s.page_texts`, `vis_s.img_feats` (OCR), `meta` (ad-library copy), `m.texts`.
- **What it does**:
  - **Normalization** (`gazetteer.fold`, `text.normalize`): NFKC + lowercase + `ł -> l` + diacritic stripping + zero-width character removal (defeats homoglyph / invisible-joiner evasion).
  - **Gazetteer extraction** (`gazetteer.py`): Polish impersonated persons (word-boundary inflected regexes, with disambiguation so `"Agnieszka Lewandowska"` or `"Tomasz Lewandowski"` does not trigger `"Robert Lewandowski"`), spoofed brands, spoofed media outlets — all descriptive.
  - **`text` and `ocr` views**: two 128-permutation MinHash signatures over 4-word shingles, both on entity-masked text (`gazetteer.mask_entities()` replaces person names with `<per>`): `text.minhash_masked` over the landing-page text (titles + page text) and `text.minhash_ocr_masked` over the creative text (OCR of screenshots / keyframes + free text + ad-library metadata). Materials stored before the second field existed get it computed from the stored `text.ocr_text` at comparison time.
  - **`semantic` view** (`text.embed_text`): `multilingual-e5-small` (384-d ONNX int8) over up to 3 balanced 220-word windows (lead, middle, end), each L2-normalized before averaging; stored as vector kind `"text"`.
  - **Keywords & amounts**: Polish `YAKE` top-15 keywords + currency amounts (`zł`, `PLN`, `EUR`, `USD`) — descriptive.
- **Output**: `TextStage` (`text_summary`, `ocr_text`, `meta_text`, `text_vecs`).
- **Incomplete-data resilience**: Short texts (`< 6` tokens) produce no MinHash (view unavailable). Without page text the `text` view is simply unavailable (a creative-only material is compared OCR-to-OCR through `ocr`); the e5 embedding then falls back to all available text (OCR + ad-library metadata + free text).

#### Stage 4 — Structured LLM Extraction (`_stage_llm` -> `LlmStage`)
- **Input**: Prompt combining titles, up to 3 landing/QR URLs, ad-library metadata, OCR text (`<= 2500` chars), page text (`<= 5000` chars) and free text (`<= 1500` chars), plus `use_llm: bool`.
- **What it does**:
  - When `use_llm=True` and `FTF_LLM` permits, invokes `claude -p --model haiku --json-schema ...` (or Gemini 2.5 Flash if `GEMINI_API_KEY` is set) with disk caching by content + model (`data/cache/llm/`).
  - Schema: `scam_type` (closed enum, validated per field), `impersonated_persons`, `impersonated_brands` (normalized onto gazetteer names), `spoofed_media_outlet`, `product_or_platform_name` (+ `summary_pl` for the UI).
  - When `use_llm=False` (or LLM unavailable / text `< 30` chars), runs deterministic `llm.rules()` (gazetteer + lexicons + CTA-filtered product regex).
  - Promotes `product_or_platform_name` (`> 2` chars, normalized) to the `product` identifier; everything else is descriptive.
- **Output**: `LlmStage` (`attrs`, `indicators`).
- **Incomplete-data resilience**: Offline/no-API environments fall back to `llm.rules()` with zero runtime errors.

#### Stage 5 — Public OSINT Enrichment (`_stage_enrich` -> `EnrichStage`)
- **Input**: Non-generic registrable domains from landing + QR URLs (up to 6 per material), enabled by `FTF_ENRICH`.
- **What it does**: `enrich.enrich_domains()` (up to 4 threads) collects RDAP (IANA RFC 9224 bootstrap, `rdap.org` fallback), DNS (`A`/`NS`/`MX`), Certificate Transparency (`crt.sh`) and CERT Polska warning-list membership (parent-domain aware). Valid responses are cached for 7 days, transient errors for 15 minutes. Nameservers are lower-cased and stripped of trailing dots; `behind_cloudflare` is updated from DNS.
- **Output**: `EnrichStage` (`infra`, `behind_cloudflare`) — **display metadata only** (registrar, creation date, NS, IP, CERT PL listing); not used for linking because registrars are shared across campaigns.
- **Incomplete-data resilience**: Disabled cleanly with `FTF_ENRICH=0`; transient API failures return partial dicts.

#### Stage 6 — Feature Assembly (`_assemble_features`)
- **Input**: Outputs of Stages 1–5 + `meta` + elapsed time.
- **What it does**: Merges indicator dicts, unions visual and named persons, extracts dates, collects `file_shas`, and packs vectors (`text` = e5, `dom` = HTML MinHash, `faces`); the two text MinHash signatures and the image pHashes stay in the feature JSON.
- **Output**: `(feats: dict, vectors: dict)` stored in SQLite (`ftf/store.py`).

---

### Phase D — Explainable Pairwise Similarity (`ftf/similarity.py`)

- **Input**: Corpus of all materials `{mid: (feats, vectors)}`.
- **What it does** (all pairs):
  1. **Identifiers**: map raw indicator types to groups (`config.IDENTIFIER_GROUP`); count document frequency `df` per `(type, value)`. A shared value counts if `df/N <= config.MAX_DF` (0.5) or `df <= 2` (held only by the two compared materials); otherwise it is kept with `ignored = True` for the explanation.
  2. **Views** (`similarity.VIEWS`): `text` (page-text MinHash Jaccard), `ocr` (creative-text MinHash Jaccard), `semantic` (e5 cosine after plain corpus mean-centring, clipped to [0, 1]; raw cosine if `N < 3`), `html` (MinHash Jaccard, max over page pairs), `images` (pHash overlap at Hamming `<= config.PHASH_HAMMING`, divided by the smaller set size). Views missing on either side are skipped.
  3. **Distance**: `d = 1 − mean(available sim_v)`; `d = 1.0` and `comparable = False` if no view is available.
  4. **Relation**: `duplicate` (shared `file_sha` / `ad_id` or `d <= DUPLICATE_CUT`) -> `same_campaign` (counted shared identifier or `d <= CAMPAIGN_CUT`) -> `similar` (`d <= FAMILY_CUT`) -> `none`.
- **Output**: `Link(a, b, distance, p, relation, shared_ids, views, comparable, same_file)`, with `p = 1.0` if a counted identifier is shared, else `1 − distance`; `Link.explain()` gives the Polish explanation.
- **Incomplete-data resilience**: A missing modality removes a view from the mean instead of counting as 0.

---

### Phase E — Clustering, Open-Set Assignment & Graph Export (`ftf/cluster.py`, `ftf/graph.py`)

- **Input**: All materials + `Link` list.
- **What it does**:
  - **Must-link components**: union-find over pairs with a counted shared identifier or an identical file (`file_sha`).
  - **Duplicates**: union-find over `duplicate` links.
  - **Dendrogram**: `D(a,b) = 0` within a must-link component, else `d(a,b)`; average-linkage (UPGMA) agglomerative clustering with `scipy.cluster.hierarchy`.
  - **Campaigns**: `fcluster` at `config.CAMPAIGN_CUT` (0.6); a cut never splits a must-link component. **Families**: `fcluster` of the same dendrogram at `config.FAMILY_CUT` (0.93).
  - **Baseline**: `HDBSCAN(metric="precomputed")` on the same `D`.
  - **Open-set assignment (`cluster.assign`)**: shared identifier with one campaign -> `known_campaign`, with ≥ 2 campaigns -> `merge_proposal`; otherwise the nearest known material `m*` by content distance (1-NN, Cover & Hart 1967 — assignment asks "is this a variant of a known material", so it does not use the batch average linkage): `d <= CAMPAIGN_CUT` -> `known_campaign` (campaign of `m*`), else `new_campaign` with `nearest` = campaign, distance and material (+ `similar_family` if `d <= FAMILY_CUT`). Any duplicate link turns the decision into `duplicate` (except a `merge_proposal`).
  - **Graph & exports (`ftf/graph.py`)**: NetworkX graph (`Material`, `Campaign`, `Family`, `Domain`, `Indicator`, `Person`, `Product`), pyvis HTML, Neo4j Cypher (`graph.cypher`), FastAPI JSON for the React + Cytoscape.js UI.

---

## 3. Worked Concrete Example (Polish Fake-News Investment Network)

Campaign C1 of the organizer sample (cases 1, 2, 3, 48, 61): spoofed Polish news articles routing to rotating fake
investment platforms (*"Świtowin Zyskarnia"*, *"Orzeł Fundaris"*, …).

### Pair 1: Same article, shared tracking (Case 1 ↔ Case 2)
- **Identifiers**: same `fb_pixel = 2012165449475163` and two shared `tenant_uuid`s (`tracking_ids`), same backend `api_template` (`kit_files`); all with `df/N ≤ 0.5` -> must-link.
- **Views**: same article and template: `text` 0.99, `semantic` 0.99, `html` 1.00, `images` 0.92 → `d = 0.025 ≤ DUPLICATE_CUT`, so the pair is reported as `duplicate` (two reports of the same landing page). Case 2 has no screenshot, so `ocr` is not available for this pair.
- **Explanation**: lists the pixel, both UUIDs and the API template with their `df/N`, then the view values.

### Pair 2: Different celebrity, headline, platform and domain — same backend (Case 1 ↔ Case 48)
- **Views**: different article (Brzoska vs *"37 minut po emisji"*), different platform name and domain -> low `text` / `semantic` similarity; content alone would not link them.
- **Identifiers**: both HARs POST to the same templated backend path `POST /api/v1/trigger/field/{id}/` (`api_template`, shared by 1/2/48/61, `df = 4/10 ≤ 0.5`) -> must-link -> same campaign.
- Case 3 joins through `healthlinkq.pro` (landing domain shared with 2) and *"Orzeł Fundaris"* (`product`, shared with 48); 61 through the API template (its content is only loosely similar to 48: `d ≈ 0.77`). C1 is therefore one must-link component and does not depend on `CAMPAIGN_CUT`.

### Pair 3: Same scam type, no shared trace (Case 14 ↔ Case 47)
- Both are Polish miracle-health supplement pages (*Metabo RX* vs *Uromexil Forte*); `scam_type` agrees, but it is descriptive only.
- No shared identifier; `d = 0.913` (`semantic` 0.39, `html` 0.04, `text` 0, `ocr` 0, `images` 0) → separate campaigns (`d > CAMPAIGN_CUT`) but the same family (`d ≤ FAMILY_CUT = 0.93`). See `RESULTS.md`.

---

## 4. Flagged Decisions, Heuristics & Known Limitations

### 4.1 Issues Found in Audit & Fixed

| # | Bug / Flaw Found in Audit | Before | After (Current Code) | Location |
|---|---|---|---|---|
| 1 | **Raw HTML SHA-1 cloaking false positives** | Hashing raw HTML bytes flagged CSP nonces (`nask.pl`) and responsive mobile HTML (`onet.pl`) as `"cloaking"`. | Replaced with structural & semantic `classify_cloaking()` comparing final registrable domain, `<title>`, visible-text token Jaccard, and 4-gram DOM tag-shingle Jaccard (`cloaking_suspected` / `bot_blocked` / `responsive_variant` / `none` / `unreachable`). | `ftf/capture.py` |
| 2 | **Missing SSRF / LFI guard in `capture.py`** | Arbitrary schemes (`file:///etc/passwd`) and loopback/private/metadata IPs could reach `requests` and Playwright Chromium. | Added `net.validate_public_url()`, byte-capped `net.safe_get()`, per-hop redirect validation, and Playwright `ctx.route("**/*", _route_guard)` + `accept_downloads=False`, `service_workers="block"`. | `ftf/net.py`, `ftf/capture.py` |
| 3 | **`.pl` RDAP HTTP 403** | Custom `User-Agent: FakeTrace/0.1` triggered 403 on NASK's `.pl` RDAP endpoint and bypassed authoritative TLD servers. | Implemented IANA RFC 9224 DNS bootstrap (`https://data.iana.org/rdap/dns.json`, 7-day cache) with `rdap.org` fallback and standard browser UA + `Accept: application/rdap+json`. | `ftf/enrich.py` |
| 4 | **NS trailing-dot mismatch** | DNS NS records had trailing dots (`ns1.foo.`) while RDAP did not, so the same nameserver was shown twice. | Strip trailing dots + lowercase NS before display. | `ftf/enrich.py` |
| 5 | **Cross-layer indicator format mismatch** | URL params emitted `fb_pixel = "pxl=123..."` and `ad_id = "ad_id=999"` while HTML/OCR/info.json emitted bare IDs or `library=999`, preventing cross-layer matches. | Canonicalized `fb_pixel` and `ad_id` to bare IDs across `web.url_indicators`, `pipeline._stage_web`, and `pipeline._extract_ocr_ad_facts`. | `ftf/web.py`, `ftf/pipeline.py` |
| 6 | **Four HAR parsing bugs** | (a) Missed dotfile `.har` in Case 61; (b) picked `POST 404` as landing URL in Case 48; (c) truncated URLs to 500 chars before following 3xx redirects; (d) classified per-visit UUIDv7 (`utm_visit` / `/trigger/`) as `tenant_uuid`. | (a) Match `ext == ".har" or low == ".har"`; (b) `_pick_landing_url` requires GET 2xx/3xx HTML on non-generic domain; (c) chase redirects on untruncated `full_reqs`; (d) collect `session_uuids` and subtract them from `tenant_uuid`. | `ftf/ingest.py`, `ftf/web.py` |
| 7 | **81 JS/CSS files misclassified as image assets** | Polish Chrome `.pobrane` / `.pobierz` and extensionless `_files/` entries were dumped into `m.assets` regardless of content. | Added 16-byte magic-byte sniffer `_is_image_file()` (PNG/JPEG/GIF/BMP/WebP/ICO/AVIF); `.js.pobrane` and non-image `.pobrane` scripts now route to `m.scripts` and are scanned for trackers/hashes. | `ftf/ingest.py`, `ftf/web.py` |
| 8 | **`"komentarze"` falsely excluded landing screenshots** | `"komentarze"` in `UI_MARKERS` flagged normal fake-news landing pages (which contain fake comment sections) as platform UI screenshots. | Removed `"komentarze"` / `"zostaw komentarz"` from `UI_MARKERS`, restricting it to true Ad Library chrome (`"identyfikator biblioteki"`, `"szczegoly reklamy"`, etc.). | `ftf/pipeline.py` |
| 9 | **`creative_crop` slicing keyframes & black-frame cache leak** | `creative_crop` sliced square/landscape video keyframes; `video_keyframes` returned stale cached black frames without re-checking. | Restricted `creative_crop` to `kind == "screenshot"` with `H/W > 1.35` and `min_area_frac = 0.35`; `_is_nonblack_frame` now validates both freshly extracted and cached keyframes. | `ftf/vision.py`, `ftf/pipeline.py` |
| 10 | **Gazetteer short-surname & Lewandowski bugs** | `mask_entities` skipped 4-char surnames (`Tusk`, `Duda`); `"Agnieszka Lewandowska"` / `"Tomasz Lewandowski"` false-matched `"Robert Lewandowski"`. | Compiled word-boundary inflected regexes for all aliases (including `Tusk`/`Duda`), added dedicated `_matches_robert_lewandowski()` excluding feminine forms and other first names. | `ftf/gazetteer.py` |
| 11 | **LLM cross-enum validation bug** | `llm.normalise()` checked enum values against the union of all enums instead of the field's own enum. | `scam_type` (the only enum left) is validated against `SCAM_TYPES`; fields outside the schema are dropped, also from older cache entries. | `ftf/llm.py` |
| 12 | **Over-engineered scoring** | ~50 signals and 92 hand-set constants; several signals showed no separation on labelled data. | Must-link identifiers + Gower mean over 5 views + average linkage + 1-NN assignment; 5 constants. See `FEATURES_AND_ML_METHODOLOGY.md` § 6. | `ftf/config.py`, `ftf/similarity.py`, `ftf/cluster.py` |

---

### 4.2 Remaining Heuristic & Open Design Decisions (Explicitly Flagged)

| # | Decision / Heuristic | Why It's Fragile | Concrete Upgrade Path |
|---|---|---|---|
| 1 | **Must-link on a single identifier** | One wrong or accidentally shared identifier (a shared third-party kit, an OCR misread domain) merges two campaigns through the whole component (chaining). | `MAX_DF` drops too-common values; the value and its `df/N` are always shown. Next: require analyst confirmation (as with `merge_proposal`) when a single identifier bridges two otherwise distant groups. |
| 2 | **Hand-set cuts and equal view weights** | `CAMPAIGN_CUT`, `FAMILY_CUT`, `DUPLICATE_CUT` and equal weights are design choices, not fitted values; stability was checked only on 10 own-labelled materials. | Re-check on the organizer test set; with enough labelled pairs, fit view weights (e.g. logistic regression on per-view similarities) while keeping per-view explanations. |
| 3 | **No visual embeddings** | A redrawn creative of the same campaign (new graphics) is not matched visually; only exact image reuse, text, HTML and identifiers can link it. | Re-introduce a visual view only if it shows separation on labelled data. |
| 4 | **Product names depend on LLM extraction** | `product` links rely on `product_or_platform_name`; the rule fallback finds fewer names and LLM output can drift across model updates. | Version-pin prompts/models in cache keys; show the extracted name in every explanation (done). |
| 5 | **Plain mean-centring with a dominant campaign** | If one campaign dominates the corpus, the mean moves towards it and lowers its own within-campaign `semantic` similarity. | Identifiers carry such campaigns (C1); for larger corpora, centre on a fixed background corpus of Polish pages. |
| 6 | **All-pairs comparison** | `O(N²)` pairs — fine for hundreds to low thousands of materials. | Inverted index on identifiers + approximate nearest neighbours for views at larger scale. |
| 7 | **Live external source fragility** | Google Ads Transparency Center internal RPC currently triggers HTTP `429` (`/sorry/index`) from datacenter/automated IPs; LinkedIn Ad Library returns HTTP `403`; Meta Ad Library API requires an identity-verified Facebook account token (`META_ACCESS_TOKEN`). | Treat `sources.LAST_STATUS` as a first-class UI health indicator; integrate official DSA/platform APIs as credentials become available. |
| 8 | **Residential/mobile geo-cloaking limits** | Server-side cloakers that verify Polish mobile carrier ASNs or live single-use click tokens (`banReason: empty_redirect_hash`) cannot be bypassed from a datacenter IP with a synthetic `fbclid`. | Preserve full ad URLs at sighting time; optionally route `capture.py` through a consented Polish residential/mobile proxy pool; rely on identifiers when content is cloaked. |
| 9 | **InsightFace `buffalo_l` non-commercial weight license** | SCRFD `det_10g` and ArcFace `w600k_r50` weights are licensed for **non-commercial research only** (acceptable for a hackathon POC). | Swap to an Apache-2.0 / MIT-licensed face detector + embedder before production; faces are descriptive only, so linking is unaffected. |
