"""Harvest historical urlscan.io scans of domains from the CERT Polska warning list into case folders.

Why: scam landing pages live for hours, but urlscan.io keeps the scan made while they were alive (rendered DOM,
screenshot, every request with its response hash, IP/ASN, TLS data). This turns the label-free CERT list
(~126k domains) into a research corpus that the normal pipeline can ingest (`python -m ftf.cli ingest <out>`).

Only the documented public API is used, rate-limit headers are honoured, and the run is resumable.
Works without a key (lower quotas); set URLSCAN_API_KEY to raise them.

    python tools/harvest_urlscan.py --limit 2000 --stride 35     # spread over the whole 6-month list
    python tools/harvest_urlscan.py --limit 500 --include-phishing

Per case (folder name = listed domain):
    page.html              rendered DOM, prefixed with a Chrome-style "saved from url" marker
    screenshot.png         urlscan screenshot
    network.har            minimal HAR rebuilt from the scan's request list (no bodies; `_sha256` per response)
    capture_manifest.json  page_url / final_url / title / captured_at / redirects (read by ftf.ingest.read_meta)
    dns_ssl.json           hostname, ip, asn, server, TLS issuer/validity
    urlscan_result.json    raw result (hashes, JS globals, cookies, links, certificates) for feature research
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
CERT_URL = "https://hole.cert.pl/domains/v2/domains.json"
API = "https://urlscan.io"
UA = "scam-campaign-research/0.1 (python-requests)"

# The CERT list mixes ad-driven scams with marketplace / courier / bank credential phishing. Those are a
# different phenomenon (no ad, no celebrity, no landing-page funnel), so they are skipped by default.
PHISHING_STEMS = (
    "allegro", "olx", "vinted", "inpost", "dpd", "dhl", "poczta", "pocztex", "pekao", "pko", "ipko", "mbank",
    "santander", "ing-", "blik", "facebook", "booking", "otomoto", "sprzedajemy", "alebilet", "bilet", "paczk",
    "kurier", "przesyl", "platnosc", "payu", "przelew", "netflix", "spotify", "orange", "t-mobile", "e-toll",
    "etoll", "podatk", "mandat", "gov-", "-gov", "epuap", "profil-zaufany", "oferta", "dostaw", "odbior",
    "status-id", "millennium", "alior", "bnp", "credit-agricole", "revolut", "paypal", "apple", "icloud",
)


def env_or_dotenv(name: str) -> str:
    """Read a setting from the environment, else from the repo's .env (KEY=value lines)."""
    val = os.environ.get(name, "").strip()
    env_file = ROOT / ".env"
    if not val and env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            k, sep, v = line.strip().removeprefix("export ").partition("=")
            if sep and k.strip() == name:
                val = v.strip().strip("'\"")
    return val


class Client:
    def __init__(self) -> None:
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        key = env_or_dotenv("URLSCAN_API_KEY")
        if key:
            self.s.headers["API-Key"] = key
        self.authenticated = bool(key)

    def get(self, url: str, quota: bool = True, **kw) -> requests.Response | None:
        """GET with rate-limit handling. Returns None on 404/410 or after repeated failures."""
        for attempt in range(6):
            try:
                r = self.s.get(url, timeout=(10, 60), **kw)
            except requests.RequestException as exc:
                print(f"  [net] {type(exc).__name__}: retry {attempt + 1}", flush=True)
                time.sleep(2 + attempt * 3)
                continue
            if r.status_code == 429:
                wait = float(r.headers.get("X-Rate-Limit-Reset-After", 30)) + 1
                print(f"  [429] quota reached ({r.headers.get('X-Rate-Limit-Window')}); sleeping {wait:.0f}s", flush=True)
                time.sleep(min(wait, 3700))
                continue
            if r.status_code in (404, 410):
                return None
            if r.status_code >= 500:
                time.sleep(3 + attempt * 3)
                continue
            if quota and r.headers.get("X-Rate-Limit-Remaining") == "0":
                time.sleep(float(r.headers.get("X-Rate-Limit-Reset-After", 2)) + 0.5)
            return r
        return None


def cert_domains(cache: Path) -> list[dict]:
    if cache.exists() and time.time() - cache.stat().st_mtime < 6 * 3600:
        data = json.loads(cache.read_text(encoding="utf-8"))
    else:
        r = requests.get(CERT_URL, headers={"User-Agent": UA}, timeout=(10, 180))
        r.raise_for_status()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(r.text, encoding="utf-8")
        data = r.json()
    act = [d for d in data if d.get("DomainAddress")]
    act.sort(key=lambda d: -int(d.get("RegisterPositionId", 0)))
    return act


def looks_like_phishing(domain: str) -> bool:
    d = domain.lower()
    return any(s in d for s in PHISHING_STEMS)


def reg_domain(host: str) -> str:
    """Cheap registrable-domain approximation (last two labels) - enough to spot off-domain bounces."""
    parts = (host or "").lower().strip(".").split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else (host or "").lower()


