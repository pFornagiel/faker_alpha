# 01 — Ad libraries and platform scraping (acquisition layer)

Research date: 2026-11-21. Scope: what can be collected today, and how, for the "Kolekcjoner Fejków / Follow the Fake" linking system (Polish scam ads).

Legend for the evidence level used throughout:

- **LIVE** — I ran the request from this machine today (no login, no credentials, 1-10 requests per source).
- **READ** — taken from official docs / a repo's source or README / a report fetched today.
- **MEMORY** — from prior knowledge, not re-checked today. Treat as a lead.

Test artefacts (requests, raw responses, helper scripts) are in
`/tmp/claude-1000/-home-pawel/c47d1afe-7feb-4ed9-b69b-483c2e110a3d/scratchpad/research_a/`.

---

## 0. TL;DR

1. **Meta is the main target and the only hard one.** The official `ads_archive` Graph API does return *all* ads delivered to the EU (incl. PL, non-political), searchable by keyword and country, kept 1 year. It needs a user access token from a Facebook account that passed identity confirmation — **the user must supply this**. Without a token, the public web UI answers a plain HTTP client with `403` + a JavaScript handshake page (LIVE); open-source scrapers get past it by replaying the handshake or by driving a real browser. I did not go past that page (see 1.1.2).
2. **Three ad repositories answered with zero credentials today (LIVE):** Google Ads Transparency Center internal RPC, Microsoft Ad Library REST API, LinkedIn Ad Library HTML. Of these only Microsoft and LinkedIn support free-text keyword search; Google is advertiser/domain pivot only.
3. **Best free seed for Poland: CERT Polska warning list** (`hole.cert.pl`), LIVE: 126,633 domains in the rolling 6-month window, about 600-900 new per day, JSON with insert timestamps, free for any use. No category labels, so it mixes phishing, fake shops and fake investments.
4. **yt-dlp works without cookies today (LIVE)** for YouTube search, metadata, comments and Polish auto-captions, and ships a `facebook:ads` extractor for Ad Library video creatives.
5. **Cloaking is real and measurable with trivial means (LIVE):** 1 of 8 sampled CERT-listed domains returned a different page (different `<title>`, 4x the size) to an Android Facebook in-app-browser profile with `Referer: l.facebook.com` + `fbclid` than to a headless-Chrome profile. 4 of 8 were JS-only SPA shells sharing one Sentry key and build hash — a ready-made linking signal that needs a rendering browser to exploit.
6. **No public labelled dataset of scam ads was found** (HF/Kaggle/Zenodo). All major studies (KommAustria, Gen Digital, AI Forensics, Debunk, TTP) built their own from the Meta Ad Library API and did not release data.

---

## 1. Ad libraries / transparency repositories

### Summary table

| Source | Access | Fields / creatives | Country=PL + keyword? | Works without login? | Best OSS tool | Verified live? |
|---|---|---|---|---|---|---|
| **Meta Ad Library API** (`/ads_archive`) | FB account + identity confirmation (facebook.com/ID) + dev app + user token | text bodies, link titles/captions/descriptions, page id/name, start/stop, platforms, languages, snapshot URL; EU: `eu_total_reach`, age/gender/country breakdown, `beneficiary_payers`, targeting. No spend/impressions for commercial ads | Yes: `ad_reached_countries=['PL']`, `search_terms`, `ad_type=ALL` | No (token) | `facebookresearch/Ad-Library-API-Script-Repository` (2025-02), `soxoj/AdsLibrary` `MetaGraphSource` (2026-07) | Docs READ (v27.0). Tokenless call returns `OAuthException` (LIVE) |
| **Meta Ad Library web UI** | None formally; anti-bot handshake, then SSR page + GraphQL | Richer than API: media URLs (image/video), `link_url`, CTA, cards, collation (variants) | Yes: `country=PL&q=...&search_type=keyword_unordered` | Browser: yes. Plain HTTP: `403` + JS handshake | `soxoj/AdsLibrary` `MetaScraperSource` (first ~30 results/query); Playwright + response interception for more | Handshake page LIVE; nothing beyond it |
| **Meta Ad Library Report** | Public CSV | Political/issue advertisers and spend only | Country yes, no creative search | Yes | — | Not tested; irrelevant for commercial scams |
| **Meta Content Library / API** | Academic / non-profit researcher application, reviewed by CASD, clean-room only | Public organic posts (FB, IG, WhatsApp Channels) | Yes | No | — | READ; not feasible for a hackathon |
| **Google Ads Transparency Center** (web RPC) | None | advertiser id/name, creative id, format, first/last shown, image URL or preview JS, landing domain; per-region impression band + dates (EU) | Region yes. **No ad-text keyword search** — advertiser name or domain only | **Yes** | `soxoj/AdsLibrary` `google_api.py` (2026-07); `faniAhmed/GoogleAdsTransparencyScraper` (stale, 2023-07) | **LIVE** (3 RPCs) |
| **Google ATC BigQuery** `bigquery-public-data.google_ads_transparency_center` | Google Cloud account | `creative_stats`, `removed_creative_stats` (EEA removals with reasons) | SQL on region | No (GCP login) | `bq` / `google-cloud-bigquery` | Not tested (needs account) |
| **TikTok Commercial Content API** | Approved research application → client key/secret | ad id, first/last shown, status, video URLs, image URLs, reach, advertiser name, `paid_for_by` | Yes: `country_code`, `search_term` (≤50 chars) | No | `soxoj/AdsLibrary` `tiktok_api.py` | Docs READ |
| **TikTok library.tiktok.com** | None in a browser | Same plus rendered creatives | Yes (region + keyword) | Page `200`; my direct API POST got `421 system busy` | none maintained on GitHub; Playwright | Partially LIVE |
| **LinkedIn Ad Library** | None | advertiser, payer, body text, landing link, media, run dates, impressions total + by country, targeting | Yes: `keyword=` + `countries=PL` | **Yes** (server-rendered HTML) | `soxoj/AdsLibrary` `linkedin_api.py` | **LIVE** (24 ads + 1 detail page) |
| **Microsoft (Bing) Ad Library API** | None (token only raises limits) | AdId, advertiser id/name, title, description, display URL, **destination URL**, image assets; detail: dates, impression band, by-country share, targeting, payer | Yes: `searchText`, `countryCodes=151` | **Yes** (official public REST) | none needed — plain `GET` | **LIVE** (4 calls) |
| **X Ads Repository** (ads.x.com/ads-repository) | None (guest session) | CSV: advertiser, funding entity, creative, dates, targeting, impressions, reach | Country yes; **advertiser handle only, no keyword** | SPA shell `200` | `soxoj/AdsLibrary` `x_api.py` (guest CSV export, takes minutes) | Shell only LIVE |
| **Snapchat Ads Gallery** (adsgallery.snap.com) | None | EU commercial ads gallery | Country yes | Page `200` | none | Shell only LIVE |
| **Pinterest Ads Repository** | None | EU ads, reach bands | Country yes | Page `200` | none | Shell only LIVE |
| **Apple Ad Repository** (adrepository.apple.com) | None | App Store search ads only | Country yes | Page `200` | none | Shell only LIVE; low relevance |
| **EU DSA Transparency Database** | Search UI + daily dumps: none. Research API: EU Login + helpdesk-issued token | Statements of reasons: platform, category (`STATEMENT_CATEGORY_SCAMS_AND_FRAUD`), keywords, decision, dates, language, territorial scope. **No content, no URL, no ad ID** | Filter on `territorial_scope`, `content_language`, category | Yes (UI, dumps) | `dsa-tdb` (official Python package) | Search page LIVE |

