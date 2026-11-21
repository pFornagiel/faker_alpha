"""Live URL capture pipeline: SSRF-safe multi-profile HTTP fetching, semantic cloaking classification,
optional sandboxed Playwright render (HAR + screenshot + DOM), and manifest persistence.

Steps:
  1. Validate target URL via `net.validate_public_url` (block non-public IPs / non-http(s) schemes).
  2. Follow redirects under 3 client profiles (`bot`, `desktop_pl`, `fb_mobile`) via `follow_profile`.
  3. Classify cloaking structurally and semantically via `classify_cloaking` (no raw HTML hashing).
  4. Optionally render in sandboxed headless Chromium via `render_browser` with route SSRF guard.
  5. Persist `capture_manifest.json` with full profile summaries and explainable cloaking verdict.
"""
from __future__ import annotations

import hashlib
import html as html_lib
import json
import logging
import re
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from . import config, net, web

log = logging.getLogger(__name__)

MAX_HTML_BYTES = 3_000_000
DEFAULT_TIMEOUT: tuple[float, float] = (5.0, 12.0)

PROFILES: dict[str, dict[str, str]] = {
    "bot": {
        "User-Agent": "Mozilla/5.0 (compatible; FakeTraceBot/0.1)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    },
    "desktop_pl": {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.5",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    },
    "fb_mobile": {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36 "
            "[FB_IAB/FB4A;FBAV/480.0.0.0;]"
        ),
        "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.5",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://l.facebook.com/",
        "X-Requested-With": "com.facebook.katana",
    },
}

META_REFRESH_RX = re.compile(
    r"""<meta\b[^>]*http-equiv\s*=\s*["']?refresh["']?[^>]*content\s*=\s*["']?\s*\d+\s*;\s*url\s*=\s*([^"'>\s]+)""",
    re.I,
)
META_REFRESH_ALT_RX = re.compile(
    r"""<meta\b[^>]*content\s*=\s*["']?\s*\d+\s*;\s*url\s*=\s*([^"'>\s]+)[^>]*http-equiv\s*=\s*["']?refresh["']?""",
    re.I,
)
JS_REDIRECT_RX = re.compile(
    r"""(?:window\.)?location(?:\.href)?\s*=\s*["']([^"']+)["']|location\.replace\(\s*["']([^"']+)["']\s*\)""",
    re.I,
)
_TOKEN_RX = re.compile(r"[a-z0-9ąćęłńóśźż]{3,}")
_BOT_BLOCK_CODES = {403, 429, 503}


# ------------------------------------------------------------------ helpers
def _with_synthetic_fbclid(url: str) -> str:
    """Append a deterministic synthetic `fbclid` parameter if none is present."""
    parts = urlsplit(url)
    params = parse_qsl(parts.query, keep_blank_values=True)
    if any(k.lower() == "fbclid" for k, _ in params):
        return url
    digest = hashlib.sha1(url.encode("utf-8", "replace")).hexdigest()[:24]
    params.append(("fbclid", f"IwAR0{digest}"))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment))


