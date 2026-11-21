"""Web-layer feature extraction: URL structure, HTML (saved pages / captures), HAR network logs, MHTML.

Produces *indicators* (discrete, typed values such as a Facebook pixel ID or a TDS tenant UUID) that
are later matched exactly across materials (config.IDENTIFIER_GROUP), plus HTML tag shingles (html view).
Tracker regexes adapted from research/02 (verified live on CERT Polska-listed sites, 2026-11-21).
"""
from __future__ import annotations

import base64
import email
import hashlib
import json
import re
from collections import Counter
from email import policy
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urljoin, urlparse

import tldextract
from bs4 import BeautifulSoup, Comment

# Bundled PSL snapshot (works offline) with private suffixes enabled so
# a.pages.dev != b.pages.dev and a.netlify.app != b.netlify.app.
_TLD = tldextract.TLDExtract(suffix_list_urls=(), include_psl_private_domains=True)

# Hosts/libraries shared by half the internet: never a linking signal on their own.
GENERIC_DOMAINS = {
    "google.com", "googleapis.com", "translate.googleapis.com", "gstatic.com", "googletagmanager.com",
    "google-analytics.com", "doubleclick.net", "googlesyndication.com", "googleadservices.com",
    "youtube.com", "ytimg.com", "facebook.com", "facebook.net", "fbcdn.net", "instagram.com",
    "cdninstagram.com", "fb.com", "jquery.com", "jsdelivr.net", "cloudflare.com",
    "cdnjs.cloudflare.com", "challenges.cloudflare.com", "cloudflareinsights.com", "unpkg.com",
    "bootstrapcdn.com", "fontawesome.com", "fonts.net", "typekit.net", "gravatar.com", "wp.com",
    "wordpress.org", "w3.org", "schema.org", "apple.com", "microsoft.com", "bing.com", "clarity.ms",
    "hotjar.com", "yandex.ru", "tiktok.com", "twitter.com", "x.com", "linkedin.com", "cookiebot.com",
    "onetrust.com", "sentry.io", "github.io", "githubusercontent.com", "vimeo.com", "localhost",
    "wikipedia.org", "wikimedia.org", "pinterest.com", "whatsapp.com", "telegram.org", "t.me",
    "shopify.com", "amazonaws.com", "cloudfront.net", "akamaihd.net", "unsplash.com", "er-api.com",
    "b-cdn.net", "polyfill.io", "hcaptcha.com",
    # Public services, placeholders and default-server pages that joined three or more unrelated kit families in a
    # background corpus of CERT Polska warning-list pages (tools/research_corpus.py).
    "flagcdn.com", "ipapi.co", "ipinfo.io", "frankfurter.dev", "alicdn.com", "klaviyo.com", "shopifysvc.com",
    "shop.app", "posthog.com", "vimeocdn.com", "tradingview.com", "tradingview-widget.com", "plesk.com",
    "nginx.com", "nginx.org", "example.com", "example.org", "domain.com", "email.com", "ejemplo.com",
}
# Hosting platforms where every customer gets a sub-host and the public-suffix list does not say so. The registrable
# domain there is the platform, shared by unrelated operators; the full host is what identifies the customer.
SHARED_HOSTING_SUFFIXES = {
    "on.aws", "weebly.com", "weeblysite.com", "base44.app", "edgeone.dev", "edgeone.app", "godaddysites.com",
    "wordpress.com", "surge.sh", "wstd.io", "mystrikingly.com", "webnode.page", "tilda.ws", "ucoz.net",
    "hostingersite.com", "translate.goog", "softr.app", "durable.co", "site123.me",
}
# Request paths owned by a hosting platform or an analytics SDK, identical on every site that uses it.
_PLATFORM_PATH_RX = re.compile(
    r"^/(?:cdn-cgi/|wp-admin/admin-ajax\.php|wp-json/|\.well-known/|__l5e/|(?:api/collect|v1/metrics|collect|e)/?$)", re.I)
_GOOGLE_CC_RX = re.compile(r"^(?:[\w-]+\.)*google(?:\.[a-z]{2,3}){1,2}$", re.I)

# Domains frequently shown as decoys/spoofed news/platforms in ad creatives (filter from ocr_domain).
OCR_DECOY_DOMAINS = {
    "amazon.com", "fb.me", "interia.pl", "onet.pl", "wp.pl", "gazeta.pl", "tvn24.pl", "polsatnews.pl",
    "allegro.pl", "olx.pl", "youtube.com", "youtu.be", "bit.ly", "tinyurl.com", "t.co",
}