### 1.1 Meta

#### 1.1.1 Official Ad Library API — `GET https://graph.facebook.com/v27.0/ads_archive`

READ from `developers.facebook.com/docs/graph-api/reference/ads_archive/` and `/archived-ad/` (page shows v27.0 today).

**Coverage.** All ads delivered to any EU location (non-political included) plus political/issue ads worldwide. Doc wording: ads that reached no EU location are returned only if they are political/issue ads. So Polish investment/health/giveaway scam ads are in scope. Retention is one year after last impression (DSA Art. 39).

**Query parameters**

| Parameter | Notes |
|---|---|
| `ad_reached_countries` | required in practice; ISO codes, e.g. `['PL']` (or `ALL`) |
| `ad_type` | `ALL` (default), `POLITICAL_AND_ISSUE_ADS`, `FINANCIAL_PRODUCTS_AND_SERVICES_ADS`, `EMPLOYMENT_ADS`, `HOUSING_ADS` |
| `search_terms` | ≤100 chars, spaces = AND, **not translated** (search in Polish) |
| `search_type` | `KEYWORD_UNORDERED` (default) or `KEYWORD_EXACT_PHRASE` |
| `search_page_ids` | up to 10 page IDs — the pivot for "all ads of this page" |
| `ad_active_status` | `ACTIVE` (default), `INACTIVE`, `ALL` — use `ALL`, scam ads die within hours/days |
| `ad_delivery_date_min` / `_max` | `YYYY-mm-dd` — incremental scheduler windows |
| `media_type` | `ALL`, `IMAGE`, `MEME`, `VIDEO`, `NONE` |
| `publisher_platforms` | `FACEBOOK`, `INSTAGRAM`, `AUDIENCE_NETWORK`, `MESSENGER`, `WHATSAPP`, `THREADS`, ... |
| `languages` | ISO 639-1, e.g. `['pl']` |
| `unmask_removed_content` | boolean, default false — "reveals content removed for policy violations". Worth testing with a token; I could not |

**Fields** (request via `fields=`)

- Always: `id`, `ad_creation_time`, `ad_creative_bodies`, `ad_creative_link_captions`, `ad_creative_link_titles`, `ad_creative_link_descriptions`, `ad_delivery_start_time`, `ad_delivery_stop_time`, `ad_snapshot_url`, `page_id`, `page_name`, `publisher_platforms`, `languages`, `total_reach_by_location`.
- EU-delivered ads: `eu_total_reach`, `age_country_gender_reach_breakdown`, `beneficiary_payers`, `target_ages`, `target_gender`, `target_locations`.
- Political only (not available for scam ads): `spend`, `impressions`, `currency`, `bylines`, `demographic_distribution`, `delivery_by_region`, `estimated_audience_size`.

**What the API does not give you directly:** image/video files and the real landing URL. `ad_snapshot_url` is an HTML page (`/ads/archive/render_ad/?id=...&access_token=...`) that must be rendered or parsed to extract media and the click-through URL. `ad_creative_link_captions` is the *displayed* domain, which advertisers can set to something unrelated to the destination (CERT Polska documents a `gazeta.pl` label on a different domain).

