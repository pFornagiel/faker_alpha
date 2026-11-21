"""Public domain/infrastructure metadata (online, cached): RDAP (registrar, creation date, nameservers),
DNS (A/NS/MX), certificate transparency (crt.sh), CERT Polska warning-list membership.

Linking indicators produced (see research/02 §6 for strength rationale):
  ns_pair     Cloudflare/hosting nameserver pair (per-account at Cloudflare)         weak-medium
  registrar   registrar name                                                          very weak (context only)
  reg_burst   registrar + NS pair + creation day  (registration burst of one operator) strong-medium
Disable with FTF_ENRICH=0 (offline demo).
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from functools import lru_cache

import requests

from . import config

log = logging.getLogger(__name__)
CACHE = config.CACHE / "enrich"
CACHE.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "FakeTrace/0.1 (research prototype)"}
ENABLED = os.environ.get("FTF_ENRICH", "1") != "0"


def _cached(domain: str) -> dict | None:
    f = CACHE / f"{domain}.json"
    if f.exists() and time.time() - f.stat().st_mtime < 7 * 86400:
        return json.loads(f.read_text())
    return None


def rdap(domain: str) -> dict:
    try:
        r = requests.get(f"https://rdap.org/domain/{domain}", headers=UA, timeout=12, allow_redirects=True)
        if r.status_code != 200:
            return {"status": r.status_code}
        d = r.json()
    except Exception as exc:
        return {"error": str(exc)[:120]}
    ev = {e.get("eventAction"): e.get("eventDate") for e in d.get("events", [])}
    registrar = None
    for ent in d.get("entities", []):
        if "registrar" in (ent.get("roles") or []):
            v = ent.get("vcardArray", [None, []])[1]
            registrar = next((x[3] for x in v if x and x[0] == "fn"), None) or ent.get("handle")
    return {"registrar": registrar, "created": ev.get("registration"), "expires": ev.get("expiration"),
            "updated": ev.get("last changed"), "nameservers": sorted(n.get("ldhName", "").lower() for n in d.get("nameservers", [])),
            "status": d.get("status")}


def dns(domain: str) -> dict:
    out = {}
    try:
        import dns.resolver

        res = dns.resolver.Resolver()
        res.lifetime = 6
        for rt in ("A", "NS", "MX"):
            try:
                out[rt] = sorted(str(x).rstrip(".").lower() for x in res.resolve(domain, rt))
            except Exception:
                out[rt] = []
    except Exception as exc:
        out["error"] = str(exc)[:100]
    return out


def crtsh(domain: str) -> dict:
    try:
        r = requests.get("https://crt.sh/", params={"q": domain, "output": "json"}, headers=UA, timeout=15)
        rows = r.json() if r.status_code == 200 else []
    except Exception:
        return {}
    if not rows:
        return {"n_certs": 0}
    first = min(rows, key=lambda x: x.get("not_before", "9"))
    sans = set()
    for x in rows:
        sans.update(n.lower() for n in (x.get("name_value") or "").split("\n") if n)
    return {"n_certs": len(rows), "first_cert": first.get("not_before"), "issuer": first.get("issuer_name", "")[:80],
            "san_names": sorted(sans)[:30]}


@lru_cache(maxsize=1)
def _cert_pl() -> set[str]:
    f = CACHE / "_cert_pl_domains.txt"
    if not f.exists() or time.time() - f.stat().st_mtime > 6 * 3600:
        try:
            r = requests.get("https://hole.cert.pl/domains/v2/domains.txt", headers=UA, timeout=60)
            r.raise_for_status()
            f.write_text(r.text)
        except Exception:
            return set()
    return set(f.read_text().split())


def enrich_domain(domain: str) -> dict:
    if not ENABLED or not domain or "." not in domain:
        return {}
    c = _cached(domain)
    if c is not None:
        return c
    d = {"domain": domain, "rdap": rdap(domain), "dns": dns(domain), "crtsh": crtsh(domain),
         "cert_pl_listed": domain in _cert_pl()}
    (CACHE / f"{domain}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1))
    return d


def indicators(info: dict) -> dict[str, set]:
    out: dict[str, set] = {}
    r = info.get("rdap") or {}
    ns = r.get("nameservers") or (info.get("dns") or {}).get("NS") or []
    if ns:
        pair = "+".join(sorted(ns)[:2])
        generic = all(re.search(r"(domaincontrol|registrar-servers|dyna-ns|porkbun|name\.com|nicenic|hostinger|dnsowl|namebrightdns|share-dns|dns\.(com|net)|parkingcrew|awsdns|googledomains|"
                                r"ns\d?\.(hostinger|ovh|cyberfolks|home\.pl|nazwa\.pl))", n) for n in ns[:2])
        if not generic:
            out["ns_pair"] = {pair}
        if r.get("registrar") and r.get("created"):
            out["reg_burst"] = {f"{r['registrar'][:40]}|{pair}|{r['created'][:10]}"}
    if r.get("registrar"):
        out["registrar"] = {r["registrar"][:60]}
    return out
