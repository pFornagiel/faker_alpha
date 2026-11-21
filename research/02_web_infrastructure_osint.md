# 02 — Web & infrastructure OSINT layer for linking scam landing pages

Research date: 2026-11-21. Scope: page-level and infrastructure-level features that link scam sites
(fake investments, fake health products, fake giveaways, fake shops; mostly Polish) into campaigns,
with free/open-source tooling only.

Legend used throughout:

- **[LIVE]** — verified by me on 2026-11-21 with a real request from this machine (curl / Python, no credentials).
- **[SRC]** — verified by reading the project's source code or primary documentation today.
- **[READ]** — taken from a vendor/research write-up or search summary; not independently reproduced.
- **[MEM]** — from prior knowledge; not re-verified today. Treat as a hypothesis to check.

Test scripts and raw outputs: `/tmp/claude-1000/-home-pawel/c47d1afe-7feb-4ed9-b69b-483c2e110a3d/scratchpad/research_b/`
(`featx.py`, `fetch_chain.py`, `linkscore.py`, `rdap_batch.py` are runnable stdlib/requests-only POCs).

---

## 0. Executive summary

1. **A free, CPU-only pipeline is enough to link most campaigns.** Fetch (Playwright) → extract identifiers (regex) →
   RDAP + DNS + CT → store indicators in a bipartite graph `(:Page)-[:HAS]->(:Indicator)` → score pairs with a
   noisy-OR of rarity-weighted evidence. Every edge explanation is simply the list of shared indicators.
2. **Distinguish three link levels**, otherwise the graph collapses into one blob:
   - **Operator / account** (same person or team): tracker and pixel IDs, lead-form endpoint + affiliate ID, phone / Telegram / wallet, registration burst, dedicated IP, shared TLS key.
   - **Kit / platform** (same template or SaaS, possibly many operators): DOM structure hash, bundler asset names, Nuxt/Next build ID, Sentry key, favicon, cookie names.
   - **Ecosystem** (meaningless alone): registrar, TLD, Cloudflare IP/ASN, Let's Encrypt, same day.
3. **Live proof on today's CERT Polska warning list** (section 1): seven `.store` domains listed this morning were registered at NameCheap
   25–34 seconds apart, share one Cloudflare NS pair, serve the same Nuxt build and Sentry key, and carry *sequential* platform
   `domainId`s 86390–86396 in registration order. One free urlscan query on a bundler asset name expanded the 7 seeds to at least 80 domains on the
   same kit; registrar + NS pair then split those into at least two operator groups (NameCheap + `dalary/jermaine` for a full year across
   `.digital` → `.rest` → `.store`, versus Porkbun + `gordon/meera`).
4. **Cloaking is the main obstacle.** The bare domain of that cluster returns "Page not found" (`banReason: empty_redirect_hash`); the scam
   only renders with the full ad URL. The demo must keep the *complete* URL from the ad (path + query) and should fall back to infrastructure
   signals, which still work when the content is hidden.
5. **Things that changed and will bite**: urlscan result/DOM retrieval now needs an API key (search does not); URLhaus needs a key;
   crt.sh had no entries for certificates issued in the last ~36 h while CertSpotter did; the warning list keeps only 6 months
   (but yearly `actions_<year>.log` files keep the full history).

---

## 1. Verified live case study (2026-11-21)

Source: `https://hole.cert.pl/domains/v2/domains.json` fetched at ~11:29 UTC. All steps [LIVE].

| Step | Observation |
|---|---|
| Warning list | 126,633 entries (126,588 active), oldest 2026-05-21 (6-month retention). 453–2,743 new entries per day in 10–20 Nov. |
| Seeds | `scaraccet`, `tonegratif`, `abbrulbas`, `vegetgutta`, `pecomiencef`, `plenicompa`, `alcheariet` — all `.store`, listed 08:07–10:41 UTC today |
| RDAP (`rdap.radix.host`) | Registrar NameCheap (IANA 1068) for all 7. Created 2026-11-20 06:54:34, 06:55:08, 06:55:37, 06:56:04, 06:56:31, 06:56:57, 06:57:22 — gaps of 25–34 s |
| Nameservers | `dalary.ns.cloudflare.com` + `jermaine.ns.cloudflare.com` on all 7 |
| A records | Cloudflare anycast (188.114.96.x, 104.21.x, 172.67.x) — no linking value |
| CT (CertSpotter) | `*.plenicompa.store` + apex, Google Trust Services and Let's Encrypt, `not_before` 06:09–06:10 (backdated ~1 h, i.e. issued within about a minute of registration) |
| CT (crt.sh) | `[]` for these domains and for a 2-day-old `.shop`; older scam domains were present → ingestion lag at test time |
| HTTP GET `/` | 200, ~4 kB Nuxt SSR page whose only visible text is "Page not found" |
| Kit markers | Nuxt `buildId` `e78da08d-06d8-4e09-be1e-d10aedfe90eb`; `sentry-release` `f2ae3e35…`; `sentry-public_key` `4eacab01120b72013711163127628faa`; assets `/_nuxt/cJIUjg4r.js`, `/_nuxt/entry.DVIo1EG1.css`; cookie `surfer_uuid` — identical on all 7 |
| Platform IDs | Server-rendered state contains `domainId` 86390…86396, increasing in exactly the registration order (two more from the same burst, registered 06:53:34 and 06:54:05, have 86388 and 86389) |
| Not an operator ID | The state also contains `webmaster_id` 42 — but the same value appears on a domain of a different registrar/NS account (below), and the response is the fallback stream (`stream_uuid` all zeros). Treat it as a platform default until proven otherwise |
| Cloaking | State contains `banReason: "empty_redirect_hash"`. Same result with a mobile Facebook in-app UA + `Referer: l.facebook.com` + `fbclid`. This points to a required token/path from the ad; IP-based filtering of my address is not excluded |
| Privacy leak | The page echoes the visitor's IP, `X-Forwarded-For` and User-Agent into the HTML → the platform logs crawlers |
| DOM hash | Tag-sequence hash identical on all 14 fetches (7 domains × 2 profiles); text simhash distance 0 |
| Favicon | `/favicon.ico` is a 78-byte text file containing a `data:image/gif;base64…` string; Shodan-style mmh3 = `-318086011` |
| urlscan pivot, `filename:"cJIUjg4r.js"` | 145 scans in total; the 100 returned (anonymous requests are capped at 100 results even with `size=200`) cover **80 distinct apex domains** (76 `.store`, 2 `.digital`, 1 `.rest`, 1 `.com`), all AS13335, all scanned 20–21 Nov |
| Kit vs operator split | Four of the 80 fetched and RDAP-checked: `raccodocum.digital` and `eduonetumef.digital` (created 2025-12-01 06:48 and 07:00), `posamlegif.rest` (2026-02-11) — all NameCheap + `dalary/jermaine`, `domainId` 49396 / 49419 / 56530. `firm-mortar.com` (2025-11-18) — **Porkbun + `gordon/meera`**, `domainId` 65262, different name style. Same build ID and Sentry key on all four |
| urlscan pivot, `hash:<favicon sha256>` | 6,502 scans including unrelated sites (`hh.ru`, `salz.ch`, …) → this favicon is a generic placeholder and must be stop-listed |

Additional observations from the same list:

- The pattern "9–11 lowercase letters + `.store`" matches 3,363 entries: 167 in Aug, 984 in Sep, 1,078 in Oct, 1,098 so far in Nov.
  The first lines of `actions_2026.log` (1 Jan) show the same style of pseudo-words on `.world` (`phasetinti.world`, `pervacombi.world`).
  That the January `.world` names come from the same generator is my inference from name shape only; I did not fetch them.
- `truly4-aliquid41.cfd`, `truly6-voluptate5.cfd`, `truly5-ut60.cfd`: Dynadot, NS pair `dolly`+`kai`, created at 00:01:04, 02:01:03, 04:01:03 UTC —
  a two-hour cron. 254 `truly<N>-<latin word><N>.cfd` entries in the last 31 days.
- Marketplace phishing uses brand labels as subdomains (`allegro.`, `olx.`, `vinted.`, `allegrolokalnie.`, `alebilet.` on one registrable domain):
  3,909 of 23,538 entries in the last 31 days. These link trivially through the registrable domain.
- TLD mix of entries since 1 Oct: com 6,736; shop 5,593; sbs 4,015; store 2,694; net 2,001; cfd 1,861; top 1,292; info 1,149; cyou 944; pl 844.

Lessons for the design:

1. Registration-time clustering (registrar + NS set + creation gap) works with zero page content.
2. Bundler artefacts (hashed asset names, build IDs, Sentry keys) are excellent **kit** pivots and are searchable for free on urlscan.
3. Inside a shared kit, the operator is separated by account-level infrastructure (registrar + Cloudflare NS pair held for 12 months here) and by
   platform IDs leaked in SSR state. Sequential `domainId`s confirm one batch; a candidate affiliate field (`webmaster_id`) turned out to be
   identical across two different accounts, so every such ID needs a prevalence check before it is trusted.
4. Favicon hashes need a prevalence check before they count.
5. Never hash raw HTML: per-request UUIDs, trace IDs and the echoed client IP make every response unique. Hash structure, not bytes.

---

## 2. Fetching and redirect chains

### 2.1 What has to be captured

| Artefact | Why |
|---|---|
| Full input URL exactly as in the ad (path, query, fragment) | Cloakers key on campaign alias / token / `fbclid`; the bare domain is usually a decoy |
| Every hop: HTTP 30x, `<meta http-equiv=refresh>`, JS `location=`, form auto-submit, iframe swap | TDS / tracker domains in the middle of the chain are shared across many landing domains |
| Final URL, status, response headers, `Set-Cookie` names | Tracker fingerprints (Keitaro `_subid`, `_token`), kit cookies |
| Rendered DOM (after JS) and raw HTML | IDs injected by GTM only appear after rendering |
| All requested hosts and URLs (HAR) | Shared third-party endpoints: lead API, cloaker API, geo-IP services, CDN buckets |
| Response body SHA-256 per resource | Reused JS/CSS/images |
| Screenshot (full page + above the fold) | Visual/face layers (other agents) |
| `window` globals, localStorage keys | Kit fingerprints |

### 2.2 Redirect and cloaking mechanics to expect

