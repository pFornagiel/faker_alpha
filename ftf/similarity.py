"""Pairwise comparison of two materials: shared identifiers (must-link) + content distance (Gower).

A. Identifiers (config.IDENTIFIER_GROUP): an exact value shared by both materials links them deterministically
   (record linkage, Christen 2012; shared analytics IDs reveal operators, Starov et al. 2018). A value counts only
   if its document frequency df/N <= config.MAX_DF (IDF idea, Spärck Jones 1972); a value held only by the two
   compared materials always counts. Too-common values are kept in the explanation as ignored.
B. Content views, one standard similarity each in [0, 1]:
     text      MinHash Jaccard of word 4-gram shingles on entity-masked landing-page text (Jaccard 1912; Broder 1997)
     ocr       the same measure on the entity-masked text of the creative (OCR of screenshots / keyframes, ad copy)
     semantic  cosine of multilingual-e5-small embeddings after corpus mean-centring (Wang 2024; Mu & Viswanath 2018)
     html      MinHash Jaccard of HTML tag 5-gram shingles, max over page pairs (Cui et al. 2017)
     css       MinHash Jaccard of the page's CSS class names, generated parts masked, max over page pairs
     js        MinHash Jaccard of token 5-grams of own inline scripts with literals masked, max over page pairs
     images    pHash overlap coefficient: share of the smaller image set with a match at Hamming <= PHASH_HAMMING (Zauner 2010)
   Gower (1971) distance: d = 1 - mean(sim_v over views available on both sides); no view -> d = 1, comparable = False.
   Because d is a plain mean, each view contributes exactly sim_v / k.
   `text` and `ocr` compare words, so for two texts in different known languages they are unavailable, not 0:
   a translated copy of a page shares no word shingles by construction (missing value in Gower's sense).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field

import numpy as np

from . import config, lang, web
from .text import jaccard_sig, minhash_sig

VIEWS = ("text", "ocr", "semantic", "html", "css", "js", "images")
VIEW_PL = {"text": "tekst strony", "ocr": "tekst kreacji (OCR)", "semantic": "znaczenie tekstu (e5)", "html": "struktura HTML",
           "css": "klasy CSS", "js": "szkielet skryptów", "images": "obrazy"}
_PAGE_SIG_VIEWS = (("html", "dom"), ("css", "css"), ("js", "js"))       # view -> vector kind, one signature per page
GROUP_PL = {"ad_library": "biblioteka reklam", "domains": "domena", "certificates": "certyfikat TLS",
            "tracking_ids": "identyfikator śledzący",
            "contacts": "kontakt", "kit_files": "plik / szablon kitu", "product": "produkt / platforma"}
TYPE_PL = {
    "ad_id": "ID reklamy", "advertiser_id": "ID reklamodawcy", "landing_domain": "domena docelowa",
    "redirect_domain": "domena w przekierowaniu", "page_host": "host strony", "ocr_domain": "domena widoczna na kreacji",
    "tds_host": "host TDS / trackera", "fb_pixel": "Facebook Pixel", "tiktok_pixel": "TikTok Pixel",
    "ga": "Google Analytics ID", "gtm": "Google Tag Manager", "gads": "Google Ads (AW-) ID",
    "tenant_uuid": "UUID tenanta landing-buildera", "affiliate": "parametr afiliacyjny", "adset": "nazwa zestawu reklam",
    "campaign_param": "ID kampanii w URL", "phone": "telefon", "email": "e-mail", "telegram": "Telegram",
    "whatsapp": "WhatsApp", "wallet": "portfel krypto", "script_hash": "identyczny skrypt (hash)",
    "api_template": "szablon API backendu", "form_endpoint": "endpoint formularza", "path_template": "szablon ścieżki URL",
    "product": "nazwa produktu / platformy", "asset_phash": "obraz na stronie", "advertiser_name": "nazwa reklamodawcy",
    "ip": "adres IP (spoza CDN)", "cert_batch": "certyfikat TLS wystawiony w tej samej minucie",
}


_GROUP_RANK = {g: i for i, g in enumerate(dict.fromkeys(config.IDENTIFIER_GROUP.values()))}


@dataclass
class SharedId:
    group: str
    type: str
    value: str
    df: int
    ignored: bool


@dataclass
class Link:
    a: str
    b: str
    distance: float                 # content (Gower) distance d(a, b) in [0, 1]
    p: float                        # 1 - D(a, b): 1.0 with a counted shared identifier, else 1 - distance
    relation: str                   # duplicate | same_campaign | similar | none
    shared_ids: list[SharedId] = field(default_factory=list)
    views: dict[str, float] = field(default_factory=dict)
    comparable: bool = True
    same_file: bool = False         # identical file (sha256) in both materials

    @property
    def must_link(self) -> bool:
        return self.same_file or any(not s.ignored for s in self.shared_ids)

    def explain(self, n: int = 5) -> str:
        parts = ["identyczny plik (sha256)"] if self.same_file else []
        parts += [f"{TYPE_PL.get(s.type.split('+')[0], s.type)} w obu: „{s.value[:60]}” ({s.df} mat.)"
                  for s in self.shared_ids if not s.ignored][:n]
        parts += [f"{VIEW_PL[v]} {s:.2f}" for v, s in sorted(self.views.items(), key=lambda kv: -kv[1])]
        parts.append(f"odległość treści d = {self.distance:.2f}" if self.comparable else "brak porównywalnej treści")
        return "; ".join(parts)

    def as_dict(self) -> dict:
        return {**asdict(self), "distance": round(self.distance, 3), "p": round(self.p, 3),
                "views": {k: round(v, 3) for k, v in self.views.items()}}


def identifiers(f: dict) -> dict[tuple[str, str], set[str]]:
    """(group, value) -> raw indicator types it came from. Domains are compared as registrable domains."""
    out: dict[tuple[str, str], set[str]] = defaultdict(set)
    for t, vals in (f.get("indicators") or {}).items():
        g = config.IDENTIFIER_GROUP.get(t)
        for v in vals if g else ():
            if g == "domains":
                v = web.registrable_domain(v)
                if not v or (web.is_decoy_or_generic_domain(v) if t == "ocr_domain" else web.is_generic(v)):
                    continue
            elif t in ("api_template", "form_endpoint") and web.is_platform_endpoint(str(v)):
                continue               # also filters features stored before the endpoint list existed
            elif t == "email" and web.is_generic(str(v).rsplit("@", 1)[-1]):
                continue               # placeholder addresses such as name@example.com
            out[(g, str(v))].add(t)
    return out


def _images(f: dict) -> list[str]:
    hs = [im["phash"] for im in f.get("images", []) if im.get("phash") and im.get("kind") != "ui_screenshot"]
    return list(dict.fromkeys(hs + list((f.get("indicators") or {}).get("asset_phash", []))))


def ocr_signature(f: dict) -> list[int] | None:
    """Creative-text MinHash; for materials stored before it existed, computed from the stored OCR text."""
    t = f.get("text") or {}
    if "minhash_ocr_masked" in t:
        return t["minhash_ocr_masked"]
    return minhash_sig(t["ocr_text"], masked=True) if t.get("ocr_text") else None


def _creative_lang(t: dict) -> str | None:
    """Language of the creative text; short OCR text gives none, then the page's language stands in."""
    lo = t.get("lang_ocr")
    return lo if lo and lo != lang.UNKNOWN else t.get("lang")


