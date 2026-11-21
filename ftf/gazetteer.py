"""Polish scam-ad gazetteer: impersonated persons, brands, media outlets and scam-type lexicons.

Sources (see research/04_prior_art_features_clustering.md §1.5): NASK list of persons used in
deepfakes (07.2024), NASK OAD reports 2025, CSIRT KNF 2024/2025, CERT Polska 2025 report,
Demagog, Bitdefender 2026, plus persons observed in the organiser sample set.
Used as the offline (no-LLM) entity extractor and to normalise LLM output.
"""
from __future__ import annotations

import re
import unicodedata

# canonical name -> (group, aliases)  — aliases are matched on diacritic-folded lowercase text
PERSONS: dict[str, tuple[str, list[str]]] = {
    "Rafał Brzoska": ("przedsiębiorca", ["brzosk", "rafal brzosk", "prezes inpost"]),
    "Andrzej Duda": ("polityk", ["andrzej dud", "prezydent duda"]),
    "Karol Nawrocki": ("polityk", ["nawrock"]),
    "Donald Tusk": ("polityk", ["tusk"]),
    "Adam Glapiński": ("bankier", ["glapinsk", "prezes nbp", "prezesa nbp", "prezes narodowego banku"]),
    "Robert Lewandowski": ("sportowiec", ["lewandowsk"]),
    "Anna Lewandowska": ("influencer", ["anna lewandowsk"]),
    "Rafał Trzaskowski": ("polityk", ["trzaskowsk"]),
    "Sławomir Mentzen": ("polityk", ["mentzen"]),
    "Grzegorz Braun": ("polityk", ["grzegorz braun", "brauna"]),
    "Sebastian Kulczyk": ("przedsiębiorca", ["kulczyk"]),
    "Kamil Labudda (Budda)": ("influencer", ["budda", "labudd"]),
    "Wojciech Cejrowski": ("celebryta", ["cejrowsk"]),
    "Krzysztof Simon": ("lekarz", ["krzysztof simon", "prof. simon", "profesor simon"]),
    "Krzysztof Bielecki": ("lekarz", ["bieleck"]),
    "Bogdan Rymanowski": ("dziennikarz", ["rymanowsk"]),
    "Izabela Leszczyna": ("polityk", ["leszczyn"]),
    "Grzegorz Ryś": ("duchowny", ["kardynal rys", "kard. rys", "grzegorz rys"]),
    "Monika Olejnik": ("dziennikarz", ["olejnik"]),
    "Krzysztof Stanowski": ("dziennikarz", ["stanowsk"]),
    "Tomasz Sekielski": ("dziennikarz", ["sekielsk"]),
    "Daniel Obajtek": ("przedsiębiorca", ["obajtk", "obajtek"]),
    "Mateusz Morawiecki": ("polityk", ["morawieck"]),
    "Szymon Hołownia": ("polityk", ["holowni"]),
    "Kuba Wojewódzki": ("celebryta", ["wojewodzk"]),
    "Krzysztof Ibisz": ("celebryta", ["ibisz"]),
    "Agnieszka Chylińska": ("celebryta", ["chylinsk"]),
    "Julia Wieniawa": ("celebryta", ["wieniaw"]),
    "Małgorzata Rozenek-Majdan": ("celebryta", ["rozenek"]),
    "Omena Mensah": ("celebryta", ["mensah"]),
    "Danuta Holecka": ("dziennikarz", ["holeck"]),
    "Piotr Kraśko": ("dziennikarz", ["krasko"]),
    "Anita Werner": ("dziennikarz", ["anita werner"]),
    "Dorota Gawryluk": ("dziennikarz", ["gawryluk"]),
    "Marcin Prokop": ("dziennikarz", ["prokop"]),
    "Dorota Wellman": ("dziennikarz", ["wellman"]),
    "Ewa Drzyzga": ("dziennikarz", ["drzyzg"]),
    "Jerzy Zięba": ("lekarz", ["zieba", "jerzy zieb"]),
    "Ewa Dąbrowska": ("lekarz", ["ewa dabrowsk"]),
    "Paweł Grzesiowski": ("lekarz", ["grzesiowsk"]),
    "Michał Sutkowski": ("lekarz", ["sutkowsk"]),
    "Roman Giertych": ("polityk", ["giertych"]),
    "Krzysztof Bosak": ("polityk", ["bosak"]),
    "Michał Sołowow": ("przedsiębiorca", ["solowow"]),
    "Leszek Czarnecki": ("przedsiębiorca", ["leszek czarneck"]),
    "Cristiano Ronaldo": ("sportowiec", ["ronaldo"]),
    "Elon Musk": ("przedsiębiorca", ["elon musk", "muska"]),
    "Mark Zuckerberg": ("przedsiębiorca", ["zuckerberg"]),
    "Stanisław Soyka": ("celebryta", ["soyka", "sojka"]),
}

