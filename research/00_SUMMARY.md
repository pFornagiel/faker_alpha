# Research summary — "Kolekcjoner Fejków / Follow the Fake" (NASK, HackNation 2026)

Consolidated from the detailed reports in this folder:
`01_ad_libraries_and_platform_scraping.md` · `02_web_infrastructure_osint.md` ·
`03_content_multimodal_models.md` · `04_prior_art_features_clustering.md` · `05_embeddinggemma2_eval.md`
(each claim there is tagged LIVE / READ / MEMORY). Organiser documents: `docs/organizers/`.

## 0. Organiser constraints (what is graded)

| Criterion | Weight | What we did about it |
|---|---|---|
| Quality of correlation / grouping method | 30 % | rarity-weighted evidence families → noisy-OR `p`, 3-level grouping (duplicates → campaigns → playbook families) + variants, open-set assignment |
| Usefulness & accuracy of features and data sources | 30 % | 5 feature layers (web/infra, visual, faces, text, LLM) + 6 live sources (CERT PL, MS/Google/Meta/LinkedIn ad libraries, yt-dlp) |
| End-to-end demonstrator | 15 % | Streamlit: URL / file / screenshot / text → features → decision → explanation; CLI; scheduler |
| Readability & interpretability of links | 15 % | every edge = list of Polish evidence sentences with weights; ignored hubs are shown too; pyvis graph + Neo4j |
| Deployment potential, scalability, portability | 10 % | Docker/compose (+Neo4j, +scheduler), CPU-only ONNX, blocking (inverted index + kNN) for >400 items |

Hard requirements: GUI (0/1), methodology doc, install instructions, Git repo, licences of models/services,
**robustness to incomplete data** (dead pages, deleted videos), **do not redistribute organiser data**.
Hidden test set = *new variants of known campaigns + materials of other campaigns* → open-set assignment
matters as much as clustering.

## 1. What can be collected (acquisition layer)

| Source | Access today (2026-11-21) | Gives | Used in POC |
|---|---|---|---|
| **Meta Ad Library API** `ads_archive` | token after FB identity check | all EU ads (also non-political) by keyword + `PL`, page id/name, bodies, link titles, dates, EU reach | ✅ if `META_ACCESS_TOKEN` (README has a how-to) |
| Meta Ad Library **creative by ad ID** | **yt-dlp `facebook:ads`**, no login | video + `.info.json` (advertiser, page id, ad id) — *this is how the organisers obtained case 5* | ✅ |
| Meta Ad Library web UI | 403 + JS handshake for plain HTTP | richer than API | ✗ (ToS; not bypassed) |
| **Google Ads Transparency Center** | internal RPC, no key (LIVE) | advertiser/domain pivot → creatives, PL impressions (YouTube video ads!) | ✅ |
| **Microsoft Ad Library API** | official, keyless (LIVE) | EEA ads with **destination URL**, PL=151 | ✅ |
| LinkedIn Ad Library | HTML, keyword + country (LIVE) | payer, text, landing link | ✅ (low yield) |
| TikTok Commercial Content Library | API needs research approval; web = browser only | — | documented |
| X / Snapchat / Pinterest repositories | pages load; X = advertiser-handle only | — | documented |
| EU DSA Transparency DB | statements of reasons, **no URLs/content** | statistics only | ✗ |
| **CERT Polska warning list** `hole.cert.pl` | free, any use (LIVE) | ~600–900 new scam domains/day, timestamps | ✅ scheduler seed |
| urlscan.io search | keyless 30/min (LIVE) | `filename:`/`hash:`/`page.ip:` pivots (one query expanded 7 → 80+ kit domains) | documented |
| crt.sh / CertSpotter, RDAP, DNS, RIPEstat | free | registrar, NS, creation time (registration bursts), certs | documented, partly used |
| yt-dlp | YouTube/TikTok/X/FB video + PL auto-captions without cookies | sponsored-video creatives | ✅ |
| Organic scrapers | instaloader (rate-limited, login), twscrape (accounts); **facebook-scraper, snscrape, nitter: dead** | — | documented |

Gotchas: scam ads live hours–days (~62 % removed by collection time → store on first sight);
**cloaking** (white page for bots; real offer for mobile + `Referer: l.facebook.com` + `fbclid` +
PL IP) → we capture with 3 client profiles and record the differential; Cloudflare makes IP/ASN
useless for most sites → we filter CDN IPs.

## 2. Are there existing clusterings/embeddings of scam-ad campaigns? (prior art)

* **No open, reusable scam-ad campaign clustering system and no campaign-labelled dataset was found.**
  Vendors/CSIRTs (Bitdefender 2026 — Poland is #1 target; Gen/Norton; CSIRT KNF; Infoblox;
  KommAustria; AI Forensics) publish narratives + IOCs, not code.