def _unit(x) -> np.ndarray:
    x = np.atleast_2d(np.asarray(x, dtype=np.float64)).mean(0)
    return x / (np.linalg.norm(x) + 1e-12)


def counted(df: int, n: int) -> bool:
    """Document-frequency filter: a shared value counts if df / N <= MAX_DF (always when only the pair holds it)."""
    return df <= 2 or df / max(1, n) <= config.MAX_DF


class Corpus:
    """Corpus statistics a pair needs: identifier document frequencies and the e5 mean for centring."""

    def __init__(self, items: dict[str, tuple[dict, dict]]):
        self.N = len(items)
        self.ids = {mid: identifiers(f) for mid, (f, _) in items.items()}
        self.df = Counter(k for ids in self.ids.values() for k in ids)
        sem = {mid: _unit(v["text"]) for mid, (_, v) in items.items() if v.get("text") is not None and len(v["text"])}
        if len(sem) >= 3:                      # plain mean-centring (Mu & Viswanath 2018); raw cosine on tiny corpora
            mu = np.mean(list(sem.values()), axis=0)
            sem = {m: x - mu for m, x in sem.items()}
            sem = {m: x / (np.linalg.norm(x) + 1e-12) for m, x in sem.items()}
        self.sem = sem
        self.ocr = {mid: ocr_signature(f) for mid, (f, _) in items.items()}

    def ocr_of(self, mid: str, f: dict):
        return self.ocr[mid] if mid in self.ocr else ocr_signature(f)

    def counted(self, df: int) -> bool:
        return counted(df, self.N)

    def ids_of(self, mid: str, f: dict) -> dict:
        return self.ids[mid] if mid in self.ids else identifiers(f)


