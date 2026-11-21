"""FakeTrace HTTP API (FastAPI) — serves curated, display-ready JSON to the web UI in `web/`.

Run:   python -m ftf.cli serve                    (UI at http://localhost:8765 after `npm run build` in web/)
Dev:   uvicorn ftf.api:app --reload --port 8765   +  `npm run dev` in web/ (Vite proxies /api)

The engine (feature extraction, similarity, clustering) is untouched; this layer only reshapes its output
into what an analyst needs to read: who is linked to whom, *why*, and how strong each reason is.
All user-facing strings are Polish; enum ids, folded values and raw hashes never reach the UI unexplained.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import shutil
import threading
import time
import uuid
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, ingest
from .engine import Engine
from .gazetteer import fold
from .labels import (DECISION_PL, ENUM_PL, FAMILY_HINT, FAMILY_ORDER, LLM_FIELDS_PL, RELATION_HINT, RELATION_PL, SOURCE_PL, TIER_HINT,
                     TIER_PL, enum_label, family_label, signal_label)
from .similarity import Corpus, Link, _generic_phrase, noisy_or, pair
from .text import normalize as text_normalize

log = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(_app):
    def warm():              # first overview hashes landing-page images for thumbnails; do it before anyone asks
        try:
            overview()
        except Exception:
            log.exception("warm-up failed")
    threading.Thread(target=warm, daemon=True).start()
    yield


app = FastAPI(title="FakeTrace API", version="1.0", lifespan=_lifespan)

_ENGINE: Engine | None = None
_ENGINE_LOCK = threading.Lock()

# literals used by the engine outside config.py (kept here so the methodology page can show them)
CORE_S_MIN = 0.6           # cluster.build: operator-level link that forms a campaign core
STRONG_MERGE = 0.85        # cluster.agglomerate: a single link this strong merges campaigns
SINGLE_ASSIGN = 0.75       # cluster.assign: a single link this strong assigns a new material
CONFLICT_FACTOR = 0.6      # similarity.pair: contradicting scam types
PLAYBOOK_MIN = 0.45        # similarity.pair: 'similar' via playbook score
FAMILY_MERGE = 0.40        # cluster.build: playbook families

BACKEND_PL = {"claude_cli": "Claude (Claude Code CLI)", "gemini": "Gemini", "rules": "reguły słownikowe (bez modelu językowego)",
              "none": "wyłączone", "auto": "automatycznie: Claude CLI → Gemini → reguły słownikowe"}
SCAN_SOURCE_PL = {"cert_pl": "CERT Polska", "ms_adlib": "Microsoft Ad Library", "google_atc": "Google Ads Transparency",
                  "meta_api": "Meta Ad Library", "linkedin": "LinkedIn"}
WEB_IMG = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif"}


def eng() -> Engine:
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            _ENGINE = Engine()
        return _ENGINE


def plural(n: int, one: str, few: str, many: str) -> str:
    if n == 1:
        return f"{n} {one}"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} {few}"
    return f"{n} {many}"


def fp(x: float) -> str:
    """Score for prose: noisy-OR never reaches 1, so never print certainty (matches the UI)."""
    return "0.99+" if x >= 0.995 else f"{x:.2f}"


def cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


# =============================================================================== helpers
def _items():
    return eng().store.all()


def _cl():
    return eng().clustering()


def _abs(p: str) -> Path:
    q = Path(p)
    return q if q.is_absolute() else config.ROOT / q


def file_url(p: str | None) -> str | None:
    return "/api/file?path=" + quote(str(p)) if p else None


def _thumb(f: dict) -> tuple[str | None, str | None]:
    """Representative picture: creative screenshot / video keyframe, else first landing-page image."""
    for im in f.get("images", []):
        if im.get("kind") != "ui_screenshot" and _abs(im["src"]).exists():
            return file_url(im["src"]), im.get("kind")
    for im in f.get("images", []):
        if _abs(im["src"]).exists():
            return file_url(im["src"]), im.get("kind")
    for a in (f.get("_material") or {}).get("assets", [])[:20]:
        if Path(a).suffix.lower() in WEB_IMG and _abs(a).exists():
            return file_url(a), "landing_asset"
    return None, None


# ------------------------------------------------------------------ shared landing-page images: hash -> file
_ASSET_HASH: dict[str, str | None] = {}
_ASSET_LOCK = threading.Lock()


def asset_hash_map(f: dict) -> dict[str, str]:
    """pHash -> asset path for one material (same hashing as the pipeline), cached per file."""
    from . import vision

    out: dict[str, str] = {}
    for a in (f.get("_material") or {}).get("assets", []):
        if Path(a).suffix.lower() not in WEB_IMG:
            continue
        with _ASSET_LOCK:
            if a not in _ASSET_HASH:
                h = None
                p = _abs(a)
                try:
                    if p.stat().st_size >= config.MIN_ASSET_BYTES:
                        im = vision.load_rgb(str(p))
                        if im is not None and min(im.size) >= config.MIN_ASSET_SIDE:
                            h = vision.hashes(im)["phash"]
                except OSError:
                    pass
                _ASSET_HASH[a] = h
        if _ASSET_HASH[a]:
            out.setdefault(_ASSET_HASH[a], a)
    return out


def thumbs_for(hashes: list[str], feats: list[dict], limit: int = 12) -> list[str]:
    maps = [asset_hash_map(f) for f in feats]
    urls: list[str] = []
    for h in hashes:
        for mp in maps:
            hit = mp.get(h) or next((p for hh, p in mp.items() if bin(int(hh, 16) ^ int(h, 16)).count("1") <= 4), None)
            if hit:
                urls.append(file_url(hit))
                break
        if len(urls) >= limit:
            break
    return urls


# ------------------------------------------------------------------ human-readable values
def _display_index(items: dict) -> dict:
    """(type, normalised value) -> original text (with diacritics/case) for LLM-derived indicators."""
    idx = {}
    for f, _ in items.values():
        llm = f.get("llm") or {}
        prod = llm.get("product_or_platform_name")
        if prod:
            idx.setdefault(("product", fold(prod).strip()), prod)
        for ph in llm.get("distinctive_phrases") or []:
            idx.setdefault(("phrase", text_normalize(ph)), ph)
    return idx


def display_value(t: str, v: str, cl: dict | None = None) -> str:
    if t in ("product", "phrase"):
        cl = cl or _cl()
        if "_display" not in cl:
            cl["_display"] = _display_index(_items())
        return cl["_display"].get((t, v), v)
    if t == "reg_burst":
        parts = v.split("|")
        if len(parts) == 3:
            return f"{parts[0]} · NS {parts[1].replace('+', ' + ')} · utworzone {parts[2]}"
    if t == "ns_pair":
        return v.replace("+", " + ")
    return v


_CONCEPT_PL = {"scam_type": "ten sam typ oszustwa", "narrative_template": "ten sam szablon narracji",
               "creative_format": "ten sam format kreacji"}
_SHARED_RX = re.compile(r"^wspólny .+?: „.*” \((\d+)/(\d+)\)$", re.S)
_HUB_RX = re.compile(r"^pominięto hub: .+ \((\d+)/(\d+) materiałów\)$", re.S)


def detail_pl(e, short: bool = False) -> str:
    """Evidence sentence in correct Polish: labels instead of enum ids, original text instead of folded values,
    'w 2 z 10 materiałów' instead of '(2/10)'."""
    if e.family == "concept" and e.signal in _CONCEPT_PL:
        return cap(f"{_CONCEPT_PL[e.signal]}: {enum_label(e.value)}")
    if e.signal == "conflict":
        d = e.detail
        for k in sorted(ENUM_PL, key=len, reverse=True):
            d = d.replace(k, enum_label(k))
        return cap(d)
    m = _SHARED_RX.match(e.detail) or _HUB_RX.match(e.detail)
    if m and e.value:
        df, n = m.groups()
        if e.signal == "asset_phash":          # a hash means nothing to a reader; the thumbnail shows the image
            s = "Ten sam obraz na stronach docelowych"
        else:
            s = f"{cap(signal_label(e.signal))}: „{display_value(e.signal, e.value)}”"
        if e.ignored:
            return f"{s} — w {df} z {n} materiałów, zbyt popularne, by coś znaczyć"
        return s if short else f"{s} — w {df} z {n} materiałów"
    return cap(e.detail)


def fam_list(families: dict) -> list[dict]:
    out = [{"family": k, "label": family_label(k), "tier": config.FAMILY_TIER.get(k, "W"), "score": round(v, 3)}
           for k, v in families.items() if v > 0]
    return sorted(out, key=lambda d: -d["score"])


# ------------------------------------------------------------------ campaigns
def campaign_name(p: dict, items: dict | None = None) -> str:
    """'<product or narrative> · <main impersonated person>' — deterministic across processes."""
    def first_max(d: dict | None):          # insertion order = member order, so ties are stable
        return max(d.items(), key=lambda kv: kv[1])[0] if d else None

    items = items if items is not None else _items()
    feats = [items[m][0] for m in p["members"] if m in items]
    imp = Counter(x for f in feats for x in set((f.get("llm") or {}).get("impersonated_persons") or []))
    vis = Counter(x for f in feats for x in set(f.get("persons_visual", [])))
    pool = imp or vis or Counter(p.get("persons") or {})
    who = min(pool, key=lambda x: (-pool[x], -vis.get(x, 0), x)) if pool else None
    prod, narr = first_max(p.get("products")), first_max(p.get("narratives"))
    main = prod or (enum_label(narr) if narr else None) or "bez nazwy"
    return " · ".join(x for x in [str(main), who] if x)


def color_slot(ci: int | None, size: int) -> int | None:
    """Only multi-material campaigns get a categorical hue (fixed order, max 8); singletons stay neutral."""
    if ci is None or size < 2 or ci >= 8:
        return None
    return ci


def camp_ref(ci: int | None, cl: dict | None = None) -> dict | None:
    if ci is None or ci < 0:
        return None
    cl = cl or _cl()
    if ci >= len(cl["profiles"]):
        return None
    p = cl["profiles"][ci]
    names = cl.setdefault("_names", {})          # cached per clustering (reset whenever the engine reclusters)
    if ci not in names:
        names[ci] = campaign_name(p, _items())
    return {"id": ci, "code": f"C{ci + 1}", "name": names[ci], "size": p["size"], "color": color_slot(ci, p["size"])}


def mat_summary(mid: str, f: dict, cl: dict | None = None) -> dict:
    cl = cl or _cl()
    llm = f.get("llm") or {}
    thumb, thumb_kind = _thumb(f)
    titles = f.get("text", {}).get("titles") or []
    m = f.get("_material") or {}
    return {
        "id": mid, "name": str(f.get("name") or mid),
        "title": titles[0] if titles else (llm.get("summary_pl") or "")[:120],
        "source": m.get("source") or "", "source_label": SOURCE_PL.get(m.get("source", ""), m.get("source", "")),
        "created_at": m.get("created_at"),
        "campaign": camp_ref(cl["campaign_of"].get(mid), cl),
        "scam_type": llm.get("scam_type"), "scam_type_label": enum_label(llm.get("scam_type")) if llm.get("scam_type") else None,
        "product": llm.get("product_or_platform_name"),
        "persons": sorted(set(f.get("persons_visual", [])) | set(f.get("persons_named", [])))[:6],
        "domains": f.get("web", {}).get("landing_domains", [])[:5],
        "thumb": thumb, "thumb_kind": thumb_kind,
        "counts": {"pages": f.get("n_pages", 0), "images": f.get("n_images", 0), "videos": f.get("n_videos", 0)},
    }


def _name(items: dict, mid: str) -> str:
    return str(items[mid][0].get("name")) if mid in items else mid


def link_brief(l: Link, items: dict, cl: dict, me: str | None = None) -> dict:
    top = sorted([e for e in l.evidence if not e.ignored and e.weight > 0], key=lambda e: -e.weight)
    seen, reasons = set(), []
    for e in top:                                   # one reason per signal type, max 3
        if e.signal in seen:
            continue
        seen.add(e.signal)
        reasons.append({"detail": detail_pl(e), "weight": round(e.weight, 3), "family": e.family})
        if len(reasons) == 3:
            break
    d = {"a": l.a, "b": l.b, "p": round(l.p, 3), "relation": l.relation, "relation_label": RELATION_PL[l.relation],
         "families": fam_list(l.families), "reasons": reasons, "comparable": l.comparable}
    if me is not None:
        other = l.b if l.a == me else l.a
        d["other"] = mat_summary(other, items[other][0], cl) if other in items else {"id": other, "name": other}
    else:
        d["a_info"] = {"id": l.a, "name": _name(items, l.a), "campaign": camp_ref(cl["campaign_of"].get(l.a), cl)}
        d["b_info"] = {"id": l.b, "name": _name(items, l.b), "campaign": camp_ref(cl["campaign_of"].get(l.b), cl)}
    return d


def link_basis(l: Link) -> tuple[str, float, float, int]:
    strong = max([v for f, v in l.families.items() if config.FAMILY_TIER.get(f) in ("S", "M")] or [0])
    s_tier = max([v for f, v in l.families.items() if config.FAMILY_TIER.get(f) == "S"] or [0])
    n_fam = sum(1 for f, v in l.families.items() if v >= 0.3 and config.FAMILY_TIER.get(f) in ("S", "M"))
    if l.relation == "duplicate":
        basis = "duplikat"
    elif s_tier >= 0.5:
        basis = "ślad operatora"
    elif strong >= 0.7:
        basis = "silny ślad kit/treść"
    elif n_fam >= 2:
        basis = f"{n_fam} niezależne rodziny śladów"
    else:
        basis = "tylko słabe podobieństwo"
    return basis, strong, s_tier, n_fam


def explain_link(l: Link, items: dict | None = None) -> dict:
    """Full, step-by-step explanation of one pairwise score (what the pair page renders)."""
    items = items if items is not None else _items()
    fams = defaultdict(list)
    ignored = []
    for e in l.evidence:
        if e.signal == "conflict":
            continue                                  # shown as a guard, not as an "ignored value"
        if e.ignored or e.weight <= 0:
            ignored.append({"detail": detail_pl(e), "signal": e.signal, "family": e.family})
            continue
        fams[e.family].append(e)
    feats = [items[x][0] for x in (l.a, l.b) if x in items]
    groups = []
    for fam in sorted(fams, key=lambda f: -l.families.get(f, 0)):
        by_sig = defaultdict(list)
        for e in fams[fam]:
            by_sig[e.signal].append(e)
        rows = []
        for sig, es in by_sig.items():
            if len(es) >= 3 or (sig == "asset_phash" and len(es) >= 2):
                vals = sorted(e.value for e in es)
                label = ("wspólnych obrazów na stronach docelowych" if sig == "asset_phash" else f"wspólnych wartości — {signal_label(sig)}")
                rows.append({"signal": sig, "signal_label": signal_label(sig), "detail": f"{len(es)} {label}",
                             "value": "", "weight": round(noisy_or([e.weight for e in es]), 3),
                             "values": [display_value(sig, v) for v in vals],
                             "thumbs": thumbs_for(vals, feats) if sig == "asset_phash" else []})
            else:
                for e in es:
                    rows.append({"signal": sig, "signal_label": signal_label(sig), "detail": detail_pl(e), "value": e.value,
                                 "weight": round(e.weight, 3),
                                 "thumbs": thumbs_for([e.value], feats) if sig == "asset_phash" else []})
        groups.append({"family": fam, "label": family_label(fam), "tier": config.FAMILY_TIER.get(fam, "W"),
                       "tier_label": TIER_PL[config.FAMILY_TIER.get(fam, "W")], "hint": FAMILY_HINT.get(fam, ""),
                       "score": round(l.families.get(fam, 0), 3), "items": sorted(rows, key=lambda x: -x["weight"])})
    raw = noisy_or(l.families.values())
    basis, strong, s_tier, n_fam = link_basis(l)
    guards = []
    if strong < 0.25 and raw > config.WEAK_ONLY_CAP:
        guards.append({"name": "weak_only_cap", "label": f"Tylko słabe dowody → p ograniczone do {config.WEAK_ONLY_CAP}",
                       "detail": "Ta sama osoba, typ oszustwa czy hosting nie wystarczą, by połączyć materiały."})
    if any(e.signal == "conflict" for e in l.evidence):
        guards.append({"name": "conflict", "label": f"Różny typ oszustwa → p × {CONFLICT_FACTOR}",
                       "detail": next(detail_pl(e) for e in l.evidence if e.signal == "conflict")})
    if l.relation == "duplicate":
        rule = f"Rodzina „duplikat” ma wynik ≥ {config.DUPLICATE_THRESHOLD} — to ten sam materiał."
    elif l.relation == "same_campaign":
        why = []
        if s_tier >= 0.5:
            why.append(f"jest ślad operatora ({fp(s_tier)} ≥ 0.5)")
        if strong >= 0.7:
            why.append(f"najsilniejszy ślad operatora lub kit/treść ma {fp(strong)} ≥ 0.7")
        if n_fam >= 2:
            why.append(f"{plural(n_fam, 'niezależna rodzina', 'niezależne rodziny', 'niezależnych rodzin')} śladów ma wynik ≥ 0.3")
        rule = f"p = {fp(l.p)} ≥ {config.LINK_THRESHOLD}, a do tego " + "; ".join(why) + "."
    elif l.relation == "similar":
        rule = (f"p = {fp(l.p)} ≥ {config.SIMILAR_THRESHOLD}" if l.p >= config.SIMILAR_THRESHOLD
                else f"wspólny schemat (playbook) = {fp(l.playbook)} ≥ {PLAYBOOK_MIN}") + \
            " — ale brak śladu wspólnego operatora, więc to nie jest „ta sama kampania”."
    else:
        rule = f"p = {fp(l.p)} < {config.SIMILAR_THRESHOLD} i brak wspólnego schematu (playbooka)."
    weak_only = bool(l.families) and all(config.FAMILY_TIER.get(f) == "W" for f in l.families)
    return {"p": round(l.p, 3), "p_raw": round(raw, 3), "relation": l.relation, "relation_label": RELATION_PL[l.relation],
            "relation_hint": RELATION_HINT[l.relation], "rule": rule, "basis": basis, "weak_only": weak_only,
            "playbook": round(l.playbook, 3), "comparable": l.comparable, "groups": groups, "ignored": ignored, "guards": guards,
            "strongest_operator": round(s_tier, 3), "strongest_sm": round(strong, 3), "n_independent": n_fam}


def find_link(a: str, b: str) -> Link:
    for l in _cl()["links"]:
        if (l.a, l.b) in ((a, b), (b, a)):
            return l if l.a == a else Link(a, b, l.p, l.relation, l.families, l.evidence, l.comparable, l.playbook)
    items = _items()
    if a not in items or b not in items:
        raise HTTPException(404, "Nie znaleziono materiału o tym identyfikatorze.")
    fa, va = items[a]
    fb, vb = items[b]
    return pair(a, fa, va, b, fb, vb, Corpus(items))


# =============================================================================== jobs (long-running work)
_POOL = ThreadPoolExecutor(max_workers=1)
_JOBS: dict[str, dict] = {}
_PROGRESS_PL = [("HAR: ", "Zapis ruchu sieciowego (HAR): "), ("HTML: ", "Zapisana strona: "), ("video keyframes: ", "Klatki wideo: "),
                ("image (", "Obraz ("), ("text embedding (EmbeddingGemma-2)", "Embedding tekstu (EmbeddingGemma-2)"),
                ("text embedding", "Embedding tekstu (e5)"), ("LLM attributes", "Atrybuty z modelu językowego"),
                ("enrich: ", "Metadane domeny (RDAP, DNS, certyfikaty): ")]


def _progress_pl(msg: str) -> str:
    for a, b in _PROGRESS_PL:
        if msg.startswith(a):
            return b + msg[len(a):]
    return msg


def submit(kind: str, label: str, fn, meta: dict | None = None) -> dict:
    jid = uuid.uuid4().hex[:10]
    job = {"id": jid, "kind": kind, "label": label, "meta": meta or {}, "status": "queued", "progress": [], "result": None,
           "error": None, "started": time.time(), "finished": None}
    _JOBS[jid] = job

    def run():
        job["status"] = "running"
        try:
            job["result"] = fn(lambda msg: job["progress"].append(_progress_pl(str(msg))[:300]))
            job["status"] = "done"
        except Exception as exc:          # surfaced to the UI verbatim
            log.exception("job %s failed", jid)
            job["status"], job["error"] = "error", f"{type(exc).__name__}: {exc}"[:500]
        job["finished"] = time.time()

    _POOL.submit(run)
    return job


@app.get("/api/jobs/{jid}")
def get_job(jid: str):
    if jid not in _JOBS:
        raise HTTPException(404, "Nie ma takiego zadania (serwer mógł zostać zrestartowany).")
    return _JOBS[jid]


# =============================================================================== campaigns
def shared_rows(p: dict, items: dict, cl: dict) -> list[dict]:
    """Every value shared by >= 2 members, grouped by (type, set of members), noise removed:
    generic phrases, page hosts duplicating a landing domain, phrases duplicating the product name."""
    mem = p["members"]
    cnt: dict[tuple, list[str]] = defaultdict(list)
    for m in mem:
        for t, vals in items[m][0].get("indicators", {}).items():
            if t in config.INDICATOR_WEIGHT:
                for v in set(vals):
                    cnt[(t, v)].append(m)
    products = {text_normalize(display_value("product", v, cl)) for (t, v), ms in cnt.items() if t == "product"}
    rows: dict[tuple, dict] = {}
    for (t, v), ms in cnt.items():
        if len(ms) < 2:
            continue
        if t == "phrase" and (_generic_phrase(v) or v in products):
            continue
        if t == "page_host" and len(cnt.get(("landing_domain", v), [])) >= len(ms):
            continue
        has = tuple(m for m in mem if m in ms)
        key = (t, has)
        fam = config.INDICATOR_FAMILY.get(t, "kit")
        r = rows.setdefault(key, {"type": t, "type_label": signal_label(t), "family": fam, "family_label": family_label(fam),
                                  "tier": config.FAMILY_TIER.get(fam, "M"), "members": list(has), "raw": []})
        r["raw"].append(v)
    out = []
    tier_rank = {"S": 0, "M": 1, "W": 2}
    for r in rows.values():
        raw = sorted(r.pop("raw"))
        r["values"] = [{"value": v, "display": display_value(r["type"], v, cl)} for v in raw]
        r["thumbs"] = thumbs_for(raw, [items[m][0] for m in r["members"]]) if r["type"] == "asset_phash" else []
        out.append(r)
    out.sort(key=lambda r: (tier_rank[r["tier"]], -len(r["members"]), -config.INDICATOR_WEIGHT.get(r["type"], 0), r["type"]))
    return out


def _rows_cached(ci: int, items: dict, cl: dict) -> list[dict]:
    cache = cl.setdefault("_rows", {})
    if ci not in cache:
        cache[ci] = shared_rows(cl["profiles"][ci], items, cl)
    return cache[ci]


def campaign_card(ci: int, cl: dict, items: dict) -> dict:
    p = cl["profiles"][ci]
    rows = _rows_cached(ci, items, cl)
    persons = Counter(x for m in p["members"] for x in set(items[m][0].get("persons_visual", [])) | set(items[m][0].get("persons_named", [])))
    order = [m for g in cl.get("variants", {}).get(ci, []) for m in g] or p["members"]
    order += [m for m in p["members"] if m not in order]
    return {
        **camp_ref(ci, cl), "members": [mat_summary(m, items[m][0], cl) for m in order],
        "scam_types": [{"value": k, "label": enum_label(k), "n": v} for k, v in p["scam_types"].items()],
        "narratives": [{"value": k, "label": enum_label(k), "n": v} for k, v in p["narratives"].items()],
        "products": list(p["products"]), "persons": [x for x, _ in sorted(persons.items(), key=lambda kv: (-kv[1], kv[0]))],
        "domains": list(p["domains"]), "date_range": p["date_range"], "mean_internal_p": p["mean_internal_p"],
        "n_shared": sum(len(r["values"]) for r in rows), "n_shared_kinds": len(rows),
        "top_shared": [{"type": r["type"], "type_label": r["type_label"], "tier": r["tier"], "value": r["values"][0]["value"],
                        "display": r["values"][0]["display"], "n_values": len(r["values"]), "count": len(r["members"])}
                       for r in rows[:4]],
        "family": next((fi for fi, fam in enumerate(cl["families"]) if p["members"][0] in fam), None),
    }


def join_chain(mem: list[str], inner: list[Link], items: dict) -> list[dict]:
    """How the campaign holds together: maximum spanning tree of the strongest links, with their key reasons."""
    parent = {m: m for m in mem}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    out = []
    for l in sorted(inner, key=lambda l: (-round(l.p, 3), sorted((_name(items, l.a), _name(items, l.b))))):
        ra, rb = find(l.a), find(l.b)
        if ra == rb:
            continue
        parent[ra] = rb
        basis = link_basis(l)[0]
        best: dict[str, object] = {}
        for e in sorted([e for e in l.evidence if not e.ignored and e.weight > 0], key=lambda e: -e.weight):
            if config.FAMILY_TIER.get(e.family) == "W" or e.family in best:
                continue
            best[e.family] = e
        reasons = [detail_pl(e, short=True) for e in list(best.values())[:3]]
        out.append({"a": l.a, "b": l.b, "a_name": _name(items, l.a), "b_name": _name(items, l.b), "p": round(l.p, 3),
                    "relation": l.relation, "basis": basis, "reasons": reasons})
    return out


@app.get("/api/overview")
def overview():
    items, cl = _items(), _cl()
    camps = [campaign_card(ci, cl, items) for ci in range(len(cl["profiles"]))]
    rel = Counter(l.relation for l in cl["links"])
    fams = [{"id": fi, "campaigns": sorted({cl["campaign_of"][m] for m in fam}), "size": len(fam)}
            for fi, fam in enumerate(cl["families"]) if len({cl["campaign_of"][m] for m in fam}) > 1]
    return {
        "n_materials": len(items), "n_campaigns": len(camps),
        "n_multi": sum(1 for c in camps if c["size"] > 1), "n_singletons": sum(1 for c in camps if c["size"] == 1),
        "n_in_multi": sum(c["size"] for c in camps if c["size"] > 1),
        "n_duplicate_groups": len(cl["duplicates"]), "links": {k: rel.get(k, 0) for k in RELATION_PL},
        "families": [{**f, "refs": [camp_ref(c, cl) for c in f["campaigns"]]} for f in fams],
        "campaigns": camps, "examples": examples(items, cl),
    }


@app.get("/api/campaigns/{ci}")
def campaign_detail(ci: int):
    items, cl = _items(), _cl()
    if ci < 0 or ci >= len(cl["profiles"]):
        raise HTTPException(404, "Nie ma takiej kampanii (numeracja mogła się zmienić po przeliczeniu).")
    p = cl["profiles"][ci]
    mem = p["members"]
    card = campaign_card(ci, cl, items)
    mset = set(mem)
    inner = sorted([l for l in cl["links"] if l.a in mset and l.b in mset], key=lambda l: -l.p)
    outer = sorted([l for l in cl["links"] if (l.a in mset) ^ (l.b in mset) and l.p >= 0.15], key=lambda l: -l.p)
    nearest, seen = [], set()
    for l in outer:
        other = l.b if l.a in mset else l.a
        oc = cl["campaign_of"].get(other)
        if oc in seen:
            continue
        seen.add(oc)
        b = link_brief(l, items, cl)
        b["inside"] = l.a if l.a in mset else l.b
        b["outside_campaign"] = camp_ref(oc, cl)
        nearest.append(b)
        if len(nearest) >= 5:
            break
    fam_i = card["family"]
    siblings = []
    if fam_i is not None:
        siblings = [camp_ref(c, cl) for c in sorted({cl["campaign_of"][m] for m in cl["families"][fam_i]}) if c != ci]
    return {**card, "matrix": _rows_cached(ci, items, cl), "chain": join_chain(mem, inner, items),
            "links": [link_brief(l, items, cl) for l in inner], "nearest_outside": nearest, "siblings": siblings,
            "variants": cl.get("variants", {}).get(ci, []), "titles": p["titles"],
            "n_pairs": len(mem) * (len(mem) - 1) // 2}


# =============================================================================== materials
@app.get("/api/materials")
def materials():
    items, cl = _items(), _cl()
    out = [mat_summary(m, f, cl) for m, (f, _) in items.items()]
    return sorted(out, key=lambda d: ((d["campaign"] or {}).get("id", 999), d["name"]))


def _indicator_groups(f: dict, corpus_df: Counter, items: dict, cl: dict) -> list[dict]:
    by_fam = defaultdict(list)
    for t, vals in f.get("indicators", {}).items():
        fam = config.INDICATOR_FAMILY.get(t)
        if fam is None or t not in config.INDICATOR_WEIGHT:
            continue
        vals = sorted(vals, key=lambda v: (-corpus_df.get((t, v), 1), v))      # shared values first
        by_fam[fam].append({"type": t, "type_label": signal_label(t),
                            "values": [{"value": v, "display": display_value(t, v, cl), "df": corpus_df.get((t, v), 1),
                                        "thumb": (thumbs_for([v], [f]) or [None])[0] if t == "asset_phash" else None} for v in vals[:12]],
                            "more": max(0, len(vals) - 12)})
    out = []
    for fam in FAMILY_ORDER:
        if fam in by_fam:
            out.append({"family": fam, "label": family_label(fam), "tier": config.FAMILY_TIER.get(fam, "W"),
                        "hint": FAMILY_HINT.get(fam, ""), "items": sorted(by_fam[fam], key=lambda x: x["type_label"])})
    return out


def material_features(f: dict, items: dict | None = None) -> dict:
    """Curated view of the extracted features (no raw minhash/vector dumps)."""
    items = items if items is not None else _items()
    cl = _cl()
    df = Counter()
    for g, _ in items.values():
        for t, vals in g.get("indicators", {}).items():
            for v in set(vals):
                df[(t, v)] += 1
    llm = f.get("llm") or {}
    llm_rows = []
    for k, lab in LLM_FIELDS_PL:
        v = llm.get(k)
        if v in (None, "", [], "other"):
            continue
        llm_rows.append({"key": k, "label": lab, "value": [enum_label(x) for x in v] if isinstance(v, list) else enum_label(v)})
    for k, v in (llm.get("extra") or {}).items():
        if v and str(v).lower() not in ("unknown", "null", "none", "brak"):
            llm_rows.append({"key": f"extra:{k}", "label": k.replace("_", " "), "value": v, "discovered": True})
    t = f.get("text", {})
    w = f.get("web", {})
    images = []
    for im in f.get("images", [])[:24]:
        images.append({"url": file_url(im["src"]) if _abs(im["src"]).exists() else None, "kind": im.get("kind"),
                       "ocr": (im.get("ocr_text") or "")[:400], "qr": im.get("qr", []),
                       "faces": [{"identity": fc.get("identity"), "sim": round(fc.get("sim", 0), 2)} for fc in im.get("faces", [])]})
    assets = [file_url(a) for a in (f.get("_material") or {}).get("assets", [])[:60]
              if Path(a).suffix.lower() in WEB_IMG and _abs(a).exists()][:12]
    infra = [{"domain": d, **{k: v for k, v in (x or {}).items()}} for d, x in (f.get("infra") or {}).items()]
    backend = llm.get("_backend")
    return {
        "summary": llm.get("summary_pl"), "llm_backend": backend, "llm_backend_label": BACKEND_PL.get(backend, backend),
        "llm": llm_rows,
        "text": {"titles": t.get("titles", []), "excerpt": (t.get("excerpt") or "")[:900], "keywords": t.get("keywords", [])[:15],
                 "amounts": t.get("amounts", [])[:12], "brands": t.get("brands_text", []), "media": t.get("media_text", []),
                 "n_chars": t.get("n_chars", 0)},
        "persons": {"faces": f.get("persons_visual", []), "named": f.get("persons_named", [])},
        "web": {"landing_urls": w.get("landing_urls", [])[:6], "landing_domains": w.get("landing_domains", []),
                "redirect_chains": w.get("redirect_chains", [])[:5], "ips": w.get("ips", [])[:12],
                "server_headers": w.get("server_headers", [])[:8], "behind_cloudflare": f.get("behind_cloudflare"),
                "infra": infra, "has_web": bool(w.get("landing_urls") or w.get("landing_domains") or w.get("ips") or infra)},
        "indicators": _indicator_groups(f, df, items, cl), "n_corpus": len(items),
        "images": images, "assets": assets, "n_assets_total": len((f.get("_material") or {}).get("assets", [])),
        "ocr_links": sorted(set(f.get("indicators", {}).get("ocr_domain", [])) | {q for im in f.get("images", []) for q in im.get("qr", [])}),
        "notes": f.get("notes", []), "dates": f.get("dates", []), "elapsed_s": f.get("elapsed_s"),
    }


@app.get("/api/materials/{mid}")
def material_detail(mid: str):
    items, cl = _items(), _cl()
    if mid not in items:
        raise HTTPException(404, "Nie znaleziono materiału o tym identyfikatorze.")
    f = items[mid][0]
    m = f.get("_material") or {}
    links = sorted([l for l in cl["links"] if mid in (l.a, l.b)], key=lambda l: -l.p)
    return {**mat_summary(mid, f, cl), "source_ref": m.get("source_ref"),
            "inputs": {"pages": [Path(p["path"]).name for p in m.get("pages", [])], "images": len(m.get("images", [])),
                       "videos": len(m.get("videos", [])), "assets": len(m.get("assets", [])), "urls": m.get("urls", [])},
            "features": material_features(f, items),
            "links": [link_brief(l, items, cl, me=mid) for l in links if l.p >= 0.05][:12]}


@app.get("/api/pair/{a}/{b}")
def pair_detail(a: str, b: str):
    items, cl = _items(), _cl()
    if a not in items or b not in items:
        raise HTTPException(404, "Nie znaleziono materiału o tym identyfikatorze.")
    l = find_link(a, b)
    return {"a": mat_summary(a, items[a][0], cl), "b": mat_summary(b, items[b][0], cl), **explain_link(l, items)}


@app.get("/api/links")
def links(min_p: float = 0.0):
    items, cl = _items(), _cl()
    return [link_brief(l, items, cl) for l in sorted(cl["links"], key=lambda l: -l.p) if l.p >= min_p]


@app.get("/api/graph")
def graph(traces: bool = False):
    """Nodes/edges for the network view: materials grouped in campaign boxes; optional shared-trace nodes
    (operator and kit/content traces only — context traces like persons would turn the graph into a hairball)."""
    items, cl = _items(), _cl()
    nodes, edges = [], []
    for ci in range(len(cl["profiles"])):
        ref = camp_ref(ci, cl)
        nodes.append({"id": f"C{ci}", "kind": "campaign", "label": f"{ref['code']} · {ref['name']}", "campaign": ref})
    for mid, (f, _) in items.items():
        ci = cl["campaign_of"].get(mid)
        s = mat_summary(mid, f, cl)
        nodes.append({"id": mid, "kind": "material", "label": s["name"], "parent": f"C{ci}" if ci is not None else None,
                      "title": s["title"], "campaign": s["campaign"], "thumb": s["thumb"], "scam_type_label": s["scam_type_label"]})
    for l in cl["links"]:
        if l.p >= config.SIMILAR_THRESHOLD or l.relation in ("duplicate", "similar"):
            if l.relation == "none":
                continue
            b = link_brief(l, items, cl)
            edges.append({"id": f"{l.a}|{l.b}", "source": l.a, "target": l.b, "kind": "link", "p": b["p"],
                          "relation": l.relation, "relation_label": b["relation_label"], "reasons": b["reasons"],
                          "families": b["families"][:4],
                          "same_campaign_box": cl["campaign_of"].get(l.a) == cl["campaign_of"].get(l.b)})
    if traces:
        from .graph import IND_TYPES_IN_GRAPH

        holders = defaultdict(set)
        for mid, (f, _) in items.items():
            for t, vals in f.get("indicators", {}).items():
                if t in IND_TYPES_IN_GRAPH | {"landing_domain", "product", "asset_phash"}:
                    for v in vals:
                        holders[(t, v)].add(mid)
        grouped: dict[tuple, list] = defaultdict(list)      # many identical images between the same pages -> one node
        for (t, v), ms in holders.items():
            if len(ms) >= 2 and not (t == "phrase" and _generic_phrase(v)):
                grouped[(t, tuple(sorted(ms)))].append(v)
        for (t, ms), vals in grouped.items():
            fam = config.INDICATOR_FAMILY.get(t, "kit")
            tier = config.FAMILY_TIER.get(fam, "W")
            if tier == "W":
                continue
            vals = sorted(vals)
            tid = f"t:{t}:{vals[0]}"
            disp = display_value(t, vals[0], cl) if len(vals) == 1 else f"×{len(vals)}"
            if t == "asset_phash":
                disp = "1 obraz" if len(vals) == 1 else f"{len(vals)} obrazy" if len(vals) < 5 else f"{len(vals)} obrazów"
            nodes.append({"id": tid, "kind": "trace", "label": disp if len(disp) <= 26 else disp[:24] + "…", "full": vals[0],
                          "full_display": "obraz ze strony docelowej" if t == "asset_phash" else display_value(t, vals[0], cl),
                          "n_values": len(vals),
                          "type": t, "type_label": signal_label(t), "tier": tier, "n": len(ms)})
            for mid in ms:
                edges.append({"id": f"{tid}|{mid}", "source": mid, "target": tid, "kind": "trace"})
    return {"nodes": nodes, "edges": edges, "thresholds": {"link": config.LINK_THRESHOLD, "similar": config.SIMILAR_THRESHOLD},
            "counts": dict(Counter(e["relation"] for e in edges if e["kind"] == "link"))}


@app.get("/api/matrix")
def matrix():
    items, cl = _items(), _cl()
    order = []
    for ci, c in enumerate(cl["campaigns"]):
        v = [m for g in cl.get("variants", {}).get(ci, []) for m in g]
        order += v + [m for m in c if m not in v]
    idx = {m: i for i, m in enumerate(order)}
    n = len(order)
    P = [[None] * n for _ in range(n)]
    R = [[None] * n for _ in range(n)]
    for l in cl["links"]:
        i, j = idx[l.a], idx[l.b]
        P[i][j] = P[j][i] = round(l.p, 3)
        R[i][j] = R[j][i] = l.relation
    return {"materials": [{"id": m, "name": _name(items, m), "campaign": camp_ref(cl["campaign_of"].get(m), cl)} for m in order],
            "p": P, "relation": R, "thresholds": {"link": config.LINK_THRESHOLD, "similar": config.SIMILAR_THRESHOLD}}


@app.get("/api/trace")
def trace(type: str, value: str):
    """Pivot: every material carrying one trace value, with its rarity weight."""
    items, cl = _items(), _cl()
    corpus = Corpus(items)
    if type == "person":       # people are not indicators: recognised face or named in text (case-insensitive)
        q = fold(value).strip()
        holders = [m for m, (f, _) in items.items()
                   if any(fold(x) == q for x in set(f.get("persons_visual", [])) | set(f.get("persons_named", [])))]
        r = corpus.rarity(("person_visual", value), df=max(1, len(holders))) if holders else 0.0
        return {"type": type, "type_label": "osoba", "value": value, "display": value, "family": "persons",
                "family_label": family_label("persons"), "tier": "W", "prior": config.PERSON_REF_WEIGHT, "rarity": round(r, 3),
                "hub": bool(holders) and r == 0.0, "weight": round(config.PERSON_REF_WEIGHT * (0.35 + 0.65 * r), 3) if holders else None,
                "df": len(holders), "n": len(items), "thumbs": [],
                "materials": [mat_summary(m, items[m][0], cl) for m in holders]}
    holders = [m for m, (f, _) in items.items() if value in f.get("indicators", {}).get(type, [])]
    fam = config.INDICATOR_FAMILY.get(type, "kit")
    prior = config.INDICATOR_WEIGHT.get(type)
    r = corpus.rarity((type, value), df=len(holders)) if holders else 0.0
    return {"type": type, "type_label": signal_label(type), "value": value, "display": display_value(type, value, cl),
            "family": fam, "family_label": family_label(fam), "tier": config.FAMILY_TIER.get(fam, "W"), "prior": prior,
            "rarity": round(r, 3), "hub": bool(holders) and r == 0.0,
            "weight": round(prior * (0.35 + 0.65 * r), 3) if prior and holders else None, "df": len(holders), "n": len(items),
            "thumbs": thumbs_for([value], [items[m][0] for m in holders]) if type == "asset_phash" else [],
            "materials": [mat_summary(m, items[m][0], cl) for m in holders]}


@app.get("/api/search")
def search(q: str = Query(..., min_length=2)):
    items, cl = _items(), _cl()
    qq = fold(q).strip()
    code = re.fullmatch(r"c(\d+)", qq)
    camps = []
    for ci, p in enumerate(cl["profiles"]):
        ref = camp_ref(ci, cl)
        if (code and int(code.group(1)) == ci + 1) or (not code and qq in fold(ref["name"])):
            camps.append(ref)
    if code:                       # a campaign code is not a substring query (hashes contain "c1" too)
        return {"materials": [], "campaigns": camps, "traces": []}
    mats, traces = [], {}
    for mid, (f, _) in items.items():
        hits = []
        llm = f.get("llm") or {}
        fields = [("nazwa", f.get("name")), ("produkt", llm.get("product_or_platform_name"))] + \
                 [("tytuł", t) for t in f.get("text", {}).get("titles", [])] + \
                 [("osoba", p) for p in set(f.get("persons_visual", [])) | set(f.get("persons_named", []))]
        for lab, v in fields:
            if v and qq in fold(str(v)):
                hits.append({"field": lab, "value": str(v)})
                if lab == "osoba":
                    traces[("person", str(v))] = traces.get(("person", str(v)), 0) + 1
        for t, vals in f.get("indicators", {}).items():
            if t not in config.INDICATOR_WEIGHT:
                continue
            for v in vals:
                if qq in fold(v):
                    hits.append({"field": signal_label(t), "value": display_value(t, v, cl)})
                    traces[(t, v)] = traces.get((t, v), 0) + 1
        if hits:
            mats.append({**mat_summary(mid, f, cl), "hits": hits[:4]})
    return {"materials": mats[:30], "campaigns": camps[:10],
            "traces": [{"type": t, "type_label": "osoba" if t == "person" else signal_label(t), "value": v,
                        "display": v if t == "person" else display_value(t, v, cl), "n": n}
                       for (t, v), n in sorted(traces.items(), key=lambda kv: (-kv[1], kv[0][1]))[:15]]}


@app.get("/api/file")
def get_file(path: str):
    p = _abs(path).resolve()
    if not (str(p).startswith(str(config.DATA.resolve()) + "/")) or not p.is_file():
        raise HTTPException(404, "Plik niedostępny.")
    return FileResponse(p)


# =============================================================================== methodology & examples
def examples(items: dict, cl: dict) -> list[dict]:
    """Data-driven 'look at this' links: one example per concept the methodology explains."""
    out = []
    name = lambda m: _name(items, m)
    pair_title = lambda l: f"Materiał {name(l.a)} ↔ materiał {name(l.b)}"
    multi = [ci for ci, p in enumerate(cl["profiles"]) if p["size"] > 1]
    if multi:
        ci = multi[0]
        card = campaign_card(ci, cl, items)
        out.append({"kind": "campaign", "to": f"/campaigns/{ci}", "title": f"{card['code']} · {card['name']}",
                    "concept": "Kampania wielomateriałowa",
                    "text": f"{plural(card['size'], 'materiał', 'materiały', 'materiałów')} jednego operatora połączonych "
                            f"{card['n_shared']} wspólnymi wartościami — zobacz, który ślad łączy które materiały."})
    ls = sorted(cl["links"], key=lambda l: (-round(l.p, 3), sorted((name(l.a), name(l.b)))))
    op = next((l for l in ls if l.relation == "same_campaign" and link_basis(l)[2] >= 0.8), None)
    if op:
        top = max((e for e in op.evidence if not e.ignored and config.FAMILY_TIER.get(e.family) == "S"), key=lambda e: e.weight)
        out.append({"kind": "pair", "to": f"/pair/{op.a}/{op.b}", "title": pair_title(op), "concept": "Ślad operatora",
                    "text": f"{detail_pl(top)}. Jeden rzadki identyfikator wystarcza, by połączyć materiały."})
    inner_multi = {m for ci in multi for m in cl["profiles"][ci]["members"]}
    chain = next((l for l in ls if l.relation != "same_campaign" and l.a in inner_multi and l.b in inner_multi
                  and cl["campaign_of"][l.a] == cl["campaign_of"][l.b]), None)
    if chain:
        out.append({"kind": "pair", "to": f"/pair/{chain.a}/{chain.b}", "title": pair_title(chain), "concept": "Połączenie pośrednie",
                    "text": f"Bezpośrednio tylko p = {fp(chain.p)}, a mimo to obie są w jednej kampanii — łączą je inne materiały tej kampanii."})
    pb = next((l for l in ls if l.relation == "similar" and cl["campaign_of"][l.a] != cl["campaign_of"][l.b]
               and link_basis(l)[2] < 0.3 and any(f in l.families for f in ("narrative", "visual", "offer"))), None) or \
        next((l for l in ls if l.relation == "similar" and cl["campaign_of"][l.a] != cl["campaign_of"][l.b] and link_basis(l)[2] < 0.3), None)
    if pb:
        fams = ", ".join(family_label(f) for f, _ in sorted(pb.families.items(), key=lambda kv: -kv[1])[:3])
        out.append({"kind": "pair", "to": f"/pair/{pb.a}/{pb.b}", "title": pair_title(pb), "concept": "Podobny playbook, inny operator",
                    "text": f"p = {fp(pb.p)}: wspólne tylko {fams} — bez śladów operatora, więc osobne kampanie (ta sama rodzina)."})
    weak = next((l for l in ls if l.families and all(config.FAMILY_TIER.get(f) == "W" for f in l.families) and "persons" in l.families
                 and l is not pb), None)
    if weak:
        fams = " i ".join(family_label(f) for f in sorted(weak.families, key=lambda f: -weak.families[f]))
        out.append({"kind": "pair", "to": f"/pair/{weak.a}/{weak.b}", "title": pair_title(weak), "concept": "Sam kontekst to za mało",
                    "text": f"Wspólne tylko: {fams} → p = {fp(weak.p)}. Bez śladów operatora materiały pozostają w osobnych kampaniach."})
    single = next((ci for ci, p in enumerate(cl["profiles"]) if p["size"] == 1), None)
    if single is not None:
        ref = camp_ref(single, cl)
        out.append({"kind": "campaign", "to": f"/campaigns/{single}", "title": f"{ref['code']} · {ref['name']}",
                    "concept": "Kampania jednomateriałowa (nowy wzorzec)",
                    "text": "Materiał bez wspólnych śladów operatora z resztą bazy — tworzy osobną kampanię."})
    return out


@app.get("/api/methodology")
def methodology():
    items, cl = _items(), _cl()
    extra = {
        "duplicate": [("identyczny plik (sha256)", 0.99), ("ta sama treść, obraz i domena", 0.97)],
        "visual": [("ten sam kadr / zdjęcie twarzy (ArcFace ≥ 0.80)", 0.45)],
        "persons": [("rozpoznana twarz z bazy referencyjnej", config.PERSON_REF_WEIGHT), ("ta sama osoba wymieniona w treści", 0.22)],
        "concept": [(f"zgodny {k.replace('scam_type', 'typ oszustwa').replace('narrative_template', 'szablon narracji').replace('creative_format', 'format kreacji')}", w)
                    for k, w in config.CONCEPT_WEIGHTS.items()]
        + [("podszycie pod to samo medium", 0.2), ("zgodny atrybut odkryty przez LLM (max)", 0.25)],
    }
    fams = []
    for f in FAMILY_ORDER:
        inds = sorted([{"type": t, "label": signal_label(t), "weight": w} for t, w in config.INDICATOR_WEIGHT.items()
                       if config.INDICATOR_FAMILY.get(t) == f], key=lambda d: -d["weight"])
        inds += [{"type": f"rule:{i}", "label": lab, "weight": w} for i, (lab, w) in enumerate(extra.get(f, []))]
        cont = [{"name": k, "lo": v[0], "hi": v[1], "max_weight": v[2]} for k, v in config.CONTINUOUS.items() if v[3] == f]
        fams.append({"family": f, "label": family_label(f), "tier": config.FAMILY_TIER.get(f, "M"), "hint": FAMILY_HINT.get(f, ""),
                     "indicators": inds, "continuous": cont})
    corpus = Corpus(items)
    N = len(items)
    rarity_table = []
    for df in sorted({2, 3, max(2, N // 4), max(2, N // 2)}):
        r = corpus.rarity(("_", "_"), df=df)
        rarity_table.append({"df": df, "rarity": round(r, 2), "mult": round(0.35 + 0.65 * r, 2)})
    hub_df = max(config.HUB_MIN_COUNT, int(N * config.HUB_FRACTION) + 1)
    rarity_table.append({"df": hub_df, "rarity": 0.0, "mult": 0.0, "hub": True})
    ev = None
    rp = config.DATA / "eval" / "report_full_run.json"
    if not rp.exists():
        rp = config.DATA / "eval" / "report.json"
    if rp.exists():
        try:
            r = json.loads(rp.read_text(encoding="utf-8"))
            ev = {"file": str(rp.relative_to(config.ROOT)), "labels": r.get("labels"),
                  "leave_one_out": (r.get("leave_one_out") or {}).get("summary"),
                  "variants": (r.get("variants") or {}).get("summary")}
        except Exception:
            ev = None
    nm = lambda l: sorted((_name(items, l.a), _name(items, l.b)))
    cands = [l for l in cl["links"] if l.relation == "same_campaign" and 2 <= len(l.families) <= 5 and l.p < 0.995]
    cands.sort(key=lambda l: (-len(l.families), -round(l.p, 3), nm(l)))
    best = cands[0] if cands else min((l for l in cl["links"] if l.relation == "same_campaign"),
                                      key=lambda l: (-round(l.p, 3), nm(l)), default=None)
    worked = None
    if best:
        worked = {"a": mat_summary(best.a, items[best.a][0], cl), "b": mat_summary(best.b, items[best.b][0], cl),
                  **explain_link(best, items)}
        ind = max((e for e in best.evidence if not e.ignored and e.signal in config.INDICATOR_WEIGHT and e.value),
                  key=lambda e: e.weight, default=None)
        if ind:
            df = corpus.df.get((ind.signal, ind.value), 2)
            r = corpus.rarity((ind.signal, ind.value))
            worked["item"] = {"label": signal_label(ind.signal), "value": display_value(ind.signal, ind.value, cl),
                              "prior": config.INDICATOR_WEIGHT[ind.signal], "df": df, "n": N, "rarity": round(r, 2),
                              "weight": round(ind.weight, 3), "family": family_label(ind.family)}
    return {"tiers": [{"tier": t, "label": TIER_PL[t], "hint": TIER_HINT[t]} for t in ("S", "M", "W")],
            "families": fams, "rarity_table": rarity_table,
            "thresholds": {"link": config.LINK_THRESHOLD, "similar": config.SIMILAR_THRESHOLD, "duplicate": config.DUPLICATE_THRESHOLD,
                           "assign": config.ASSIGN_THRESHOLD, "candidate": config.CANDIDATE_THRESHOLD,
                           "weak_cap": config.WEAK_ONLY_CAP, "hub_fraction": config.HUB_FRACTION, "hub_min": config.HUB_MIN_COUNT,
                           "core_s": CORE_S_MIN, "strong_merge": STRONG_MERGE, "single_assign": SINGLE_ASSIGN,
                           "conflict": CONFLICT_FACTOR, "playbook": PLAYBOOK_MIN, "family_merge": FAMILY_MERGE},
            "relations": [{"relation": k, "label": RELATION_PL[k], "hint": RELATION_HINT[k]} for k in RELATION_PL],
            "decisions": [{"decision": k, "label": v[0], "hint": v[1]} for k, v in DECISION_PL.items()],
            "examples": examples(items, cl), "worked": worked, "evaluation": ev, "n_materials": N}


# =============================================================================== analysis of a new material
def _analysis_payload(res: dict, keep: bool, meta: dict) -> dict:
    items, cl = _items(), _cl()
    f = res["features"]
    m = res["material"]
    lab, desc = DECISION_PL[res["decision"]]
    scores = [{"score": s, **(camp_ref(c, cl) or {"id": c, "code": f"C{c + 1}", "name": "?", "size": 0, "color": None})}
              for s, c in res["campaign_scores"]]
    all_items = {**items, m.id: (f, res.get("vectors", {}))}
    links_out = []
    for l in res["links"][:10]:
        other = l.b
        links_out.append({"p": round(l.p, 3), "relation": l.relation, "relation_label": RELATION_PL[l.relation],
                          "families": fam_list(l.families),
                          "other": mat_summary(other, items[other][0], cl) if other in items else {"id": other, "name": other},
                          "explain": explain_link(l, all_items)})
    return {"decision": res["decision"], "decision_label": lab, "decision_hint": desc,
            "campaign": camp_ref(res["campaign"], cl) if res["campaign"] is not None else None,
            "similar_playbook": camp_ref(res.get("similar_playbook"), cl) if res.get("similar_playbook") is not None else None,
            "closest": scores[0] if scores else None, "scores": scores, "links": links_out,
            "kept": keep and m.id in items, "material_id": m.id, "name": m.name, "input": meta,
            "features": material_features({**f, "_material": m.to_dict()}, items),
            "thresholds": {"assign": config.ASSIGN_THRESHOLD, "candidate": config.CANDIDATE_THRESHOLD,
                           "similar": config.SIMILAR_THRESHOLD, "link": config.LINK_THRESHOLD}}


@app.post("/api/analyse")
async def analyse(mode: str = Form(...), url: str = Form(""), text: str = Form(""), render: bool = Form(True),
                  keep: bool = Form(True), use_llm: bool = Form(True), file: UploadFile | None = File(None)):
    data = await file.read() if file is not None else None
    fname = file.filename if file is not None else None
    if mode == "url" and not re.match(r"^https?://\S+\.\S+", url.strip()):
        raise HTTPException(400, "Podaj pełny adres URL zaczynający się od http:// lub https://.")
    if mode == "text" and not text.strip():
        raise HTTPException(400, "Wpisz tekst.")
    if mode == "file" and not data:
        raise HTTPException(400, "Wybierz plik.")
    src = url.strip() if mode == "url" else fname if mode == "file" else text.strip()
    meta = {"mode": mode, "source": (src or "")[:200], "use_llm": use_llm, "keep": keep, "render": render}

    def work(progress):
        if mode == "url":
            from .capture import capture_url

            progress("Pobieranie strony w 3 profilach klienta (wykrywanie cloakingu)…")
            cap_ = capture_url(url.strip(), render=render)
            progress("Cloaking: " + ("TAK — różna treść dla różnych klientów" if cap_.get("cloaking") else "nie wykryto"))
            m = ingest.from_url(url.strip(), cap_)
        elif mode == "file":
            m = ingest.from_upload(fname or "upload.bin", data)
        else:
            m = ingest.from_text(text.strip())
        progress("Ekstrakcja śladów…")
        res = eng().analyse_new(m, use_llm=use_llm, keep=keep, progress=progress)
        progress("Porównanie z bazą i decyzja.")
        return _analysis_payload(res, keep, meta)

    short = (src or "")[:60] + ("…" if len(src or "") > 60 else "")
    kind_pl = {"url": "adres", "file": "plik", "text": "tekst"}[mode] if mode in ("url", "file", "text") else mode
    return submit("analyse", f"Analiza ({kind_pl}): {short}", work, meta)


# =============================================================================== data management
class DatasetReq(BaseModel):
    path: str
    use_llm: bool = True
    force: bool = False


EVENT_PL = {"scan": "skan źródła", "scan_error": "błąd źródła", "scheduler_run": "skan zakończony", "analysed": "analiza materiału",
            "dataset": "import zbioru", "recluster": "przeliczenie kampanii"}


def event_view(e: dict) -> dict:
    k, p = e["kind"], e.get("payload") or {}
    src = str(p.get("source", ""))
    base, _, kw = src.partition(":")
    src_pl = SCAN_SOURCE_PL.get(base, base) + (f" (hasło „{kw}”)" if kw else "")
    if k == "scan":
        text = f"{src_pl}: {plural(int(p.get('n', 0)), 'pozycja', 'pozycje', 'pozycji')}"
    elif k == "scan_error":
        text = f"{src_pl}: niedostępne ({str(p.get('error', ''))[:120]})"
    elif k == "scheduler_run":
        text = f"znaleziono {p.get('found', 0)}, nowych {p.get('fresh', 0)}, przeanalizowano {len(p.get('analysed') or [])}"
    elif k == "analysed":
        dec = DECISION_PL.get(p.get("decision"), (p.get("decision"), ""))[0]
        c = p.get("campaign")
        text = f"„{str(p.get('name', ''))[:60]}” → {dec}" + (f" (C{c + 1})" if isinstance(c, int) else "")
    elif k == "dataset":
        text = f"{plural(int(p.get('n', 0)), 'przypadek', 'przypadki', 'przypadków')} z {p.get('path')} → {p.get('campaigns')} kampanii"
    elif k == "recluster":
        text = f"{p.get('campaigns')} kampanii ({p.get('seconds')} s)"
    else:
        text = json.dumps(p, ensure_ascii=False)[:160]
    return {"ts": e["ts"], "kind": k, "label": EVENT_PL.get(k, k), "text": text}


@app.get("/api/data")
def data_status():
    items, cl = _items(), _cl()
    by_src = Counter((f.get("_material") or {}).get("source", "?") for f, _ in items.values())
    store = config.STORE_PATH
    return {"n_materials": len(items), "n_campaigns": len(cl["campaigns"]),
            "n_multi": sum(1 for c in cl["campaigns"] if len(c) > 1),
            "by_source": {SOURCE_PL.get(k, k): v for k, v in by_src.items()},
            "last_added": max(((f.get("_material") or {}).get("created_at") or "" for f, _ in items.values()), default=None),
            "store": str(store.relative_to(config.ROOT)) if store.is_relative_to(config.ROOT) else str(store),
            "default_dataset": str((config.DATA / "organizer" / "dane").relative_to(config.ROOT)),
            "llm_backend": config.LLM_BACKEND, "llm_backend_label": BACKEND_PL.get(config.LLM_BACKEND, config.LLM_BACKEND),
            "llm_available": {"claude_cli": bool(shutil.which("claude")), "gemini": bool(os.environ.get("GEMINI_API_KEY"))},
            "neo4j": bool(os.environ.get("NEO4J_URI")),
            "recent": [event_view(e) for e in eng().store.events(20)]}


@app.post("/api/dataset")
def load_dataset(req: DatasetReq):
    p = Path(req.path)
    p = p if p.is_absolute() else config.ROOT / p
    if not p.is_dir():
        raise HTTPException(400, f"Folder nie istnieje: {req.path}")

    def work(progress):
        n = eng().add_dataset(p, use_llm=req.use_llm, progress=progress, force=req.force)
        progress("Przeliczanie kampanii…")
        cl = eng().clustering(refresh=True)
        eng().store.log("dataset", {"path": req.path, "n": n, "campaigns": len(cl["campaigns"])})
        return {"n": n, "campaigns": len(cl["campaigns"])}

    return submit("dataset", f"Import zbioru: {req.path}", work, {"path": req.path, "use_llm": req.use_llm, "force": req.force})


@app.post("/api/recluster")
def recluster():
    t = time.time()
    cl = eng().clustering(refresh=True)
    out = {"campaigns": len(cl["campaigns"]), "seconds": round(time.time() - t, 2)}
    eng().store.log("recluster", out)
    return out


@app.get("/api/export/{kind}")
def export(kind: str):
    items, cl = _items(), _cl()
    if kind == "campaigns.json":
        body = json.dumps([{"code": f"C{ci + 1}", "name": camp_ref(ci, cl)["name"],
                            **{k: v for k, v in p.items() if k != "members"},
                            "members": [_name(items, m) for m in p["members"]]} for ci, p in enumerate(cl["profiles"])],
                          ensure_ascii=False, indent=1, default=str)
        return Response(body, media_type="application/json", headers={"Content-Disposition": "attachment; filename=campaigns.json"})
    if kind == "links.csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["material_a", "campaign_a", "material_b", "campaign_b", "p", "relation", "families", "explanation"])
        code = lambda m: f"C{cl['campaign_of'][m] + 1}" if m in cl["campaign_of"] else ""
        for l in sorted(cl["links"], key=lambda l: -l.p):
            w.writerow([_name(items, l.a), code(l.a), _name(items, l.b), code(l.b), round(l.p, 3), RELATION_PL[l.relation],
                        "; ".join(f"{family_label(k)}={v:.2f}" for k, v in sorted(l.families.items(), key=lambda kv: -kv[1])),
                        "; ".join(r["detail"] for r in link_brief(l, items, cl)["reasons"])])
        return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=links.csv"})
    if kind == "graph.cypher":
        p = eng().export_cypher()
        return Response(p.read_text(encoding="utf-8"), media_type="text/plain",
                        headers={"Content-Disposition": "attachment; filename=graph.cypher"})
    raise HTTPException(404, "Nieznany format eksportu.")


@app.post("/api/neo4j")
def neo4j_push():
    from .graph import build_graph, push_neo4j

    cl = _cl()
    return {"message": push_neo4j(build_graph(_items(), cl, cl["profiles"]))}


# =============================================================================== scanner (ad libraries / CERT list)
class ScanReq(BaseModel):
    keywords: list[str] = []
    analyse: bool = False


class StartReq(BaseModel):
    minutes: int = 30
    keywords: list[str] = []
    analyse: bool = False


@app.get("/api/scanner")
def scanner_status():
    from . import scheduler

    running = bool(scheduler._SCHED and scheduler._SCHED.running)
    nxt = None
    if running:
        job = scheduler._SCHED.get_job("scan")
        nxt = str(job.next_run_time) if job and job.next_run_time else None
    found = eng().store.get("scheduler_found", [])
    for r in found:
        r["source_label"] = SCAN_SOURCE_PL.get(r.get("source", ""), r.get("source", ""))
    return {"running": running, "next_run": nxt, "config": scheduler.CURRENT if running else None,
            "default_keywords": scheduler.DEFAULT_KEYWORDS, "meta_token": bool(os.environ.get("META_ACCESS_TOKEN")),
            "found": sorted(found[-300:], key=lambda r: -(r.get("score") or 0)),
            "events": [event_view(e) for e in eng().store.events(80) if e["kind"] in ("scan", "scan_error", "scheduler_run", "analysed")]}


@app.post("/api/scanner/run")
def scanner_run(req: ScanReq):
    from . import scheduler

    def work(progress):
        progress("Skanowanie: lista CERT Polska, Microsoft Ad Library, Google Ads Transparency, Meta Ad Library…")
        return scheduler.run_once(eng(), keywords=req.keywords or None, analyse=req.analyse)

    return submit("scan", "Skan źródeł", work, {"keywords": req.keywords, "analyse": req.analyse})


@app.post("/api/scanner/start")
def scanner_start(req: StartReq):
    from . import scheduler

    minutes = min(1440, max(5, req.minutes))
    return {"message": scheduler.start_background(eng(), minutes=minutes, analyse=req.analyse, keywords=req.keywords or None)}


@app.post("/api/scanner/stop")
def scanner_stop():
    from . import scheduler

    return {"message": scheduler.stop_background()}


@app.get("/api/library-search")
def library_search(q: str = Query(..., min_length=2)):
    from . import scheduler, sources

    found, errors = [], {}
    for name, fn in (("Microsoft Ad Library", sources.ms_adlib_search), ("Google Ads Transparency", sources.google_atc_suggest),
                     ("Meta Ad Library", sources.meta_api_search)):
        try:
            res = fn(q)
            for r in res:
                r["score"], r["why"] = scheduler.suspicion(r)
                r["source_label"] = SCAN_SOURCE_PL.get(r.get("source", ""), r.get("source", ""))
            found += res
        except Exception as exc:
            errors[name] = str(exc)[:200]
    return {"results": sorted(found, key=lambda r: -r["score"])[:100], "errors": errors}


# =============================================================================== static web UI (built by `npm run build`)
WEB_DIST = config.ROOT / "web" / "dist"


@app.get("/api/health")
def health():
    return {"ok": True, "materials": eng().store.count()}


if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Nie ma takiego zasobu API."}, status_code=404)
        f = WEB_DIST / full_path
        if full_path and f.is_file():
            return FileResponse(f)
        return FileResponse(WEB_DIST / "index.html")
