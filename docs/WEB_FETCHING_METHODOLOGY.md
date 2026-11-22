# FakerAlpha — Web Fetching, Anti-Cloaking & OSINT Enrichment Methodology

> Technical and methodological reference for FakerAlpha's acquisition, safe web-fetching, cloaking classification, artifact ingestion, and public infrastructure OSINT layers (`ftf/net.py`, `ftf/capture.py`, `ftf/ingest.py`, `ftf/web.py`, `ftf/enrich.py`, `ftf/sources.py`, `ftf/scheduler.py`).
>
> See also: [`docs/PIPELINE_WALKTHROUGH.md`](PIPELINE_WALKTHROUGH.md) · [`docs/FEATURES_AND_ML_METHODOLOGY.md`](FEATURES_AND_ML_METHODOLOGY.md) · [`docs/METHODOLOGY.md`](METHODOLOGY.md)

---

## 1. Design Goals

Investigating online scam-ad ecosystems in Poland (and the EU) imposes five hard engineering constraints:

1. **SSRF & Archive Safety**: Analysts and schedulers feed untrusted third-party URLs, redirects, HARs, HTML files, and ZIP uploads into the pipeline. Every outbound HTTP request and Playwright subrequest must be restricted to globally routable `http(s)` targets, every response body must be byte-capped, and every ZIP upload must defend against zip-slip, symlinks, and decompression bombs.
2. **Cloaking Awareness Without False Alarms**: Malicious Traffic Distribution Systems (TDS) such as Keitaro, HideClick, and Adspect routinely serve benign "white pages" to bots while redirecting mobile social-media users to scam offers (Invernizzi et al. 2016; CERT Polska 2024; Zhang et al. 2021). However, legitimate Polish portals emit dynamic CSP nonces (`nask.pl`) and responsive mobile markup (`onet.pl`). Cloaking detection must distinguish *semantic/destination divergence* from benign dynamic HTML or standard WAF bot blocks.
3. **Offline Reproducibility & Caching**: Scam domains have a median lifetime of ~11 days and scam ads often disappear within 21 hours (Kotzias et al. 2025; CERT Polska 2024). All captures, manifests, RDAP/DNS/CT lookups, and CERT Polska snapshots are cached on disk (`data/artifacts/`, `data/cache/`) with atomic writes and explicit TTLs so analyses remain reproducible long after infrastructure goes dark.
4. **Incomplete-Data Tolerance**: Live sites return `404`, drop connections, or block bots. Missing HTML, missing HARs, or failed external APIs must never crash the pipeline or poison downstream similarity with spurious zero values.
5. **No Silent Failures**: External ad libraries and public feeds change endpoints or impose rate limits frequently. Every acquisition source records its exact runtime status (`ok`, `rate_limited`, `blocked`, `no_credentials`, `error`) in `sources.LAST_STATUS`.

---

## 2. Layer-by-Layer Architecture

### 2.1 Shared Network Safety & CDN Filtering (`ftf/net.py`)

`ftf/net.py` is the single security boundary for outbound HTTP traffic and CDN classification:

- **URL & DNS validation (`validate_public_url`)**:
  - Allows only `http` and `https` schemes (blocks `file://`, `ftp://`, `gopher://`, `javascript:`, etc.).
  - Parses literal IPv4/IPv6 addresses (unwrapping IPv4-mapped IPv6 such as `::ffff:127.0.0.1` via `_parse_ip`) and resolves hostnames via `socket.getaddrinfo()`.
  - Enforces `_is_public_ip(addr)`: requires `addr.is_global` and explicitly rejects private (`RFC 1918`), loopback (`127.0.0.0/8`, `::1`), link-local (`169.254.0.0/16` cloud metadata, `fe80::/10`), multicast, reserved, and unspecified addresses. If *any* resolved address is non-public, the target is rejected with `ValueError`.