GENERIC_SCRIPT_NAMES = re.compile(
    r"^(jquery|bootstrap|popper|swiper|slick|lazysizes|sweetalert|shaka-player|video|hls|vue|react|"
    r"lodash|moment|axios|gtag|analytics|fbevents|sdk|main|app|index|script|scripts|common|vendor|"
    r"runtime|polyfills?|chunk|bundle|core|min|jquery-\d|wp-|wp_|wpembed|wp-emoji|style|styles|"
    r"normalize|reset|fonts?|icons?|all|libs?)([-._]|\d|$)", re.I)

TRACKER_RX = {
    "ga": r"\b(?:UA-\d{4,10}-\d{1,4}|G-[A-Z0-9]{8,12})\b",
    "gtm": r"\bGTM-[A-Z0-9]{4,9}\b",
    "gads": r"\bAW-\d{9,12}\b",
    "fb_pixel": r"""fbq\(\s*['"]init['"]\s*,\s*['"](\d{14,17})['"]|facebook\.com/tr/?\?id=(\d{14,17})|"pixel_?id"\s*:\s*"?(\d{14,17})""",
    "tiktok_pixel": r"""ttq\.load\(\s*['"]([A-Z0-9]{18,22})['"]|analytics\.tiktok\.com/[^"']*?sdkid=([A-Z0-9]{18,22})""",
}
CONTACT_RX = {
    "telegram": r"(?:t\.me|telegram\.me)/(\+?[A-Za-z0-9_]{5,32})",
    "whatsapp": r"(?:wa\.me|api\.whatsapp\.com/send\?phone=)/?(\d{8,15})",
    "email": r"\b([A-Za-z0-9._%+-]{2,40}@[A-Za-z0-9.-]{2,60}\.[a-z]{2,10})\b",
    "phone": r"(?<![\d/=.-])((?:\+48|0048)[ -]?\d{3}[ -]?\d{3}[ -]?\d{3}|\+\d{2}[ -]?\d{2,3}[ -]?\d{3}[ -]?\d{2,3}[ -]?\d{2,3})(?![\d])",
    "wallet": r"\b(bc1[ac-hj-np-z02-9]{25,60}|0x[a-fA-F0-9]{40}|T[1-9A-HJ-NP-Za-km-z]{33})\b",
}
EMAIL_IGNORE = re.compile(
    r"(example\.|sentry|wixpress|@2x|\.png|\.jpg|\.webp|\.svg|\.gif|domain\.com|email\.com|"
    r"yourmail|twojmail|test@|user@|name@)", re.I)

UUID_RX = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)

# URL query parameters that carry operator/affiliate/campaign identity (value is an indicator)
ID_PARAMS = {
    "fb_pixel": {"pxl", "fbpx", "pixel", "pixel_id", "fb_pixel", "fbp_id", "px", "fbpixel"},
    "ad_id": {"ad_id", "adid", "fb_ad_id", "utm_content_id"},
    "adset": {"adset_name", "adset", "adset_id", "ad_name", "campaign_name"},
    "affiliate": {
        "acc", "aff", "aff_id", "affid", "affiliate", "affiliate_id", "partner", "sub_id", "subid",
        "sub1", "webmaster", "webmaster_id", "wm", "pid", "source_id", "offer_id", "offer", "lpkey",
        "land_id", "_camp_id", "camp_id", "trafficsource", "flow", "stream", "user_id",
    },
}
VOLATILE_PARAMS = {
    "fbclid", "gclid", "clickid", "click_id", "utm_visit", "access_token", "_trk", "key",
    "ttclid", "msclkid", "wbraid", "gbraid", "yclid", "t", "ts", "v", "_", "cb", "rnd", "nocache",
}
SESSION_PARAM_HINTS = ("utm_visit", "clickid", "click_id", "session", "visit")


def registrable_domain(url_or_host: str) -> str:
    if not url_or_host:
        return ""
    host = urlparse(url_or_host).hostname if "://" in url_or_host else url_or_host.split("/")[0]
    if not host:
        return ""
    host = host.strip().lower().rstrip(".")
    ext = _TLD(host)
    if not ext.suffix:
        return host if "." in host else ""
    if not ext.domain:
        return host
    reg = f"{ext.domain}.{ext.suffix}".lower()
    for shared in SHARED_HOSTING_SUFFIXES:
        if reg == shared or reg.endswith("." + shared):
            return host            # customer sub-host of a shared platform, e.g. <id>.ecs.us-east-1.on.aws
    return reg


