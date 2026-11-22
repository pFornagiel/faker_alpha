# FakerAlpha: funkcje i przebieg pozyskiwania danych

Krótki opis tego, co narzędzie robi i jak zbiera dane. Instalacja jest w [README.md](README.md).
Szczegóły metody są w [docs/METHODOLOGY.md](docs/METHODOLOGY.md).

## 1. Pojęcia

| Pojęcie | Znaczenie |
|---|---|
| materiał | jeden przypadek: reklama, strona, zrzut ekranu, wideo albo tekst |
| identyfikator | dokładna wartość, której operator używa ponownie, np. domena, piksel Facebooka, numer telefonu |
| widok treści | jeden sposób porównania treści dwóch materiałów, z wynikiem od 0 do 1 |
| kampania | grupa materiałów, za którą najpewniej stoi ten sam operator |
| rodzina | grupa kampanii o podobnej treści, bez wspólnego śladu operatora |

## 2. Funkcje

### 2.1 Panel analityka

| Strona | Co pokazuje |
|---|---|
| Kampanie | liczby ogólne i karty kampanii z najmocniejszymi wspólnymi śladami |
| Kampania | materiały kampanii, ślady łączące materiały i najbliższe materiały spoza kampanii |
| Przestrzeń cech | materiały na płaszczyźnie i porównanie metod grupowania |
| Graf | sieć kampanii i materiałów, kliknięcie krawędzi pokazuje dowody |
| Macierz | mapa cieplna bliskości wszystkich par |
| Materiały | lista z wyszukiwarką i strona każdego materiału z wyciągniętymi cechami |
| Para, Ślad | dlaczego dwa materiały są powiązane i które materiały mają daną wartość |
| Analizuj materiał | analiza nowego materiału i import całego zbioru |
| Słowniczek, Odrzucone cechy | pojęcia oraz cechy, które sprawdziliśmy i odrzuciliśmy, z powodem |

Wyszukiwarka w nagłówku (`/` lub `Ctrl+K`) znajduje domeny, identyfikatory, osoby, produkty i kampanie.

### 2.2 Analiza nowego materiału

Materiałem może być adres URL, plik (zrzut, wideo, zapisana strona, HAR, MHTML, ZIP z folderem przypadku) albo
tekst. Wynikiem jest jedna z czterech decyzji:

| Decyzja | Kiedy |
|---|---|
| duplikat | ten sam plik, ten sam identyfikator reklamy albo prawie identyczna treść |
| znana kampania | wspólny identyfikator z jedną kampanią albo treść bliska znanemu materiałowi |
| propozycja scalenia | wspólne identyfikatory z dwiema lub więcej kampaniami |
| nowy wzorzec | brak wspólnego identyfikatora i brak dość bliskiego materiału |

Każda decyzja ma dowody: wspólne wartości, podobieństwo w każdym widoku i najbliższe materiały. Analiza może
działać bez zapisu w bazie.

### 2.3 Import zbioru

Folder, w którym każdy podfolder to jeden przypadek, wczytuje się w panelu albo poleceniem `ftf ingest`. Przypadki
już obecne w bazie są pomijane. Zbiór demonstracyjny (8 zmyślonych przypadków) wczytuje się jednym przyciskiem.

### 2.4 Skaner źródeł

Skaner przegląda publiczne źródła i szuka nowych podejrzanych reklam. Działa z wiersza poleceń
(`python -m ftf.scheduler`), jednorazowo albo cyklicznie.

1. Pobiera nowe pozycje z listy ostrzeżeń CERT Polska i z bibliotek reklam.
2. Ocenia każdą pozycję prostym wynikiem podejrzliwości: podszycie pod osobę lub markę, słownictwo oszustw,
   ryzykowna domena najwyższego poziomu, obecność na liście CERT Polska.
3. Z opcją `--analyse` przechwytuje najbardziej podejrzane pozycje i analizuje je jak nowy materiał.

Tryb obserwacji kampanii (`--watch`) szuka nowych materiałów znanych kampanii. Jako zapytań używa identyfikatorów tych kampanii:
domen, identyfikatorów reklamodawców i nazw produktów. Trafienie jest tylko tropem. Do kampanii trafia dopiero wtedy,
gdy zwykła analiza przypisze je do tej kampanii.

