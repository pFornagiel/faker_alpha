# 🕵️ FakeTrace — Follow the Fake

**HackNation 2026 · wyzwanie NASK „Kolekcjoner Fejków / Follow the Fake”.**
Narzędzie, które z pojedynczych podejrzanych reklam (posty sponsorowane, filmy, strony docelowe)
wyciąga wspólne ślady — tekstowe, wizualne, osobowe, infrastrukturalne — i łączy je w **kampanie**,
pokazując **uzasadnienie każdego powiązania**. Nowy materiał jest przypisywany do znanej kampanii albo
oznaczany jako **nowy wzorzec** (open-set).

* Metodyka (skrót PL): [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md)
* Przebieg pipeline'u krok po kroku i audyt decyzji: [`docs/PIPELINE_WALKTHROUGH.md`](docs/PIPELINE_WALKTHROUGH.md)
* Metodyka pobierania web, cloakingu i OSINT: [`docs/WEB_FETCHING_METHODOLOGY.md`](docs/WEB_FETCHING_METHODOLOGY.md)
* Metodyka cech, modeli ML, podobieństwa i klastrowania: [`docs/FEATURES_AND_ML_METHODOLOGY.md`](docs/FEATURES_AND_ML_METHODOLOGY.md)
* Research (źródła danych, modele, prior art): [`research/`](research/)
* Wyniki na zbiorze przykładowym: [`docs/RESULTS.md`](docs/RESULTS.md)
* Rozwiązanie zagadki CTF ze strony z zajawką: [`docs/CTF_SOLUTION.md`](docs/CTF_SOLUTION.md)

```
URL / zrzut ekranu / wideo / HTML / HAR / ZIP / nazwa produktu / biblioteka reklam
        │
        ▼  ingest (ftf/ingest.py, ftf/capture.py, ftf/sources.py)
  identyfikatory (domeny, piksele/ID śledzące, kontakty, pliki kitu, produkt, ID reklamy)
  widoki treści: text (MinHash strony) · ocr (MinHash tekstu kreacji) · semantic (e5) · html (szablon DOM) · images (pHash)
  opis: osoby (ArcFace + baza), typ oszustwa, słowa kluczowe, metadane domen
        │
        ▼  must-link po wspólnym identyfikatorze + odległość Gowera po widokach (ftf/similarity.py)
  duplikaty · kampanie i rodziny = dwa cięcia jednego dendrogramu (średnie wiązanie) (ftf/cluster.py)
  nowy materiał: wspólny identyfikator, inaczej najbliższy znany materiał (1-NN, Cover & Hart 1967) z progiem odrzucenia
        │
        ▼  panel analityka (React + shadcn/ui, FastAPI) · Neo4j · CSV/JSON · scheduler bibliotek reklam
```

