# FakeTrace — metodyka (Kolekcjoner Fejków / Follow the Fake)

> Cel: z chaosu pojedynczych podejrzanych reklam wydobyć **wspólne ślady** i połączyć materiały w
> **kampanie**, wskazując dla każdego powiązania **przesłanki** i ich **wiarygodność**.
> Nie budujemy detektora pojedynczej fałszywej reklamy — budujemy metodę łączenia.

## 1. Model danych

* **Materiał (incydent)** = jeden folder przypadku ze zbioru organizatora, jeden przesłany plik
  (zrzut ekranu, wideo, HTML, HAR, MHTML, ZIP), jeden przechwycony URL, jedna pozycja z biblioteki
  reklam albo tekstowa wskazówka (nazwa produktu, treść reklamy).
* Materiał grupuje **artefakty**: strony docelowe (zapisany HTML + `_files/`, HAR, MHTML, zrzut z
  narzędzia archiwizującego: `manifest.json`, `dom.html`, `page.har`, `resources/`), kreacje
  (zrzuty ekranu z FB/IG/telefonu, klatki wideo), metadane (`*.info.json` z yt-dlp — biblioteka
  reklam Meta, manifesty capture), tekst.
* Loader jest tolerancyjny: brak strony (404), usunięte wideo (`video_deleted.txt`), sam zrzut
  ekranu — wszystko to jest poprawnym materiałem; brakujące modalności po prostu nie głosują.

## 2. Pozyskiwanie (warstwa acquisition)

| Źródło | Co daje | Status |
|---|---|---|
| Zbiór organizatora / upload | HTML, HAR, MHTML, zrzuty, wideo, info.json | ✅ |
| Przechwycenie URL (`ftf/capture.py`) | łańcuch przekierowań w 3 profilach klienta (bot / desktop PL / **FB in-app Android + Referer l.facebook.com**) → wykrywanie **cloakingu**; render Playwright (HAR + DOM + screenshot) | ✅ |
| Lista ostrzeżeń **CERT Polska** (`hole.cert.pl/domains/v2/domains.json`) | ~600–900 nowych domen/dzień; delta po `RegisterPositionId` + filtr słów kluczowych | ✅ live |
| **Microsoft Ad Library API** (bez klucza) | reklamy EOG, `DestinationUrl`, PL=`151` | ✅ live |
| **Google Ads Transparency Center** (RPC) | pivot: reklamodawca/domena → kreacje, PL=`2616` | ✅ live |
| **Meta Ad Library** | API `ads_archive` (token, instrukcja w README); kreacje po ID reklamy przez **yt-dlp `facebook:ads`** — dokładnie tak organizator pozyskał przypadek 5 | ✅ (token opcjonalny) |
| LinkedIn Ad Library | wyszukiwanie po słowie kluczowym (HTML) | ✅ |

Szczegóły, endpointy i weryfikacja „na żywo”: `research/01_ad_libraries_and_platform_scraping.md`,
`research/02_web_infrastructure_osint.md`.

## 3. Ekstrakcja cech (`ftf/pipeline.py`)

### 3.1 Warstwa web / infrastruktura (`ftf/web.py`) — najsilniejsze ślady operatora
Z URL-i (w tym `saved from url=` w zapisanych stronach, `page_url` w manifestach), HTML i HAR:

* **identyfikatory śledzące**: Facebook Pixel (`fbq('init')`, `facebook.com/tr?id=`, parametry
  `pxl=`, `fbpx=`), GA/GA4, GTM, Google Ads `AW-`, TikTok Pixel, Yandex Metrika, Clarity, Hotjar,
  klucze Sentry, reCAPTCHA, build ID (Next/Nuxt);
* **parametry kampanii/afiliacji w URL**: `ad_id`, `adset_name`, `acc=`, `land_id`, `_camp_id`,
  `trafficsource`, numeryczne ID kampanii Meta w `utm_*`;
* **sygnatura TDS** — kształt parametrów (`utm_id=A20&utm_medium=A10&…&utm_visit=U`): ten sam
  system dystrybucji ruchu na różnych domenach;
* **UUID tenanta landing-buildera** w ścieżkach zasobów (`/_cdn/production/landing-cdn/<uuid>/…`);
* **endpointy formularzy/API** (POST z HAR, `form action`) po **usunięciu identyfikatorów sesji**
  (`/api/v1/trigger/field/{id}/`) oraz ich szablon bez hosta (ten sam backend = ten sam kit);
* kontakty: telefony, e-maile, Telegram, WhatsApp, portfele krypto;
* nazwy i hashe skryptów 1st-party (z HAR), nazwy CSS, favicon (mmh3 jak Shodan);
* **szablon DOM**: MinHash 5-gramów sekwencji tagów;
* domeny: docelowa, w łańcuchu przekierowań, hosty TDS; IP serwerów z HAR **z odfiltrowaniem CDN**
  (Cloudflare, Meta, Google, Akamai…), nagłówki `server`.
