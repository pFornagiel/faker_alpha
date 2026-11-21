"""LLM feature augmentation: derive structured, enum-constrained attributes from raw material text
("from the car model infer the body type"). Backends, in order for FTF_LLM=auto:
  1. claude_cli - Claude Code CLI headless (`claude -p --model haiku --json-schema ...`), uses the
                  user's Claude subscription, no API key needed;
  2. gemini     - if GEMINI_API_KEY is set (REST, gemini-flash);
  3. rules      - offline gazetteer/lexicon extractor (always available, deterministic).
Results are cached on disk by content hash, so re-runs and the scheduler are cheap.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess

from . import config
from .gazetteer import (NARRATIVE_LEXICON, SCAM_LEXICON, URGENCY_CUES, best_label, find_brands, find_media,
                        find_persons, fold)
from .text import amounts

log = logging.getLogger(__name__)

SCAM_TYPES = ["investment_fake_platform", "fund_recovery", "health_miracle_product", "fake_giveaway_survey",
              "fake_shop", "parcel_delivery_phishing", "gov_refund_or_benefit_phishing", "illegal_gambling",
              "marketplace_phishing", "job_task_scam", "subscription_trap", "political_disinfo_ad", "other"]
NARRATIVES = ["celebrity_scandal_or_attack", "censored_interview", "banker_scandal", "celebrity_testament_or_death",
              "staged_studio_quarrel", "state_project_shares", "national_income_programme", "doctor_vs_big_pharma",
              "miracle_cure_testimonial", "investment_event", "casino_app", "brand_giveaway", "clearance_sale",
              "undelivered_parcel", "lost_funds_recovery", "other"]
FORMATS = ["fake_news_article", "fake_news_studio_video", "deepfake_talking_head", "static_portrait_with_headline",
           "product_packshot", "fake_app_store_page", "fake_event_page", "quiz_or_survey", "ugc_testimonial", "other"]

SCHEMA = {
    "type": "object",
    "properties": {
        "scam_type": {"type": "string", "enum": SCAM_TYPES},
        "narrative_template": {"type": "string", "enum": NARRATIVES},
        "creative_format": {"type": "string", "enum": FORMATS},
        "impersonated_persons": {"type": "array", "items": {"type": "string"}},
        "impersonated_brands": {"type": "array", "items": {"type": "string"}},
        "spoofed_media_outlet": {"type": ["string", "null"]},
        "product_or_platform_name": {"type": ["string", "null"]},
        "promised_benefit": {"type": ["string", "null"]},
        "entry_cost": {"type": ["string", "null"]},
        "call_to_action": {"type": ["string", "null"]},
        "urgency_cues": {"type": "array", "items": {"type": "string"}},
        "emotional_triggers": {"type": "array", "items": {"type": "string"}},
        "target_audience": {"type": "array", "items": {"type": "string"}},
        "fictional_persona": {"type": ["string", "null"]},
        "distinctive_phrases": {"type": "array", "items": {"type": "string"}},
        "summary_pl": {"type": "string"},
        "evidence": {"type": "object", "additionalProperties": {"type": "string"}},
    },
    "required": ["scam_type", "narrative_template", "creative_format", "impersonated_persons",
                 "impersonated_brands", "product_or_platform_name", "distinctive_phrases", "summary_pl"],
}

SYSTEM = """Jesteś analitykiem CERT badającym oszukańcze reklamy i strony docelowe (scam ads) w Polsce.
Dostajesz surowy tekst materiału (tekst strony, OCR zrzutów ekranu, metadane reklamy).
Zwróć WYŁĄCZNIE obiekt JSON zgodny ze schematem. Zasady:
- scam_type / narrative_template / creative_format wybieraj tylko z dozwolonych wartości enum.
- impersonated_persons: pełne imię i nazwisko osób, których wizerunek/autorytet jest wykorzystywany
  (celebryci, politycy, lekarze, dziennikarze); nie wpisuj fikcyjnych komentujących.
