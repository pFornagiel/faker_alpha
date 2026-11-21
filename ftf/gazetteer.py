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

NARRATIVE_LEXICON: dict[str, list[str]] = {
    "celebrity_scandal_or_attack": ["zamach", "napasc", "atak", "strzel", "kajdank", "aresztow", "skandal",
                                    "zatrzyman", "brutaln", "pobit"],
    "censored_interview": ["usunieto", "wywiad", "nagranie", "na zywo", "emisj", "ujawni", "sekret",
                           "nie chca, zebys", "zakazan", "ocenzurow"],
    "banker_scandal": ["prezes nbp", "bank", "banki", "premi", "glapinsk"],
    "celebrity_testament_or_death": ["testament", "spadek", "dziedzictw", "zmarl", "pozegnan", "majatek"],
    "state_project_shares": ["orlen", "baltic", "udzial", "spolk skarbu", "program rzadow", "obywatel"],
    "doctor_vs_big_pharma": ["lekarz", "profesor", "koncern", "farmaceut", "ukrywa", "naturaln metod"],
    "investment_event": ["summit", "konferencj", "forum", "kongres"],
    "casino_app": ["app store", "aplikacj", "kasyno", "spin"],
}

URGENCY_CUES = ["tylko dzis", "ostatni", "pozostal", "liczba miejsc", "zostalo", "ograniczon", "wygasa",
                "pilne", "natychmiast", "teraz", "limited time", "spiesz", "do polnocy", "ostatnia szansa"]


def fold(text: str) -> str:
    """lowercase + strip diacritics (ł->l) + NFKC (defeats many homoglyph tricks)."""
    t = unicodedata.normalize("NFKC", text or "").lower()
    t = t.replace("ł", "l")
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[​-‏⁠﻿]", "", t)


def _find(folded: str, table: dict) -> list[str]:
    out = []
    padded = f" {folded} "
    for name, spec in table.items():
        aliases = spec[1] if isinstance(spec, tuple) else spec
        if any(a in padded for a in aliases):
            out.append(name)
    return out


def find_persons(text: str) -> list[str]:
    return _find(fold(text), PERSONS)


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
    """Replace known person names (all alias stems) by <PER> - used to detect 'same template,
    swapped celebrity' variants (e.g. 'Brutalna napaść na Krzysztofa Stanowskiego' vs '... Tomasza Sekielskiego')."""
    f = fold(text)
    for _, (_, aliases) in PERSONS.items():
        for a in aliases:
            if len(a) >= 5:
                f = re.sub(re.escape(a) + r"\w*", " <per> ", f)
    # generic capitalised first-name + surname pattern (Polish declension endings)
    f = re.sub(r"\b(krzysztof|tomasz|rafal|monik|adam|andrzej|donald|robert|anna|karol|piotr|marcin|ewa|"
               r"dorot|jerzy|pawel|michal|grzegorz|sebastian|kamil|wojciech|bogdan|izabel|szymon|"
               r"mateusz|daniel|agnieszk|juli|malgorzat|danut|anit|leszek|roman)\w*", " <per> ", f)
    return re.sub(r"(\s*<per>\s*)+", " <per> ", f)
