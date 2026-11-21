#!/usr/bin/env python
"""Which signals link scam pages into campaigns? An empirical study on the harvested urlscan corpus.

Reads the case folders written by tools/harvest_urlscan.py (needs the keyed harvest: urlscan_result.json),
derives candidate linking features from the raw scan data, and scores each feature family against three
references it does not use itself: the same brand-masked page-title template, the same dedicated server IP
(outside CDNs and large clouds), and near-identical screenshots (pHash).

    python tools/research_corpus.py data/harvest/urlscan --out data/harvest/research.json

With --store it also replays the product's must-link rule on the same pages (FTF_STORE must point at the
store written by tools/ingest_parallel.py) and compares variants of that rule.

Nothing here feeds the product pipeline; it is evidence for deciding which features are worth adding.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ftf import web  # noqa: E402

HEXISH = re.compile(r"(?<![a-z])[0-9a-f]{8,}(?![a-z])|\d+", re.I)


def _ts(s: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def phash(path: Path):
    import cv2

    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None, True
    blank = float(img.std()) < 8.0
    low = cv2.dct(np.float32(cv2.resize(img, (32, 32), interpolation=cv2.INTER_AREA)))[:8, :8].flatten()
    return low > np.median(low[1:]), blank


TITLE_SEP = re.compile(r"\s[|—–]\s|\s-\s|\s?™\s?")
# Networks where one IP serves unrelated customers: a shared IP there says nothing about the operator.
SHARED_ASN = {"AS13335", "AS209242", "AS16509", "AS14618", "AS15169", "AS396982", "AS8075", "AS54113", "AS20940",
              "AS27647", "AS132203", "AS45102", "AS14061", "AS16276", "AS24940", "AS63949", "AS31898"}


def title_template(title: str, host: str) -> str:
    """Title with the brand masked: '<brand> | Official Website' -> 'official website'. '' when there is no template."""
    t = re.sub(r"\s+", " ", re.sub(r"\d+", "0", (title or "").lower())).strip()
    parts = TITLE_SEP.split(t, 1)
    if len(parts) == 2 and len(parts[1].strip()) >= 8:
        return parts[1].strip()
    for label in host.lower().split("."):
        if len(label) > 3 and label in t:
            return ""
    return t if len(t) >= 12 else ""


def path_template(url: str) -> str:
    from urllib.parse import urlparse

    p = urlparse(url).path
    return HEXISH.sub("#", p)[:120]


def load_case(folder: Path) -> dict | None:
    rp, mp = folder / "urlscan_result.json", folder / "capture_manifest.json"
    if not rp.exists() or not mp.exists():
        return None
    try:
        res, man = json.loads(rp.read_text()), json.loads(mp.read_text())
    except Exception:
        return None
    page, data, lists = res.get("page") or {}, res.get("data") or {}, res.get("lists") or {}
    host = (page.get("domain") or folder.name).lower()
    apex = web.registrable_domain(host)
    scan_t = _ts((res.get("task") or {}).get("time"))
    fam: dict[str, set[str]] = defaultdict(set)

    for r in data.get("requests") or []:
        req = (r.get("request") or {}).get("request") or {}
        rsp = r.get("response") or {}
        url = req.get("url") or ""
        if not url.startswith("http"):
            continue
        rhost = web.registrable_domain(url)
        full = url.split("/")[2].split(":")[0].lower()
        first = rhost == apex
        sha, rtype, size = rsp.get("hash"), (rsp.get("type") or "Other"), rsp.get("size") or 0
        if (r.get("request") or {}).get("primaryRequest") and sha:
            fam["doc_sha"].add(sha)
        if sha and size >= 512:
            kind = {"Script": "js", "Stylesheet": "css", "Image": "img", "Font": "font"}.get(rtype)
            if kind:
                fam[("fp_" if first else "tp_") + kind + "_sha"].add(sha)
            if "favicon" in url.lower() or url.lower().split("?")[0].endswith(".ico"):
                fam["favicon_sha"].add(sha)
        if first:
            if rtype in ("Script", "Stylesheet", "XHR", "Fetch"):
                fam["fp_path_tpl"].add(rtype[:3] + ":" + path_template(url))
        else:
            fam["tp_host"].add(full)
            fam["tp_reg"].add(rhost)
    for g in data.get("globals") or []:
        if g.get("prop"):
            fam["js_global"].add(g["prop"])
    for c in data.get("cookies") or []:
        if c.get("name"):
            fam["cookie_name"].add(HEXISH.sub("#", c["name"]))
    for i in data.get("identifiers") or []:
        fam["dom_id"].add(str(i))
    for n in data.get("inputNames") or []:
        fam["input_name"].add(str(n))
    for c in lists.get("certificates") or []:
        if c.get("subjectName") and web.registrable_domain(c["subjectName"].lstrip("*.")) == apex and c.get("validFrom"):
            fam["tls_issued_min"].add(str(int(c["validFrom"]) // 60))
    if page.get("ip"):
        fam["ip"].add(page["ip"])
        fam["ip24"].add(".".join(page["ip"].split(".")[:3]) if "." in page["ip"] else page["ip"][:19])
    if page.get("asn"):
        fam["asn"].add(page["asn"])
    tt = title_template(page.get("title") or man.get("title") or "", host)
    age = page.get("apexDomainAgeDays")
    if scan_t and isinstance(age, int) and age < 400:
        fam["reg_date"].add((scan_t - timedelta(days=age)).date().isoformat())
    fam["apex"].add(apex)
    return {
        "name": folder.name, "host": host, "apex": apex, "title": page.get("title") or "", "title_tpl": tt,
        "asn": page.get("asn") or "", "asnname": page.get("asnname") or "", "server": page.get("server") or "",
        "domain_age": age, "tls_age": page.get("tlsAgeDays"), "tls_issuer": page.get("tlsIssuer") or "",
        "cert_t": _ts(man.get("cert_pl_inserted")), "scan_t": scan_t,
        "brand": (res.get("visible") or {}).get("brandname") or "",
        "fam": {k: v for k, v in fam.items()}, "shot": folder / "screenshot.png",
    }


KIT_FAMILIES = ("fp_path_tpl", "js_global", "cookie_name", "tp_host", "fp_js_sha", "fp_css_sha", "favicon_sha", "input_name")


class UF:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int) -> None:
        self.p[self.find(a)] = self.find(b)

    def groups(self) -> list[list[int]]:
        g = defaultdict(list)
        for i in range(len(self.p)):
            g[self.find(i)].append(i)
        return sorted(g.values(), key=len, reverse=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--out", default="")
    ap.add_argument("--hamming", type=int, default=6)
    ap.add_argument("--store", action="store_true", help="also replay the pipeline's must-link rule on FTF_STORE")
    ap.add_argument("--pipeline-sample", type=int, default=0,
                    help="with --store: run the product's full clustering on this many random pages per rule variant")
    a = ap.parse_args()

    cases = [c for c in (load_case(p) for p in sorted(Path(a.root).iterdir()) if p.is_dir()) if c]
    N = len(cases)
    apex = np.array([c["apex"] for c in cases])
    iu = np.triu(np.ones((N, N), bool), 1) & (apex[:, None] != apex[None, :])
    n_pairs = int(iu.sum())
    print(f"pages with full scan data: {N} | distinct registrable domains: {len(set(apex))} | pairs: {n_pairs}")

    # ---- references: evidence a feature family does not use itself ------------------------------------
    ttl = np.array([c["title_tpl"] for c in cases])
    has_t = ttl != ""
    TTL = (ttl[:, None] == ttl[None, :]) & has_t[:, None] & has_t[None, :] & iu
    ips = np.array([next(iter(c["fam"].get("ip", {""}))) for c in cases])
    ded = np.array([bool(ip) and c["asn"] not in SHARED_ASN for ip, c in zip(ips, cases)])
    DIP = (ips[:, None] == ips[None, :]) & ded[:, None] & ded[None, :] & iu
    bits, okv = [], []
    for c in cases:
        b, blank = phash(c["shot"]) if c["shot"].exists() else (None, True)
        okv.append(b is not None and not blank)
        bits.append(b if b is not None else np.zeros(64, bool))
    B, okv = np.array(bits), np.array(okv)
    both = okv[:, None] & okv[None, :]
    VIS = np.zeros((N, N), bool)
    for s in range(0, N, 256):
        VIS[s:s + 256] = (B[s:s + 256, None, :] != B[None, :, :]).sum(-1) <= a.hamming
    VIS &= both & iu
    refs = {"title": TTL, "ip": DIP, "visual": VIS}
    print(f"templated titles: {int(has_t.sum())} pages | dedicated IPs: {int(ded.sum())} pages | non-blank screenshots: {int(okv.sum())}")
    print("reference pairs: " + ", ".join(f"{k} {int(v.sum())} ({v.sum() / n_pairs:.4f} of all pairs)" for k, v in refs.items()))
    for x, y in (("title", "ip"), ("ip", "title"), ("title", "visual"), ("ip", "visual")):
        den = refs[x] & (both if y == "visual" else True)
        print(f"  P({y} same | {x} same) = {(refs[x] & refs[y]).sum() / max(den.sum(), 1):.2f}")

    def score(M: np.ndarray) -> dict:
        n = int(M.sum())
        return {"pairs": n,
                "p_title": round(float((M & TTL).sum() / max(n, 1)), 3), "p_ip": round(float((M & DIP).sum() / max(n, 1)), 3),
                "p_any": round(float((M & (TTL | DIP)).sum() / max(n, 1)), 3),
                "p_vis": round(float((M & VIS).sum() / max((M & both).sum(), 1)), 3),
                "r_title": round(float((M & TTL).sum() / max(TTL.sum(), 1)), 3), "r_ip": round(float((M & DIP).sum() / max(DIP.sum(), 1)), 3),
                "pages": int((M | M.T).any(1).sum())}

    # ---- feature families -----------------------------------------------------------------------------
    families = sorted({k for c in cases for k in c["fam"]} - {"apex"})
    inv: dict[str, dict[str, list[int]]] = {f: defaultdict(list) for f in families}
    for i, c in enumerate(cases):
        for f, vals in c["fam"].items():
            if f in inv:
                for v in vals:
                    inv[f][v].append(i)
    dfs = {f: {v: len({apex[h] for h in hs}) for v, hs in inv[f].items()} for f in families}

    report: dict = {"n_pages": N, "families": {}, "top_values": {}}
    cap = max(10, N // 50)
    print(f"\nFAMILY SCORES: two pages are linked when they share a value held by 2..{cap} domains (2 % of the corpus).")
    print("P_* = share of linked pairs confirmed by a reference; R_* = share of that reference's pairs found.")
    print(f"{'family':<15}{'cover':>6}{'values':>8}{'shared':>7}{'pairs':>8}{'P_title':>8}{'P_ip':>6}{'P_any':>6}{'P_vis':>6}{'R_title':>8}{'R_ip':>6}{'pages':>6}")
    for f in families:
        M = np.zeros((N, N), bool)
        for v, hs in inv[f].items():
            if 2 <= dfs[f][v] <= cap:
                idx = np.array(hs)
                M[np.ix_(idx, idx)] = True
        M = (M | M.T) & iu
        sc = score(M)
        sc.update(coverage=round(sum(1 for c in cases if c["fam"].get(f)) / N, 3), values=len(dfs[f]),
                  shared_values=sum(1 for d in dfs[f].values() if d >= 2))
        report["families"][f] = sc
        print(f"{f:<15}{sc['coverage']:>6.2f}{sc['values']:>8}{sc['shared_values']:>7}{sc['pairs']:>8}{sc['p_title']:>8.2f}{sc['p_ip']:>6.2f}"
              f"{sc['p_any']:>6.2f}{sc['p_vis']:>6.2f}{sc['r_title']:>8.2f}{sc['r_ip']:>6.2f}{sc['pages']:>6}")

    # ---- kit fingerprint: IDF-weighted Jaccard over everything a kit leaves behind -----------------------
    tok_df: Counter = Counter()
    toks: list[set[str]] = []
    for c in cases:
        t = {f"{f}:{v}" for f in KIT_FAMILIES for v in c["fam"].get(f, ())}
        toks.append(t)
        tok_df.update(t)
    vocab = {t: i for i, t in enumerate(sorted(t for t, d in tok_df.items() if d >= 2))}
    idf = np.array([np.log(N / tok_df[t]) for t in vocab], dtype=np.float32)
    X = np.zeros((N, len(vocab)), dtype=np.float32)
    for i, t in enumerate(toks):
        for x in t:
            if x in vocab:
                X[i, vocab[x]] = 1.0
    W = X * idf
    inter = W @ X.T
    tot = W.sum(1)
    KIT = inter / np.maximum(tot[:, None] + tot[None, :] - inter, 1e-9)
    n_tok = X.sum(1)
    enough = (n_tok >= 5)[:, None] & (n_tok >= 5)[None, :]
    print(f"\nKIT FINGERPRINT: IDF-weighted Jaccard over {', '.join(KIT_FAMILIES)}")
    print(f"vocabulary {len(vocab)} shared tokens; pages with >= 5 tokens: {int((n_tok >= 5).sum())}")
    print(f"{'threshold':<10}{'pairs':>8}{'P_title':>8}{'P_ip':>6}{'P_any':>6}{'P_vis':>6}{'R_title':>8}{'R_ip':>6}{'pages':>6}")
    report["kit"] = {}
    for th in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
        sc = score((KIT >= th) & enough & iu)
        report["kit"][str(th)] = sc
        print(f"{th:<10}{sc['pairs']:>8}{sc['p_title']:>8.2f}{sc['p_ip']:>6.2f}{sc['p_any']:>6.2f}{sc['p_vis']:>6.2f}{sc['r_title']:>8.2f}{sc['r_ip']:>6.2f}{sc['pages']:>6}")

    th = 0.6
    uf = UF(N)
    M = (KIT >= th) & enough & iu
    for i, j in zip(*np.nonzero(M)):
        uf.union(int(i), int(j))
    comps = [g for g in uf.groups() if len(g) >= 2]
    print(f"\nKIT FAMILIES at similarity >= {th} (average linkage would split further; this is the connected view): "
          f"{len(comps)} families covering {sum(map(len, comps))} of {N} pages")
    print(f"{'pages':>6}{'IPs':>5}{'ded.IP':>7}{'ASNs':>5}{'titles':>7}{'P_vis':>6}  typical title | top networks | distinctive tokens")
    report["kit_families"] = []
    for g in comps[:18]:
        idx = np.array(g)
        sub = np.triu(np.ones((len(g), len(g)), bool), 1)
        pv = (VIS | VIS.T)[np.ix_(idx, idx)][sub].sum() / max(both[np.ix_(idx, idx)][sub].sum(), 1)
        ipset = {ips[i] for i in g}
        dipset = {ips[i] for i in g if ded[i]}
        asn = Counter(cases[i]["asnname"][:22] for i in g).most_common(3)
        tt = Counter(cases[i]["title"][:44] for i in g)
        tpl = Counter(ttl[i] for i in g if ttl[i]).most_common(1)
        common = Counter(x for i in g for x in toks[i] if x in vocab)
        sig = [t for t, n in sorted(common.items(), key=lambda kv: (-(kv[1] / len(g)) * np.log(N / tok_df[kv[0]]))) if n >= 0.8 * len(g)][:4]
        row = {"pages": len(g), "ips": len(ipset), "dedicated_ips": len(dipset), "asns": len({cases[i]["asn"] for i in g}),
               "distinct_titles": len(tt), "p_vis": round(float(pv), 2), "title_template": tpl[0][0] if tpl else "",
               "example_titles": [t for t, _ in tt.most_common(3)], "networks": asn, "signature": sig,
               "domains": [cases[i]["name"] for i in g][:12],
               "cert_listed": sorted({str(cases[i]["cert_t"])[:10] for i in g if cases[i]["cert_t"]})[:1] +
                              sorted({str(cases[i]["cert_t"])[:10] for i in g if cases[i]["cert_t"]})[-1:]}
        tld = Counter(cases[i]["apex"].rsplit(".", 1)[-1] for i in g).most_common(1)[0]
        slds = [cases[i]["apex"].split(".")[0] for i in g]
        row["top_tld"] = f".{tld[0]} {tld[1] / len(g):.0%}"
        row["name_len_median"] = int(np.median([len(x) for x in slds]))
        row["names_with_digit_or_hyphen"] = round(sum(1 for x in slds if re.search(r"[\d-]", x)) / len(g), 2)
        report["kit_families"].append(row)
        print(f"{len(g):>6}{len(ipset):>5}{len(dipset):>7}{row['asns']:>5}{len(tt):>7}{pv:>6.2f}  "
              f"{(tpl[0][0] if tpl else tt.most_common(1)[0][0])[:40]!r} | {[f'{n} x{k}' for n, k in asn]} | {[s[:46] for s in sig]}")

    fam_of = {}
    for k, g in enumerate(comps):
        for i in g:
            fam_of[i] = k
    print("\nDOMAIN NAMES PER KIT FAMILY (top TLD, median name length, share of names with a digit or hyphen) and TLD concentration")
    for k, row in enumerate(report["kit_families"][:12]):
        print(f"  family {k + 1:>2} ({row['pages']:>3} pages): {row['top_tld']:<12} len {row['name_len_median']:>2}  digit/hyphen {row['names_with_digit_or_hyphen']:.2f}  e.g. {row['domains'][:4]}")
    tld_all = Counter(c["apex"].rsplit(".", 1)[-1] for c in cases)
    report["tld"] = []
    for t, n in tld_all.most_common(12):
        fams = Counter(fam_of.get(i, -1) for i, c in enumerate(cases) if c["apex"].endswith("." + t))
        top, k = fams.most_common(1)[0]
        report["tld"].append({"tld": t, "pages": n, "largest_family_share": round(k / n, 2), "family": top + 1 if top >= 0 else None})
        print(f"  .{t:<8} {n:>4} pages; {k / n:.0%} in one kit family" + (f" (family {top + 1})" if top >= 0 else " (unlinked)"))

    # ---- most shared values: public library or kit signature? --------------------------------------------
    print("\nMOST SHARED VALUES (domains holding it; share of holder pairs confirmed by title / dedicated IP)")
    for f in ("tp_host", "js_global", "cookie_name", "fp_path_tpl", "fp_js_sha", "favicon_sha", "ip", "tls_issued_min"):
        rows = []
        for v, hs in sorted(inv[f].items(), key=lambda kv: -dfs[f][kv[0]])[:200]:
            if dfs[f][v] < 3:
                continue
            idx = np.array(hs)
            sub = iu[np.ix_(idx, idx)] | iu[np.ix_(idx, idx)].T
            sub = np.triu(sub, 1)
            n = max(int(sub.sum()), 1)
            pt = ((TTL | TTL.T)[np.ix_(idx, idx)] & sub).sum() / n
            pi = ((DIP | DIP.T)[np.ix_(idx, idx)] & sub).sum() / n
            rows.append({"value": v[:64], "domains": dfs[f][v], "p_title": round(float(pt), 2), "p_ip": round(float(pi), 2),
                         "titles": [f"{t} x{k}" for t, k in Counter(cases[h]["title"][:30] for h in hs).most_common(2)]})
        report["top_values"][f] = rows[:50]
        print(f"[{f}]")
        for r in rows[:9]:
            print(f"  {r['domains']:>4}  P_title {r['p_title']:.2f}  P_ip {r['p_ip']:.2f}  {r['value']:<50} {r['titles']}")

    # ---- time proximity ------------------------------------------------------------------------------
    print("\nTIME PROXIMITY: share of pairs within the gap that are in the same kit family (kit) / confirmed by title or dedicated IP (ref)")
    ANY = TTL | DIP
    fam_id = np.array([fam_of.get(i, -1 - i) for i in range(N)])
    SAMEFAM = (fam_id[:, None] == fam_id[None, :]) & iu
    base = ANY.sum() / n_pairs
    base_kit = SAMEFAM.sum() / n_pairs
    for label, key in (("CERT listing", "cert_t"), ("TLS issuance", "tls"), ("urlscan scan", "scan_t")):
        if key == "tls":
            ts = np.array([min(map(int, c["fam"]["tls_issued_min"])) if c["fam"].get("tls_issued_min") else np.nan for c in cases], dtype=float)
        else:
            ts = np.array([c[key].timestamp() / 60 if c[key] else np.nan for c in cases])
        gap = np.abs(ts[:, None] - ts[None, :])
        out, prev = [], -1.0
        for g_ in (1, 10, 60, 1440):
            m = (gap <= g_) & (gap > prev) & iu
            out.append(f"<= {g_} min: {int(m.sum())} pairs, kit {(m & SAMEFAM).sum() / max(m.sum(), 1):.2f} ref {(m & ANY).sum() / max(m.sum(), 1):.2f}")
            prev = g_
        report.setdefault("time", {})[label] = out
        print(f"  {label:<13} " + " | ".join(out) + f" | all pairs: kit {base_kit:.3f} ref {base:.3f}")
    batches = [(v, sorted({apex[h]: h for h in hs}.values())) for v, hs in inv.get("tls_issued_min", {}).items() if dfs["tls_issued_min"][v] >= 2]
    pure = [len({fam_id[i] for i in g}) == 1 for _, g in batches]
    sizes = sorted((len(g) for _, g in batches), reverse=True)
    report["tls_batches"] = {"batches": len(batches), "one_kit_family": int(sum(pure)), "sizes": sizes[:15],
                             "pages_in_batches": int(sum(sizes))}
    print(f"  certificates issued in the same minute for >= 2 domains: {len(batches)} batches covering {sum(sizes)} pages; "
          f"{sum(pure)} batches fall entirely inside one kit family; sizes {sizes[:12]}")

    # ---- shared-hosting names -------------------------------------------------------------------------
    by_apex = defaultdict(list)
    for i, c in enumerate(cases):
        by_apex[c["apex"]].append(i)
    shared = [{"apex": ax, "hosts": len(ix), "generic_in_pipeline": web.is_generic(ax),
               "titles": [t for t, _ in Counter(cases[h]["title"][:30] for h in ix).most_common(3)]}
              for ax, ix in sorted(by_apex.items(), key=lambda kv: -len(kv[1])) if len(ix) >= 2]
    report["shared_apex"] = shared
    print("\nSEVERAL LISTED HOSTS UNDER ONE REGISTRABLE DOMAIN (shared hosting the pipeline treats as one landing domain)")
    for s in shared[:15]:
        print(f"  {s['hosts']:>4}  generic={str(s['generic_in_pipeline']):<5} {s['apex']:<26} {s['titles']}")

    # ---- corpus profile -------------------------------------------------------------------------------
    ages = [c["domain_age"] for c in cases if isinstance(c["domain_age"], int)]
    prof = {
        "domain_age_days_quantiles_10_25_50_75_90": [int(x) for x in np.quantile(ages, [0.1, 0.25, 0.5, 0.75, 0.9])] if ages else [],
        "share_domain_age_le_7d": round(sum(1 for x in ages if x <= 7) / max(len(ages), 1), 2),
        "top_networks": Counter(c["asnname"][:36] for c in cases).most_common(10),
        "top_title_templates": Counter(t[:46] for t in ttl if t).most_common(14),
        "top_brands_seen_by_urlscan": Counter(c["brand"] for c in cases if c["brand"]).most_common(12),
        "blank_or_missing_screenshots": int((~okv).sum()),
    }
    report["profile"] = prof
    print("\nCORPUS PROFILE")
    for k, v in prof.items():
        print(f"  {k}: {v}")

    # ---- the product's must-link rule on the same pages ---------------------------------------------------
    if a.store:
        from ftf import similarity
        from ftf.store import Store

        items = Store().all()
        by_name = {c["name"]: i for i, c in enumerate(cases)}
        mids = [(m, by_name[f.get("name")]) for m, (f, _) in items.items() if f.get("name") in by_name]
        print(f"\nPIPELINE MUST-LINK REPLAY on {len(mids)} ingested pages (one shared counted identifier joins two pages; "
              f"joins are transitive)")
        raw = {m: similarity.identifiers(items[m][0]) for m, _ in mids}
        third_party = {"flagcdn.com", "ipapi.co", "frankfurter.dev", "vimeocdn.com", "tradingview.com", "tradingview-widget.com"}

        def replay(label: str, keep, max_df: float, abs_cap: int = 0) -> None:
            n = len(mids)
            df: Counter = Counter()
            held = {}
            for m, _ in mids:
                held[m] = {gv for gv, types in raw[m].items() if keep(gv, types)}
                df.update(held[m])
            pos = {m: k for k, (m, _) in enumerate(mids)}
            u = UF(n)
            first: dict = {}
            for m, _ in mids:
                for gv in held[m]:
                    d = df[gv]
                    if d >= 2 and (d <= 2 or (d / n <= max_df and (not abs_cap or d <= abs_cap))):
                        if gv in first:
                            u.union(pos[m], first[gv])
                        else:
                            first[gv] = pos[m]
            groups = u.groups()
            M = np.zeros((N, N), bool)
            for g in groups:
                if len(g) >= 2:
                    idx = np.array([mids[k][1] for k in g])
                    M[np.ix_(idx, idx)] = True
            M = (M | M.T) & iu
            sc = score(M)
            sc.update(label=label, largest=len(groups[0]), largest_share=round(len(groups[0]) / n, 3),
                      groups=sum(1 for g in groups if len(g) >= 2), singletons=sum(1 for g in groups if len(g) == 1))
            report.setdefault("mustlink_replay", []).append(sc)
            print(f"  {label:<58} largest {len(groups[0]):>5} ({len(groups[0]) / n:>4.0%}) groups {sc['groups']:>4} single {sc['singletons']:>5} "
                  f"| pairs {sc['pairs']:>7} P_title {sc['p_title']:.2f} P_ip {sc['p_ip']:.2f} P_any {sc['p_any']:.2f} R_title {sc['r_title']:.2f} R_ip {sc['r_ip']:.2f}")

        everything = lambda gv, types: True                                                    # noqa: E731
        no_3p_host = lambda gv, types: not (gv[0] == "domains" and types <= {"page_host"})      # noqa: E731
        no_platform = lambda gv, types: no_3p_host(gv, types) and not (                         # noqa: E731
            gv[0] == "kit_files" and ("/cdn-cgi/" in gv[1] or "/.events/" in gv[1])) and gv[0] != "product" and not (
            gv[0] == "contacts" and re.search(r"ejemplo|example|email\.com|domain\.|test@", gv[1]))
        replay("current rule (MAX_DF 0.5)", everything, 0.5)
        replay("current rule, MAX_DF 0.05", everything, 0.05)
        replay("current rule, value held by <= 10 pages", everything, 1.0, 10)
        replay("without hosts seen only as third-party resources", no_3p_host, 0.5)
        replay("+ without platform endpoints, product words, placeholders", no_platform, 0.5)
        replay("+ and value held by <= 2 % of pages", no_platform, 0.02)

        if a.pipeline_sample:
            from ftf import cluster

            rng = np.random.default_rng(1)
            pick = [mids[k] for k in sorted(rng.choice(len(mids), size=min(a.pipeline_sample, len(mids)), replace=False))]
            sub = {m: items[m] for m, _ in pick}
            row_of = dict(pick)
            S = np.zeros(N, bool)
            S[list(row_of.values())] = True
            inS = S[:, None] & S[None, :] & iu
            kit_loose, kit_tight = (KIT >= 0.3) & enough & inS, (KIT >= 0.6) & enough & inS
            orig_ids, orig_counted = similarity.identifiers, similarity.counted
            print(f"\nPRODUCT CLUSTERING on a random {len(sub)}-page sample (must-link + content views + average linkage), per rule variant")
            print("P_kit = share of grouped pairs that also share a kit fingerprint (>= 0.3); R_kit = share of strong kit pairs (>= 0.6) grouped")

            def run(label: str, keep, max_df: float) -> None:
                similarity.identifiers = lambda f: {gv: t for gv, t in orig_ids(f).items() if keep(gv, t)}
                similarity.counted = lambda df, n: df <= 2 or df / max(1, n) <= max_df
                try:
                    cl = cluster.build(sub)
                finally:
                    similarity.identifiers, similarity.counted = orig_ids, orig_counted
                for level in ("campaigns", "families"):
                    groups = [g["members"] if isinstance(g, dict) else g for g in cl[level]]
                    M = np.zeros((N, N), bool)
                    for g in groups:
                        if len(g) >= 2:
                            idx = np.array([row_of[m] for m in g])
                            M[np.ix_(idx, idx)] = True
                    M = (M | M.T) & inS
                    n = max(int(M.sum()), 1)
                    sizes = sorted(map(len, groups), reverse=True)
                    row = {"label": label, "level": level, "largest": sizes[0], "groups": sum(1 for x in sizes if x >= 2),
                           "singletons": sum(1 for x in sizes if x == 1), "pairs": int(M.sum()),
                           "p_kit": round(float((M & kit_loose).sum() / n), 3),
                           "r_kit": round(float((M & kit_tight).sum() / max(kit_tight.sum(), 1)), 3),
                           "p_any": round(float((M & (TTL | DIP)).sum() / n), 3),
                           "r_title": round(float((M & TTL).sum() / max((TTL & inS).sum(), 1)), 3),
                           "r_ip": round(float((M & DIP).sum() / max((DIP & inS).sum(), 1)), 3), "top_sizes": sizes[:8]}
                    report.setdefault("product_clustering", []).append(row)
                    print(f"  {label:<44} {level:<9} largest {sizes[0]:>4} groups {row['groups']:>4} single {row['singletons']:>4} | "
                          f"P_kit {row['p_kit']:.2f} R_kit {row['r_kit']:.2f} P_any {row['p_any']:.2f} R_title {row['r_title']:.2f} R_ip {row['r_ip']:.2f} | {sizes[:6]}")

            run("current rule", everything, 0.5)
            run("no third-party hosts / platform endpoints", no_platform, 0.5)
            run("same, value held by <= 2 % of pages", no_platform, 0.02)
            run("content views only (no identifiers)", lambda gv, types: False, 0.5)

    if a.out:
        Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str))
        print(f"\nwritten {a.out}")


if __name__ == "__main__":
    main()
