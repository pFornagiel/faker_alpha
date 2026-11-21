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
from .gazetteer import SCAM_LEXICON, best_label, find_brands, find_media, find_persons, fold

log = logging.getLogger(__name__)

SCAM_TYPES = ["investment_fake_platform", "fund_recovery", "health_miracle_product", "fake_giveaway_survey",
              "fake_shop", "parcel_delivery_phishing", "gov_refund_or_benefit_phishing", "illegal_gambling",
              "marketplace_phishing", "job_task_scam", "subscription_trap", "political_disinfo_ad", "other"]

SCHEMA = {
    "type": "object",
    "properties": {
        "scam_type": {"type": "string", "enum": SCAM_TYPES},
        "impersonated_persons": {"type": "array", "items": {"type": "string"}},
        "impersonated_brands": {"type": "array", "items": {"type": "string"}},
        "spoofed_media_outlet": {"type": ["string", "null"]},
        "product_or_platform_name": {"type": ["string", "null"]},
        "summary_pl": {"type": "string"},
    },
    "required": ["scam_type", "impersonated_persons", "impersonated_brands", "product_or_platform_name", "summary_pl"],
}

SYSTEM = """Jesteś analitykiem CERT badającym oszukańcze reklamy i strony docelowe (scam ads) w Polsce.
Dostajesz surowy tekst materiału (tekst strony, OCR zrzutów ekranu, metadane reklamy).
Zwróć WYŁĄCZNIE obiekt JSON zgodny ze schematem. Zasady:
- scam_type wybieraj tylko z dozwolonych wartości enum.
- impersonated_persons: pełne imię i nazwisko osób, których wizerunek/autorytet jest wykorzystywany
  (celebryci, politycy, lekarze, dziennikarze); nie wpisuj fikcyjnych komentujących.
- impersonated_brands: marki / instytucje, pod które podszywa się materiał.
- spoofed_media_outlet: medium, którego wygląd jest podrabiany (np. "Gazeta.pl"), jeśli występuje.
- product_or_platform_name: nazwa produktu/platformy/aplikacji (np. "Kardivix", "Trwały Działunek").
- summary_pl: 1 zdanie opisu mechanizmu oszustwa.
Nie zgaduj - gdy brak danych użyj null / [] / "other"."""


def _cache_path(text: str, backend: str):
    h = hashlib.sha1((backend + config.LLM_MODEL + text).encode("utf-8", "replace")).hexdigest()[:20]
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
    prompt = f"{SYSTEM}\n\n=== MATERIAŁ ===\n{text[:12000]}\n=== KONIEC ===\nZwróć JSON."
    cmd = [exe, "-p", "--model", config.LLM_MODEL, "--output-format", "json", "--tools", "",
           "--no-session-persistence", "--json-schema", json.dumps(SCHEMA)]
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
    body = {"contents": [{"parts": [{"text": f"{SYSTEM}\n\nSchemat: {json.dumps(SCHEMA)}\n\n{text[:12000]}"}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0}}
    try:
        r = requests.post(url, json=body, timeout=60)
        r.raise_for_status()
        return _extract_json(r.json()["candidates"][0]["content"]["parts"][0]["text"])
    except Exception as exc:
        log.warning("gemini failed: %s", exc)
        return None


_CTA_STOP = {"pobierz", "sprawdz", "kliknij", "zobacz", "dowiedz", "zarejestruj", "otworz", "wiecej", "tutaj", "teraz"}


def rules(text: str) -> dict:
    """Deterministic fallback using the gazetteer/lexicons (always available)."""
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
    return {
        "scam_type": best_label(text, SCAM_LEXICON) or "other",
        "impersonated_persons": persons,
        "impersonated_brands": find_brands(text),
        "spoofed_media_outlet": (find_media(text) or [None])[0],
        "product_or_platform_name": product,
        "summary_pl": title, "_backend": "rules",
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
            return normalise(json.loads(cp.read_text()))      # older cache entries may carry dropped fields
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
    if a.get("scam_type") not in SCAM_TYPES:
        a["scam_type"] = "other"
    return {k: a.get(k) for k in (*SCHEMA["properties"], "_backend") if k in a}