* How they link campaigns (our feature priorities follow this): **infrastructure identifiers first**
  (pixels, tracker IDs, TDS/redirect parameters, DGA-like domain patterns, HTML/CSS reuse), then
  **template/narrative reuse**, then persons. Celebrity identity is never sufficient alone.
* Reusable building blocks: Meta ThreatExchange (PDQ/vPDQ/TMK hashing), SSCD copy detection,
  VIGINUM D3lta (copypasta detection), datasketch (MinHash/LSH), Splink (Fellegi–Sunter record
  linkage with per-pair explanations), HDBSCAN, Leiden, Phishpedia/KnowPhish (logo-based brand
  ID), InsightFace, GLiNER. Nearest pipeline analogue: AdLens (CCS 2026).
* Polish context: CSIRT KNF 2026 note on a mass campaign (DGA `finance<NN>-<word><NN>.sbs`, 554
  domains, 36 rotating fake-platform names — e.g. "Cyrkiel Zyskanta"; our data shows the same
  pattern: "Świtowin Zyskarnia", "Orzeł Fundaris", "Trwały Działunek"). Most impersonated: Brzoska,
  Duda, Nawrocki, Tusk, Glapiński, Lewandowski, Trzaskowski, Mentzen, Kulczyk, doctors (Simon,
  Bielecki), TV anchors (Rymanowski, Olejnik); brands: Orlen, Baltic Pipe, TVN24, Gazeta.pl, InPost.

## 3. Feature catalogue (hand-crafted + latent + LLM-derived)

| Layer | Features | Link strength |
|---|---|---|
| Operator IDs | FB/TikTok pixel, GA/GTM/AW, Yandex, Clarity, Hotjar, Sentry key, reCAPTCHA key, phone/Telegram/WhatsApp/wallet, lead-form/API endpoint (session IDs stripped) | **strong** |
| Tracking / TDS | Meta ad/campaign IDs in URL, `acc=`/`land_id`/`_camp_id`, TDS host, landing-builder tenant UUID, URL parameter *shape* signature | strong–medium |
| Domain | landing / redirect-chain domains, domain seen on the creative, registration bursts (registrar + NS + minutes apart) | strong |
| Kit | first-party script names/hashes, API path templates, CSS names, DOM tag-shingle MinHash, favicon mmh3, build IDs | medium |
| Assets | identical images embedded on different landing pages (pHash) | medium |
| Visual | creative pHash/dHash/PDQ, CLIP (look), DINOv2 (layout), layout grid of text+faces from OCR boxes | medium |
| Narrative | text MinHash, **entity-masked MinHash** (swap-the-celebrity variants), title template, e5 embedding (centred), distinctive phrases | medium |
| Persons | ArcFace identity vs reference DB (hub-discounted), recurring *unknown* faces (personas), face quality | weak–medium |
| LLM-derived ("car model → body type") | scam_type, narrative_template, creative_format, impersonated persons/brands, spoofed media outlet, product/platform name, promised benefit, CTA, urgency cues, emotional triggers, fictional persona | weak (concept) / medium (product name) |
| Meta / temporal | advertiser id/name, ad-library id, first-seen dates, capture tool, cloaking flag | strong (advertiser) |

LLM augmentation literature (it *is* established): CAAFE, FeatLLM, LLM-FE, Viswanathan et al. 2023
(keyphrase expansion improves few-shot clustering), ClusterLLM, GoalEx, TnT-LLM, LLooM. Our use:
enum-constrained JSON (consistent across items), cached, converted to agree/disagree features,
rarity-weighted product/phrase indicators and a **negative** feature (contradicting scam types).
Iterative refinement loop (LLM proposes new attributes from cluster discrepancies) is described in
report 04 §3.4.

## 4. Models that fit a CPU laptop (ONNX, no PyTorch, ~460 MB)
multilingual-e5-small int8 (text), CLIP ViT-B/32 vision int8 (look), DINOv2-small int8 (layout),
SCRFD + ArcFace w600k_r50 (faces; weights non-commercial), RapidOCR PP-OCRv6 (Polish OK).
Optional upgrades (report 03): SigLIP2, `sdadas/mmlw-roberta-base` (best small Polish embedder),
Parakeet-TDT-0.6B ONNX ASR (better PL WER than Whisper large-v3), SSCD copy detection, facetorch.
AI-text / AI-image / deepfake detectors: **not reliable enough as verdicts** in the wild — used, if
at all, only as weak features.

## 5. Baseline on the organiser sample (10 cases)
See `docs/RESULTS.md` (generated by `tools/evaluate.py`).