**Access steps** (secondary sources + MEMORY; Meta's own access page returned 403 to my fetch): (1) confirm identity and location at `facebook.com/ID` with a personal account (ID document; can take a day or more), (2) register at Meta for Developers, (3) create an app, (4) take a user access token from Graph API Explorer, optionally exchange for a long-lived (~60 day) token. Rate limit is not published (error `613`); ~200 calls/hour per user is the commonly quoted figure (MEMORY). KommAustria's study hit the limit hard enough to cut one keyword's window from three months to one week.

```bash
curl -G 'https://graph.facebook.com/v27.0/ads_archive' \
  --data-urlencode "access_token=$META_TOKEN" \
  --data-urlencode "ad_reached_countries=['PL']" \
  --data-urlencode "ad_type=ALL" --data-urlencode "ad_active_status=ALL" \
  --data-urlencode "search_terms=platforma inwestycyjna" \
  --data-urlencode "ad_delivery_date_min=2026-11-14" \
  --data-urlencode "fields=id,page_id,page_name,ad_creative_bodies,ad_creative_link_titles,ad_creative_link_captions,ad_creative_link_descriptions,ad_delivery_start_time,ad_delivery_stop_time,ad_snapshot_url,publisher_platforms,languages,eu_total_reach,beneficiary_payers,target_ages,target_gender,target_locations,age_country_gender_reach_breakdown" \
  --data-urlencode "limit=100"
# follow .paging.next until .data is empty
```

LIVE: the same call without a token returns `{"error":{"type":"OAuthException","code":1,...}}`.

**Known data-quality problems** (READ, KommAustria/RTR study, data Sept-Nov 2025, Meta API crawler):

- 62.4% of identified scam ads were already removed by Meta at collection time (46.9% page/account disabled, 16.2% content violation). Scheduler must poll often and store everything on first sight.
- Ads documented earlier could not be found later (one keyword went from ~2,300 ads to zero), despite the 1-year retention duty.
- Some ads are not retrievable by text search although visible via the page — several celebrity names had to be dropped from keyword lists. Always pivot by `page_id` as well.
- `beneficiary_payers` is unverified free text ("1", random strings, "facebook"); one payer named "1" accounted for 11,712 ads. Useless as identity, **useful as a linking token**.
- Pages marked disabled later ran new ads under the same Page ID.
- 58% of not-yet-removed ads in one scheme pointed to `fb.me` (Messenger/WhatsApp funnels), i.e. no landing page at all.

CERT Polska (READ, Dec 2024) adds: an advertiser can run several versions so the library may show a different creative than users saw; indexing lags up to 24 h; sometimes no version is indexed.

#### 1.1.2 Public web UI — `https://www.facebook.com/ads/library/`

URL parameters (MEMORY, consistent with `soxoj/AdsLibrary` source READ today):
`active_status=all|active|inactive`, `ad_type=all`, `country=PL`, `q=<keyword>`, `search_type=keyword_unordered|keyword_exact_phrase|page`, `view_all_page_id=<page_id>`, `media_type=all|image|video|meme`, `id=<ad_archive_id>` (single ad).

**LIVE result:** a plain `curl` with a desktop Chrome UA gets `HTTP 403` and a 481-byte page whose script does `fetch('/__rd_verify_...?challenge=3', {method:'POST'})` and then reloads. A real browser passes this transparently.

**I stopped there.** Replaying that POST with a cookie jar was declined by this session's permission policy as unauthorized access, and I did not look for another route around it. Everything below about what lies behind the handshake is READ from open-source code, not verified by me.

How `soxoj/AdsLibrary` (`AdsLibrary/main.py`, last commit 2026-07-12, `requests` only) does it:

1. GET the library URL → 403 handshake page; regex out the `/__rd_verify_...` path; POST to it (sets an `rd_challenge` cookie); GET again.
2. The first page of results is server-rendered into the HTML as a Relay payload: find `"search_results_connection":` and parse the balanced JSON object → `edges[].node.collated_results[]`, each with `ad_archive_id`, `page_id`, `snapshot{...}` (title, body, images, videos, cards, link URL). About 30 ads per query.
3. The old `ads/library/async/search_ads/` endpoints are gone (404). Deeper pagination is GraphQL (`/api/graphql/`, operation `AdLibrarySearchPaginationQuery`) with a `doc_id` that rotates roughly monthly — the reason most scrapers break at page 2.

Practical options without a token, in order of robustness:

- **Playwright (or patchright/camoufox) with a real browser**: open the search URL, scroll, and capture `page.on("response")` for `/api/graphql/` bodies. No `doc_id` bookkeeping, because the page issues its own queries. This is what the paid Apify actors do.
- **First-page-only via SSR payload** (soxoj approach): cheap, ~30 newest ads per keyword per run. With a keyword list of 50-100 Polish scam phrases polled hourly this is already a usable discovery feed.
- **yt-dlp `facebook:ads`** extractor (present in yt-dlp 2026.10.26, LIVE-checked in the extractor list, not run): takes `https://www.facebook.com/ads/library/?id=<id>` and downloads the video creative(s).

ToS note: automated collection from the web UI is against Meta's terms. The API route is the clean one. For NASK specifically, DSA Art. 40(12) (access to publicly accessible data for vetted/qualifying researchers) is the legal hook worth mentioning in the pitch.

#### 1.1.3 Ad Library Report and Meta Content Library

- **Ad Library Report**: CSV of political/issue advertisers and spend. Meta stopped accepting political ads in the EU (soxoj README, READ), so it adds nothing for Polish commercial scams.
- **Meta Content Library/API**: public organic posts from FB/IG/WhatsApp Channels. Application via Research Tools Manager, independently reviewed by CASD; requires affiliation with an academic or non-profit research organisation; API only inside Meta Secure Research Environment or SOMAR VDE; processing "typically 2 to 3 weeks after review" (READ). NASK may qualify long-term; it is not usable in a hackathon and data cannot leave the clean room.

### 1.2 Google Ads Transparency Center — works without login (LIVE)

No official API. The site's internal RPCs answer a plain `curl` (no TLS impersonation needed at this volume; one vendor write-up claims 403s for Python's default TLS stack at scale — keep `curl_cffi` in reserve).

Covers Search, YouTube, Display, Shopping, Maps, Play. YouTube video ads are in here, which makes it the route to sponsored-video scams.

Region code for Poland is `2616` (confirmed in a response).

**1) Advertiser/domain suggestions by keyword**

```bash
curl 'https://adstransparency.google.com/anji/_/rpc/SearchService/SearchSuggestions?authuser=' \
  -H 'content-type: application/x-www-form-urlencoded' \
  -H 'origin: https://adstransparency.google.com' -H 'referer: https://adstransparency.google.com/?region=PL' \
  -A 'Mozilla/5.0 ... Chrome/130 Safari/537.36' \
  --data-urlencode 'f.req={"1":"inwestycje","2":10,"3":10}'
```

Returns advertisers `{"1":{"1":name,"2":"AR...","3":"PL","4":{"2":{"1":lo,"2":hi}}}}` (ad count band; `"5":true` = verified) and matching domains `{"2":{"1":"noweinwestycje.pl"}}`.

**2) Creatives of an advertiser or domain**

```bash
# by advertiser
--data-urlencode 'f.req={"2":40,"3":{"12":{"1":"","2":true},"8":[2616],"13":{"1":["AR11575447740489924609"]}},"7":{"1":1,"2":0,"3":2616}}'
# by landing domain
--data-urlencode 'f.req={"2":40,"3":{"12":{"1":"noweinwestycje.pl","2":true},"8":[2616]},"7":{"1":1,"2":0,"3":2616}}'
# endpoint: /anji/_/rpc/SearchService/SearchCreatives?authuser=
```

Response mapping (inferred from LIVE responses): per creative `"1"` advertiser id, `"2"` creative id (`CR...`), `"3"` rendering — either `{"3":{"2":"<img src=https://tpc.googlesyndication.com/archive/simgad/...>"}}` or `{"1":{"4":"https://displayads-formats.googleusercontent.com/ads/preview/content.js?..."}}` — `"4"` format (1 text, 2 image, 3 video), `"6"`/`"7"` first/last shown (epoch seconds), `"12"` advertiser name, `"13"` day count, `"14"` landing domain. Top level: `"2"` next-page token, `"4"`/`"5"` total-count band. Passing the token back for page 2 is as in the OSS scrapers (MEMORY, not tested).

**3) Creative detail**

```bash
# /anji/_/rpc/LookupService/GetCreativeById?authuser=
--data-urlencode 'f.req={"1":"AR02004893551271346177","2":"CR01844009032755445761","5":{"1":1,"2":0,"3":2616}}'
```