def is_generic(domain: str) -> bool:
    d = (domain or "").strip().lower().rstrip(".")
    if not d or "." not in d:
        return True
    if _GOOGLE_CC_RX.match(d):
        return True
    if d in SHARED_HOSTING_SUFFIXES:
        return True                # the platform itself; its customer sub-hosts are not generic
    return d in GENERIC_DOMAINS or any(d.endswith("." + g) for g in GENERIC_DOMAINS)


def is_platform_endpoint(value: str) -> bool:
    """True for an `api_template` ("POST /path") or `form_endpoint` ("host/path") that belongs to a hosting platform
    or analytics SDK (Cloudflare RUM, WordPress AJAX, PostHog, ...) rather than to the page's operator."""
    v = (value or "").split(" ", 1)[-1]
    host, path = ("", v) if v.startswith("/") else (v.split("/", 1)[0], "/" + v.partition("/")[2])
    if host and is_generic(registrable_domain(host)):
        return True
    return bool(_PLATFORM_PATH_RX.match(path))


def is_decoy_or_generic_domain(dom: str) -> bool:
    """True for generic infrastructure/CDNs and spoofed media/platform decoy domains (e.g. interia.pl, fb.me)."""
    d = (dom or "").strip().lower().rstrip(".")
    if is_generic(d):
        return True
    reg = registrable_domain(d)
    return d in OCR_DECOY_DOMAINS or reg in OCR_DECOY_DOMAINS


def _clean_asset_filename(raw_name: str) -> str:
    """Strip URL-encoding, Chrome '(1)' duplicate suffix, and browser '.pobrane/.pobierz' suffix."""
    name = unquote(raw_name or "").strip()
    name = re.sub(r"\.(?:pobrane|pobierz)$", "", name, flags=re.I)
    name = re.sub(r"\s*\(\d+\)(?=\.[^.]+$)", "", name)
    return name


def url_indicators(url: str) -> dict:
    """Indicators carried by a URL: domain, host, ID-bearing params, tenant UUIDs, path template."""
    if not url or not url.startswith(("http://", "https://")):
        return {}
    p = urlparse(url)
    host = (p.hostname or "").lower()
    dom = registrable_domain(url)
    q = parse_qsl(p.query, keep_blank_values=True)
    out: dict[str, set[str]] = {}
    if dom and not is_generic(dom):
        out["landing_domain"] = {dom}
    if host and not is_generic(dom or host):
        out["page_host"] = {host}

    for kind, keys in ID_PARAMS.items():
        for k, v in q:
            kl = k.lower()
            if kl in keys and v and len(v) >= 3 and kl not in VOLATILE_PARAMS:
                val = unquote(v).strip()[:120]
                if kind == "fb_pixel":
                    if not re.fullmatch(r"\d{14,17}", val):
                        continue
                    out.setdefault("fb_pixel", set()).add(val)  # bare numeric ID
                elif kind == "ad_id":
                    out.setdefault("ad_id", set()).add(val)     # bare ad ID
                else:
                    out.setdefault(kind, set()).add(f"{kl}={val}")

    for k, v in q:  # numeric utm_campaign / utm_id are Meta campaign IDs (15-20 digits)
        if k in ("utm_campaign", "utm_id", "utm_term", "utm_content") and re.fullmatch(r"\d{15,20}", v):
            out.setdefault("campaign_param", set()).add(v)

    if dom and not is_generic(dom):
        tenants = set(UUID_RX.findall(p.path))
        if tenants:
            out["tenant_uuid"] = {t.lower() for t in tenants}

    tmpl = UUID_RX.sub("{uuid}", p.path)
    tmpl = re.sub(r"/[0-9a-f]{16,}", "/{hex}", tmpl)
    tmpl = re.sub(r"\d+", "{n}", tmpl)
    if tmpl not in ("", "/"):
        out["path_template"] = {tmpl}
    return {k: v for k, v in out.items() if v and v != {""}}


def template_path(path: str) -> str:
    """/api/v1/trigger/field/01a11f55-dea2-.../ -> /api/v1/trigger/field/{id}/ (per-visit IDs removed)."""
    t = UUID_RX.sub("{id}", path)
    t = re.sub(r"(?<=/)[0-9a-f]{16,}(?=/|$)", "{id}", t)
    t = re.sub(r"(?<=/)\d{3,}(?=/|$)", "{n}", t)
    return t