* **metadane domen online** (`ftf/enrich.py`, cache 7 dni, `FTF_ENRICH=0` offline): RDAP
  (rejestrator, data utworzenia, NS), DNS (A/NS/MX), crt.sh (pierwszy certyfikat, SAN), obecność na
  liście CERT Polska. Wskaźniki: **para NS** (dla Cloudflare przypisywana per konto; domyślne NS
  rejestratorów są pomijane jako generyczne) oraz **seria rejestracji** `rejestrator | para NS | dzień
  utworzenia` — domeny jednego operatora rejestrowane hurtem (np. `civicdaybook.live` i
  `healthlinkq.pro` utworzone 2026-10-08, dzień przed reklamą).

### 3.2 Warstwa wizualna (`ftf/vision.py`)
Zrzuty kreacji i klatki wideo (8 równomiernie, z odrzuceniem czarnych klatek — technika omijania
moderacji opisana przez CSIRT KNF):
* **pHash / dHash / colorhash** (duplikaty, rekompresja) po przycięciu jednolitych ramek i **wycięciu kreacji
  ze zrzutu feedu** (najwyższy pas wierszy „obrazkowych” — usuwa interfejs aplikacji, który dominował CLIP/DINO);
* zrzuty **interfejsu platformy** (szczegóły reklamy w bibliotece, komentarze) są rozpoznawane po OCR i wyłączane
  z podobieństwa wizualnego (zostają: OCR, ID reklamy z „Identyfikator biblioteki”, reklamodawca nad „Sponsorowane”);
* **CLIP ViT-B/32** (ONNX int8) — „wygląd” reklamy; **DINOv2-small** — układ/szablon graficzny;
* **OCR** RapidOCR PP-OCRv6 (polskie znaki) z pozycjami linii → tekst kreacji + **sygnatura
  layoutu** (siatka 4×4 obecności tekstu i twarzy = szablon produkcji);
* QR (OpenCV), domeny widoczne na kreacji (`ocr_domain` ↔ domena docelowa innego materiału);
* **obrazy osadzone na stronach** (`_files/`, `resources/`, obrazy z HAR) → pHash jako wskaźnik
  „ten sam obraz na dwóch stronach”.

### 3.3 Osoby (`ftf/faces.py`)
* detekcja **SCRFD** + embedding **ArcFace** (InsightFace buffalo_l, ONNX bez pakietu insightface);
* **baza referencyjna** 29 najczęściej podszywanych osób (lista z raportów NASK/CSIRT KNF/Demagog,
  zdjęcia z Wikimedia Commons, kotwica = portret z Wikipedii, filtr spójności) — `tools/build_face_gallery.py`;
* jakość twarzy (score detektora × rozmiar × ostrość — w duchu MagFace/eDifFIQA) waży dopasowania;
* **nieznane twarze** też są śladem: ta sama „ekspertka”/„lekarz” na różnych reklamach = persona kampanii.
* Celebryta jest **hubem** (występuje w wielu kampaniach) → sam w sobie jest słabym dowodem.

### 3.4 Tekst / narracja (`ftf/text.py`, `ftf/gazetteer.py`)
* **MinHash** 4-gramów słów (near-duplicate) — na tekście strony i osobno na tekście OCR kreacji;
* **MinHash po zamaskowaniu osób** (`<per>`): wykrywa „ten sam szablon, podmieniony celebryta”
  (np. „Brutalna napaść na Krzysztofa Stanowskiego…” ↔ „…na Tomasza Sekielskiego…”);
* **szablon tytułu** (osoby, liczby, nazwy mediów zamaskowane) + podobieństwo 3-gramów;
* **multilingual-e5-small** (ONNX int8) — podobieństwo narracji semantycznej; embeddingi są **centrowane średnią
  korpusu** (korekta anizotropii: surowe cos dla niepowiązanych polskich stron scamowych wynosiły 0.89–0.93);
  opcjonalnie **EmbeddingGemma-2** (`FTF_GEMMA=1`, lepszy na polskim STS, wolniejszy);
* YAKE (słowa kluczowe), kwoty (`zł`, `PLN`), gazetteer osób / marek / mediów (NFKC + usunięcie
  diakrytyków i znaków zero-width = odporność na homoglify).

