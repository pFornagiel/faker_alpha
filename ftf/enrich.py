"""Public domain/infrastructure OSINT enrichment (online, cached):
  Step 1. RDAP via IANA RFC 9224 bootstrap (with rdap.org fallback)
  Step 2. DNS (A / NS / MX) with short timeouts
  Step 3. Certificate Transparency via crt.sh (errors distinguished from 0 certs)
  Step 4. CERT Polska warning-list membership (atomic cache, stale fallback, parent-domain match)
  Step 5. Smart caching (7d for valid results, 15m negative TTL for transient/partial errors)
  Step 6. Linking indicators (`ns_pair`, `reg_burst` — only for non-generic NS pairs)
  Step 7. Concurrent batch enrichment (`enrich_domains`)

Disable dynamically at any time via `FTF_ENRICH=0`.
"""
from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import re
import threading
import time
from pathlib import Path

import requests

from . import config

log = logging.getLogger(__name__)

CACHE = config.CACHE / "enrich"
CACHE.mkdir(parents=True, exist_ok=True)
BOOTSTRAP_FILE = config.CACHE / "rdap_bootstrap.json"
CERT_PL_FILE = CACHE / "_cert_pl_domains.txt"

FULL_TTL_S = 7 * 86_400
PARTIAL_TTL_S = 900            # 15 minutes for transient/partial errors (e.g., crt.sh 503)
BOOTSTRAP_TTL_S = 7 * 86_400
CERT_PL_TTL_S = 6 * 3_600

UA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}
RDAP_HEADERS = {
    **UA_HEADERS,
    "Accept": "application/rdap+json, application/json;q=0.9",
}

GENERIC_NS_RX = re.compile(
    r"(?:"
    r"dyna-ns\.net|registrar-servers\.com|domaincontrol\.com|dns-parking\.com|hostinger|"
    r"registrar\.eu|ovh\.net|wixdns\.net|vercel-dns\.com|azure-dns|digitalocean\.com|"
    r"hetzner|sedoparking|bodis|parkingcrew|namecheaphosting|awsdns|googledomains|"
    r"linode|vultr|nsone\.net|dnsmadeeasy|"
    r"porkbun|name\.com|nicenic|dnsowl|namebrightdns|share-dns|dns\.(?:com|net)|"
    r"cyberfolks|home\.pl|nazwa\.pl"
    r")",
    re.I,
)

_BOOTSTRAP_LOCK = threading.Lock()
_BOOTSTRAP_CACHE: tuple[float, dict[str, str]] | None = None

_CERT_LOCK = threading.Lock()
_CERT_CACHE: tuple[float, set[str]] | None = None


def is_enabled() -> bool:
    """Evaluate `FTF_ENRICH` dynamically so tests/callers can toggle it without re-importing."""
    return os.environ.get("FTF_ENRICH", "1") != "0"


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _normalize_registrar(name: str | None) -> str:
    if not name:
        return ""
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def _safe_domain_filename(domain: str) -> Path:
    safe = re.sub(r"[^a-z0-9._-]", "_", domain.rstrip(".").lower())
    return CACHE / f"{safe}.json"


