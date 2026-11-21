"""Built-in scheduler: periodically scans ad libraries / warning lists, scores suspicion, and (optionally)
analyses new items against the known campaigns (open-set assignment). APScheduler BackgroundScheduler.

    python -m ftf.scheduler --once [--analyse]      # single run (cron-friendly)
    python -m ftf.scheduler --every 30              # foreground loop every 30 min
"""
from __future__ import annotations

import argparse
import logging
import time

from . import gazetteer, ingest, sources

log = logging.getLogger(__name__)
DEFAULT_KEYWORDS = ["inwestycja", "zarabiaj", "platforma inwestycyjna", "Brzoska", "Orlen akcje", "dochód pasywny",
                    "kryptowaluty", "cukrzyca lek", "stawy kapsułki", "kasyno bonus"]
_SCHED = None
CURRENT: dict | None = None     # settings of the running periodic scan (shown in the UI)


def suspicion(item: dict) -> tuple[float, list[str]]:
    """Cheap triage score: celebrity/brand impersonation + scam lexicon + risky TLD + CERT listing."""
    txt = " ".join(str(item.get(k) or "") for k in ("title", "text", "advertiser", "domain", "display_url", "url", "name"))
    why = []
    s = 0.0
    if item.get("source") == "cert_pl":
        s += 0.6; why.append("na liście ostrzeżeń CERT Polska")
    p = gazetteer.find_persons(txt)
    if p:
        s += 0.3; why.append(f"osoby: {', '.join(p[:3])}")
    b = gazetteer.find_brands(txt)
    if b:
        s += 0.1; why.append(f"marki: {', '.join(b[:3])}")
    lex = gazetteer.lexicon_scores(txt, gazetteer.SCAM_LEXICON)
    top = max(lex.items(), key=lambda kv: kv[1])
    if top[1] >= 2:
        s += 0.2; why.append(f"leksykon: {top[0]}")
    dom = item.get("domain") or item.get("url") or ""
    if any(str(dom).rstrip("/").endswith(t) for t in (".live", ".click", ".top", ".icu", ".sbs", ".cfd", ".xyz", ".online",
                                                       ".site", ".pro", ".shop", ".store", ".life", ".ink", ".rest")):
        s += 0.15; why.append("ryzykowna TLD")
    return min(1.0, s), why


def run_once(engine, keywords: list[str] | None = None, analyse: bool = False, max_analyse: int = 5) -> dict:
    keywords = keywords or DEFAULT_KEYWORDS
    found, errors = [], {}
    jobs = [("cert_pl", lambda: sources.cert_pl_new(engine.store, keywords))]
    for kw in keywords[:4]:
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
    seen = {(x.get("source"), x.get("url") or x.get("domain") or x.get("ad_id")) for x in prev}
    fresh = [r for r in found if (r.get("source"), r.get("url") or r.get("domain") or r.get("ad_id")) not in seen]
    engine.store.put("scheduler_found", (prev + fresh)[-2000:])
    analysed = []
    if analyse:
        from .capture import capture_url

        for r in [x for x in fresh if x["score"] >= 0.5][:max_analyse]:
            try:
                if r.get("url", "").startswith("https://www.facebook.com/ads/library/") and r.get("ad_id"):
                    folder = sources.meta_ad_media(r["ad_id"])
                    m = ingest.load_folder(folder, source="scheduler:meta") if folder else ingest.from_text(r.get("text", ""))
                elif r.get("url"):
                    m = ingest.from_url(r["url"], capture_url(r["url"], render=False))
                    m.source = f"scheduler:{r['source']}"
                    if r.get("text") or r.get("title"):
                        m.texts.append(f"{r.get('title') or ''}\n{r.get('text') or ''}")
                else:
                    continue
                out = engine.analyse_new(m, use_llm=True)
                analysed.append({"item": r.get("url") or r.get("domain"), "decision": out["decision"], "campaign": out["campaign"]})
            except Exception as exc:
                errors[f"analyse:{r.get('url')}"] = str(exc)[:200]
    summary = {"found": len(found), "fresh": len(fresh), "top": fresh[:15], "analysed": analysed, "errors": errors}
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
    _SCHED.add_job(lambda: run_once(engine, keywords=kws, analyse=analyse), "interval", minutes=minutes, id="scan",
                   max_instances=1, coalesce=True)
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