def _decode_body(resp: requests.Response, raw: bytes) -> str:
    if not raw:
        return ""
    enc = resp.encoding or "utf-8"
    try:
        return raw.decode(enc, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def _extract_meta_refresh(snippet: str) -> str | None:
    m = META_REFRESH_RX.search(snippet) or META_REFRESH_ALT_RX.search(snippet)
    if not m:
        return None
    target = html_lib.unescape(m.group(1)).strip().strip("'\"")
    return target or None


def _visible_text_len(raw_html: str) -> int:
    soup = BeautifulSoup(raw_html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg", "template"]):
        tag.decompose()
    return len(re.sub(r"\s+", " ", soup.get_text(" ")).strip())


def _extract_page_signature(raw_html: str) -> dict:
    """Build a structural & semantic signature resilient to CSP nonces and dynamic attributes."""
    soup = BeautifulSoup(raw_html, "lxml")
    title = ""
    if soup.title and soup.title.string:
        title = re.sub(r"\s+", " ", soup.title.string).strip()

    tags = [t.name for t in soup.find_all(True) if t.name not in ("script", "style", "noscript")]
    tag_shingles = {" ".join(tags[i : i + 4]) for i in range(max(1, len(tags) - 3))} if tags else set()

    for tag in soup(["script", "style", "noscript", "svg", "template"]):
        tag.decompose()
    visible = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
    tokens = set(_TOKEN_RX.findall(visible.lower()))
    return {
        "title": title,
        "title_norm": title.lower(),
        "text_len": len(visible),
        "tokens": tokens,
        "tag_shingles": tag_shingles,
    }


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    union = len(a | b)
    return len(a & b) / union if union else 1.0


def _reg_domain(url: str) -> str:
    return web.registrable_domain(url) if url else ""


# ------------------------------------------------------------------ Step 2: follow_profile
def follow_profile(
    url: str,
    profile_name: str,
    headers: dict[str, str],
    max_hops: int = 12,
    timeout: tuple[float, float] = DEFAULT_TIMEOUT,
) -> dict:
    """Follow HTTP, `<meta http-equiv=refresh>`, and stub-page JS redirects under one client profile."""
    cur = _with_synthetic_fbclid(url) if profile_name == "fb_mobile" else url
    chain: list[str] = []
    seen_urls: set[str] = set()
    body_html = ""
    status: int | None = None
    last_headers: dict[str, str] = {}
    session = requests.Session()

    try:
        for _ in range(max_hops):
            if cur in seen_urls:
                return {
                    "profile": profile_name,
                    "chain": chain,
                    "final_url": chain[-1] if chain else cur,
                    "html": body_html,
                    "status": status,
                    "headers": last_headers,
                    "error": "redirect cycle detected",
                }
            try:
                cur, _ = net.validate_public_url(cur)
            except ValueError as exc:
                return {
                    "profile": profile_name,
                    "chain": chain + [cur],
                    "final_url": chain[-1] if chain else cur,
                    "html": body_html,
                    "status": status,
                    "headers": last_headers,
                    "error": f"blocked redirect target: {exc}",
                }

            seen_urls.add(cur)
            try:
                resp, raw = net.safe_get(
                    session,
                    cur,
                    headers=headers,
                    timeout=timeout,
                    max_bytes=MAX_HTML_BYTES,
                    allow_redirects=False,
                )
            except Exception as exc:
                return {
                    "profile": profile_name,
                    "chain": chain + [cur],
                    "final_url": chain[-1] if chain else cur,
                    "html": body_html,
                    "status": status,
                    "headers": last_headers,
                    "error": str(exc)[:200],
                }

            chain.append(cur)
            status = resp.status_code
            last_headers = dict(resp.headers)

            if resp.is_redirect and resp.headers.get("location"):
                nxt = urljoin(cur, resp.headers["location"].strip())
                if nxt != cur:
                    cur = nxt
                    continue

            ctype = (resp.headers.get("content-type") or "").lower()
            body_html = _decode_body(resp, raw) if ("html" in ctype or not ctype) else ""

            # Check <meta http-equiv="refresh"> and tiny JS redirector stubs
            nxt_ref = _extract_meta_refresh(body_html[:20_000])
            if not nxt_ref and body_html and len(body_html) < 3500 and _visible_text_len(body_html) < 300:
                jm = JS_REDIRECT_RX.search(body_html)
                if jm:
                    nxt_ref = html_lib.unescape(jm.group(1) or jm.group(2) or "").strip()

            if nxt_ref and not nxt_ref.lower().startswith(("#", "javascript:", "data:", "mailto:")):
                resolved = urljoin(cur, nxt_ref)
                if resolved != cur:
                    cur = resolved
                    continue
            break
    finally:
        session.close()

    return {
        "profile": profile_name,
        "chain": chain,
        "final_url": chain[-1] if chain else url,
        "html": body_html,
        "status": status,
        "headers": last_headers,
        "error": None,
    }


def follow(url: str, headers: dict[str, str], max_hops: int = 12, timeout: int | tuple[float, float] = 15) -> dict:
    """Backwards-compatible wrapper around `follow_profile`."""
    to = (min(5.0, float(timeout)), float(timeout)) if isinstance(timeout, (int, float)) else timeout
    return follow_profile(url, "custom", headers, max_hops=max_hops, timeout=to)


# ------------------------------------------------------------------ Step 3: classify_cloaking
def classify_cloaking(profile_results: dict[str, dict]) -> dict:
    """Compare client profile responses structurally & semantically to classify cloaking.

    Verdicts:
      - `cloaking_suspected` (`cloaking=True`): different final registrable domain (200 vs 200),
        or substantial divergent content (different title + low text & DOM overlap).
      - `bot_blocked` (`cloaking=False`): WAF/rate-limiter blocks `bot` (403/429/503) while
        `desktop_pl` and `fb_mobile` receive matching 200 responses.
      - `responsive_variant` (`cloaking=False`): same domain & narrative, minor mobile layout shift.
      - `none` (`cloaking=False`): consistent responses across profiles.
      - `unreachable` (`cloaking=False`): no profile received a 2xx HTML response.
    """
    sigs: dict[str, dict] = {}
    ok_profiles: list[str] = []
    statuses: dict[str, int | None] = {}
    domains: dict[str, str] = {}

    for name, res in profile_results.items():
        st = res.get("status")
        statuses[name] = st
        final_u = res.get("final_url") or ""
        domains[name] = _reg_domain(final_u)
        raw_html = res.get("html") or ""
        if st is not None and 200 <= st < 300 and raw_html:
            ok_profiles.append(name)
            sigs[name] = _extract_page_signature(raw_html)

    metrics: dict = {"statuses": statuses, "domains": domains, "pairs": {}}
    reasons: list[str] = []

    if not ok_profiles:
        return {
            "cloaking": False,
            "verdict": "unreachable",
            "reasons": ["no client profile received a 2xx HTML response"],
            "metrics": metrics,
        }

    bot_status = statuses.get("bot")
    bot_blocked = bot_status in _BOT_BLOCK_CODES

    # Rule 1: Compare final registrable domains across 2xx profiles
    pairs_to_check: list[tuple[str, str]] = []
    for a, b in (("desktop_pl", "fb_mobile"), ("bot", "fb_mobile"), ("bot", "desktop_pl")):
        if a in sigs and b in sigs:
            pairs_to_check.append((a, b))

    domain_mismatch = False
    content_cloaking = False
    responsive_diff = False

    for a, b in pairs_to_check:
        dom_a, dom_b = domains[a], domains[b]
        if dom_a and dom_b and dom_a != dom_b:
            domain_mismatch = True
            reasons.append(f"different final domain: {a} -> {dom_a} vs {b} -> {dom_b}")

        sa, sb = sigs[a], sigs[b]
        text_j = _jaccard(sa["tokens"], sb["tokens"])
        dom_j = _jaccard(sa["tag_shingles"], sb["tag_shingles"])
        same_title = bool(sa["title_norm"] and sa["title_norm"] == sb["title_norm"])
        metrics["pairs"][f"{a}_vs_{b}"] = {
            "text_jaccard": round(text_j, 3),
            "dom_jaccard": round(dom_j, 3),
            "same_title": same_title,
            "text_len_a": sa["text_len"],
            "text_len_b": sb["text_len"],
        }

        if dom_a == dom_b:
            substantial = sa["text_len"] >= 200 and sb["text_len"] >= 200
            if substantial and not same_title and text_j < 0.30 and dom_j < 0.40:
                content_cloaking = True
                reasons.append(
                    f"divergent page content between {a} and {b} on {dom_a} "
                    f"(text_jaccard={text_j:.2f}, dom_jaccard={dom_j:.2f}, titles differ)"
                )
            elif text_j >= 0.55 or (same_title and text_j >= 0.35):
                if text_j < 0.85 or dom_j < 0.85:
                    responsive_diff = True

    if domain_mismatch or content_cloaking:
        return {
            "cloaking": True,
            "verdict": "cloaking_suspected",
            "reasons": reasons,
            "metrics": metrics,
        }

    if bot_blocked and "desktop_pl" in sigs and "fb_mobile" in sigs:
        reasons.append(
            f"bot profile blocked (HTTP {bot_status}) while desktop_pl and fb_mobile received matching 200 responses"
        )
        return {
            "cloaking": False,
            "verdict": "bot_blocked",
            "reasons": reasons,
            "metrics": metrics,
        }

    if bot_blocked and len(ok_profiles) == 1:
        reasons.append(f"bot profile blocked (HTTP {bot_status}); only {ok_profiles[0]} returned 200")
        return {
            "cloaking": False,
            "verdict": "bot_blocked",
            "reasons": reasons,
            "metrics": metrics,
        }

    if responsive_diff:
        reasons.append("minor layout/responsive differences across profiles on the same domain")
        return {
            "cloaking": False,
            "verdict": "responsive_variant",
            "reasons": reasons,
            "metrics": metrics,
        }

    reasons.append("consistent domain and content across client profiles")
    return {
        "cloaking": False,
        "verdict": "none",
        "reasons": reasons,
        "metrics": metrics,
    }


# ------------------------------------------------------------------ Step 4: render_browser
def render_browser(url: str, out_dir: Path) -> dict:
    """Render `url` in a sandboxed mobile Chromium context (HAR + screenshot + DOM).

    Guards all subrequests with `net.validate_public_url` and guarantees clean browser shutdown.
    """
    from playwright.sync_api import sync_playwright

    har = out_dir / "page.har"
    shot = out_dir / "screenshot.png"
    dom = out_dir / "rendered.html"

    def _route_guard(route) -> None:
        req_url = route.request.url
        scheme = urlsplit(req_url).scheme.lower()
        if scheme in ("data", "blob", "about"):
            route.continue_()
            return
        try:
            net.validate_public_url(req_url)
        except ValueError as exc:
            log.debug("Playwright blocked non-public request %s: %s", req_url, exc)
            route.abort("blockedbyclient")
            return
        route.continue_()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = None
        try:
            ctx = browser.new_context(
                user_agent=PROFILES["fb_mobile"]["User-Agent"],
                locale="pl-PL",
                timezone_id="Europe/Warsaw",
                viewport={"width": 412, "height": 915},
                is_mobile=True,
                accept_downloads=False,
                service_workers="block",
                record_har_path=str(har),
                record_har_content="embed",
                extra_http_headers={
                    "Referer": "https://l.facebook.com/",
                    "X-Requested-With": "com.facebook.katana",
                },
            )
            ctx.route("**/*", _route_guard)
            page = ctx.new_page()
            nav_ok = False
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=25_000)
                nav_ok = True
            except Exception as exc:
                log.debug("Playwright goto partial/failed for %s: %s", url, exc)
            try:
                page.wait_for_load_state("networkidle", timeout=6_000)
            except Exception:
                pass
            page.wait_for_timeout(1200)

            final = page.url or ""
            rendered = page.content() if nav_ok or (final and final != "about:blank") else ""
            succeeded = bool(final and final != "about:blank" and rendered and len(rendered) > 64)

            out: dict[str, str | None] = {
                "har": None,
                "screenshot": None,
                "rendered_html": None,
                "final_url": None,
            }
            if succeeded:
                dom.write_text(
                    f"<!-- saved from url=({len(final):04d}){final} -->\n" + rendered,
                    encoding="utf-8",
                )
                page.screenshot(path=str(shot), full_page=False)
                out["rendered_html"] = str(dom)
                out["screenshot"] = str(shot)
                out["final_url"] = final
        finally:
            if ctx is not None:
                try:
                    ctx.close()
                except Exception:
                    pass
            try:
                browser.close()
            except Exception:
                pass

    if har.exists() and har.stat().st_size > 0 and out.get("rendered_html"):
        out["har"] = str(har)
    return out


# ------------------------------------------------------------------ Orchestrator
def capture_url(url: str, render: bool = True) -> dict:
    """Run the 5-step safe URL capture pipeline and return a manifest-backed summary dict."""
    # Step 1: SSRF / scheme validation
    try:
        clean_url, resolved_ips = net.validate_public_url(url)
    except ValueError as exc:
        log.warning("capture_url rejected %r: %s", url, exc)
        return {
            "url": url,
            "dir": None,
            "profiles": {},
            "final_url": None,
            "html": None,
            "title": "",
            "cloaking": False,
            "cloaking_verdict": "invalid_url",
            "cloaking_reasons": [str(exc)],
            "manifest": None,
            "rendered_html": None,
            "har": None,
            "screenshot": None,
            "meta": [],
            "notes": [f"blocked URL: {exc}"],
            "error": str(exc),
        }

    h = hashlib.sha1(clean_url.encode("utf-8", "replace")).hexdigest()[:12]
    out_dir = config.ARTIFACTS / "captures" / h
    out_dir.mkdir(parents=True, exist_ok=True)

    # Step 2: Multi-profile HTTP redirect following
    raw_profiles: dict[str, dict] = {}
    profile_summaries: dict[str, dict] = {}
    chosen_html_path: str | None = None
    chosen_final_url: str | None = None
    chosen_title = ""
    notes: list[str] = []

    for name, hdrs in PROFILES.items():
        r = follow_profile(clean_url, name, hdrs)
        raw_profiles[name] = r
        raw_html = r.get("html") or ""
        sig = _extract_page_signature(raw_html) if raw_html else {"title": ""}
        profile_summaries[name] = {
            "chain": r["chain"],
            "final_url": r.get("final_url"),
            "status": r.get("status"),
            "error": r.get("error"),
            "len": len(raw_html),
            "title": sig["title"],
        }
        if raw_html and (name == "fb_mobile" or chosen_html_path is None):
            snap = out_dir / f"{name}.html"
            f_url = r.get("final_url") or clean_url
            snap.write_text(
                f"<!-- saved from url=({len(f_url):04d}){f_url} -->\n" + raw_html,
                encoding="utf-8",
            )
            chosen_html_path = str(snap)
            chosen_final_url = f_url
            chosen_title = sig["title"]
        time.sleep(0.25)

    # Step 3: Semantic & structural cloaking classification
    cloak = classify_cloaking(raw_profiles)
    if cloak["cloaking"]:
        notes.append("cloaking suspected: " + "; ".join(cloak["reasons"]))
    elif cloak["verdict"] == "bot_blocked":
        notes.append("WAF/bot protection: " + "; ".join(cloak["reasons"]))
    elif cloak["verdict"] == "unreachable":
        notes.append("page unreachable (dead domain or blocked)")

    # Step 4: Optional sandboxed Playwright render
    rendered_html: str | None = None
    har_path: str | None = None
    screenshot_path: str | None = None
    if render:
        try:
            r_out = render_browser(clean_url, out_dir)
            rendered_html = r_out.get("rendered_html")
            har_path = r_out.get("har")
            screenshot_path = r_out.get("screenshot")
            if rendered_html and r_out.get("final_url"):
                chosen_html_path = rendered_html
                chosen_final_url = r_out["final_url"]
                if not chosen_title:
                    chosen_title = _extract_page_signature(
                        Path(rendered_html).read_text(encoding="utf-8", errors="replace")
                    )["title"]
        except Exception as exc:
            notes.append(f"render skipped: {str(exc)[:120]}")

    # Step 5: Persist capture manifest
    fb_chain = profile_summaries.get("fb_mobile", {}).get("chain") or profile_summaries.get("desktop_pl", {}).get("chain") or []
    manifest_path = out_dir / "capture_manifest.json"
    manifest_data = {
        "tool": "ftf.capture",
        "page_url": clean_url,
        "final_url": chosen_final_url,
        "title": chosen_title,
        "resolved_ips": resolved_ips,
        "redirects": fb_chain,
        "profiles": profile_summaries,
        "cloaking": cloak["cloaking"],
        "cloaking_verdict": cloak["verdict"],
        "cloaking_reasons": cloak["reasons"],
        "cloaking_metrics": cloak["metrics"],
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    manifest_path.write_text(json.dumps(manifest_data, ensure_ascii=False, indent=1), encoding="utf-8")

    return {
        "url": clean_url,
        "dir": str(out_dir),
        "profiles": profile_summaries,
        "final_url": chosen_final_url,
        "html": chosen_html_path,
        "title": chosen_title,
        "cloaking": cloak["cloaking"],
        "cloaking_verdict": cloak["verdict"],
        "cloaking_reasons": cloak["reasons"],
        "manifest": str(manifest_path),
        "rendered_html": rendered_html,
        "har": har_path,
        "screenshot": screenshot_path,
        "meta": [str(manifest_path)],
        "notes": notes,
    }