BRANDS: dict[str, tuple[str, list[str]]] = {
    "Orlen": ("spółka_skarbu", ["orlen"]),
    "Baltic Pipe": ("spółka_skarbu", ["baltic pipe", "baltica"]),
    "PGE": ("spółka_skarbu", [" pge "]),
    "PKO BP": ("bank", ["pko bp", "pko bank"]),
    "NBP": ("instytucja", [" nbp", "narodowy bank polski", "narodowego banku polskiego"]),
    "KNF": ("instytucja", [" knf", "komisja nadzoru finansowego"]),
    "ZUS": ("instytucja", [" zus"]),
    "GPW": ("instytucja", [" gpw", "gielda papierow"]),
    "InPost": ("firma", ["inpost", "paczkomat"]),
    "Poczta Polska": ("firma", ["poczta polska"]),
    "Allegro": ("firma", ["allegro"]),
    "OLX": ("firma", [" olx"]),
    "Lidl": ("firma", [" lidl"]),
    "Biedronka": ("firma", ["biedronk"]),
    "Rossmann": ("firma", ["rossmann"]),
    "Żabka": ("firma", [" zabka", " zabki"]),
    "Lotto": ("firma", [" lotto"]),
    "XTB": ("firma", [" xtb"]),
    "Tesla": ("firma", [" tesla"]),
    "Meta/Facebook": ("platforma", ["facebook", " meta "]),
    "App Store": ("platforma", ["app store", "appstore"]),
    "Google Play": ("platforma", ["google play"]),
}

MEDIA: dict[str, list[str]] = {
    "TVN24": ["tvn24", "tvn 24", " tvn "], "Gazeta.pl": ["gazeta.pl", "gazeta pl"],
    "Polsat News": ["polsat"], "Onet": ["onet"], "Wprost": ["wprost"], "TVP Info": ["tvp info", "tvp"],
    "Fakt": ["fakt.pl", " fakt "], "Business Insider": ["business insider", "businessinsider"],
    "Rzeczpospolita": ["rzeczpospolita", "rp.pl"], "Interia": ["interia"], "WP": ["wp.pl", "wirtualna polska"],
    "Money.pl": ["money.pl"], "Kanał Zero": ["kanal zero", "kanał zero"], "Forbes": ["forbes"],
}

# scam-type lexicons (diacritic-folded stems) -> rule-based scam_type when no LLM is available
SCAM_LEXICON: dict[str, list[str]] = {
    "investment_fake_platform": ["inwestyc", "zarabia", "zarobi", "platform", "zysk", "kapital", "kryptowalut",
                                 "bitcoin", "gield", "akcj", "dochod pasywn", "algorytm", "sztuczn inteligencj",
                                 "trading", "inwestor", "fundusz", "portfel", "wplata", "250 zl", "1000 zl"],
    "health_miracle_product": ["cukrzyc", "nadcisnien", "stawy", "staw", "grzybic", "odchudz", "schudn",
                               "prostat", "kardio", "serce", "cholesterol", "kapsulk", "suplement",
                               "lekarz", "leczen", "bol ", "dolegliw", "zdrow", "chorob", "apteka", "metabo", "potencj"],
    "illegal_gambling": ["kasyno", "casino", "spin", "bonus", "bonanza", "slot", "wygran", "jackpot", "zaklad"],
    "fake_giveaway_survey": ["nagrod", "ankiet", "rozdaj", "voucher", "bon ", "gratis", "darmow", "losowan"],
    "fund_recovery": ["odzyskan", "odzyska", "zwrot srodkow", "interpol", "europol", "cyberpolic"],
    "fake_shop": ["promocj", "wyprzedaz", "-70%", "-80%", "dostawa", "koszyk", "sklep"],
    "parcel_delivery_phishing": ["przesylk", "paczk", "doplat", "kurier"],
    "political_disinfo_ad": ["wybor", "rzad", "sejm", "partia", "ukrain", "imigrant"],
}


def fold(text: str) -> str:
    """lowercase + strip diacritics (ł->l) + NFKC (defeats many homoglyph tricks)."""
    t = unicodedata.normalize("NFKC", text or "").lower()
    t = t.replace("ł", "l")
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[​-‏⁠﻿]", "", t)


