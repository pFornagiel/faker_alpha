# FakerAlpha w terminalu — opis CLI

`python -m ftf` daje analitykowi w terminalu (albo skryptowi) to samo, co panel WWW: kampanie, materiały, uzasadnienie
każdej pary, śledzenie pojedynczej wartości, analizę nowego materiału, miary jakości grupowania i eksport. Polecenia
odczytu wypisują czytelne tabele, a z opcją `--json` — JSON o stałych kluczach.

Wszystkie przykłady w tym dokumencie pochodzą z prawdziwego uruchomienia na **syntetycznym** zbiorze
`tests/fixtures/synthetic_dataset` (osiem zmyślonych przypadków w domenach `.example`). Możesz je powtórzyć u siebie
bez dostępu do zbioru organizatora i bez sieci.

Spis treści: [Instalacja](#instalacja) · [Baza materiałów](#baza-materiałów) · [Pierwsza analiza](#pierwsza-analiza) ·
[Zasady wspólne](#zasady-wspólne) · [Polecenia](#polecenia) · [JSON](#json) · [Kody wyjścia](#kody-wyjścia) ·
[Zmienne środowiskowe](#zmienne-środowiskowe) · [Co polecenia zapisują na dysku](#co-polecenia-zapisują-na-dysku) ·
[Zgodność ze starszymi wywołaniami](#zgodność-ze-starszymi-wywołaniami) · [Czego w CLI nie ma](#czego-w-cli-nie-ma)

## Instalacja

CLI nie ma własnych zależności — używa tego samego środowiska co reszta projektu (README, „Szybki start”):

```bash
./setup.sh --no-web                           # biblioteki i modele; bez --no-web buduje też panel (wymaga Node ≥ 20)
.venv/bin/python -m ftf --help
```

albo ręcznie:

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python tools/download_models.py     # modele ONNX: znaczenie tekstu (e5), twarze, OCR
.venv/bin/python -m ftf --help
```

W Dockerze każde polecenie poprzedź `docker compose exec app`, np. `docker compose exec app python -m ftf status`.

Dalej piszemy krótko `python -m ftf`; chodzi o interpreter z `.venv` (`.venv/bin/python -m ftf` albo po
`source .venv/bin/activate`). `python -m ftf` i `python -m ftf.cli` to to samo polecenie.

## Baza materiałów

Wszystko, co CLI pokazuje, pochodzi z jednego pliku SQLite z cechami materiałów. O tym, który plik zostanie użyty,
decyduje kolejno:

1. opcja `--store ŚCIEŻKA` (przed poleceniem albo po nim),
2. zmienna środowiskowa `FTF_STORE`,
3. domyślnie `<FTF_ROOT>/data/store/ftf.sqlite`, gdzie `FTF_ROOT` to katalog repozytorium, chyba że zmienna
   `FTF_ROOT` wskazuje inny katalog danych.

```bash
python -m ftf --store data/store/demo_syntetyczne.sqlite campaigns
FTF_STORE=data/store/demo_syntetyczne.sqlite python -m ftf campaigns
FTF_ROOT=/srv/fakeralpha python -m ftf status        # baza: /srv/fakeralpha/data/store/ftf.sqlite
```

Polecenia odczytu otwierają bazę **tylko do odczytu** i nigdy jej nie tworzą. Jeśli pliku nie ma albo jest pusty,
polecenie kończy się kodem 3 i mówi, co zrobić:

```text
$ python -m ftf --store /tmp/nie-ma-takiej.sqlite campaigns
błąd: nie znaleziono bazy materiałów: /tmp/nie-ma-takiej.sqlite
  wskaż istniejącą bazę:  python -m ftf --store ŚCIEŻKA <polecenie>   albo zmienna FTF_STORE=ŚCIEŻKA
  albo utwórz ją:         python -m ftf ingest <folder_zbioru>   lub   python -m ftf add <plik|folder|"tekst">
  domyślna baza to <FTF_ROOT>/data/store/ftf.sqlite; FTF_ROOT domyślnie wskazuje katalog repozytorium
```

Bazę tworzą wyłącznie polecenia, które zapisują: `ingest`, `demo`, `add` bez `--dry` oraz `serve`. Kampanie nie są
przechowywane w bazie — każde polecenie odczytu porównuje wszystkie pary od nowa (kilka sekund przy kilkudziesięciu
materiałach; powyżej 400 materiałów CLI uprzedza, że potrwa to dłużej).

## Pierwsza analiza

Poniższa sesja zakłada osobną bazę na dane syntetyczne, żeby nie dotykać bazy domyślnej:

```bash
export FTF_STORE=data/store/demo_syntetyczne.sqlite
export FTF_LLM=none FTF_ENRICH=0      # nic nie wychodzi poza ten komputer (bez modelu językowego, bez RDAP / DNS / crt.sh)
```

**1. Import zbioru.** Każdy podfolder to jeden przypadek. Postęp idzie na stderr, wynik na stdout:

```text
$ python -m ftf ingest tests/fixtures/synthetic_dataset --no-llm
Tworzę nową bazę: data/store/demo_syntetyczne.sqlite
[1/8] syn-07-kasyno
[2/8] syn-08-krypto
[3/8] syn-04-fundusz
[4/8] syn-06-loteria
[5/8] syn-01-kardivix
[6/8] syn-02-kardivix-bis
[7/8] syn-03-kardivix-news
[8/8] syn-05-fundusz-tekst
Przetworzono 8 przypadków z tests/fixtures/synthetic_dataset: 8 nowych, 0 już było w bazie (pominięte; --force
analizuje ponownie). Baza data/store/demo_syntetyczne.sqlite ma 8 materiałów.

5 kampanii · 8 materiałów (2 wielomateriałowych, 3 pojedynczych)

KOD  MAT.  NAZWA                            TYP OSZUSTWA      ŚLADY  ŚR. p  MATERIAŁY         DOMENY
C1      3  „cudowny” produkt zdrowotny      „cudowny” produ…      6   1.00  syn-01-kardivix…  kardivix-promo.…
C2      2  fałszywa platforma inwestycyjna  fałszywa platfo…      —   0.46  syn-04-fundusz,…  zloty-fundusz.e…
C3      1  nielegalny hazard                nielegalny haza…      —      —  syn-07-kasyno
C4      1  fałszywa platforma inwestycyjna  fałszywa platfo…      —      —  syn-08-krypto     krypto-akademia…
C5      1  fałszywa ankieta / rozdanie      fałszywa ankiet…      —      —  syn-06-loteria

Najmocniejsze wspólne ślady
  C1  domena docelowa: kardivix-promo.example — 2 mat.
      Facebook Pixel: 900000000000001 — 3 mat.
      Google Tag Manager: GTM-SYNTH01 — 2 mat.
      Telegram: kardivix_syntetyczny — 2 mat.

Duplikaty (ten sam materiał zgłoszony kilka razy)
  syn-01-kardivix = syn-02-kardivix-bis

Rodziny (podobna treść, osobne kampanie)
  C3 nielegalny hazard + C5 fałszywa ankieta / rozdanie
```

**2. Jedna kampania z bliska** — kto do niej należy i który ślad łączy które materiały:

```text
$ python -m ftf campaign C1
C1 · „cudowny” produkt zdrowotny
  materiały:    3 · par wewnątrz: 3 · średnie p wewnątrz: 1.00
  typ oszustwa: „cudowny” produkt zdrowotny (3)
  domeny:       kardivix-promo.example, zdrowe-serce-news.example

Materiały
  NAZWA             ID            TYP OSZUSTWA      PRODUKT  DOMENY            TYTUŁ
  syn-01-kardivix   4799a4116662  „cudowny” produ…  —        kardivix-promo.…  Kardivix — kapsułki na serce.…
  syn-02-kardivix…  5cc6e90ebf7c  „cudowny” produ…  —        kardivix-promo.…  Kardivix — kapsułki na serce.…
  syn-03-kardivix…  c1ddb81f1b96  „cudowny” produ…  —        zdrowe-serce-ne…  Kardiolog ujawnia w wywiadzie:…

Wspólne ślady — który ślad łączy które materiały
  GRUPA                   ŚLAD                 WARTOŚĆ                           MATERIAŁY               ŁĄCZY
  domena                  domena docelowa      kardivix-promo.example            syn-01-kardivix, syn-…  tak
  identyfikator śledzący  Facebook Pixel       900000000000001                   syn-01-kardivix, syn-…  tak
  identyfikator śledzący  Google Tag Manager   GTM-SYNTH01                       syn-01-kardivix, syn-…  tak
  kontakt                 Telegram             kardivix_syntetyczny              syn-01-kardivix, syn-…  tak
  plik / szablon kitu     endpoint formularza  kardivix-promo.example/api/order  syn-01-kardivix, syn-…  tak
  plik / szablon kitu     szablon ścieżki URL  /oferta/serce                     syn-01-kardivix, syn-…  tak

Łańcuch najsilniejszych par — jak kampania trzyma się razem
  A                B                     p     d  PODSTAWA            UZASADNIENIE
  syn-01-kardivix  syn-02-kardivix-…  1.00  0.00  duplikat            Domena docelowa: „kardivix-promo.exampl…
  syn-01-kardivix  syn-03-kardivix-…  1.00  0.84  wspólny identyfik…  Facebook Pixel: „900000000000001” — w 3…

Profil podobieństwa w widokach treści (średnia: pary wewnątrz kampanii / pary z materiałami spoza)
  WIDOK                  WEWNĄTRZ  NA ZEWNĄTRZ  PAR WEWN.  PAR ZEWN.
  tekst strony               0.33         0.00          3          6
  znaczenie tekstu (e5)      0.64         0.00          3         15
  struktura HTML             0.35         0.04          3          6
  klasy CSS                  1.00            —          1          0
```

**3. Dlaczego te dwa materiały są razem** — pełne wyjaśnienie pary:

```text
$ python -m ftf pair syn-01-kardivix syn-03-kardivix-news
syn-01-kardivix  ↔  syn-03-kardivix-news
  syn-01-kardivix:      4799a4116662 · C1 · Kardivix — kapsułki na serce. Oferta specjalna tylko dziś
  syn-03-kardivix-news: c1ddb81f1b96 · C1 · Kardiolog ujawnia w wywiadzie: nadciśnienie znika po 3 tygodniach
                        — Portal Zdrowe Serce

Relacja: ta sama kampania   p = 1.00   d = 0.84
  Wspólny identyfikator obecny w co najwyżej 50% materiałów (Facebook Pixel: „900000000000001”) — powiązanie
  pewne (must-link), p = 1.
  (ta sama kampania: wspólny identyfikator (obecny w ≤ 50% materiałów) lub d ≤ 0.6)

Wspólne identyfikatory (łączą na pewno)
  GRUPA                   ŚLAD            WARTOŚĆ           df
  identyfikator śledzący  Facebook Pixel  900000000000001  3/8

Podobieństwo w widokach treści
  WIDOK                  PODOBIEŃSTWO  WKŁAD s/k  UWAGI
  tekst strony                  0.000      0.000
  tekst kreacji (OCR)               —          —  niedostępny po obu stronach — pominięty
  znaczenie tekstu (e5)         0.460      0.153
  struktura HTML                0.031      0.010
  klasy CSS                         —          —  niedostępny po obu stronach — pominięty
  szkielet skryptów                 —          —  niedostępny po obu stronach — pominięty
  obrazy                            —          —  niedostępny po obu stronach — pominięty

Obliczenie odległości treści
  d = 1 − (0.00 + 0.46 + 0.03) / 3 = 0.84
  p = 1.00  (wspólny identyfikator → p = 1)
```

**4. Nowy materiał** — analiza „na sucho”, czyli bez zapisu w bazie:

```text
$ python -m ftf add tests/fixtures/synthetic_new_ad.html --dry --no-llm
Analiza (plik): synthetic_new_ad.html
  HTML: synthetic_new_ad.html
  text embedding
Decyzja: Znana kampania → C1 · „cudowny” produkt zdrowotny   [known_campaign]
  Materiał ma wspólny identyfikator z kampanią w bazie lub jego treść jest bliska pojedynczemu znanemu
  materiałowi (najbliższy sąsiad, 1-NN — Cover & Hart 1967; d ≤ 0.6) — przypisano go do kampanii tego
  materiału.
  materiał:                  synthetic_new_ad.html · id 9a0662cd91f7
  najbliższy znany materiał: syn-03-kardivix-news (C1 · „cudowny” produkt zdrowotny), d = 0.85
  zapis:                     nie zapisano — analiza na sucho (--dry)

Najbliższe kampanie (odległość do najbliższego materiału kampanii, 1-NN)
  KOD  NAZWA                            MAT.     p     d
  C1   „cudowny” produkt zdrowotny         3  0.15  0.85
  C4   fałszywa platforma inwestycyjna     1  0.04  0.96
  C2   fałszywa platforma inwestycyjna     2  0.03  0.97
  C3   nielegalny hazard                   1  0.00  1.00
  C5   fałszywa ankieta / rozdanie         1  0.00  1.00

Dowody — najbliższe materiały w bazie
  MATERIAŁ              KAMP.     p     d  RELACJA           UZASADNIENIE
  syn-03-kardivix-news  C1     1.00  0.85  ta sama kampania  Facebook Pixel: „900000000000001” — w 4 z 9 mate…
  syn-01-kardivix       C1     1.00  0.85  ta sama kampania  Facebook Pixel: „900000000000001” — w 4 z 9 mate…
  syn-02-kardivix-bis   C1     1.00  0.85  ta sama kampania  Facebook Pixel: „900000000000001” — w 4 z 9 mate…
  syn-08-krypto         C4     0.04  0.96  brak powiązania   struktura HTML 0.11
  syn-04-fundusz        C2     0.03  0.97  brak powiązania   struktura HTML 0.09
  syn-05-fundusz-tekst  C2     0.00  1.00  brak powiązania   odległa treść (d = 1.00)
  syn-06-loteria        C5     0.00  1.00  brak powiązania   odległa treść (d = 1.00)
  syn-07-kasyno         C3     0.00  1.00  brak powiązania   odległa treść (d = 1.00)
  Najbliższa para: Wspólny identyfikator obecny w co najwyżej 50% materiałów (Facebook Pixel:
  „900000000000001”) — powiązanie pewne (must-link), p = 1. d = 1 − (0.01 + 0.37 + 0.07) / 3 = 0.85

Identyfikatory nowego materiału (W BAZIE = ile z 8 pozostałych materiałów ma tę wartość)
  GRUPA                  ŚLAD                    WARTOŚĆ                               W BAZIE  STATUS
  domena                 domena docelowa         serce-bez-tabletek.example                0/8  nowa wartość
  domena                 host strony             serce-bez-tabletek.example                0/8  nowa wartość
  identyfikator śledzą…  Facebook Pixel          900000000000001                           3/8  łączy z 3 mat.
  plik / szablon kitu    endpoint formularza     serce-bez-tabletek.example/api/order      0/8  nowa wartość
  plik / szablon kitu    szablon ścieżki URL     /promo/kardivix                           0/8  nowa wartość
  produkt / platforma    nazwa produktu / plat…  kardivix                                  0/8  nowa wartość

dostępne widoki treści: tekst strony, znaczenie tekstu (e5), struktura HTML
typ oszustwa:           „cudowny” produkt zdrowotny
produkt / platforma:    Kardivix
```

Trzy pierwsze linie („Analiza…”, kroki ekstrakcji) to postęp na stderr; `-q` je wyłącza.

## Zasady wspólne

### Opcje wspólne

Działają z każdym poleceniem i można je podać przed nim albo po nim (`python -m ftf -q campaigns` = `python -m ftf campaigns -q`).

| Opcja | Znaczenie |
|---|---|
| `--store ŚCIEŻKA` | plik bazy; ma pierwszeństwo przed `FTF_STORE` |
| `-v`, `--verbose` | więcej na stderr: `-v` kroki i czas porównania, `-vv` diagnostyka bibliotek; przy błędzie wewnętrznym pełny ślad stosu |
| `-q`, `--quiet` | bez komunikatów postępu i podpowiedzi |
| `--color auto\|always\|never` | kolor; `auto` (domyślnie) włącza go tylko w terminalu, gdy nie ustawiono `NO_COLOR` i `TERM` nie jest `dumb` |
| `--no-color` | to samo co `--color never` |
| `--wide` | nie skracaj tabel do szerokości terminala |
| `-h`, `--help` | pomoc polecenia z przykładami |
| `-V`, `--version` | wersja (tylko przed poleceniem) |

Polecenia odczytu mają dodatkowo `--json` (patrz [JSON](#json)).

### Wyjście

- **stdout** dostaje wyłącznie wynik: tabelę albo JSON. **stderr** dostaje postęp, uwagi i błędy. Dzięki temu
  `python -m ftf links --json > pary.json` zawsze daje poprawny plik.
- Tabele mieszczą się w szerokości terminala; za długie komórki kończą się znakiem `…`. Poza terminalem (potok,
  plik) limit to `$COLUMNS`, a bez tej zmiennej 140 znaków. `--wide` wyłącza skracanie, `--json` daje pełne wartości.
  Liczby i identyfikatory materiałów nie są skracane.
- Kolor oznacza relację pary (duplikat, ta sama kampania, podobna treść) i nigdy nie jest jedynym nośnikiem
  informacji — ta sama relacja jest zawsze wypisana słowami.
- Podpowiedź „Dalej: …” pod wynikiem pojawia się tylko w terminalu.

### Jak wskazać materiał i kampanię

**Materiał** (argumenty `MATERIAŁ`, `A`, `B`, `--of`, `--material`) można podać jako:

1. pełny identyfikator — 12 znaków z kolumny `ID`,
2. dokładną nazwę (kolumna `NAZWA`; dla przypadku z folderu to nazwa folderu),
3. początek identyfikatora, co najmniej 4 znaki,
4. nazwę bez rozróżniania wielkości liter i polskich znaków,
5. jednoznaczny fragment nazwy, co najmniej 3 znaki.

Gdy tekst pasuje do kilku materiałów, polecenie niczego nie zgaduje — wypisuje kandydatów i kończy się kodem 4:

```text
$ python -m ftf material kardivix
błąd: „kardivix” pasuje do 3 materiałów: 4799a4116662 (syn-01-kardivix), 5cc6e90ebf7c (syn-02-kardivix-bis), c1ddb81f1b96 (syn-03-kardivix-news)
  podaj pełny identyfikator materiału (pierwsza kolumna ID w `materials`)
```

Identyfikator przypadku z folderu zależy od ścieżki tego folderu, więc na Twoim komputerze identyfikatory z przykładów
będą inne; nazwy pozostaną te same.

**Kampania** (argument `KAMPANIA`, `--campaign`) to kod z kolumny `KOD`: `C1`, `c1` albo samo `1`. Kody są nadawane
od największej kampanii przy każdym uruchomieniu, więc po dodaniu materiałów numeracja może się zmienić. Trwałym
odnośnikiem jest materiał: `python -m ftf campaign --of <materiał>`.

### Pojęcia w dwóch zdaniach

Materiały łączy w kampanię **wspólny identyfikator** (ta sama domena, piksel, kontakt, plik kitu…) — o ile wartość
występuje w co najwyżej 50% materiałów bazy (`df/N ≤ 50%`) — albo **bliska treść**: odległość `d ≤ 0.6`, liczona jako
1 − średnia podobieństw w widokach treści dostępnych po obu stronach. Bliskość `p` wynosi 1.00 przy wspólnym
identyfikatorze, a w pozostałych przypadkach `1 − d`. Pełny słowniczek z aktualnymi progami: `python -m ftf glossary`.

## Polecenia

| Polecenie | Do czego służy | Zapisuje? |
|---|---|---|
| [`status`](#status) | która baza, ile materiałów i kampanii, konfiguracja | nie |
| [`campaigns`](#campaigns) | lista kampanii, najmocniejsze wspólne ślady, duplikaty, rodziny | nie |
| [`campaign`](#campaign) | jedna kampania: materiały, wspólne ślady, najsilniejsze pary | nie |
| [`materials`](#materials) | lista materiałów z filtrem | nie |
| [`material`](#material) | jeden materiał: opis, identyfikatory z `df`, widoki treści, najbliższe materiały | nie |
| [`search`](#search) | szukanie tekstu w materiałach, kampaniach i wartościach śladów | nie |
| [`links`](#links) | pary materiałów z uzasadnieniem | nie |
| [`pair`](#pair) | pełne wyjaśnienie jednej pary | nie |
| [`trace`](#trace) | wszystkie materiały z daną wartością śladu | nie |
| [`matrix`](#matrix) | macierz bliskości | nie |
| [`metrics`](#metrics) | jakość grupowania: metody, silhouette, ARI, rozkłady | nie |
| [`eval`](#eval) | zgodność kampanii z własnymi etykietami | nie |
| [`add`](#add) (alias `analyse`) | analiza nowego materiału: plik, folder, URL albo tekst | tak, chyba że `--dry` |
| [`ingest`](#ingest) | import zbioru przypadków | tak |
| [`demo`](#demo) | import zbioru demonstracyjnego dołączonego do kodu | tak |
| [`export`](#export) | pliki `graph.html`, `graph.cypher`, `campaigns.json`, `links.csv` | tylko pliki eksportu |
| [`serve`](#serve) | panel WWW i API | tak (panel pozwala dodawać materiały) |
| [`glossary`](#glossary) | słowniczek pojęć, typów śladów i progów | nie, nie wymaga bazy |

### status

```text
python -m ftf status [--json]
```

Która baza jest używana i co w niej jest. Kod wyjścia 0 oznacza bazę z materiałami, 3 — brak bazy albo pustą bazę,
więc polecenie nadaje się na warunek w skrypcie (`python -m ftf status -q >/dev/null || …`).

```text
$ python -m ftf status
FakerAlpha 0.1.0
Baza:            data/store/demo_syntetyczne.sqlite (96 kB, otwarta tylko do odczytu)
Materiały:       8 (zbiór organizatora 8)
Kampanie:        5 (2 wielomateriałowych obejmuje 5 materiałów · 3 pojedynczych)
Duplikaty:       1 grupa
Rodziny:         1 łączących co najmniej 2 kampanie
Pary:            28 (duplikat 1 · ta sama kampania 3 · podobna treść 2 · brak powiązania 22)
Progi:           duplikat d ≤ 0.05 · kampania d ≤ 0.6 · rodzina d ≤ 0.93 · identyfikator liczy się przy df/N ≤
                 50%
Ostatnio dodany: 2026-11-22T03:08:53+00:00
LLM:             FTF_LLM=none (wyłączone); dostępne: claude_cli tak, gemini nie
Panel WWW:       zbudowany — python -m ftf serve
Neo4j:           nieskonfigurowany (NEO4J_URI)
```

Uwaga: `ingest` oznacza każdy importowany zbiór jako źródło `organizer` („zbiór organizatora”), także ten syntetyczny.

### campaigns

```text
python -m ftf campaigns [--json] [--min-size N]
```

| Opcja | Znaczenie |
|---|---|
| `--min-size N` | tylko kampanie z co najmniej N materiałami (domyślnie 1, czyli także pojedyncze) |

Odpowiednik strony „Kampanie”. `ŚLADY` to liczba wspólnych wartości identyfikatorów, `ŚR. p` — średnia bliskość par
wewnątrz kampanii.

```text
$ python -m ftf campaigns
5 kampanii · 8 materiałów (2 wielomateriałowych, 3 pojedynczych)

KOD  MAT.  NAZWA                            TYP OSZUSTWA      ŚLADY  ŚR. p  MATERIAŁY         DOMENY
C1      3  „cudowny” produkt zdrowotny      „cudowny” produ…      6   1.00  syn-01-kardivix…  kardivix-promo.…
C2      2  fałszywa platforma inwestycyjna  fałszywa platfo…      —   0.46  syn-04-fundusz,…  zloty-fundusz.e…
C3      1  nielegalny hazard                nielegalny haza…      —      —  syn-07-kasyno
C4      1  fałszywa platforma inwestycyjna  fałszywa platfo…      —      —  syn-08-krypto     krypto-akademia…
C5      1  fałszywa ankieta / rozdanie      fałszywa ankiet…      —      —  syn-06-loteria

Najmocniejsze wspólne ślady
  C1  domena docelowa: kardivix-promo.example — 2 mat.
      Facebook Pixel: 900000000000001 — 3 mat.
      Google Tag Manager: GTM-SYNTH01 — 2 mat.
      Telegram: kardivix_syntetyczny — 2 mat.

Duplikaty (ten sam materiał zgłoszony kilka razy)
  syn-01-kardivix = syn-02-kardivix-bis

Rodziny (podobna treść, osobne kampanie)
  C3 nielegalny hazard + C5 fałszywa ankieta / rozdanie
```

### campaign

```text
python -m ftf campaign [--json] [--all-pairs] KAMPANIA
python -m ftf campaign [--json] [--all-pairs] --of MATERIAŁ
```

| Opcja | Znaczenie |
|---|---|
| `--of MATERIAŁ` | zamiast kodu: kampania, do której należy ten materiał |
| `--all-pairs` | wszystkie pary wewnątrz kampanii zamiast samego łańcucha najsilniejszych |

Odpowiednik strony „Kampania”: materiały, macierz „który ślad łączy które materiały”, łańcuch najsilniejszych par,
profil podobieństwa w widokach treści, a gdy istnieją — najbliższe materiały spoza kampanii i kampanie z tej samej
rodziny. Przykładowy wynik jest w sekcji [Pierwsza analiza](#pierwsza-analiza).

### materials

```text
python -m ftf materials [--json] [--campaign KAMPANIA] [--source ŹRÓDŁO] [--limit N] [TEKST]
```

| Opcja | Znaczenie |
|---|---|
| `TEKST` | tylko materiały zawierające ten tekst w nazwie, identyfikatorze, tytule, produkcie, typie oszustwa, osobach, domenach albo kampanii (bez rozróżniania wielkości liter i polskich znaków) |
| `--campaign KAMPANIA` | tylko materiały tej kampanii |
| `--source ŹRÓDŁO` | tylko jedno źródło: `organizer`, `upload`, `url`, `text`, `scheduler` |
| `--limit N` | najwyżej N wierszy |

```text
$ python -m ftf materials
ID            NAZWA             KAMP.  TYP OSZUSTWA      PRODUKT  ID.  DOMENY            TYTUŁ
4799a4116662  syn-01-kardivix   C1     „cudowny” produ…  —          7  kardivix-promo.…  Kardivix — kapsułki…
5cc6e90ebf7c  syn-02-kardivix…  C1     „cudowny” produ…  —          7  kardivix-promo.…  Kardivix — kapsułki…
c1ddb81f1b96  syn-03-kardivix…  C1     „cudowny” produ…  —          4  zdrowe-serce-ne…  Kardiolog ujawnia w…
5325d56d8cc4  syn-04-fundusz    C2     fałszywa platfo…  —          6  zloty-fundusz.e…  Złoty Fundusz Obywat…
9d4510a5c7af  syn-05-fundusz-…  C2     fałszywa platfo…  —          0                    TYTUŁY:
a9f60a466f09  syn-07-kasyno     C3     nielegalny haza…  —          0                    TYTUŁY:
af9c6581a815  syn-08-krypto     C4     fałszywa platfo…  —          6  krypto-akademia…  Krypto Akademia Seni…
e13181bca6e1  syn-06-loteria    C5     fałszywa ankiet…  —          0                    TYTUŁY:

8 materiałów · ID. = liczba wartości identyfikatorów, które mogą łączyć
```

### material

```text
python -m ftf material [--json] [--all-values] MATERIAŁ
```

| Opcja | Znaczenie |
|---|---|
| `--all-values` | wszystkie wartości identyfikatorów (domyślnie do 6 na typ, w JSON do 12) |

Odpowiednik strony materiału. `df` mówi, w ilu materiałach bazy występuje dana wartość; kolumna `STATUS` — czy ta
wartość kogoś łączy, czy jest pomijana jako zbyt popularna. Sekcja „Opis” to cechy opisowe, które nigdy nie łączą.

```text
$ python -m ftf material syn-03-kardivix-news
Materiał syn-03-kardivix-news   id c1ddb81f1b96
  tytuł:    Kardiolog ujawnia w wywiadzie: nadciśnienie znika po 3 tygodniach — Portal Zdrowe Serce
  kampania: C1 · „cudowny” produkt zdrowotny (3 materiały)
  źródło:   zbiór organizatora — tests/fixtures/synthetic_dataset/syn-03-kardivix-news
  dodany:   2026-11-22T03:08:53+00:00
  wejście:  1 strona, 0 obrazów, 0 wideo, 0 zasobów strony

Opis (cechy opisowe — nigdy nie łączą)
  streszczenie:     TYTUŁY: Kardiolog ujawnia w wywiadzie: nadciśnienie znika po 3 tygodniach — Portal Zdrowe
                    Serce
  typ oszustwa:     „cudowny” produkt zdrowotny
  źródło atrybutów: reguły słownikowe (bez modelu językowego)
  słowa kluczowe:   portal zdrowe, zdrowe serce, nadciśnienie znika, kardiolog ujawnia, serce portal, serce
                    kardiolog, serce wiadomości, wiadomości wywiady, wywiady zdrowie, wywiad dnia (+5)
  kwoty:            199 zł, 398 zł
  adresy docelowe:  https://zdrowe-serce-news.example/wywiad/kardiolog-ujawnia

Identyfikatory (df = w ilu z 8 materiałów bazy występuje wartość)
  GRUPA                   ŚLAD                 WARTOŚĆ                     df  STATUS
  domena                  domena docelowa      zdrowe-serce-news.example  1/8  tylko w tym materiale
  domena                  host strony          zdrowe-serce-news.example  1/8  tylko w tym materiale
  identyfikator śledzący  Facebook Pixel       900000000000001            3/8  łączy z 2 mat.
  plik / szablon kitu     szablon ścieżki URL  /wywiad/kardiolog-ujawnia  1/8  tylko w tym materiale

Widoki treści — na czym ten materiał da się porównać
  WIDOK                  DOSTĘPNY  CO ZAWIERA
  tekst strony           tak       1208 znaków tekstu strony
  tekst kreacji (OCR)    nie       —
  znaczenie tekstu (e5)  tak       wektor znaczenia tekstu (384 liczby)
  struktura HTML         tak       szablon znaczników HTML strony
  klasy CSS              nie       —
  szkielet skryptów      nie       —
  obrazy                 nie       —

Najbliższe materiały
  NAZWA             ID            KAMP.     p     d  RELACJA           UZASADNIENIE
  syn-01-kardivix   4799a4116662  C1     1.00  0.84  ta sama kampania  Facebook Pixel: „900000000000001” — w…
  syn-02-kardivix…  5cc6e90ebf7c  C1     1.00  0.84  ta sama kampania  Facebook Pixel: „900000000000001” — w…
```

### search

```text
python -m ftf search [--json] TEKST [TEKST ...]
```

Wyszukiwarka z nagłówka panelu: tekst (co najmniej 2 znaki) jest szukany w nazwach, tytułach, produktach, osobach
i wartościach identyfikatorów. Zwraca pasujące kampanie, materiały i ślady; kod kampanii (np. `C2`) znajduje tę
kampanię. Brak trafień nie jest błędem: kod wyjścia 0, a w JSON puste listy.

```text
$ python -m ftf search kardivix
Materiały
  ID            NAZWA                 KAMP.  TRAFIENIA
  4799a4116662  syn-01-kardivix       C1     nazwa: syn-01-kardivix; tytuł: Kardivix — kapsułki na serce. Ofe…
  5cc6e90ebf7c  syn-02-kardivix-bis   C1     nazwa: syn-02-kardivix-bis; tytuł: Kardivix — kapsułki na serce.…
  c1ddb81f1b96  syn-03-kardivix-news  C1     nazwa: syn-03-kardivix-news

Ślady (wartości identyfikatorów i osoby)
  TYP             ŚLAD                 WARTOŚĆ                           MAT.
  landing_domain  domena docelowa      kardivix-promo.example               2
  page_host       host strony          kardivix-promo.example               2
  form_endpoint   endpoint formularza  kardivix-promo.example/api/order     2
  telegram        Telegram             kardivix_syntetyczny                 2
```

Znalezioną wartość można potem prześledzić dokładnie: `python -m ftf trace kardivix-promo.example`.

### links

```text
python -m ftf links [--json] [--min P] [--relation RELACJA] [--material MATERIAŁ] [--campaign KAMPANIA] [--limit N]
```

| Opcja | Znaczenie |
|---|---|
| `--min P` | najmniejsza bliskość `p` (domyślnie 0.1; `--min 0` pokazuje wszystkie pary) |
| `--relation RELACJA` | tylko pary o tej relacji: `duplicate`, `same_campaign`, `similar`, `none`; można powtórzyć |
| `--material MATERIAŁ` | tylko pary z tym materiałem |
| `--campaign KAMPANIA` | tylko pary wewnątrz tej kampanii |
| `--limit N` | najwyżej N par |

Pary od najbliższych. `KAMP.` pokazuje kampanię pary albo obie kampanie, gdy materiały należą do różnych.

```text
$ python -m ftf links
A                 B                 KAMP.       p     d  RELACJA           UZASADNIENIE
syn-01-kardivix   syn-02-kardivix…  C1       1.00  0.00  duplikat          Domena docelowa: „kardivix-promo.e…
syn-01-kardivix   syn-03-kardivix…  C1       1.00  0.84  ta sama kampania  Facebook Pixel: „900000000000001”…
syn-02-kardivix…  syn-03-kardivix…  C1       1.00  0.84  ta sama kampania  Facebook Pixel: „900000000000001”…
syn-04-fundusz    syn-05-fundusz-…  C2       0.46  0.54  ta sama kampania  Znaczenie tekstu (e5): podobieństw…
syn-05-fundusz-…  syn-06-loteria    C2 / C5  0.16  0.84  podobna treść     Znaczenie tekstu (e5): podobieństw…
syn-06-loteria    syn-07-kasyno     C5 / C3  0.15  0.85  podobna treść     Znaczenie tekstu (e5): podobieństw…

6 par o p ≥ 0.1 (p = 1 − D; p = 1.00 przy wspólnym identyfikatorze, inaczej 1 − d)
```

### pair

```text
python -m ftf pair [--json] A B
```

Odpowiednik strony „Para”: relacja i reguła, która ją dała, wspólne identyfikatory z `df`, wartości wspólne, ale
pominięte jako zbyt popularne, podobieństwo w każdym widoku treści i obliczenie odległości `d`. Przykładowy wynik jest
w sekcji [Pierwsza analiza](#pierwsza-analiza).

### trace

```text
python -m ftf trace [--json] [--type TYP] WARTOŚĆ [WARTOŚĆ ...]
```

| Opcja | Znaczenie |
|---|---|
| `--type TYP` | ogranicz do jednego typu śladu, np. `landing_domain`, `fb_pixel`, `phone`, `product`, `person`; pełną listę typów wypisuje `glossary` |

Odpowiednik strony „Ślad”: wszystkie materiały, które mają daną wartość, jej `df` i informacja, czy wartość liczy się
przy łączeniu. Bez `--type` przeszukiwane są wszystkie typy identyfikatorów oraz osoby.

```text
$ python -m ftf trace 900000000000001
Facebook Pixel: „900000000000001”   [fb_pixel · identyfikator śledzący]
  występuje w 3 z 8 materiałów (38%)
  liczy się jako identyfikator łączący (df/N ≤ 50%)
  ID            NAZWA                 KAMP.  TYP OSZUSTWA             TYTUŁ
  4799a4116662  syn-01-kardivix       C1     „cudowny” produkt zdro…  Kardivix — kapsułki na serce. Oferta sp…
  5cc6e90ebf7c  syn-02-kardivix-bis   C1     „cudowny” produkt zdro…  Kardivix — kapsułki na serce. Oferta sp…
  c1ddb81f1b96  syn-03-kardivix-news  C1     „cudowny” produkt zdro…  Kardiolog ujawnia w wywiadzie: nadciśni…
```

Wartość musi być pełna i dokładna. Gdy nie ma jej w bazie, polecenie podpowiada podobne i kończy się kodem 4:

```text
$ python -m ftf trace kardivix-promo
błąd: żaden materiał nie ma śladu „kardivix-promo”
  podobne ślady: landing_domain „kardivix-promo.example” (2 mat.); page_host „kardivix-promo.example” (2 mat.); form_endpoint „kardivix-promo.example/api/order” (2 mat.)
  wartość musi być pełna i dokładna; fragmentu szukaj przez: python -m ftf search "kardivix-promo"
```

### matrix

```text
python -m ftf matrix [--json] [--campaign KAMPANIA] [--distance]
```

| Opcja | Znaczenie |
|---|---|
| `--campaign KAMPANIA` | tylko materiały jednej kampanii |
| `--distance` | odległość treści `d` zamiast bliskości `p` |

Odpowiednik strony „Macierz”: wartości ×100, wiersze i kolumny w kolejności kampanii. Tabela tekstowa ma sens do
kilkudziesięciu materiałów; przy większej bazie użyj `--campaign` albo `--json`.

```text
$ python -m ftf matrix
bliskość p = 1 − D (×100), wiersze i kolumny w kolejności kampanii; · = brak powiązania, kolor = relacja

                                     1   2   3   4   5   6   7   8
  1 C1   syn-01-kardivix             — 100 100   ·   ·   ·   ·   ·
  2 C1   syn-02-kardivix-bis       100   — 100   ·   ·   ·   ·   ·
  3 C1   syn-03-kardivix-news      100 100   —   ·   ·   ·   ·   ·
  4 C2   syn-04-fundusz              ·   ·   ·   —  46   ·   ·   ·
  5 C2   syn-05-fundusz-tekst        ·   ·   ·  46   —   ·   ·  16
  6 C3   syn-07-kasyno               ·   ·   ·   ·   ·   —   ·  15
  7 C4   syn-08-krypto               ·   ·   ·   ·   ·   ·   —   ·
  8 C5   syn-06-loteria              ·   ·   ·   ·  16  15   ·   —

progi: duplikat d ≤ 0.05 · ta sama kampania d ≤ 0.6 lub wspólny identyfikator (p = 100) · podobna treść d ≤
0.93
```

### metrics

```text
python -m ftf metrics [--json] [--methods]
```

| Opcja | Znaczenie |
|---|---|
| `--methods` | dopisz objaśnienie każdej metody grupowania |

Liczby ze strony „Przestrzeń cech” i z wykresów strony „Kampanie”: porównanie metod grupowania na tych samych
odległościach (silhouette, ARI względem FakerAlpha i — jeśli istnieje `data/labels_dane.csv` — względem etykiet
referencyjnych), wysokości scaleń dendrogramu, rozkład odległości par, co łączy pary, rozdzielczość widoków, pokrycie
cech. `--json` zawiera dodatkowo współrzędne rzutów MDS / t-SNE i dendrogram, z których panel rysuje mapę.

```text
$ python -m ftf metrics
8 materiałów · 5 kampanii (2 wielomateriałowych, 3 pojedynczych) · 28 par, w tym 3 ze wspólnym identyfikatorem

Metody grupowania na tych samych odległościach
  METODA               GRUPY ≥ 2  POJED.  SZUM  SILHOUETTE  ARI/FakerAlpha  ARI/etykiety
  FakerAlpha                   2       3     0       0.475           1.000             —
  Sama treść                   2       4     0       0.100           0.632             —
  Pojedyncze wiązanie          2       3     0       0.475           1.000             —
  Pełne wiązanie               2       3     0       0.475           1.000             —
  HDBSCAN                      2       0     0       0.427           0.323             —
  Louvain                      2       1     0       0.440           0.521             —
  POJED. = grupy jednoelementowe; silhouette: zwartość grup na macierzy D (bliżej 1 = lepiej); ARI: zgodność
  podziału z FakerAlpha i z etykietami referencyjnymi (brak pliku data/labels_dane.csv albo brak dopasowanych
  materiałów); opis metod: python -m ftf metrics --methods

Wysokości scaleń dendrogramu (UPGMA)
  0 (×2), 0.538, 0.851, 0.943, 0.984, 0.995 — cięcia: kampanie 0.6, rodziny 0.93

Rozkład odległości treści d między parami
  d        PAR                                W. IDENT.  TA SAMA KAMP.  PODOBNE  BRAK
  0.0–0.1    1  █                                     1              0        0     0
  0.1–0.2    0                                        0              0        0     0
  0.2–0.3    0                                        0              0        0     0
  0.3–0.4    0                                        0              0        0     0
  0.4–0.5    0                                        0              0        0     0
  0.5–0.6    1  █                                     0              1        0     0
  0.6–0.7    0                                        0              0        0     0
  0.7–0.8    0                                        0              0        0     0
  0.8–0.9    4  █████                                 2              0        2     0
  0.9–1.0   22  ████████████████████████████          0              0        0    22

Co łączy pary w kampaniach
  PODSTAWA                       PAR
  identyfikator śledzący           3  ████████████████████████████
  domena                           1  █████████
  plik / szablon kitu              1  █████████
  kontakt                          1  █████████
  wyłącznie podobieństwo treści    1  █████████

Widoki treści: średnie podobieństwo w tej samej kampanii / w różnych kampaniach
  WIDOK                  TA SAMA  RÓŻNE  PAR (TA SAMA)  PAR (RÓŻNE)
  tekst strony             0.333  0.000              3            7
  tekst kreacji (OCR)      0.000  0.104              0            3
  znaczenie tekstu (e5)    0.596  0.021              4           24
  struktura HTML           0.354  0.041              3            7
  klasy CSS                1.000  0.000              1            0
  szkielet skryptów        0.000  0.000              0            0
  obrazy                   0.000  0.000              0            0

Pokrycie cech
  CECHA                                           MAT.   %
  Strona docelowa (HTML / URL)                     5/8  62  ████████████
  Kreacje / zrzuty / klatki                        0/8   0
  Tekst odczytany z obrazu (OCR)                   0/8   0
  Rozpoznane twarze (ArcFace)                      0/8   0
  Identyfikatory techniczne (piksele/kit/domena)   5/8  62  ████████████
  Metadane domen (RDAP / DNS / CERT)               0/8   0
  Atrybuty opisowe (LLM)                           0/8   0

Typy oszustw
  TYP                              MAT.
  „cudowny” produkt zdrowotny         3
  fałszywa platforma inwestycyjna     3
  fałszywa ankieta / rozdanie         1
  nielegalny hazard                   1
```

### eval

```text
python -m ftf eval [--json] ETYKIETY.csv
```

Zgodność kampanii z własnymi etykietami. Plik CSV ma wiersze `id_lub_nazwa_materiału,etykieta`; linie zaczynające się
od `#` są pomijane. Gdy żaden wiersz nie pasuje do materiału w bazie, polecenie kończy się kodem 5.

```text
$ python -m ftf eval tests/fixtures/synthetic_labels.csv
Zgodność kampanii z etykietami tests/fixtures/synthetic_labels.csv
  MIARA                             WARTOŚĆ  KLUCZ JSON
  materiały z etykietą                    8  n
  precyzja par                        1.000  pairwise_precision
  czułość par                         1.000  pairwise_recall
  F1 par                              1.000  pairwise_f1
  B-cubed precyzja                    1.000  bcubed_precision
  B-cubed czułość                     1.000  bcubed_recall
  ARI (FakerAlpha)                    1.000  ARI
  ARI (HDBSCAN, punkt odniesienia)    0.323  ARI_hdbscan_baseline
```

Pełny protokół oceny (leave-one-out i warianty syntetyczne) pozostaje w `tools/evaluate.py`.

### add

```text
python -m ftf add [--json] [--no-llm] [--dry] [--text] [--no-render] CEL
python -m ftf analyse …        # alias
```

| Opcja | Znaczenie |
|---|---|
| `CEL` | istniejący plik (zrzut, wideo, HTML, HAR, MHTML, ZIP przypadku) lub folder przypadku; adres `http(s)://…`; w pozostałych przypadkach tekst (treść reklamy, nazwa produktu) |
| `--dry` | tylko analiza i decyzja; baza jest otwierana tylko do odczytu i nic do niej nie trafia |
| `--no-llm` | bez modelu językowego — atrybuty opisowe z reguł słownikowych |
| `--text` | traktuj `CEL` jako tekst, nawet jeśli wygląda jak ścieżka albo adres |
| `--no-render` | adres URL: bez renderowania w headless Chromium (samo pobranie HTTP) |

Odpowiednik strony „Analizuj materiał”. Decyzja open-set to jedna z czterech: `duplicate` (duplikat),
`known_campaign` (znana kampania), `merge_proposal` (propozycja scalenia — materiał ma wspólne identyfikatory z dwiema
kampaniami) albo `new_campaign` (nowy wzorzec). Pod decyzją są dowody: najbliższe kampanie, najbliższe materiały
z uzasadnieniem i identyfikatory nowego materiału z informacją, ile materiałów bazy ma tę samą wartość.

Przykład z plikiem jest w sekcji [Pierwsza analiza](#pierwsza-analiza). Sam tekst, bez komunikatów postępu (`-q`):

```text
$ python -m ftf add 'Wygraj 25 000 zł w loterii, opłać tylko przesyłkę 4,99 zł' --dry --no-llm -q
Decyzja: Nowy wzorzec   [new_campaign]
  Brak wspólnych identyfikatorów i żaden znany materiał nie jest dość bliski treścią — prawdopodobnie nowa
  kampania.
  materiał:                  Wygraj 25 000 zł w loterii, opłać tylko przesyłkę 4,99 zł · id 286ef214cddb
  najbliższy znany materiał: syn-06-loteria (C5 · fałszywa ankieta / rozdanie), d = 0.82
  podobna rodzina:           C5 · fałszywa ankieta / rozdanie
  zapis:                     nie zapisano — analiza na sucho (--dry)

Najbliższe kampanie (odległość do najbliższego materiału kampanii, 1-NN)
  KOD  NAZWA                            MAT.     p     d
  C5   fałszywa ankieta / rozdanie         1  0.18  0.82
  C1   „cudowny” produkt zdrowotny         3  0.00  1.00
  C2   fałszywa platforma inwestycyjna     2  0.00  1.00
  C3   nielegalny hazard                   1  0.00  1.00
  C4   fałszywa platforma inwestycyjna     1  0.00  1.00

Dowody — najbliższe materiały w bazie
  MATERIAŁ              KAMP.     p     d  RELACJA          UZASADNIENIE
  syn-06-loteria        C5     0.18  0.82  podobna treść    znaczenie tekstu (e5) 0.36
  syn-01-kardivix       C1     0.00  1.00  brak powiązania  odległa treść (d = 1.00)
  syn-02-kardivix-bis   C1     0.00  1.00  brak powiązania  odległa treść (d = 1.00)
  syn-03-kardivix-news  C1     0.00  1.00  brak powiązania  odległa treść (d = 1.00)
  syn-04-fundusz        C2     0.00  1.00  brak powiązania  odległa treść (d = 1.00)
  syn-05-fundusz-tekst  C2     0.00  1.00  brak powiązania  odległa treść (d = 1.00)
  syn-07-kasyno         C3     0.00  1.00  brak powiązania  odległa treść (d = 1.00)
  syn-08-krypto         C4     0.00  1.00  brak powiązania  odległa treść (d = 1.00)
  Najbliższa para: Brak wspólnego identyfikatora; d = 0.82 > 0.6, ale ≤ 0.93 — podobna treść, osobne kampanie
  (mogą należeć do jednej rodziny). d = 1 − (0.00 + 0.36) / 2 = 0.82

Identyfikatory nowego materiału (W BAZIE = ile z 8 pozostałych materiałów ma tę wartość)
  (brak identyfikatorów)

dostępne widoki treści: tekst kreacji (OCR), znaczenie tekstu (e5)
```

Bez `--dry` materiał zostaje zapisany, a wiersz `zapis:` podaje bazę. Argument, który wygląda jak ścieżka, ale nie
istnieje, jest błędem (kod 5), a nie tekstem do analizy — tak literówka w nazwie pliku nie zamieni się po cichu
w „reklamę”.

**Prywatność i bezpieczeństwo.**

- Bez `--no-llm` tekst materiału może trafić do zewnętrznego modelu językowego (zmienna `FTF_LLM`; `FTF_LLM=none`
  wyłącza go całkowicie), a domeny do publicznych usług RDAP / DNS / crt.sh (wyłącza je `FTF_ENRICH=0`).
- Adres URL jest pobierany z tego komputera, w trzech profilach klienta i opcjonalnie w headless Chromium. Nie kieruj
  polecenia na działające strony oszustów poza odizolowanym środowiskiem — patrz uwaga w README, sekcja „Większy
  zbiór badawczy”. Adresy lokalne i prywatne są odrzucane.

### ingest

```text
python -m ftf ingest [--no-llm] [--force] FOLDER
```

| Opcja | Znaczenie |
|---|---|
| `FOLDER` | folder zbioru; każdy podfolder to jeden przypadek (zapisane strony, HAR, zrzuty, wideo, pliki `.txt`) |
| `--no-llm` | bez modelu językowego |
| `--force` | analizuj ponownie także przypadki, które już są w bazie (domyślnie są pomijane) |

Zapisuje do bazy i tworzy ją, jeśli nie istnieje. Na końcu wypisuje to samo co `campaigns`. Polecenie nie ma `--json`
— po imporcie użyj `python -m ftf campaigns --json`. Przykład jest w sekcji [Pierwsza analiza](#pierwsza-analiza).
Uwagi o prywatności z polecenia `add` dotyczą także importu.

### demo

```text
python -m ftf demo [--force]
```

| Opcja | Znaczenie |
|---|---|
| `--force` | analizuj ponownie także przypadki, które już są w bazie (domyślnie są pomijane) |

Importuje zbiór demonstracyjny dołączony do kodu (`tests/fixtures/synthetic_dataset`): 8 zmyślonych przypadków
w domenach `.example`, które układają się w kampanie, jeden duplikat i jedną rodzinę. To najszybszy sposób, żeby
po instalacji zobaczyć działający panel i polecenia odczytu:

```bash
python -m ftf demo          # kilkanaście sekund, bez sieci
python -m ftf campaigns
python -m ftf serve         # panel: http://127.0.0.1:8765
```

Polecenie działa jak `ingest tests/fixtures/synthetic_dataset --no-llm` z wyłączonymi zapytaniami RDAP / DNS /
crt.sh, niezależnie od `FTF_LLM` i `FTF_ENRICH` — nic nie wychodzi poza ten komputer. Zapisuje do bazy i tworzy ją,
jeśli nie istnieje; nie ma `--json`. Żeby dane demonstracyjne nie mieszały się z własnymi, wskaż osobną bazę:
`python -m ftf --store data/store/demo.sqlite demo`. To samo robi przycisk „Wczytaj zbiór demonstracyjny” w panelu.

### export

```text
python -m ftf export [--json] [--out KATALOG] [--only PLIK]
```

| Opcja | Znaczenie |
|---|---|
| `--out KATALOG` | katalog docelowy (domyślnie `<FTF_ROOT>/data/exports`) |
| `--only PLIK` | tylko ten plik; można powtórzyć: `graph.html`, `graph.cypher`, `campaigns.json`, `links.csv` |

Zapisuje pliki i wypisuje ich ścieżki, po jednej w wierszu. Bazy nie zmienia.

```text
$ python -m ftf export --out /tmp/ftf-eksport
/tmp/ftf-eksport/graph.html
/tmp/ftf-eksport/graph.cypher
/tmp/ftf-eksport/campaigns.json
/tmp/ftf-eksport/links.csv
```

| Plik | Zawartość |
|---|---|
| `graph.html` | interaktywny graf materiałów i powiązań (samodzielna strona) |
| `graph.cypher` | polecenia Cypher do wczytania grafu w Neo4j |
| `campaigns.json` | profile kampanii z nazwami materiałów |
| `links.csv` | pary z relacją inną niż „brak powiązania”: `a, b, p, distance, relation, views, explanation` |

### serve

```text
python -m ftf serve [--host HOST] [--port PORT]
```

| Opcja | Znaczenie |
|---|---|
| `--host HOST` | adres nasłuchu (domyślnie `127.0.0.1`) |
| `--port PORT` | port (domyślnie `8765`) |

Uruchamia panel analityka i API. Panel trzeba wcześniej zbudować (`cd web && npm ci && npm run build`); bez tego
polecenie ostrzega i udostępnia samo API pod `/api`. Zajęty port to kod wyjścia 6 z podpowiedzią — działającego już
panelu polecenie nie rusza. Do samego odczytu panel nie jest potrzebny: polecenia tekstowe czytają bazę bezpośrednio.

### glossary

```text
python -m ftf glossary [--json]
```

Słowniczek: kroki metody, miary (`d`, `p`, `df`), typy identyfikatorów i ich grupy (to są wartości dla
`trace --type`), ślady opisowe, widoki treści, relacje par i decyzje dla nowego materiału, z aktualnymi progami.
Nie wymaga bazy.

```text
$ python -m ftf glossary
Jak powstają kampanie
  1. Wspólne identyfikatory → połączenie pewne. Para materiałów, które mają identyczną wartość identyfikatora
  (domena, piksel / ID analityki, kontakt, plik lub szablon kitu, ID reklamy, nazwa produktu), trafia do
  jednej kampanii (must-link, spójne składowe grafu). Wartość liczy się tylko, gdy występuje w co najwyżej 50%
  materiałów — zbyt popularne wartości są pokazywane, ale pomijane.
  2. Odległość treści (Gower). 7 widoków treści, każdy ze standardową miarą podobieństwa w [0, 1]: tekst
  strony i tekst kreacji (OCR) (MinHash-Jaccard 4-gramów słów), znaczenie tekstu (e5) (cosinus), struktura
  HTML (MinHash-Jaccard znaczników), obrazy (pHash). d = 1 − średnia z widoków dostępnych po obu stronach;
  brakujące widoki są pomijane, więc każdy widok wnosi dokładnie s/k.
  3. Grupowanie hierarchiczne. D = 0 wewnątrz składowej must-link, w przeciwnym razie D = d. Grupowanie
  aglomeracyjne ze średnim wiązaniem (UPGMA): kampanie = cięcie dendrogramu na wysokości 0.6, rodziny = cięcie
  na 0.93. HDBSCAN na tym samym D jako punkt odniesienia.
  4. Nowy materiał (zbiór otwarty). Wspólny identyfikator z jedną kampanią → znana kampania; z dwiema lub
  więcej → propozycja scalenia. W przeciwnym razie najbliższy znany materiał (1-NN): d ≤ 0.6 → jego kampania,
  inaczej nowy wzorzec (z najbliższym materiałem; przy d ≤ 0.93 także podobna rodzina). Grupowanie pyta „które
  materiały tworzą grupę”, przypisanie — „czy to wariant znanego materiału”, stąd najbliższy sąsiad. Duplikat:
  ten sam plik, to samo ID reklamy lub d ≤ 0.05.
  5. Cechy opisowe. Osoby (ArcFace + gazetteer), typ oszustwa, słowa kluczowe, kwoty, rejestrator / data
  utworzenia / NS / IP / lista CERT Polska, reklamodawca, podszyte medium i marki — wyświetlane analitykowi,
  nigdy nie łączą.

Miary
  d:  odległość treści (Gower) — 1 − średnia podobieństw w widokach dostępnych po obu stronach; 1 = nic
      wspólnego albo nic do porównania
  p:  bliskość — 1 − D; równa 1 przy wspólnym identyfikatorze, inaczej 1 − d
  df: częstość dokumentowa — w ilu materiałach bazy występuje wartość; identyfikator łączy, gdy df/N ≤ 50%
      (albo mają go tylko dwa porównywane materiały)

Identyfikatory — wspólna wartość łączy materiały (typ podajesz w `trace --type`)
  GRUPA                   TYP              ZNACZENIE
  biblioteka reklam       ad_id            ID reklamy
  biblioteka reklam       advertiser_id    ID reklamodawcy
…
```

## JSON

Każde polecenie odczytu przyjmuje `--json`. Zasady:

- wynik to zawsze **jeden obiekt JSON** na stdout (UTF-8, wcięcia 2 spacje); postęp i błędy idą na stderr,
- klucze są angielskie i stałe; teksty przeznaczone dla człowieka mają osobne klucze z przyrostkiem `_label` / `_hint`,
- wartości nie są skracane, a brak wartości to `null`,
- w razie błędu stdout jest pusty, a kod wyjścia niezerowy (wyjątek: `status --json` wypisuje obiekt także wtedy, gdy
  bazy nie ma — z `"store_exists": false` — i kończy się kodem 3),
- kampania jest wszędzie tym samym obiektem `{id, code, name, size}`: `code` to kod z tabel (`C1`), a `id` to
  indeks liczony od zera (`code` = `C` + (`id` + 1)).

### Klucze najwyższego poziomu

| Polecenie | Klucze |
|---|---|
| `status` | `version`, `store`, `store_exists`, `root`, `n_materials`, `n_campaigns`, `web_ui_built`; gdy baza istnieje także: `store_size_bytes`, `n_multi`, `n_singletons`, `n_in_multi`, `n_duplicate_groups`, `n_families_multi`, `n_pairs`, `links` `{duplicate, same_campaign, similar, none}`, `by_source` `{źródło: liczba}`, `last_added`, `llm_backend`, `llm_available`, `neo4j`, `thresholds`, `recent` |
| `campaigns` | `n_materials`, `n_campaigns`, `n_multi`, `n_singletons`, `campaigns` [kampania z profilem], `duplicates` [[`{id, name}`]], `families` [`{id, campaigns, size, refs}`], `links`, `thresholds` |
| `campaign` | profil kampanii (`id`, `code`, `name`, `size`, `members` [materiał], `scam_types`, `products`, `persons`, `domains`, `date_range`, `mean_internal_p`, `n_shared`, `n_shared_kinds`, `top_shared`, `family`) oraz `matrix` [`{type, type_label, group, group_label, linking, members, values}`], `chain` [`{a, b, a_name, b_name, p, distance, relation, basis, reasons}`], `links` [para], `n_pairs`, `nearest_outside`, `siblings`, `titles`, `view_profile` [`{view, label, inside, outside, n_inside, n_outside}`], `thresholds` |
| `materials` | `n_total`, `n_matched`, `materials` [materiał] |
| `material` | materiał oraz `source_ref`, `inputs` `{pages, images, videos, urls}`, `features` `{summary, llm_backend, llm_backend_label, llm, text, persons, web, indicators, n_corpus, images, n_assets_total, ocr_links, notes, dates, elapsed_s, views}`, `links` [para z kluczem `other` zamiast `a_info` / `b_info`] |
| `search` | `query`, `materials` [materiał + `hits`], `campaigns`, `traces` [`{type, type_label, value, display, n}`] |
| `links` | `min_p`, `n_matched`, `links` [para] |
| `pair` | `a`, `b` (materiały), `p`, `distance`, `relation`, `relation_label`, `relation_hint`, `rule`, `basis`, `comparable`, `must_link`, `identifiers` [`{group, label, hint, items}`], `ignored`, `views` [`{view, label, hint, available, score, contribution, note}`], `n_views`, `formula`, `evidence` |
| `trace` | `query`, `type`, `traces` [`{type, type_label, value, display, group, group_label, linking, counted, df, n, max_df, materials}`] |
| `matrix` | `materials` [`{id, name, campaign}`], `p`, `distance`, `relation` (macierze kwadratowe w kolejności `materials`; przekątna `null`), `thresholds` |
| `metrics` | `n_materials`, `n_campaigns`, `n_multi`, `n_singletons`, `n_pairs`, `n_must_link`, `thresholds`, `methods` [`{key, label, hint, n_clusters, n_singletons, n_noise, silhouette, ari_fakeralpha, ari_labels, clusters, noise}`], `labels`, `distance_histogram`, `signal_attribution`, `view_summary`, `feature_coverage`, `scam_types`, `top_persons`, `merge_heights`, `projections` `{mds, tsne}`, `dendrogram` |
| `eval` | `n`, `pairwise_precision`, `pairwise_recall`, `pairwise_f1`, `bcubed_precision`, `bcubed_recall`, `ARI`, `ARI_hdbscan_baseline` |
| `add` | `decision`, `decision_label`, `decision_hint`, `campaign`, `similar_family`, `nearest` `{id, code, name, size, distance, material_id, material_name}`, `closest`, `scores` [`{score, distance, id, code, name, size}`], `links` [`{p, distance, relation, relation_label, evidence, other, explain}`], `kept`, `material_id`, `name`, `input` `{mode, source, use_llm, keep, render}`, `features`, `thresholds` |
| `export` | `directory`, `files` [`{kind, path, bytes}`] |
| `glossary` | `steps`, `measures`, `identifier_groups` [`{group, label, hint, types}`], `descriptive_types`, `views`, `relations`, `decisions`, `constants` `{max_df, duplicate_cut, campaign_cut, family_cut, phash_hamming}` |

### Obiekty powtarzające się w wynikach

**Materiał** — `id`, `name`, `display_name`, `title`, `source`, `source_label`, `created_at`, `campaign`
`{id, code, name, size}`, `scam_type`, `scam_type_label`, `product`, `persons`, `domains`, `counts`
`{pages, images, videos}`, `signals` `{has_web, has_infra, has_faces, has_ocr, has_llm, has_images, n_indicators,
n_linking_indicators, n_faces, n_domains}`.

**Para** — `a`, `b` (identyfikatory materiałów), `a_info`, `b_info` (`{id, name, campaign}`), `p`, `distance`,
`relation` (`duplicate` | `same_campaign` | `similar` | `none`), `relation_label`, `comparable`, `reasons`
[`{detail, weight, kind, key}`], `evidence` [`{kind, key, label, type, type_label, value, df, ignored}`].

**Progi** (`thresholds`) — `duplicate_cut`, `campaign_cut`, `family_cut` to progi odległości `d`; `duplicate`, `link`,
`similar` to te same progi wyrażone jako bliskość `p`; `max_df` to największy udział materiałów, przy którym
identyfikator jeszcze łączy.

Wyniki pochodzą z tych samych funkcji co odpowiedzi API panelu; CLI usuwa z nich tylko pola potrzebne wyłącznie
interfejsowi WWW (miniatury, kolory) i zamienia adresy plików panelu na zwykłe ścieżki (`path`).

### Przykłady

```text
$ python -m ftf status --json
{
  "version": "0.1.0",
  "store": "data/store/demo_syntetyczne.sqlite",
  "store_exists": true,
  "root": "/ścieżka/do/follow-the-fake",
  "n_materials": 8,
  "n_campaigns": 5,
  "web_ui_built": true,
  "store_size_bytes": 98304,
  "n_multi": 2,
  "n_singletons": 3,
  "n_in_multi": 5,
  "n_duplicate_groups": 1,
  "n_families_multi": 1,
  "n_pairs": 28,
  "links": {
    "duplicate": 1,
    "same_campaign": 3,
    "similar": 2,
    "none": 22
  },
  "by_source": {
    "organizer": 8
  },
  "last_added": "2026-11-22T03:08:53+00:00",
  "llm_backend": "none",
  "llm_available": {
    "claude_cli": true,
    "gemini": false
  },
  "neo4j": false,
  "thresholds": {
    "duplicate_cut": 0.05,
    "campaign_cut": 0.6,
    "family_cut": 0.93,
    "max_df": 0.5
  },
  "recent": []
}
```

```text
$ python -m ftf eval tests/fixtures/synthetic_labels.csv --json
{
  "n": 8,
  "pairwise_precision": 1.0,
  "pairwise_recall": 1.0,
  "pairwise_f1": 1.0,
  "bcubed_precision": 1.0,
  "bcubed_recall": 1.0,
  "ARI": 1.0,
  "ARI_hdbscan_baseline": 0.323
}
```

```text
$ python -m ftf export --out /tmp/ftf-eksport --only links.csv --json
{
  "directory": "/tmp/ftf-eksport",
  "files": [
    {
      "kind": "links.csv",
      "path": "/tmp/ftf-eksport/links.csv",
      "bytes": 1678
    }
  ]
}
```

Typowe użycie z `jq` (wyniki z tej samej bazy syntetycznej):

```console
$ python -m ftf campaigns --json | jq -r '.campaigns[] | [.code, .size, .name] | @tsv'
C1	3	„cudowny” produkt zdrowotny
C2	2	fałszywa platforma inwestycyjna
C3	1	nielegalny hazard
C4	1	fałszywa platforma inwestycyjna
C5	1	fałszywa ankieta / rozdanie

$ python -m ftf links --json | jq -r '.links[] | [.a_info.name, .b_info.name, .p, .relation] | @tsv'
syn-01-kardivix	syn-02-kardivix-bis	1.0	duplicate
syn-01-kardivix	syn-03-kardivix-news	1.0	same_campaign
syn-02-kardivix-bis	syn-03-kardivix-news	1.0	same_campaign
syn-04-fundusz	syn-05-fundusz-tekst	0.462	same_campaign
syn-05-fundusz-tekst	syn-06-loteria	0.163	similar
syn-06-loteria	syn-07-kasyno	0.149	similar

$ python -m ftf trace 900000000000001 --json | jq -r '.traces[].materials[].name'
syn-01-kardivix
syn-02-kardivix-bis
syn-03-kardivix-news

$ python -m ftf add "Kardivix — kapsułki na serce, tylko dziś -50%" --dry --no-llm -q --json \
    | jq '{decision, campaign: .campaign.code, nearest: .nearest.material_name, d: .nearest.distance}'
{
  "decision": "new_campaign",
  "campaign": null,
  "nearest": "syn-01-kardivix",
  "d": 0.786
}
```

## Kody wyjścia

| Kod | Znaczenie | Przykład |
|---|---|---|
| 0 | powodzenie | |
| 1 | błąd nieoczekiwany (wewnętrzny); `-v` pokazuje ślad stosu | |
| 2 | złe wywołanie: nieznane polecenie, brak argumentu, zła wartość opcji; także wywołanie bez polecenia | `python -m ftf links --min x` |
| 3 | brak bazy, pusta baza albo plik, który nie jest bazą FakerAlpha | `python -m ftf --store brak.sqlite campaigns` |
| 4 | nie ma takiego materiału, kampanii lub śladu; niejednoznaczne wskazanie materiału | `python -m ftf campaign C9` |
| 5 | złe dane wejściowe: brak pliku lub folderu, pusty plik, odrzucony adres URL, etykiety bez dopasowań | `python -m ftf add ./nie-ma.png --dry` |
| 6 | środowisko: zajęty port, brak pakietu potrzebnego do `serve` | `python -m ftf serve --port 8765`, gdy panel już działa |
| 130 | przerwano (Ctrl+C) | |

Błędy użytkownika nigdy nie kończą się śladem stosu. Komunikat ma zawsze tę samą postać: wiersz `błąd: …` i wcięte
wiersze z tym, co zrobić:

```text
$ python -m ftf campaign C9
błąd: nie ma kampanii C9
  w tej bazie są kampanie C1…C5; numeracja zmienia się po dodaniu materiałów — zobacz `python -m ftf campaigns`
```

Pomyłka w nazwie polecenia dostaje podpowiedź:

```console
$ python -m ftf campains
Użycie: python -m ftf [opcje wspólne] <polecenie> [argumenty]
błąd: nieznane polecenie „campains”
  czy chodziło o: campaigns, campaign?
  polecenia: status, campaigns, campaign, materials, material, search, links, pair, trace, matrix, metrics, eval, add, analyse, ingest, export, serve, glossary
  pomoc: python -m ftf --help
```

## Zmienne środowiskowe

| Zmienna | Domyślnie | Znaczenie |
|---|---|---|
| `FTF_STORE` | `<FTF_ROOT>/data/store/ftf.sqlite` | plik bazy materiałów; opcja `--store` ma pierwszeństwo |
| `FTF_ROOT` | katalog repozytorium | katalog, w którym leży `data/` (baza, pliki robocze, eksport) i `web/dist` |
| `FTF_LLM` | `auto` | model językowy dla cech opisowych: `auto`, `claude_cli`, `gemini`, `none`. `none` = nic nie jest wysyłane; to samo dla pojedynczego wywołania daje `--no-llm` |
| `FTF_LLM_MODEL`, `FTF_LLM_TIMEOUT` | `haiku`, `120` | model i limit czasu (s) dla `FTF_LLM` |
| `GEMINI_API_KEY` | — | klucz dla `FTF_LLM=gemini` |
| `FTF_ENRICH` | `1` | `0` wyłącza zapytania o domeny do RDAP / DNS / crt.sh podczas `add` i `ingest` |
| `FTF_LOCAL_MATCH`, `FTF_OCR_CHARS` | `1`, `0` | przełączniki eksperymentalne widoków „obrazy” i „tekst kreacji”; zmieniają wyniki porównań |
| `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` | — | połączenie z Neo4j używane przez panel; `status` pokazuje, czy jest skonfigurowane |
| `NO_COLOR` | — | dowolna niepusta wartość wyłącza kolor |
| `COLUMNS` | — | szerokość tabel, gdy wyjście nie jest terminalem (bez niej 140) |

`FTF_STORE`, `FTF_ROOT` i `FTF_LLM*` są odczytywane przy starcie procesu.

W Dockerze `docker-compose.yml` przekazuje do kontenera `FTF_STORE`, `FTF_LLM`, `FTF_ENRICH`, `GEMINI_API_KEY`
i `META_ACCESS_TOKEN`. Ustawia się je przy starcie, np. `FTF_STORE=data/store/test.sqlite docker compose up -d`.
Polecenia `docker compose exec` dziedziczą te wartości. Dodatkowo `FTF_PORT` wybiera port panelu na komputerze
(domyślnie 8765).

## Co polecenia zapisują na dysku

| Polecenie | Co i gdzie |
|---|---|
| polecenia odczytu, `add --dry` | nic w bazie (plik otwierany tylko do odczytu; SQLite może przy tym odświeżyć swój pomocniczy plik `<baza>-shm`, sam plik bazy się nie zmienia). `add --dry` obrazu, wideo lub adresu URL może zostawić pliki robocze w `data/artifacts` i `data/cache` |
| `add` | materiał w bazie; dla pliku także kopia robocza w `data/uploads/<skrót>/` |
| `ingest`, `demo` | materiały w bazie, pliki robocze w `data/artifacts` i `data/cache` |
| `export` | pliki eksportu w `data/exports` albo w `--out` |
| `serve` | to, co zapisze panel: materiały dodane na stronie „Analizuj materiał” i zaimportowane zbiory |

Niezależnie od polecenia samo uruchomienie tworzy puste katalogi `data/cache`, `data/artifacts` i `data/exports`
w `FTF_ROOT` oraz katalog nadrzędny pliku wskazanego przez `FTF_STORE`, jeśli jeszcze nie istnieją (pliku bazy —
nie). Przy `--store` katalog nie jest tworzony.

## Zgodność ze starszymi wywołaniami

Wywołania sprzed rozbudowy CLI działają bez zmian, z tymi samymi flagami:

```bash
python -m ftf.cli ingest <folder> [--no-llm] [--force]
python -m ftf.cli add <cel> [--no-llm] [--dry]
python -m ftf.cli campaigns
python -m ftf.cli links [--min 0.1]
python -m ftf.cli export
python -m ftf.cli eval <etykiety.csv>
python -m ftf.cli serve [--host 127.0.0.1] [--port 8765]
```

Zmieniła się tylko postać wyniku: tabele zamiast surowych wierszy, a `eval` wypisuje tabelę zamiast słownika JSON —
dawny słownik (te same klucze) daje `eval --json`.

## Czego w CLI nie ma

- **Skaner źródeł, wyszukiwanie w bibliotekach reklam i obserwacja kampanii** (lista CERT Polska, biblioteki
  reklam) mają własne polecenie: `python -m ftf.scheduler --once [--analyse] [--watch]`. Wymagają sieci i pobierają
  materiały z zewnątrz, dlatego nie są częścią poleceń analitycznych.
- **Rysunki**: mapa przestrzeni cech, dendrogram i graf. CLI podaje dane, z których powstają (`metrics --json`:
  `projections`, `dendrogram`), a graf zapisuje `export` jako `graph.html`.
- **Miniatury i podgląd materiału** — `material --json` podaje ścieżki plików.
- **Wysyłka grafu do działającego Neo4j** jest tylko w panelu; `export` zapisuje `graph.cypher` do ręcznego
  wczytania.