## Szybki start (lokalnie, CPU)

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python tools/download_models.py            # ~310 MB modeli ONNX (e5, SCRFD+ArcFace) + ~30 MB OCR
.venv/bin/python tools/build_face_gallery.py         # baza referencyjna twarzy (Wikimedia Commons)
# zbiór organizatora (nie jest dystrybuowany w repo) -> data/organizer/dane/<case>/...
.venv/bin/python -m ftf.cli ingest data/organizer/dane   # ekstrakcja cech + kampanie
(cd web && npm ci && npm run build)                     # panel analityka (jednorazowo; Node ≥ 20)
.venv/bin/python -m ftf.cli serve                       # http://localhost:8765
```

Tryb deweloperski UI: `uvicorn ftf.api:app --reload --port 8765` + `cd web && npm run dev` (Vite, proxy `/api` → 8765).

### Panel analityka — co gdzie jest
| Strona | Do czego służy |
|---|---|
| **Kampanie** `/` | kluczowe liczby, karty kampanii z najmocniejszymi wspólnymi śladami, rozkład odległości par, co łączy pary, pojedyncze materiały |
| **Kampania** `/campaigns/:id` | materiały, macierz „który ślad łączy które materiały”, profil podobieństwa w 5 widokach treści, łańcuch najsilniejszych par, najbliższe materiały spoza kampanii |
| **Przestrzeń cech** `/space` | materiały na płaszczyźnie (MDS / t-SNE z odległości treści `d`), kolor wg metody grupowania: FakeTrace, sama treść, pojedyncze / pełne wiązanie, HDBSCAN, Louvain; tabela silhouette i ARI (vs FakeTrace i vs `data/labels_dane.csv`), dendrogram UPGMA, które cechy odróżniają kampanie |
| **Graf** `/graph` | sieć: kampanie jako ramki, materiały jako kółka; klik pokazuje dowody pary |
| **Macierz** `/matrix` | mapa cieplna bliskości `p` uporządkowana wg kampanii; klik otwiera porównanie pary |
| **Materiały** `/materials`, `/materials/:id` | lista z jednym polem wyszukiwania; strona materiału: podgląd, najbliższe materiały, identyfikatory z `df`, 5 widoków treści z wyjaśnieniem, opis (nie łączy) |
| **Para** `/pair/:a/:b` · **Ślad** `/trace` | relacja, wspólne identyfikatory, podobieństwo w każdym widoku i obliczenie `d`; wszystkie materiały z daną wartością |
| **Słowniczek** `/glossary` | pojęcia, identyfikatory, widoki, miary, metody grupowania i rzuty |
| **Analizuj materiał** `/analyse` | URL / plik / tekst → decyzja open-set z dowodami (opcjonalnie bez zapisu w bazie) |

Skaner źródeł (CERT Polska, biblioteki reklam) działa tylko z wiersza poleceń: `python -m ftf.scheduler --once [--analyse] [--watch]`
albo cyklicznie `--every N`. Import i eksport danych: `python -m ftf.cli ingest <folder>` / `python -m ftf.cli export`.

Wyszukiwarka w nagłówku (`/` lub `Ctrl+K`) znajduje domeny, identyfikatory, osoby, produkty i kampanie.
Poprzedni demonstrator Streamlit (`app.py`) pozostaje w repo jako wersja historyczna.

Opcjonalnie render stron w headless Chromium: `uv pip install playwright && .venv/bin/playwright install chromium`.

### Docker

```bash
docker compose up --build                      # UI na :8765 (modele pobierane przy budowie obrazu)
docker compose --profile neo4j up --build      # + Neo4j na :7474 (neo4j/fakefakefake)
```
Dane wejściowe montowane są z `./data` (zbiór organizatora w `./data/organizer/dane`).

## CLI

```bash
python -m ftf.cli ingest <folder_zbioru> [--no-llm]   # przetwórz przypadki (folder = incydent)
python -m ftf.cli add <plik|folder|URL|"tekst">        # nowy materiał -> decyzja + najbardziej podobne
python -m ftf.cli campaigns                            # kampanie, wspólne ślady, duplikaty, rodziny
python -m ftf.cli links --min 0.1                      # pary z uzasadnieniem (p = 1 − D; domyślnie 0.1)
python -m ftf.cli export                               # data/exports: graph.html, graph.cypher, campaigns.json, links.csv
python -m ftf.cli eval labels.csv                      # P/R/F1, B-cubed, ARI (gdy są etykiety)
python tools/evaluate.py --labels data/labels_dane.csv --no-llm   # leave-one-out + 5 wariantów syntetycznych + metryki
python -m ftf.scheduler --once [--analyse]             # skan bibliotek reklam / listy CERT
python -m ftf.scheduler --once --watch                 # + obserwacja kampanii: szukanie nowych materiałów po ich domenach / ID reklamodawców / produktach
```

## Większy zbiór badawczy (CERT Polska + urlscan.io)

Zbiór organizatora to kilkanaście przypadków — za mało, by sprawdzić, które ślady naprawdę łączą kampanie, a które
tylko tak wyglądają. `tools/harvest_urlscan.py` buduje publiczny korpus tła: bierze domeny z listy ostrzeżeń CERT Polska
i pobiera ich **historyczne** skany z urlscan.io (zrzut ekranu, DOM, lista żądań, IP / ASN / TLS). Stron oszustów nie
odwiedzamy sami. Każda domena trafia do folderu w tym samym układzie co przypadki organizatora, więc czyta go zwykły potok.

```bash
# 1. klucz: darmowe konto urlscan.io -> plik .env w katalogu repo (jest w .gitignore)
echo 'URLSCAN_API_KEY=...' > .env