- **Bounded streaming GET (`safe_get`)**:
  - Validates the initial URL and **every redirect hop** (up to 8 hops when `allow_redirects=True`) via `validate_public_url`, preventing open-redirect SSRF bypasses.
  - Checks `Content-Length` up front and skips reading oversized non-text/non-HTML binaries (`> max_bytes`).
  - Streams response bodies in 64 KB chunks up to `max_bytes` (default `3_000_000` bytes) and guarantees `resp.close()` in a `finally` block.
- **Exact CDN CIDR filtering (`is_cloudflare_ip`, `is_cdn_ip`)**:
  - Maintains official Cloudflare IPv4/IPv6 CIDR blocks (`CLOUDFLARE_CIDRS`, 22 prefixes) plus exact edge allocations for Fastly, Google, Meta, AWS CloudFront, and Akamai (`OTHER_CDN_CIDRS`) — intentionally avoiding overly broad `/8` masks like `23.0.0.0/8` that would drop legitimate non-CDN hosts.
  - Because ~82% of CERT Polska scam domains sit behind Cloudflare AS13335 (CERT Polska 2025), raw IP matching without CIDR filtering would collapse unrelated campaigns together.

### 2.2 Multi-Profile Capture & Sandboxed Browser Rendering (`ftf/capture.py`)

`capture_url(url, render=True)` executes a 5-step capture pipeline:

1. **Pre-flight SSRF Validation**: Rejects invalid or non-public URLs immediately with `cloaking_verdict = "invalid_url"`.
2. **Multi-Profile Redirect Following (`follow_profile`)**: Fetches the exact ad URL (preserving full path and query parameters) under three distinct client profiles (`PROFILES`, `0.25s` polite delay between profiles, up to `12` hops, timeout `(5.0s, 12.0s)`, body cap `3 MB`):
   - `bot`: `Mozilla/5.0 (compatible; FakerAlphaBot/0.1)` — baseline crawler identity.
   - `desktop_pl`: Windows 10 Chrome 131 with `Accept-Language: pl-PL,pl;q=0.9,en;q=0.5`.
   - `fb_mobile`: Android 14 Samsung SM-S918B Chrome 131 with Facebook In-App Browser signature `[FB_IAB/FB4A;FBAV/480.0.0.0;]`, `Accept-Language: pl-PL,pl;q=0.9,en;q=0.5`, `Referer: https://l.facebook.com/`, `X-Requested-With: com.facebook.katana`, plus a deterministic synthetic `fbclid=IwAR0<sha1[:24]>` appended via `_with_synthetic_fbclid()` if none is present.
   - Tracks HTTP `3xx` redirects, `<meta http-equiv="refresh">` (both attribute orderings, first 20 KB), and small JS redirect stubs (`len(html) < 3500`, visible text `< 300` chars matching `location.href = ...` / `location.replace(...)`), detecting redirect cycles and validating every hop with `net.validate_public_url`.
3. **Semantic & Structural Cloaking Classification (`classify_cloaking`)**: Detailed in Section 3 below.
4. **Optional Sandboxed Playwright Render (`render_browser`)**:
   - Launches headless Chromium in mobile Polish context (`viewport 412x915`, `is_mobile=True`, `locale="pl-PL"`, `timezone_id="Europe/Warsaw"`, `fb_mobile` UA & headers).
   - Hardens context with `accept_downloads=False`, `service_workers="block"`, and a `ctx.route("**/*", _route_guard)` handler that runs `net.validate_public_url()` on every network subrequest (allowing only `data:`, `blob:`, `about:` locally and aborting any private/internal target with `blockedbyclient`).
   - Captures `page.har` (`record_har_content="embed"`), `screenshot.png` (above-the-fold), and `rendered.html` (tagged with Chrome-compatible `<!-- saved from url=(NNNN)<final_url> -->`), waiting for `domcontentloaded` (25s), `networkidle` (6s), plus a 1.2s settle delay. Browser and context are always closed inside `finally`.
5. **Manifest Persistence**: Saves `capture_manifest.json` inside `data/artifacts/captures/<sha1[:12]>/` with resolved IPs, per-profile chains/statuses/titles, cloaking verdict, human-readable reasons, and pairwise similarity metrics.