### 2.5 CLI i eksport

Wszystko, co pokazuje panel, jest dostępne w terminalu (`python -m ftf`), jako tabele albo JSON. Polecenie `export`
zapisuje interaktywny graf (`graph.html`), polecenia Cypher dla Neo4j, profile kampanii (`campaigns.json`) i pary
z uzasadnieniem (`links.csv`). Opis poleceń: [docs/CLI.md](docs/CLI.md).

## 3. Przebieg pozyskiwania danych

```text
folder przypadku, plik, ZIP, tekst ─────> rozpoznanie plików ──┐
adres URL ─────────────────────────────> przechwycenie ────────┼──> materiał ──> ekstrakcja cech ──> porównanie z bazą
CERT Polska, biblioteki reklam ──> skaner ──> przechwycenie ───┘                                    (kampania albo nowy wzorzec)
```

### 3.1 Przechwycenie adresu URL

1. **Kontrola adresu.** Dozwolone są tylko publiczne adresy `http` i `https`. Adresy prywatne, lokalne i metadane
   chmury są odrzucane (ochrona przed SSRF). Ta sama kontrola obejmuje każde przekierowanie.
2. **Trzy profile klienta.** Ten sam adres jest pobierany trzy razy: jako robot, jako polska przeglądarka na
   komputerze i jako telefon z aplikacją Facebooka (z nagłówkiem `Referer` z Facebooka i parametrem `fbclid`).
   Każdy profil przechodzi łańcuch przekierowań: HTTP 3xx, `meta refresh` i krótkie przekierowania w JavaScript,
   najwyżej 12 kroków. Odpowiedź jest ograniczona do 3 MB.
3. **Ocena cloakingu.** Strony z trzech profili są porównywane po domenie docelowej, tytule, tekście i strukturze
   HTML. Werdykt jest jednym z pięciu:

   | Werdykt | Znaczenie |
   |---|---|
   | podejrzenie cloakingu | profile trafiły na różne domeny albo dostały zupełnie inną treść |
   | blokada robota | robot dostał błąd 403, 429 lub 503, przeglądarki dostały stronę |
   | wariant mobilny | ta sama strona w innym układzie |
   | brak | wszystkie profile widziały to samo |
   | niedostępna | żaden profil nie dostał strony |

4. **Render w przeglądarce** (opcjonalnie). Headless Chromium w polskim, mobilnym kontekście zapisuje HAR, zrzut
   ekranu i wyrenderowany HTML. Każde zapytanie strony przechodzi tę samą kontrolę adresu. Pobieranie plików
   i service workery są zablokowane.
5. **Zapis.** Wyniki trafiają do `data/artifacts/captures/` razem z plikiem `capture_manifest.json`. Analizę można
   powtórzyć także wtedy, gdy strona już nie działa.

Ograniczenie: cloaking, który wpuszcza tylko polskie mobilne adresy IP albo jednorazowe tokeny kliknięcia, pokazuje
wszystkim trzem profilom stronę zastępczą. Wtedy łączą głównie identyfikatory infrastruktury.

### 3.2 Rozpoznanie plików

Pliki w folderze przypadku są rozpoznawane po rozszerzeniu i zawartości:

* zapisane strony HTML i MHTML, z adresem z nagłówka `saved from url` lub z nagłówka MHTML,
* zapisy ruchu HAR, z wyborem właściwej strony docelowej i usunięciem identyfikatorów sesji,
* zrzuty, grafiki i wideo,
* pliki `.txt` z tekstem reklamy, a pliki o nazwach z `usuni`, `deleted` lub `removed` jako notatka o usuniętym materiale,
* metadane JSON z `yt-dlp`, z przechwycenia i z archiwizatora (DNS, certyfikat TLS),
* zasoby zapisane przez polskiego Chrome (`.pobrane`, `.pobierz`) rozpoznawane po zawartości.

Archiwa ZIP są rozpakowywane bezpiecznie: bez ścieżek wychodzących poza katalog, bez dowiązań symbolicznych,
najwyżej 500 plików, 50 MB na plik i 250 MB razem.