def search_batch(cl: Client, domains: list[str]) -> list[dict]:
    q = "task.domain:(" + " OR ".join(f'"{d}"' for d in domains) + ")"
    r = cl.get(f"{API}/api/v1/search/", params={"q": q, "size": 100})
    if r is None or r.status_code != 200:
        print(f"  [search] failed: {None if r is None else r.status_code}", flush=True)
        return []
    return r.json().get("results", [])


def pick_scan(hits: list[dict], domain: str) -> dict | None:
    """Earliest scan that returned a 2xx document on the listed domain (the page as served while alive)."""
    good = []
    for h in hits:
        page = h.get("page", {})
        status = str(page.get("status", ""))
        if not status.startswith("2"):
            continue
        if reg_domain(page.get("domain", "")) != reg_domain(domain):
            continue      # bounced to google.com / a parking page / a white page elsewhere
        good.append(h)
    good.sort(key=lambda h: h.get("task", {}).get("time", ""))
    return good[0] if good else None


def to_har(result: dict) -> dict:
    entries = []
    for rq in result.get("data", {}).get("requests", []):
        req = (rq.get("request") or {}).get("request") or {}
        rsp_outer = rq.get("response") or {}
        rsp = rsp_outer.get("response") or {}
        url = req.get("url", "")
        if not url.startswith("http"):
            continue
        redir = (rq.get("request") or {}).get("redirectResponse")
        if redir:      # the hop that led here
            entries.append({
                "request": {"url": redir.get("url", ""), "method": "GET"},
                "response": {"status": redir.get("status", 302),
                             "headers": [{"name": k, "value": str(v)} for k, v in (redir.get("headers") or {}).items()],
                             "content": {"mimeType": ""}, "redirectURL": url},
                "serverIPAddress": redir.get("remoteIPAddress", ""),
            })
        entries.append({
            "request": {"url": url, "method": req.get("method", "GET")},
            "response": {"status": rsp.get("status", 0),
                         "headers": [{"name": k, "value": str(v)} for k, v in (rsp.get("headers") or {}).items()],
                         "content": {"mimeType": rsp.get("mimeType", "")}},
            "serverIPAddress": rsp.get("remoteIPAddress", ""),
            "_sha256": rsp_outer.get("hash", ""),
            "_size": rsp_outer.get("size", 0),
        })
    page_url = result.get("page", {}).get("url", "")
    return {"log": {"version": "1.2", "creator": {"name": "urlscan.io result -> HAR", "version": "0.1"},
                    "pages": [{"title": page_url}], "entries": entries}}


def _complete(case: Path) -> bool:
    mf = case / "capture_manifest.json"
    if not mf.exists():
        return False
    try:
        return not json.loads(mf.read_text(encoding="utf-8")).get("partial")
    except ValueError:
        return False