def merge_ind(dst: dict, src: dict) -> dict:
    for k, vals in (src or {}).items():
        dst.setdefault(k, set()).update(v for v in vals if v)
    return dst


def regex_indicators(text: str) -> dict:
    out: dict[str, set[str]] = {}
    if not text:
        return out
    for kind, rx in {**TRACKER_RX, **CONTACT_RX}.items():
        for m in re.finditer(rx, text):
            groups = [g for g in m.groups() if g] if m.groups() else [m.group(0)]
            for g in groups or [m.group(0)]:
                g = g.strip()
                if kind == "email" and EMAIL_IGNORE.search(g):
                    continue
                if kind == "phone":
                    g = re.sub(r"[ -]", "", g)
                    if g.startswith("0048"):
                        g = "+48" + g[4:]
                    if len(set(g[-9:])) <= 2 or re.search(r"55501\d{2}$", g):
                        continue
                out.setdefault(kind, set()).add(g)
    return out


def extract_script_indicators(path: Path) -> dict[str, set[str]]:
    """Scan a local saved JS asset (.js, .js.pobrane, .js.pobierz) for trackers and its content hash."""
    out: dict[str, set[str]] = {}
    p = Path(path)
    try:
        body = p.read_text(encoding="utf-8", errors="replace")[:1_000_000]
    except Exception:
        return out
    if not body.strip():
        return out
    raw_ind = regex_indicators(body)
    merge_ind(out, {k: v for k, v in raw_ind.items() if k not in ("email", "phone")})
    name = _clean_asset_filename(p.name)
    name_norm = re.sub(r"[._-][0-9a-f]{6,}(?=\.)", "", name)
    if name_norm.lower().endswith(".js") and not GENERIC_SCRIPT_NAMES.match(name_norm) and len(body) > 500:
        out.setdefault("script_hash", set()).add(hashlib.sha1(body.encode("utf-8", "replace")).hexdigest()[:16])
    return out


# ------------------------------------------------------------------------------------------ HTML
def extract_html(html: str, base_url: str = "") -> dict:
    """Parse a saved page / rendered DOM."""
    saved = re.search(r"saved from url=\(\d+\)(\S+)", html[:3000])
    saved_url = saved.group(1).rstrip("-> ") if saved else ""
    soup = BeautifulSoup(html, "lxml")
    base = base_url or saved_url
    canon = soup.find("link", rel=lambda r: r and "canonical" in r)
    og_url = soup.find("meta", attrs={"property": "og:url"})
    title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    metas = {}
    for m in soup.find_all("meta"):
        k = m.get("name") or m.get("property") or m.get("http-equiv")
        if k and m.get("content"):
            metas[k.lower()] = m["content"][:300]
    comments = [
        c.strip()[:200] for c in soup.find_all(string=lambda s: isinstance(s, Comment))
        if c.strip() and not c.strip().startswith("saved from url")
    ][:20]
    scripts = [s.get("src") for s in soup.find_all("script") if s.get("src")]
    inline_js = "\n".join(s.get_text() for s in soup.find_all("script") if not s.get("src"))[:400_000]
    css = [l.get("href") for l in soup.find_all("link") if l.get("href") and "stylesheet" in (l.get("rel") or [])]
    icons = [l.get("href") for l in soup.find_all("link") if l.get("href") and any("icon" in r for r in (l.get("rel") or []))]
    forms = []
    for f in soup.find_all("form"):
        forms.append({
            "action": f.get("action") or "",
            "method": (f.get("method") or "get").lower(),
            "inputs": sorted({i.get("name") for i in f.find_all(["input", "select", "textarea"]) if i.get("name")}),
        })
    links = [a.get("href") for a in soup.find_all("a") if a.get("href")]
    imgs = [i.get("src") or i.get("data-src") for i in soup.find_all("img") if (i.get("src") or i.get("data-src"))]
    tags = [t.name for t in soup.find_all(True)]
    classes = sorted({c for t in soup.find_all(True) for c in (t.get("class") or [])})
    for t in soup(["script", "style", "noscript", "svg", "template"]):
        t.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()

    ind: dict[str, set[str]] = {}
    merge_ind(ind, regex_indicators(html))
    for u in [saved_url, canon.get("href") if canon else "", og_url.get("content") if og_url else ""]:
        if u and u.startswith("http"):
            merge_ind(ind, url_indicators(u))
    for f in forms:
        act = f["action"]
        if act and not act.startswith(("#", "javascript")):
            full = urljoin(base, act) if base else act
            pr = urlparse(full)
            ep_dom = registrable_domain(pr.hostname or "")
            if pr.hostname and is_generic(ep_dom or pr.hostname):
                pass
            else:
                ep = f"{(pr.hostname or '').lower()}{pr.path}" if pr.hostname else pr.path
                if ep and ep not in ("/", ""):
                    ind.setdefault("form_endpoint", set()).add(ep)
    out_domains = set()
    for u in scripts + css + links + imgs:
        if u and u.startswith(("http", "//")):
            d = registrable_domain(urljoin("https://x/", u))
            if d and not is_generic(d):
                out_domains.add(d)
    return {
        "title": title, "saved_url": saved_url, "canonical": canon.get("href") if canon else "",
        "og_url": og_url.get("content") if og_url else "", "metas": metas, "comments": comments,
        "text": text, "scripts": scripts, "css": css, "icons": icons, "forms": forms,
        "links": links[:500], "images": imgs[:300], "tags": tags, "classes": classes,
        "linked_domains": sorted(out_domains), "inline_js_len": len(inline_js), "indicators": ind,
        "lang": (soup.html.get("lang") if soup.html else "") or "",
        "generator": metas.get("generator", ""),
    }