### 3.5 Augmentacja cech przez LLM (`ftf/llm.py`)
Pomysł „z modelu auta wywnioskuj typ nadwozia” jest ugruntowany w literaturze (CAAFE, FeatLLM,
keyphrase expansion — Viswanathan i in. 2023, TnT-LLM). LLM (Claude Haiku przez `claude -p`,
alternatywnie Gemini, fallback regułowy) zwraca **JSON ze słownikami zamkniętymi (enum)**:
`scam_type`, `narrative_template`, `creative_format`, `impersonated_persons`, `impersonated_brands`,
`spoofed_media_outlet`, `product_or_platform_name`, `promised_benefit`, `call_to_action`,
`urgency_cues`, `emotional_triggers`, `fictional_persona`, `distinctive_phrases`, `evidence`.
Atrybuty stają się cechami: kategorie → zgodność (a **sprzeczność `scam_type` = dowód ujemny**),
nazwy produktów/platform i charakterystyczne frazy → wskaźniki dyskretne (rzadkość jak niżej).
Wyniki są cache’owane po hashu treści.

**Iteracyjne odkrywanie cech** (`tools/llm_refine.py`): dla grup niejednoznacznych (ta sama rodzina-
playbook, różne kampanie; krawędzie 0.30–0.55) LLM dostaje profile materiałów i **proponuje nowe
atrybuty rozróżniające** (np. styl nazw fikcyjnych platform, motyw historii, rola celebryty), od razu
je wypełniając. Zaakceptowane atrybuty trafiają do `data/cache/llm_extra_schema.json` i stają się
częścią schematu ekstrakcji dla **wszystkich kolejnych materiałów**; zgodność wartości jest
dowodem w rodzinie `concept` (ważonym rzadkością). To realizuje pętlę: klastry → rozbieżności →
nowe cechy → lepsze klastry.

## 4. Podobieństwo — ważone, probabilistyczne, wyjaśnialne (`ftf/similarity.py`)

Dla pary materiałów zbieramy **dowody** (sygnał, wartość, waga, opis PL), pogrupowane w **rodziny**:

| Rodzina | Tier | Przykłady |
|---|---|---|
| `duplicate` | S | identyczny plik (sha256); ta sama treść + obraz + domena |
| `infra_ids` | S | Pixel/GA/GTM/AW, telefon, Telegram, portfel, endpoint formularza |
| `tracking` | S | ID reklamy/kampanii Meta, parametry afiliacyjne, UUID tenanta, host TDS |
| `domain` | S | ta sama domena docelowa / w łańcuchu / widoczna na kreacji |
| `advertiser` | S | to samo ID/nazwa reklamodawcy w bibliotece reklam |
| `kit` | M | nazwy/hashe skryptów, szablon API, sygnatura parametrów URL, szablon DOM, favicon |
| `assets` | M | ten sam obraz osadzony na stronach |
| `visual` | M | CLIP, DINOv2, pHash kreacji; ten sam kadr twarzy |
| `narrative` | M | MinHash (surowy / zamaskowany / OCR), szablon tytułu, e5, frazy |
| `offer` | M | ta sama nazwa produktu/platformy |
| `persons` | W | ta sama osoba (twarz z bazy / w tekście); ta sama nieznana twarz (M-) |
| `concept` | W | zgodny `scam_type`, `narrative_template`, `creative_format`, podszyte medium |
| `hosting` | W | ten sam adres IP spoza CDN |

**Wskaźniki dyskretne**: waga = `prior(typ) × (0.35 + 0.65·rzadkość)`, gdzie
`rzadkość = log(N/df) / log(N/2)` (intuicja Fellegi–Sunter: zgodność na wartości występującej w 2 z
1000 reklam jest mocna, na wartości z połowy korpusu — szumem). Wartości obecne w >50% materiałów
(i ≥6) to **huby** — są ignorowane i *raportowane jako pominięte* (np. Cloudflare, popularny
celebryta).

**Sygnały ciągłe** → dowód przez rampę liniową `[lo, hi] → [0, w_max]` (progi w `ftf/config.py`;
punkty startowe z literatury i kalibracji na zbiorze przykładowym).

**Łączenie**: w rodzinie noisy-OR dowodów, między rodzinami noisy-OR →
`p = 1 − Π(1 − s_rodziny)`, z zabezpieczeniami:
1. tylko słabe rodziny (osoby/koncepcja/hosting) → `p ≤ 0.45` (sam celebryta nic nie łączy);
2. sprzeczny `scam_type` bez dowodu operatorskiego → `p × 0.6`;
3. pary **nieporównywalne** (brak wspólnej modalności — np. sam zrzut vs sam HAR) są oznaczane i
   nie zaniżają średnich przy klastrowaniu (niekompletne dane).