# 2. pobranie: co 10. domena z listy CERT (rozrzut po ~6 miesiącach), do 2000 przypadków -> data/harvest/urlscan/<domena>/
python tools/harvest_urlscan.py --limit 2000 --stride 10 --max-domains 12000

# 3. ekstrakcja cech równolegle, do osobnej bazy (demo w data/store/ftf.sqlite zostaje nietknięte)
FTF_STORE=data/store/ftf_harvest.sqlite python tools/ingest_parallel.py data/harvest/urlscan \
    --source urlscan --workers 8 --threads 2 --require page.html

# 4. badanie: które cechy łączą strony + jak reguła must-link zachowuje się w tej skali
FTF_STORE=data/store/ftf_harvest.sqlite python tools/research_corpus.py data/harvest/urlscan \
    --store --pipeline-sample 400 --out data/harvest/research.json

# 5. panel na tym korpusie (na serwerze), a z laptopa tunel: ssh -N -L 8790:127.0.0.1:8790 <serwer>
FTF_STORE=data/store/ftf_harvest.sqlite python -m ftf.cli serve --port 8790
```

Uwagi praktyczne:

- **Limity urlscan.io** (darmowy klucz, stan z listopada 2026): 1000 wyszukiwań i 10 000 pobrań wyników dziennie; przebieg
  na 2000 przypadków zużywa ok. 280 wyszukiwań i trwa ok. 45 min. Bez klucza dostępny jest tylko zrzut ekranu i metadane
  hostingu (100 wyszukiwań na godzinę); późniejsze uruchomienie z kluczem uzupełnia takie przypadki.
- **Wznawianie i kolejne porcje:** skrypt pomija gotowe przypadki. Inny wycinek listy: `--skip 5 --stride 10`.
  Domeny podszywające się pod banki, kurierów i serwisy ogłoszeniowe są domyślnie pomijane (`--include-phishing`).
- **Puste strony:** ok. 25 % skanów ma pusty DOM (strona martwa albo cloaking wobec skanera). `--require page.html`
  pomija je przy ekstrakcji cech.
- **Wspólny serwer:** `ingest_parallel.py` ogranicza wątki każdego procesu i przypina całość do `workers × threads` rdzeni.
  Bez tego onnxruntime i OCR startują po jednym wątku na rdzeń w każdym procesie.
- **Panel przy większej liczbie materiałów:** porównanie par jest kwadratowe (ok. 10 s dla 250 materiałów, szacunkowo 6 min dla
  1500). Do przeglądania wygodniej wyciąć próbkę kilkuset materiałów do osobnej bazy.
- **Dane nie trafiają do repo:** `data/harvest/` jest w `.gitignore`; treści skanów urlscan.io nie redystrybuujemy.

### Co pokazał korpus (1503 strony z pełnym skanem, listopad 2026)

- **Kity zmieniają skórkę na każdej domenie.** Jedna operacja to 107 domen na 3 dedykowanych serwerach, każda z inną
  marką i tytułem w innym języku; tylko 8 % par wygląda podobnie. Stały jest szkielet kitu: hashe własnych skryptów,
  szablony ścieżek, zmienne globalne JS, nazwy ciasteczek. Odcisk złożony z tych cech grupuje 80 % stron w 74 rodziny.
- **Sieć widoczna tylko po szkielecie:** 224 domeny `.store` o losowych 10-literowych nazwach zwracają skanerowi
  „Page not found”, a mają ten sam kod sklepu i to samo ciasteczko śledzące.
- **Czas wystawienia certyfikatu TLS** w tej samej minucie: 91 % takich par należy do jednej rodziny kitu (średnio 5 %).
  Wpis na listę CERT w odstępie do godziny: 43–55 %.
- **Słabe sygnały osobno:** data rejestracji domeny, podsieć /24, ASN.
- **Fałszywe must-linki.** Przed poprawką publiczne usługi (`flagcdn.com`, `ipapi.co`), endpointy platform
  (`POST /cdn-cgi/rum` Cloudflare) i wspólne sufiksy hostingu (`on.aws`, `weebly.com`) łączyły niezwiązane strony
  i przez przechodniość sklejały połowę próby w jedną kampanię. Po poprawce (`ftf/web.py`: `SHARED_HOSTING_SUFFIXES`,
  `is_platform_endpoint`, rozszerzone `GENERIC_DOMAINS`) na tej samej próbie 400 stron:

  | | największa kampania | pary w kampaniach ze wspólnym odciskiem kitu | odzyskane silne pary kitu |
  |---|---|---|---|
  | przed | 200 z 400 | 19 % | 88 % |
  | po | 69 z 400 | 85 % | 79 % |
  | same widoki treści, bez identyfikatorów | 69 z 400 | 83 % | 69 % |

Korpus nie ma etykiet, więc to zgodność z niezależnymi sygnałami (szkielet kitu, szablon tytułu, dedykowany IP),
a nie precyzja względem prawdy. Na materiałach organizatora poprawka zmienia jedno: przypadek teaserowy `p10`
(inny produkt, inna usługa AWS) przestaje być doklejany do kampanii inwestycyjnej przez wspólny sufiks `on.aws`.

## LLM (augmentacja cech)
`FTF_LLM=auto` (domyślnie): **Claude Code CLI** w trybie headless (`claude -p --model haiku
--json-schema …`, korzysta z subskrypcji Claude, bez klucza API) → **Gemini** (`GEMINI_API_KEY`) →
**reguły** (gazetteer + leksykony, zawsze dostępne, deterministyczne). Wyniki cache’owane w
`data/cache/llm/`. `FTF_LLM=none` wyłącza LLM.

## Meta Ad Library — jak zdobyć token (dla schedulera)
Bez tokenu: kreacje po ID reklamy pobieramy przez `yt-dlp` (`https://www.facebook.com/ads/library/?id=<ID>`,
ekstraktor `facebook:ads` — tak pozyskano przypadek 5 zbioru organizatora).
Z tokenem scheduler przeszukuje **wszystkie reklamy emitowane w UE (także niepolityczne)** po słowach kluczowych:
1. Konto Facebook → **potwierdzenie tożsamości** na <https://www.facebook.com/ID> (dowód osobisty; trwa od kilku godzin do kilku dni).
2. <https://developers.facebook.com/> → *My Apps* → *Create App* (typ „Business”/„Other”).
3. Zaakceptuj warunki Ad Library API: <https://www.facebook.com/ads/library/api> → „Get started”.
4. *Graph API Explorer* → wybierz aplikację → *Generate Access Token* (user token) → zamień na
   long-lived (60 dni): `GET /oauth/access_token?grant_type=fb_exchange_token&client_id=…&client_secret=…&fb_exchange_token=…`.
