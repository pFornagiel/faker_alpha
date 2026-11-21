"""Built-in scheduler: periodically scans ad libraries and warning lists, scores suspicion,
and optionally captures + analyses new items against known campaigns (open-set assignment).

    python -m ftf.scheduler --once [--analyse]      # single run (cron-friendly)
    python -m ftf.scheduler --every 30              # foreground loop every 30 min
    python -m ftf.scheduler --once --watch          # + campaign watch (pivot on known campaigns' identifiers)

Campaign watch (`watch_campaigns`): for already-detected campaigns, the campaign's own counted identifiers
(registrable domains, advertiser IDs, product names — the values similarity.counted() treats as linking) are used
as search seeds in public sources (pivoting on shared identifiers, Starov et al. 2018). A hit is only a lead:
it is linked to the campaign only if the normal capture -> engine.analyse_new -> cluster.assign path says so.
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import re
import time
from urllib.parse import urlparse

from . import gazetteer, ingest, sources, web

log = logging.getLogger(__name__)

DEFAULT_KEYWORDS = [
    "inwestycja",
    "zarabiaj",
    "platforma inwestycyjna",
    "Brzoska",
    "Orlen akcje",
    "dochód pasywny",
    "kryptowaluty",
    "cukrzyca lek",
    "stawy kapsułki",
    "kasyno bonus",
]

RISKY_TLDS = (
    ".live", ".click", ".top", ".icu", ".sbs", ".cfd", ".xyz", ".online",
    ".site", ".pro", ".shop", ".store", ".life", ".ink", ".rest",
)

REQUEST_PAUSE = 0.5             # seconds between requests to public sources

_SCHED = None
CURRENT: dict | None = None     # settings of the running periodic scan (shown in the UI)


def _extract_host(item: dict) -> str:
    """Extract normalized hostname from `item['domain']` or `item['url']`."""
    raw_dom = str(item.get("domain") or "").strip()
    if raw_dom:
        host = urlparse(raw_dom).hostname if "://" in raw_dom else raw_dom.split("/", 1)[0]
        if host:
            return host.rstrip(".").lower()
    raw_url = str(item.get("url") or "").strip()
    if raw_url:
        host = urlparse(raw_url).hostname or ""
        return host.rstrip(".").lower()
    return ""


def _dedup_key(item: dict) -> tuple:
    """Stable deduplication key covering URL/domain/ad_id items as well as Google ATC advertisers."""
    src = item.get("source")
    primary = item.get("url") or item.get("domain") or item.get("ad_id")
    if primary:
        return (src, primary)
    return (src, item.get("advertiser_id") or "", item.get("name") or "")


def suspicion(item: dict) -> tuple[float, list[str]]:
    """Cheap triage score: celebrity/brand impersonation + scam lexicon + risky TLD + CERT listing."""
    txt = " ".join(
        str(item.get(k) or "")
        for k in ("title", "text", "advertiser", "domain", "display_url", "url", "name")
    )
    why: list[str] = []
    score = 0.0

    # Balanced CERT Polska prior: plain banking/OLX phishing stays below 0.5 unless ad-scam signals fire
    if item.get("source") == "cert_pl":
        score += 0.35
        why.append("na liście ostrzeżeń CERT Polska")

    persons = gazetteer.find_persons(txt)
    if persons:
        score += 0.30
        why.append(f"osoby: {', '.join(persons[:3])}")

    brands = gazetteer.find_brands(txt)
    if brands:
        score += 0.15
        why.append(f"marki: {', '.join(brands[:3])}")

    lex = gazetteer.lexicon_scores(txt, gazetteer.SCAM_LEXICON)
    if lex:
        top_cat, top_hits = max(lex.items(), key=lambda kv: kv[1])
        if top_hits >= 2:
            score += 0.20
            why.append(f"leksykon: {top_cat}")

    host = _extract_host(item)
    if host and any(host.endswith(tld) for tld in RISKY_TLDS):
        score += 0.15
        why.append("ryzykowna TLD")

    return min(1.0, round(score, 4)), why


def _analyse_hit(engine, r: dict, allow_domain: bool = False) -> dict | None:
    """Capture one found item and run it through the normal open-set assignment (engine.analyse_new).
    Returns the assignment result, or None when nothing could be captured."""
    from .capture import capture_url

    url = str(r.get("url") or "")
    if not url and allow_domain and r.get("domain"):
        url = f"https://{r['domain']}/"
    if url.startswith("https://www.facebook.com/ads/library/") and r.get("ad_id"):
        folder = sources.meta_ad_media(r["ad_id"])
        if folder:
            m = ingest.load_folder(folder, source="scheduler:meta")
        elif r.get("text"):
            m = ingest.from_text(r["text"])
        else:
            engine.store.log("capture_empty", {"source": r.get("source"), "url": url, "reason": "no media or text"})
            return None
    elif url:
        cap = capture_url(url, render=False)
        if not (cap.get("html") or cap.get("har") or cap.get("screenshot")):
            engine.store.log(
                "capture_empty",
                {
                    "source": r.get("source"),
                    "url": url,
                    "verdict": cap.get("cloaking_verdict"),
                    "notes": (cap.get("notes") or [])[:3],
                },
            )
            return None
        m = ingest.from_url(url, cap)
        m.source = f"scheduler:{r['source']}"
        if r.get("text") or r.get("title"):
            m.texts.append(f"{r.get('title') or ''}\n{r.get('text') or ''}".strip())
    else:
        return None
    return engine.analyse_new(m, use_llm=True)


def run_once(
    engine,
    keywords: list[str] | None = None,
    analyse: bool = False,
    max_analyse: int = 5,
    max_keywords: int | None = None,
    watch: bool = False,
) -> dict:
    """Run one scan across all configured public sources, deduplicate, and optionally analyse top hits.
    With `watch=True` the campaign watch (`watch_campaigns`) runs afterwards with the same `analyse` setting."""
    raw_keywords = list(keywords or DEFAULT_KEYWORDS)
    limit_kw = max_keywords if max_keywords is not None else 10
    active_keywords = raw_keywords[: max(0, limit_kw)]

    found: list[dict] = []
    errors: dict[str, str] = {}

    jobs = [("cert_pl", lambda: sources.cert_pl_new(engine.store, active_keywords))]
    for kw in active_keywords:
        jobs.append((f"ms_adlib:{kw}", lambda kw=kw: sources.ms_adlib_search(kw)))
        jobs.append((f"google_atc:{kw}", lambda kw=kw: sources.google_atc_suggest(kw)))
        jobs.append((f"meta_api:{kw}", lambda kw=kw: sources.meta_api_search(kw)))

    for name, fn in jobs:
        try:
            res = fn()
            for r in res:
                r["score"], r["why"] = suspicion(r)
            found.extend(res)
            engine.store.log("scan", {"source": name, "n": len(res)})
        except Exception as exc:
            errors[name] = str(exc)[:200]
            engine.store.log("scan_error", {"source": name, "error": str(exc)[:200]})
        time.sleep(REQUEST_PAUSE)

    found.sort(key=lambda r: -r["score"])

    prev = engine.store.get("scheduler_found", [])
    seen = {_dedup_key(x) for x in prev}
    fresh: list[dict] = []
    for r in found:
        key = _dedup_key(r)
        if key not in seen:
            seen.add(key)
            fresh.append(r)

    engine.store.put("scheduler_found", (prev + fresh)[-2000:])

    analysed: list[dict] = []
    if analyse:
        for r in [x for x in fresh if x["score"] >= 0.5][:max_analyse]:
            try:
                out = _analyse_hit(engine, r)
                if out is not None:
                    analysed.append({"item": r.get("url") or r.get("domain"), "decision": out["decision"],
                                     "campaign": out["campaign"]})
            except Exception as exc:
                errors[f"analyse:{r.get('url')}"] = str(exc)[:200]

    summary = {
        "found": len(found),
        "fresh": len(fresh),
        "top": fresh[:15],
        "analysed": analysed,
        "errors": errors,
    }
    engine.store.log("scheduler_run", {k: v for k, v in summary.items() if k != "top"})
    if watch:
        try:
            summary["watch"] = watch_campaigns(engine, analyse=analyse, max_analyse=max_analyse)
        except Exception as exc:
            errors["watch"] = str(exc)[:200]
    return summary


# ------------------------------------------------------------------ campaign watch (pivot search)
WATCH_MAX_CAMPAIGNS = 8     # campaigns per run (largest first)
WATCH_MAX_SEEDS = 4         # seeds per campaign
WATCH_GROUPS = ("domains", "ad_library", "product")
MIN_STEM = 5                # shortest CERT Polska stem (shorter labels match unrelated domains)
_GOOGLE_ADVERTISER_RX = re.compile(r"AR\d{10,}")      # Google Ads Transparency advertiser IDs: AR + digits


def _compact(v: str) -> str:
    return re.sub(r"[^a-z0-9]", "", gazetteer.fold(v).lower())


def _seed_plan(group: str, value: str) -> tuple[list[str], str | None, str | None]:
    """Which sources a seed is searched in, its CERT Polska stem, and why something was skipped."""
    if group == "domains":
        label = web._TLD(value).domain.lower()
        stem = label if len(_compact(label)) >= MIN_STEM else None
        return ["google_atc", "ms_adlib"], stem, None if stem else f"etykieta domeny krótsza niż {MIN_STEM} znaków — bez CERT Polska"
    if group == "ad_library":
        if _GOOGLE_ADVERTISER_RX.fullmatch(value):
            return ["google_atc"], None, None
        return [], None, "format ID nie pasuje do Google Ads Transparency (AR…) — pominięto"
    if group == "product":
        srcs = ["ms_adlib"] + (["meta_api"] if os.environ.get("META_ACCESS_TOKEN") else [])
        stem = _compact(value)
        stem = stem if len(stem) >= MIN_STEM else None
        return srcs, stem, None if os.environ.get("META_ACCESS_TOKEN") else "Meta Ad Library pominięta (brak tokenu)"
    return [], None, None


def _query(source: str, seed: dict) -> list[dict]:
    g, v = seed["group"], seed["value"]
    if source == "google_atc":
        return sources.google_atc_creatives(advertiser_id=v, n=20) if g == "ad_library" else sources.google_atc_creatives(domain=v, n=20)
    if source == "ms_adlib":
        return sources.ms_adlib_search(v)
    if source == "meta_api":
        return sources.meta_api_search(v)
    return []


def campaign_label(ci: int, profile: dict | None) -> str:
    name = (profile or {}).get("name")
    return f"C{ci + 1} · {name}" if name else f"C{ci + 1}"


def campaign_seeds(engine, campaigns: list[int] | None = None, max_campaigns: int = WATCH_MAX_CAMPAIGNS,
                   max_seeds: int = WATCH_MAX_SEEDS) -> list[dict]:
    """Search seeds per campaign = its own *counted* identifiers (df/N <= MAX_DF, as in similarity) from the
    groups domains / ad_library (advertiser IDs) / product; generic & decoy domains and real brand names dropped.
    Campaigns: the given indices, else the `max_campaigns` largest (multi-material first). Within a campaign the
    values held by more members come first, taking groups in turn (domain, advertiser, product, domain, ...)."""
    from .similarity import Corpus

    items = engine.store.all()
    if not items:
        return []
    cl = engine.clustering()
    camps = cl["campaigns"]
    profiles = cl.get("profiles") or [None] * len(camps)
    order = sorted(range(len(camps)), key=lambda ci: (-len(camps[ci]), ci))
    order = [ci for ci in order if ci in set(campaigns)] if campaigns is not None else order[:max(0, max_campaigns)]
    corpus = Corpus(items)
    out: list[dict] = []
    for ci in order:
        cand: dict[tuple[str, str], dict] = {}
        for m in camps[ci]:
            for (g, v), types in corpus.ids.get(m, {}).items():
                if g not in WATCH_GROUPS or not corpus.counted(corpus.df[(g, v)]):
                    continue
                if g == "ad_library" and "advertiser_id" not in types:      # an ad ID names one ad, not who runs it
                    continue
                if g == "domains" and web.is_decoy_or_generic_domain(v):
                    continue
                if g == "product" and (gazetteer.find_brands(v) or gazetteer.find_media(v)):   # real brand -> legit ads
                    continue
                e = cand.setdefault((g, v), {"types": set(), "n": 0})
                e["types"] |= {t for t in types if g != "ad_library" or t == "advertiser_id"}
                e["n"] += 1
        per_group: dict[str, list] = {}
        for (g, v), e in sorted(cand.items(), key=lambda kv: (-kv[1]["n"], kv[0][1])):
            per_group.setdefault(g, []).append((g, v, e))
        ranked = sorted(((r, WATCH_GROUPS.index(g), g, v, e) for g, lst in per_group.items() for r, (g, v, e) in enumerate(lst)),
                        key=lambda t: t[:4])
        label = campaign_label(ci, profiles[ci] if ci < len(profiles) else None)
        for _, _, g, v, e in ranked[:max(0, max_seeds)]:
            srcs, stem, note = _seed_plan(g, v)
            out.append({"campaign": ci, "campaign_label": label, "group": g, "type": "+".join(sorted(e["types"])),
                        "value": v, "df": corpus.df[(g, v)], "n_members": e["n"], "campaign_size": len(camps[ci]),
                        "sources": srcs + (["cert_pl"] if stem else []), "cert_stem": stem, "note": note})
    return out


def _hit_seed(seed: dict, source: str) -> dict:
    return {k: seed[k] for k in ("campaign", "campaign_label", "group", "type", "value")} | {"source": source}


def watch_campaigns(engine, campaigns: list[int] | None = None, analyse: bool = False,
                    max_campaigns: int = WATCH_MAX_CAMPAIGNS, max_seeds: int = WATCH_MAX_SEEDS,
                    max_analyse: int = 5, progress=None) -> dict:
    """Campaign watch: search public sources with each campaign's own identifiers (seeds) for NEW materials.

    Every hit carries `seed` (campaign, label, group, type, value, source). A hit is a lead, not a link: with
    `analyse=True` new hits are captured and assigned by the normal engine.analyse_new -> cluster.assign path,
    and that decision is stored as `outcome` (`confirmed` = assigned to a campaign containing the seed campaign's
    members). Hits are ordered by campaign, then source; deduplicated with `_dedup_key` against `scheduler_found`.
    """
    say = progress or (lambda _msg: None)
    seeds = campaign_seeds(engine, campaigns, max_campaigns=max_campaigns, max_seeds=max_seeds)
    cl = engine.clustering() if seeds else {"campaigns": []}
    seed_members = {s["campaign"]: set(cl["campaigns"][s["campaign"]]) for s in seeds}
    found: list[dict] = []
    errors: dict[str, str] = {}

    def keep(res: list[dict], seed: dict, source: str) -> None:
        for r in res:
            r["score"], r["why"] = suspicion(r)
            r["seed"] = _hit_seed(seed, source)
        found.extend(res)
        engine.store.log("watch_scan", {"source": source, "campaign_label": seed["campaign_label"], "group": seed["group"],
                                        "value": seed["value"], "n": len(res)})

    for seed in seeds:
        for source in seed["sources"]:
            if source == "cert_pl":
                continue
            say(f"{seed['campaign_label']}: {seed['value']} → {source}")
            try:
                keep(_query(source, seed), seed, source)
            except Exception as exc:
                errors[f"{source}:{seed['value']}"] = str(exc)[:200]
                engine.store.log("scan_error", {"source": f"{source}:{seed['value']}", "error": str(exc)[:200]})
            time.sleep(REQUEST_PAUSE)

    stems: dict[str, dict] = {}
    for seed in seeds:
        if seed.get("cert_stem"):
            stems.setdefault(seed["cert_stem"], seed)
    if stems:
        say(f"CERT Polska: {len(stems)} rdzeni domen/produktów")
        try:
            for r in sources.cert_pl_watch(engine.store, list(stems)):
                keep([r], stems[r["match"][0]], "cert_pl")
        except Exception as exc:
            errors["cert_pl"] = str(exc)[:200]
            engine.store.log("scan_error", {"source": "cert_pl", "error": str(exc)[:200]})

    rank = {ci: i for i, ci in enumerate(dict.fromkeys(s["campaign"] for s in seeds))}
    found.sort(key=lambda r: (rank.get(r["seed"]["campaign"], 0), r["seed"]["source"]))

    prev = engine.store.get("scheduler_found", [])
    by_key = {_dedup_key(x): x for x in prev}
    hits, fresh, run_keys = [], [], set()
    for r in found:
        key = _dedup_key(r)
        if key in run_keys:
            continue
        run_keys.add(key)
        old = by_key.get(key)
        if old is None:
            fresh.append(r)
            hits.append({**r, "new": True})
        else:
            old.setdefault("seed", r["seed"])      # found earlier by keyword: keep the item, add its provenance
            hits.append({**old, "new": False})
    engine.store.put("scheduler_found", (prev + fresh)[-2000:])

    analysed: list[dict] = []
    if analyse and fresh:
        outcomes: dict[tuple, dict] = {}
        for r in fresh[:max(0, max_analyse)]:
            say(f"Analiza: {r.get('url') or r.get('domain')}")
            try:
                cl_now = engine.clustering()          # the clustering assign() decides against
                out = _analyse_hit(engine, r, allow_domain=True)
            except Exception as exc:
                errors[f"analyse:{r.get('url') or r.get('domain')}"] = str(exc)[:200]
                continue
            if out is None:
                outcome = {"decision": None, "confirmed": False, "note": "nie udało się pobrać materiału"}
            else:
                c = out["campaign"]
                members = set(cl_now["campaigns"][c]) if isinstance(c, int) and c < len(cl_now["campaigns"]) else set()
                confirmed = out["decision"] != "new_campaign" and bool(members & seed_members.get(r["seed"]["campaign"], set()))
                outcome = {"decision": out["decision"], "campaign": c, "campaign_label": f"C{c + 1}" if isinstance(c, int) else None,
                           "confirmed": confirmed, "material": out["material"].id}
            outcomes[_dedup_key(r)] = outcome
            analysed.append({"item": r.get("url") or r.get("domain"), "seed": r["seed"], **outcome})
        stored = engine.store.get("scheduler_found", [])
        for x in stored:
            if _dedup_key(x) in outcomes:
                x["outcome"] = outcomes[_dedup_key(x)]
        engine.store.put("scheduler_found", stored)
        for h in hits:
            if _dedup_key(h) in outcomes:
                h["outcome"] = outcomes[_dedup_key(h)]

    engine.store.put("watch_last", {"ts": dt.datetime.now().isoformat(timespec="seconds"), "campaigns": campaigns,
                                    "seeds": seeds})
    summary = {
        "campaigns": list(dict.fromkeys(s["campaign_label"] for s in seeds)),
        "seeds": seeds,
        "found": len(found),
        "fresh": len(fresh),
        "hits": hits[:100],
        "analysed": analysed,
        "confirmed": sum(1 for a in analysed if a.get("confirmed")),
        "errors": errors,
    }
    engine.store.log("watch_run", {"campaigns": len(summary["campaigns"]), "seeds": len(seeds), "found": len(found),
                                   "fresh": len(fresh), "analysed": len(analysed), "confirmed": summary["confirmed"],
                                   "errors": len(errors)})
    return summary


def start_background(engine, minutes: int = 30, analyse: bool = True, keywords: list[str] | None = None,
                     watch: bool = False) -> str:
    global _SCHED, CURRENT
    from apscheduler.schedulers.background import BackgroundScheduler

    if _SCHED and _SCHED.running:
        return "Skan cykliczny już działa."
    kws = keywords or DEFAULT_KEYWORDS
    _SCHED = BackgroundScheduler(daemon=True)
    # NB: next_run_time must not be None here — in APScheduler 3.x that adds the job *paused* (it would never run)
    _SCHED.add_job(
        lambda: run_once(engine, keywords=kws, analyse=analyse, watch=watch),
        "interval",
        minutes=minutes,
        id="scan",
        max_instances=1,
        coalesce=True,
    )
    _SCHED.start()
    CURRENT = {"minutes": minutes, "keywords": kws, "analyse": analyse, "watch": watch}
    return f"Skan cykliczny włączony (co {minutes} min, pierwszy za {minutes} min)."


def stop_background() -> str:
    global _SCHED, CURRENT
    if _SCHED and _SCHED.running:
        _SCHED.shutdown(wait=False)
        CURRENT = None
        return "Skan cykliczny zatrzymany."
    return "Skan cykliczny nie był włączony."


if __name__ == "__main__":
    from .engine import Engine

    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--analyse", action="store_true")
    ap.add_argument("--every", type=int, default=0)
    ap.add_argument("--watch", action="store_true", help="also search with known campaigns' identifiers")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    eng = Engine()
    while True:
        s = run_once(eng, analyse=a.analyse, watch=a.watch)
        print({k: v for k, v in s.items() if k not in ("top", "watch")})
        if s.get("watch"):
            w = s["watch"]
            print(f"watch: {len(w['seeds'])} seeds, found {w['found']}, new {w['fresh']}, confirmed {w['confirmed']}")
        for r in s["top"][:10]:
            print(f"  {r['score']:.2f} {r['source']:10s} {r.get('domain') or r.get('url') or r.get('name')}  {r['why']}")
        if a.once or not a.every:
            break
        time.sleep(a.every * 60)