### 2.3 Safe Ingestion & Normalization (`ftf/ingest.py`)

`ftf/ingest.py` normalizes heterogeneous sources into the `Material` dataclass:

- **Archive & upload security (`_extract_zip_safely`)**:
  - Fixes legacy CP437/UTF-8 ZIP filenames (common in Polish Windows archives).
  - Rejects Unix symlinks (`stat.S_ISLNK(info.external_attr >> 16)`).
  - Prevents zip-slip traversal (`(dest_root / name).resolve().is_relative_to(dest_root)`).
  - Enforces strict decompression caps: `MAX_FILES = 500`, `MAX_FILE_BYTES = 50 MB`, `MAX_TOTAL_BYTES = 250 MB`.
- **File routing (`load_folder`)**:
  - Recognizes `.har` files including dotfiles named `.har` (`ext == ".har" or low == ".har"`).
  - Prefers archiver `rendered.html` over sibling `source.html`.
  - Uses 16-byte magic-byte sniffing (`_is_image_file`: PNG, JPEG, GIF, BMP, WebP, ICO, AVIF/HEIC) on Polish browser saves (`.pobrane`, `.pobierz`) and extensionless asset files, routing real images to `m.assets` and saved JS bundles (`.js.pobrane`, etc.) to `m.scripts`.
  - Deduplicates sibling `.mhtml` files next to `.html` in the same folder *only after* extracting `Snapshot-Content-Location` from the first 8 KB of the MHTML header (`_extract_mhtml_url`) and attaching it to `m.urls` and the sibling HTML record.
  - Recognizes deletion placeholder files (`*deleted*`, `*removed*`, `*usuni*`) as structured `notes` rather than page text.
- **Metadata unifier (`read_meta`)**: Parses `yt-dlp` `.info.json`, `capture_manifest.json`, and archiver DNS/SSL JSONs into a common `{ad_library, capture, dns}` schema.

### 2.4 Web Artifact Parsing (`ftf/web.py`)

`ftf/web.py` extracts structured indicators from URLs, saved HTML, MHTML (RFC 2557), HAR 1.2 logs, and saved local scripts:

- **Public Suffix List (PSL) Offline Domain Extraction**: Uses `tldextract.TLDExtract(suffix_list_urls=(), include_psl_private_domains=True)` so offline operation is guaranteed and multi-tenant hosting suffixes (`a.pages.dev` vs `b.pages.dev`, `a.netlify.app` vs `b.netlify.app`) are never collapsed into a single registrable domain.
- **HAR 1.2 Parsing (`parse_har`)**:
  - Keeps untruncated `full_reqs` in memory while chasing 3xx redirect chains (truncating to 500 chars only in the serialized summary).
  - Selects the primary landing document via `_pick_landing_url()`: prioritizes non-generic `GET` requests returning `2xx`/`3xx` HTML (preventing telemetry `POST 404` requests from being chosen as the landing URL).
  - Identifies per-visit session UUIDs (from `SESSION_PARAM_HINTS` query keys or `/trigger/` / `session` POST paths) and subtracts them from `tenant_uuid` so per-visit UUIDv7 tokens never create noise.
  - Strips per-visit IDs from POST endpoints via `template_path()` (`/api/v1/trigger/field/01a11f55-.../` -> `/api/v1/trigger/field/{id}/`) to produce both host-qualified `form_endpoint` and host-agnostic `api_template`.
  - Computes SHA-1 hashes of non-generic first-party JS (`script_hash`, `> 500` bytes).
- **URL Fingerprinting (`url_indicators`)**:
  - Canonicalizes `fb_pixel` (14–17 digits) and `ad_id` to bare IDs across query params, HTML, OCR, and ad-library metadata.