- **Tracking link → cloaker → landing** [READ, CERT Polska 2024]: decisions use User-Agent, Referer and IP; ranges of NASK, KNF, Facebook and Google are blocked outright. CERT Polska's example: a Linux browser got a "business coaching" page, a Windows browser got the scam.
- **Keitaro** (self-hosted ad tracker abused as TDS + cloaker) [READ, Infoblox/Confiant 2026]: about 15,500 domains with malicious instances in Oct 2025–Jan 2026, investment scams the largest category. Filters on device, OS, geo, referrer, browser, URI parameters; fallback is a "white page". Integrations with third-party cloakers HideClick, Adspect, IMKLO. `KClient JS` swaps content with no visible redirect.
  - Indicators [READ, unverified by me]: cookies `_subid`, `_token`; paths `/click.php`, `/lander/<name>/`, `/click_api/v3`; queries `?_lp=1`, `?_update_tokens=1`; body strings `window.kclient`, `kclient.js?v=`, `imklo_loader`.
  - Attribution caveat [READ]: cracked Keitaro builds (7.x–9.x) circulate, so the same legacy cookie value appears on unrelated operations. A shared Keitaro cookie is a weak link.
- **Ruthless Rabbit** [READ, Infoblox 2025]: cloaking service at `mcraftdb[.]tech`; lead submit endpoint `…/api/v1/submit/<uuid>/`; campaign paths such as `/4YJ3LH?MPC_3=…`, `/lander/gazinvestgaz_4301/`; bare domain returns 404.
- **Reckless Rabbit** [READ]: wildcard DNS on registered domains; decoy site on the bare domain, scam on a deep path; ad caption shows a decoy domain different from the real link.
- **Geo-IP calls from the page** [READ]: `ipinfo.io`, `ipgeolocation.io`, `ipapi.co` requested client-side to pick language and prefill the phone prefix. Their API tokens, when present in the URL, are operator-level identifiers.
- **Ad-side evasion** [READ, CERT Polska]: Ad Library shows a different creative; new variants are indexed up to 24 h late; campaigns live about 21 h on average.

### 2.3 Capture stack options

| Tool | Role | Status (last commit) | Notes |
|---|---|---|---|
| `playwright` (Python) | Baseline capture: HAR, DOM, screenshot, cookies | 2026-11-20 [LIVE check of repo] | Chromium download ~150–300 MB [MEM]. Stock headless is detected by serious cloakers |
| `patchright-python` | Drop-in Playwright fork that removes CDP leaks | 2026-11-10 | Same API, lowest migration cost [READ] |
| `camoufox` | Patched Firefox, fingerprint spoofing at C++ level, Playwright API | 2026-11-19 | Strongest fingerprint realism in third-party benchmarks; separate browser download [READ] |
| `nodriver` | Drives real Chrome over CDP, no WebDriver | 2026-10-26 | Best against Cloudflare in a May 2026 benchmark; different API, AGPL per one source [READ] |
| `playwright-stealth` | JS init-script patches | Mattwmaster58 fork 2026-04-04; AtuboDad 2023-09 (stale) | Weakest option; proof-of-concept level [READ] |
| `SeleniumBase` (UC/CDP mode) | Alternative stealth driver | 2026-11-21 | Not evaluated |
| `curl_cffi` | TLS/JA3 impersonation for plain HTTP fetches | 2026-11-21 | Good for fast first-pass fetch without a browser |
| `Lookyloo` + `PlaywrightCapture` + `har2tree` | Complete open-source capture-and-pivot system (CIRCL) | 2026-11-07 / 11-13 / 11-21 | See 6.1 — closest existing system to what we are building |
| `lacus` (ail-project) | Standalone capture service used by Lookyloo | 2026-11-13 | |
| ProjectDiscovery `httpx` | Bulk HTTP probing | 2026-11-19 | Go ≥ 1.26 to build; did not install |
| ProjectDiscovery `katana` | Crawler (follows links, JS parsing) | 2026-11-19 | Useful to find lead-form pages below the landing |
| `subfinder`, `dnsx`, `tlsx`, `cdncheck`, `asnmap` | Passive subdomains, bulk DNS, TLS grab, CDN/ASN tagging | all 2026-11-16…19 | Go binaries |
| `gowitness` | Bulk screenshots | 2026-10-11 | |
| `FlareSolverr` | Solves Cloudflare challenges as a proxy | 2026-10-24 | Only for sites *behind* a challenge; not for cloakers |

Cloudflare note: scam sites use Cloudflare as a reverse proxy (hides origin IP) and sometimes its bot challenge. After takedown Cloudflare
serves a "Suspected Phishing" interstitial — PhishStats returned exactly that title for a `.pl` URL today [LIVE]. Detect it and mark the capture as `taken_down`, do not fingerprint it.

`httpx` one-liner [SRC: README flags; not run]:

```bash
httpx -l domains.txt -sc -title -server -td -favicon -jarm -hash sha256,simhash \
      -ip -cname -asn -cdn -tls-grab -location -fr -include-chain \
      -sr -srd out/ -j -o httpx.jsonl \
      -H 'User-Agent: Mozilla/5.0 (Linux; Android 14) ... Mobile Safari/537.36' -H 'Accept-Language: pl-PL'
```

Flags confirmed in the README: `-favicon` (mmh3 of `/favicon.ico`), `-jarm`, `-hash` (md5, mmh3, simhash, sha1, sha256, sha512), `-td`
(Wappalyzer dataset), `-asn`, `-cdn`, `-cname`, `-tls-grab`, `-csp-probe`, `-fr`, `-include-chain`, `-store-chain`, `-sr`, `-ss`, `-er`, `-j`.
PyPI's `httpx[cli]` installs a binary with the same name [MEM] — call the Go binary by full path.

### 2.4 HTTP-level chain + cloaking differential [LIVE — `fetch_chain.py`]

Runs three profiles (bot, desktop PL, Facebook in-app mobile) and flags a mismatch of final URL or DOM hash. Verified on `cert.pl` and on the case-study cluster.

```python
import re, hashlib, requests
from urllib.parse import urljoin
from html.parser import HTMLParser

PROFILES = {
  'bot':    {'User-Agent': 'python-requests/2.x'},
  'desk':   {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36',
             'Accept-Language': 'pl-PL,pl;q=0.9,en;q=0.5'},
  'fb_mob': {'User-Agent': 'Mozilla/5.0 (Linux; Android 14; SM-A546B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36 [FB_IAB/FB4A;FBAV/480.0.0.0;]',
             'Accept-Language': 'pl-PL,pl;q=0.9', 'Referer': 'https://l.facebook.com/'},
}
META = re.compile(r'<meta[^>]+http-equiv=["\']?refresh["\']?[^>]*content=["\']?\s*\d+\s*;\s*url=([^"\'>\s]+)', re.I)
JSR  = re.compile(r'''(?:window\.|document\.|top\.|self\.)?location(?:\.href)?\s*=\s*["']([^"']+)["']|location\.(?:replace|assign)\(\s*["']([^"']+)["']''', re.I)

class Tags(HTMLParser):
    def __init__(s): super().__init__(); s.t = []
    def handle_starttag(s, t, a): s.t.append(t)

def domhash(html):   # same definition as Lookyloo/har2tree "domhash"
    p = Tags(); p.feed(html)
    return hashlib.sha256('|'.join(p.t).encode()).hexdigest()[:32]

def chain(url, headers, max_hops=10):
    s, hops = requests.Session(), []
    for _ in range(max_hops):
        r = s.get(url, headers=headers, allow_redirects=False, timeout=15)
        hop = {'url': url, 'status': r.status_code, 'via': None, 'cookies': sorted(r.cookies.keys())}
        nxt = None
        if r.status_code in (301, 302, 303, 307, 308):
            nxt, hop['via'] = urljoin(url, r.headers.get('location', '')), 'http'
        else:
            body = r.text[:200000]
            if (m := META.search(body)):
                nxt, hop['via'] = urljoin(url, m.group(1).replace('&amp;', '&')), 'meta-refresh'
            elif len(body) < 3000 and (j := JSR.search(body)):      # tiny page that only redirects
                nxt, hop['via'] = urljoin(url, j.group(1) or j.group(2)), 'js-location'
        hops.append(hop)
        if not nxt or nxt == url:
            hop.update(final=True, size=len(r.content), domhash=domhash(r.text)); break
        url = nxt
    return hops
```

### 2.5 Browser capture [not run — Playwright is not installed here; API from memory]

```python
from playwright.sync_api import sync_playwright
import hashlib, json

def capture(url, out, mobile=True):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
        dev = p.devices['Pixel 7'] if mobile else {}
        ctx = browser.new_context(**dev, locale='pl-PL', timezone_id='Europe/Warsaw',
                                  record_har_path=f'{out}/capture.har', record_har_content='embed',
                                  service_workers='block', ignore_https_errors=True,
                                  extra_http_headers={'Accept-Language': 'pl-PL,pl;q=0.9'})
        page = ctx.new_page()
        navs, reqs, bodies = [], [], {}
        page.on('framenavigated', lambda f: navs.append(f.url) if f == page.main_frame else None)   # catches JS + meta hops
        page.on('request', lambda r: reqs.append({'url': r.url, 'method': r.method, 'type': r.resource_type,
                                                   'post': (r.post_data or '')[:2000]}))
        def on_resp(r):
            try: bodies[r.url] = hashlib.sha256(r.body()).hexdigest()
            except Exception: pass
        page.on('response', on_resp)
        resp = page.goto(url, referer='https://l.facebook.com/', wait_until='domcontentloaded', timeout=45000)
        try: page.wait_for_load_state('networkidle', timeout=15000)
        except Exception: pass
        http_chain, r = [], resp.request if resp else None
        while r: http_chain.insert(0, r.url); r = r.redirected_from       # HTTP 30x hops
        page.screenshot(path=f'{out}/full.png', full_page=True)
        result = {'input': url, 'final': page.url, 'http_chain': http_chain, 'nav_chain': navs, 'title': page.title(),
                  'cookies': ctx.cookies(), 'requests': reqs, 'body_sha256': bodies,
                  'globals': page.evaluate('''() => { const f = document.createElement('iframe'); document.body.appendChild(f);
                      const base = new Set(Object.keys(f.contentWindow)); f.remove();
                      return Object.keys(window).filter(k => !base.has(k)).slice(0, 300); }'''),
                  'local_storage': page.evaluate('Object.keys(localStorage)')}
        open(f'{out}/dom.html', 'w').write(page.content())
        json.dump(result, open(f'{out}/capture.json', 'w'), ensure_ascii=False)
        ctx.close(); browser.close()
        return result
```