def views(ida: str, fa: dict, va: dict, idb: str, fb: dict, vb: dict, corpus: Corpus) -> dict[str, float]:
    out: dict[str, float] = {}
    ta, tb = fa.get("text") or {}, fb.get("text") or {}
    j = jaccard_sig(ta.get("minhash_masked"), tb.get("minhash_masked"))
    if j is not None and not lang.differ(ta.get("lang"), tb.get("lang")):
        out["text"] = j
    j = jaccard_sig(corpus.ocr_of(ida, fa), corpus.ocr_of(idb, fb))
    if j is not None and not lang.differ(_creative_lang(ta), _creative_lang(tb)):
        out["ocr"] = j
    if ida in corpus.sem and idb in corpus.sem:
        out["semantic"] = float(np.clip(corpus.sem[ida] @ corpus.sem[idb], 0.0, 1.0))
    for view, kind in _PAGE_SIG_VIEWS:
        da, db = va.get(kind), vb.get(kind)
        if da is not None and db is not None and len(da) and len(db):
            out[view] = max(jaccard_sig(list(x), list(y)) or 0.0 for x in np.atleast_2d(da) for y in np.atleast_2d(db))
    A, B = sorted((_images(fa), _images(fb)), key=len)
    if A:
        hits = sum(any(bin(int(x, 16) ^ int(y, 16)).count("1") <= config.PHASH_HAMMING for y in B) for x in A)
        out["images"] = hits / len(A)
    return out


def pair(ida: str, fa: dict, va: dict, idb: str, fb: dict, vb: dict, corpus: Corpus) -> Link:
    ia, ib = corpus.ids_of(ida, fa), corpus.ids_of(idb, fb)
    shared = [SharedId(g, "+".join(sorted(ia[(g, v)] | ib[(g, v)])), v, corpus.df.get((g, v), 2),
                       not corpus.counted(corpus.df.get((g, v), 2)))
              for g, v in sorted(set(ia) & set(ib))]
    shared.sort(key=lambda s: (s.ignored, _GROUP_RANK[s.group], s.df, s.type, s.value))
    vs = views(ida, fa, va, idb, fb, vb, corpus)
    d = 1.0 - float(np.mean(list(vs.values()))) if vs else 1.0
    link = Link(ida, idb, d, 0.0, "none", shared, vs, bool(vs),
                bool(set(fa.get("file_shas") or []) & set(fb.get("file_shas") or [])))
    link.p = 1.0 if link.must_link else 1.0 - d
    same_ad = any(s.group == "ad_library" and "ad_id" in s.type and not s.ignored for s in shared)
    if link.same_file or same_ad or (link.comparable and d <= config.DUPLICATE_CUT):
        link.relation = "duplicate"
    elif link.must_link or d <= config.CAMPAIGN_CUT:
        link.relation = "same_campaign"
    elif d <= config.FAMILY_CUT:
        link.relation = "similar"
    return link


def all_links(items: dict[str, tuple[dict, dict]], corpus: Corpus | None = None) -> list[Link]:
    corpus = corpus or Corpus(items)
    ids = list(items)
    return [pair(a, *items[a], b, *items[b], corpus) for i, a in enumerate(ids) for b in ids[i + 1:]]