- **HTML & Script Extraction (`extract_html`, `extract_script_indicators`)**:
  - Extracts trackers (`TRACKER_RX`: FB Pixel, TikTok Pixel, GA/GA4, GTM, Google Ads `AW-`) and contacts (`CONTACT_RX`: Telegram, WhatsApp, email, Polish/international phone, BTC/ETH/TRON crypto wallets).
  - Cleans Polish Chrome asset filenames (`_clean_asset_filename` strips `.pobrane`/`.pobierz` and duplicate `(1)` suffixes) and filters common libraries (`GENERIC_SCRIPT_NAMES`) so only first-party scripts are hashed.
  - Produces 5-gram DOM tag shingles (`tag_shingles`) for structural template MinHash.

---

## 3. Multi-Profile Cloaking Classification

### Why Raw HTML Hashing Fails in Production

Early prototypes compared `sha1(html)` across client profiles. Empirical live testing immediately exposed two fatal false-positive modes:
- **Per-request nonces & tokens** (e.g., `nask.pl`): Content Security Policy (`nonce="..."`), CSRF tokens, and echoed timestamps change the raw SHA-1 on every single request even for identical pages.
- **Responsive mobile layouts** (e.g., `onet.pl`): Serving a mobile-optimized template to `fb_mobile` vs a desktop layout to `desktop_pl` changes raw bytes while preserving the exact same domain, article title, and core narrative.
- **WAF / Bot Management**: Legitimate sites behind Cloudflare/Akamai often return HTTP `403`/`429`/`503` to `FakerAlphaBot/0.1` while serving identical `200 OK` pages to `desktop_pl` and `fb_mobile`.

### Structural & Semantic Classifier (`capture.classify_cloaking`)

For every profile that receives a `2xx` HTML response, `_extract_page_signature()` strips `<script>`, `<style>`, `<noscript>`, `<svg>`, and `<template>`, extracting:
- `title_norm`: normalized `<title>` text,
- `text_len`: length of visible text,
- `tokens`: set of lowercase Polish/alphanumeric word tokens (`len >= 3`),
- `tag_shingles`: set of 4-gram DOM tag sequences (excluding script/style/noscript).

Pairwise profile comparisons (`desktop_pl vs fb_mobile`, `bot vs fb_mobile`, `bot vs desktop_pl`) then produce one of five explainable verdicts:

| Verdict | `cloaking` Flag | Trigger Condition | Interpretation |
|---|---|---|---|
| **`cloaking_suspected`** | `True` | (a) Two `2xx` profiles land on **different final registrable domains**, **OR** (b) on the same domain, both pages have substantial text (`text_len >= 200`), titles differ (`not same_title`), visible-text Jaccard `< 0.30`, **and** 4-gram DOM tag-shingle Jaccard `< 0.40`. | Strong evidence of server-side cloaking / decoy white-page substitution. |
| **`bot_blocked`** | `False` | No cloaking detected; `bot` profile received HTTP `403`, `429`, or `503` while `desktop_pl`/`fb_mobile` returned `2xx` (matching if both succeeded). | Standard WAF / anti-bot rule rather than ad-targeted cloaking. |
| **`responsive_variant`** | `False` | Same domain, no cloaking; text Jaccard `>= 0.55` (or same title with text Jaccard `>= 0.35`), while `text_jaccard < 0.85` or `dom_jaccard < 0.85`. | Legitimate mobile vs desktop responsive layout difference. |
| **`none`** | `False` | Consistent final registrable domain and high text/DOM overlap across `2xx` profiles. | No differential serving observed. |
| **`unreachable`** | `False` | No client profile received a `2xx` HTML response. | Dead domain, NXDOMAIN, TLS error, or total IP block. |
| *(Pre-flight)* **`invalid_url`** | `False` | `net.validate_public_url()` rejected the input URL. | Disallowed scheme or non-public/SSRF target. |

**Known limitation**: Server-side cloakers that verify Polish mobile carrier ASNs (residential mobile IP) or single-use live click tokens (`banReason: "empty_redirect_hash"`, observed live on CERT Polska `.store` scam bursts in `research/02_web_infrastructure_osint.md`) serve the white page to all three profiles from a datacenter IP. In those cases, FakerAlpha records the exact verdict (`none` / `unreachable`) and falls back to infrastructure OSINT (RDAP registration bursts, account-scoped Cloudflare NS pairs, kit hashes).