def tag_shingles(tags: list[str], k: int = 5) -> set[str]:
    return {" ".join(tags[i:i + k]) for i in range(max(1, len(tags) - k + 1))}


# ------------------------------------------------------------------------------------------ HAR
TEXT_MIME = ("text/", "javascript", "json", "xml", "x-www-form-urlencoded")


def _body(content: dict) -> str:
    txt = content.get("text")
    if not txt:
        return ""
    if content.get("encoding") == "base64":
        mime = (content.get("mimeType") or "").lower()
        if not any(m in mime for m in TEXT_MIME):
            return ""
        try:
            txt = base64.b64decode(txt).decode("utf-8", "replace")
        except Exception:
            return ""
    return txt[:2_000_000]


def _body_bytes(content: dict) -> bytes:
    txt = content.get("text")
    if not txt:
        return b""
    if content.get("encoding") == "base64":
        try:
            return base64.b64decode(txt)
        except Exception:
            return b""
    return txt.encode("utf-8", "replace")


def _pick_landing_url(full_reqs: list[dict], pages: list[str]) -> str:
    """Select the primary landing document from HAR requests (skipping POST 404s and generic trackers)."""
    for r in full_reqs:
        if r["method"] == "GET" and 200 <= r["status"] < 400 and not is_generic(r["domain"]):
            if "html" in r["mime"] or 300 <= r["status"] < 400:
                return r["url"]
    for p in pages:
        if p and p.startswith("http") and not is_generic(registrable_domain(p)):
            return p
    for r in full_reqs:
        if r["method"] == "GET" and 200 <= r["status"] < 400 and not is_generic(r["domain"]):
            return r["url"]
    return next((r["url"] for r in full_reqs if r["method"] == "GET"), "")