# ------------------------------------------------------------------ Step 1: RDAP (RFC 9224 bootstrap)
def _load_rdap_bootstrap() -> dict[str, str]:
    """Load IANA DNS RDAP bootstrap map (`tld -> base_url`), cached 7 days with stale fallback."""
    global _BOOTSTRAP_CACHE
    with _BOOTSTRAP_LOCK:
        need_refresh = (
            not BOOTSTRAP_FILE.exists()
            or (time.time() - BOOTSTRAP_FILE.stat().st_mtime) > BOOTSTRAP_TTL_S
        )
        if need_refresh:
            try:
                r = requests.get("https://data.iana.org/rdap/dns.json", headers=UA_HEADERS, timeout=(5.0, 15.0))
                r.raise_for_status()
                _atomic_write_text(BOOTSTRAP_FILE, r.text)
            except Exception as exc:
                log.debug("IANA RDAP bootstrap refresh failed: %s", exc)
                if not BOOTSTRAP_FILE.exists():
                    return {}

        try:
            mtime = BOOTSTRAP_FILE.stat().st_mtime
            if _BOOTSTRAP_CACHE is not None and _BOOTSTRAP_CACHE[0] == mtime:
                return _BOOTSTRAP_CACHE[1]
            data = json.loads(BOOTSTRAP_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            log.debug("IANA RDAP bootstrap read failed: %s", exc)
            return {}

        mapping: dict[str, str] = {}
        for entry in data.get("services", []):
            if not isinstance(entry, list) or len(entry) < 2:
                continue
            tlds, urls = entry[0], entry[1]
            if not urls:
                continue
            base = next((u for u in urls if str(u).startswith("https://")), urls[0])
            base = str(base).rstrip("/") + "/"
            for tld in tlds:
                mapping[str(tld).lower().lstrip(".")] = base
        _BOOTSTRAP_CACHE = (mtime, mapping)
        return mapping


def _rdap_urls_for_domain(domain: str) -> list[str]:
    dom = domain.rstrip(".").lower()
    tld = dom.rsplit(".", 1)[-1] if "." in dom else ""
    urls: list[str] = []
    bootstrap = _load_rdap_bootstrap()
    if tld and tld in bootstrap:
        urls.append(f"{bootstrap[tld]}domain/{dom}")
    fallback = f"https://rdap.org/domain/{dom}"
    if fallback not in urls:
        urls.append(fallback)
    return urls


def rdap(domain: str) -> dict:
    """Fetch RDAP record via authoritative IANA-bootstrapped server (with `rdap.org` fallback)."""
    dom = (domain or "").rstrip(".").lower()
    if not dom or "." not in dom:
        return {"error": "invalid domain"}

    last_error: str | None = None
    last_status: int | None = None
    data: dict | None = None
    used_url: str | None = None

    for url in _rdap_urls_for_domain(dom):
        try:
            r = requests.get(url, headers=RDAP_HEADERS, timeout=(5.0, 12.0), allow_redirects=True)
            last_status = r.status_code
            if r.status_code == 200:
                data = r.json()
                used_url = url
                break
            if r.status_code == 404:
                return {"status": 404, "rdap_url": url}
            if r.status_code == 429:
                return {"error": "HTTP 429", "status": 429, "rdap_url": url}
            last_error = f"HTTP {r.status_code}"
        except Exception as exc:
            last_error = str(exc)[:120]

    if data is None:
        out: dict = {"error": last_error or f"HTTP {last_status}"}
        if last_status is not None:
            out["status"] = last_status
        return out

    events = {e.get("eventAction"): e.get("eventDate") for e in data.get("events", []) if isinstance(e, dict)}
    registrar: str | None = None
    registrar_iana_id: str | None = None

    for ent in data.get("entities", []):
        if not isinstance(ent, dict) or "registrar" not in (ent.get("roles") or []):
            continue
        vcard = ent.get("vcardArray")
        if isinstance(vcard, list) and len(vcard) >= 2 and isinstance(vcard[1], list):
            registrar = next((x[3] for x in vcard[1] if isinstance(x, list) and len(x) >= 4 and x[0] == "fn"), None)
        if not registrar:
            registrar = ent.get("handle")
        for pid in ent.get("publicIds") or []:
            if isinstance(pid, dict) and "iana" in str(pid.get("type", "")).lower() and pid.get("identifier"):
                registrar_iana_id = str(pid["identifier"]).strip()
                break
        if registrar or registrar_iana_id:
            break

    nameservers = sorted(
        {
            str(ns.get("ldhName", "")).rstrip(".").lower()
            for ns in (data.get("nameservers") or [])
            if isinstance(ns, dict) and ns.get("ldhName")
        }
    )

    return {
        "registrar": registrar,
        "registrar_norm": _normalize_registrar(registrar),
        "registrar_iana_id": registrar_iana_id,
        "created": events.get("registration"),
        "expires": events.get("expiration"),
        "updated": events.get("last changed") or events.get("last update of RDAP database"),
        "nameservers": nameservers,
        "status": data.get("status"),
        "rdap_url": used_url,
    }


# ------------------------------------------------------------------ Step 2: DNS
def dns(domain: str) -> dict:
    """Resolve A, NS, and MX records with short timeouts."""
    dom = (domain or "").rstrip(".").lower()
    out: dict = {}
    try:
        import dns.resolver

        resolver = dns.resolver.Resolver()
        resolver.timeout = 2.0
        resolver.lifetime = 4.0
        for rtype in ("A", "NS", "MX"):
            try:
                answers = resolver.resolve(dom, rtype)
                out[rtype] = sorted({str(x).rstrip(".").lower() for x in answers})
            except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
                out[rtype] = []
            except Exception as exc:
                out[rtype] = []
                out.setdefault("errors", {})[rtype] = str(exc)[:100]
    except Exception as exc:
        out["error"] = str(exc)[:100]
    return out


# ------------------------------------------------------------------ Step 3: crt.sh
def crtsh(domain: str) -> dict:
    """Query crt.sh certificate transparency logs, distinguishing errors from genuine empty results."""
    dom = (domain or "").rstrip(".").lower()
    try:
        r = requests.get("https://crt.sh/", params={"q": dom, "output": "json"}, headers=UA_HEADERS, timeout=(5.0, 12.0))
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}"}
        rows = r.json()
        if not isinstance(rows, list):
            return {"error": "unexpected response format"}
    except Exception as exc:
        return {"error": str(exc)[:120]}

    if not rows:
        return {"n_certs": 0}

    first = min(rows, key=lambda x: x.get("not_before") or "9")
    sans: set[str] = set()
    for row in rows:
        for name in (row.get("name_value") or "").splitlines():
            clean = name.strip().lower()
            if clean:
                sans.add(clean)
    return {
        "n_certs": len(rows),
        "first_cert": first.get("not_before"),
        "issuer": str(first.get("issuer_name") or "")[:80],
        "san_names": sorted(sans)[:30],
    }