---

## 4. Public OSINT Enrichment & Smart Caching (`ftf/enrich.py`)

When `FTF_ENRICH != "0"` (evaluated dynamically via `is_enabled()`), `enrich_domains()` queries up to 4 domains concurrently per material across four free public signals:

1. **RDAP via IANA RFC 9224 Bootstrap (`rdap`)**:
   - Downloads and caches `https://data.iana.org/rdap/dns.json` (`BOOTSTRAP_TTL_S = 7 days`, atomic write, stale-cache fallback) to map each TLD (including `.pl`, `.pro`, `.sbs`, `.store`, `.cfd`, `.live`) directly to its authoritative HTTPS RDAP base URL, falling back to `https://rdap.org/domain/<dom>`.
   - Uses browser-compatible `User-Agent` + `Accept: application/rdap+json` (fixing HTTP `403` rejections observed on `.pl` RDAP with custom crawler UAs).
   - Extracts registrar name, normalized registrar (`_normalize_registrar`), registrar IANA ID, creation/expiration/update timestamps, domain status, and normalized lowercase nameservers (trailing dots stripped).
2. **DNS (`dns`)**: Resolves `A`, `NS`, and `MX` records via `dnspython` with strict short timeouts (`timeout = 2.0s`, `lifetime = 4.0s`), distinguishing empty (`NXDOMAIN`/`NoAnswer`) from transport errors.
3. **Certificate Transparency (`crtsh`)**: Queries `https://crt.sh/?q=<dom>&output=json` (`(5s, 12s)` timeout), explicitly distinguishing HTTP/network errors (`{"error": ...}`) from genuine zero-certificate results (`{"n_certs": 0}`). Records `n_certs`, earliest `first_cert`, `issuer`, and up to 30 `san_names`.
4. **CERT Polska Warning List (`_cert_pl`, `is_cert_pl_listed`)**: Downloads `https://hole.cert.pl/domains/v2/domains.txt` (6-hour mtime cache, atomic temp-file + `os.replace`, stale-cache fallback on network failure). Matches both exact domains and any parent domain (`sub.bad.pl` -> `bad.pl`).

### Dual-TTL Smart Caching & Display Metadata

- **Dual TTL**: Complete responses are cached in `data/cache/enrich/<domain>.json` for `FULL_TTL_S = 7 days`. Any response with transient/partial errors (`_partial = True`, e.g., `crt.sh` HTTP `503`, RDAP `429`, DNS timeout) uses a short negative TTL of `PARTIAL_TTL_S = 900s` (15 minutes) so transient outages are never frozen for a week.
- **Display metadata, not linking signals**: registrar, creation date, nameservers (lower-cased, trailing dots stripped), IPs and CERT Polska listing are shown to the analyst (e.g., `civicdaybook.live` and `healthlinkq.pro` both created on `2026-10-08`). They do not link materials, because registrars and nameservers are shared across different campaigns — see [`FEATURES_AND_ML_METHODOLOGY.md`](FEATURES_AND_ML_METHODOLOGY.md) § 1.3.

---

## 5. Empirical Status of Live Polish / EU Data Sources

External feeds are inherently volatile. `ftf/sources.py` tracks every call in `LAST_STATUS` (`status`, `detail`, `count`) and `ftf/scheduler.py` logs per-job errors into SQLite so outages are visible rather than silently returning `[]`:

| Source (`ftf/sources.py`) | Endpoint / Mechanism | Credentials | Empirical Live Status | What It Provides & Known Caveats |
|---|---|---|---|---|
| **CERT Polska Warning List** (`cert_pl_new`) | `https://hole.cert.pl/domains/v2/domains.json` (ETag + `If-Modified-Since`) | None (public) | **Live & reliable** | ~600–900+ new Polish scam domains/day; watermarked by `RegisterPositionId`; filtered with boundary-aware `_match_domain_stems` (avoids `akcj` matching `transakcja`). First run scans newest 2,000 active entries. |
| **Microsoft Ad Library** (`ms_adlib_search`) | `https://adlibrary.api.bingads.microsoft.com/api/v1/Ads` (`countryCodes=151`) | None (keyless) | **Live & reliable** | EEA ads targeted at Poland including `DestinationUrl`, advertiser ID/name, title, description, and assets. |
| **RDAP + DNS** (`enrich.rdap`, `enrich.dns`) | IANA RFC 9224 bootstrap -> TLD RDAP servers (`rdap.org` fallback) + UDP/TCP DNS | None | **Live & reliable** | Authoritative registrar, creation date, and NS records (`.pl`, `.pro`, `.sbs`, `.store`, `.live` verified). Occasional per-registry `429` handled with 15-min partial cache. |
| **crt.sh CT Logs** (`enrich.crtsh`) | `https://crt.sh/?q=<dom>&output=json` | None | **Intermittent / lagging** | Useful for historical cert counts & SANs, but frequently returns `503`/`502` or lags ~36h on brand-new certs (handled by 15-min negative TTL). |
| **Meta Ad Library API** (`meta_api_search`) | `https://graph.facebook.com/v27.0/ads_archive` | `META_ACCESS_TOKEN` (FB ID check required) | **Works with token** (`no_credentials` without) | EU/PL commercial ads (`ad_type=ALL`), page ID/name, creative copy, snapshot URL, EU reach, beneficiary/payers. Skips cleanly when token is unset. |
| **Meta Ad Creative Media** (`meta_ad_media`) | `yt-dlp` `facebook:ads` extractor (`--max-filesize 100M`, strict `\d{5,25}` ID check) | None | **Live per ad ID** | Downloads video + `.info.json` (advertiser, page ID, ad ID) for known Meta ad IDs; subject to Meta ad takedown/expiry. |
| **Google Ads Transparency Center** (`google_atc_*`) | Internal RPC `adstransparency.google.com/anji/_/rpc/SearchService/*` (`PL=2616`) | None | **Fragile — currently rate-limited (`429 /sorry/index`)** | Designed for advertiser/domain -> creative pivots, but Google aggressively challenges automated/datacenter traffic with HTTP `429` / CAPTCHA redirects. Recorded as `rate_limited` in `LAST_STATUS`. |
| **LinkedIn Ad Library** (`linkedin_search`) | `https://www.linkedin.com/ad-library/search` | None | **Blocked (`403` / `999`)** | Anti-bot protection routinely returns HTTP `403`/`999` to plain `requests`. Raises `HTTPError` and records `blocked` in `LAST_STATUS`. |

### 5.1 Campaign Watch — pivot search on a known campaign's identifiers (`scheduler.watch_campaigns`)

The keyword scan (`scheduler.run_once`) only finds *suspicious* ads. The campaign watch looks for *new materials of campaigns already detected*, by searching the public sources with each campaign's own identifiers, the same pivoting on shared identifiers that Starov et al. (2018) use to expand campaigns from analytics IDs.

- **Seeds** (`scheduler.campaign_seeds`): the identifier values held by the campaign's members that similarity already treats as linking. They must be *counted* (`similarity.counted`: df/N ≤ `config.MAX_DF`). They come from three groups: `domains` (registrable domain; generic/CDN and decoy media domains dropped with `web.is_decoy_or_generic_domain`), `ad_library` (only `advertiser_id`, since an ad ID names a single ad) and `product` (real brand/media names recognised by the gazetteer are dropped, because they return legitimate ads). Caps: the `WATCH_MAX_CAMPAIGNS = 8` largest campaigns per run (multi-material first), or one campaign on request; at most `WATCH_MAX_SEEDS = 4` seeds per campaign. Values held by more members come first, and the groups are taken in turn. Requests are paced by the same `REQUEST_PAUSE = 0.5 s`.
- **Sources per seed**:

  | Seed group | Queried in |
  |---|---|
  | domain | `google_atc_creatives(domain=…)`, `ms_adlib_search(domain)`, new CERT Polska entries whose domain contains the domain's second-level label (≥ 5 characters, `_match_domain_stems`) |
  | advertiser ID | `google_atc_creatives(advertiser_id=…)`, only for Google IDs (`AR…`); other formats (e.g. Meta page IDs) are skipped and the reason is shown |
  | product | `ms_adlib_search(product)`, `meta_api_search(product)` (only with `META_ACCESS_TOKEN`), CERT Polska stem = folded product name without spaces/hyphens (≥ 5 characters) |

  CERT Polska is read once per run (`sources.cert_pl_watch`). It keeps its own watermark (`cert_pl_watch_last_id`), so the keyword scan and the watch each see every new entry once.