Returns all variations (`"5"`), and per-region stats `"17":[{"1":2616,"2":"20000","3":"25000","4":20260820,"5":20261120}]` = Poland, 20k-25k impressions, first/last shown dates.

**Limits found LIVE**

- **No ad-text keyword search.** A query with only a region (and a format filter) returned `{}`. Discovery must come from elsewhere; GATC is a *pivot*: domain → advertiser → all creatives → other domains.
- Three fresh CERT-listed scam domains returned `{}` — expected, as most Polish scam volume is on Meta, and Google removes suspended advertisers' ads from the centre.
- Creative text for text/display ads sits inside `content.js` preview scripts and needs rendering.

**BigQuery public dataset** `bigquery-public-data.google_ads_transparency_center` (READ from Google community threads; schema details MEMORY): tables `creative_stats` (advertiser id, legal/disclosed name, location, verification status, creative id + page URL, format, per-region first/last shown and impression bands) and `removed_creative_stats` (ads served in the EEA that Google removed: where and why, plus serving dates and a Transparency Center link). Needs a Google Cloud account; free tier is 1 TB of queries/month but the tables are large, so select columns and filter. Users report it is less complete than the website. `removed_creative_stats` is the single most interesting item here for scam hunting; not tested because it requires a login.

### 1.3 TikTok

**Commercial Content API** (READ, developers.tiktok.com):

- `POST https://open.tiktokapis.com/v2/research/adlib/ad/query/?fields=...`, scope `research.adlib.basic`, `Authorization: Bearer <client token>` from `/v2/oauth/token/`.
- Body: `filters.ad_published_date_range{min,max}` (YYYYMMDD, min within one year), `filters.country_code`, plus `ad_type`, `ad_status`, `ad_reach`, `ages`, `gender`; `search_term` (≤50 chars), `search_type` `exact_phrase|fuzzy_phrase`; `max_count` (max 10 per the ads page); `search_id` for paging.
- Fields: `ad.id`, `ad.first_shown_date`, `ad.last_shown_date`, `ad.status`, `ad.videos`, `ad.image_urls`, `ad.reach`, `advertiser.business_id`, `advertiser.business_name`, `advertiser.paid_for_by`.
- Also `/v2/research/adlib/commercial_content/query/` for branded/creator content (EEA creators, max 50).
- Access requires an approved research application; no timeline is published. `soxoj/AdsLibrary` README reports HTTP 500 `internal_error` on ad queries as of 2026-06-13 with a valid token. No ad caption text is returned.

**Web library** `https://library.tiktok.com/ads?region=PL&...`: page loads without login (`200`, LIVE). My one direct POST to its search endpoint returned `421 system busy`; the endpoint path was from memory, so this only shows that a naive replay does not work. No maintained GitHub scraper found; the paid Apify actors use browsers. Treat as Playwright-only and second priority.

### 1.4 LinkedIn Ad Library — works without login (LIVE)

```bash
curl -A '<desktop UA>' 'https://www.linkedin.com/ad-library/search?keyword=inwestycje&countries=PL'
# → 200, server-rendered HTML, 24 ads; ids via regex /ad-library/detail/(\d+)
curl -A '<desktop UA>' 'https://www.linkedin.com/ad-library/detail/1621066473'
```

The detail page (LIVE) exposes: advertiser, "paid for by", ad format, full body text, landing URL (`...?trk=ad_library_ad_preview_headline_content`) and `lnkd.in` short links, media (`media.licdn.com`), active period, total impressions band, impressions by country, targeting facets (language, location, audience categories incl./excl.). Low prior for consumer scams, but it costs two regexes.

### 1.5 Microsoft (Bing) Ad Library — official public API, no key (LIVE)

Base `https://adlibrary.api.bingads.microsoft.com/api/v1/` (READ: Microsoft Learn, "publicly available and doesn't require any user sign-up or log-in"; unauthenticated calls have stricter, unspecified limits). EEA-served ads only, since June 2023.

```bash
curl 'https://adlibrary.api.bingads.microsoft.com/api/v1/Ads?searchText=kryptowaluty&top=12&skip=0&countryCodes=151'
curl 'https://adlibrary.api.bingads.microsoft.com/api/v1/Ads(76966046489342)?$expand=AdDetails($expand=ImpressionsByCountry,Targets)'
curl 'https://adlibrary.api.bingads.microsoft.com/api/v1/Advertisers?searchText=...&top=3'
```

- Poland = `151`. Other params: `startDate`, `endDate` (`yyyy-MM-dd`), `advertiserId`.
- List fields: `AdId`, `AdvertiserName`, `AdvertiserId`, `Title`, `Description`, `DisplayUrl`, **`DestinationUrl`**, `AssetJson` (image URLs on `bing.com/th?id=...`), `@odata.count`.
- Detail fields: `PaidForByName`, `StartDate`, `EndDate`, `TotalImpressionsRange` (e.g. "2.5M - 5M"), `ImpressionsByCountry`, `Targets`, restriction reason.
- LIVE: `searchText=inwestycje` → 201 ads; `kryptowaluty` + PL → 4 ads.

The only repository that hands over the real destination URL in a documented JSON API with no credentials. Search/native ads on Bing/MSN; CERT Polska names sponsored search results for investment keywords as a real vector.

### 1.6 X, Snapchat, Pinterest, Apple

- **X** `https://ads.x.com/ads-repository`: SPA (LIVE `200`). Search by advertiser handle + country + date range, result is a CSV export; no keyword search, no per-ad ID. `soxoj/AdsLibrary/x_api.py` implements it on a guest session (reverse-engineered, export takes minutes, "the repository is sparse"). Only useful once you already have a handle.
- **Snapchat** `adsgallery.snap.com`, **Pinterest** `ads.pinterest.com/ads-repository/`, **Apple** `adrepository.apple.com`: pages load (LIVE `200`), no documented API, no maintained OSS client. Not where Polish investment/health scams run. Skip for the POC.

### 1.7 EU DSA Transparency Database

- Search UI `https://transparency.dsa.ec.europa.eu/statement?category[]=STATEMENT_CATEGORY_SCAMS_AND_FRAUD` — LIVE `200`; filters: `platform_id`, `category`, `category_specification`, `content_type`, `content_language`, `territorial_scope`, `decision_*`, `source_type`, `automated_detection`, `account_type`. Last 6 months, first 10,000 results paginated, first 1,000 exportable as CSV.
- Daily dumps: `https://transparency.dsa.ec.europa.eu/explore-data/download` — global "full" zip was 2.99 GB (44.7 GB CSV) for 2026-11-20; per-platform files exist (Facebook, Instagram, TikTok, YouTube, Google Shopping...). Official `dsa-tdb` Python package for scripted download/Parquet/aggregates.
- Research API `https://transparency.dsa.ec.europa.eu/api/v1/research/{search,sql,count,query,aggregates}` (OpenSearch): Bearer token via EU Login + email to the DSA helpdesk; max 1,000 rows, last 6 months.

