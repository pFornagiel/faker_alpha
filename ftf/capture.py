"""Live capture of a URL (ad landing page): redirect chain under several client profiles (cloaking
detection), HTML snapshot, optional headless Chromium render (HAR + screenshot) via Playwright.

Profiles follow research/02: cloakers serve a harmless 'white page' to bots/datacenter clients and the
real offer to mobile users coming from Facebook (Referer l.facebook.com + fbclid). A different final
URL or DOM between profiles is itself recorded as a feature (cloaking=True).
Safety: no form submission, no downloads executed; captures go to data/artifacts/captures/<hash>/.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests

from . import config

log = logging.getLogger(__name__)
PROFILES = {
    "bot": {"User-Agent": "Mozilla/5.0 (compatible; FakeTraceBot/0.1)"},
    "desktop_pl": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                                 "Chrome/131.0 Safari/537.36", "Accept-Language": "pl-PL,pl;q=0.9"},
    "fb_mobile": {"User-Agent": "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/131.0 Mobile Safari/537.36 [FB_IAB/FB4A;FBAV/480.0.0.0;]",
                  "Accept-Language": "pl-PL,pl;q=0.9", "Referer": "https://l.facebook.com/"},
}
META_REFRESH = re.compile(r"""<meta[^>]+http-equiv=["']?refresh["']?[^>]+content=["']?\d+;\s*url=([^"'>]+)""", re.I)
JS_REDIRECT = re.compile(r"""(?:window\.)?location(?:\.href)?\s*=\s*["']([^"']+)["']|location\.replace\(["']([^"']+)["']\)""")


def follow(url: str, headers: dict, max_hops: int = 12, timeout: int = 15) -> dict:
    chain, html, status = [], "", None
    s = requests.Session()
    cur = url
    for _ in range(max_hops):
        try:
            r = s.get(cur, headers=headers, timeout=timeout, allow_redirects=False)
        except Exception as exc:
            return {"chain": chain + [cur], "error": str(exc)[:200], "html": html, "status": status}
        chain.append(cur)
        status = r.status_code
        if r.is_redirect and r.headers.get("location"):
            cur = urljoin(cur, r.headers["location"])
            continue
        ctype = r.headers.get("content-type", "")
        html = r.text[:3_000_000] if "html" in ctype or not ctype else ""
        m = META_REFRESH.search(html[:20000]) or None
        j = JS_REDIRECT.search(html[:20000]) if len(html) < 20000 else None
        nxt = (m.group(1) if m else None) or (j and (j.group(1) or j.group(2)))
        if nxt and not nxt.startswith(("#", "javascript")) and urljoin(cur, nxt) != cur:
            cur = urljoin(cur, nxt)
            continue
        break
    return {"chain": chain, "final_url": chain[-1] if chain else url, "html": html, "status": status,
            "headers": dict(r.headers) if "r" in locals() else {}}


def capture_url(url: str, render: bool = True) -> dict:
    h = hashlib.sha1(url.encode()).hexdigest()[:12]
    out_dir = config.ARTIFACTS / "captures" / h
    out_dir.mkdir(parents=True, exist_ok=True)
    res: dict = {"url": url, "profiles": {}, "notes": [], "meta": []}
    digests = {}
    for name, hdr in PROFILES.items():
        r = follow(url, hdr)
        res["profiles"][name] = {"chain": r["chain"], "status": r.get("status"), "error": r.get("error"),
                                 "len": len(r.get("html", ""))}
        if r.get("html"):
            digests[name] = (r["final_url"], hashlib.sha1(re.sub(r"\s+", "", r["html"])[:50000].encode()).hexdigest())
            if name == "fb_mobile" or "html" not in res:
                p = out_dir / f"{name}.html"
                p.write_text(f"<!-- saved from url=({len(r['final_url']):04d}){r['final_url']} -->\n" + r["html"], encoding="utf-8")
                res["html"] = str(p)
                res["final_url"] = r["final_url"]
        time.sleep(0.3)
    finals = {v[0] for v in digests.values()}
    if len(finals) > 1 or len({v[1] for v in digests.values()}) > 1:
        res["cloaking"] = True
        res["notes"].append("cloaking suspected: different final URL/content per client profile")
    if not digests:
        res["notes"].append("page unreachable (dead domain or blocked)")
    if render:
        try:
            res.update(_render(url, out_dir))
        except Exception as exc:          # playwright not installed / browser missing
            res["notes"].append(f"render skipped: {str(exc)[:120]}")
    mp = out_dir / "capture_manifest.json"
    mp.write_text(json.dumps({"tool": "ftf.capture", "page_url": url, "final_url": res.get("final_url"),
                              "redirects": res["profiles"].get("fb_mobile", {}).get("chain"),
                              "cloaking": res.get("cloaking", False), "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S")},
                             ensure_ascii=False, indent=1))
    res["meta"].append(str(mp))
    return res


def _render(url: str, out_dir: Path) -> dict:
    from playwright.sync_api import sync_playwright

    har = out_dir / "page.har"
    shot = out_dir / "screenshot.png"
    dom = out_dir / "rendered.html"
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(user_agent=PROFILES["fb_mobile"]["User-Agent"], locale="pl-PL", viewport={"width": 412, "height": 915},
                            is_mobile=True, record_har_path=str(har), record_har_content="embed",
                            extra_http_headers={"Referer": "https://l.facebook.com/"})
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception:
            pass
        page.wait_for_timeout(1500)
        final = page.url
        dom.write_text(f"<!-- saved from url=({len(final):04d}){final} -->\n" + page.content(), encoding="utf-8")
        page.screenshot(path=str(shot), full_page=False)
        ctx.close()
        b.close()
    return {"har": str(har), "screenshot": str(shot), "html": str(dom), "final_url": final}
