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
  web+infra (trackery, TDS, endpointy, DOM, IP) · wizualne (pHash, CLIP, DINOv2, OCR) · twarze (ArcFace + baza)
  tekst (MinHash, maskowanie osób, e5) · LLM (typ oszustwa, szablon narracji, produkt, frazy)
        │
        ▼  podobieństwo ważone rzadkością + rodziny dowodów + zabezpieczenia (ftf/similarity.py)
  duplikaty → rdzenie operatorskie → kampanie (średnie wiązanie) → rodziny/playbooki (ftf/cluster.py)
        │
        ▼  panel analityka (React + shadcn/ui, FastAPI) · Neo4j · CSV/JSON · scheduler bibliotek reklam
```

## Szybki start (lokalnie, CPU)

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python tools/download_models.py            # ~460 MB modeli ONNX (e5, CLIP, DINOv2, SCRFD+ArcFace, OCR)
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
| **Przegląd kampanii** `/` | kampanie wielomateriałowe z najmocniejszymi wspólnymi śladami, pojedyncze materiały, przykłady „od czego zacząć” |
| **Kampania** `/campaigns/:id` | macierz „który ślad łączy które materiały”, pary z siłą p, warianty przekazu, najbliższe materiały spoza kampanii, rodzina (playbook) |
| **Materiał** `/materials/:id` | podsumowanie, najbardziej podobne materiały, ślady techniczne, infrastruktura domen, treść/atrybuty LLM, kreacje z OCR i twarzami |
| **Powiązanie** `/pair/:a/:b` | werdykt, siła rodzin dowodów, obliczenie p krok po kroku, pełna lista dowodów (z pominiętymi hubami) |
| **Ślad** `/trace?type=&value=` | wszystkie materiały z daną wartością (piksel, domena, osoba…), jej rzadkość i waga |
| **Powiązania / Graf / Macierz** | te same pary jako tabela, sieć (kampanie jako ramki) i mapa cieplna uporządkowana wg kampanii |
| **Analizuj nowy materiał** | URL / plik / tekst → decyzja open-set z dowodami (opcjonalnie bez zapisu w bazie) |
| **Skaner źródeł** · **Dane i eksport** · **Metodyka** | CERT PL + biblioteki reklam; import zbioru, przeliczenie, eksport JSON/CSV/Cypher; metoda z bieżącymi wagami i przykładem |

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
python -m ftf.cli links --min 0.3                      # krawędzie z uzasadnieniem
python -m ftf.cli export                               # data/exports: graph.html, graph.cypher, campaigns.json, links.csv
python -m ftf.cli eval labels.csv                      # P/R/F1, B-cubed, ARI (gdy są etykiety)
python tools/evaluate.py                               # leave-one-out + syntetyczne warianty
python -m ftf.scheduler --once [--analyse]             # skan bibliotek reklam / listy CERT
```

## LLM (augmentacja cech)
`FTF_LLM=auto` (domyślnie): **Claude Code CLI** w trybie headless (`claude -p --model haiku
--json-schema …`, korzysta z subskrypcji Claude, bez klucza API) → **Gemini** (`GEMINI_API_KEY`) →
**reguły** (gazetteer + leksykony, zawsze dostępne, deterministyczne). Wyniki cache’owane w
`data/cache/llm/`. `FTF_LLM=none` wyłącza LLM.

## Opcjonalnie: EmbeddingGemma-2 (drugi sygnał narracji)
`FTF_GEMMA=1` dodaje embedding `google/embeddinggemma-2` (ONNX q4, 175 MB, Apache-2.0, `models/embeddinggemma2/`)
jako drugi sygnał narracji (max z e5, bez podwójnego liczenia). Na polskim STS: Spearman 0.772 vs 0.695
(SICK-R-PL) i 0.926 vs 0.895 (CDSC-R) względem e5-small, ale ~4–5× wolniej na CPU — szczegóły:
`research/05_embeddinggemma2_eval.md`.

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
| Wikimedia Commons (baza twarzy) | publiczne | licencje CC/PD zapisane w `data/reference_faces/*/sources.json` |
| Zbiór organizatora | tylko na potrzeby wyzwania | **nie jest publikowany w repo** (`.gitignore`) |

## Modele i biblioteki (licencje)
| Komponent | Licencja |
|---|---|
| intfloat/multilingual-e5-small (ONNX int8, Xenova) | MIT |
| openai/clip-vit-base-patch32 (ONNX int8, Xenova) | MIT |
| facebook/dinov2-small (ONNX, Xenova) | Apache-2.0 |
| InsightFace buffalo_l (SCRFD det_10g + ArcFace w600k_r50) | kod MIT, **wagi: tylko badania niekomercyjne** |
| RapidOCR / PP-OCRv6 | Apache-2.0 |
| onnxruntime, OpenCV, scikit-learn, datasketch, networkx, pyvis, streamlit, imagehash, yake, tldextract, bs4 | MIT/BSD/Apache |
| FastAPI, React, Tailwind CSS, shadcn/ui, Radix UI, TanStack Query, Cytoscape.js (+fcose), lucide | MIT |
| Claude (Anthropic) przez Claude Code CLI / Gemini API | usługi zewnętrzne, opcjonalne |

## Struktura repo
```
web/                   panel analityka: React + TypeScript + Tailwind + shadcn/ui, Cytoscape.js (graf)
ftf/api.py             FastAPI: JSON dla panelu (kampanie, pary z uzasadnieniem, graf, macierz, analiza, skaner)
ftf/labels.py          polskie etykiety enumów, rodzin dowodów, relacji i decyzji
app.py                 poprzedni demonstrator Streamlit (historyczny)
ftf/ingest.py          materiały i loadery (folder przypadku, upload, URL, tekst)
ftf/capture.py         przechwycenie URL: 3 profile klienta, cloaking, Playwright
ftf/web.py             URL/HTML/HAR/MHTML → wskaźniki (piksele, TDS, endpointy, DOM…)
ftf/vision.py          pHash, CLIP, DINOv2, OCR, QR, klatki wideo, layout
ftf/faces.py           SCRFD + ArcFace + baza referencyjna
ftf/text.py            MinHash, maskowanie osób, e5, YAKE, kwoty
ftf/gazetteer.py       osoby / marki / media / leksykony (PL)
ftf/llm.py             atrybuty LLM (claude CLI / Gemini / reguły)
ftf/similarity.py      dowody, rzadkość, rodziny, p, uzasadnienia
ftf/cluster.py         duplikaty, kampanie, rodziny, HDBSCAN, przypisanie open-set
ftf/graph.py           NetworkX, pyvis, Neo4j/Cypher
ftf/sources.py         CERT PL, MS Ad Library, Google ATC, Meta API/yt-dlp, LinkedIn
ftf/scheduler.py       APScheduler: skan → triage → analiza
tools/                 pobieranie modeli, baza twarzy, ewaluacja, rozwiązanie CTF
research/              raporty z researchu (źródła, infrastruktura, modele, prior art)
```