Capture rules:

- Run at least two profiles (desktop datacentre vs mobile PL with Facebook referrer) and store both; a difference is itself a feature (`cloaked=true`).
- **Never submit forms.** Read `form[action]`, hidden inputs and the JS that builds the POST; do not send data.
- Block or sandbox downloads; run the browser in a container with no access to the internal network.
- Use a dedicated egress IP. A residential or mobile Polish exit is what reveals cloaked content; datacentre IPs often get the white page.
- Do not submit ad URLs containing one-time tokens to public scanners with `visibility=public`; that burns the token and tips off the operator. Use `unlisted`.

---

## 3. Domain intelligence

### 3.1 RDAP / WHOIS

- **Bootstrap**: `https://data.iana.org/rdap/dns.json` maps TLD → RDAP base URL [LIVE]. Examples seen: `.pl` → `https://rdap.dns.pl/`,
  `.store/.online/.site` → `rdap.radix.host`, `.xyz/.cfd/.sbs/.icu` → `rdap.centralnic.com`, `.shop` → `rdap.gmoregistry.net`,
  `.top` → `rdap.zdnsgtld.com`, `.com` → `rdap.verisign.com`, `.cc` → `tld-rdap.verisign.com`. `https://rdap.org/domain/<d>` redirects to the right server [LIVE].
- **Fields that survive GDPR redaction** [LIVE]: registrar name + IANA ID, `registration` / `expiration` / `last changed` events (second precision), nameservers, EPP status (`add period` = inside the 5-day grace window → brand new). Registrant is redacted for gTLDs.
- **.pl specifics** [LIVE]: NASK runs both RDAP (`https://rdap.dns.pl/domain/<name>`, conformance `nask0`) and WHOIS (`whois -h whois.dns.pl <name>`).
  Both show registrar, creation / last-modified dates and nameservers with a delay of up to 15 minutes. WHOIS adds `registrant type: organization|individual`;
  data of individuals is not shown. For a 4-hour-old `.pl` phishing domain RDAP returned registrar `nazwa.pl sp. z o.o.`, creation time and an empty NS list.
- `https://www.dns.pl/deleted_domains.txt` — daily list of deleted `.pl` names [LIVE, 44 kB]. I found no public feed of newly registered `.pl` names.
- Python libraries: `whodap` (RDAP, last commit 2026-10-01), `python-whois` (richardpenman, 2026-10-26). The 30-line stdlib client in `rdap_batch.py` was sufficient.

```python
import json, urllib.request
BOOT = json.load(urllib.request.urlopen('https://data.iana.org/rdap/dns.json', timeout=30))
TLD = {t: u[0] for ts, u in BOOT['services'] for t in ts}

def rdap(registrable_domain):
    base = TLD[registrable_domain.rsplit('.', 1)[-1]]
    req = urllib.request.Request(base.rstrip('/') + '/domain/' + registrable_domain,
                                 headers={'Accept': 'application/rdap+json'})
    j = json.load(urllib.request.urlopen(req, timeout=25))
    out = {e['eventAction']: e['eventDate'][:19] for e in j.get('events', [])}
    out['ns'] = sorted(n['ldhName'].lower() for n in j.get('nameservers', []))
    out['status'] = j.get('status')
    for ent in j.get('entities', []):
        if 'registrar' in ent.get('roles', []):
            out['registrar'] = [v[3] for v in ent.get('vcardArray', [None, []])[1] if v[0] == 'fn'][:1]
            out['registrar_iana'] = [p['identifier'] for p in ent.get('publicIds', [])]
    return out
```

Use `tldextract` (or the Public Suffix List) to get the registrable domain; `frisco-pl.eu.cc` and `*.pages.dev` on today's list show why naive "last two labels" fails.

**Registration-burst feature** (strongest infrastructure-only signal, see section 1): key = `(registrar IANA ID, sorted NS set, TLD)`, then single-linkage
on creation time with a gap ≤ 120 s (tight) or ≤ 10 min (loose). Add a name-shape signature (`L10`, `truly D - L D`, `word-word`) as a secondary key.

### 3.2 DNS

- `dnspython` (2026-11-11) or `dig`: A, AAAA, NS, MX, TXT, CNAME, SOA.
- Useful values: NS set; SOA `rname` and serial on non-CDN DNS; MX host; TXT verification tokens (`google-site-verification=`, `facebook-domain-verification=`, `yandex-verification:`) — these are account-bound and therefore operator-level; SPF `include:` targets; CNAME targets (`*.pages.dev`, `*.vercel.app`, SaaS shop hosts).
- Wildcard test: resolve a random label. Reckless Rabbit domains answer for any subdomain [READ].
- **Cloudflare NS pair**: Cloudflare assigns one pair of named nameservers per account, so domains added to one account share the pair [READ]. Lookyloo indexes this as a pivot (`index_cloudflare_ns_capture`, key = the two names sorted and joined) [SRC]. The pool of pairs is small relative to the number of Cloudflare accounts, so one pair is shared by many unrelated accounts: weak alone, strong together with registrar + creation window (7 of 7 in the case study).

### 3.3 IP → ASN / hosting

| Source | Endpoint | Key | Status |
|---|---|---|---|
| Team Cymru | `dig +short TXT 4.3.2.1.origin.asn.cymru.com` then `dig +short TXT AS<n>.asn.cymru.com` | none | [LIVE] |
| RIPEstat | `https://stat.ripe.net/data/prefix-overview/data.json?resource=<ip>`; also `network-info`, `whois`, `reverse-dns-ip` | none | [LIVE] |
| ipinfo | `https://ipinfo.io/<ip>/json` | works without token (limited) | [LIVE] |
| Shodan InternetDB | `https://internetdb.shodan.io/<ip>` (ports, hostnames, tags) | none | [LIVE] endpoint answers; no data for my test IP |
| `cdncheck` (ProjectDiscovery) | local lists of CDN/WAF ranges | none | not run |

Always tag an IP as `cdn` / `shared-hosting` / `dedicated` before using it. Cloudflare (AS13335) addresses carry no linking information.
Dedicated IPs on small "bulletproof-ish" hosts are valuable: Infoblox reports Ruthless Rabbit on two dedicated IPs hosting 2,600+ domains and names Aeza (AS210644) and u1host (AS213877) in Keitaro abuse [READ].

### 3.4 Reverse IP, passive DNS

| Source | Endpoint | Free tier | Status |
|---|---|---|---|
| HackerTarget | `https://api.hackertarget.com/reverseiplookup/?q=<ip>` | small daily quota without key [MEM] | [LIVE] endpoint answers |
| Mnemonic PDNS | `https://api.mnemonic.no/pdns/v3/<domain-or-ip>?limit=N` | public, no key | [LIVE]; no records for a 2-day-old domain |
| AlienVault OTX | `https://otx.alienvault.com/api/v1/indicators/domain/<d>/{general,passive_dns,url_list,whois}` | no key for reads | [LIVE] |
| urlscan search | `page.ip:"<ip>"`, `ip:"<ip>"` | no key | [LIVE] (same API as other pivots) |
| CIRCL Passive DNS, Validin, SecurityTrails, Silent Push community | — | registration required | [MEM], not tested |

Passive DNS coverage of domains that live for one day is poor. Our own resolution history (re-resolve every few hours) is more reliable.

### 3.5 Certificate transparency

| Source | Endpoint | Notes |
|---|---|---|
| crt.sh | `https://crt.sh/?q=<domain>&output=json` (`%25.` prefix for subdomains; `&exclude=expired`) | [LIVE] 2–8 s per query. Returned `[]` for certificates issued 1–2 days earlier; fine for domains older than a few weeks. Also a public Postgres at `crt.sh:5432` user `guest` db `certwatch` [MEM] |
| CertSpotter | `https://api.certspotter.com/v1/issuances?domain=<d>&include_subdomains=true&expand=dns_names&expand=issuer` | [LIVE] no key; `x-ratelimit-limit: 10` (window not stated in the response). Had the fresh certificates crt.sh lacked. Returns `pubkey_sha256` |
| `certstream-server-go` | self-hosted WebSocket firehose of CT logs (`/`, `/full-stream`, `/domains-only`) | [SRC] last commit 2026-09-13; ~40 MB RAM, ~15 Mbit/s, 250–300 certs/s; client must ping every 60 s. README does not say whether static-CT (Sunlight) logs are supported |
| Calidog `certstream` | `wss://certstream.calidog.io` | Host answers over HTTPS [LIVE]; stream not tested; `certstream-python` last commit 2021; reported outages [READ]. Do not depend on it |

- Let's Encrypt moved to static-CT logs and announced end-of-life of its RFC 6962 logs for early 2026 [READ]; any CT monitor that only speaks RFC 6962 misses those certificates. This is a plausible cause of the crt.sh gap, not a confirmed one.
- Certificate `not_before` is backdated about one hour by Let's Encrypt and Google Trust Services (observed: `not_before` 06:09 for a domain created 06:56). Allow an hour of tolerance when aligning certificate times with RDAP creation times.
- Linking value: Cloudflare/Let's Encrypt single-domain certificates link nothing. A multi-SAN certificate on a non-CDN host, or the same `pubkey_sha256` across certificates, is a strong link.
- CT is the standard discovery feed in the literature: CryptoScamTracker (NDSS 2023) and Crimson (WWW 2025, ~6 billion names → 43,572 crypto-investment scam sites in 8 months of 2024) both start from CT logs [READ].

### 3.6 Lookalike generation

- `dnstwist` (last commit 2025-04, stable): `dnstwist --registered --format json --lsh tlsh --phash <brand>.pl` — permutations, resolution, fuzzy HTML hash and screenshot pHash against the original [MEM for flags].
- `openSquat` (2026-10-27) — newly-registered-domain squatting detection.
- Relevance here is limited: today's list is dominated by random/RDGA names, not typosquats. Brand keywords appear as *subdomain labels* (`allegro.<random>.shop`) and inside long names (`pl-oqloszenie…`, `frisco-pl.eu.cc`). A keyword/regex pass over hostnames is cheaper and more useful than permutation generation.

---

## 4. Page fingerprints for campaign linking

### 4.1 Identifier extraction [LIVE — `featx.py`, stdlib only]

Run on both raw HTML and rendered DOM, and on the bodies of first-party JS files.