- **Provenance**: every hit carries `seed = {campaign, campaign_label, group, type, value, source}`, so the UI can say e.g. "found via the domain healthlinkq.pro of campaign C1 · Microsoft Ad Library". Hits are ordered by campaign, then source. They are deduplicated with `_dedup_key` against the stored `scheduler_found` list. An item already found by the keyword scan is kept once and only gains its `seed`.
- **A hit is a lead, not a link.** Nothing is linked to the campaign because of the seed. With `analyse=True` (at most 5 new hits) each hit goes through the normal capture → `engine.analyse_new` → `cluster.assign` path. That decision (`known_campaign` / `new_campaign` / `merge_proposal` / `duplicate`) is stored as `outcome`. `confirmed` is true only when the assigned campaign contains the seed campaign's members. The UI shows "potwierdzone: C1" or "nie potwierdzono (…)". No new score or weight is introduced: the triage score is the unchanged `suspicion()`.
- **Integration**: `POST /api/scanner/watch {campaign?: int, analyse: bool}` (background job), `GET /api/scanner/seeds?campaign=` (preview), `GET /api/scanner` (`watch_found`, `watch_last`). `run_once(watch=True)` and `start_background(watch=True)` add the watch to the one-off and periodic scan, and `python -m ftf.scheduler --once --watch` does the same from the CLI. Events are logged as `watch_scan` / `watch_run`. UI: the "Szukaj materiałów znanych kampanii" section on the scanner page and the "Szukaj nowych materiałów tej kampanii" button on each campaign page.

---

## 6. Testing & Verification

Web-fetching safety, cloaking logic, ingestion edge cases, enrichment caching, and live endpoints are covered by two test suites:

```bash
# Offline unit & security regression tests (no internet required, fast)
.venv/bin/python -m unittest tests.test_web_fetching tests.test_campaign_watch

# Opt-in live network smoke tests (real CERT PL, RDAP, DNS, capture against benign sites)
FTF_LIVE_TESTS=1 .venv/bin/pytest tests/test_live_smoke.py
```

Key behaviors verified:
- SSRF blocking of `file://`, `127.0.0.1`, `169.254.169.254`, RFC1918, `::ffff:127.0.0.1`, and redirect-to-localhost chains.
- Semantic cloaking verdicts across synthetic identical pages, CSP-nonce mutations, responsive mobile layouts, WAF `403` bot blocks, and genuine domain/content cloaking.
- ZIP-slip, symlink, and zip-bomb rejection in `ingest._extract_zip_safely`.
- Magic-byte asset classification for `.pobrane`/`.pobierz` files and sibling MHTML URL recovery.
- HAR dotfile loading, `POST 404` skipping, untruncated redirect chasing, and session UUID filtering.
- RDAP bootstrap loading, dual-TTL partial error caching, and CERT Polska parent-domain matching.

---

## 7. Authoritative References