5. `export META_ACCESS_TOKEN=...` (lub w `.env`) — `ftf/sources.py:meta_api_search` użyje
   `GET https://graph.facebook.com/v27.0/ads_archive?ad_reached_countries=['PL']&search_terms=…`.

## Źródła danych i ich licencje / ograniczenia
| Źródło | Dostęp | Uwagi |
|---|---|---|
| Lista ostrzeżeń CERT Polska `hole.cert.pl` | publiczne, bez klucza | dowolne użycie, bez gwarancji |
| Microsoft Ad Library API | publiczne, bez klucza | reklamy EOG |
| Google Ads Transparency Center | publiczne (wewn. RPC) | brak wyszukiwania pełnotekstowego |
| Meta Ad Library API | token (wyżej) | automatyczny scraping UI jest sprzeczny z ToS Meta — używamy API/yt-dlp per ID |
| urlscan.io — historyczne skany domen z listy CERT (`tools/harvest_urlscan.py`) | klucz API (darmowe konto) | limity dzienne; tylko korpus badawczy, treści skanów nie są w repo (`data/harvest/` w `.gitignore`) |
| Wikimedia Commons (baza twarzy) | publiczne | licencje CC/PD zapisane w `data/reference_faces/*/sources.json` |
| Zbiór organizatora | tylko na potrzeby wyzwania | **nie jest publikowany w repo** (`.gitignore`) |