**Verdict:** the schema has no URL, no content and no platform ad ID — only an opaque `puid` — and submitters are told not to include personal data. It cannot seed removed scam ads. Its use is contextual: daily counts of `SCAMS_AND_FRAUD` decisions per platform with `territorial_scope` containing PL, as a backdrop chart. Optional.

---

## 2. Organic platform scraping (state on 2026-11-21)

Last-commit dates read today from each repo's commit feed.

| Platform | Tool | Last commit | Login needed? | State / notes |
|---|---|---|---|---|
| YouTube | **yt-dlp** | 2026-11-21 (release 2026.10.26) | No | **LIVE**: `ytsearch3:<query>` flat search; `--write-info-json --write-comments --write-auto-subs --sub-langs pl --skip-download` gave title, description, channel id/handle, upload date, tags, views, likes, thumbnail, 5 comments, Polish auto-captions (VTT). Warning about missing impersonation target (install `yt-dlp[default,curl-cffi]`). At volume or from datacenter IPs expect "confirm you're not a bot" → cookies/PO token |
| YouTube | YouTube Data API v3 | — | Free API key | 10,000 units/day; `search.list` = 100 units, so ~100 searches/day (MEMORY). No caption download for third-party videos. Use for channel/video metadata at scale, yt-dlp for captions/media |
| Facebook Ad Library creatives | yt-dlp `facebook:ads` | as above | No | Extractor present (LIVE-listed); not run |
| Facebook public video/reel | yt-dlp `facebook`, `facebook:reel` | as above | Usually no | Per-URL only |
| Facebook pages/posts | kevinzg/facebook-scraper | 2023-10-30 | — | **Dead.** Fork `moda20/facebook-scraper` last commit 2024-06. No maintained no-login OSS scraper found. Use the Ad Library instead; for a single public post URL use Playwright |
| Instagram | instaloader | 2026-11-01 | Effectively yes | Anonymous access heavily rate-limited (401/429), profile post iteration requires login; repeated doc_id breakages fixed by PRs through 2026. Account ban risk |
| Instagram | gallery-dl | 2026-11-21 | Cookies for most | Actively maintained, broad site support |
| Instagram | yt-dlp `Instagram` | — | Often cookies | Single post/reel; `instagram:user` flagged "CURRENTLY BROKEN" in the extractor list (LIVE) |
| Instagram | instagrapi | 2026-11-19 | Yes (private API) | Works, highest ban risk |
| X/Twitter | twscrape | 2026-11-19 | Yes (account pool/cookies) | Working per 2026 reviews |
| X/Twitter | twikit | 2026-03-10 | Yes | Intermittently broken (open issues on transaction-id, user fields) |
| X/Twitter | snscrape / nitter | 2023-06 / archived | — | **Dead** for X |
| X/Twitter | yt-dlp `twitter` | — | Sometimes | Per-tweet video |
| TikTok | yt-dlp `TikTok`, `tiktok:user` | — | No (per URL) | `tiktok:tag`, `tiktok:sound`, `tiktok:effect` flagged broken (LIVE-listed) |
| TikTok | davidteather/TikTok-Api | 2026-11-14 | `ms_token` cookie + Playwright browser | Maintained, brittle, heavy |
| Telegram | Telethon | **GitHub repo archived 2026-02-21, moved to Codeberg** | Yes: `api_id`/`api_hash` + phone login | Still installable from PyPI; v1 in maintenance mode. Public-channel web preview `t.me/s/<channel>` needs no login (MEMORY; my single test hit a redirect on a guessed channel name, so unverified) |
| Multi-platform archiving | **bellingcat/auto-archiver** | 2026-11-18 | Per platform | Wraps yt-dlp, Telethon, instaloader, screenshots, WACZ, hashing. Good fit for "URL in → evidence bundle out" |
| Generic crawl | crawl4ai | 2026-11-20 | — | Playwright-based, markdown extraction, fine on CPU |
| Generic crawl | scrapy / crawlee-python | 2026-11-19 / 2026-11-20 | — | Stable |
| Stealth browsers | patchright-python / camoufox / nodriver / Scrapling | 2026-11-10 / 2026-11-19 / 2026-10-26 / 2026-11-17 | — | All active. camoufox = patched Firefox (~500 MB download); patchright = drop-in patched Playwright Chromium |
| HTTP with browser TLS | curl_cffi | 2026-11-21 | — | Tiny; fixes TLS-fingerprint 403s |
| Capture/forensics | **Lookyloo/PlaywrightCapture**, Lookyloo | 2026-11-13 / 2026-11-07 | — | See section 4 |
| Archiving | browsertrix-crawler | 2026-11-11 | — | Docker, WARC/WACZ; heavy for a POC |
| Self-hosted scraping API | Firecrawl | 2026-11-20 | — | Multi-container stack; overkill with ~9 GB disk |

Disk note: Playwright Chromium is ~300-400 MB with dependencies; camoufox and browsertrix are larger. Pick **one** browser (Playwright Chromium, optionally via patchright) and use it for everything.

---

## 3. Seeding sources for Poland

### 3.1 CERT Polska warning list — `hole.cert.pl` (LIVE)

| URL | Format |
|---|---|
| `https://hole.cert.pl/domains/v2/domains.json` | JSON array: `RegisterPositionId`, `DomainAddress`, `InsertDate`, `DeleteDate` (22.5 MB) |
| `https://hole.cert.pl/domains/v2/domains.csv` | TSV: `PozycjaRejestru`, `AdresDomeny`, `DataWpisu`, `DataWykreslenia` |
| `https://hole.cert.pl/domains/v2/domains.txt` | active domains, one per line (2.6 MB) |
| `https://hole.cert.pl/domains/v2/domains.xml`, `_hosts.txt`, `_adblock.txt`, `_rpz.db`, `_mikrotik.rsc` | other formats |
| `https://hole.cert.pl/domains/v2/actions_2026.log` | JSONL event stream for the whole year: `RegisterPositionId`, `DomainAddress`, `ActionTime`, `ActionType` (`block`/...) — goes back beyond the 6-month window |
| `https://hole.cert.pl/schema/certpl_lista_ostrzezen_api_v2.pdf` | spec |