1. **Hollenbeck, S., & Newton, A.** (2021). *JSON Responses for the Registration Data Access Protocol (RDAP)*. IETF **RFC 9083**. <https://datatracker.ietf.org/doc/html/rfc9083>
2. **Blanchet, M.** (2022). *Finding the Authoritative Registration Data Access Protocol (RDAP) Service*. IETF **RFC 9224**. <https://datatracker.ietf.org/doc/html/rfc9224>
3. **Odvarko, J., et al.** (2012). *HTTP Archive (HAR) 1.2 Specification*. W3C Web Performance Working Group draft. <https://w3c.github.io/web-performance/specs/HAR/Overview.html>
4. **Palme, J., Hopmann, A., & Shelness, N.** (1999). *MIME Encapsulation of Aggregate Documents, such as HTML (MHTML)*. IETF **RFC 2557**. <https://datatracker.ietf.org/doc/html/rfc2557>
5. **Mozilla Foundation.** *Public Suffix List (PSL)*. <https://publicsuffix.org/>
6. **OWASP.** *Server-Side Request Forgery (SSRF) Prevention Cheat Sheet*. <https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html>
7. **Invernizzi, L., Thomas, K., Kapravelos, A., Comanescu, O., Picod, J.-M., & Bursztein, E.** (2016). *Cloak of Visibility: Detecting When Machines Browse a Different Web*. **IEEE Symposium on Security and Privacy (S&P 2016)**, pp. 743–758. <https://doi.org/10.1109/SP.2016.50>
8. **Zhang, P., Oest, A., Cho, H., Sun, Z., Johnson, R. C., Wardman, B., Sarker, S., Kapravelos, A., Bao, T., Wang, R., Shoshitaishvili, Y., Doupé, A., & Ahn, G.-J.** (2021). *CrawlPhish: Large-scale Analysis of Client-side Cloaking Techniques in Phishing*. **IEEE Symposium on Security and Privacy (S&P 2021)**, pp. 1109–1124. <https://doi.org/10.1109/SP40001.2021.00021>
9. **Oest, A., Safaei, Y., Zhang, P., Wardman, B., Tyers, K., Shoshitaishvili, Y., & Doupé, A.** (2020). *PhishTime: Continuous Longitudinal Measurement of the Effectiveness of Anti-phishing Blacklists*. **USENIX Security 2020**, pp. 379–396. <https://www.usenix.org/conference/usenixsecurity20/presentation/oest-phishtime>
10. **Starov, O., Zhou, Y., Zhang, J., Miramirkhani, N., & Nikiforakis, N.** (2018). *Betrayed by Your Dashboard: Discovering Malicious Campaigns via Web Analytics*. **The Web Conference (WWW 2018)**, pp. 227–236. <https://doi.org/10.1145/3178876.3186089> · <https://securitee.org/files/malanalytics_www2018.pdf>
11. **Cui, Q., Jourdan, G.-V., Bochmann, G. V., Couturier, R., & Onut, I.-V.** (2017). *Tracking Phishing Attacks Over Time*. **The Web Conference (WWW 2017)**, pp. 667–676. <https://doi.org/10.1145/3038912.3052654>
12. **Muzammil, M. B., Bilal, M., Ajmal, S., Shongwe, S. C., & Ghadi, Y. Y.** (2025). *Understanding and Detecting Evasive Cloaking in Modern Malicious Web Campaigns* / Large-scale web cloaking measurement literature (**The Web Conference / WWW 2025**). <https://dl.acm.org/doi/proceedings/10.1145/3696410>
13. **CERT Polska (NASK).** *Warning List API v2 (`hole.cert.pl`)* & *Malicious Advertisements / Annual Reports (2024–2025)*. <https://cert.pl/lista-ostrzezen/> · <https://cert.pl/uploads/docs/Raport_CP_2025.pdf>
14. **KommAustria / RTR.** (2025). *Betrugsökosystem Werbung / Online Advertising Fraud Ecosystem Study*. <https://www.rtr.at/medien/aktuelles/publikationen/Publikationen/Publikationen_2026/Betrugsoekosystem_Werbung_KommAustria_final_EN.pdf>
15. **CIRCL.** *Lookyloo — Web Capture & Redirect-Tree Analysis Interface*. <https://github.com/Lookyloo/lookyloo>