## Modele i biblioteki (licencje)
| Komponent | Licencja |
|---|---|
| intfloat/multilingual-e5-small (ONNX int8, Xenova) | MIT |
| InsightFace buffalo_l (SCRFD det_10g + ArcFace w600k_r50) | kod MIT, **wagi: tylko badania niekomercyjne** |
| RapidOCR / PP-OCRv6 | Apache-2.0 |
| onnxruntime, OpenCV, SciPy, scikit-learn, datasketch, networkx, pyvis, streamlit, imagehash, yake, tldextract, bs4 | MIT/BSD/Apache |
| FastAPI, React, Tailwind CSS, shadcn/ui, Radix UI, TanStack Query, Cytoscape.js (+fcose), lucide | MIT |
| Claude (Anthropic) przez Claude Code CLI / Gemini API | usługi zewnętrzne, opcjonalne |

## Struktura repo
```
web/                   panel analityka: React + TypeScript + Tailwind + shadcn/ui, Cytoscape.js (graf)
ftf/api.py             FastAPI: JSON dla panelu (kampanie, pary z uzasadnieniem, graf, macierz, analiza, skaner)
ftf/labels.py          polskie etykiety enumów, grup identyfikatorów, widoków, relacji i decyzji
app.py                 poprzedni demonstrator Streamlit (historyczny)
ftf/ingest.py          materiały i loadery (folder przypadku, upload, URL, tekst)
ftf/capture.py         przechwycenie URL: 3 profile klienta, cloaking, Playwright
ftf/web.py             URL/HTML/HAR/MHTML → wskaźniki (piksele, TDS, endpointy, DOM…)
ftf/vision.py          pHash, OCR, QR, klatki wideo, wycięcie kreacji
ftf/faces.py           SCRFD + ArcFace + baza referencyjna
ftf/text.py            MinHash, maskowanie osób, e5, YAKE, kwoty
ftf/gazetteer.py       osoby / marki / media / leksykony (PL)
ftf/llm.py             atrybuty LLM: typ oszustwa, osoby, marki, medium, produkt (claude CLI / Gemini / reguły)
ftf/similarity.py      identyfikatory (must-link, MAX_DF), widoki treści, odległość Gowera, Link + uzasadnienie
ftf/cluster.py         średnie wiązanie: duplikaty, kampanie, rodziny; HDBSCAN; przypisanie open-set (1-NN)
ftf/graph.py           NetworkX, pyvis, Neo4j/Cypher
ftf/sources.py         CERT PL, MS Ad Library, Google ATC, Meta API/yt-dlp, LinkedIn
ftf/scheduler.py       APScheduler: skan → triage → analiza
tools/                 pobieranie modeli, baza twarzy, ewaluacja, rozwiązanie CTF
tools/harvest_urlscan.py, ingest_parallel.py, research_corpus.py   korpus badawczy: pobranie, równoległa ekstrakcja, badanie cech
research/              raporty z researchu (źródła, infrastruktura, modele, prior art)
```
