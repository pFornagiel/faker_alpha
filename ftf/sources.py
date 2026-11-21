"""Public sources of suspicious ads and scam domains:

  cert_pl_new          CERT Polska warning list (hole.cert.pl) — ETag cached, delta by RegisterPositionId
  ms_adlib_search      Microsoft Ad Library REST API (keyless) — EEA ads incl. destination URL, PL=151
  google_atc_*         Google Ads Transparency Center internal RPC — advertiser/domain pivots (PL=2616)
  meta_api_search      Meta Ad Library Graph API `ads_archive` (needs META_ACCESS_TOKEN)
  meta_ad_media        Meta Ad Library creative by ad ID via yt-dlp `facebook:ads`
  linkedin_search      LinkedIn Ad Library (server-rendered HTML)

Every source records its latest status in `LAST_STATUS` so silent failures are never hidden.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import requests

from . import config
from .gazetteer import fold

log = logging.getLogger(__name__)

UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
}

DOMAIN_STEMS = [
    "invest", "inwest", "zysk", "orlen", "baltic", "pge", "krypto", "crypto", "bitcoin", "gield", "trade",
    "profit", "dochod", "zarob", "inpost", "paczk", "poczta", "brzosk", "lewandow", "kasyn", "casino",
    "bonus", "lotto", "nagrod", "zwrot", "podatk", "zus", "energa", "tauron", "fundusz", "akcj", "bank",
    "nbp", "knf", "gpw", "biedronk", "lidl", "rossmann", "zdrow", "kardio", "cukrzy", "stawy", "news", "info24",
]

# Short or ambiguous stems that must start on a domain/token boundary (e.g., avoid 'akcj' matching 'transakcja')
_BOUNDARY_STEMS = {"akcj", "bank", "pge", "zus", "nbp", "knf", "gpw", "lidl", "news", "zysk", "lotto", "bonus"}

# Latest execution status per source: {source: {"status": ..., "detail": ..., "count": ...}}
LAST_STATUS: dict[str, dict] = {}

_CERT_JSON_CACHE = config.CACHE / "cert_pl_domains.json"
_CERT_META_CACHE = config.CACHE / "cert_pl_domains.meta.json"


def _set_status(source: str, status: str, detail: str, count: int = 0) -> None:
    LAST_STATUS[source] = {"status": status, "detail": detail, "count": count}


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _match_domain_stems(domain: str, stems: list[str]) -> list[str]:
    """Match domain tokens against keyword stems without substring false positives like 'transakcja'."""
    folded = fold(domain).lower()
    hits: list[str] = []
    for raw_stem in stems:
        s = raw_stem.strip().lower()
        if not s:
            continue
        if len(s) <= 4 or s in _BOUNDARY_STEMS:
            # Require token/segment start boundary (start of domain or after '.', '-', '_', or digit)
            if re.search(rf"(?:^|[.\-_0-9]){re.escape(s)}", folded):
                hits.append(s)
        else:
            if s in folded:
                hits.append(s)
    return hits


def _http_error_status(code: int) -> str:
    if code == 429:
        return "rate_limited"
    if code in (401, 403, 999):
        return "blocked"
    return "error"


# ------------------------------------------------------------------ CERT Polska
def _fetch_cert_pl_json() -> list[dict]:
    """Download CERT Polska JSON feed with ETag / If-Modified-Since caching."""
    headers = dict(UA)
    meta: dict = {}
    if _CERT_META_CACHE.exists() and _CERT_JSON_CACHE.exists():
        try:
            meta = json.loads(_CERT_META_CACHE.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
        if meta.get("etag"):
            headers["If-None-Match"] = meta["etag"]
        if meta.get("last_modified"):
            headers["If-Modified-Since"] = meta["last_modified"]

    r = requests.get("https://hole.cert.pl/domains/v2/domains.json", headers=headers, timeout=(10.0, 120.0))
    if r.status_code == 304 and _CERT_JSON_CACHE.exists():
        return json.loads(_CERT_JSON_CACHE.read_text(encoding="utf-8"))

    r.raise_for_status()
    data = r.json()
    try:
        _atomic_write(_CERT_JSON_CACHE, r.text)
        new_meta = {
            "etag": r.headers.get("ETag"),
            "last_modified": r.headers.get("Last-Modified"),
        }
        _atomic_write(_CERT_META_CACHE, json.dumps(new_meta))
    except OSError as exc:
        log.debug("CERT PL cache write skipped: %s", exc)
    return data


def cert_pl_new(store, keywords: list[str] | None = None, limit: int = 200) -> list[dict]:
    """Return newly added CERT Polska domains matching scam stems/keywords since last watermark."""
    try:
        data = _fetch_cert_pl_json()
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else 0
        _set_status("cert_pl", _http_error_status(code), f"HTTP {code}: {exc}")
        log.warning("cert_pl_new HTTP error: %s", exc)
        raise
    except Exception as exc:
        _set_status("cert_pl", "error", str(exc)[:200])
        log.warning("cert_pl_new failed: %s", exc)
        raise

    last = int(store.get("cert_pl_last_id", 0) or 0)
    kw_stems = [tok for k in (keywords or []) for tok in re.split(r"\s+", fold(k)) if len(tok) >= 3]
    stems = list(dict.fromkeys(kw_stems + DOMAIN_STEMS))

    active_new = [d for d in data if int(d.get("RegisterPositionId", 0)) > last and not d.get("DeleteDate")]
    all_max_id = max((int(d.get("RegisterPositionId", 0)) for d in data), default=last)
    if all_max_id > last:
        store.put("cert_pl_last_id", all_max_id)

    if last == 0:
        # First run: scan only the newest 2000 active entries
        active_new = sorted(active_new, key=lambda d: -int(d["RegisterPositionId"]))[:2000]

    out: list[dict] = []
    for d in active_new:
        dom = d.get("DomainAddress", "")
        hits = _match_domain_stems(dom, stems)
        if hits:
            out.append(
                {
                    "source": "cert_pl",
                    "domain": dom,
                    "url": f"https://{dom}/",
                    "inserted": d.get("InsertDate"),
                    "id": d.get("RegisterPositionId"),
                    "match": hits[:4],
                }
            )
    result = out[:limit]
    _set_status("cert_pl", "ok", f"scanned {len(active_new)} new entries (watermark={all_max_id})", len(result))
    return result


# ------------------------------------------------------------------ Microsoft Ad Library
def ms_adlib_search(keyword: str, top: int = 25) -> list[dict]:
    """Query Microsoft Ad Library REST API for Poland (countryCodes=151)."""
    try:
        r = requests.get(
            "https://adlibrary.api.bingads.microsoft.com/api/v1/Ads",
            headers=UA,
            timeout=(5.0, 30.0),
            params={"searchText": keyword, "top": top, "skip": 0, "countryCodes": 151},
        )
        if r.status_code >= 400:
            _set_status("ms_adlib", _http_error_status(r.status_code), f"HTTP {r.status_code} for {keyword!r}")
            r.raise_for_status()
        js = r.json()
    except requests.HTTPError:
        raise
    except Exception as exc:
        _set_status("ms_adlib", "error", str(exc)[:200])
        log.warning("ms_adlib_search(%r) failed: %s", keyword, exc)
        raise

    rows = js.get("value", js if isinstance(js, list) else [])
    out: list[dict] = []
    for a in rows:
        assets = a.get("Assets") or a.get("AdAssets") or []
        out.append(
            {
                "source": "ms_adlib",
                "ad_id": a.get("AdId"),
                "advertiser": a.get("AdvertiserName"),
                "advertiser_id": a.get("AdvertiserId"),
                "title": a.get("Title"),
                "text": a.get("Description"),
                "display_url": a.get("DisplayUrl"),
                "url": a.get("DestinationUrl"),
                "assets": assets,
                "keyword": keyword,
            }
        )
    _set_status("ms_adlib", "ok", f"keyword={keyword!r}", len(out))
    return out


# ------------------------------------------------------------------ Google Ads Transparency Center
def _gatc(rpc: str, req: dict) -> dict:
    try:
        r = requests.post(
            f"https://adstransparency.google.com/anji/_/rpc/{rpc}?authuser=",
            timeout=(5.0, 30.0),
            headers={
                **UA,
                "content-type": "application/x-www-form-urlencoded",
                "origin": "https://adstransparency.google.com",
                "referer": "https://adstransparency.google.com/?region=PL",
            },
            data={"f.req": json.dumps(req, separators=(",", ":"))},
        )
        if r.status_code >= 400:
            _set_status("google_atc", _http_error_status(r.status_code), f"HTTP {r.status_code} on {rpc}")
            r.raise_for_status()
        return r.json()
    except requests.HTTPError:
        raise
    except Exception as exc:
        _set_status("google_atc", "error", str(exc)[:200])
        log.warning("Google ATC %s failed: %s", rpc, exc)
        raise


def google_atc_suggest(keyword: str) -> list[dict]:
    """Query Google Ads Transparency Center advertiser & domain suggestions."""
    js = _gatc("SearchService/SearchSuggestions", {"1": keyword, "2": 10, "3": 10})
    out: list[dict] = []
    for s in js.get("1", []):
        if "1" in s:
            a = s["1"]
            out.append(
                {
                    "source": "google_atc",
                    "kind": "advertiser",
                    "name": a.get("1"),
                    "advertiser_id": a.get("2"),
                    "country": a.get("3"),
                    "keyword": keyword,
                }
            )
        elif "2" in s:
            out.append({"source": "google_atc", "kind": "domain", "domain": s["2"].get("1"), "keyword": keyword})
    _set_status("google_atc", "ok", f"suggest keyword={keyword!r}", len(out))
    return out


def google_atc_creatives(domain: str | None = None, advertiser_id: str | None = None, n: int = 40) -> list[dict]:
    """Query Google Ads Transparency Center creatives for a domain or advertiser ID (PL=2616)."""
    flt: dict = {"12": {"1": domain or "", "2": True}, "8": [2616]}
    if advertiser_id:
        flt["13"] = {"1": [advertiser_id]}
    js = _gatc("SearchService/SearchCreatives", {"2": n, "3": flt, "7": {"1": 1, "2": 0, "3": 2616}})
    out: list[dict] = []
    for c in js.get("1", []):
        rend = json.dumps(c.get("3", {}))
        img = re.search(r"https://tpc\.googlesyndication\.com/archive/simgad/\d+", rend)
        out.append(
            {
                "source": "google_atc",
                "advertiser_id": c.get("1"),
                "creative_id": c.get("2"),
                "advertiser": c.get("12"),
                "domain": c.get("14"),
                "format": {1: "text", 2: "image", 3: "video"}.get(c.get("4")),
                "first_shown": (c.get("6") or {}).get("1") if isinstance(c.get("6"), dict) else c.get("6"),
                "image": img.group(0) if img else None,
            }
        )
    _set_status("google_atc", "ok", f"creatives domain={domain!r} adv={advertiser_id!r}", len(out))
    return out


# ------------------------------------------------------------------ Meta Ad Library
def meta_api_search(keyword: str, days: int = 7, limit: int = 50) -> list[dict]:
    """Query Meta Ad Library Graph API `ads_archive` (requires `META_ACCESS_TOKEN`)."""
    tok = os.environ.get("META_ACCESS_TOKEN")
    if not tok:
        _set_status("meta_api", "no_credentials", "META_ACCESS_TOKEN is not set", 0)
        log.info("meta_api_search skipped: META_ACCESS_TOKEN not configured")
        return []

    version = os.environ.get("META_GRAPH_VERSION", "v27.0").strip() or "v27.0"
    params = {
        "access_token": tok,
        "ad_reached_countries": "['PL']",
        "ad_type": "ALL",
        "ad_active_status": "ALL",
        "search_terms": keyword,
        "limit": limit,
        "ad_delivery_date_min": (dt.date.today() - dt.timedelta(days=days)).isoformat(),
        "fields": (
            "id,page_id,page_name,ad_creative_bodies,ad_creative_link_titles,"
            "ad_creative_link_captions,ad_creative_link_descriptions,"
            "ad_delivery_start_time,ad_snapshot_url,publisher_platforms,"
            "eu_total_reach,beneficiary_payers"
        ),
    }
    try:
        r = requests.get(f"https://graph.facebook.com/{version}/ads_archive", params=params, timeout=(10.0, 60.0))
        if r.status_code >= 400:
            _set_status("meta_api", _http_error_status(r.status_code), f"HTTP {r.status_code} ({version})")
            r.raise_for_status()
        rows = r.json().get("data", [])
    except requests.HTTPError:
        raise
    except Exception as exc:
        _set_status("meta_api", "error", str(exc)[:200])
        log.warning("meta_api_search(%r) failed: %s", keyword, exc)
        raise

    out: list[dict] = []
    for a in rows:
        out.append(
            {
                "source": "meta_api",
                "ad_id": a.get("id"),
                "advertiser": a.get("page_name"),
                "advertiser_id": a.get("page_id"),
                "title": " | ".join(a.get("ad_creative_link_titles") or []),
                "text": " | ".join(a.get("ad_creative_bodies") or []),
                "display_url": " | ".join(a.get("ad_creative_link_captions") or []),
                "started": a.get("ad_delivery_start_time"),
                "url": f"https://www.facebook.com/ads/library/?id={a.get('id')}",
                "snapshot_url": a.get("ad_snapshot_url"),
                "payers": a.get("beneficiary_payers"),
                "reach": a.get("eu_total_reach"),
                "keyword": keyword,
            }
        )
    _set_status("meta_api", "ok", f"keyword={keyword!r} ({version})", len(out))
    return out


def meta_ad_media(ad_id: str) -> Path | None:
    """Download an Ad Library creative (video + .info.json) via yt-dlp's `facebook:ads` extractor."""
    ad_id_str = str(ad_id).strip()
    if not re.fullmatch(r"\d{5,25}", ad_id_str):
        raise ValueError(f"Invalid Meta ad_id (expected 5-25 digits): {ad_id!r}")

    exe = shutil.which("yt-dlp") or str(Path(sys.executable).parent / "yt-dlp")
    if not Path(exe).exists() and not shutil.which("yt-dlp"):
        _set_status("meta_ad_media", "error", "yt-dlp executable not found", 0)
        log.warning("meta_ad_media(%s): yt-dlp not found", ad_id_str)
        return None

    out = config.ARTIFACTS / "meta_ads" / ad_id_str
    out.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            exe,
            "--write-info-json",
            "--no-progress",
            "--max-filesize",
            "100M",
            "-o",
            str(out / "%(title).60s [%(id)s].%(ext)s"),
            f"https://www.facebook.com/ads/library/?id={ad_id_str}",
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()[:300]
        log.warning("meta_ad_media(%s) failed (rc=%d): %s", ad_id_str, proc.returncode, err)
        _set_status("meta_ad_media", "error", f"yt-dlp rc={proc.returncode}: {err[:160]}", 0)
    files = list(out.iterdir())
    if files:
        _set_status("meta_ad_media", "ok", f"downloaded {len(files)} file(s) for {ad_id_str}", len(files))
        return out
    return None


# ------------------------------------------------------------------ LinkedIn Ad Library
def linkedin_search(keyword: str) -> list[dict]:
    """Query LinkedIn Ad Library public search page."""
    r = requests.get(
        "https://www.linkedin.com/ad-library/search",
        params={"keyword": keyword, "countries": "PL"},
        headers=UA,
        timeout=(5.0, 30.0),
    )
    if r.status_code in (403, 429, 999):
        msg = f"LinkedIn blocked ad-library search (HTTP {r.status_code})"
        _set_status("linkedin", "blocked", msg, 0)
        log.warning("%s for keyword=%r", msg, keyword)
        raise requests.HTTPError(msg, response=r)
    if r.status_code >= 400:
        _set_status("linkedin", "error", f"HTTP {r.status_code} for {keyword!r}", 0)
        r.raise_for_status()

    ids = list(dict.fromkeys(re.findall(r"/ad-library/detail/(\d+)", r.text)))[:10]
    out = [
        {"source": "linkedin", "ad_id": i, "url": f"https://www.linkedin.com/ad-library/detail/{i}", "keyword": keyword}
        for i in ids
    ]
    _set_status("linkedin", "ok", f"keyword={keyword!r}", len(out))
    return out
