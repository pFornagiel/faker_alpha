"""Public sources of suspicious ads / domains (all endpoints verified live 2026-11-21, see research/01).

  cert_pl_new          CERT Polska warning list (hole.cert.pl) — delta by RegisterPositionId, keyword filter
  ms_adlib_search      Microsoft Ad Library REST API (keyless) — EEA ads incl. destination URL, PL=151
  google_atc_*         Google Ads Transparency Center internal RPC — advertiser/domain pivots (PL=2616)
  meta_api_search      Meta Ad Library Graph API `ads_archive` (needs META_ACCESS_TOKEN — see README)
  meta_ad_media        Meta Ad Library creative by ad ID via yt-dlp `facebook:ads` (how the organisers got case 5)
  linkedin_search      LinkedIn Ad Library (server-rendered HTML)
Low volume by design (one request per keyword per run), descriptive UA, no logins, no CAPTCHA bypass.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

import requests

from . import config
from .gazetteer import fold

log = logging.getLogger(__name__)
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"}
DOMAIN_STEMS = ["invest", "inwest", "zysk", "orlen", "baltic", "pge", "krypto", "crypto", "bitcoin", "gield", "trade",
                "profit", "dochod", "zarob", "inpost", "paczk", "poczta", "brzosk", "lewandow", "kasyn", "casino",
                "bonus", "lotto", "nagrod", "zwrot", "podatk", "zus", "energa", "tauron", "fundusz", "akcj", "bank",
                "nbp", "knf", "gpw", "biedronk", "lidl", "rossmann", "zdrow", "kardio", "cukrzy", "stawy", "news", "info24"]


def cert_pl_new(store, keywords: list[str] | None = None, limit: int = 200) -> list[dict]:
    r = requests.get("https://hole.cert.pl/domains/v2/domains.json", headers=UA, timeout=120)
    r.raise_for_status()
    data = r.json()
    last = int(store.get("cert_pl_last_id", 0) or 0)
    stems = [fold(k) for k in (keywords or [])] + DOMAIN_STEMS
    new = [d for d in data if int(d.get("RegisterPositionId", 0)) > last and not d.get("DeleteDate")]
    if new:
        store.put("cert_pl_last_id", max(int(d["RegisterPositionId"]) for d in new))
    if last == 0:                                    # first run: only look at the newest entries
        new = sorted(new, key=lambda d: -int(d["RegisterPositionId"]))[:2000]
    out = []
    for d in new:
        dom = d.get("DomainAddress", "")
        hits = [s for s in stems if s and s in fold(dom)]
        if hits:
            out.append({"source": "cert_pl", "domain": dom, "url": f"https://{dom}/", "inserted": d.get("InsertDate"),
                        "id": d.get("RegisterPositionId"), "match": hits[:4]})
    return out[:limit]


def ms_adlib_search(keyword: str, top: int = 25) -> list[dict]:
    r = requests.get("https://adlibrary.api.bingads.microsoft.com/api/v1/Ads", headers=UA, timeout=30,
                     params={"searchText": keyword, "top": top, "skip": 0, "countryCodes": 151})
    r.raise_for_status()
    js = r.json()
    rows = js.get("value", js if isinstance(js, list) else [])
    out = []
    for a in rows:
        out.append({"source": "ms_adlib", "ad_id": a.get("AdId"), "advertiser": a.get("AdvertiserName"),
                    "title": a.get("Title"), "text": a.get("Description"), "display_url": a.get("DisplayUrl"),
                    "url": a.get("DestinationUrl"), "keyword": keyword})
    return out


def _gatc(rpc: str, req: dict) -> dict:
    r = requests.post(f"https://adstransparency.google.com/anji/_/rpc/{rpc}?authuser=", timeout=30,
                      headers={**UA, "content-type": "application/x-www-form-urlencoded",
                               "origin": "https://adstransparency.google.com",
                               "referer": "https://adstransparency.google.com/?region=PL"},
                      data={"f.req": json.dumps(req, separators=(",", ":"))})
    r.raise_for_status()
    return r.json()


def google_atc_suggest(keyword: str) -> list[dict]:
    js = _gatc("SearchService/SearchSuggestions", {"1": keyword, "2": 10, "3": 10})
    out = []
    for s in js.get("1", []):
        if "1" in s:
            a = s["1"]
            out.append({"source": "google_atc", "kind": "advertiser", "name": a.get("1"), "advertiser_id": a.get("2"),
                        "country": a.get("3"), "keyword": keyword})
        elif "2" in s:
            out.append({"source": "google_atc", "kind": "domain", "domain": s["2"].get("1"), "keyword": keyword})
    return out


def google_atc_creatives(domain: str | None = None, advertiser_id: str | None = None, n: int = 40) -> list[dict]:
    flt = {"12": {"1": domain or "", "2": True}, "8": [2616]}
    if advertiser_id:
        flt["13"] = {"1": [advertiser_id]}
    js = _gatc("SearchService/SearchCreatives", {"2": n, "3": flt, "7": {"1": 1, "2": 0, "3": 2616}})
    out = []
    for c in js.get("1", []):
        rend = json.dumps(c.get("3", {}))
        img = re.search(r"https://tpc\.googlesyndication\.com/archive/simgad/\d+", rend)
        out.append({"source": "google_atc", "advertiser_id": c.get("1"), "creative_id": c.get("2"),
                    "advertiser": c.get("12"), "domain": c.get("14"), "format": {1: "text", 2: "image", 3: "video"}.get(c.get("4")),
                    "first_shown": (c.get("6") or {}).get("1") if isinstance(c.get("6"), dict) else c.get("6"),
                    "image": img.group(0) if img else None})
    return out


def meta_api_search(keyword: str, days: int = 7, limit: int = 50) -> list[dict]:
    tok = os.environ.get("META_ACCESS_TOKEN")
    if not tok:
        return []
    import datetime as dt

    params = {"access_token": tok, "ad_reached_countries": "['PL']", "ad_type": "ALL", "ad_active_status": "ALL",
              "search_terms": keyword, "limit": limit,
              "ad_delivery_date_min": (dt.date.today() - dt.timedelta(days=days)).isoformat(),
              "fields": "id,page_id,page_name,ad_creative_bodies,ad_creative_link_titles,ad_creative_link_captions,"
                        "ad_creative_link_descriptions,ad_delivery_start_time,ad_snapshot_url,publisher_platforms,"
                        "eu_total_reach,beneficiary_payers"}
    r = requests.get("https://graph.facebook.com/v27.0/ads_archive", params=params, timeout=60)
    r.raise_for_status()
    out = []
    for a in r.json().get("data", []):
        out.append({"source": "meta_api", "ad_id": a.get("id"), "advertiser": a.get("page_name"), "advertiser_id": a.get("page_id"),
                    "title": " | ".join(a.get("ad_creative_link_titles") or []), "text": " | ".join(a.get("ad_creative_bodies") or []),
                    "display_url": " | ".join(a.get("ad_creative_link_captions") or []), "started": a.get("ad_delivery_start_time"),
                    "url": f"https://www.facebook.com/ads/library/?id={a.get('id')}", "payers": a.get("beneficiary_payers"),
                    "reach": a.get("eu_total_reach"), "keyword": keyword})
    return out


def meta_ad_media(ad_id: str) -> Path | None:
    """Download an Ad Library creative (video + .info.json) with yt-dlp's facebook:ads extractor."""
    exe = shutil.which("yt-dlp") or str(Path(os.sys.executable).parent / "yt-dlp")
    if not Path(exe).exists() and not shutil.which("yt-dlp"):
        return None
    out = config.ARTIFACTS / "meta_ads" / str(ad_id)
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run([exe, "--write-info-json", "--no-progress", "-o", str(out / "%(title).60s [%(id)s].%(ext)s"),
                    f"https://www.facebook.com/ads/library/?id={ad_id}"], capture_output=True, timeout=300)
    return out if any(out.iterdir()) else None


def linkedin_search(keyword: str) -> list[dict]:
    r = requests.get("https://www.linkedin.com/ad-library/search", params={"keyword": keyword, "countries": "PL"},
                     headers=UA, timeout=30)
    ids = list(dict.fromkeys(re.findall(r"/ad-library/detail/(\d+)", r.text)))[:10]
    return [{"source": "linkedin", "ad_id": i, "url": f"https://www.linkedin.com/ad-library/detail/{i}", "keyword": keyword} for i in ids]