# ------------------------------------------------------------------ Step 4: CERT Polska
def _cert_pl() -> set[str]:
    """Load CERT Polska warning-list domains using an mtime-checked cache, atomic writes, and stale fallback."""
    global _CERT_CACHE
    with _CERT_LOCK:
        need_refresh = (
            not CERT_PL_FILE.exists()
            or (time.time() - CERT_PL_FILE.stat().st_mtime) > CERT_PL_TTL_S
        )
        if need_refresh:
            try:
                r = requests.get("https://hole.cert.pl/domains/v2/domains.txt", headers=UA_HEADERS, timeout=(5.0, 45.0))
                r.raise_for_status()
                _atomic_write_text(CERT_PL_FILE, r.text)
            except Exception as exc:
                log.warning("CERT Polska domain list refresh failed (using stale cache if available): %s", exc)
                if not CERT_PL_FILE.exists():
                    return set()

        try:
            mtime = CERT_PL_FILE.stat().st_mtime
            if _CERT_CACHE is not None and _CERT_CACHE[0] == mtime:
                return _CERT_CACHE[1]
            domains = {line.strip().lower() for line in CERT_PL_FILE.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()}
            _CERT_CACHE = (mtime, domains)
            return domains
        except Exception as exc:
            log.warning("Failed reading CERT Polska cache: %s", exc)
            return set()


def is_cert_pl_listed(domain: str) -> bool:
    """Return True if `domain` or any parent domain (e.g. `bad.pl` for `sub.bad.pl`) is on CERT Polska."""
    listed = _cert_pl()
    if not listed or not domain:
        return False
    parts = domain.rstrip(".").lower().split(".")
    for i in range(len(parts) - 1):
        candidate = ".".join(parts[i:])
        if candidate in listed:
            return True
    return False