- fictional_persona: wymyślona postać (np. "dr Jan Kowalski", "Ojciec Bonifacy"), jeśli występuje.
- product_or_platform_name: nazwa produktu/platformy/aplikacji (np. "Kardivix", "Trwały Działunek").
- distinctive_phrases: 3-6 charakterystycznych, dosłownych fraz (szablonowych), po polsku.
- summary_pl: 1 zdanie opisu mechanizmu oszustwa.
- evidence: dla scam_type i product_or_platform_name krótki dosłowny cytat.
Nie zgaduj - gdy brak danych użyj null / [] / "other"."""


def extra_schema() -> list[dict]:
    f = config.CACHE / "llm_extra_schema.json"
    try:
        return json.loads(f.read_text()) if f.exists() else []
    except Exception:
        return []


def schema() -> dict:
    """Base schema + attributes discovered by tools/llm_refine.py (iterative feature discovery)."""
    ex = extra_schema()
    if not ex:
        return SCHEMA
    sc = json.loads(json.dumps(SCHEMA))
    sc["properties"]["extra"] = {"type": "object", "properties": {a["name"]: {"type": ["string", "null"], "description": a["description"]}
                                                                    for a in ex}}
    return sc


def _cache_path(text: str, backend: str):
    ex = extra_schema()
    h = hashlib.sha1((backend + config.LLM_MODEL + (json.dumps(ex) if ex else "") + text).encode("utf-8", "replace")).hexdigest()[:20]
    p = config.CACHE / "llm"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{h}.json"


def _extract_json(s: str) -> dict | None:
    s = s.strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    m = re.search(r"\{.*\}", s, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


def _claude_cli(text: str) -> dict | None:
    exe = shutil.which("claude")
    if not exe:
        return None
    extra = "".join(f"\n- extra.{a['name']}: {a['description']}" for a in extra_schema())
    extra = ("\nDodatkowe atrybuty (pole extra, krótkie znormalizowane wartości małymi literami):" + extra) if extra else ""
    prompt = f"{SYSTEM}{extra}\n\n=== MATERIAŁ ===\n{text[:12000]}\n=== KONIEC ===\nZwróć JSON."
    cmd = [exe, "-p", "--model", config.LLM_MODEL, "--output-format", "json", "--tools", "",
           "--no-session-persistence", "--json-schema", json.dumps(schema())]
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=config.LLM_TIMEOUT,
                           env={**os.environ, "CLAUDE_CODE_ENTRYPOINT": "ftf"})
    except subprocess.TimeoutExpired:
        log.warning("claude CLI timeout")
        return None
    if r.returncode != 0:
        log.warning("claude CLI failed: %s", r.stderr[:300])
        return None
    try:
        env = json.loads(r.stdout)
    except Exception:
        return _extract_json(r.stdout)
    so = env.get("structured_output")
    if isinstance(so, dict):
        return so
    return _extract_json(env.get("result", "") or "")


def _gemini(text: str) -> dict | None:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    import requests

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}"
    body = {"contents": [{"parts": [{"text": f"{SYSTEM}\n\nSchemat: {json.dumps(schema())}\n\n{text[:12000]}"}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0}}
    try:
        r = requests.post(url, json=body, timeout=60)
        r.raise_for_status()
        return _extract_json(r.json()["candidates"][0]["content"]["parts"][0]["text"])
    except Exception as exc:
        log.warning("gemini failed: %s", exc)
        return None


_CTA_STOP = {"pobierz", "sprawdz", "kliknij", "zobacz", "dowiedz", "zarejestruj", "otworz", "wiecej", "tutaj", "teraz"}
_ENUM_BY_FIELD = {"scam_type": set(SCAM_TYPES), "narrative_template": set(NARRATIVES), "creative_format": set(FORMATS)}


def rules(text: str) -> dict:
    """Deterministic fallback using the gazetteer/lexicons (always available)."""
    f = fold(text)
    persons = find_persons(text)
    title = text.split("\n", 1)[0][:200]
    product = None
    for m in re.finditer(
        r"(?i:\b(?:produkt|preparat|kapsułki|aplikacj[aęi]|platform[aęy]))\s+[„\"']?([A-ZŁŚŻŹĆ][\w-]{3,30}(?:\s[A-ZŁŚŻŹĆ][\w-]+)?)",
        text,
    ):
        cand = m.group(1).strip()
        first_word = fold(cand.split()[0])
        if first_word not in _CTA_STOP:
            product = cand
            break
    fmt = "other"
    if any(k in f for k in ("app store", "google play", "pobierz aplikacj")):
        fmt = "fake_app_store_page"
    elif find_media(text):
        fmt = "fake_news_article"
    elif any(k in f for k in ("summit", "konferencj", "forum")):
        fmt = "fake_event_page"
    return {
        "scam_type": best_label(text, SCAM_LEXICON) or "other",
        "narrative_template": best_label(text, NARRATIVE_LEXICON, 2) or "other",
        "creative_format": fmt,
        "impersonated_persons": persons,
        "impersonated_brands": find_brands(text),
        "spoofed_media_outlet": (find_media(text) or [None])[0],
        "product_or_platform_name": product,
        "promised_benefit": (amounts(text) or [None])[0],
        "entry_cost": None, "call_to_action": None,
        "urgency_cues": [u for u in URGENCY_CUES if u in f][:6],
        "emotional_triggers": [], "target_audience": [], "fictional_persona": None,
        "distinctive_phrases": [], "summary_pl": title, "evidence": {}, "_backend": "rules",
    }


def extract_attributes(text: str, backend: str | None = None) -> dict:
    backend = backend or config.LLM_BACKEND
    text = (text or "").strip()
    if len(text) < 30:
        return rules(text)
    order = {"auto": ["claude_cli", "gemini"], "claude_cli": ["claude_cli"], "gemini": ["gemini"], "none": []}.get(backend, [])
    for b in order:
        cp = _cache_path(text, b)
        if cp.exists():
            return json.loads(cp.read_text())
        res = _claude_cli(text) if b == "claude_cli" else _gemini(text)
        if res:
            res = normalise(res)
            res["_backend"] = b
            cp.write_text(json.dumps(res, ensure_ascii=False, indent=1))
            return res
    return rules(text)


def normalise(a: dict) -> dict:
    """Map free-text LLM entities onto gazetteer canonical names (keeps unknown ones)."""
    persons = []
    for p in a.get("impersonated_persons") or []:
        canon = find_persons(p)
        persons.extend(canon or [p.strip()])
    a["impersonated_persons"] = sorted(set(persons))
    brands = []
    for b in a.get("impersonated_brands") or []:
        canon = find_brands(b) + find_media(b)
        brands.extend(canon or [b.strip()])
    a["impersonated_brands"] = sorted(set(brands))
    for k, allowed in _ENUM_BY_FIELD.items():
        if a.get(k) not in allowed:
            a[k] = "other"
    return a