### 3.3 Ekstrakcja cech

| Etap | Co powstaje |
|---|---|
| 1. strona | identyfikatory z adresów, HTML, HAR i skryptów: domeny, piksele i identyfikatory analityki, kontakty, skróty skryptów, szablony ścieżek API, struktura HTML |
| 2. obraz i twarze | klatki wideo (bez czarnych klatek), wycięcie kreacji ze zrzutu, OCR, kody QR, pHash obrazów, twarze porównane z bazą 29 osób |
| 3. tekst | tekst strony i kreacji z zamaskowanymi nazwiskami (MinHash), wektor znaczenia (e5), słowa kluczowe, kwoty |
| 4. atrybuty opisowe | typ oszustwa, podszyte osoby, marki i media, nazwa produktu (model językowy albo reguły słownikowe) |
| 5. OSINT domen | rejestrator, data utworzenia, serwery NS, adresy IP, certyfikaty, obecność na liście CERT Polska |
| 6. złożenie | identyfikatory, widoki treści i opis zapisane w bazie |

Etap 5 korzysta z RDAP, DNS, crt.sh i listy CERT Polska. Pełne odpowiedzi są przechowywane 7 dni, a niepełne
15 minut. `FTF_ENRICH=0` wyłącza ten etap. `FTF_LLM=none` albo `--no-llm` wyłącza model językowy w etapie 4.

### 3.4 Źródła zewnętrzne

| Źródło | Dostęp | Stan |
|---|---|---|
| lista ostrzeżeń CERT Polska | publiczny | działa |
| Microsoft Ad Library | bez klucza | działa |
| Meta Ad Library | token `META_ACCESS_TOKEN` | działa z tokenem |
| kreacje Meta przez `yt-dlp` | publiczny, po identyfikatorze reklamy | działa, dopóki reklama istnieje |
| Google Ads Transparency Center | bez klucza | często blokuje automatyczne zapytania (429) |
| LinkedIn Ad Library | bez klucza | blokuje zapytania (403) |
| RDAP, DNS | publiczny | działa |
| crt.sh | publiczny | działa z przerwami |

Stan każdego źródła jest zapisywany przy każdym wywołaniu, więc awaria źródła jest widoczna.

## 4. Łączenie materiałów

1. **Wspólny identyfikator łączy dwa materiały.** Wartość liczy się tylko wtedy, gdy ma ją najwyżej połowa
   materiałów w bazie. Zbyt popularne wartości są pokazywane, ale nie łączą.
2. **Treść porównuje siedem widoków:** tekst strony, tekst kreacji (OCR), znaczenie tekstu, struktura HTML, nazwy
   klas CSS, własne skrypty i obrazy. Odległość `d` to 1 minus średnie podobieństwo w widokach dostępnych po obu
   stronach.
3. **Grupowanie** to średnie wiązanie na tych odległościach. Cięcie dendrogramu na 0,6 daje kampanie, a na 0,93
   rodziny. Pary z `d` ≤ 0,05 są duplikatami.
4. **Nowy materiał** trafia do kampanii przez wspólny identyfikator albo przez najbliższy znany materiał, gdy
   `d` ≤ 0,6. W przeciwnym razie jest nowym wzorcem.

Osoby, typ oszustwa, rejestrator, słowa kluczowe i kwoty są tylko opisem. Nie łączą materiałów, bo te same wartości
pojawiają się w różnych kampaniach.

## 5. Dalsza lektura

| Dokument | Temat |
|---|---|
| [docs/METHODOLOGY.md](docs/METHODOLOGY.md) | metoda łączenia, ewaluacja i ograniczenia |
| [docs/WEB_FETCHING_METHODOLOGY.md](docs/WEB_FETCHING_METHODOLOGY.md) | pozyskiwanie, cloaking i OSINT, szczegóły techniczne (EN) |
| [docs/PIPELINE_WALKTHROUGH.md](docs/PIPELINE_WALKTHROUGH.md) | przebieg analizy krok po kroku (EN) |
| [docs/CLI.md](docs/CLI.md) | wszystkie polecenia terminala |