# ------------------------------------------------------------------ Step 5: Caching & single-domain enrichment
def _has_transient_error(info: dict) -> bool:
    r = info.get("rdap") or {}
    d = info.get("dns") or {}
    c = info.get("crtsh") or {}
    if "error" in r or r.get("status") in (429, 500, 502, 503, 504):
        return True
    if "error" in d or "errors" in d:
        return True
    if "error" in c:
        return True
    return False


def _cached(domain: str) -> dict | None:
    f = _safe_domain_filename(domain)
    if not f.exists():
        return None
    try:
        age = time.time() - f.stat().st_mtime
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None
    ttl = PARTIAL_TTL_S if data.get("_partial") or _has_transient_error(data) else FULL_TTL_S
    return data if age < ttl else None


def enrich_domain(domain: str, force: bool = False) -> dict:
    """Collect RDAP, DNS, crt.sh, and CERT Polska signals for one domain (with TTL caching)."""
    dom = (domain or "").rstrip(".").lower()
    if not is_enabled() or not dom or "." not in dom:
        return {}
    if not force:
        cached = _cached(dom)
        if cached is not None:
            return cached

    info = {
        "domain": dom,
        "rdap": rdap(dom),
        "dns": dns(dom),
        "crtsh": crtsh(dom),
        "cert_pl_listed": is_cert_pl_listed(dom),
    }
    if _has_transient_error(info):
        info["_partial"] = True
    try:
        _atomic_write_text(_safe_domain_filename(dom), json.dumps(info, ensure_ascii=False, indent=1))
    except OSError as exc:
        log.debug("Failed writing enrich cache for %s: %s", dom, exc)
    return info


# ------------------------------------------------------------------ Step 6: Linking indicators
def indicators(info: dict) -> dict[str, set]:
    """Derive domain-infrastructure linking indicators (`ns_pair`, `reg_burst`).

    Only emits `ns_pair` and `reg_burst` when the nameserver pair is non-generic (e.g., an
    account-scoped Cloudflare pair), preventing false links across unrelated domains parked at
    generic registrar/hosting nameservers.
    """
    out: dict[str, set] = {}
    if not info:
        return out
    r = info.get("rdap") or {}
    raw_ns = r.get("nameservers") or (info.get("dns") or {}).get("NS") or []
    ns = sorted({str(n).rstrip(".").lower() for n in raw_ns if n})
    if ns:
        top2 = ns[:2]
        pair = "+".join(top2)
        generic = all(bool(GENERIC_NS_RX.search(n)) for n in top2)
        if not generic:
            out["ns_pair"] = {pair}
            reg_norm = r.get("registrar_norm") or _normalize_registrar(r.get("registrar"))
            created = str(r.get("created") or "")[:10]
            if reg_norm and created:
                out["reg_burst"] = {f"{reg_norm[:40]}|{pair}|{created}"}
    return out


# ------------------------------------------------------------------ Step 7: Concurrent enrichment
def enrich_domains(domains: list[str], max_workers: int = 4, force: bool = False) -> dict[str, dict]:
    """Enrich multiple domains concurrently with a bounded thread pool."""
    if not is_enabled():
        return {}
    clean = list(dict.fromkeys(d.rstrip(".").lower() for d in domains if d and "." in d))
    if not clean:
        return {}
    workers = max(1, min(max_workers, len(clean)))
    results: dict[str, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(enrich_domain, d, force): d for d in clean}
        for fut in concurrent.futures.as_completed(futs):
            dom = futs[fut]
            try:
                results[dom] = fut.result()
            except Exception as exc:
                log.warning("enrich_domains failed for %s: %s", dom, exc)
                results[dom] = {"domain": dom, "error": str(exc)[:120]}
    return results
