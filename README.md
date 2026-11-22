# 🕵️ FakerAlpha — Follow the Fake

**HackNation 2026 · wyzwanie NASK „Kolekcjoner Fejków / Follow the Fake”.**
Narzędzie, które z pojedynczych podejrzanych reklam (posty sponsorowane, filmy, strony docelowe)
wyciąga wspólne ślady — tekstowe, wizualne, osobowe, infrastrukturalne — i łączy je w **kampanie**,
pokazując **uzasadnienie każdego powiązania**. Nowy materiał jest przypisywany do znanej kampanii albo
oznaczany jako **nowy wzorzec** (open-set).

* Uruchomienie w Dockerze: [Uruchomienie](#uruchomienie) · własne dane: [Własne dane](#własne-dane) · bez Dockera: [Bez Dockera](#bez-dockera)
* Funkcje i przebieg pozyskiwania danych w skrócie: [`FUNKCJE.md`](FUNKCJE.md)
* Metodyka (skrót PL): [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md)
* Przebieg pipeline'u krok po kroku i audyt decyzji: [`docs/PIPELINE_WALKTHROUGH.md`](docs/PIPELINE_WALKTHROUGH.md)
* Metodyka pobierania web, cloakingu i OSINT: [`docs/WEB_FETCHING_METHODOLOGY.md`](docs/WEB_FETCHING_METHODOLOGY.md)
* Metodyka cech, modeli ML, podobieństwa i klastrowania: [`docs/FEATURES_AND_ML_METHODOLOGY.md`](docs/FEATURES_AND_ML_METHODOLOGY.md)
* Research (źródła danych, modele, prior art): [`research/`](research/)
* Wyniki na zbiorze przykładowym: [`docs/RESULTS.md`](docs/RESULTS.md)

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

## Uruchomienie

Zalecana droga to Docker. Potrzebny jest tylko Docker z poleceniem `docker compose`: Docker Desktop na Windows
i macOS albo Docker Engine z wtyczką Compose na Linuksie. Python, Node, ffmpeg i modele są w obrazie.
Instalację bez Dockera opisuje rozdział [Bez Dockera](#bez-dockera).

### Instalacja i start

```bash
git clone <adres repozytorium> faker_alpha
cd faker_alpha
docker compose up --build -d
```

Pierwsza budowa obrazu trwa ok. 7 min. Pobiera ok. 1 GB bibliotek i ok. 340 MB modeli, a gotowy obraz zajmuje
ok. 4 GB. Kolejne starty trwają kilka sekund. Czas zmierzono na laptopie (8 wątków, szybkie łącze) bez pamięci
podręcznej Dockera.

Po starcie otwórz <http://localhost:8765>. Polecenie `docker compose ps` pokazuje stan `healthy`, gdy serwer odpowiada.

### Zbiór demonstracyjny

Na pustej bazie panel pokazuje przycisk **Wczytaj zbiór demonstracyjny**. Zbiór ma 8 zmyślonych przypadków.
Import trwa ok. 10 s i nie używa sieci. To samo z terminala:

```bash
docker compose exec app python -m ftf demo
```

### Własne dane

Kontener widzi tylko folder `./data` w katalogu repozytorium (w kontenerze `/app/data`). Zbiór trzeba najpierw
tam skopiować.

**Krok 1. Przygotuj folder.** Jeden podfolder to jeden przypadek, czyli jedna reklama albo jedna strona.
Do podfolderu włóż wszystko, co masz o tym przypadku. Nazwy plików są dowolne. Wystarczy jeden plik.

```text
moj_zbior/
├── przypadek-01/
│   ├── strona.html          zapisana strona (z folderem zasobów, jeśli przeglądarka go utworzyła)
│   ├── ruch.har             zapis ruchu sieciowego
│   └── zrzut.png            zrzut ekranu reklamy
├── przypadek-02/
│   └── reklama.mp4          wideo
└── przypadek-03/
    └── reklama.txt          tekst reklamy albo lista linków
```

| Rodzaj pliku | Rozszerzenia |
|---|---|
| zapisana strona | `.html`, `.htm`, `.mhtml` |
| zapis ruchu sieciowego | `.har` |
| zrzut ekranu, grafika reklamy | `.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`, `.bmp`, `.avif` |
| wideo | `.mp4`, `.mov`, `.webm`, `.mkv`, `.m4v`, `.avi` |
| tekst reklamy, linki | `.txt` |

**Krok 2. Skopiuj folder do `./data`.**

```bash
cp -r ~/moj_zbior data/
```

Na Windows wystarczy skopiować folder w Eksploratorze do `faker_alpha\data\`. Zbiór organizatora włóż do
`data/organizer/dane`. Tę ścieżkę panel podpowiada sam.

**Krok 3. Wczytaj zbiór.** Na stronie startowej panelu albo na stronie **Analizuj materiał** jest karta
**Wczytaj zbiór przypadków**. Wpisz `data/moj_zbior` i kliknij **Importuj zbiór**. Pasek postępu pokazuje kolejne
przypadki. Import trwa ok. 20 s na przypadek na CPU. To samo z terminala:

```bash
docker compose exec app python -m ftf ingest data/moj_zbior
```

**Krok 4. Zobacz wynik.** Strona **Kampanie** pokazuje, które przypadki trafiły do jednej kampanii. Po kliknięciu
kampanii albo pary materiałów widać ślady i podobieństwa, które je połączyły. To samo z terminala:

```bash
docker compose exec app python -m ftf campaigns                        # lista kampanii
docker compose exec app python -m ftf pair przypadek-01 przypadek-02   # dlaczego dwa materiały są (albo nie są) powiązane
docker compose exec app python -m ftf export                           # graf, kampanie i pary do ./data/exports
```

Dalsze możliwości:

1. **Zbiór testowy.** Skopiuj go do `./data` i wczytaj tak samo, z innego folderu. Nowe przypadki dołączają do
   znanych kampanii albo tworzą nowe. Przypadki, które już są w bazie, są pomijane.
2. **Jeden nowy materiał.** Strona **Analizuj materiał** przyjmuje adres URL, plik albo tekst. Plikiem może być
   zrzut, wideo, zapisana strona, HAR albo ZIP z folderem przypadku. Odpowiedzią jest decyzja z dowodami: duplikat,
   znana kampania, propozycja scalenia albo nowy wzorzec. Z terminala plik musi leżeć w `./data`:

   ```bash
   docker compose exec app python -m ftf add data/nowa_reklama.png --dry   # --dry: bez zapisu w bazie
   docker compose exec app python -m ftf add "https://przyklad.example/oferta"
   ```
3. **Ocena względem własnych etykiet.** Zapisz w `./data/etykiety.csv` wiersze `nazwa_przypadku,etykieta_kampanii`.
   Wynik to precyzja, czułość i F1 par, B-cubed oraz ARI.

   ```text
   przypadek-01,kampania-A
   przypadek-02,kampania-A
   przypadek-03,kampania-B
   ```

   ```bash
   docker compose exec app python -m ftf eval data/etykiety.csv
   ```
4. **Osobna baza dla testów.** `FTF_STORE=data/store/test.sqlite docker compose up -d` uruchamia panel na osobnej
   bazie. Importy z panelu i polecenia `docker compose exec` trafiają wtedy do niej. Powrót do głównej bazy daje
   `docker compose up -d`.

Uwagi:

* Nie przenoś folderu przypadku po imporcie. Identyfikator materiału zależy od ścieżki, więc przeniesiony przypadek
  zostałby wczytany drugi raz.
* Model językowy działa w kontenerze tylko z kluczem `GEMINI_API_KEY` w pliku `.env` obok `docker-compose.yml`.
  Bez klucza atrybuty opisowe powstają z reguł słownikowych. Przełącznik w karcie importu wyłącza model dla
  jednego importu, a w terminalu robi to opcja `--no-llm`.
* `FTF_LLM=none FTF_ENRICH=0 docker compose up -d` uruchamia panel bez usług zewnętrznych. Tekst przypadków nie
  trafia wtedy do modelu językowego, a domeny nie są sprawdzane w RDAP, DNS i crt.sh.

### Codzienna obsługa

| Czynność | Polecenie |
|---|---|
| start | `docker compose up -d` |
| zatrzymanie (dane zostają w `./data`) | `docker compose down` |
| stan | `docker compose ps` |
| logi serwera | `docker compose logs -f app` |
| aktualizacja po `git pull` | `docker compose up --build -d` |
| inny port | `FTF_PORT=8770 docker compose up -d`, panel pod <http://localhost:8770> |
| pusta baza | `docker compose down`, potem `docker compose run --rm app rm -r data/store` i `docker compose up -d` |
| pomoc CLI | `docker compose exec app python -m ftf --help` |

Warianty obrazu:

```bash
docker compose build --build-arg WITH_PLAYWRIGHT=0    # mniejszy obraz bez headless Chromium (render stron z URL)
docker compose --profile neo4j up --build -d          # dodatkowo Neo4j na :7474 (neo4j/fakefakefake)
docker compose --profile scheduler up -d              # dodatkowo cykliczny skaner źródeł
```

Na Linuksie kontener zapisuje pliki w `./data` jako root. Własność zmienia `sudo chown -R "$USER" data`.

### Bez Dockera

Linux, macOS albo WSL.

| Wymaganie | Do czego | Instalacja |
|---|---|---|
| [`uv`](https://docs.astral.sh/uv/) | środowisko Pythona (uv sam pobiera Pythona 3.12) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Node ≥ 20 z npm | jednorazowa budowa panelu | <https://nodejs.org/> albo menedżer pakietów systemu |
| `ffmpeg`, `ffprobe` | klatki z wideo | `sudo apt install ffmpeg` lub `brew install ffmpeg` |

Bez `uv` skrypt użyje Pythona 3.12 lub 3.13 z `PATH` (venv i pip, wolniej).
Bez `ffmpeg` wszystko działa, ale wideo jest analizowane bez klatek.

```bash
git clone <adres repozytorium> faker_alpha
cd faker_alpha
./setup.sh --demo                     # biblioteki, modele, panel i zbiór demonstracyjny, ok. 1,5 min
.venv/bin/python -m ftf serve         # panel: http://127.0.0.1:8765
```

Skrypt `setup.sh` można uruchamiać wielokrotnie. Gotowe kroki są pomijane. Opcje:

| Opcja | Znaczenie |
|---|---|
| `--demo` | wczytuje zbiór demonstracyjny |
| `--playwright` | instaluje headless Chromium do renderowania stron z URL (ok. 300 MB) |
| `--no-web` | pomija budowę panelu, zostaje samo CLI i Node nie jest potrzebny |

Polecenia z rozdziału [Własne dane](#własne-dane) działają tak samo. Zamiast `docker compose exec app python -m ftf`
wpisz `.venv/bin/python -m ftf`. Zbiór nie musi leżeć w `data/`. Ścieżka wpisana w panelu jest liczona względem
katalogu repozytorium. Osobną bazę wybiera `FTF_STORE=data/store/test.sqlite .venv/bin/python -m ftf serve`.

Te same kroki co `setup.sh --demo`, wykonane ręcznie:

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt   # ok. 30 s
.venv/bin/python tools/download_models.py     # ~310 MB modeli ONNX (e5, SCRFD + ArcFace) + ~30 MB OCR, ok. 15 s
(cd web && npm ci && npm run build)           # panel analityka, ok. 15 s
.venv/bin/python -m ftf demo                  # zbiór demonstracyjny, ok. 15 s
.venv/bin/python -m ftf serve                 # http://127.0.0.1:8765
```

Baza referencyjna twarzy działa od razu po instalacji, także w Dockerze. Plik `ftf/assets/face_gallery.npz` zawiera
średnie embeddingi ArcFace 29 osób, pod które oszuści podszywają się najczęściej. Są to same wektory, bez zdjęć.
Skrypt `tools/build_face_gallery.py` jest potrzebny tylko do dodania osób albo odtworzenia pliku ze zdjęć
Wikimedia Commons:

```bash
.venv/bin/python tools/build_face_gallery.py "Imię Nazwisko"   # pobiera zdjęcia do data/reference_faces/
.venv/bin/python tools/build_face_gallery.py --export          # zapisuje ftf/assets/face_gallery.* ze zdjęć na dysku
```

### Gdy coś nie działa

| Objaw | Co zrobić |
|---|---|
| `Bind for 0.0.0.0:8765 failed: port is already allocated` | Port jest zajęty. Uruchom `FTF_PORT=8770 docker compose up -d`. |
| Import w panelu zgłasza, że folder nie istnieje | W Dockerze zbiór musi leżeć w `./data`, a ścieżka w panelu zaczyna się od `data/`. Bez Dockera ścieżka jest liczona względem katalogu repozytorium. |
| Panel pokazuje komunikat o pustej bazie | Wczytaj zbiór przyciskiem na tej stronie albo poleceniem `demo`. |
| Panel nie odpowiada po starcie | Sprawdź `docker compose ps` i `docker compose logs app`. Serwer startuje kilka sekund. |
| Budowa obrazu przerwała się przy pobieraniu | Uruchom ponownie `docker compose up --build -d`. Gotowe warstwy są brane z pamięci podręcznej. |
| Brak uprawnień do plików w `./data` (Linux) | `sudo chown -R "$USER" data` |
| Bez Dockera: `nie można nasłuchiwać na 127.0.0.1:8765` | Port jest zajęty. Uruchom `.venv/bin/python -m ftf serve --port 8770`. |
| Bez Dockera: pod adresem panelu jest tylko API, bez strony | Panel nie jest zbudowany. Uruchom `./setup.sh` albo `cd web && npm ci && npm run build`. |
| Bez Dockera: pobieranie modeli zostało przerwane | Uruchom ponownie `tools/download_models.py`. Gotowe pliki są pomijane. |
| Bez Dockera: brak klatek z wideo | Zainstaluj `ffmpeg` i wczytaj zbiór ponownie z opcją `--force`. |

Tryb deweloperski UI: `uvicorn ftf.api:app --reload --port 8765` + `cd web && npm run dev` (Vite, proxy `/api` → 8765).

### Panel analityka — co gdzie jest
| Strona | Do czego służy |
|---|---|
| **Kampanie** `/` | kluczowe liczby, karty kampanii z najmocniejszymi wspólnymi śladami, rozkład odległości par, co łączy pary, pojedyncze materiały |
| **Kampania** `/campaigns/:id` | materiały, macierz „który ślad łączy które materiały”, profil podobieństwa w 7 widokach treści, łańcuch najsilniejszych par, najbliższe materiały spoza kampanii |
| **Przestrzeń cech** `/space` | materiały na płaszczyźnie (MDS / t-SNE z odległości treści `d`), kolor wg metody grupowania: FakerAlpha, sama treść, pojedyncze / pełne wiązanie, HDBSCAN, Louvain; tabela silhouette i ARI (vs FakerAlpha i vs `data/labels_dane.csv`), dendrogram UPGMA, które cechy odróżniają kampanie |
| **Graf** `/graph` | sieć: kampanie jako ramki, materiały jako kółka; klik pokazuje dowody pary |
| **Macierz** `/matrix` | mapa cieplna bliskości `p` uporządkowana wg kampanii; klik otwiera porównanie pary |
| **Materiały** `/materials`, `/materials/:id` | lista z jednym polem wyszukiwania; strona materiału: podgląd, najbliższe materiały, identyfikatory z `df`, 7 widoków treści z wyjaśnieniem, opis (nie łączy) |
| **Para** `/pair/:a/:b` · **Ślad** `/trace` | relacja, wspólne identyfikatory, podobieństwo w każdym widoku i obliczenie `d`; wszystkie materiały z daną wartością |
| **Słowniczek** `/glossary` | pojęcia, identyfikatory, widoki, miary, metody grupowania i rzuty |
| **Analizuj materiał** `/analyse` | URL / plik / tekst → decyzja open-set z dowodami (opcjonalnie bez zapisu w bazie) |

Skaner źródeł (CERT Polska, biblioteki reklam) działa tylko z wiersza poleceń: `python -m ftf.scheduler --once [--analyse] [--watch]`
albo cyklicznie `--every N`. Import zbioru opisuje rozdział [Własne dane](#własne-dane). Eksport: `python -m ftf export`.

Wyszukiwarka w nagłówku (`/` lub `Ctrl+K`) znajduje domeny, identyfikatory, osoby, produkty i kampanie.
Poprzedni demonstrator Streamlit (`app.py`) pozostaje w repo jako wersja historyczna. Jego zależności są w osobnym pliku:
`uv pip install --python .venv/bin/python -r requirements-legacy.txt && .venv/bin/streamlit run app.py`.

## CLI

Wszystko, co pokazuje panel, jest dostępne w terminalu: czytelne tabele, a z `--json` JSON o stałych kluczach.
Pełny opis z przykładowymi wynikami, kształtem JSON, kodami wyjścia i zmiennymi środowiskowymi: [docs/CLI.md](docs/CLI.md).
`python -m ftf` i `python -m ftf.cli` to to samo polecenie; dotychczasowe wywołania działają bez zmian.

```bash
python -m ftf --help                                 # przegląd poleceń; każde ma własne --help z przykładami
python -m ftf status                                 # która baza, ile materiałów i kampanii, konfiguracja

# co jest w bazie
python -m ftf campaigns [--min-size N]               # kampanie, najmocniejsze wspólne ślady, duplikaty, rodziny
python -m ftf campaign C1                            # jedna kampania: materiały, który ślad łączy które, najsilniejsze pary
python -m ftf materials [tekst] [--campaign C1]      # lista materiałów z filtrem
python -m ftf material <id|nazwa>                    # identyfikatory z df, widoki treści, najbliższe materiały, opis
python -m ftf search <tekst>                         # szukanie w materiałach, kampaniach i wartościach śladów

# dlaczego materiały są powiązane
python -m ftf links [--min 0.1] [--relation …]       # pary z uzasadnieniem (p = 1 − D; domyślnie p ≥ 0.1)
python -m ftf pair <A> <B>                           # jedna para: wspólne identyfikatory, podobieństwo w widokach, obliczenie d
python -m ftf trace <wartość> [--type fb_pixel]      # wszystkie materiały z daną domeną, pikselem, telefonem, osobą…
python -m ftf matrix [--campaign C1] [--distance]    # macierz bliskości

# jakość grupowania
python -m ftf metrics [--methods]                    # metody grupowania (silhouette, ARI), rozkład odległości, pokrycie cech
python -m ftf eval labels.csv                        # P/R/F1 par, B-cubed, ARI względem własnych etykiet
python tools/evaluate.py --labels data/labels_dane.csv --no-llm   # leave-one-out + 5 wariantów syntetycznych + metryki

# nowe dane (jedyne polecenia, które zapisują do bazy)
python -m ftf add <plik|folder|URL|"tekst"> [--dry] [--no-llm]    # nowy materiał -> decyzja open-set + dowody (--dry: bez zapisu)
python -m ftf ingest <folder_zbioru> [--no-llm] [--force]         # import zbioru (podfolder = przypadek)

# eksport, panel, słowniczek
python -m ftf export [--out katalog] [--only links.csv]           # graph.html, graph.cypher, campaigns.json, links.csv (domyślnie data/exports)
python -m ftf serve [--host 127.0.0.1] [--port 8765]              # panel WWW i API
python -m ftf glossary                                            # typy śladów, widoki treści, relacje, decyzje, progi

# skaner źródeł ma osobne polecenie
python -m ftf.scheduler --once [--analyse]           # skan bibliotek reklam / listy CERT
python -m ftf.scheduler --once --watch               # + obserwacja kampanii: szukanie nowych materiałów po ich domenach / ID reklamodawców / produktach
```

Bazę wskazuje opcja `--store ŚCIEŻKA` albo zmienna `FTF_STORE` (domyślnie `<FTF_ROOT>/data/store/ftf.sqlite`); polecenia
odczytu otwierają ją tylko do odczytu, a gdy pliku nie ma, mówią, jak go wskazać lub utworzyć. `FTF_LLM=none` i `--no-llm`
wyłączają model językowy. `add <URL>` pobiera stronę z tego komputera — obowiązuje uwaga o izolacji z sekcji poniżej.

## Większy zbiór badawczy (CERT Polska + urlscan.io)

> **Uwaga: pobieranie jest domyślnie wyłączone i nie należy go uruchamiać bez wyraźnej potrzeby.**
> `tools/harvest_urlscan.py` zapisuje na dysku kopie stron oszustów: wyrenderowany HTML razem ze skryptami napisanymi
> przez oszustów, zrzuty ekranu i listy żądań. Korpus pobrany w listopadzie 2026 został 22.11.2026 usunięty z laptopa
> i z serwera ze względów bezpieczeństwa. Zostały tylko dane pochodne: bazy cech (poza repo) i wyniki w
> `research/experiments/`. Skrypt odmawia działania bez flagi `--i-accept-scam-content-on-this-machine`.
> Jeśli korpus trzeba kiedyś odtworzyć: tylko w odizolowanym środowisku (maszyna wirtualna albo kontener bez dostępu
> do prywatnych i współdzielonych danych), bez otwierania plików `page.html` w przeglądarce, a foldery przypadków
> należy usunąć zaraz po ekstrakcji cech. Poniższe polecenia opisują, jak korpus powstał.

Zbiór organizatora to kilkanaście przypadków — za mało, by sprawdzić, które ślady naprawdę łączą kampanie, a które
tylko tak wyglądają. `tools/harvest_urlscan.py` buduje publiczny korpus tła: bierze domeny z listy ostrzeżeń CERT Polska
i pobiera ich **historyczne** skany z urlscan.io (zrzut ekranu, DOM, lista żądań, IP / ASN / TLS). Stron oszustów nie
odwiedzamy sami. Każda domena trafia do folderu w tym samym układzie co przypadki organizatora, więc czyta go zwykły potok.

```bash
# 1. klucz: darmowe konto urlscan.io -> plik .env w katalogu repo (jest w .gitignore)
echo 'URLSCAN_API_KEY=...' > .env

# 2. pobranie: co 10. domena z listy CERT (rozrzut po ~6 miesiącach), do 2000 przypadków -> data/harvest/urlscan/<domena>/
#    NIEBEZPIECZNE i domyślnie wyłączone (patrz uwaga wyżej); bez flagi skrypt kończy pracę, nic nie pobierając
python tools/harvest_urlscan.py --i-accept-scam-content-on-this-machine --limit 2000 --stride 10 --max-domains 12000

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
| urlscan.io — historyczne skany domen z listy CERT (`tools/harvest_urlscan.py`) | klucz API (darmowe konto) | **pobieranie domyślnie wyłączone** (kopie stron oszustów na dysku, patrz sekcja o zbiorze badawczym); limity dzienne; treści skanów nie są w repo (`data/harvest/` w `.gitignore`) |
| Wikimedia Commons (baza twarzy) | publiczne | licencje CC/PD zdjęć zapisane w `data/reference_faces/*/sources.json`; w repo są tylko wektory cech (`ftf/assets/face_gallery.npz`), bez zdjęć |
| Zbiór organizatora | tylko na potrzeby wyzwania | **nie jest publikowany w repo** (`.gitignore`) |

## Modele i biblioteki (licencje)
Licencje bibliotek odczytane z metadanych zainstalowanych pakietów (`requirements.txt`, `requirements-legacy.txt`, `web/package.json`).

**Modele**

| Komponent | Licencja |
|---|---|
| intfloat/multilingual-e5-small (ONNX int8, Xenova) | MIT |
| InsightFace buffalo_l (SCRFD det_10g + ArcFace w600k_r50) | kod MIT, **wagi: tylko badania niekomercyjne** |
| RapidOCR / PP-OCRv6 | Apache-2.0 |

**Biblioteki Pythona (`requirements.txt`)**

| Komponent | Licencja |
|---|---|
| onnxruntime, datasketch, beautifulsoup4, APScheduler, FastAPI | MIT |
| Pillow | MIT-CMU |
| NumPy, SciPy, scikit-learn, networkx, lxml, tldextract, uvicorn | BSD-3-Clause |
| imagehash, pyvis | BSD |
| opencv-python-headless, tokenizers, rapidocr, requests, python-multipart, neo4j (sterownik) | Apache-2.0 |
| dnspython | ISC |
| yt-dlp | Unlicense |
| tylko historyczny `app.py` (`requirements-legacy.txt`): streamlit, pandas | Apache-2.0, BSD-3-Clause |

**Panel (`web/package.json`)**

| Komponent | Licencja |
|---|---|
| React, React Router, Tailwind CSS, shadcn/ui, Radix UI, TanStack Query, Cytoscape.js (+fcose), cmdk, sonner, next-themes, tw-animate-css, Vite | MIT |
| lucide-react | ISC |
| class-variance-authority, TypeScript | Apache-2.0 |
| krój Geist (`@fontsource-variable/geist`) | OFL-1.1 |

**Narzędzia systemowe i usługi**

| Komponent | Licencja / ograniczenia |
|---|---|
| ffmpeg / ffprobe (klatki z wideo) | LGPL lub GPL, zależnie od kompilacji |
| Playwright + Chromium (opcjonalnie, render stron) | Playwright: Apache-2.0; Chromium: BSD-3-Clause i inne |
| Neo4j Community 5 (opcjonalnie, profil `neo4j` w `docker-compose.yml`) | GPLv3 |
| Claude (Anthropic) przez Claude Code CLI / Gemini API | usługi zewnętrzne, opcjonalne; obowiązują regulaminy dostawców |

## Struktura repo
```
FUNKCJE.md             krótki opis funkcji i przebiegu pozyskiwania danych
setup.sh               instalacja lokalna jednym poleceniem (środowisko, modele, panel, opcjonalnie zbiór demonstracyjny)
Dockerfile, docker-compose.yml   obraz z modelami i panelem; profile: neo4j, scheduler
requirements.txt       biblioteki Pythona; requirements-legacy.txt: tylko dla historycznego app.py
web/                   panel analityka: React + TypeScript + Tailwind + shadcn/ui, Cytoscape.js (graf)
ftf/api.py             FastAPI: JSON dla panelu (kampanie, pary z uzasadnieniem, graf, macierz, analiza, skaner)
ftf/labels.py          polskie etykiety enumów, grup identyfikatorów, widoków, relacji i decyzji
app.py                 poprzedni demonstrator Streamlit (historyczny)
ftf/ingest.py          materiały i loadery (folder przypadku, upload, URL, tekst)
ftf/capture.py         przechwycenie URL: 3 profile klienta, cloaking, Playwright
ftf/web.py             URL/HTML/HAR/MHTML → wskaźniki (piksele, TDS, endpointy, DOM…)
ftf/vision.py          pHash, OCR, QR, klatki wideo, wycięcie kreacji
ftf/faces.py           SCRFD + ArcFace + baza referencyjna
ftf/assets/            gotowe embeddingi bazy referencyjnej twarzy (face_gallery.npz + opis w .json)
ftf/text.py            MinHash, maskowanie osób, e5, słowa kluczowe, kwoty
ftf/gazetteer.py       osoby / marki / media / leksykony (PL)
ftf/llm.py             atrybuty LLM: typ oszustwa, osoby, marki, medium, produkt (claude CLI / Gemini / reguły)
ftf/similarity.py      identyfikatory (must-link, MAX_DF), widoki treści, odległość Gowera, Link + uzasadnienie
ftf/cluster.py         średnie wiązanie: duplikaty, kampanie, rodziny; HDBSCAN; przypisanie open-set (1-NN)
ftf/graph.py           NetworkX, pyvis, Neo4j/Cypher
ftf/sources.py         CERT PL, MS Ad Library, Google ATC, Meta API/yt-dlp, LinkedIn
ftf/scheduler.py       APScheduler: skan → triage → analiza
tools/                 pobieranie modeli, baza twarzy, ewaluacja
tests/                 testy (python -m unittest); tests/fixtures/synthetic_dataset = zbiór demonstracyjny
tools/harvest_urlscan.py, ingest_parallel.py, research_corpus.py   korpus badawczy: pobranie (domyślnie wyłączone, niebezpieczne), równoległa ekstrakcja, badanie cech
research/              raporty z researchu (źródła, infrastruktura, modele, prior art)
```
