"""Human-readable (Polish) labels for enums, signals, families and decisions — shared by the API and exports."""
from __future__ import annotations

from . import config
from .similarity import FAMILY_PL, PL_SIGNAL

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
NARRATIVE_PL = {
    "celebrity_scandal_or_attack": "skandal / atak na celebrytę",
    "censored_interview": "„ocenzurowany wywiad”",
    "banker_scandal": "afera bankowa",
    "celebrity_testament_or_death": "testament / śmierć celebryty",
    "staged_studio_quarrel": "inscenizowana kłótnia w studiu",
    "state_project_shares": "akcje państwowego projektu",
    "national_income_programme": "„narodowy program dochodu”",
    "doctor_vs_big_pharma": "lekarz kontra koncerny",
    "miracle_cure_testimonial": "świadectwo „cudownego leku”",
    "investment_event": "wydarzenie inwestycyjne",
    "casino_app": "aplikacja kasynowa",
    "brand_giveaway": "rozdanie marki",
    "clearance_sale": "wyprzedaż",
    "undelivered_parcel": "niedostarczona paczka",
    "lost_funds_recovery": "odzyskanie utraconych środków",
    "other": "inne",
}
FORMAT_PL = {
    "fake_news_article": "fałszywy artykuł prasowy",
    "fake_news_studio_video": "fałszywe wideo ze studia TV",
    "deepfake_talking_head": "deepfake „gadająca głowa”",
    "static_portrait_with_headline": "portret + nagłówek",
    "product_packshot": "zdjęcie produktu",
    "fake_app_store_page": "fałszywa strona sklepu z aplikacjami",
    "fake_event_page": "fałszywa strona wydarzenia",
    "quiz_or_survey": "quiz / ankieta",
    "ugc_testimonial": "„opinia użytkownika”",
    "other": "inne",
}
ENUM_PL = {**SCAM_TYPE_PL, **NARRATIVE_PL, **FORMAT_PL}

TIER_PL = {"S": "operator", "M": "kit / treść", "W": "kontekst (słaby)"}
TIER_HINT = {
    "S": "ślad, który praktycznie zawsze należy do jednego operatora (ten sam piksel, domena, endpoint, ID reklamy)",
    "M": "ten sam zestaw narzędzi lub ta sama treść/kreacja — mocny, ale może być skopiowany",
    "W": "zgodność kontekstu (ta sama osoba, ten sam typ oszustwa) — sama w sobie niczego nie łączy",
}
FAMILY_HINT = {
    "duplicate": "identyczny plik lub ta sama treść + obraz + domena",
    "infra_ids": "piksele/ID analityki, telefony, komunikatory, portfele, endpointy formularzy",
    "tracking": "ID reklam/kampanii, parametry afiliacyjne, UUID tenanta landing-buildera, hosty TDS",
    "domain": "ta sama domena docelowa, w przekierowaniu, widoczna na kreacji; seria rejestracji",
    "advertiser": "ten sam reklamodawca w bibliotece reklam",
    "kit": "nazwy/hashe skryptów, szablon API, sygnatura parametrów URL, szablon DOM, favicon",
    "assets": "ten sam obraz osadzony na stronach docelowych",
    "visual": "podobny wygląd kreacji (CLIP), układ (DINOv2), prawie identyczny obraz (pHash)",
    "narrative": "prawie identyczny tekst, szablon tytułu, podobna narracja, charakterystyczne frazy",
    "offer": "ta sama nazwa produktu lub fikcyjnej platformy",
    "persons": "ta sama osoba (twarz z bazy referencyjnej / w tekście), ta sama nieznana twarz",
    "concept": "zgodny typ oszustwa, szablon narracji, format kreacji (atrybuty LLM)",
    "hosting": "ten sam adres IP spoza CDN, ta sama para serwerów NS",
}
FAMILY_ORDER = ["duplicate", "infra_ids", "tracking", "domain", "advertiser", "kit", "assets", "visual", "narrative",
                "offer", "persons", "concept", "hosting"]

RELATION_PL = {
    "duplicate": "duplikat",
    "same_campaign": "ta sama kampania",
    "similar": "podobny playbook",
    "none": "brak powiązania",
}
RELATION_HINT = {
    "duplicate": "to ten sam materiał zgłoszony ponownie",
    "same_campaign": f"p ≥ {config.LINK_THRESHOLD} i (dowód operatorski ≥ 0.5 lub dowód kit/treść ≥ 0.7 lub ≥ 2 niezależne rodziny)",
    "similar": f"p ≥ {config.SIMILAR_THRESHOLD} lub ten sam „przepis” (narracja, koncepcja, wizualia, osoby) — bez dowodu wspólnego operatora",
    "none": f"p < {config.SIMILAR_THRESHOLD} i brak wspólnego playbooka",
}

DECISION_PL = {
    "duplicate": ("Duplikat", "Ten materiał był już analizowany (identyczny plik lub ta sama treść, obraz i domena)."),
    "known_campaign": ("Znana kampania", "Materiał ma wspólne ślady z kampanią w bazie — przypisano go do niej."),
    "merge_proposal": ("Propozycja scalenia", "Materiał silnie łączy się z dwiema kampaniami naraz — możliwe, że to jedna kampania."),
    "candidate_review": ("Do weryfikacji", "Umiarkowane podobieństwo z kampanią — potrzebna decyzja analityka."),
    "new_campaign": ("Nowy wzorzec", "Brak wystarczających wspólnych śladów — prawdopodobnie nowa kampania."),
}

SOURCE_PL = {"organizer": "zbiór organizatora", "upload": "przesłany plik", "url": "przechwycony URL", "text": "tekst"}

LLM_FIELDS_PL = [
    ("scam_type", "Typ oszustwa"),
    ("narrative_template", "Szablon narracji"),
    ("creative_format", "Format kreacji"),
    ("product_or_platform_name", "Produkt / platforma"),
    ("spoofed_media_outlet", "Podszyte medium"),
    ("impersonated_persons", "Podszyte osoby"),
    ("impersonated_brands", "Podszyte marki"),
    ("fictional_persona", "Fikcyjna persona"),
    ("promised_benefit", "Obietnica"),
    ("entry_cost", "Koszt wejścia"),
    ("call_to_action", "Wezwanie do działania"),
    ("urgency_cues", "Presja czasu"),
    ("emotional_triggers", "Wyzwalacze emocji"),
    ("target_audience", "Grupa docelowa"),
    ("distinctive_phrases", "Charakterystyczne frazy"),
]


def signal_label(t: str) -> str:
    return PL_SIGNAL.get(t, t)


def family_label(f: str) -> str:
    return FAMILY_PL.get(f, f)


def enum_label(v) -> str:
    return ENUM_PL.get(v, v) if isinstance(v, str) else v
