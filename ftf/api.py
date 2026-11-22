"""FakerAlpha HTTP API (FastAPI) — serves curated, display-ready JSON to the web UI in `web/`.

Run:   python -m ftf.cli serve                    (UI at http://localhost:8765 after `npm run build` in web/)
Dev:   uvicorn ftf.api:app --reload --port 8765   +  `npm run dev` in web/ (Vite proxies /api)

The engine (feature extraction, similarity, clustering) is untouched; this layer only reshapes its output
into what an analyst needs to read: who is linked to whom and *why* — which identifiers the two materials share
(must-link) and how similar their content is in each view (text, semantic, HTML, images).
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
from dataclasses import replace
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
from .labels import (DECISION_PL, GROUP_HINT, GROUP_ORDER, LLM_FIELDS_PL, RELATION_HINT, RELATION_PL, SOURCE_PL, VIEW_HINT,
                     enum_label, group_label, signal_label, view_label)
from .similarity import VIEWS, Corpus, Link, SharedId, counted, pair

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


app = FastAPI(title="FakerAlpha API", version="1.0", lifespan=_lifespan)

_ENGINE: Engine | None = None
_ENGINE_LOCK = threading.Lock()

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
            hit = mp.get(h) or next((p for hh, p in mp.items()
                                     if bin(int(hh, 16) ^ int(h, 16)).count("1") <= config.PHASH_HAMMING), None)
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
        prod = (f.get("llm") or {}).get("product_or_platform_name")
        if prod:
            idx.setdefault(("product", fold(prod).strip()), prod)
    return idx


def display_value(t: str, v: str, cl: dict | None = None) -> str:
    if t == "product":
        cl = cl or _cl()
        if "_display" not in cl:
            cl["_display"] = _display_index(_items())
        return cl["_display"].get((t, v), v)
    return v


def _type0(s: SharedId) -> str:
    return s.type.split("+")[0]


def sid_detail(s: SharedId, n: int, short: bool = False) -> str:
    """'Facebook Pixel: „2012…” — w 2 z 10 materiałów' (+ 'zbyt popularne' when the df filter dropped it)."""
    txt = f"{cap(signal_label(_type0(s)))}: „{display_value(_type0(s), s.value)}”"
    if s.ignored:
        return f"{txt} — w {s.df} z {n} materiałów, zbyt popularne, by coś znaczyć"
    return txt if short else f"{txt} — w {s.df} z {n} materiałów"


def view_detail(v: str, score: float) -> str:
    return f"{cap(view_label(v))}: podobieństwo {score:.2f}"


def evidence_list(l: Link) -> list[dict]:
    """Everything a link rests on: counted identifiers, content views (high to low), then ignored identifiers."""
    ids = [{"kind": "identifier", "key": s.group, "label": f"wspólny identyfikator: {group_label(s.group)}",
            "type": _type0(s), "type_label": signal_label(_type0(s)), "value": display_value(_type0(s), s.value),
            "df": s.df, "ignored": s.ignored} for s in l.shared_ids]
    if l.same_file:
        ids.insert(0, {"kind": "identifier", "key": "file_sha", "label": "identyczny plik (sha256)", "type": "file_sha",
                       "type_label": "plik", "value": "", "df": 2, "ignored": False})
    k = max(1, len(l.views))
    views = [{"kind": "view", "key": v, "label": view_label(v), "score": round(s, 3), "contribution": round(s / k, 3)}
             for v, s in sorted(l.views.items(), key=lambda kv: -kv[1])]
    return [e for e in ids if not e["ignored"]] + views + [e for e in ids if e["ignored"]]


def reasons_of(l: Link, n_corpus: int, top: int = 3) -> list[dict]:
    """Up to `top` reasons: identifiers first (one per type), then the most similar content views."""
    out, seen = [], set()
    if l.same_file:
        out.append({"detail": "Identyczny plik (sha256)", "weight": 1.0, "kind": "identifier", "key": "file_sha"})
    for s in l.shared_ids:
        if not s.ignored and _type0(s) not in seen:
            seen.add(_type0(s))
            out.append({"detail": sid_detail(s, n_corpus), "weight": 1.0, "kind": "identifier", "key": s.group})
    for v, sc in sorted(l.views.items(), key=lambda kv: -kv[1]):
        if sc > 0:
            out.append({"detail": view_detail(v, sc), "weight": round(sc, 3), "kind": "view", "key": v})
    return out[:top]


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
    prod, stype = first_max(p.get("products")), first_max(p.get("scam_types"))
    main = prod or (enum_label(stype) if stype else None) or "bez nazwy"
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


def short_name(raw: str | None) -> str:
    """Short, non-overflowing display label for a material (especially URL-captured ones)."""
    s = str(raw or "").strip()
    if not s:
        return "—"
    if s.startswith(("http://", "https://")):
        from urllib.parse import urlparse

        u = urlparse(s)
        host = (u.netloc or "").removeprefix("www.")
        path = (u.path or "").strip("/")
        if not path:
            return host[:24] + ("…" if len(host) > 24 else "")
        tail = path.split("/")[-1]
        if len(tail) > 10:
            tail = "…" + tail[-6:]
        out = f"{host}/{tail}"
        return out if len(out) <= 24 else out[:23] + "…"
    return s if len(s) <= 28 else s[:27] + "…"


def _material_signals(f: dict) -> dict:
    """Compact feature-coverage flags for visual cards & filtering."""
    ind = f.get("indicators") or {}
    w = f.get("web") or {}
    llm = f.get("llm") or {}
    imgs = f.get("images") or []
    n_ind = sum(len(set(v)) for t, v in ind.items() if t in DISPLAY_TYPES)
    n_link = sum(len(set(v)) for t, v in ind.items() if t in config.IDENTIFIER_GROUP)
    n_faces = len(set(f.get("persons_visual") or []))
    has_ocr = any((im.get("ocr_text") or "").strip() for im in imgs)
    has_web = bool(w.get("landing_urls") or w.get("landing_domains") or w.get("ips") or f.get("infra"))
    has_infra = bool(f.get("infra"))
    has_llm = llm.get("_backend") not in (None, "rules", "none")
    return {
        "has_web": has_web,
        "has_infra": has_infra,
        "has_faces": n_faces > 0,
        "has_ocr": has_ocr,
        "has_llm": has_llm,
        "has_images": len(imgs) > 0,
        "n_indicators": n_ind,
        "n_linking_indicators": n_link,
        "n_faces": n_faces,
        "n_domains": len(w.get("landing_domains") or []),
    }


def mat_summary(mid: str, f: dict, cl: dict | None = None) -> dict:
    cl = cl or _cl()
    llm = f.get("llm") or {}
    thumb, thumb_kind = _thumb(f)
    titles = f.get("text", {}).get("titles") or []
    m = f.get("_material") or {}
    raw_name = str(f.get("name") or mid)
    return {
        "id": mid, "name": raw_name, "display_name": short_name(raw_name),
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
        "signals": _material_signals(f),
    }


def _name(items: dict, mid: str) -> str:
    return short_name(items[mid][0].get("name")) if mid in items else short_name(mid)


def link_brief(l: Link, items: dict, cl: dict, me: str | None = None) -> dict:
    d = {"a": l.a, "b": l.b, "p": round(l.p, 3), "distance": round(l.distance, 4), "relation": l.relation,
         "relation_label": RELATION_PL[l.relation], "evidence": evidence_list(l), "reasons": reasons_of(l, len(items)),
         "comparable": l.comparable}
    if me is not None:
        other = l.b if l.a == me else l.a
        d["other"] = mat_summary(other, items[other][0], cl) if other in items else {"id": other, "name": other}
    else:
        d["a_info"] = {"id": l.a, "name": _name(items, l.a), "campaign": camp_ref(cl["campaign_of"].get(l.a), cl)}
        d["b_info"] = {"id": l.b, "name": _name(items, l.b), "campaign": camp_ref(cl["campaign_of"].get(l.b), cl)}
    return d


def link_basis(l: Link) -> str:
    if l.relation == "duplicate":
        return "duplikat"
    if l.must_link:
        return "wspólny identyfikator"
    if not l.comparable:
        return "brak porównywalnej treści"
    return f"podobna treść (d = {l.distance:.2f})" if l.relation != "none" else f"odległa treść (d = {l.distance:.2f})"


def _rule(l: Link, n: int) -> str:
    counted = [s for s in l.shared_ids if not s.ignored]
    ids_txt = "; ".join(sid_detail(s, n, short=True) for s in counted[:3])
    d = f"d = {l.distance:.2f}"
    if l.relation == "duplicate":
        why = ("identyczny plik (sha256)" if l.same_file else
               "to samo ID reklamy" if any(s.group == "ad_library" and "ad_id" in s.type for s in counted) else
               f"odległość treści {d} ≤ {config.DUPLICATE_CUT}")
        return f"Duplikat: {why} — to ten sam materiał."
    if l.must_link:
        return (f"Wspólny identyfikator obecny w co najwyżej {config.MAX_DF:.0%} materiałów ({ids_txt}) — "
                "powiązanie pewne (must-link), p = 1.")
    if l.relation == "same_campaign":
        return f"Brak wspólnego identyfikatora, ale treść bliska: {d} ≤ {config.CAMPAIGN_CUT}."
    if l.relation == "similar":
        return (f"Brak wspólnego identyfikatora; {d} > {config.CAMPAIGN_CUT}, ale ≤ {config.FAMILY_CUT} — "
                "podobna treść, osobne kampanie (mogą należeć do jednej rodziny).")
    if not l.comparable:
        return "Brak wspólnego identyfikatora i brak porównywalnej treści (żaden widok nie jest dostępny po obu stronach)."
    return f"Brak wspólnego identyfikatora i {d} > {config.FAMILY_CUT}."


def _shared_assets(feats: list[dict]) -> list[str]:
    """Landing-page image hashes of the first material with a pHash match in the second (for thumbnails)."""
    if len(feats) < 2:
        return []
    A, B = (f.get("indicators", {}).get("asset_phash", []) for f in feats[:2])
    return [x for x in A if any(bin(int(x, 16) ^ int(y, 16)).count("1") <= config.PHASH_HAMMING for y in B)]


def explain_link(l: Link, items: dict | None = None) -> dict:
    """Full, step-by-step explanation of one pair (what the pair page renders)."""
    items = items if items is not None else _items()
    n = len(items)
    feats = [items[x][0] for x in (l.a, l.b) if x in items]
    by_group = defaultdict(list)
    for s in l.shared_ids:
        if not s.ignored:
            by_group[s.group].append({"type": _type0(s), "type_label": signal_label(_type0(s)), "value": s.value,
                                      "display": display_value(_type0(s), s.value), "df": s.df, "n": n,
                                      "detail": sid_detail(s, n)})
    identifiers = [{"group": g, "label": group_label(g), "hint": GROUP_HINT.get(g, ""), "items": by_group[g]}
                   for g in GROUP_ORDER if g in by_group]
    if l.same_file:
        identifiers.insert(0, {"group": "file_sha", "label": "identyczny plik", "hint": "ten sam plik (sha256) w obu materiałach",
                               "items": []})
    ignored = [{"detail": sid_detail(s, n), "type": _type0(s), "group": s.group, "df": s.df} for s in l.shared_ids if s.ignored]
    k = len(l.views)
    views = [{"view": v, "label": view_label(v), "hint": VIEW_HINT[v], "available": v in l.views,
              "score": round(l.views[v], 3) if v in l.views else None,
              "contribution": round(l.views[v] / k, 3) if v in l.views else None,
              "thumbs": thumbs_for(_shared_assets(feats), feats, 6) if v == "images" and l.views.get("images") else [],
              "note": (f"{l.local_images} dopasowane po punktach charakterystycznych (przycięta lub przeskalowana kopia)"
                       if v == "images" and l.local_images else "")}
             for v in VIEWS]
    formula = (f"d = 1 − ({' + '.join(f'{l.views[v]:.2f}' for v in VIEWS if v in l.views)}) / {k} = {l.distance:.2f}"
               if k else "d = 1 (brak widoku dostępnego po obu stronach)")
    return {"p": round(l.p, 3), "distance": round(l.distance, 4), "relation": l.relation,
            "relation_label": RELATION_PL[l.relation], "relation_hint": RELATION_HINT[l.relation], "rule": _rule(l, n),
            "basis": link_basis(l), "comparable": l.comparable, "must_link": l.must_link, "identifiers": identifiers,
            "ignored": ignored, "views": views, "n_views": k, "formula": formula, "evidence": evidence_list(l)}


def find_link(a: str, b: str) -> Link:
    for l in _cl()["links"]:
        if (l.a, l.b) in ((a, b), (b, a)):
            return l if l.a == a else replace(l, a=a, b=b)
    items = _items()
    if a not in items or b not in items:
        raise HTTPException(404, "Nie znaleziono materiału o tym identyfikatorze.")
    return pair(a, *items[a], b, *items[b], Corpus(items))


# =============================================================================== jobs (long-running work)
_POOL = ThreadPoolExecutor(max_workers=1)
_JOBS: dict[str, dict] = {}
_PROGRESS_PL = [("HAR: ", "Zapis ruchu sieciowego (HAR): "), ("HTML: ", "Zapisana strona: "), ("video keyframes: ", "Klatki wideo: "),
                ("image (", "Obraz ("), ("text embedding", "Embedding tekstu (e5)"), ("LLM attributes", "Atrybuty z modelu językowego"),
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
MATRIX_TYPES = set(config.IDENTIFIER_GROUP) | {"asset_phash"}


def _group_of(t: str) -> str:
    return config.IDENTIFIER_GROUP.get(t, "images" if t == "asset_phash" else "descriptive")


def _group_label(g: str) -> str:
    return {"images": "obrazy (widok treści)", "descriptive": "opisowe (nie łączą)"}.get(g) or group_label(g)


def _group_rank(g: str) -> int:
    return GROUP_ORDER.index(g) if g in GROUP_ORDER else len(GROUP_ORDER) + (g == "descriptive")


def shared_rows(p: dict, items: dict, cl: dict) -> list[dict]:
    """Every identifier value (and landing-page image) shared by >= 2 members, grouped by (type, set of members);
    page hosts that only repeat a landing domain are dropped."""
    mem = p["members"]
    cnt: dict[tuple, list[str]] = defaultdict(list)
    for m in mem:
        for t, vals in items[m][0].get("indicators", {}).items():
            if t in MATRIX_TYPES:
                for v in set(vals):
                    cnt[(t, v)].append(m)
    rows: dict[tuple, dict] = {}
    for (t, v), ms in cnt.items():
        if len(ms) < 2 or (t == "page_host" and len(cnt.get(("landing_domain", v), [])) >= len(ms)):
            continue
        has = tuple(m for m in mem if m in ms)
        g = _group_of(t)
        r = rows.setdefault((t, has), {"type": t, "type_label": signal_label(t), "group": g, "group_label": _group_label(g),
                                       "linking": t in config.IDENTIFIER_GROUP, "members": list(has), "raw": []})
        r["raw"].append(v)
    out = []
    for r in rows.values():
        raw = sorted(r.pop("raw"))
        r["values"] = [{"value": v, "display": display_value(r["type"], v, cl)} for v in raw]
        r["thumbs"] = thumbs_for(raw, [items[m][0] for m in r["members"]]) if r["type"] == "asset_phash" else []
        out.append(r)
    out.sort(key=lambda r: (_group_rank(r["group"]), -len(r["members"]), r["type"]))
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
    return {
        **camp_ref(ci, cl), "members": [mat_summary(m, items[m][0], cl) for m in p["members"]],
        "scam_types": [{"value": k, "label": enum_label(k), "n": v} for k, v in p["scam_types"].items()],
        "products": list(p["products"]), "persons": [x for x, _ in sorted(persons.items(), key=lambda kv: (-kv[1], kv[0]))],
        "domains": list(p["domains"]), "date_range": p["date_range"], "mean_internal_p": p["mean_internal_p"],
        "n_shared": sum(len(r["values"]) for r in rows), "n_shared_kinds": len(rows),
        "top_shared": [{"type": r["type"], "type_label": r["type_label"], "group": r["group"], "group_label": r["group_label"],
                        "linking": r["linking"],
                        "value": r["values"][0]["value"], "display": r["values"][0]["display"], "n_values": len(r["values"]),
                        "count": len(r["members"])} for r in rows[:4]],
        "family": cl["family_of"].get(p["members"][0]),
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
    for l in sorted(inner, key=lambda l: (-round(l.p, 3), l.distance, sorted((_name(items, l.a), _name(items, l.b))))):
        ra, rb = find(l.a), find(l.b)
        if ra == rb:
            continue
        parent[ra] = rb
        out.append({"a": l.a, "b": l.b, "a_name": _name(items, l.a), "b_name": _name(items, l.b), "p": round(l.p, 3),
                    "distance": round(l.distance, 4), "relation": l.relation, "basis": link_basis(l),
                    "reasons": [r["detail"] for r in reasons_of(l, len(items))]})
    return out


@app.get("/api/overview")
def overview():
    items, cl = _items(), _cl()
    camps = [campaign_card(ci, cl, items) for ci in range(len(cl["profiles"]))]
    rel = Counter(l.relation for l in cl["links"])
    fams = [{"id": fi, "campaigns": sorted({cl["campaign_of"][m] for m in fam}), "size": len(fam)}
            for fi, fam in enumerate(cl["families"]) if len({cl["campaign_of"][m] for m in fam}) > 1]
    dups = [[mat_summary(m, items[m][0], cl) for m in grp if m in items] for grp in cl["duplicates"]]
    return {
        "n_materials": len(items), "n_campaigns": len(camps),
        "n_multi": sum(1 for c in camps if c["size"] > 1), "n_singletons": sum(1 for c in camps if c["size"] == 1),
        "n_in_multi": sum(c["size"] for c in camps if c["size"] > 1),
        "n_duplicate_groups": len(cl["duplicates"]),
        "duplicates": [g for g in dups if len(g) > 1],
        "links": {k: rel.get(k, 0) for k in RELATION_PL},
        "families": [{**f, "refs": [camp_ref(c, cl) for c in f["campaigns"]]} for f in fams],
        "campaigns": camps, "examples": examples(items, cl), "thresholds": _thresholds(),
    }


def _campaign_view_profile(inner: list[Link], outer_all: list[Link]) -> list[dict]:
    """Mean similarity per content view inside the campaign vs against materials outside."""
    out = []
    for v in VIEWS:
        in_vals = [l.views[v] for l in inner if v in l.views]
        out_vals = [l.views[v] for l in outer_all if v in l.views]
        out.append({
            "view": v,
            "label": view_label(v),
            "inside": round(sum(in_vals) / len(in_vals), 3) if in_vals else None,
            "outside": round(sum(out_vals) / len(out_vals), 3) if out_vals else None,
            "n_inside": len(in_vals),
            "n_outside": len(out_vals),
        })
    return out


@app.get("/api/campaigns/{ci}")
def campaign_detail(ci: int):
    items, cl = _items(), _cl()
    if ci < 0 or ci >= len(cl["profiles"]):
        raise HTTPException(404, "Nie ma takiej kampanii (numeracja mogła się zmienić po przeliczeniu).")
    p = cl["profiles"][ci]
    mem = p["members"]
    card = campaign_card(ci, cl, items)
    mset = set(mem)
    inner = sorted([l for l in cl["links"] if l.a in mset and l.b in mset], key=lambda l: (-l.p, l.distance))
    outer_all = [l for l in cl["links"] if (l.a in mset) ^ (l.b in mset)]
    outer = sorted([l for l in outer_all if l.relation != "none"], key=lambda l: (-l.p, l.distance))
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
            "titles": p["titles"], "view_profile": _campaign_view_profile(inner, outer_all),
            "thresholds": _thresholds(),
            "n_pairs": len(mem) * (len(mem) - 1) // 2}


# =============================================================================== materials
@app.get("/api/materials")
def materials():
    items, cl = _items(), _cl()
    out = [mat_summary(m, f, cl) for m, (f, _) in items.items()]
    return sorted(out, key=lambda d: ((d["campaign"] or {}).get("id", 999), d["name"]))


DISPLAY_TYPES = MATRIX_TYPES | {"advertiser_name", "ip"}
_EXTRA_HINT = {"images": "obrazy ze stron docelowych — porównywane w widoku „obrazy” (pHash), nie jako identyfikator",
               "descriptive": "wyświetlane analitykowi, nigdy nie służą do łączenia"}


def _indicator_groups(f: dict, corpus_df: Counter, items: dict, cl: dict, limit: int | None = 12) -> list[dict]:
    """`limit` caps the values listed per identifier type (the panel shows 12); None lists all (CLI --all-values)."""
    by_group = defaultdict(list)
    for t, vals in f.get("indicators", {}).items():
        if t not in DISPLAY_TYPES:
            continue
        vals = sorted(vals, key=lambda v: (-corpus_df.get((t, v), 1), v))      # shared values first
        by_group[_group_of(t)].append({
            "type": t, "type_label": signal_label(t),
            "values": [{"value": v, "display": display_value(t, v, cl), "df": corpus_df.get((t, v), 1),
                        "thumb": (thumbs_for([v], [f]) or [None])[0] if t == "asset_phash" else None}
                       for v in (vals if limit is None else vals[:limit])],
            "more": 0 if limit is None else max(0, len(vals) - limit)})
    return [{"group": g, "label": _group_label(g), "linking": g in GROUP_ORDER, "hint": GROUP_HINT.get(g) or _EXTRA_HINT[g],
             "items": sorted(by_group[g], key=lambda x: x["type_label"])}
            for g in sorted(by_group, key=_group_rank)]


def view_status(f: dict, v: dict | None) -> list[dict]:
    """Which of the content views a material can be compared on, and what each one holds."""
    from .similarity import _images, ocr_signature

    v = v or {}
    t = f.get("text") or {}
    n_img = len(_images(f))
    dom = v.get("dom")
    sem = v.get("text")
    have = {
        "text": (t.get("minhash_masked") is not None, plural(t.get("n_chars", 0), "znak", "znaki", "znaków") + " tekstu strony"),
        "ocr": (ocr_signature(f) is not None, plural(len(t.get("ocr_text") or ""), "znak", "znaki", "znaków") + " odczytanych z kreacji"),
        "semantic": (sem is not None and len(sem) > 0, "wektor znaczenia tekstu (384 liczby)"),
        "html": (dom is not None and len(dom) > 0, "szablon znaczników HTML strony"),
        "css": (v.get("css") is not None and len(v["css"]) > 0, "zbiór nazw klas CSS strony"),
        "js": (v.get("js") is not None and len(v["js"]) > 0, "szkielet własnych skryptów strony"),
        "images": (n_img > 0, plural(n_img, "odcisk obrazu", "odciski obrazów", "odcisków obrazów")),
    }
    return [{"view": k, "label": view_label(k), "hint": VIEW_HINT[k], "available": bool(have[k][0]),
             "detail": have[k][1] if have[k][0] else None} for k in VIEWS]


def material_features(f: dict, items: dict | None = None, vec: dict | None = None) -> dict:
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
        "views": view_status(f, vec),
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
            "features": material_features(f, items, items[mid][1]),
            "links": [link_brief(l, items, cl, me=mid) for l in links if l.p >= 0.05][:12]}


@app.get("/api/materials/{mid}/seeds")
def material_seeds(mid: str):
    """Ready-to-search queries extracted from one material for inline further investigation."""
    items, cl = _items(), _cl()
    if mid not in items:
        raise HTTPException(404, "Nie znaleziono materiału o tym identyfikatorze.")
    f = items[mid][0]
    ind = f.get("indicators") or {}
    llm = f.get("llm") or {}
    t = f.get("text") or {}
    seeds: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, kind_label: str, value: str, *, can_library: bool = True, can_analyse_url: bool = False):
        v = str(value or "").strip()
        if not v or len(v) < 2:
            return
        key = (kind, fold(v))
        if key in seen:
            return
        seen.add(key)
        seeds.append({
            "kind": kind,
            "kind_label": kind_label,
            "value": v,
            "query": v,
            "can_library_search": can_library,
            "can_analyse_url": can_analyse_url,
        })

    for d in (f.get("web") or {}).get("landing_domains") or []:
        add("domain", "Domena", d, can_library=True, can_analyse_url=True)
    if llm.get("product_or_platform_name"):
        add("product", "Produkt / platforma", llm["product_or_platform_name"], can_library=True)
    for aid in ind.get("advertiser_id", [])[:3]:
        add("advertiser_id", "ID reklamodawcy", aid, can_library=True)
    for aname in ind.get("advertiser_name", [])[:3]:
        add("advertiser_name", "Reklamodawca", aname, can_library=True)
    for p in list(f.get("persons_visual") or []) + list(f.get("persons_named") or []):
        add("person", "Osoba", p, can_library=True)
    for u in sorted(set(ind.get("ocr_domain", [])) | {q for im in f.get("images", []) for q in im.get("qr", [])}):
        add("ocr_link", "Link z OCR / QR", u, can_library=True, can_analyse_url=True)
    for kw in (t.get("keywords") or [])[:5]:
        if len(kw.strip()) >= 4:
            add("keyword", "Słowo kluczowe", kw, can_library=True)

    return {
        "material_id": mid,
        "campaign": camp_ref(cl["campaign_of"].get(mid), cl),
        "seeds": seeds[:20],
    }


def _build_dendrogram(items: dict, cl: dict) -> dict | None:
    """Serialize the UPGMA dendrogram (exact same linkage as ftf/cluster.py) for SVG rendering."""
    ids = [m for c in cl["campaigns"] for m in c]
    n = len(ids)
    if n < 2:
        return None
    from scipy.cluster.hierarchy import linkage
    from scipy.spatial.distance import squareform

    from .cluster import distance_matrix

    D, _ = distance_matrix(ids, cl["links"])
    Z = linkage(squareform(D, checks=False), method="average")

    # Recursively compute leaf ordering (in-order traversal) and internal node coordinates.
    children: dict[int, tuple[int, int, float]] = {}
    for row_i, row in enumerate(Z):
        children[n + row_i] = (int(row[0]), int(row[1]), round(float(row[2]), 4))

    leaf_order: list[int] = []
    pos_map: dict[int, float] = {}

    def walk_pos(node_id: int) -> float:
        if node_id < n:
            pos = float(len(leaf_order))
            leaf_order.append(node_id)
            pos_map[node_id] = pos
            return pos
        l, r, _ = children[node_id]
        p = (walk_pos(l) + walk_pos(r)) / 2.0
        pos_map[node_id] = p
        return p

    root = 2 * n - 2
    walk_pos(root)

    leaves = []
    for x, idx in enumerate(leaf_order):
        mid = ids[idx]
        s = mat_summary(mid, items[mid][0], cl)
        leaves.append({
            "idx": idx,
            "x": x,
            "id": mid,
            "name": s["display_name"],
            "title": s["title"],
            "campaign": s["campaign"],
        })

    merges = []
    for row_i, row in enumerate(Z):
        nid = n + row_i
        l, r, dist = int(row[0]), int(row[1]), round(float(row[2]), 4)
        hl = 0.0 if l < n else children[l][2]
        hr = 0.0 if r < n else children[r][2]
        merges.append({
            "id": nid,
            "left_x": pos_map[l],
            "right_x": pos_map[r],
            "x": pos_map[nid],
            "left_y": hl,
            "right_y": hr,
            "y": dist,
        })

    return {
        "leaves": leaves,
        "merges": merges,
        "max_d": round(max(1.0, float(Z[:, 2].max())), 3),
        "thresholds": _thresholds(),
    }


@app.get("/api/metrics/overview")
def metrics_overview():
    """Aggregated metrics & chart series explaining how the database is grouped and what features exist."""
    items, cl = _items(), _cl()
    n = len(items)
    links_all = cl["links"]

    # 1. Pairwise content distance histogram (10 bins in [0, 1]) + must-link counts
    bins = [{"range": f"{i / 10:.1f}–{(i + 1) / 10:.1f}", "lo": round(i / 10, 1), "hi": round((i + 1) / 10, 1),
             "must_link": 0, "same_campaign": 0, "similar": 0, "none": 0, "total": 0}
            for i in range(10)]
    n_must_link = 0
    for l in links_all:
        bi = min(9, max(0, int(l.distance * 10)))
        b = bins[bi]
        b["total"] += 1
        if l.must_link:
            b["must_link"] += 1
            n_must_link += 1
        elif l.relation in ("same_campaign", "duplicate"):
            b["same_campaign"] += 1
        elif l.relation == "similar":
            b["similar"] += 1
        else:
            b["none"] += 1

    # 2. What drives links across the DB (signal group attribution)
    sig_pairs: Counter[str] = Counter()
    for l in links_all:
        if l.relation not in ("same_campaign", "duplicate"):
            continue
        if l.must_link:
            groups = set()
            if l.same_file:
                groups.add("file_sha")
            for s in l.shared_ids:
                if not s.ignored:
                    groups.add(s.group)
            for g in groups:
                sig_pairs[g] += 1
        else:
            sig_pairs["content_only"] += 1

    sig_labels = {
        **{g: group_label(g) for g in GROUP_ORDER},
        "file_sha": "identyczny plik (sha256)",
        "content_only": "wyłącznie podobieństwo treści",
    }
    signal_attribution = [
        {"group": g, "label": sig_labels.get(g, g), "pairs": cnt}
        for g, cnt in sig_pairs.most_common()
    ]

    # 3. Feature coverage across materials
    sigs = [_material_signals(f) for f, _ in items.values()]
    cov_defs = [
        ("has_web", "Strona docelowa (HTML / URL)", sum(1 for s in sigs if s["has_web"])),
        ("has_images", "Kreacje / zrzuty / klatki", sum(1 for s in sigs if s["has_images"])),
        ("has_ocr", "Tekst odczytany z obrazu (OCR)", sum(1 for s in sigs if s["has_ocr"])),
        ("has_faces", "Rozpoznane twarze (ArcFace)", sum(1 for s in sigs if s["has_faces"])),
        ("has_linking", "Identyfikatory techniczne (piksele/kit/domena)", sum(1 for s in sigs if s["n_linking_indicators"] > 0)),
        ("has_infra", "Metadane domen (RDAP / DNS / CERT)", sum(1 for s in sigs if s["has_infra"])),
        ("has_llm", "Atrybuty opisowe (LLM)", sum(1 for s in sigs if s["has_llm"])),
    ]
    feature_coverage = [
        {"key": k, "label": lab, "count": cnt, "total": n, "pct": round(100 * cnt / max(1, n))}
        for k, lab, cnt in cov_defs
    ]

    # 4. Scam types & top impersonated persons
    scam_cnt: Counter[str] = Counter()
    person_vis: Counter[str] = Counter()
    person_named: Counter[str] = Counter()
    person_any: Counter[str] = Counter()
    for f, _ in items.values():
        st = (f.get("llm") or {}).get("scam_type")
        scam_cnt[enum_label(st) if st else "nieokreślony"] += 1
        vis = set(f.get("persons_visual") or [])
        nam = set(f.get("persons_named") or [])
        for p in vis:
            person_vis[p] += 1
        for p in nam:
            person_named[p] += 1
        for p in vis | nam:
            person_any[p] += 1

    scam_types = [{"label": k, "count": v} for k, v in scam_cnt.most_common()]
    top_persons = [
        {"name": p, "count": cnt, "visual": person_vis[p], "named": person_named[p]}
        for p, cnt in person_any.most_common(10)
    ]

    # 5. View separation summary (mean similarity inside same campaign vs different campaigns)
    camp_of = cl["campaign_of"]
    view_summary = []
    for v in VIEWS:
        same_vals = [l.views[v] for l in links_all if v in l.views and camp_of.get(l.a) == camp_of.get(l.b)]
        diff_vals = [l.views[v] for l in links_all if v in l.views and camp_of.get(l.a) != camp_of.get(l.b)]
        view_summary.append({
            "view": v,
            "label": view_label(v),
            "mean_same": round(sum(same_vals) / len(same_vals), 3) if same_vals else 0.0,
            "mean_diff": round(sum(diff_vals) / len(diff_vals), 3) if diff_vals else 0.0,
            "n_same": len(same_vals),
            "n_diff": len(diff_vals),
        })

    return {
        "n_materials": n,
        "n_campaigns": len(cl["campaigns"]),
        "n_multi": sum(1 for c in cl["campaigns"] if len(c) > 1),
        "n_singletons": sum(1 for c in cl["campaigns"] if len(c) == 1),
        "n_pairs": len(links_all),
        "n_must_link": n_must_link,
        "thresholds": _thresholds(),
        "distance_histogram": bins,
        "signal_attribution": signal_attribution,
        "feature_coverage": feature_coverage,
        "scam_types": scam_types,
        "top_persons": top_persons,
        "view_summary": view_summary,
        "dendrogram": _build_dendrogram(items, cl),
    }


@app.get("/api/feature-space")
def feature_space_view():
    """2D projections of the content distance + alternative clusterings with their scores (ftf/explore.py)."""
    from .explore import feature_space

    items, cl = _items(), _cl()
    if "_space" not in cl:
        ids = [m for c in cl["campaigns"] for m in c]
        sizes = {ci: len(c) for ci, c in enumerate(cl["campaigns"])}
        res = feature_space(items, cl, ids, lambda ci: color_slot(ci, sizes.get(ci, 0))) if len(ids) >= 2 else \
            {"projections": {}, "methods": [], "identifier_edges": [], "labels": None, "campaign_cut": config.CAMPAIGN_CUT}
        res["points"] = [mat_summary(m, items[m][0], cl) for m in ids]
        cl["_space"] = res
    return cl["_space"]


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
    return [link_brief(l, items, cl) for l in sorted(cl["links"], key=lambda l: (-l.p, l.distance)) if l.p >= min_p]


def _thresholds() -> dict:
    """Cuts in p units (p = 1 - D) for filters/colour scales, plus the raw distance cuts."""
    return {"link": round(1 - config.CAMPAIGN_CUT, 3), "similar": round(1 - config.FAMILY_CUT, 3),
            "duplicate": round(1 - config.DUPLICATE_CUT, 3), "campaign_cut": config.CAMPAIGN_CUT,
            "family_cut": config.FAMILY_CUT, "duplicate_cut": config.DUPLICATE_CUT}


@app.get("/api/graph")
def graph(traces: bool = False):
    """Nodes/edges for the network view: materials grouped in campaign boxes; optional shared-trace nodes
    (identifier values and landing-page images held by >= 2 materials)."""
    items, cl = _items(), _cl()
    nodes, edges = [], []
    for ci in range(len(cl["profiles"])):
        ref = camp_ref(ci, cl)
        nodes.append({"id": f"C{ci}", "kind": "campaign", "label": f"{ref['code']} · {ref['name']}", "campaign": ref})
    for mid, (f, _) in items.items():
        ci = cl["campaign_of"].get(mid)
        s = mat_summary(mid, f, cl)
        nodes.append({"id": mid, "kind": "material", "label": s["display_name"], "parent": f"C{ci}" if ci is not None else None,
                      "title": s["title"], "campaign": s["campaign"], "thumb": s["thumb"], "scam_type_label": s["scam_type_label"]})
    for l in cl["links"]:
        if l.relation == "none":
            continue
        b = link_brief(l, items, cl)
        edges.append({"id": f"{l.a}|{l.b}", "source": l.a, "target": l.b, "kind": "link", "p": b["p"],
                      "distance": b["distance"], "relation": l.relation, "relation_label": b["relation_label"],
                      "reasons": b["reasons"], "evidence": b["evidence"][:4],
                      "same_campaign_box": cl["campaign_of"].get(l.a) == cl["campaign_of"].get(l.b)})
    if traces:
        holders = defaultdict(set)
        for mid, (f, _) in items.items():
            for t, vals in f.get("indicators", {}).items():
                if t in MATRIX_TYPES and t != "page_host":
                    for v in vals:
                        holders[(t, v)].add(mid)
        grouped: dict[tuple, list] = defaultdict(list)      # many identical images between the same pages -> one node
        for (t, v), ms in holders.items():
            if len(ms) >= 2:
                grouped[(t, tuple(sorted(ms)))].append(v)
        for (t, ms), vals in grouped.items():
            vals = sorted(vals)
            tid = f"t:{t}:{vals[0]}"
            disp = display_value(t, vals[0], cl) if len(vals) == 1 else f"×{len(vals)}"
            if t == "asset_phash":
                disp = "1 obraz" if len(vals) == 1 else f"{len(vals)} obrazy" if len(vals) < 5 else f"{len(vals)} obrazów"
            nodes.append({"id": tid, "kind": "trace", "label": disp if len(disp) <= 26 else disp[:24] + "…", "full": vals[0],
                          "full_display": "obraz ze strony docelowej" if t == "asset_phash" else display_value(t, vals[0], cl),
                          "n_values": len(vals), "type": t, "type_label": signal_label(t), "group": _group_of(t),
                          "group_label": _group_label(_group_of(t)), "n": len(ms)})
            for mid in ms:
                edges.append({"id": f"{tid}|{mid}", "source": mid, "target": tid, "kind": "trace"})
    return {"nodes": nodes, "edges": edges, "thresholds": _thresholds(),
            "counts": dict(Counter(e["relation"] for e in edges if e["kind"] == "link"))}


@app.get("/api/matrix")
def matrix():
    items, cl = _items(), _cl()
    order = [m for c in cl["campaigns"] for m in c]
    idx = {m: i for i, m in enumerate(order)}
    n = len(order)
    P = [[None] * n for _ in range(n)]
    Dm = [[None] * n for _ in range(n)]
    R = [[None] * n for _ in range(n)]
    for l in cl["links"]:
        i, j = idx[l.a], idx[l.b]
        P[i][j] = P[j][i] = round(l.p, 3)
        Dm[i][j] = Dm[j][i] = round(l.distance, 4)
        R[i][j] = R[j][i] = l.relation
    return {"materials": [{"id": m, "name": _name(items, m), "campaign": camp_ref(cl["campaign_of"].get(m), cl)} for m in order],
            "p": P, "distance": Dm, "relation": R, "thresholds": _thresholds()}


@app.get("/api/trace")
def trace(type: str, value: str):
    """Pivot: every material carrying one trace value, with its document frequency (df / N vs MAX_DF)."""
    items, cl = _items(), _cl()
    n = len(items)
    if type == "person":       # people are descriptive: recognised face or named in text (case-insensitive)
        q = fold(value).strip()
        holders = [m for m, (f, _) in items.items()
                   if any(fold(x) == q for x in set(f.get("persons_visual", [])) | set(f.get("persons_named", [])))]
        return {"type": type, "type_label": "osoba", "value": value, "display": value, "group": "descriptive",
                "group_label": _group_label("descriptive"), "linking": False, "counted": False, "df": len(holders), "n": n,
                "max_df": config.MAX_DF, "thumbs": [], "materials": [mat_summary(m, items[m][0], cl) for m in holders]}
    holders = [m for m, (f, _) in items.items() if value in f.get("indicators", {}).get(type, [])]
    linking = type in config.IDENTIFIER_GROUP
    return {"type": type, "type_label": signal_label(type), "value": value, "display": display_value(type, value, cl),
            "group": _group_of(type), "group_label": _group_label(_group_of(type)), "linking": linking,
            "counted": linking and counted(len(holders), n),
            "df": len(holders), "n": n, "max_df": config.MAX_DF,
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
            if t not in DISPLAY_TYPES or t == "asset_phash":
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
    n = len(items)
    name = lambda m: _name(items, m)
    pair_title = lambda l: f"Materiał {name(l.a)} ↔ materiał {name(l.b)}"
    camp = cl["campaign_of"]
    multi = [ci for ci, p in enumerate(cl["profiles"]) if p["size"] > 1]
    if multi:
        ci = multi[0]
        card = campaign_card(ci, cl, items)
        out.append({"kind": "campaign", "to": f"/campaigns/{ci}", "title": f"{card['code']} · {card['name']}",
                    "concept": "Kampania wielomateriałowa",
                    "text": f"{plural(card['size'], 'materiał', 'materiały', 'materiałów')} połączonych "
                            f"{card['n_shared']} wspólnymi wartościami — zobacz, który ślad łączy które materiały."})
    ls = sorted(cl["links"], key=lambda l: (-round(l.p, 3), l.distance, sorted((name(l.a), name(l.b)))))
    op = next((l for l in ls if l.must_link and l.relation == "same_campaign" and l.shared_ids), None)
    if op:
        top = next(s for s in op.shared_ids if not s.ignored)
        out.append({"kind": "pair", "to": f"/pair/{op.a}/{op.b}", "title": pair_title(op), "concept": "Wspólny identyfikator",
                    "text": f"{sid_detail(top, n)}. Jeden rzadki wspólny identyfikator wystarcza, by połączyć materiały."})
    inner_multi = {m for ci in multi for m in cl["profiles"][ci]["members"]}
    chain = next((l for l in ls if l.relation not in ("same_campaign", "duplicate") and l.a in inner_multi
                  and l.b in inner_multi and camp[l.a] == camp[l.b]), None)
    if chain:
        out.append({"kind": "pair", "to": f"/pair/{chain.a}/{chain.b}", "title": pair_title(chain), "concept": "Połączenie pośrednie",
                    "text": f"Bezpośrednio brak wspólnego identyfikatora (d = {chain.distance:.2f}), a mimo to obie są w jednej "
                            "kampanii — łączą je inne materiały tej kampanii."})
    sim = next((l for l in sorted(ls, key=lambda l: l.distance) if l.relation == "similar" and camp[l.a] != camp[l.b]), None)
    if sim:
        vs = ", ".join(f"{view_label(v)} {x:.2f}" for v, x in sorted(sim.views.items(), key=lambda kv: -kv[1]) if x > 0)
        out.append({"kind": "pair", "to": f"/pair/{sim.a}/{sim.b}", "title": pair_title(sim), "concept": "Podobna treść, inna kampania",
                    "text": f"d = {sim.distance:.2f} ({vs}) — bez wspólnego identyfikatora i d > {config.CAMPAIGN_CUT}, więc osobne "
                            "kampanie; obie w jednej rodzinie."})
    hub = next((l for l in ls if any(s.ignored for s in l.shared_ids) and not l.must_link), None)
    if hub:
        s0 = next(s for s in hub.shared_ids if s.ignored)
        out.append({"kind": "pair", "to": f"/pair/{hub.a}/{hub.b}", "title": pair_title(hub), "concept": "Zbyt popularna wartość",
                    "text": f"{sid_detail(s0, n)}. Wartość obecna w ponad {config.MAX_DF:.0%} materiałów jest pomijana."})
    persons = lambda m: set(items[m][0].get("persons_visual", [])) | set(items[m][0].get("persons_named", []))
    same_face = next((l for l in ls if l.relation == "none" and persons(l.a) & persons(l.b)), None)
    if same_face:
        who = sorted(persons(same_face.a) & persons(same_face.b))[0]
        out.append({"kind": "pair", "to": f"/pair/{same_face.a}/{same_face.b}", "title": pair_title(same_face),
                    "concept": "Ta sama osoba to za mało",
                    "text": f"Oba materiały wykorzystują wizerunek: {who}. Osoby są tylko opisem — bez wspólnego identyfikatora "
                            f"i przy d = {same_face.distance:.2f} materiały są w osobnych kampaniach."})
    single = next((ci for ci, p in enumerate(cl["profiles"]) if p["size"] == 1), None)
    if single is not None:
        ref = camp_ref(single, cl)
        out.append({"kind": "campaign", "to": f"/campaigns/{single}", "title": f"{ref['code']} · {ref['name']}",
                    "concept": "Kampania jednomateriałowa (nowy wzorzec)",
                    "text": "Materiał bez wspólnych identyfikatorów i bez bliskiej treści z resztą bazy — tworzy osobną kampanię."})
    return out


REFERENCES = [
    ("christen2012", "Christen, Data Matching, Springer 2012", "https://doi.org/10.1007/978-3-642-31164-2"),
    ("starov2018", "Starov et al., Betrayed by Your Dashboard, WWW 2018", "https://doi.org/10.1145/3178876.3186089"),
    ("sparckjones1972", "Spärck Jones, A statistical interpretation of term specificity, J. Documentation 1972",
     "https://doi.org/10.1108/eb026526"),
    ("bijmans2021", "Bijmans et al., Catching Phishers By Their Bait, USENIX Security 2021",
     "https://www.usenix.org/conference/usenixsecurity21/presentation/bijmans"),
    ("jaccard1912", "Jaccard, New Phytologist 1912", "https://doi.org/10.1111/j.1469-8137.1912.tb05611.x"),
    ("broder1997", "Broder, On the resemblance and containment of documents, 1997", "https://doi.org/10.1109/SEQUEN.1997.666900"),
    ("wang2024", "Wang et al., Multilingual E5, 2024", "https://arxiv.org/abs/2402.05672"),
    ("mu2018", "Mu & Viswanath, All-but-the-Top, ICLR 2018", "https://arxiv.org/abs/1702.01417"),
    ("cui2017", "Cui et al., Tracking Phishing Attacks Over Time, WWW 2017", "https://doi.org/10.1145/3038912.3052654"),
    ("zauner2010", "Zauner, Implementation and Benchmarking of Perceptual Image Hash Functions, 2010",
     "https://phash.org/docs/pubs/thesis_zauner.pdf"),
    ("deng2019", "Deng et al., ArcFace, CVPR 2019", "https://arxiv.org/abs/1801.07698"),
    ("guo2021", "Guo et al., SCRFD, 2021", "https://arxiv.org/abs/2105.04714"),
    ("gower1971", "Gower, A general coefficient of similarity, Biometrics 1971", "https://doi.org/10.2307/2528823"),
    ("mullner2011", "Müllner, Modern hierarchical, agglomerative clustering algorithms, 2011", "https://arxiv.org/abs/1109.2378"),
    ("campello2013", "Campello et al., HDBSCAN, PAKDD 2013", "https://doi.org/10.1007/978-3-642-37456-2_14"),
    ("cover1967", "Cover & Hart, Nearest neighbor pattern classification, IEEE Trans. Inf. Theory 13(1):21–27, 1967",
     "https://doi.org/10.1109/TIT.1967.1053964"),
    ("bendale2015", "Bendale & Boult, Towards Open World Recognition, CVPR 2015", "https://arxiv.org/abs/1412.5687"),
    ("hubert1985", "Hubert & Arabie, Comparing partitions (ARI), 1985", "https://doi.org/10.1007/BF01908075"),
    ("amigo2009", "Amigó et al., B-cubed, 2009", "https://doi.org/10.1007/s10791-008-9066-8"),
]


def method_steps() -> list[dict]:
    c = config
    return [
        {"step": 1, "title": "Wspólne identyfikatory → połączenie pewne",
         "text": "Para materiałów, które mają identyczną wartość identyfikatora (domena, piksel / ID analityki, kontakt, plik lub "
                 "szablon kitu, ID reklamy, nazwa produktu), trafia do jednej kampanii (must-link, spójne składowe grafu). "
                 f"Wartość liczy się tylko, gdy występuje w co najwyżej {c.MAX_DF:.0%} materiałów — zbyt popularne wartości "
                 "są pokazywane, ale pomijane.", "refs": ["christen2012", "starov2018", "sparckjones1972", "bijmans2021"]},
        {"step": 2, "title": "Odległość treści (Gower)",
         "text": f"{cap(plural(len(VIEWS), 'widok', 'widoki', 'widoków'))} treści, każdy ze standardową miarą podobieństwa w [0, 1]: tekst strony i tekst kreacji (OCR) "
                 f"(MinHash-Jaccard 4-gramów słów), {view_label('semantic')} (cosinus), struktura HTML (MinHash-Jaccard znaczników), obrazy "
                 "(pHash). d = 1 − średnia z widoków "
                 "dostępnych po obu stronach; brakujące widoki są pomijane, więc każdy widok wnosi dokładnie s/k.",
         "refs": ["gower1971", "jaccard1912", "broder1997", "wang2024", "mu2018", "cui2017", "zauner2010"]},
        {"step": 3, "title": "Grupowanie hierarchiczne",
         "text": "D = 0 wewnątrz składowej must-link, w przeciwnym razie D = d. Grupowanie aglomeracyjne ze średnim wiązaniem "
                 f"(UPGMA): kampanie = cięcie dendrogramu na wysokości {c.CAMPAIGN_CUT}, rodziny = cięcie na {c.FAMILY_CUT}. "
                 "HDBSCAN na tym samym D jako punkt odniesienia.", "refs": ["mullner2011", "campello2013"]},
        {"step": 4, "title": "Nowy materiał (zbiór otwarty)",
         "text": "Wspólny identyfikator z jedną kampanią → znana kampania; z dwiema lub więcej → propozycja scalenia. W przeciwnym "
                 f"razie najbliższy znany materiał (1-NN): d ≤ {c.CAMPAIGN_CUT} → jego kampania, inaczej nowy wzorzec "
                 f"(z najbliższym materiałem; przy d ≤ {c.FAMILY_CUT} także podobna rodzina). Grupowanie pyta „które "
                 "materiały tworzą grupę”, przypisanie — „czy to wariant znanego materiału”, stąd najbliższy sąsiad. "
                 f"Duplikat: ten sam plik, to samo ID reklamy lub d ≤ {c.DUPLICATE_CUT}.", "refs": ["cover1967", "bendale2015"]},
        {"step": 5, "title": "Cechy opisowe",
         "text": "Osoby (ArcFace + gazetteer), typ oszustwa, słowa kluczowe, kwoty, rejestrator / data utworzenia / NS / "
                 "IP / lista CERT Polska, reklamodawca, podszyte medium i marki — wyświetlane analitykowi, nigdy nie łączą.",
         "refs": ["deng2019", "guo2021"]},
    ]


@app.get("/api/methodology")
def methodology():
    items, cl = _items(), _cl()
    N = len(items)
    groups = defaultdict(list)
    for t, g in config.IDENTIFIER_GROUP.items():
        groups[g].append({"type": t, "label": signal_label(t)})
    df_table = [{"df": df, "share": round(df / max(1, N), 2), "counted": counted(df, N)}
                for df in sorted({2, 3, max(2, N // 2), max(3, N // 2 + 1)})]
    ev = None
    rp = config.DATA / "eval" / "report.json"          # written by tools/evaluate.py with the current method
    if rp.exists():
        try:
            r = json.loads(rp.read_text(encoding="utf-8"))
            ev = {"file": str(rp.relative_to(config.ROOT)), "labels": r.get("labels"),
                  "leave_one_out": (r.get("leave_one_out") or {}).get("summary"),
                  "variants": (r.get("variants") or {}).get("summary")}
        except Exception:
            ev = None
    nm = lambda l: sorted((_name(items, l.a), _name(items, l.b)))
    cands = sorted((l for l in cl["links"] if l.must_link and l.shared_ids and len(l.views) >= 2),
                   key=lambda l: (-len(l.views), l.distance, nm(l)))
    best = cands[0] if cands else min((l for l in cl["links"] if l.relation == "same_campaign"),
                                      key=lambda l: (l.distance, nm(l)), default=None)
    worked = None
    if best:
        worked = {"a": mat_summary(best.a, items[best.a][0], cl), "b": mat_summary(best.b, items[best.b][0], cl),
                  **explain_link(best, items)}
        s0 = next((s for s in best.shared_ids if not s.ignored), None)
        if s0:
            worked["item"] = {"label": signal_label(_type0(s0)), "group": s0.group, "group_label": group_label(s0.group),
                              "value": display_value(_type0(s0), s0.value, cl), "df": s0.df, "n": N,
                              "share": round(s0.df / max(1, N), 2), "max_df": config.MAX_DF}
    return {"steps": method_steps(), "references": [{"id": i, "text": t, "url": u} for i, t, u in REFERENCES],
            "identifier_groups": [{"group": g, "label": group_label(g), "hint": GROUP_HINT[g], "types": groups[g]}
                                  for g in GROUP_ORDER],
            "views": [{"view": v, "label": view_label(v), "hint": VIEW_HINT[v]} for v in VIEWS],
            "constants": {"max_df": config.MAX_DF, "phash_hamming": config.PHASH_HAMMING, "duplicate_cut": config.DUPLICATE_CUT,
                          "min_class_names": config.MIN_CLASS_NAMES, "min_script_shingles": config.MIN_SCRIPT_SHINGLES,
                          "campaign_cut": config.CAMPAIGN_CUT, "family_cut": config.FAMILY_CUT,
                          "face_det_threshold": config.FACE_DET_THRESHOLD, "face_min_side": config.FACE_MIN_SIDE,
                          "face_match_threshold": config.FACE_MATCH_THRESHOLD},
            "df_table": df_table, "thresholds": _thresholds(),
            "relations": [{"relation": k, "label": RELATION_PL[k], "hint": RELATION_HINT[k]} for k in RELATION_PL],
            "decisions": [{"decision": k, "label": v[0], "hint": v[1]} for k, v in DECISION_PL.items()],
            "examples": examples(items, cl), "worked": worked, "evaluation": ev, "n_materials": N}


# =============================================================================== analysis of a new material
def _analysis_payload(res: dict, keep: bool, meta: dict) -> dict:
    items, cl = _items(), _cl()
    f = res["features"]
    m = res["material"]
    lab, desc = DECISION_PL[res["decision"]]
    ref = lambda c: camp_ref(c, cl) or {"id": c, "code": f"C{c + 1}", "name": "?", "size": 0, "color": None}
    scores = [{"score": s, "distance": round(1 - s, 3), **ref(c)} for s, c in res["campaign_scores"]]  # 1-NN per campaign
    all_items = {**items, m.id: (f, res.get("vectors", {}))}
    links_out = []
    for l in res["links"][:10]:
        other = l.b
        links_out.append({"p": round(l.p, 3), "distance": round(l.distance, 4), "relation": l.relation,
                          "relation_label": RELATION_PL[l.relation], "evidence": evidence_list(l),
                          "other": mat_summary(other, items[other][0], cl) if other in items else {"id": other, "name": other},
                          "explain": explain_link(l, all_items)})
    near = res.get("nearest")
    return {"decision": res["decision"], "decision_label": lab, "decision_hint": desc,
            "campaign": camp_ref(res["campaign"], cl) if res["campaign"] is not None else None,
            "similar_family": camp_ref(res.get("similar_family"), cl) if res.get("similar_family") is not None else None,
            "nearest": {**ref(near["campaign"]), "distance": near["distance"], "material_id": near["material"],
                        "material_name": near["name"]} if near else None,
            "closest": scores[0] if scores else None, "scores": scores, "links": links_out,
            "kept": keep and m.id in items, "material_id": m.id, "name": m.name, "input": meta,
            "features": material_features({**f, "_material": m.to_dict()}, items, res.get("vectors")), "thresholds": _thresholds()}


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
            "dataset": "import zbioru", "recluster": "przeliczenie kampanii", "watch_scan": "obserwacja kampanii: źródło",
            "watch_run": "obserwacja kampanii zakończona"}


def event_view(e: dict) -> dict:
    k, p = e["kind"], e.get("payload") or {}
    src = str(p.get("source", ""))
    base, _, kw = src.partition(":")
    src_pl = SCAN_SOURCE_PL.get(base, base) + (f" (hasło „{kw}”)" if kw else "")
    if k == "watch_scan":
        text = (f"{SCAN_SOURCE_PL.get(src, src)}: {p.get('campaign_label', '')}, {group_label(str(p.get('group', '')))} "
                f"„{str(p.get('value', ''))[:60]}” → {plural(int(p.get('n', 0)), 'pozycja', 'pozycje', 'pozycji')}")
    elif k == "watch_run":
        text = (f"{plural(int(p.get('campaigns', 0)), 'kampania', 'kampanie', 'kampanii')}, "
                f"{plural(int(p.get('seeds', 0)), 'ziarno', 'ziarna', 'ziaren')}; znaleziono {p.get('found', 0)}, nowych {p.get('fresh', 0)}, "
                f"przeanalizowano {p.get('analysed', 0)}, potwierdzono {p.get('confirmed', 0)}")
    elif k == "scan":
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
            "default_dataset_exists": (config.DATA / "organizer" / "dane").is_dir(),
            "demo_available": config.DEMO_DATASET.is_dir(),
            "llm_backend": config.LLM_BACKEND, "llm_backend_label": BACKEND_PL.get(config.LLM_BACKEND, config.LLM_BACKEND),
            "llm_available": {"claude_cli": bool(shutil.which("claude")), "gemini": bool(os.environ.get("GEMINI_API_KEY"))},
            "neo4j": bool(os.environ.get("NEO4J_URI")),
            "recent": [event_view(e) for e in eng().store.events(20)]}


@app.post("/api/dataset")
def load_dataset(req: DatasetReq):
    p = Path(req.path)
    p = p if p.is_absolute() else config.ROOT / p
    if not p.is_dir():
        raise HTTPException(400, f"Folder nie istnieje: {req.path}. Ścieżka jest liczona na komputerze, na którym działa "
                                 f"serwer (w Dockerze: wewnątrz kontenera, katalog ./data to /app/data), względem {config.ROOT}.")
    if not any(c.is_dir() for c in p.iterdir()):
        raise HTTPException(400, f"Folder {req.path} nie ma podfolderów. Każdy podfolder zbioru to jeden przypadek; "
                                 "pojedynczy plik dodaj na stronie „Analizuj materiał”.")

    def work(progress):
        n = eng().add_dataset(p, use_llm=req.use_llm, progress=progress, force=req.force)
        progress("Przeliczanie kampanii…")
        cl = eng().clustering(refresh=True)
        eng().store.log("dataset", {"path": req.path, "n": n, "campaigns": len(cl["campaigns"])})
        return {"n": n, "campaigns": len(cl["campaigns"])}

    return submit("dataset", f"Import zbioru: {req.path}", work, {"path": req.path, "use_llm": req.use_llm, "force": req.force})


@app.post("/api/demo")
def load_demo():
    """Import the synthetic dataset shipped with the code (invented cases: no LLM, no RDAP / DNS / crt.sh lookups)."""
    p = config.DEMO_DATASET
    if not p.is_dir():
        raise HTTPException(404, "Zbiór demonstracyjny nie jest dołączony do tej instalacji (tests/fixtures/synthetic_dataset).")

    def work(progress):
        n = eng().add_dataset(p, use_llm=False, progress=progress, enrich_online=False)
        progress("Przeliczanie kampanii…")
        cl = eng().clustering(refresh=True)
        eng().store.log("dataset", {"path": "zbiór demonstracyjny", "n": n, "campaigns": len(cl["campaigns"])})
        return {"n": n, "campaigns": len(cl["campaigns"])}

    return submit("dataset", "Import zbioru demonstracyjnego", work, {"path": "demo", "use_llm": False, "force": False})


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
        w.writerow(["material_a", "campaign_a", "material_b", "campaign_b", "p", "distance", "relation", "shared_identifiers",
                    "views", "explanation"])
        code = lambda m: f"C{cl['campaign_of'][m] + 1}" if m in cl["campaign_of"] else ""
        for l in sorted(cl["links"], key=lambda l: (-l.p, l.distance)):
            w.writerow([_name(items, l.a), code(l.a), _name(items, l.b), code(l.b), round(l.p, 3), round(l.distance, 3),
                        RELATION_PL[l.relation],
                        "; ".join(f"{s.type}={s.value} ({s.df}/{len(items)})" for s in l.shared_ids if not s.ignored),
                        "; ".join(f"{view_label(k)}={v:.2f}" for k, v in sorted(l.views.items(), key=lambda kv: -kv[1])),
                        l.explain()])
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
    watch: bool = False


class StartReq(BaseModel):
    minutes: int = 30
    keywords: list[str] = []
    analyse: bool = False
    watch: bool = False


class WatchReq(BaseModel):
    campaign: int | None = None
    analyse: bool = False


def seed_view(seed: dict) -> dict:
    """Display labels for a campaign-watch seed (search identifier of a known campaign)."""
    t = str(seed.get("type") or "").split("+")[0]
    return {**seed, "group_label": group_label(str(seed.get("group", ""))), "type_label": signal_label(t) if t else "",
            "source_label": SCAN_SOURCE_PL.get(seed.get("source", ""), seed.get("source", "")),
            "sources_label": [SCAN_SOURCE_PL.get(x, x) for x in seed.get("sources", [])]}


def scan_item_view(r: dict) -> dict:
    r = {**r, "source_label": SCAN_SOURCE_PL.get(r.get("source", ""), r.get("source", ""))}
    if r.get("seed"):
        r["seed"] = seed_view(r["seed"])
    o = r.get("outcome")
    if o:
        r["outcome"] = {**o, "decision_label": DECISION_PL.get(o.get("decision"), (o.get("note") or "—", ""))[0]}
    return r


@app.get("/api/scanner")
def scanner_status():
    from . import scheduler

    running = bool(scheduler._SCHED and scheduler._SCHED.running)
    nxt = None
    if running:
        job = scheduler._SCHED.get_job("scan")
        nxt = str(job.next_run_time) if job and job.next_run_time else None
    found = [scan_item_view(r) for r in eng().store.get("scheduler_found", [])]
    watch_found = [r for r in found if r.get("seed")]
    watch_last = eng().store.get("watch_last")
    return {"running": running, "next_run": nxt, "config": scheduler.CURRENT if running else None,
            "default_keywords": scheduler.DEFAULT_KEYWORDS, "meta_token": bool(os.environ.get("META_ACCESS_TOKEN")),
            "found": sorted(found[-300:], key=lambda r: -(r.get("score") or 0)),
            "watch_found": watch_found[-300:][::-1],
            "watch_last": {**watch_last, "seeds": [seed_view(x) for x in watch_last.get("seeds", [])]} if watch_last else None,
            "events": [event_view(e) for e in eng().store.events(80)
                       if e["kind"] in ("scan", "scan_error", "scheduler_run", "analysed", "watch_scan", "watch_run")]}


@app.post("/api/scanner/run")
def scanner_run(req: ScanReq):
    from . import scheduler

    def work(progress):
        progress("Skanowanie: lista CERT Polska, Microsoft Ad Library, Google Ads Transparency, Meta Ad Library…")
        return scheduler.run_once(eng(), keywords=req.keywords or None, analyse=req.analyse, watch=req.watch)

    return submit("scan", "Skan źródeł", work, {"keywords": req.keywords, "analyse": req.analyse, "watch": req.watch})


def _check_campaign(ci: int | None) -> None:
    if ci is not None and not 0 <= ci < len(_cl()["campaigns"]):
        raise HTTPException(404, "Nie ma takiej kampanii (numeracja mogła się zmienić po przeliczeniu).")


@app.get("/api/scanner/seeds")
def scanner_seeds(campaign: int | None = None):
    """Seeds the campaign watch would search with (one campaign, or the default set of largest campaigns)."""
    from . import scheduler

    _check_campaign(campaign)
    seeds = scheduler.campaign_seeds(eng(), [campaign] if campaign is not None else None)
    return {"seeds": [seed_view(x) for x in seeds], "max_campaigns": scheduler.WATCH_MAX_CAMPAIGNS,
            "max_seeds": scheduler.WATCH_MAX_SEEDS, "meta_token": bool(os.environ.get("META_ACCESS_TOKEN"))}


@app.post("/api/scanner/watch")
def scanner_watch(req: WatchReq):
    """Campaign watch: search public sources with known campaigns' own identifiers (all, or one campaign)."""
    from . import scheduler

    _check_campaign(req.campaign)
    camps = [req.campaign] if req.campaign is not None else None

    def work(progress):
        progress("Ziarna wyszukiwania: domeny, ID reklamodawców i produkty znanych kampanii…")
        out = scheduler.watch_campaigns(eng(), campaigns=camps, analyse=req.analyse, progress=progress)
        return {**out, "seeds": [seed_view(x) for x in out["seeds"]], "hits": [scan_item_view(r) for r in out["hits"]]}

    label = f"Obserwacja kampanii C{req.campaign + 1}" if req.campaign is not None else "Obserwacja znanych kampanii"
    return submit("watch", label, work, {"campaign": req.campaign, "analyse": req.analyse})


@app.post("/api/scanner/start")
def scanner_start(req: StartReq):
    from . import scheduler

    minutes = min(1440, max(5, req.minutes))
    return {"message": scheduler.start_background(eng(), minutes=minutes, analyse=req.analyse, keywords=req.keywords or None,
                                                  watch=req.watch)}


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