```python
TRACKERS = {
 'ga_ua':      r'\bUA-\d{4,10}-\d{1,4}\b',
 'ga4':        r'\bG-[A-Z0-9]{8,12}\b',
 'gtm':        r'\bGTM-[A-Z0-9]{4,9}\b',
 'gads':       r'\bAW-\d{9,12}\b',
 'adsense':    r'\b(?:ca-)?pub-\d{16}\b',
 'fb_pixel':   r'''fbq\(\s*['"]init['"]\s*,\s*['"](\d{14,17})['"]|facebook\.com/tr\?id=(\d{14,17})''',
 'tiktok_px':  r'''ttq\.load\(\s*['"]([A-Z0-9]{18,22})['"]''',
 'ym':         r'''ym\(\s*(\d{7,9})\s*,\s*['"]init|mc\.yandex\.ru/watch/(\d{7,9})''',
 'hotjar':     r'hjid\s*[:=]\s*(\d{5,8})',
 'clarity':    r'clarity\.ms/tag/([a-z0-9]{8,12})',
 'sentry_key': r'sentry[-_]public[-_]key=([0-9a-f]{32})|https://([0-9a-f]{32})@[a-z0-9.-]*sentry',
 'sentry_rel': r'sentry-release=([0-9a-f]{7,40})',
 'nuxt_build': r'buildId:"([0-9a-f-]{8,40})"',
 'next_build': r'"buildId":"([A-Za-z0-9_-]{8,40})"',
 'recaptcha':  r'\b6L[0-9A-Za-z_-]{38}\b',
 'telegram':   r'(?:t\.me|telegram\.me)/(\+?[A-Za-z0-9_]{5,32})',
 'whatsapp':   r'(?:wa\.me|api\.whatsapp\.com/send\?phone=)/?(\d{8,15})',
 'email':      r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,10}',
 'phone_pl':   r'(?<!\d)(?:\+48|0048)[ -]?\d{3}[ -]?\d{3}[ -]?\d{3}(?!\d)',
 'btc':        r'\b(?:bc1[ac-hj-np-z02-9]{25,60}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b',
 'eth':        r'\b0x[a-fA-F0-9]{40}\b',
 'tron':       r'\bT[1-9A-HJ-NP-Za-km-z]{33}\b',
 'keitaro':    r'_subid|KTRACKING|/click\.php\?|_lp=1|kclient',
}
```

Only `sentry_key`, `sentry_rel` and `nuxt_build` were exercised against live scam pages today (the cluster has no ad pixels on its decoy page);
the other patterns follow the vendors' documented ID formats and need validation on the hackathon dataset. Lookyloo's own extractor is
`(?:G-|AW-|GA-|UA-|GTM-)\w{9,15}` plus captcha `data-sitekey` for reCAPTCHA / hCaptcha / Turnstile [SRC].

Validation steps that prevent false links:

- Validate wallets by checksum (Base58Check / bech32 / EIP-55) — the BTC and TRON regexes match random strings.
- Drop e-mail matches on asset names (`logo@2x.png`) and on library authors in comments.
- **Cloned-page trap**: fake news pages are often HTTrack-style copies of Onet / TVP / WP articles and keep the original site's GTM/GA IDs. If an ID also occurs on the legitimate brand's domain, stop-list it.

### 4.2 Structure, content and asset hashes

| Fingerprint | Definition | Robustness |
|---|---|---|
| `domhash` | `sha256("\|".join(tag names in rendered DOM))[:32]` (join character is a pipe) — the definition used by Lookyloo/har2tree, previously named `certpl_html_structure_hash` in Lookyloo's index [SRC] | Exact-match only; survives text and attribute changes; breaks on one extra `<div>` |
| Tag-shingle MinHash | 4-gram shingles of the tag sequence → Jaccard, or MinHash + LSH via `datasketch` (2026-10-10) | Tolerates local edits; threshold ~0.8 |
| CSS class-set Jaccard | Set of class names | Good for Tailwind/Bootstrap kits; fails on obfuscated class names |
| Tag-count vector | Vector of tag counts with proportional distance (Cui et al., WWW 2017) | Simple baseline with published results on phishing |
| Text simhash | 64-bit simhash over 3-word shingles of visible text; Hamming ≤ 6 = near-duplicate | Catches reused article text with a swapped celebrity name |
| TLSH / ssdeep of HTML | `py-tlsh` (2026-07) | Sensitive to per-request tokens; hash after stripping scripts and attributes |
| Resource SHA-256 | Per response body from HAR | First-party JS/CSS/images only; third-party libraries are noise |
| Bundler asset names | `/_nuxt/cJIUjg4r.js`, `main.3f2a1c.js`, `/_next/static/<buildId>/` | Content-hashed names are effectively file hashes and are searchable in urlscan (`filename:`) without a key [LIVE] |
| JS API-usage profile | Set of browser APIs called by page scripts (arXiv 2509.13186, 97 % kit-family accuracy on 548 families) [READ] | More stable across kit variants than DOM shape; needs instrumentation |
| HHHash | Hash of the ordered list of response header *names* (`adulau/HHHash`; implemented in har2tree) [SRC] | Identifies server stack; meaningless behind Cloudflare |
| JARM / JA4X | Active TLS fingerprint of the server | Only for origin servers (trackers on a VPS); CDN-fronted sites all look alike |

Favicon hash [LIVE]: Shodan's `http.favicon.hash` is MurmurHash3 x86-32 (signed) of the base64 encoding **with a newline every 76 characters**:

```python
import base64, mmh3            # pip install mmh3  (pure-python fallback in featx.py, self-test passes)
def favicon_hash(raw: bytes) -> int:
    return mmh3.hash(base64.encodebytes(raw))
```