def parse_har(path: str | Path, keep_images: bool = True) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
    log = data.get("log", {})
    entries = log.get("entries", [])
    pages = [p.get("title", "") for p in log.get("pages", [])]
    full_reqs, requests_summary = [], []
    ips, hosts, server_hdrs = Counter(), Counter(), Counter()
    posts_summary, redirects_full, docs = [], [], []
    ind: dict[str, set[str]] = {}
    session_uuids: set[str] = set()
    script_hashes, images = set(), []

    for e in entries:
        rq, rs = e.get("request", {}), e.get("response", {})
        url = rq.get("url", "")
        method = (rq.get("method") or "GET").upper()
        status = rs.get("status", 0) or 0
        if not url.startswith("http"):
            continue
        pr = urlparse(url)
        host = (pr.hostname or "").lower()
        dom = registrable_domain(url)
        hosts[host] += 1
        ip = (e.get("serverIPAddress") or "").strip("[]")
        if ip:
            ips[ip] += 1
        mime = (rs.get("content", {}).get("mimeType") or "").lower()
        full_reqs.append({"method": method, "url": url, "status": status, "ip": ip, "mime": mime, "domain": dom})
        requests_summary.append({"method": method, "url": url[:500], "status": status, "ip": ip, "mime": mime})

        hdrs = {h["name"].lower(): h["value"] for h in rs.get("headers", []) if "name" in h}
        for hk in ("server", "x-powered-by", "x-generator", "x-cache", "via"):
            if hk in hdrs:
                server_hdrs[f"{hk}:{hdrs[hk][:60]}"] += 1

        if 300 <= status < 400:
            loc = rs.get("redirectURL") or hdrs.get("location", "")
            redirects_full.append((url, urljoin(url, loc) if loc else ""))
        if method == "GET" and "html" in mime and status == 200:
            docs.append(url)

        # Record per-visit session UUIDs (query params + /trigger/ or session POST paths) to exclude from tenant_uuid
        for qk, qv in parse_qsl(pr.query, keep_blank_values=True):
            qkl = qk.lower()
            if any(h in qkl for h in SESSION_PARAM_HINTS):
                session_uuids.update(u.lower() for u in UUID_RX.findall(qv))

        merge_ind(ind, regex_indicators(url))

        if method == "POST":
            posts_summary.append(url[:300])
            if "/trigger/" in pr.path.lower() or "session" in pr.path.lower():
                session_uuids.update(u.lower() for u in UUID_RX.findall(pr.path))
            tmpl = template_path(pr.path)
            if not is_generic(dom) and not is_platform_endpoint(tmpl):
                ind.setdefault("form_endpoint", set()).add(f"{host}{tmpl}")
                if tmpl.count("/") >= 2:
                    ind.setdefault("api_template", set()).add(f"POST {tmpl}")
        elif not is_generic(dom) and any(x in mime for x in ("image", "javascript", "css", "font")):
            for u in UUID_RX.findall(pr.path):  # tenant / workspace IDs of landing builders
                ind.setdefault("tenant_uuid", set()).add(u.lower())

        body = _body(rs.get("content", {}))
        if body and any(m in mime for m in TEXT_MIME):
            merge_ind(ind, {k: v for k, v in regex_indicators(body).items() if k not in ("email", "phone")})
            if "javascript" in mime and not is_generic(dom):
                name = _clean_asset_filename(pr.path.rsplit("/", 1)[-1])
                if len(body) > 500 and not GENERIC_SCRIPT_NAMES.match(name):
                    script_hashes.add(hashlib.sha1(body.encode("utf-8", "replace")).hexdigest()[:16])

        if keep_images and mime.startswith("image/") and status == 200:
            raw = _body_bytes(rs.get("content", {}))
            if len(raw) > 4000:
                images.append((url, raw))

    if script_hashes:
        ind["script_hash"] = script_hashes

    # First landing GET document -> follow 3xx using FULL URLs in memory
    first = _pick_landing_url(full_reqs, pages)
    chain_full = [first] if first else []
    rmap = dict(redirects_full)
    cur = first
    for _ in range(15):
        nxt = rmap.get(cur)
        if not nxt or nxt in chain_full:
            break
        chain_full.append(nxt)
        cur = nxt

    for u in chain_full:
        merge_ind(ind, url_indicators(u))
    for u in docs[:10]:
        d = registrable_domain(u)
        if d and not is_generic(d):
            ind.setdefault("redirect_domain" if u not in chain_full[:1] else "landing_domain", set()).add(d)
    for h in hosts:
        d = registrable_domain(h)
        if d and not is_generic(d):
            ind.setdefault("page_host", set()).add(h)
            if any(t in h for t in ("click", "track", "trk", "redirect", "go.", "lnk", "keitaro", "binom")):
                ind.setdefault("tds_host", set()).add(h)

    if session_uuids and "tenant_uuid" in ind:
        ind["tenant_uuid"] -= session_uuids
        if not ind["tenant_uuid"]:
            del ind["tenant_uuid"]

    return {
        "pages": pages,
        "n_requests": len(full_reqs),
        "requests": requests_summary[:400],
        "hosts": dict(hosts),
        "ips": dict(ips),
        "redirect_chain": [u[:500] for u in chain_full],
        "posts": posts_summary[:50],
        "server_headers": dict(server_hdrs),
        "documents": [u[:500] for u in docs[:20]],
        "indicators": ind,
        "images": images,
    }


# ------------------------------------------------------------------------------------------ MHTML
def parse_mhtml(path: str | Path) -> tuple[str, str]:
    """Return (html, location) of the main document in an MHTML archive."""
    raw = Path(path).read_bytes()
    msg = email.message_from_bytes(raw, policy=policy.default)
    loc = msg.get("Snapshot-Content-Location", "") or ""
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            try:
                html = part.get_content()
            except Exception:
                html = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
            return html, part.get("Content-Location", loc) or loc
    return "", loc