**Relacja krawędzi**: `duplicate` (rodzina duplicate ≥ 0.97) · `same_campaign` (`p ≥ 0.55` i
[dowód S ≥ 0.5 lub dowód M ≥ 0.7 lub ≥ 2 niezależne rodziny]) · `similar` (`p ≥ 0.30` lub podobny
playbook) · `none`. **Lista dowodów jest uzasadnieniem krawędzi** (UI, graf, CSV, Neo4j).

**Skalowanie**: poniżej 400 materiałów — wszystkie pary; powyżej — blocking: indeks odwrócony po
wskaźnikach (z pominięciem hubów) + kNN po embeddingach tekstu i CLIP (`candidate_pairs`).

## 5. Grupowanie (`ftf/cluster.py`)

* **L0 – duplikaty**: union-find po krawędziach `duplicate` (deduplikacja zgłoszeń „wysłanych 47 razy”).
* **L1 – kampanie**: (a) *rdzenie* = spójne składowe po dowodach operatorskich (tier S ≥ 0.6);
  (b) aglomeracja rdzeni **średnim wiązaniem** liczonym tylko po parach porównywalnych (odporność
  na niekompletne dane, brak „łańcuchowania” single-linkage), plus scalenie przy pojedynczym
  bardzo silnym dowodzie (p ≥ 0.85).
* **L2 – rodziny / playbooki**: scalanie kampanii wyłącznie po narracji, koncepcji, wizualiach i
  osobach — „ten sam przepis na oszustwo, być może inny operator”. Raportowane osobno, by nie
  przypisywać wspólnego operatora bez dowodów infrastrukturalnych.
* **Baseline**: HDBSCAN na macierzy `1 − p` (ablation, pokazywany w UI).
* **Profil kampanii**: wspólne ślady posortowane wg pokrycia × wagi, domeny, osoby, produkty,
  typy, okres aktywności, rodziny dowodów wewnątrz kampanii.

## 6. Nowy materiał — przypisanie otwarte (open-set) (`cluster.assign`)
Cechy → porównanie z całym zbiorem → wynik kampanii = średnia z 2 najlepszych porównywalnych `p`
(lub pojedynczy dowód ≥ 0.85) →
`duplicate` · `known_campaign` (≥ 0.55) · `merge_proposal` (dwie kampanie ≥ 0.55) ·
`candidate_review` (0.30–0.55) · **`new_campaign`** (< 0.30). Wynik zawiera listę najbardziej
podobnych incydentów z uzasadnieniem.

## 7. Reprezentacja powiązań (`ftf/graph.py`)
NetworkX → interaktywny graf pyvis w UI (krawędzie z uzasadnieniem w tooltipie) oraz eksport do
**Neo4j** (Cypher lub bezpośrednio przez `NEO4J_URI`). Schemat: `Material`, `Campaign`, `Family`,
`Domain`, `Indicator`, `Person`, `Product`; relacje `LINKED{p, relation, explanation, families}`,
`IN_CAMPAIGN`, `IN_FAMILY`, `USES_DOMAIN`, `HAS_INDICATOR`, `DEPICTS{source}`, `PROMOTES`.

## 8. Ewaluacja (`tools/evaluate.py`, `ftf.cli eval`)
Brak etykiet kampanii w zbiorze przykładowym → protokół zgodny z planem testów organizatora:
1. **Leave-one-out**: każdy materiał usuwamy z bazy i przypisujemy ponownie → czy wraca do swojej
   kampanii / czy singleton jest rozpoznany jako nowy wzorzec.
2. **Syntetyczne warianty** („nowe odsłony znanych kampanii”): tylko kreacja bez strony, tylko
   strona bez kreacji, zrzut przycięty i przekompresowany, podmieniona domena, tekst z zamienionym
   nazwiskiem → oczekiwane przypisanie do kampanii źródłowej.
3. **Materiały niepowiązane** (inne kampanie, strony neutralne) → oczekiwane `new_campaign`.
4. Gdy dostępne są etykiety (`labels.csv`): pairwise P/R/F1, B-cubed, ARI vs baseline HDBSCAN.

## 9. Ograniczenia i dalszy rozwój
* Cloaking: część stron pokazuje treść tylko polskim IP mobilnym z pełnym URL reklamy — zapisujemy
  to, co widział crawler, i profil, który to zobaczył.
* Wagi są priorytetami eksperckimi — z etykietami (lub słabą superwizją: pary dzielące rzadki
  piksel jako pozytywy) można je dopasować regresją logistyczną z zachowaniem interpretowalności.
* Detektory deepfake/AI-text nie są używane jako werdykt (niska skuteczność „w dzikiej naturze”
  — research/03); obecność rozpoznanej twarzy + narracja oszustwa + niezwiązana domena jest
  pewniejszym sygnałem podszycia.
* Licencje: wagi InsightFace — tylko do badań niekomercyjnych; pozostałe modele MIT/Apache-2.0.