Collect the icon from `<link rel~=icon>` first, then `/favicon.ico`. Also store SHA-256 (urlscan `hash:` pivot) and MD5 (Cloudflare URL Scanner's `page.favicon.hash` [READ]).
Keep a stop-list of generic icons: empty file, 1×1 GIF, the 78-byte data-URI text seen today, default WordPress / Nuxt / Vite / React icons.

### 4.3 Lead forms and endpoints (highest-value page feature)

Collect without submitting anything:

- `form[action]`, method, ordered list of input `name`s, hidden input names **and values**.
- Endpoints in JS: `fetch(`, `axios.post(`, `$.ajax(`, `XMLHttpRequest.open(` arguments; captured XHR URLs in the HAR.
- Third-party hosts contacted before any user action (geo-IP lookups, cloaker APIs).

What to key on:

| Pattern | Level | Source |
|---|---|---|
| Endpoint with embedded UUID / token, e.g. `…/api/v1/submit/<uuid>/` | Operator | Infoblox Ruthless Rabbit [READ] |
| Trackbox-style lead fields `ai`, `ci`, `gi` (partner-assigned affiliate/campaign/group IDs), `so` (funnel name), `sub`, `MPC_1…MPC_12` (`MPC_3` usually the click ID) | Values of `ai`/`gi` = operator; presence of the schema = platform | Trackbox partner docs via search summary [READ]; matches the `MPC_3` and `so` parameters Infoblox reports |
| Hidden affiliate fields `sub1…sub5`, `subid`, `clickid`, `aff_id`, `offer_id`, `flow`, `pid`, `utm_*` | Values = operator/affiliate; name set = affiliate-network kit | [MEM] — COD "nutra" networks; validate on the dataset |
| Same order/lead API host across unrelated landing domains | Operator or affiliate network (check prevalence) | — |
| Form field name set + JS validation helper names (e.g. `generateRandomEmail()`) | Kit | Infoblox [READ] |

For COD health-product pages the funnel is ad → advertorial pre-lander → landing → order form [READ, Reset Tech]. The pre-lander and the order page are often on different domains; store the link between them as a `REDIRECTS_TO` / `LINKS_TO` edge.

### 4.4 Other markers

- **URL schema**: sorted set of query keys of the ad URL and of outbound links; path templates (`/lander/<slug>_<digits>/`); campaign aliases (Keitaro: 6–8 mixed-case characters as the first path segment).
- **HTML comments and language residue**: Cyrillic comments, `<!-- Yandex.Metrika counter -->`, `lang="ru"` on a Polish page, HTTrack signatures (`<!-- Mirrored from … by HTTrack`), leftover offer names from other countries. ESET links Nomani to Russian-speaking operators partly through Cyrillic comments and Yandex tools [READ].
- **Framework IDs**: Nuxt `buildId`, Next.js `buildId` / `/_next/static/<id>/`, WordPress theme and plugin paths (`/wp-content/themes/<name>/`), `<meta name=generator>`.
- **Cookie and storage names**: custom names (`surfer_uuid`) are kit markers; `_subid`, `_token` mark Keitaro. urlscan indexes `content.cookieNames`, `content.globalNames`, `content.storageNames`, `content.inputNames` but searching them is paid [LIVE: 403 on free].
- **Technology detection**: Wappalyzer went closed-source in 2023 [MEM]; maintained fingerprint sets: `enthec/webappanalyzer` (2026-11-21), `projectdiscovery/wappalyzergo` (2026-11-16), `rverton/webanalyze` (2026-09), Python `s0md3v/wappalyzer-next` (2026-09), `ShielderSec/webtech` (2026-06). Technology is ecosystem-level evidence, useful mostly as a filter.
- **Outbound link targets**: the "official site" button target is frequently the shared offer domain.
- **Images**: SHA-256 for exact reuse, pHash for resized/re-encoded reuse (other agents own this layer); image *URLs* on shared buckets (`*.r2.dev`, `*.b-cdn.net`, S3) are an infrastructure link.

---

## 5. Threat-intel, reputation and historical sources (free tiers)

| Source | What it gives | Access tested today | Limits / caveats |
|---|---|---|---|
| **CERT Polska warning list** | Ground-truth malicious domains for Poland | [LIVE] `https://hole.cert.pl/domains/v2/domains.{json,txt,xml}`, `domains_hosts.txt`, `domains_adblock.txt`, `domains_rpz.db`, `domains_mikrotik.rsc` | JSON fields `RegisterPositionId`, `DomainAddress`, `InsertDate`, `DeleteDate` (null = active). 22.5 MB JSON / 2.6 MB TXT. A listed name covers its subdomains [SRC spec]. Only the last 6 months [SRC spec; confirmed, oldest entry 2026-05-21]. No category label — investment scams, marketplace phishing and fake shops are mixed |
| Warning list history | Every block/unblock action per year | [LIVE] `https://hole.cert.pl/domains/v2/actions_<year>.log` (NDJSON: `RegisterPositionId`, `DomainAddress`, `ActionTime`, `ActionType`) for 2020–2026; 2025 = 33.8 MB, 2026 = 31.5 MB | Full history beyond the 6-month window; ideal training/evaluation corpus for registration-pattern clustering |
| Warning list push | Callback on add/remove | `hole-api.cert.pl` [READ]; example repo `CERT-Polska/phishing-api` last commit 2020 | Not tested |
| **urlscan.io search** | Historical scans, pivots on `domain`, `ip`, `asn`, `hash`, `filename`, `page.title`, `page.domain`, `task.tags` | [LIVE] no key: 30/min, 100/h, 500/day per IP (from `/api/v1/quotas`) | No regex or leading wildcards without an account [LIVE]. `dom.hash`, `text.*`, `content.*`, `links.*`, verdicts, brand fields are paid [LIVE 403]. Structure-similar search is Pro [READ] |
| urlscan result / DOM | Full scan JSON, DOM snapshot | [LIVE] **403 "You're not logged in"** without a key | Free account key required. Screenshot `https://urlscan.io/screenshots/<uuid>.png` worked without a key [LIVE] |
| urlscan submit | Third-party vantage-point capture | Not tested (needs key). Anonymous quota table lists `public` 2,500/day, `unlisted` 500/day, `private` 25/day | urlscan itself is often cloaked (its screenshot of the case-study domain showed only "Page not found") |
| Cloudflare Radar URL Scanner | Scans + search on `page.domStructHash`, favicon hash, ASN, IP | [READ] `GET /accounts/{id}/urlscanner/v2/search?q=` with an API token | Free Cloudflare account; not tested. The only free service found that exposes a DOM-structure-hash search |
| CertSpotter / crt.sh | Certificates per domain | [LIVE] see 3.5 | crt.sh lag on fresh certs |
| Wayback CDX | Archived snapshots, content digests | [LIVE] `https://web.archive.org/cdx/search/cdx?url=<d>*&output=json&collapse=digest&fl=timestamp,original,statuscode,digest` | Empty for the scam domain tested — short-lived domains are rarely archived. Useful for the *legitimate* pages being cloned |
| Common Crawl index | Monthly crawl lookups | [LIVE] `collinfo.json` OK (latest `CC-MAIN-2026-43`); index query returned 504 | Monthly cadence → low value for one-day domains |
| AlienVault OTX | Pulses, passive DNS, URL list | [LIVE] no key for reads | No pulses for the fresh domain tested |
| Mnemonic PDNS | Passive DNS | [LIVE] no key | Sparse for fresh domains |
| PhishStats | Recent phishing URLs with IP/ASN/title | [LIVE] `https://api.phishstats.info/api/phishing?_where=(tld,eq,pl)&_sort=-date&_size=N` | Quality varies |
| OpenPhish community | ~300 live phishing URLs | [LIVE] `openphish.com/feed.txt` now 302 → `raw.githubusercontent.com/openphish/public_feed/refs/heads/main/feed.txt` | Credential phishing, few scams |
| PhishTank | Verified phishing URLs dump | [LIVE] `https://data.phishtank.com/data/online-valid.json.gz` (2.3 MB) with a descriptive User-Agent | Credential phishing; rate-limited without an app key [MEM] |
| phishing.army | Blocklist aggregate | [LIVE] 3.2 MB | Domain list only |
| URLhaus (abuse.ch) | Malware distribution URLs | [LIVE] API → 401 without `Auth-Key`; old `/downloads/csv_recent/` → 410 Gone | Free key from auth.abuse.ch required since mid-2025 [READ]. Malware-focused; low relevance for ad scams |
| VirusTotal public API | Engine verdicts, relations | Not tested (key) | 4 req/min, 500/day on the public tier [MEM]; non-commercial terms |
| Google Safe Browsing | Verdict | Not tested (key) | Free key; verdict only, no pivoting |
| Shodan / Censys / SecurityTrails / Validin | Host search, favicon search, historical DNS/WHOIS | Not tested | Free tiers are small and change often; treat as optional manual enrichment |
| Community scam lists | Crypto-drainer and scam domains | Repos alive: `MetaMask/eth-phishing-detect` (2026-11-21), `scamsniffer/scam-database` (2026-11-21), `PhishDestroy/destroylist` (2026-11-21), `Phishing-Database/Phishing.Database` (2026-10), `JPCERTCC/phishurl-list` (2026-10) | Label source only |
| Team Cymru, RIPEstat, ipinfo, InternetDB | IP context | [LIVE] see 3.3 | — |

Free urlscan pivots that worked today without a key:

```bash
# kit pivot by content-hashed asset name -> at least 80 apex domains from 7 seeds (100 results returned of 145)
curl -s 'https://urlscan.io/api/v1/search/?q=filename:%22cJIUjg4r.js%22&size=100'
# exact resource reuse (favicon, logo, JS) by SHA-256
curl -s 'https://urlscan.io/api/v1/search/?q=hash:<sha256>&size=100'
# everything urlscan saw for a set of domains
curl -s 'https://urlscan.io/api/v1/search/?q=page.domain:(a.store%20OR%20b.store)&size=100'
# quotas for the current identity
curl -s https://urlscan.io/api/v1/quotas
```

Search results already include `page.ip`, `page.asn`, `page.title`, `page.server`, `page.tlsIssuer`, `page.tlsValidFrom`, `page.domainAgeDays`,
`page.redirected`, `task.url` vs `page.url` — enough to build edges without retrieving full results. Use `total` from a pivot query as an
**external prevalence** estimate for an indicator (6,502 hits → generic; 145 hits on 80 fresh `.store` domains → specific).

---

## 6. Existing open-source frameworks and research

### 6.1 Frameworks (maintenance checked today via last commit on the default branch)

| Project | What it does | Last commit | Verdict |
|---|---|---|---|
| **Lookyloo** (CIRCL) + `har2tree` + `PlaywrightCapture` + `lacus` | Playwright capture → request tree → Redis/Valkey indexes and cross-capture pivots. Indexes present in `lookyloo/indexing.py` [SRC]: cookie names, body hashes, HHHash, IPs, URLs, hostnames, TLDs, domains, favicons, `domhash`, identifiers (Google tag IDs, captcha site keys), categories, Cloudflare NS pairs | 2026-11-07 / 2026-11-21 | **Maintained. Best reference design.** The DOM hash was indexed under the name `certpl_html_structure_hash` before being renamed `domhash`, which suggests CERT Polska's involvement with this toolchain. Heavy to deploy for a hackathon; reuse `har2tree`/`PlaywrightCapture` as libraries or copy the hash definitions |
| phish.report **IOK** | Sigma-style rules over `title`, `hostname`, `html`, `dom`, `js`, `css`, `cookies`, `headers`, `requests`; 215+ rules; ODbL | 2025-04 | Slowing down. Good *format* for our own kit signatures; rules target credential-phishing kits |
| **Phishpedia** / **PhishIntention** | Logo detection + brand matching (and credential-page intent) from screenshots | 2025-07 / 2026-06 | Research code, Detectron2-era dependencies, GPU preferred. Brand-impersonation detection, not campaign linking |
| `miteru` (ninoseki) | Finds exposed phishing-kit zips on phishing hosts | 2026-06 | Maintained; credential-phishing oriented |
| `kitphishr` | Hunts phishing-kit source archives | 2026-09 | Maintained; same caveat |
| StalkPhish | Phishing-kit stalker | 2024-03 | Stale |
| `neonprimetime/PhishingKitTracker` | Kit e-mail/exfil tracker | 2022-01 | Dead |
| SpiderFoot (OSS) | 200+ OSINT modules, correlation rules | 2023-11 | Stale open-source edition; too broad for the POC |
| `mihari` (ninoseki) | Query aggregator across urlscan / Shodan / Censys / VT / crt.sh with rule files | 2026-10 | Maintained; handy for scheduled pivots |
| AIL framework | Leak/crawl analysis with correlation engine | 2026-11-19 | Maintained; heavy |
| `web-check` (Lissy93) | All-in-one site OSINT dashboard (DNS, TLS, headers, redirects, tech) | 2026-11-13 | Good checklist of per-site checks |
| `phishing_catcher` (x0rz) | Certstream keyword scoring | 2020-12 | Dead; idea still valid on a self-hosted certstream |
| `dnstwist` / `openSquat` | Lookalike generation / new-domain squatting | 2025-04 / 2026-10 | Usable |
| CERT Polska `Artemis`, `n6` | Vulnerability scanner; incident data exchange | 2026-11-20 / 2026-06 | Not about scam linking; `n6` is the national sharing platform |
| Maltego CE, OpenCTI | Graph pivoting GUI; CTI knowledge base with connectors (urlscan, VT, crt.sh, …) | not checked | Maltego CE is rate-limited and manual. OpenCTI is too heavy for a weekend; its STIX relationship model is a useful vocabulary |
| `AnalyticsRelationships` | GA-ID → related domains via third-party lookups | 2022-03 | Dead; the idea is reproducible with our own index |

### 6.2 Research worth citing in the pitch

| Work | Relevant finding |
|---|---|
| Starov et al., "Betrayed by Your Dashboard" (WWW 2018) | Analytics IDs extracted from 145K malicious URLs (9,395 unique IDs) led to 11K additional live domains — direct support for tracker-ID linking [READ] |
| Akamai (2019), phishing via analytics networks | 874 phishing domains carried analytics IDs, ~396 Google Analytics [READ] |
| Cui et al., "Tracking Phishing Attacks Over Time" (WWW 2017) | Tag-count vectors + proportional distance cluster phishing pages; most attacks are re-deployments [READ] |
| Bijmans et al., "Catching Phishers By Their Bait" (USENIX Security 2021) | Fingerprints from collected kits matched against live domains (Dutch landscape) [READ] |
| "Characterizing Phishing Pages by JavaScript Capabilities" (arXiv 2509.13186) | Browser-API usage clusters kits with 97 % accuracy on 548 families; DOM clustering scored far lower for kit identification [READ] |
| Infoblox, Reckless/Ruthless Rabbit (2025) | RDGA naming, wildcard DNS, dedicated IPs, lead-API UUID, `MPC_3` parameter as clustering keys for investment scams targeting Eastern Europe [READ] |
| Infoblox + Confiant, Keitaro series (2026) | ~15,500 domains; cookie-based clustering and its collision problem; registration bursts aligned with registrar promotions [READ] |
| CERT Polska, "Ad fraud on large online platforms" (Dec 2024) | Cloaking on UA / Referer / IP; 32,000 fake-investment domains blocked in 2023; 139+ impersonated public figures [READ] |
| Muzammil et al., "The Poorest Man in Babylon" (WWW 2025); Li et al., "Double and Nothing" (NDSS 2023) | CT-log-driven discovery pipelines for investment / giveaway scams [READ; second title MEM] |
| Vadrevu & Perdisci (IMC 2019); Oest et al., "Sunrise to Sunset" (USENIX Security 2020); Zhang et al., "CrawlPhish" (S&P 2021) | Screenshot-hash campaign clustering; ~21 h campaign lifetime; client-side cloaking taxonomy [MEM] |
| DomainTools / Silent Push pivoting guides | NS pair + registrar + time window as the standard "guided pivot" [READ] |

---

## 7. Link strength: weights and rules

### 7.1 Principles

1. **Weight = P(same operator | this value is shared and rare).** Base weights below are expert priors; calibrate them on the dataset.
2. **Rarity discount.** Multiply the base weight by a factor that decays with the number of distinct registrable domains carrying the value
   (inside our corpus, optionally also urlscan `total`). A value on 2 sites keeps its full weight; a value on a large share of the corpus tends to zero.
3. **One vote per evidence family.** Build ID, asset names and Sentry key all come from the same build; count the strongest one, not all three.
   Families: tracker IDs · contact handles · lead endpoint/affiliate · registration · hosting · TLS · kit code · kit structure · text · visual.
4. **Noisy-OR across families**: `score = 1 − Π(1 − wᵢ)`.
5. **Weak evidence cannot create an edge alone**: cap the score at 0.40 when every item is ecosystem-level.
6. **Typed edges**: `SAME_OPERATOR` needs at least one operator-level item and score ≥ 0.8; otherwise `SAME_KIT`. Campaign = connected component over
   `SAME_OPERATOR` edges (plus `SAME_KIT` edges that co-occur with matching theme/celebrity from the content layers).
7. **Stop-lists**: generic favicons, library file hashes (jQuery, Bootstrap, intl-tel-input), IDs of impersonated legitimate sites, CDN IPs, parking pages, takedown interstitials.

### 7.2 Proposed weights

| # | Signal | Base weight | Level | Justification / failure mode |
|---|---|---|---|---|
| 1 | Same lead-form POST endpoint incl. embedded campaign/affiliate UUID or token | 0.95 | Operator | The endpoint is where the money is made; operators do not share CRM credentials. Fails when the endpoint is a public affiliate-network API without an ID → check prevalence |
| 2 | Same crypto wallet (checksum-validated) | 0.95 | Operator | Funds control. Exchange deposit addresses can be shared — rare in practice |
| 3 | Same Facebook / TikTok pixel ID | 0.90 | Operator | Bound to the ad account that optimises the campaign. Fails on cloned pages that keep a foreign pixel |
| 4 | Same GA4 / GTM / UA / Yandex Metrika / Clarity / Hotjar ID | 0.90 | Operator | Supported by Starov et al. Fails on copies of legitimate sites (stop-list brand IDs) and on kit vendors who leave their own counter in the template (then prevalence is high → discounted) |
| 5 | Same phone / WhatsApp / Telegram handle / contact e-mail | 0.90 | Operator | Call-centre contact points are scarce resources |
| 6 | Same affiliate / webmaster / sub-ID **value** (`ai`+`gi`, `sub1`, platform affiliate field) on the same platform | 0.85 | Operator | Identifies the affiliate inside a shared kit. Key as `(platform fingerprint, id)` and check prevalence first: in the case study `webmaster_id` 42 was a platform-wide default, shared by two different accounts |
| 7 | Same TLS public key, or same multi-SAN certificate on a non-CDN host | 0.90 | Operator | Key reuse means the same server or deployment tooling |
| 8 | Registration burst: same registrar + same NS set + creation ≤ 10 min apart (≤ 120 s → 0.85) | 0.80 | Operator | Verified live: 7/7 domains, 25–34 s gaps. Fails at large registrars during promotions if the NS set is a registrar default → require a non-default or account-level NS set |
| 9 | Same final offer / "broker" domain or same intermediate TDS domain in the redirect chain | 0.80 | Operator | Shared funnel exit. If the domain is an affiliate network's shared tracker → 0.4 |
| 10 | Same captcha site key (reCAPTCHA / hCaptcha / Turnstile) or domain-verification TXT token | 0.80 | Operator | Account-bound. Site keys are sometimes copied with the kit → discount by prevalence |
| 11 | Same dedicated IP (non-CDN, ≤ ~50 domains on the IP), overlapping in time | 0.70 | Operator | Fails on cheap shared hosting; tag hosting type first |
| 12 | Same Nuxt / Next build ID, or same Sentry DSN key | 0.70 | Kit | Same build artefact = same platform deployment. Multi-tenant platforms serve many affiliates from one build |
| 13 | Same SHA-256 of a first-party JS/CSS file; same content-hashed asset filename | 0.60 / 0.55 | Kit | Verified pivot (80 domains). Exclude third-party libraries |
| 14 | Same `domhash` (exact DOM tag sequence), page ≥ 30 tags | 0.50 | Kit | Templates are sold and shared. For tiny pages (error stubs) use 0.2 |
| 15 | Tag-shingle Jaccard ≥ 0.8 or class-set Jaccard ≥ 0.8 | 0.45 | Kit | Near-duplicate template |
| 16 | Text simhash Hamming ≤ 6 of 64 (≥ 150 words) | 0.50 | Kit / content | Reused article; celebrity or product name swapped |
| 17 | Same non-generic favicon hash | 0.50 | Kit | Verified failure mode: generic icon matched 6,502 unrelated scans → prevalence check is mandatory |
| 18 | Same ordered set of form input names / hidden input names | 0.40 | Kit | Affiliate-network or CRM template |
| 19 | Same set of custom cookie / localStorage / global names | 0.35 | Kit | `surfer_uuid` style markers |
| 20 | Same URL parameter schema or path template | 0.30 | Kit | `MPC_3`, `/lander/<slug>_<n>/`; tracker conventions |
| 21 | Same exact `<title>` (non-generic) | 0.30 | Kit / content | |
| 22 | Same Cloudflare NS pair (alone) | 0.25 | Ecosystem | Account-level but pairs are shared by many accounts. With same registrar and same day → 0.60 |
| 23 | Same legacy Keitaro cookie value | 0.30 | Ecosystem | Cracked licences cause collisions (Infoblox) |
| 24 | Same small hosting ASN (non-CDN) | 0.15 | Ecosystem | Scam-friendly hosts concentrate many actors |
| 25 | Same HHHash / JARM on a non-CDN server | 0.15 | Ecosystem | Server stack |
| 26 | Same registrar | 0.05 | Ecosystem | Dynadot, NameCheap, PDR, Sav dominate abuse generally |
| 27 | Same creation day | 0.05 | Ecosystem | Hundreds to thousands of listed domains per day |
| 28 | Same TLD | 0.03 | Ecosystem | |
| 29 | Same Cloudflare / CDN IP, same CA, same tracker *vendor*, same framework | 0.00 | — | Never use |

Composite rules (evaluate before the generic scoring; they encode dependence between signals):

- `registrar ∧ NS set ∧ Δcreated ≤ 120 s` → 0.85; `… ≤ 10 min` → 0.80; `registrar ∧ CF NS pair ∧ same day` → 0.60; add 0.05 when the name-shape signature matches.
- `registrar ∧ CF NS pair ∧ same kit fingerprint` (any dates) → 0.75. This is what ties the December 2025 `.digital` domains to the November 2026 `.store` burst in the case study, and what separates `firm-mortar.com` from both.
- `same registrable domain` → 1.0 (`allegro.x.shop` / `olx.x.shop`).
- `same platform fingerprint ∧ consecutive platform IDs (|Δ| ≤ 10)` → 0.90 (verified pattern); with a matching, non-default affiliate ID → 0.95.
- `page A redirects or links to page B` → directed `LEADS_TO` edge, weight 0.9 for campaign membership.
- Temporal sanity: indicators must overlap in time (default ±30 days) or the weight is halved; an IP reused a year later means nothing.

### 7.3 Scoring implementation [LIVE — `linkscore.py`]

```python
import math, itertools, collections

W = {  # (base weight, level)  O=operator, K=kit, E=ecosystem
 'form_endpoint': (0.95,'O'), 'wallet': (0.95,'O'), 'fb_pixel': (0.90,'O'), 'ga4': (0.90,'O'), 'gtm': (0.90,'O'),
 'ym': (0.90,'O'), 'tiktok_px': (0.90,'O'), 'phone': (0.90,'O'), 'telegram': (0.90,'O'), 'email': (0.90,'O'),
 'affiliate_id': (0.85,'O'), 'cert_pubkey': (0.90,'O'), 'final_offer_domain': (0.80,'O'), 'captcha_sitekey': (0.80,'O'),
 'reg_burst': (0.80,'O'), 'dedicated_ip': (0.70,'O'),
 'sentry_key': (0.70,'K'), 'build_id': (0.70,'K'), 'asset_sha256': (0.60,'K'), 'asset_name': (0.55,'K'),
 'domhash': (0.50,'K'), 'favicon': (0.50,'K'), 'text_simhash': (0.50,'K'), 'hidden_inputs': (0.40,'K'),
 'cookie_names': (0.35,'K'), 'url_param_schema': (0.30,'K'), 'title': (0.30,'K'), 'cf_ns_pair': (0.25,'E'),
 'hhhash': (0.15,'E'), 'asn_small': (0.15,'E'), 'registrar': (0.05,'E'), 'created_day': (0.05,'E'), 'tld': (0.03,'E'),
}
STOP = {('favicon', '-318086011'), ('favicon', '0'), ('title', ''), ('title', '404 Not Found')}
CAP_WEAK_ONLY = 0.40

def rarity(df, n_docs):
    if df <= 2: return 1.0
    return max(0.0, 1.0 - math.log(df / 2) / math.log(max(n_docs, 4) / 2))

def build_edges(docs, threshold=0.5):
    """docs: {doc_id: {indicator_type: set(values)}} -> explained edges."""
    posting = collections.defaultdict(set)
    for d, feats in docs.items():
        for t, vals in feats.items():
            for v in vals:
                if (t, str(v)) not in STOP: posting[(t, v)].add(d)
    pair_ev = collections.defaultdict(list)
    for (t, v), ds in posting.items():
        if len(ds) < 2 or t not in W: continue
        w, lvl = W[t]; r = rarity(len(ds), len(docs))
        if w * r < 0.01: continue
        for a, b in itertools.combinations(sorted(ds), 2):
            pair_ev[(a, b)].append({'type': t, 'value': v, 'level': lvl, 'w': round(w * r, 3), 'df': len(ds)})
    edges = []
    for (a, b), ev in pair_ev.items():
        best = {}
        for e in ev:                                   # strongest item per type (extend to per-family)
            if e['type'] not in best or e['w'] > best[e['type']]['w']: best[e['type']] = e
        ev = sorted(best.values(), key=lambda e: -e['w'])
        score = 1 - math.prod(1 - e['w'] for e in ev)  # noisy-OR
        if all(e['level'] == 'E' for e in ev): score = min(score, CAP_WEAK_ONLY)
        rel = ('SAME_OPERATOR' if any(e['level'] == 'O' for e in ev) and score >= 0.8
               else 'SAME_KIT' if any(e['level'] in 'OK' for e in ev) else 'WEAK')
        if score >= threshold:
            why = '; '.join(f"{e['type']}={e['value']} (w={e['w']}, seen on {e['df']} sites)" for e in ev[:6])
            edges.append({'a': a, 'b': b, 'score': round(score, 3), 'rel': rel, 'explanation': why, 'evidence': ev})
    return sorted(edges, key=lambda e: -e['score'])
```

Output on features measured today (toy corpus of 7 documents, so the rarity discount on kit markers is harsh):

```
alcheariet.store <-> plenicompa.store 0.965 SAME_OPERATOR
    reg_burst=1068|dalary-jermaine|2026-11-20T06:5x (w=0.8, seen on 2 sites); sentry_key=4eacab01… (w=0.313, seen on 4 sites);
    build_id=e78da08d-… (w=0.313, seen on 4 sites); asset_name=entry.DVIo1EG1.css (w=0.246, …); domhash=… (w=0.223, …);
    cf_ns_pair=dalary-jermaine (w=0.169, seen on 3 sites)
alcheariet.store <-> raccodocum.digital 0.813 SAME_KIT
    sentry_key, build_id, asset_name, domhash, cf_ns_pair=dalary-jermaine (w=0.169), cookie_names=surfer_uuid (w=0.156)
alcheariet.store <-> firm-mortar.com 0.767 SAME_KIT
    sentry_key, build_id, asset_name, domhash, cookie_names=surfer_uuid          (no NS-pair or registrar evidence)
truly5-ut60.cfd <-> truly6-voluptate5.cfd 0.332 WEAK
    cf_ns_pair=dolly-kai (w=0.25, seen on 2 sites); created_day=2026-11-21 (w=0.05); registrar=472 (w=0.034, seen on 3 sites); tld=cfd (w=0.03)
```

Reading the output:

- The burst pair is `SAME_OPERATOR`; the year-old `.digital` domain and the Porkbun domain are only `SAME_KIT` under generic scoring.
  The composite rule `registrar ∧ CF NS pair ∧ same kit` promotes the `.digital` domain to the operator cluster and leaves `firm-mortar.com` out — the intended result.
- The `truly*.cfd` pair stays below threshold under generic scoring although it is an obvious cron-registered family. The composite rule
  `registrar ∧ CF NS pair ∧ same day` (0.60) plus the name-shape bonus is what catches it.

Scaling note: pairwise expansion of a posting list is quadratic. For indicators with more than ~200 documents do not materialise pairs; keep the
indicator node and let the UI show "shares X with 3,000 other sites".

### 7.4 Graph model (Neo4j)

```cypher
// bipartite evidence layer: explanations come for free
MERGE (p:Page {url: $final_url}) SET p.input_url = $input_url, p.captured_at = $ts, p.cloaked = $cloaked
MERGE (d:Domain {name: $registrable_domain})
MERGE (p)-[:ON_DOMAIN]->(d)
MERGE (i:Indicator {type: $type, value: $value})
MERGE (p)-[:HAS {source: $source, first_seen: $ts}]->(i);

// redirect chain
MERGE (a:Url {url: $hop_n})-[:REDIRECTS_TO {via: $via, order: $n}]->(b:Url {url: $hop_n1});

// prevalence for rarity weighting and super-node control
MATCH (i:Indicator)<-[:HAS]-(:Page)-[:ON_DOMAIN]->(d:Domain)
WITH i, count(DISTINCT d) AS df SET i.df = df;

// candidate pairs with their shared evidence (then score in Python and write LINKED edges)
MATCH (a:Page)-[:HAS]->(i:Indicator)<-[:HAS]-(b:Page)
WHERE elementId(a) < elementId(b) AND i.df <= 200
RETURN a.url, b.url, collect({type: i.type, value: i.value, df: i.df}) AS evidence;

// materialised explained edge
MATCH (a:Page {url: $a}), (b:Page {url: $b})
MERGE (a)-[l:LINKED]->(b) SET l.score = $score, l.rel = $rel, l.explanation = $why, l.evidence = $evidence_json;
```

Campaign assignment: connected components or Louvain/Leiden on `LINKED` edges with `score ≥ 0.8` (NetworkX is enough for a POC; Neo4j GDS if available).

---

## 8. Feature catalog

Cost column: all "free" unless noted. "Strength" is for *sharing the same value*.

| Feature | How to extract (lib / endpoint) | Cost | Strength | Notes |
|---|---|---|---|---|
| Full redirect chain (HTTP/meta/JS) | `requests` loop (`fetch_chain.py`) + Playwright `framenavigated`, `request.redirected_from` | free | Strong (shared intermediate or final domain) | Keep the full ad URL; record `via` |
| Cloaking differential | Same URL with bot / desktop-PL / FB-mobile profiles; compare final URL + `domhash` | free | n/a (page property) | Property `cloaked`; rerun later from another IP |
| Final offer / broker domain | Last hop + CTA link targets | free | Strong | Affiliate-network trackers → medium |
| TDS / tracker signature (Keitaro etc.) | Cookie names `_subid`, `_token`; `/click.php`, `_lp=1`, `kclient` in body | free | Weak (tool-level) | Legacy cookie value: weak-medium, collisions |
| GA4 / UA / GTM / Google Ads ID | Regex on HTML + rendered DOM + first-party JS | free | Strong | Stop-list IDs of cloned legitimate sites |
| Facebook / TikTok pixel ID | Regex `fbq('init',…)`, `facebook.com/tr?id=`, `ttq.load(…)`; HAR requests | free | Strong | Requires rendering when loaded through GTM |
| Yandex Metrika / Clarity / Hotjar ID | Regex | free | Strong | Yandex on a Polish page is itself a regional hint |
| Captcha site key | `data-sitekey` on `.g-recaptcha`, `.h-captcha`, `.cf-turnstile` | free | Strong-medium | Same extractor as Lookyloo |
| Domain-verification TXT tokens | `dig TXT` (`google-site-verification`, `facebook-domain-verification`) | free | Strong | Rare on throwaway domains |
| Lead-form endpoint | `form[action]`; `fetch/axios/$.ajax` URLs in JS; XHR in HAR | free | Strong | Never submit the form |
| Affiliate / campaign IDs | Hidden input values; `ai/ci/gi/so/MPC_n`, `sub1..5`; SSR state (`__NUXT_DATA__`, `__NEXT_DATA__`) | free | Strong (with platform key, after prevalence check) | Key as `(platform, id)`; platform defaults look like IDs |
| Sequential platform IDs | Numeric IDs in SSR state (`domainId`) compared across pages of one kit | free | Strong for consecutive values | Verified: 86388–86396 follow registration order |
| Form field-name set | Ordered input names, hidden names | free | Medium (kit) | |
| Phone / WhatsApp / Telegram / e-mail | Regex + `tel:`, `mailto:`, `wa.me`, `t.me` links; normalise to E.164 | free | Strong | Filter library/author e-mails |
| Crypto wallets | Regex + checksum validation | free | Strong | Mostly giveaway scams |
| `domhash` (DOM tag sequence) | SHA-256 of tag names joined with a pipe, first 32 hex chars on rendered DOM | free | Medium (kit) | Lookyloo-compatible |
| Tag-shingle MinHash / class-set Jaccard | `datasketch.MinHash` + LSH | free | Medium (kit) | Threshold ≈ 0.8 |
| Text simhash | 64-bit simhash of 3-word shingles | free | Medium | Min 150 words |
| First-party JS/CSS SHA-256 | HAR response bodies | free | Medium (kit) | Exclude CDN libraries; urlscan `hash:` to expand |
| Content-hashed asset names | `script[src]`, `link[href]` basenames | free | Medium (kit) | urlscan `filename:"…"` to expand (no key) |
| Framework build ID | `buildId` in Nuxt/Next bootstrap; `/_next/static/<id>/` | free | Medium (kit) | |
| Sentry DSN / release | `sentry-public_key`, `sentry-release` in `<meta name=baggage>` or JS | free | Medium (kit/developer) | |
| Favicon hash | mmh3 of `base64.encodebytes(raw)`; also SHA-256, MD5 | free | Medium | Mandatory prevalence check |
| Cookie / storage / global names | `Set-Cookie`, `context.cookies()`, `Object.keys(localStorage)` | free | Medium-weak | Custom names only |
| URL parameter schema / path template | `urllib.parse`; regex templates | free | Medium-weak | |
| HTML comments, language residue | Parser comments; `lang` attr; Cyrillic detection | free | Weak-medium | Good explanation text |
| CMS theme / plugin / generator | `/wp-content/themes/<x>/`, `<meta generator>`; webappanalyzer fingerprints | free | Weak | |
| Screenshot pHash / logo / face | Other agents | free | Medium | Cross-modal link to ads |
| Registrable domain | `tldextract` | free | Certain | Subdomain families |
| Registrar, creation time, NS, status | RDAP via IANA bootstrap; `.pl`: `rdap.dns.pl` / `whois.dns.pl` | free | Weak alone | Inputs to the burst rule |
| Registration burst | Group by registrar + NS set; time gap ≤ 120 s / 10 min | free | Strong | Verified live |
| Name-shape / RDGA signature | Regex classes, length, dictionary/n-gram model | free | Weak-medium | Boosts burst rule |
| Cloudflare NS pair | NS records ending `.ns.cloudflare.com`, sorted pair | free | Weak alone, medium with registrar + day | Lookyloo indexes it |
| A/AAAA + hosting type | `dnspython`; Team Cymru / RIPEstat; `cdncheck` | free | Dedicated IP: medium-strong; CDN: none | Tag before use |
| Reverse IP co-hosting | HackerTarget, urlscan `page.ip:`, Mnemonic PDNS | free, small quotas | Medium on dedicated IPs | |
| MX / SPF / SOA rname | `dig` | free | Weak-medium | Mostly absent on scam domains |
| Wildcard DNS | Resolve random label | free | Weak (behavioural) | |
| TLS certificate SANs, pubkey | CertSpotter (`pubkey_sha256`), crt.sh, direct `ssl` handshake | free | Strong when shared key / multi-SAN off-CDN | CDN certs: none |
| JARM / JA4X / HHHash | `httpx -jarm`, `tlsx`, FoxIO `ja4`, har2tree `make_hhhash` | free | Weak | Non-CDN only |
| Domain age vs first ad | RDAP creation vs capture time | free | n/a (risk feature) | `add period` status = < 5 days |
| Warning-list membership + listing time | `hole.cert.pl/domains/v2/domains.json`, `actions_<year>.log` | free | n/a (label); same-minute listing = weak hint | Ground truth |
| urlscan history | Search API (no key); results need free key | free | Source of the above | 500 searches/day anonymous |
| Wayback / Common Crawl | CDX API | free | — | Rarely covers scam domains |
| VT / GSB / OTX / PhishTank verdicts | Respective APIs | free keys | n/a (reputation) | Not linking features |

---

## 9. Recommended minimal pipeline (CPU-only Python POC)

```
input (URL | screenshot→OCR'd URL | product name→search | file)
  │
  ├─ 1 normalise: keep full URL; tldextract → registrable domain
  ├─ 2 fetch_chain (requests / curl_cffi) × 3 profiles → hops, cloaked?
  ├─ 3 browser capture (Playwright or patchright; camoufox if cloaked) → DOM, HAR, screenshot, cookies
  ├─ 4 featx: IDs, forms, assets, domhash, shingles, simhash, favicon hash
  ├─ 5 infra: RDAP (IANA bootstrap), dig NS/A/MX/TXT, Cymru ASN, CertSpotter (crt.sh fallback)
  ├─ 6 enrich: hole.cert.pl membership (local copy, refresh ≤ hourly), urlscan search pivots on rare indicators
  ├─ 7 upsert (:Page)-[:HAS]->(:Indicator); recompute df
  └─ 8 score pairs (linkscore) → LINKED edges with explanation → components = campaigns
```

Dependencies (all small): `requests`, `tldextract`, `dnspython`, `mmh3`, `beautifulsoup4` + `lxml` (or `selectolax`), `datasketch`,
`playwright` (+ Chromium), `neo4j` driver, `networkx`. Optional: `patchright`, `camoufox`, `curl_cffi`, `whodap`, `py-tlsh`.

Seeding the demo graph cheaply: take the last N days of the warning list → RDAP + NS for each registrable domain (about 1 request each,
several different registries so rate limits spread) → burst clusters appear immediately, before any page is fetched. Then capture one or two
pages per cluster for kit/operator indicators and expand with urlscan `filename:` / `hash:` searches.

---

## 10. Gotchas

- **Bare domains lie.** Scam content sits behind a path/token; the root is a decoy or 404. A page captured from a hostname-only feed (warning list, CT) often yields only kit markers.
- **Cloakers fingerprint the visitor**: UA, Referer, IP range and ASN, geo, device, `navigator.webdriver`, client hints. Datacentre and security-vendor ranges are pre-blocked. Expect to need a Polish residential/mobile exit for full content; plan the demo so it still works on infrastructure signals alone.
- **Our crawler is visible.** The case-study platform echoes visitor IP and headers into the page and sets a tracking cookie; repeated visits from one IP may get that IP banned (`banReason` field exists).
- **Dynamic HTML.** Per-request UUIDs, trace IDs and CSRF tokens make raw-body hashes useless; normalise or hash structure.
- **Cloudflare everywhere.** IP, ASN, JARM, HHHash, certificate issuer are uninformative for CF-fronted sites. NS pair and account-bound page IDs remain.
- **Takedown pages** ("Suspected Phishing | Cloudflare", registrar parking, hosting suspension) cluster perfectly with each other — detect and exclude.
- **Generic values**: placeholder favicons, default titles, jQuery hashes, shared pixel IDs of cloned sites. Always check prevalence before linking.
- **Kit ≠ operator.** Templates, cloaker services and multi-tenant teaser platforms are shared; only account-bound IDs separate operators.
- **Keitaro cookies collide** because of cracked licences.
- **urlscan**: search without key is fine (30/min, 100/h, 500/day per IP) but returned at most 100 results per request; paginate with `search_after` [MEM]; result JSON and DOM need a free API key; regex needs an account; the useful `content.*` and `dom.hash` fields are paid. Its own scans are frequently cloaked.
- **crt.sh**: slow (2–8 s), sometimes times out, and was missing day-old certificates today. Use CertSpotter for fresh domains; anonymous limit header says 10.
- **CT timestamps** are backdated ~1 h; RDAP `.pl` data lags up to 15 min; fresh `.pl` domains may show no NS yet.
- **RDAP differences per registry**: event names (`registration`, `last changed`, `expiration`) are consistent, entity layout is not; registrar IANA ID is missing for `.pl`. Rate limits are per registry and undocumented — cache aggressively.
- **Warning list** keeps 6 months, has no category labels, and lists hostnames (8,896 of the last 23,538 entries have ≥ 3 labels); a listed name implies its subdomains.
- **URLhaus / PhishTank / OpenPhish** are about malware and credential phishing; coverage of ad-driven investment and health scams is thin. The CERT Polska list is the relevant feed.
- **Wayback / Common Crawl** almost never contain one-day domains.
- **Ethics and safety**: no form submissions, no credential entry, no interaction with call-centre contacts; open captured HTML only as data; do not publish victim-facing one-time URLs to public scanners.
- **GitHub API** unauthenticated limit was already exhausted on this network; repository freshness above was read from `commits.atom` feeds instead.

---

## 11. Sources

Primary / verified today:

- CERT Polska warning list: https://hole.cert.pl/domains/v2/domains.json · spec https://cert.pl/uploads/2023/08/hole-v2-rfc/certpl_lista_ostrzezen_api_v2_rfc.pdf · https://cert.pl/en/warning-list/
- NASK .pl RDAP / WHOIS: https://rdap.dns.pl/ · https://dns.pl/en/RDAP_in_NASK · https://www.dns.pl/deleted_domains.txt
- IANA RDAP bootstrap: https://data.iana.org/rdap/dns.json
- urlscan API: https://urlscan.io/docs/search/ · https://docs.urlscan.io/pages/api-rate-limits · https://urlscan.io/api/v1/quotas
- Lookyloo source: https://github.com/Lookyloo/lookyloo (`lookyloo/indexing.py`) · https://github.com/Lookyloo/har2tree (`har2tree/nodes.py`, `helper.py`) · https://www.lookyloo.eu/docs/main/index.html
- ProjectDiscovery httpx: https://github.com/projectdiscovery/httpx
- certstream-server-go: https://github.com/d-Rickyy-b/certstream-server-go
- IOK: https://github.com/phish-report/IOK
- CertSpotter API: https://api.certspotter.com/v1/issuances · crt.sh: https://crt.sh/
- RIPEstat: https://stat.ripe.net/docs/data_api · Team Cymru IP-to-ASN DNS · https://ipinfo.io · https://internetdb.shodan.io
- Feeds: https://github.com/openphish/public_feed · https://data.phishtank.com/ · https://phishing.army/ · https://api.phishstats.info/ · https://otx.alienvault.com/ · https://api.mnemonic.no/pdns/v3/

Read (not reproduced):

- CERT Polska, Ad fraud on large online platforms (2024-12): https://cert.pl/en/posts/2024/12/Ad-fraud-on-large-online-platforms/
- Infoblox, Reckless Rabbit / Ruthless Rabbit: https://www.infoblox.com/blog/threat-intelligence/uncovering-actor-ttp-patterns-and-the-role-of-dns-in-investment-scams/
- Infoblox + Confiant, Keitaro: https://www.infoblox.com/blog/threat-intelligence/patterns-pirates-and-provider-action-what-we-learned-working-with-keitaro/
- Malwarebytes summary (15,500 domains): https://www.malwarebytes.com/blog/news/2026/05/massive-ai-investment-scam-network-spans-15500-domains
- PhishDestroy Keitaro checker (advocacy site, indicator strings only): https://phishdestroy.github.io/ScamIntelLogs/keitaro/checker.html
- Starov et al., WWW 2018: https://securitee.org/files/malanalytics_www2018.pdf
- Muzammil et al., WWW 2025: https://securitee.org/files/crimson_www2025.pdf
- JS-capability kit clustering: https://arxiv.org/html/2509.13186v1
- Cui et al., WWW 2017 (tag vectors): https://www.site.uottawa.ca/~bochmann/Curriculum/Pub/2017%20-%20Tracking%20phishing%20attacks%20over%20time.pdf
- Let's Encrypt RFC 6962 log end-of-life: https://letsencrypt.org/2025/08/14/rfc-6962-logs-eol.html
- Cloudflare URL Scanner: https://developers.cloudflare.com/radar/investigate/url-scanner/
- ESET Nomani coverage: https://www.welivesecurity.com/en/scams/investors-beware-ai-powered-financial-scams-swamp-social-media/ · https://thehackernews.com/2025/12/nomani-investment-scam-surges-62-using.html
- Reset Tech, Clickbait Cures: https://reset.tech/resources/research-note-clickbait-cures-fake-meds-market
- Stealth browser benchmark (third-party): https://ianlpaterson.com/blog/anti-detect-browser-benchmark-patchright-nodriver-curl-cffi/
- NS-pair pivoting: https://circleid.com/posts/the-phishing-domain-you-missed-shares-a-nameserver-with-the-one-you-caught · https://www.domaintools.com/wp-content/uploads/DomainTools-Valuable-Datasets-Cheatsheet.pdf
- Trackbox lead API fields: https://intercom.help/tigloo/en/articles/9349579-trackbox-api-documentation