# Common Polish first names (folded stems) that should NOT trigger "Robert Lewandowski"
# when paired with the very common surname "Lewandowski".
_OTHER_FIRST_NAME_RX = re.compile(
    r"^(?:tomasz|jan|piotr|marek|mark|andrzej|krzysztof|pawel|pawl|michal|marcin|lukasz|"
    r"adam|jakub|kamil|dawid|mateusz|wojciech|maciej|grzegorz|rafal|sebastian|daniel|szymon|"
    r"anna|ann|agnieszk|zofi|katarzyn|magdalen|malgorzat|ew|mari|joann|barbar)\w*$"
)
_ROBERT_LEW_FULL_RX = re.compile(r"\brobert\w*\s+lewandowsk\w*\b")
_MASC_LEW_RX = re.compile(r"\blewandowski(?:ego|emu|m)?\b")


def _alias_regex(alias: str) -> re.Pattern:
    """Compile a word-boundary regex for an alias (supporting inflected multi-word Polish names)."""
    parts = alias.strip().split()
    if len(parts) == 1:
        return re.compile(r"\b" + re.escape(parts[0]) + r"\w*")
    # Allow Polish declension suffix on each token (e.g. 'andrzej dud' matches 'andrzeju dudzie')
    return re.compile(r"\b" + r"\w*\s+".join(re.escape(p) for p in parts) + r"\w*")


def _matches_robert_lewandowski(folded: str) -> bool:
    """Match 'Robert Lewandowski' (inflected) or standalone masculine 'Lewandowski(ego|emu|m)',
    avoiding feminine 'Lewandowska' and other first names like 'Tomasz Lewandowski'."""
    if _ROBERT_LEW_FULL_RX.search(folded):
        return True
    for m in _MASC_LEW_RX.finditer(folded):
        prefix = folded[: m.start()].rstrip()
        prev_word = prefix.rsplit(None, 1)[-1] if prefix else ""
        if not _OTHER_FIRST_NAME_RX.match(prev_word):
            return True
    return False


_PERSON_RX: dict[str, list[re.Pattern]] = {
    pname: [_alias_regex(a) for a in aliases]
    for pname, (_, aliases) in PERSONS.items()
    if pname != "Robert Lewandowski"
}

_MASK_FIRST_NAMES = re.compile(
    r"\b(slawomir|krzysztof|tomasz|rafal|monik|adam|andrzej|donald|robert|anna|karol|piotr|marcin|ewa|"
    r"dorot|jerzy|pawel|michal|grzegorz|sebastian|kamil|wojciech|bogdan|izabel|szymon|"
    r"mateusz|daniel|agnieszk|juli|malgorzat|danut|anit|leszek|roman|stanislaw|elon|mark|cristiano)\w*"
)


def _find(folded: str, table: dict) -> list[str]:
    out = []
    padded = f" {folded} "
    for name, spec in table.items():
        aliases = spec[1] if isinstance(spec, tuple) else spec
        if any(a in padded for a in aliases):
            out.append(name)
    return out


def find_persons(text: str) -> list[str]:
    f = fold(text)
    if not f:
        return []
    out = []
    for name in PERSONS:
        if name == "Robert Lewandowski":
            if _matches_robert_lewandowski(f):
                out.append(name)
        elif any(rx.search(f) for rx in _PERSON_RX[name]):
            out.append(name)
    return out


def find_brands(text: str) -> list[str]:
    return _find(fold(text), BRANDS)


def find_media(text: str) -> list[str]:
    return _find(fold(text), MEDIA)


def lexicon_scores(text: str, lex: dict[str, list[str]]) -> dict[str, int]:
    f = f" {fold(text)} "
    return {k: sum(f.count(stem) for stem in stems) for k, stems in lex.items()}


def best_label(text: str, lex: dict[str, list[str]], min_hits: int = 2) -> str | None:
    sc = lexicon_scores(text, lex)
    k, v = max(sc.items(), key=lambda kv: kv[1]) if sc else (None, 0)
    return k if v >= min_hits else None


def mask_entities(text: str) -> str:
    """Replace known person names (all alias stems, including short surnames like Tusk/Duda and
    Polish inflected first+last names) by <per> - used to detect 'same template, swapped celebrity'."""
    f = fold(text)
    for _, (_, aliases) in PERSONS.items():
        for a in aliases:
            rx = _alias_regex(a)
            f = rx.sub(" <per> ", f)
    # Also mask inflected 'Duda' (duda/dudy/dudzie/dude/dudo) when appearing without 'Andrzej'
    f = re.sub(r"\bdud(?:a|y|zie|e|o)\b", " <per> ", f)
    # Generic Polish first names (with declension endings)
    f = _MASK_FIRST_NAMES.sub(" <per> ", f)
    return re.sub(r"(\s*<per>\s*)+", " <per> ", f)