def save_case(cl: Client, out: Path, domain: str, hit: dict, cert_row: dict) -> str:
    """Write one case folder. Without an API key only the screenshot and search metadata are available
    (`partial: true` in the manifest); a later run with a key upgrades the case with DOM + request list."""
    uuid = hit["_id"]
    case = out / re.sub(r"[^a-zA-Z0-9._-]", "_", domain)
    if _complete(case):
        return "exists"
    had_partial = (case / "capture_manifest.json").exists()
    page, task = hit.get("page", {}), hit.get("task", {})
    result, html = None, ""
    if cl.authenticated:
        r = cl.get(f"{API}/api/v1/result/{uuid}/")
        if r is not None and r.status_code == 200:
            result = r.json()
            page, task = result.get("page", page), result.get("task", task)
            dom = cl.get(f"{API}/dom/{uuid}/", quota=False)
            html = dom.text if dom is not None and dom.status_code == 200 else ""
    partial = result is None or len(html) < 400
    if partial and had_partial:
        return "still_partial"
    url = page.get("url") or task.get("url") or f"https://{domain}/"
    case.mkdir(parents=True, exist_ok=True)
    if not (case / "screenshot.png").exists():
        shot = cl.get(f"{API}/screenshots/{uuid}.png", quota=False)
        if shot is not None and shot.status_code == 200 and len(shot.content) > 2000:
            (case / "screenshot.png").write_bytes(shot.content)
    redirects: list[str] = []
    if not partial:
        (case / "page.html").write_text(f"<!-- saved from url=({len(url):04d}){url} -->\n{html}", encoding="utf-8")
        har = to_har(result)
        (case / "network.har").write_text(json.dumps(har), encoding="utf-8")
        (case / "urlscan_result.json").write_text(json.dumps(result), encoding="utf-8")
        redirects = [e["request"]["url"] for e in har["log"]["entries"] if 300 <= (e["response"]["status"] or 0) < 400]
    (case / "dns_ssl.json").write_text(json.dumps({
        "hostname": page.get("domain"), "ip": page.get("ip"), "asn": page.get("asn"), "asnname": page.get("asnname"),
        "country": page.get("country"), "server": page.get("server"), "tls_issuer": page.get("tlsIssuer"),
        "tls_valid_from": page.get("tlsValidFrom"), "tls_valid_days": page.get("tlsValidDays"),
        "tls_age_days": page.get("tlsAgeDays"), "apex_domain": page.get("apexDomain"),
    }, ensure_ascii=False), encoding="utf-8")
    manifest = {
        "tool": "urlscan.io", "page_url": task.get("url") or url, "final_url": url, "title": page.get("title"),
        "captured_at": task.get("time"), "redirects": redirects[:20], "urlscan_uuid": uuid,
        "urlscan_report": f"{API}/result/{uuid}/", "listed_domain": domain,
        "cert_pl_id": cert_row.get("RegisterPositionId"), "cert_pl_inserted": cert_row.get("InsertDate"),
        "source": "CERT Polska warning list (hole.cert.pl) + urlscan.io public scan",
    }
    if partial:
        manifest["partial"] = True       # screenshot + metadata only; rerun with URLSCAN_API_KEY to complete
    (case / "capture_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return "partial" if partial else ("upgraded" if had_partial else "saved")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=2000, help="stop after this many saved cases")
    ap.add_argument("--max-domains", type=int, default=30000, help="how many CERT domains to query at most")
    ap.add_argument("--skip", type=int, default=0, help="skip the newest N CERT domains")
    ap.add_argument("--stride", type=int, default=1, help="take every N-th CERT domain (spreads the sample over "
                    "the 6-month list instead of one listing burst, which is usually a single kit family)")
    ap.add_argument("--batch", type=int, default=15, help="domains per search query")
    ap.add_argument("--out", default=str(ROOT / "data" / "harvest" / "urlscan"))
    ap.add_argument("--include-phishing", action="store_true", help="keep marketplace/courier/bank phishing domains")
    a = ap.parse_args()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "_search_hits.jsonl").touch()
    hits_log = (out / "_search_hits.jsonl").open("a", encoding="utf-8")
    done_path = out / "_queried_domains.txt"
    queried = set(done_path.read_text().split()) if done_path.exists() else set()
    done_log = done_path.open("a", encoding="utf-8")

    cl = Client()
    rows = cert_domains(ROOT / "data" / "cache" / "cert_pl_domains.json")
    cert_by_dom = {r["DomainAddress"].lower(): r for r in rows}
    cand = [r for r in rows if a.include_phishing or not looks_like_phishing(r["DomainAddress"])]
    print(f"CERT domains: {len(rows)}; after phishing filter: {len(cand)}; api key: {cl.authenticated}", flush=True)
    doms = [r["DomainAddress"] for r in cand[a.skip::a.stride][:a.max_domains] if r["DomainAddress"] not in queried]

    # hits already collected by earlier runs
    grouped: dict[str, list[dict]] = {}
    hits_path = out / "_search_hits.jsonl"
    for line in hits_path.read_text(encoding="utf-8").splitlines():
        try:
            h = json.loads(line)
        except ValueError:
            continue
        grouped.setdefault((h.get("task", {}).get("domain") or "").lower(), []).append(h)
    picks = {d: p for d, hs in grouped.items() if d in cert_by_dom and (p := pick_scan(hs, d))}
    print(f"usable scans known from earlier runs: {len(picks)}", flush=True)

    # ---- phase 1: search until enough usable scans are known
    t0 = time.time()
    seen = {"no_scan": 0, "no_usable_scan": 0}
    for i in range(0, len(doms), a.batch):
        if len(picks) >= a.limit:
            break
        batch = doms[i:i + a.batch]
        new: dict[str, list[dict]] = {}
        for h in search_batch(cl, batch):
            hits_log.write(json.dumps({k: h.get(k) for k in ("_id", "task", "page", "stats")}, ensure_ascii=False) + "\n")
            new.setdefault((h.get("task", {}).get("domain") or "").lower(), []).append(h)
        hits_log.flush()
        for d in batch:
            hs = new.get(d.lower(), [])
            p = pick_scan(hs, d) if hs else None
            if p:
                picks[d.lower()] = p
            else:
                seen["no_usable_scan" if hs else "no_scan"] += 1
            done_log.write(d + "\n")
        done_log.flush()
        if (i // a.batch) % 20 == 0:
            print(f"[search {time.time() - t0:5.0f}s] queried {i + len(batch)}/{len(doms)} | usable {len(picks)} | {seen}", flush=True)
    print(f"search done: usable scans {len(picks)} | {seen}", flush=True)

    # ---- phase 2: download (screenshot always; DOM + request list when a key is set)
    stats: dict[str, int] = {}
    for n, (d, hit) in enumerate(list(picks.items())[:a.limit]):
        res = save_case(cl, out, d, hit, cert_by_dom[d])
        stats[res] = stats.get(res, 0) + 1
        if n % 100 == 0:
            print(f"[fetch {time.time() - t0:5.0f}s] {n + 1}/{min(len(picks), a.limit)} | {stats}", flush=True)
    print(f"done: {stats}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
