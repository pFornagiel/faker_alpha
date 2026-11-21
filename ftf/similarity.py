"""Explainable pairwise linking of materials.

For a pair of materials we collect *evidence items* (signal, shared value / similarity, weight,
human-readable reason). Each item belongs to an evidence *family* (infra IDs, tracking, domain,
kit, assets, visual, narrative, persons, concept, advertiser, hosting, duplicate).

  * Discrete indicators (pixel IDs, TDS tenant UUIDs, form endpoints, domains, script names...) are
    weighted by a prior (config.INDICATOR_WEIGHT) times a *rarity* factor estimated from the corpus
    (Fellegi–Sunter intuition: agreement on a value seen in 2 of 1000 ads is strong, agreement on a
    value seen in half of the corpus is noise). Hubs (Cloudflare, famous faces, generic CDNs) are
    discounted automatically and reported as ignored.
  * Continuous similarities (text MinHash, entity-masked MinHash, e5, CLIP, DINOv2, pHash, DOM
    template, unknown-face ArcFace) are mapped to evidence with calibrated piecewise-linear ramps.
  * Within a family: noisy-OR of items; across families: noisy-OR, then guards:
      - weak-only evidence (persons/concept/hosting) is capped (a famous face alone links nothing),
      - contradicting scam types reduce the score unless operator-level (S) evidence exists.
The list of evidence items *is* the explanation shown on every graph edge.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import numpy as np

from . import config
from .text import char_ngram_sim, jaccard_sig

PL_SIGNAL = {
    "fb_pixel": "Facebook Pixel", "tiktok_pixel": "TikTok Pixel", "ga": "Google Analytics ID", "gtm": "Google Tag Manager",
    "gads": "Google Ads (AW-) ID", "ym": "Yandex Metrika", "clarity": "MS Clarity", "hotjar": "Hotjar ID",
    "sentry_key": "klucz Sentry", "recaptcha": "klucz reCAPTCHA", "adsense": "AdSense ID", "phone": "telefon",
    "email": "e-mail", "telegram": "Telegram", "whatsapp": "WhatsApp", "wallet": "portfel krypto",
    "form_endpoint": "endpoint formularza/API", "api_template": "szablon API backendu (kit)", "ad_id": "ID reklamy/kampanii Meta",
    "adset": "nazwa zestawu reklam", "affiliate": "parametr afiliacyjny/TDS", "tds_host": "host TDS/trackera",
    "tenant_uuid": "UUID tenanta landing-buildera", "campaign_param": "ID kampanii w URL", "build_id": "build ID aplikacji",
    "landing_domain": "domena docelowa", "redirect_domain": "domena w łańcuchu przekierowań", "page_host": "host strony",
    "ocr_domain": "domena widoczna na kreacji", "script_name": "nazwa skryptu 1st-party", "script_hash": "identyczny skrypt (hash)",
    "css_name": "nazwa arkusza CSS", "favicon": "favicon", "param_signature": "sygnatura parametrów URL (TDS)",
    "path_template": "szablon ścieżki URL", "asset_phash": "ten sam obraz na stronie", "advertiser_id": "ID reklamodawcy",
    "advertiser_name": "nazwa reklamodawcy", "ip": "adres IP (nie-CDN)", "product": "nazwa produktu/platformy",
    "platform_name": "nazwa platformy", "phrase": "charakterystyczna fraza", "form_fields": "zestaw pól formularza",
    "ns_pair": "para serwerów NS", "reg_burst": "seria rejestracji (rejestrator+NS+dzień)",
}
FAMILY_PL = {"duplicate": "duplikat", "infra_ids": "identyfikatory operatora", "tracking": "śledzenie/TDS",
             "domain": "domeny", "kit": "szablon/kit strony", "assets": "wspólne obrazy", "visual": "wizualne",
             "narrative": "narracja/tekst", "persons": "osoby", "concept": "koncepcja (LLM)",
             "advertiser": "reklamodawca", "hosting": "hosting", "offer": "oferta/produkt"}

config.INDICATOR_WEIGHT.setdefault("form_fields", 0.35)
config.INDICATOR_FAMILY.setdefault("form_fields", "kit")
config.INDICATOR_FAMILY["product"] = "offer"
config.FAMILY_TIER.setdefault("offer", "M")


@dataclass
class Evidence:
    family: str
    signal: str
    detail: str
    weight: float
    value: str = ""
    ignored: bool = False

    def as_dict(self):
        return {"family": self.family, "signal": self.signal, "detail": self.detail, "weight": round(self.weight, 3),
                "value": self.value, "ignored": self.ignored}


@dataclass
class Link:
    a: str
    b: str
    p: float
    relation: str
    families: dict = field(default_factory=dict)
    evidence: list = field(default_factory=list)
    comparable: bool = True
    playbook: float = 0.0

    def explain(self, top: int = 6) -> str:
        items = sorted([e for e in self.evidence if not e.ignored], key=lambda e: -e.weight)[:top]
        return "; ".join(f"{e.detail} [+{e.weight:.2f}]" for e in items)

    def as_dict(self):
        return {"a": self.a, "b": self.b, "p": round(self.p, 3), "relation": self.relation, "playbook": round(self.playbook, 3),
                "families": {k: round(v, 3) for k, v in self.families.items()},
                "evidence": [e.as_dict() for e in self.evidence], "comparable": self.comparable}


def ramp(x: float | None, lo: float, hi: float) -> float:
    if x is None or x <= lo:
        return 0.0
    return min(1.0, (x - lo) / (hi - lo))


def noisy_or(ws) -> float:
    p = 1.0
    for w in ws:
        p *= (1.0 - max(0.0, min(0.999, w)))
    return 1.0 - p


def _max_cos(A, B) -> float | None:
    if A is None or B is None or len(A) == 0 or len(B) == 0:
        return None
    A, B = np.atleast_2d(A), np.atleast_2d(B)
    return float((A @ B.T).max())


def _hex_ham(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


class Corpus:
    """Document-frequency statistics for rarity weighting."""

    def __init__(self, items: dict[str, tuple[dict, dict]]):
        self.items = items
        self.N = max(1, len(items))
        self.df = Counter()
        for f, _ in items.values():
            for t, vals in f.get("indicators", {}).items():
                for v in set(vals):
                    self.df[(t, v)] += 1
            for pname in set(f.get("persons_visual", [])):
                self.df[("person_visual", pname)] += 1
            for pname in set(f.get("persons_named", [])):
                self.df[("person_named", pname)] += 1
            for k, v in ((f.get("llm") or {}).get("extra") or {}).items():
                if v and str(v).lower() not in ("unknown", "null", "none", "brak"):
                    self.df[("extra", k, str(v).lower())] += 1
        # anisotropy correction: centre embeddings on the corpus mean (removes the common
        # "Polish scam landing page" / "phone screenshot UI" component shared by all materials)
        self.mean = {}
        self.centred: dict[tuple[str, str], np.ndarray] = {}
        for kind in ("text", "text_gemma", "clip", "dino"):
            vs = [np.atleast_2d(v[kind]).mean(0) for _, v in items.values() if kind in v and len(v[kind])]
            if len(vs) >= 3:
                self.mean[kind] = np.mean(vs, axis=0)

    def centre(self, mid: str, kind: str, V):
        if V is None or len(V) == 0:
            return None
        if kind not in self.mean:
            return np.atleast_2d(V)
        key = (mid, kind)
        if key not in self.centred:
            A = np.atleast_2d(V) - self.mean[kind]
            self.centred[key] = A / (np.linalg.norm(A, axis=1, keepdims=True) + 1e-9)
        return self.centred[key]

    def rarity(self, key, df: int | None = None) -> float:
        n = df if df is not None else self.df.get(key, 2)
        n = max(2, n)
        frac = n / self.N
        if n >= config.HUB_MIN_COUNT and frac > config.HUB_FRACTION:
            return 0.0
        if self.N <= 3:
            return 1.0
        return max(0.0, min(1.0, math.log(1 / frac) / math.log(self.N / 2)))


GENERIC_PHRASES = {"dowiedz sie wiecej", "kliknij tutaj", "zarejestruj sie", "zamow teraz", "kup teraz", "sprawdz teraz",
                   "wiecej informacji", "czytaj wiecej", "learn more", "sign up", "zobacz wiecej", "nie przegap",
                   "tylko dzis", "ograniczona oferta", "dolacz teraz", "zacznij zarabiac"}


def _generic_phrase(v: str) -> bool:
    return v in GENERIC_PHRASES or len(v.split()) < 3 or len(v) < 15


def _indicator_evidence(fa, fb, corpus: Corpus) -> list[Evidence]:
    ev = []
    A, B = fa.get("indicators", {}), fb.get("indicators", {})
    has_landing = bool(set(A.get("landing_domain", [])) & set(B.get("landing_domain", [])))
    for t, va in A.items():
        if t not in config.INDICATOR_WEIGHT or t not in B:
            continue
        if t == "page_host" and has_landing:
            continue
        if t == "asset_phash":
            shared = []
            vb = B[t]
            for x in va:
                for y in vb:
                    if _hex_ham(x, y) <= 4:
                        shared.append(x)
                        break
        else:
            shared = sorted(set(va) & set(B[t]))
        fam = config.INDICATOR_FAMILY.get(t, "kit")
        if t == "phrase":
            shared = [v for v in shared if not _generic_phrase(v)]
        for v in shared[:12]:
            df = corpus.df.get((t, v), 2)
            r = corpus.rarity((t, v))
            name = PL_SIGNAL.get(t, t)
            if r == 0.0:
                ev.append(Evidence(fam, t, f"pominięto hub: {name} „{v[:40]}” ({df}/{corpus.N} materiałów)", 0.0, v, True))
                continue
            w = config.INDICATOR_WEIGHT[t] * (0.35 + 0.65 * r)
            ev.append(Evidence(fam, t, f"wspólny {name}: „{v[:60]}” ({df}/{corpus.N})", w, v))
    # domain shown on a creative == landing domain of the other material
    for x, y in ((A, B), (B, A)):
        for d in set(x.get("ocr_domain", [])) & set(y.get("landing_domain", [])):
            ev.append(Evidence("domain", "ocr_domain", f"domena z kreacji = domena docelowa: {d}", 0.85, d))
    return ev


def pair(ida: str, fa: dict, va: dict, idb: str, fb: dict, vb: dict, corpus: Corpus) -> Link:
    ev: list[Evidence] = []
    # ---------------------------------------------------------------- duplicates
    shared_files = set(fa.get("file_shas", [])) & set(fb.get("file_shas", []))
    if shared_files:
        ev.append(Evidence("duplicate", "file_sha", f"identyczny plik (sha256) ×{len(shared_files)}", 0.99))
    # ---------------------------------------------------------------- discrete indicators
    ev += _indicator_evidence(fa, fb, corpus)
    # ---------------------------------------------------------------- text / narrative
    ta, tb = fa.get("text", {}), fb.get("text", {})
    sims: dict[str, float | None] = {}
    sims["text_minhash"] = jaccard_sig(ta.get("minhash"), tb.get("minhash"))
    sims["masked_minhash"] = jaccard_sig(ta.get("minhash_masked"), tb.get("minhash_masked"))
    ocr_j = jaccard_sig(ta.get("minhash_ocr"), tb.get("minhash_ocr"))
    if ocr_j is not None and (sims["text_minhash"] is None or ocr_j > sims["text_minhash"]):
        sims["text_minhash"] = ocr_j
    tt = [char_ngram_sim(x, y) for x in ta.get("title_templates", []) for y in tb.get("title_templates", []) if len(x) > 15 and len(y) > 15]
    sims["title_template"] = max(tt) if tt else None
    sims["text_embedding"] = _max_cos(corpus.centre(ida, "text", va.get("text")), corpus.centre(idb, "text", vb.get("text")))
    g = _max_cos(corpus.centre(ida, "text_gemma", va.get("text_gemma")), corpus.centre(idb, "text_gemma", vb.get("text_gemma")))
    if g is not None and (sims["text_embedding"] is None or g > sims["text_embedding"]):
        sims["text_embedding"] = g
    # ---------------------------------------------------------------- visual
    sims["clip"] = _max_cos(corpus.centre(ida, "clip", va.get("clip")), corpus.centre(idb, "clip", vb.get("clip")))
    sims["dinov2"] = _max_cos(corpus.centre(ida, "dino", va.get("dino")), corpus.centre(idb, "dino", vb.get("dino")))
    ph = [1 - _hex_ham(x["phash"], y["phash"]) / 64 for x in fa.get("images", []) for y in fb.get("images", [])
          if x.get("phash") and y.get("phash") and "ui" not in (x.get("kind", ""), y.get("kind", "")) and
          x.get("kind") != "ui_screenshot" and y.get("kind") != "ui_screenshot"]
    sims["phash"] = max(ph) if ph else None
    # ---------------------------------------------------------------- DOM template
    da, db = va.get("dom"), vb.get("dom")
    if da is not None and db is not None and len(da) and len(db):
        sims["dom_template"] = max(jaccard_sig(list(x), list(y)) or 0 for x in np.atleast_2d(da) for y in np.atleast_2d(db))
    # ---------------------------------------------------------------- faces
    fa_f, fb_f = fa.get("faces", []), fb.get("faces", [])
    Fa, Fb = va.get("faces"), vb.get("faces")
    if Fa is not None and Fb is not None and len(Fa) and len(Fb) and len(fa_f) == len(Fa) and len(fb_f) == len(Fb):
        S = np.atleast_2d(Fa) @ np.atleast_2d(Fb).T
        unk = [S[i, j] for i in range(len(fa_f)) for j in range(len(fb_f))
               if not fa_f[i].get("identity") and not fb_f[j].get("identity")
               and fa_f[i].get("quality", 0) >= 0.25 and fb_f[j].get("quality", 0) >= 0.25]
        sims["face_unknown"] = float(max(unk)) if unk else None
        if S.max() >= 0.80:
            ev.append(Evidence("visual", "same_face_image", f"ten sam kadr/zdjęcie twarzy (ArcFace cos={S.max():.2f})", 0.45))
    for name, val in sims.items():
        if val is None or name not in config.CONTINUOUS:
            continue
        lo, hi, wmax, fam = config.CONTINUOUS[name]
        w = ramp(val, lo, hi) * wmax
        if w > 0.01:
            label = {"text_minhash": "tekst prawie identyczny (MinHash)", "masked_minhash": "ten sam szablon tekstu po zamaskowaniu osób",
                     "title_template": "ten sam szablon tytułu", "text_embedding": "podobna narracja (e5)",
                     "clip": "podobny wygląd kreacji (CLIP)", "dinov2": "podobny układ/szablon graficzny (DINOv2)",
                     "phash": "prawie identyczny obraz (pHash)", "dom_template": "ten sam szablon HTML (DOM)",
                     "face_unknown": "ta sama nieznana twarz (persona)"}[name]
            ev.append(Evidence(fam, name, f"{label}: {val:.2f}", w, f"{val:.3f}"))
    # near-duplicate content (same text and same picture)
    if (sims.get("text_minhash") or 0) >= 0.93 and ((sims.get("phash") or 0) >= 0.95 or sims.get("phash") is None) \
            and set(fa.get("indicators", {}).get("landing_domain", [])) & set(fb.get("indicators", {}).get("landing_domain", [])):
        ev.append(Evidence("duplicate", "near_duplicate", "ta sama treść i ta sama domena (near-duplicate)", 0.97))
    # ---------------------------------------------------------------- persons
    for pname in sorted(set(fa.get("persons_visual", [])) & set(fb.get("persons_visual", []))):
        r = corpus.rarity(("person_visual", pname))
        w = config.PERSON_REF_WEIGHT * (0.35 + 0.65 * r)
        ev.append(Evidence("persons", "face_identity", f"rozpoznana twarz: {pname} (w obu)", w, pname, r == 0))
    for pname in sorted(set(fa.get("persons_named", [])) & set(fb.get("persons_named", [])) - set(fa.get("persons_visual", []))):
        r = corpus.rarity(("person_named", pname))
        w = 0.22 * (0.35 + 0.65 * r)
        ev.append(Evidence("persons", "person_named", f"ta sama osoba w treści: {pname}", w, pname, r == 0))
    # ---------------------------------------------------------------- concept (LLM)
    la, lb = fa.get("llm", {}), fb.get("llm", {})
    conflict = False
    for k, w in config.CONCEPT_WEIGHTS.items():
        x, y = la.get(k), lb.get(k)
        if x and y and x != "other" and y != "other":
            if x == y:
                ev.append(Evidence("concept", k, f"{k} = {x}", w, x))
            elif k == "scam_type":
                conflict = True
    ea, eb = (la.get("extra") or {}), (lb.get("extra") or {})
    for k in sorted(set(ea) & set(eb)):
        va_, vb_ = str(ea[k]).lower(), str(eb[k]).lower()
        if va_ == vb_ and va_ not in ("unknown", "null", "none", "brak", ""):
            r = corpus.rarity(("extra", k, va_))
            if r > 0:
                ev.append(Evidence("concept", f"llm_extra:{k}", f"atrybut odkryty przez LLM {k} = „{va_}”", 0.25 * (0.35 + 0.65 * r), va_))
    if la.get("spoofed_media_outlet") and la.get("spoofed_media_outlet") == lb.get("spoofed_media_outlet"):
        ev.append(Evidence("concept", "media", f"podszycie pod to samo medium: {la['spoofed_media_outlet']}", 0.2))
    # ---------------------------------------------------------------- combine
    fam_w: dict[str, list[float]] = defaultdict(list)
    for e in ev:
        if not e.ignored and e.weight > 0:
            fam_w[e.family].append(e.weight)
    families = {f: noisy_or(ws) for f, ws in fam_w.items()}
    p = noisy_or(families.values())
    strong = max([v for f, v in families.items() if config.FAMILY_TIER.get(f) in ("S", "M")] or [0])
    if strong < 0.25:
        p = min(p, config.WEAK_ONLY_CAP)
    s_tier = max([v for f, v in families.items() if config.FAMILY_TIER.get(f) == "S"] or [0])
    if conflict and s_tier < 0.5:
        p *= 0.6
        ev.append(Evidence("concept", "conflict", f"różny typ oszustwa: {la.get('scam_type')} vs {lb.get('scam_type')} (kara ×0.6)", 0.0, "", True))
    # comparability: did the two materials have at least one modality in common?
    comparable = any(v is not None for v in sims.values()) or bool(set(fa.get("indicators", {})) & set(fb.get("indicators", {})))
    playbook = noisy_or([families.get(f, 0) for f in ("narrative", "concept", "visual", "persons", "offer")])
    dup = families.get("duplicate", 0)
    n_fam = sum(1 for f, v in families.items() if v >= 0.3 and config.FAMILY_TIER.get(f) in ("S", "M"))
    if dup >= config.DUPLICATE_THRESHOLD:
        rel = "duplicate"
    elif p >= config.LINK_THRESHOLD and (s_tier >= 0.5 or strong >= 0.7 or n_fam >= 2):
        rel = "same_campaign"
    elif p >= config.SIMILAR_THRESHOLD or playbook >= 0.45:
        rel = "similar"
    else:
        rel = "none"
    return Link(ida, idb, p, rel, families, ev, comparable, playbook)


def candidate_pairs(items: dict[str, tuple[dict, dict]], max_full: int = 400, k: int = 15) -> set[tuple[str, str]]:
    """Blocking for scale: exact-key inverted index + embedding kNN (all pairs when small)."""
    ids = list(items)
    if len(ids) <= max_full:
        return {(ids[i], ids[j]) for i in range(len(ids)) for j in range(i + 1, len(ids))}
    cands = set()
    inv = defaultdict(list)
    for mid, (f, _) in items.items():
        for t, vals in f.get("indicators", {}).items():
            for v in vals:
                inv[(t, v)].append(mid)
    for key, mids in inv.items():
        if 1 < len(mids) <= max(50, len(ids) * 0.02):
            for i in range(len(mids)):
                for j in range(i + 1, len(mids)):
                    cands.add(tuple(sorted((mids[i], mids[j]))))
    for kind in ("text", "clip"):
        vs = [(mid, v[kind].mean(0) if np.ndim(v[kind]) == 2 else v[kind]) for mid, (_, v) in items.items() if kind in v]
        if len(vs) < 2:
            continue
        M = np.stack([x for _, x in vs])
        M = M / (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)
        S = M @ M.T
        for i in range(len(vs)):
            for j in np.argsort(-S[i])[1:k + 1]:
                cands.add(tuple(sorted((vs[i][0], vs[j][0]))))
    return cands


def all_links(items: dict[str, tuple[dict, dict]]) -> list[Link]:
    corpus = Corpus(items)
    out = []
    for a, b in candidate_pairs(items):
        fa, va = items[a]
        fb, vb = items[b]
        out.append(pair(a, fa, va, b, fb, vb, corpus))
    return out
