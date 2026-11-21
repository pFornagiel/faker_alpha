"""Built-in scheduler: periodically scans ad libraries and warning lists, scores suspicion,
and optionally captures + analyses new items against known campaigns (open-set assignment).

    python -m ftf.scheduler --once [--analyse]      # single run (cron-friendly)
    python -m ftf.scheduler --every 30              # foreground loop every 30 min
"""
from __future__ import annotations

import argparse
import logging
import time
from urllib.parse import urlparse

from . import gazetteer, ingest, sources

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


def run_once(
    engine,
    keywords: list[str] | None = None,
    analyse: bool = False,
    max_analyse: int = 5,
    max_keywords: int | None = None,
) -> dict:
    """Run one scan across all configured public sources, deduplicate, and optionally analyse top hits."""
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
        time.sleep(0.5)

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
        from .capture import capture_url

        for r in [x for x in fresh if x["score"] >= 0.5][:max_analyse]:
            try:
                url = str(r.get("url") or "")
                if url.startswith("https://www.facebook.com/ads/library/") and r.get("ad_id"):
                    folder = sources.meta_ad_media(r["ad_id"])
                    if folder:
                        m = ingest.load_folder(folder, source="scheduler:meta")
                    elif r.get("text"):
                        m = ingest.from_text(r["text"])
                    else:
                        engine.store.log("capture_empty", {"source": r.get("source"), "url": url, "reason": "no media or text"})
                        continue
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
                        continue
                    m = ingest.from_url(url, cap)
                    m.source = f"scheduler:{r['source']}"
                    if r.get("text") or r.get("title"):
                        m.texts.append(f"{r.get('title') or ''}\n{r.get('text') or ''}".strip())
                else:
                    continue

                out = engine.analyse_new(m, use_llm=True)
                analysed.append(
                    {
                        "item": r.get("url") or r.get("domain"),
                        "decision": out["decision"],
                        "campaign": out["campaign"],
                    }
                )
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
    return summary


def start_background(engine, minutes: int = 30, analyse: bool = True, keywords: list[str] | None = None) -> str:
    global _SCHED, CURRENT
    from apscheduler.schedulers.background import BackgroundScheduler

    if _SCHED and _SCHED.running:
        return "Skan cykliczny już działa."
    kws = keywords or DEFAULT_KEYWORDS
    _SCHED = BackgroundScheduler(daemon=True)
    # NB: next_run_time must not be None here — in APScheduler 3.x that adds the job *paused* (it would never run)
    _SCHED.add_job(
        lambda: run_once(engine, keywords=kws, analyse=analyse),
        "interval",
        minutes=minutes,
        id="scan",
        max_instances=1,
        coalesce=True,
    )
    _SCHED.start()
    CURRENT = {"minutes": minutes, "keywords": kws, "analyse": analyse}
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
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    eng = Engine()
    while True:
        s = run_once(eng, analyse=a.analyse)
        print({k: v for k, v in s.items() if k != "top"})
        for r in s["top"][:10]:
            print(f"  {r['score']:.2f} {r['source']:10s} {r.get('domain') or r.get('url') or r.get('name')}  {r['why']}")
        if a.once or not a.every:
            break
        time.sleep(a.every * 60)