Measured today: 126,633 entries, oldest 2026-05-21 (rolling 6 months), newest minutes old. Monthly inserts: Jun 21,276 · Jul 29,589 · Aug 17,685 · Sep 17,755 · Oct 19,369 · Nov (to 21st) 16,081. Recommended refresh: every 5 minutes. Terms: free for any purpose incl. commercial, no warranty, attribution not required, do not imply endorsement by NASK/CERT Polska.

Caveats: no category or source field (phishing, fake shops and fake investments mixed; CERT says 32k of 80k in 2023 were fake investments); entries are hostnames, sometimes subdomains or `*.pages.dev`; average campaign lifetime is quoted as 21 hours, so capture within minutes of listing.

Why it matters for linking: the names themselves cluster (`alcheariet.store`, `tonegratif.store`, `immiscatal.store`, `speedcangi.store` listed minutes apart, same TLD, same generator pattern), and insert bursts align with campaigns.

Scheduler delta logic: keep `max(RegisterPositionId)`; every 5-15 min fetch `domains.json` (or tail `actions_2026.log` with an HTTP `Range` request — LIVE: range requests return `206`), enqueue new IDs for landing capture.

### 3.2 Other Polish / infrastructure seeds

| Source | What | Access | Verified |
|---|---|---|---|
| KNF public warning list `knf.gov.pl/dla_konsumenta/ostrzezenia_publiczne` | 669 entities (names of fake brokers/platforms) → keyword list for ad-library searches | HTML table, no API/export link found | LIVE (`200`, 669) |
| CSIRT KNF reports `cebrf.knf.gov.pl` | PDF write-ups with screenshots, advertiser names, domains (e.g. "Phishing Campaign Advertisers") | PDFs | READ (search hit) |
| CERT Polska articles (`cert.pl/en/posts/2024/12/Ad-fraud-on-large-online-platforms/`, `.../expectations-from-meta/`, `2025/03/evaluation-of-expectations-towards-meta/`) | scheme taxonomy, 139+ impersonated public figures, evasion tricks | HTML | READ |
| CERT Orange Polska (CyberTarcza) | says fake investments were ~68% of blocked domains in 2025; blog posts with deepfake cases | HTML | search snippet only |
| Demagog, Konkret24, Niebezpiecznik, Sekurak, xyz.pl "ScamWatch" | case studies with ad screenshots and page names | HTML | search snippets only |
| urlscan.io search API `https://urlscan.io/api/v1/search/?q=domain:<d>` | prior scans, screenshots, DOM, IPs, ASNs, redirect targets for a domain | search works unauthenticated (LIVE); submitting scans needs a free API key | LIVE — a domain listed by CERT at 10:41 UTC already had a public scan from 11:15 UTC, final page `google.com` (a cloaker bounce) |
| crt.sh `https://crt.sh/?q=<domain>&output=json` | certificate history, sibling hostnames, issuance time | no key; slow, sometimes 5xx | LIVE |
| OpenPhish / PhishTank / URLhaus / phishing.army | generic phishing feeds, little Polish scam-ad content | free | MEMORY |

### 3.3 Public datasets of scam ads

None found on Hugging Face, Kaggle, Zenodo or GitHub (two searches). The big studies did not publish data:

- KommAustria/RTR "Analysis of the online advertising fraud ecosystem on Meta platforms" (Dec 2025, 80 pp.) — **read this for methodology**: scheme-specific keyword tables, iterative keyword expansion in the Ad Library, API crawler, manual cleaning, HTML-similarity clustering of landing pages, shared mail-server pivot that exposed 300+ further sites.
- Gen Digital "The Scam Ad Machine" (14.5M EU/UK ads via Meta API; 30.99% pointed to scam infrastructure; 10 advertisers behind 56% of scam ads).
- AI Forensics (450M ads via the API since Aug 2023; 46k health-scam ads), Debunk.org (50k+ ads, 459 domains, Polish third most common language), Tech Transparency Project, CCDH, DFRLab (2023, altered images of a Polish politician).

Plan to build the evaluation set yourselves: CERT list + Ad Library keyword sweeps + a few hand-labelled campaigns from the Polish case studies above.

### 3.4 Apify and other paid routes

Dozens of Apify actors for Meta Ad Library ($0.25-$4 per 1,000 ads), Google ATC, TikTok library, Bing/Snap/Pinterest. They use the same GraphQL interception described in 1.1.2. Apify's free plan includes a small monthly credit (MEMORY: $5), enough for a few thousand Meta ads — a legitimate **fallback for the demo** if neither a Meta token nor a working browser scraper is ready. SerpApi also sells a Google ATC endpoint. Free equivalents: everything in sections 1.2, 1.4, 1.5 plus soxoj/AdsLibrary.

---

## 4. Cloaking

### 4.1 What the cloakers check

CERT Polska (READ): **User-Agent** (the same ad showed different pages on Linux and Windows), **Referer** (direct visit vs. coming from a Facebook link), **IP address** (ranges of NASK, KNF, Facebook, Google are blocked). Visitors failing the checks get a harmless "white page" (e.g. a business-coaching site). KommAustria (READ): people clicking through *from the Ad Library* also get the white page. Literature (READ via search: Spartacus CCS 2022, CloudSEK, a study of 2,421 kits): IP- and UA-based checks dominate, UA checks in ~82% of cases. Vendor blogs add TLS/JA3 fingerprints, headless-browser tells, request timing, one-time click tokens.

Typical gate, combining the above with MEMORY of Keitaro-style trackers:

1. Mobile UA, often specifically the Facebook/Instagram in-app WebView (`[FB_IAB/FB4A;FBAV/...]`, `Instagram ...`).
2. `Referer` from `facebook.com` / `l.facebook.com` / `m.facebook.com`.
3. `fbclid` (and the campaign's own `utm_*` / sub-ID parameters — the exact ad URL matters, a bare domain often bounces).
4. Polish residential or mobile IP; datacenter ASNs and known security ranges blocked.
5. `Accept-Language: pl`, Europe/Warsaw timezone, JS checks (`navigator.webdriver`, screen size, touch support).
6. First-visit-only or time-windowed serving.

### 4.2 LIVE mini-experiment (8 domains, curl only, 2 requests each)

Script: `.../scratchpad/research_a/cloak_test.sh`. Domains: 8 entries listed by CERT Polska today. Profile A: headless-Chrome UA, no referer. Profile B: Android WebView UA with `[FB_IAB/FB4A;...]`, `Referer: https://l.facebook.com/`, `Accept-Language: pl-PL`, `X-Requested-With: com.facebook.katana`, `?fbclid=...`.

| Domain | Profile A | Profile B | Reading |
|---|---|---|---|
| `indigo-corbel.shop` | 200, 384 KB, title "ostrzeżenie - B***a" | 200, 1.49 MB, title "Kuchnia，Frytkownica beztłuszczowa" | **Different page per profile** — server-side cloaking on UA/referer/fbclid |
| `alcheariet.store`, `tonegratif.store`, `immiscatal.store`, `speedcangi.store` | 200, 4,099 B | 200, 4,394 B | Identical Nuxt SPA shell on all four: same `/_nuxt/entry.DVIo1EG1.css`, same Sentry `public_key=4eacab01...` and release hash. Content decided client-side → needs a rendering browser. **Strong infrastructure link between four "independent" domains** |
| `imartykul2345232.sbs` | → `https://www.google.com/` | → `https://www.google.com/` | Bounce for both: needs the real campaign path/params or a different IP |
| `enterserig.store`, `dk-9431941.sbs` | no response | no response | Dead / not resolving |

So with nothing but headers: 1/8 uncloaked, 4/8 need JS, 1/8 needs more (path/IP), 2/8 gone. Small sample, illustrative only.

### 4.3 What researchers do, and tools

Legitimate approach = emulate an ordinary targeted visitor, capture several profiles, diff them. No CAPTCHA solving, no credential use.

1. **Multi-profile capture and diff.** Fetch each URL as (a) desktop headless, (b) Android FB in-app WebView with FB referer + `fbclid`, (c) iPhone Safari/Instagram. Store final URL, redirect chain, status, title, DOM hash, screenshot pHash. *A difference between profiles is itself a feature* ("cloaked = suspicious"), and the white page is a linkable artefact too (white-page templates are reused across campaigns).
2. **Use the exact click URL from the ad** (`snapshot.link_url` in the web payload, or the CTA link rendered at `ad_snapshot_url`), not the bare domain; append a plausible `fbclid`.
3. **Real browser with mobile emulation**: Playwright device descriptors (`playwright.devices["Pixel 7"]`) plus `user_agent` override, `locale="pl-PL"`, `timezone_id="Europe/Warsaw"`, `extra_http_headers`, `page.goto(url, referer="https://l.facebook.com/")`. Add patchright or camoufox if `navigator.webdriver` checks bite.
4. **Polish IP.** Run the capturer from a Polish residential/mobile line (a laptop tethered to a phone is the hackathon answer). Datacenter and institutional ranges are what the cloakers block.
5. **Capture fast and once** — within minutes of discovery; keep HAR + HTML + screenshot on first contact.
6. **Borrow third-party vantage points**: urlscan.io (unauthenticated search of existing scans — LIVE; submission API with custom UA/referer/country needs a free key), public Lookyloo instance at `lookyloo.circl.lu`.

Open-source tools:

| Tool | Use |
|---|---|
| **Lookyloo/PlaywrightCapture** (`pip install playwrightcapture`, last commit 2026-11-13) | One call → HAR, screenshot, cookies, final URL, rendered HTML. Source confirms `device_name` (Playwright device descriptors), `referer`, custom `headers`, UA, proxy, locale, timezone, geolocation settings. Best ready-made capture primitive |
| **Lookyloo** (2026-11-07) | Full web UI over the above with redirect-tree view; heavier (Redis/Valkey stack). Use the public instance for demos rather than self-hosting |
| Playwright / patchright-python | Roll your own 60-line capturer with three profiles — likely the simplest for the POC |
| camoufox | Firefox-based anti-detect; good against fingerprint checks, but cannot convincingly pose as an Android FB WebView |
| curl_cffi | Cheap first-pass differential fetch with browser TLS fingerprints (`impersonate="chrome_android"`) before spending a browser on a URL |
| urlscan.io API | Second opinion and history; `page.url`, IPs, ASN, screenshot, DOM hash for pivots |

Research prototypes (papers, no maintained code found): CrawlPhish (S&P 2021, client-side cloaking), Spartacus (CCS 2022), PhishParrot (2025, LLM-chosen crawl profiles).

Residual gaps to state honestly in the pitch: IP-reputation cloaking cannot be beaten from a datacenter; one-time links are burnt by the first capture; Messenger/WhatsApp funnels (`fb.me`, 58% of surviving ads in one KommAustria scheme) have no landing page at all.

---

## 5. Recommended acquisition stack for a CPU-only POC with a scheduler

| Layer | Choice | Why |
|---|---|---|
| Scheduler | APScheduler inside the Streamlit/Gradio process (or a sidecar `python -m scheduler`) with a SQLite job/state table | No infra, survives restarts |
| Seed 1 | CERT Polska `domains.json` delta, every 5-15 min | LIVE, free, PL-specific, hundreds of fresh domains/day |
| Seed 2 | Meta Ad Library: **API if the user supplies a token**; else Playwright on the web UI (first page per keyword, intercept GraphQL), hourly keyword sweep with `country=PL`, `active_status=all`; pivot by `page_id` for every hit | The core "ad library" requirement |
| Seed 3 | Microsoft Ad Library API keyword sweep (`countryCodes=151`), hourly | LIVE, no key, real destination URLs |
| Pivot | Google ATC: `SearchSuggestions` + `SearchCreatives` by domain/advertiser for every domain in the graph; `GetCreativeById` for PL impression bands | LIVE, no key; brings in YouTube/Display creatives |
| Optional | LinkedIn keyword sweep; TikTok library via Playwright; urlscan/crt.sh enrichment | Cheap extras |
| Landing capture | Playwright Chromium, 2-3 profiles (desktop / Android FB WebView + referer + fbclid / iPhone), HAR + HTML + screenshot; or PlaywrightCapture | Cloaking differential + SPA rendering |
| Media | yt-dlp (YouTube, FB ads/videos, TikTok, X) with `--write-info-json --write-auto-subs --sub-langs pl` | LIVE, one tool for all video |
| HTTP | `httpx`/`requests`, `curl_cffi` in reserve | TLS-fingerprint fallback |
| Store | SQLite or DuckDB + content-addressed files (`sha256/…`) | Dedup on ad id, creative hash, domain |
| User input → pipeline | URL → capture; screenshot → OCR → extract URL/brand → capture + keyword sweep; product name → keyword sweep across Meta/MS/LinkedIn + GATC suggestions; file → hash + same matchers | Matches the organisers' four input types |

Keyword list for sweeps: start from KNF warning-list names, CERT Polska scheme vocabulary (e.g. "platforma inwestycyjna", "dochód pasywny", "program rządowy", brand names such as Orlen/PGE/InPost/Baltic Pipe, names of frequently impersonated public figures) and expand iteratively from hits, as in the KommAustria method. Remember that celebrity-name text search can silently return nothing on Meta — pivot by page.

Linking signals that fall out of acquisition for free (hand-off to the linking team): Meta `page_id`, `beneficiary_payers` strings, `collation_id` (variants of one ad); GATC advertiser id ↔ domains; MS `AdvertiserId` ↔ `DestinationUrl`; landing-page build hashes, Sentry/analytics/pixel IDs, favicon hash; TLS cert issuance time and SAN siblings (crt.sh); IP/ASN (urlscan); CERT insert-time bursts and domain-name generator patterns; white-page template hash.

### Credentials the user would need to provide

| Credential | Needed for | Effort | Without it |
|---|---|---|---|
| **Meta user access token** (identity-confirmed FB account + dev app) | `ads_archive` API | Hours to days (ID check) | Browser scraping of the web UI, or Apify free credit |
| TikTok research client key/secret | Commercial Content API | Application review, open-ended | Playwright on library.tiktok.com, or skip |
| Google Cloud account | BigQuery `removed_creative_stats` | Minutes | Skip |
| urlscan.io API key (free) | Submitting scans | Minutes | Search-only |
| YouTube Data API key (free) | Bulk metadata | Minutes | yt-dlp only |
| Telegram `api_id`/`api_hash` + phone | Telethon | Minutes, personal account | Skip Telegram |
| X / Instagram accounts | twscrape / instaloader | Burner accounts, ban risk | Skip; per-URL yt-dlp/gallery-dl only |

### Gotchas

1. Meta web UI rejects plain HTTP clients with a 403 handshake; GraphQL `doc_id` rotates. Budget time for breakage, or get the token.
2. Scam ads live hours to days and ~60% are gone by the time you look. Store raw payload + media on first sight; never rely on re-fetching.
3. Media URLs on `fbcdn`, `tpc.googlesyndication.com`, `media.licdn.com`, `bing.com/th` are signed or ephemeral — download immediately.
4. Displayed domain ≠ destination on Meta; payer field is free text.
5. Google ATC cannot be searched by ad text and cannot be browsed by region alone.
6. CERT list has no labels and holds only six months in `domains.*` (use `actions_<year>.log` for history).
7. Cloaked landings need a Polish non-datacenter IP and the exact ad URL; a quarter to a half of fresh domains are JS-only shells.
8. Telethon's GitHub repo is archived (moved to Codeberg); facebook-scraper, snscrape and nitter are dead; yt-dlp marks several Instagram/TikTok listing extractors as broken.
9. Disk: one Playwright Chromium (~400 MB) is affordable; avoid camoufox + browsertrix + Firecrawl together on a machine with ~9 GB free.
10. DSA Transparency Database contains no content or URLs — statistics only.

---

## 6. Sources

Official docs / primary:
- Meta Graph API `ads_archive`: https://developers.facebook.com/docs/graph-api/reference/ads_archive/ and `archived-ad`: https://developers.facebook.com/docs/graph-api/reference/archived-ad/
- Meta Content Library access: https://developers.facebook.com/docs/content-library-and-api/get-access
- TikTok Commercial Content API: https://developers.tiktok.com/doc/commercial-content-api-query-ads , https://developers.tiktok.com/doc/commercial-content-api-query-commercial-content , https://developers.tiktok.com/doc/commercial-content-api-getting-started
- Microsoft Ad Library API: https://learn.microsoft.com/en-us/advertising/guides/ad-library-api?view=bingads-13
- DSA Transparency Database: https://transparency.dsa.ec.europa.eu/page/api-documentation , https://transparency.dsa.ec.europa.eu/page/research-api , https://transparency.dsa.ec.europa.eu/explore-data/download
- CERT Polska warning list: https://cert.pl/lista-ostrzezen/ , spec https://hole.cert.pl/schema/certpl_lista_ostrzezen_api_v2.pdf , tools https://github.com/CERT-Polska/warning-list-tools
- CERT Polska on ad fraud: https://cert.pl/en/posts/2024/12/Ad-fraud-on-large-online-platforms/
- KNF warning list: https://www.knf.gov.pl/dla_konsumenta/ostrzezenia_publiczne

Studies:
- KommAustria/RTR study (EN): https://www.rtr.at/medien/aktuelles/publikationen/Publikationen/Publikationen_2026/Betrugsoekosystem_Werbung_KommAustria_final_EN.pdf
- Gen Digital: https://www.gendigital.com/blog/insights/research/scam-ad-machine-meta
- AI Forensics health ads: https://www.aiforensics.org/work/meta-health-ads
- Tech Transparency Project: https://techtransparencyproject.org/articles/meta-awash-in-deepfake-scam-ads
- Debunk.org: https://www.debunk.org/over-50k-ads-on-social-media-impersonated-interpol-europol-and-eu-institutions-promising-fraud-r
- PoPETs 2026 "A Year Under the DSA": https://petsymposium.org/popets/2026/popets-2026-0059.php
- Mozilla "Full Disclosure": https://www.mozillafoundation.org/en/research/library/full-disclosure-stress-testing-tech-platforms-ad-repositories/
- Spartacus (CCS 2022): https://adamdoupe.com/publications/spartacus-ccs2022.pdf ; PhishParrot: https://arxiv.org/html/2508.02035

Open-source tools:
- https://github.com/soxoj/AdsLibrary (Meta web + Graph, Google, TikTok, LinkedIn, X, Snapchat; MCP server)
- https://github.com/facebookresearch/Ad-Library-API-Script-Repository
- https://github.com/faniAhmed/GoogleAdsTransparencyScraper
- https://github.com/yt-dlp/yt-dlp , https://github.com/mikf/gallery-dl , https://github.com/instaloader/instaloader , https://github.com/vladkens/twscrape , https://github.com/davidteather/TikTok-Api
- https://github.com/bellingcat/auto-archiver
- https://github.com/Lookyloo/PlaywrightCapture , https://github.com/Lookyloo/lookyloo
- https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python , https://github.com/daijro/camoufox , https://github.com/lexiforest/curl_cffi , https://github.com/unclecode/crawl4ai
- Secondary overviews: https://adlibrary.com/posts/eu-dsa-ad-repositories-developers
