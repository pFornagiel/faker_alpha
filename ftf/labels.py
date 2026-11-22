"""Human-readable (Polish) labels for enums, identifier groups, content views, relations and decisions."""
from __future__ import annotations

from . import config
from .similarity import GROUP_PL, TYPE_PL, VIEW_PL

SCAM_TYPE_PL = {
    "investment_fake_platform": "fałszywa platforma inwestycyjna",
    "fund_recovery": "„odzyskiwanie środków”",
    "health_miracle_product": "„cudowny” produkt zdrowotny",
    "fake_giveaway_survey": "fałszywa ankieta / rozdanie",
    "fake_shop": "fałszywy sklep",
    "parcel_delivery_phishing": "phishing „na paczkę”",
    "gov_refund_or_benefit_phishing": "phishing „na zwrot / świadczenie”",
    "illegal_gambling": "nielegalny hazard",
    "marketplace_phishing": "phishing „na marketplace”",
    "job_task_scam": "oszustwo „praca / zadania”",
    "subscription_trap": "pułapka subskrypcyjna",
    "political_disinfo_ad": "dezinformacja polityczna",
    "other": "inne",
}
ENUM_PL = SCAM_TYPE_PL

GROUP_ORDER = ["ad_library", "domains", "tracking_ids", "contacts", "kit_files", "product"]
GROUP_HINT = {
    "ad_library": "to samo ID reklamy lub reklamodawcy w bibliotece reklam",
    "domains": "ta sama domena docelowa, w przekierowaniu, host TDS lub domena widoczna na kreacji",
    "tracking_ids": "piksele i ID analityki, UUID tenanta landing-buildera, parametry afiliacyjne, ID kampanii w URL",
    "contacts": "ten sam telefon, e-mail, Telegram, WhatsApp lub portfel krypto",
    "kit_files": "identyczny skrypt, szablon API backendu, endpoint formularza, szablon ścieżki URL",
    "product": "ta sama nazwa produktu lub fikcyjnej platformy",
}
VIEW_HINT = {
    "text": "MinHash-Jaccard 4-gramów słów tekstu strony docelowej z zamaskowanymi osobami (Broder 1997)",
    "ocr": "ta sama miara na tekście kreacji (OCR zrzutów i klatek wideo, treść reklamy), osoby zamaskowane",
    "semantic": "cosinus embeddingów multilingual-e5-small po odjęciu średniej korpusu (Mu & Viswanath 2018)",
    "html": "MinHash-Jaccard 5-gramów znaczników HTML (Cui et al. 2017)",
    "css": "MinHash-Jaccard zbioru nazw klas CSS strony; części generowane automatycznie są zamaskowane",
    "js": "MinHash-Jaccard 5-gramów tokenów własnych skryptów strony; napisy i liczby są zamaskowane",
    "images": "odsetek obrazów mniejszego zbioru z odpowiednikiem pHash w odległości Hamminga ≤ "
              f"{config.PHASH_HAMMING} (Zauner 2010)",
}

RELATION_PL = {
    "duplicate": "duplikat",
    "same_campaign": "ta sama kampania",
    "similar": "podobna treść",
    "none": "brak powiązania",
}
RELATION_HINT = {
    "duplicate": f"ten sam plik, to samo ID reklamy lub odległość treści d ≤ {config.DUPLICATE_CUT}",
    "same_campaign": f"wspólny identyfikator (obecny w ≤ {config.MAX_DF:.0%} materiałów) lub d ≤ {config.CAMPAIGN_CUT}",
    "similar": f"brak wspólnego identyfikatora, ale treść podobna: d ≤ {config.FAMILY_CUT}",
    "none": f"brak wspólnego identyfikatora i d > {config.FAMILY_CUT}",
}

DECISION_PL = {
    "duplicate": ("Duplikat", "Ten materiał był już analizowany (ten sam plik, to samo ID reklamy lub niemal identyczna treść)."),
    "known_campaign": ("Znana kampania", "Materiał ma wspólny identyfikator z kampanią w bazie lub jego treść jest bliska "
                                         f"pojedynczemu znanemu materiałowi (najbliższy sąsiad, 1-NN — Cover & Hart 1967; d ≤ {config.CAMPAIGN_CUT}) — przypisano go "
                                         "do kampanii tego materiału."),
    "merge_proposal": ("Propozycja scalenia", "Materiał ma wspólne identyfikatory z dwiema kampaniami naraz — możliwe, że to jedna kampania."),
    "new_campaign": ("Nowy wzorzec", "Brak wspólnych identyfikatorów i żaden znany materiał nie jest dość bliski treścią — prawdopodobnie nowa kampania."),
}

SOURCE_PL = {"organizer": "zbiór organizatora", "upload": "przesłany plik", "url": "przechwycony URL", "text": "tekst"}

LLM_FIELDS_PL = [
    ("scam_type", "Typ oszustwa"),
    ("product_or_platform_name", "Produkt / platforma"),
    ("spoofed_media_outlet", "Podszyte medium"),
    ("impersonated_persons", "Podszyte osoby"),
    ("impersonated_brands", "Podszyte marki"),
]


def signal_label(t: str) -> str:
    return TYPE_PL.get(t, t)


def group_label(g: str) -> str:
    return GROUP_PL.get(g, g)


def view_label(v: str) -> str:
    return VIEW_PL.get(v, v)


def enum_label(v) -> str:
    return ENUM_PL.get(v, v) if isinstance(v, str) else v
