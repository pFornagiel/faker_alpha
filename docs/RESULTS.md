# Wyniki na zbiorze przykładowym organizatora (DANE.zip, 10 przypadków)

Reprodukcja: `python -m ftf.cli ingest data/organizer/dane` → `python tools/evaluate.py --labels data/labels_dane.csv --no-llm`
(raport: `data/eval/report.json`; liczby poniżej z przebiegu 2026-11-21 na cechach zapisanych w `data/store/ftf.sqlite`). CPU laptop (i5-8365U, bez GPU), ~1–3 min / przypadek (OCR + twarze + e5 + LLM Haiku).
Metoda: [`METHODOLOGY.md`](METHODOLOGY.md).

## Wykryte kampanie

| Kampania | Przypadki | Przesłanki powiązania (identyfikatory → must-link; widoki treści) |
|---|---|---|
| **C1** — operator fałszywych artykułów „Gazeta.pl/TVN24” → fikcyjne platformy inwestycyjne | 1, 2, 3, 48, 61 | **1↔2**: `tracking_ids` — ten sam Facebook Pixel `2012165449475163` i 2 `tenant_uuid` landing-buildera · **2↔3**: `domains` — ta sama domena docelowa `healthlinkq.pro` · **3↔48**: `product` — ta sama fikcyjna platforma „Orzeł Fundaris” · **1/2/48/61**: `kit_files` — ten sam szablon API backendu `POST /api/v1/trigger/field/{id}/` (w 4 z 10 materiałów, ≤ `MAX_DF`). Treść 48↔61 jest tylko częściowo podobna (d ≈ 0,77: HTML 0,35, obrazy 0,30, e5 0,44) — łączy je identyfikator, nie treść. Para 1↔2 to duplikat (d = 0,025: ta sama strona zgłoszona dwa razy). Rotujące nazwy platform: „Świtowin Zyskarnia”, „Orzeł Fundaris”, „Trwały Działunek”, „Polska Platforma Aktywnego Oszczędzania Emerytalnego”. |
| C2 | 47 (Uromexil Forte) | singleton |
| C3 | 5 (wideo z Biblioteki Reklam Meta, „lekarz” n. med. Jarosław Czubak) | singleton |
| C4 | 36 (Poland Invest Summit 2026) | singleton |
| C5 | 14 (Metabo RX, reklamodawca „Sustain Studio”) | singleton |
| C6 | 10 (Sweet Bonanza – kasyno, deepfake Ronaldo) | singleton |

Przy tych przesłankach C1 tworzy jedną składową must-link (łańcuch 1–2–3–48 przez piksel, domenę i produkt, 61
przez szablon API), więc nie zależy od progu `CAMPAIGN_CUT`. Osoby (Brzoska, Olejnik)
i typ oszustwa są wyświetlane, ale nie łączą — ci sami celebryci i ten sam `scam_type` występują też poza C1.

Etykiety referencyjne (`data/labels_dane.csv`) zostały ustalone przez nas ręczną weryfikacją faktów w surowych
plikach (ten sam piksel w HTML 1 i 2, `healthlinkq.pro` w HAR 2 i HTML 3, „Orzeł Fundaris” w 3 i 48, ten sam
artykuł w 48 i 61) — **nie są to etykiety organizatora**.

## Metryki

| Test | Wynik |
|---|---|
| Etykiety (10 materiałów): pairwise P / R / F1 | 1,00 / 1,00 / 1,00 |
| Etykiety: B-cubed P / R | 1,00 / 1,00 |
| Etykiety: ARI | **1,00** |
| Baseline HDBSCAN na tej samej macierzy `D`: ARI | 0,68 (łączy singletony 10, 14, 36, 47 w jeden klaster, 5 jako szum) |
| Leave-one-out (usuń materiał → `cluster.assign`) | **10/10** (5/5 wraca do C1 — 2× `duplicate`, 3× `known_campaign`; 5/5 singletonów → `new_campaign`) |
| Warianty: tylko kreacja (strona martwa) | **8/8** (7× `duplicate` przez identyczny zrzut, 47 → `known_campaign` przez widok `ocr`, d = 0,59) |
| Warianty: tylko strona (brak kreacji) | **8/8** (wszystkie `duplicate`, d ≤ 0,06) |
| Warianty: podmieniona domena + usunięte ID w URL | **9/9** (d do źródła 0,01–0,07) |
| Warianty: podmienione nazwisko celebryty w tekście | **5/5** (d 0,03–0,15 dzięki maskowaniu osób) |
| Warianty: zrzut przycięty o 8 %, zmniejszony ×0,6, JPEG q = 55 | **1/7** (tylko 10; zob. niżej) |

Ocena wariantu: decyzja `known_campaign` lub `duplicate` **i** właściwa kampania. Uruchomione z `--no-llm`
(LLM tylko dla `product`, który w wariantach nie był potrzebny).

### Stabilność progów (cięcie dendrogramu, ARI względem etykiet)

| Cięcie | ARI | Grupy wielomateriałowe |
|---|---|---|
| 0,05 – 0,90 | 1,00 | {1, 2, 3, 48, 61} |
| 0,92 – 0,95 | 0,94 | + {14, 47} |
| 0,97 | 0,88 | + {10, 36} |
| 0,99 | 0,68 | {10, 14, 36, 47} |
| 1,00 | 0,00 | wszystko |

Wysokości scaleń dendrogramu: 0 (×4, must-link w C1), 0,913, 0,957, 0,982, 0,997, 1,0.

* **Kampanie**: `CAMPAIGN_CUT` = 0,6 leży w szerokim przedziale [0,05; 0,90] o identycznym wyniku. C1 jest jedną
  składową must-link (1–2 piksel/UUID/produkt, 2–3 domena, 3–48 produkt, 1/2/48/61 szablon API), więc **nie zależy od
  `CAMPAIGN_CUT`**; pozostałe materiały nie mają z nikim d ≤ 0,90.
* **Rodziny przy `FAMILY_CUT` = 0,93**: łączy się tylko **C5 (14, Metabo RX) + C2 (47, Uromexil Forte)** — dwa
  „cudowne” produkty zdrowotne, podobne znaczeniowo (e5 0,39), bez wspólnego identyfikatora (d = 0,913). Następne
  scalenie (10 kasyno + 36 „Poland Invest Summit”, 0,957) łączyłoby niepowiązane tematy, więc próg leży poniżej.
  Margines jest wąski (0,913 vs 0,957) — to wybór na 10 materiałach, nie wartość dopasowana.
* Po dodaniu widoku `ocr` (który dla tej pary wynosi 0) odległość 14↔47 wzrosła z 0,892 do 0,913, dlatego
  `FAMILY_CUT` podnieśliśmy z 0,90 do 0,93; przy 0,90 żadna rodzina nie łączyłaby kampanii.

### Zmiana względem pierwszej wersji uproszczonej metody

| Wariant | Średnia do kampanii, jeden widok tekstu | 1-NN + osobny widok `ocr` |
|---|---|---|
| tylko kreacja | 7/8 | **8/8** |
| tylko strona | 8/8 | 8/8 |
| podmieniona domena | 7/9 | **9/9** |
| podmienione nazwisko | 5/5 | 5/5 |
| przycięty zrzut | 1/7 | 1/7 |

* **Podmieniona domena 1 i 2**: wariant był niemal kopią źródła (d ≈ 0,07), ale **średnia** odległość do całej C1
  wynosiła ≈ 0,62 > `CAMPAIGN_CUT`, bo C1 spajają identyfikatory, a treść jej materiałów jest różna. Przypisanie przez
  najbliższego sąsiada (1-NN, Cover & Hart 1967) odpowiada na właściwe pytanie — „czy to wariant znanego
  materiału?” — i daje `known_campaign`.
* **Tylko kreacja 47**: zapisane pHashe klatek wideo 47 pochodzą ze starszej wersji przetwarzania i nie pasują do
  świeżo policzonych; wcześniej porównanie OCR kreacji z tekstem strony dawało 0. Osobny widok `ocr` porównuje
  OCR-do-OCR (dla zapisanych materiałów liczony z zapisanego `ocr_text`), co daje d = 0,59 i `known_campaign`.

## Po dodaniu sygnałów struktury strony, reguły językowej i dopasowania obrazów (listopad 2026)

Dodane: widoki `css` i `js`, reguła językowa dla `text` / `ocr`, identyfikator `cert_batch`, dopasowanie obrazów
punktami charakterystycznymi. Opis i pełne tabele: [`research/experiments/integration.md`](../research/experiments/integration.md).
Pomiar bez LLM (`--no-llm`), stary i nowy kod na tej samej maszynie, każdy na świeżej analizie zbioru.

| Test | Przed | Po |
|---|---|---|
| Kampanie, duplikaty, rodziny | 6 kampanii | bez zmian |
| Etykiety: pairwise P / R, ARI | 1,00 / 1,00, 1,00 | 1,00 / 1,00, 1,00 |
| Leave-one-out | 9/10 | 9/10 |
| Warianty: tylko kreacja / tylko strona / domena / nazwisko | 7/8, 8/8, 9/9, 5/5 | bez zmian |
| Warianty: zrzut przycięty o 8 %, zmniejszony ×0,6, JPEG q = 55 | 2/7 | **6/7** |

Korpus badawczy (1 503 strony z listy ostrzeżeń CERT Polska, bez etykiet operatorów; ocena względem wskazań
pośrednich): udział par z co najmniej dwoma niezależnymi wskazaniami, które trafiają do jednej kampanii, wzrósł
z 0,38 do 0,72 przy tym samym odsetku połączeń par uznanych za niepowiązane (0,0022). Liczba stron bez kampanii
spadła z 350 do 209.

## Ograniczenia wyników

* 10 materiałów, w tym 5 singletonów — wyniki pokazują poprawność działania, nie skuteczność na nowych danych.
* C1 opiera się na identyfikatorach; jeden błędny identyfikator scaliłby dwie kampanie (łańcuchowanie must-link).
  Dlatego każda wspólna wartość jest pokazywana z `df/N`.
* Powiązanie 3↔48 zależy od wyekstrahowania nazwy produktu przez LLM.
* Bez embeddingów wizualnych przerysowana kreacja tej samej kampanii nie zostałaby dopasowana po wyglądzie.
* **Przycięty i przekompresowany zrzut (1/7)**: pHash nie jest odporny na przycięcie o 8 % (zmienia się
  dyskretna transformata całego obrazu), więc widok `images` daje 0; OCR zmniejszonego (×0,6) i mocno skompresowanego
  zrzutu jest słabszy, a `text` / `html` są niedostępne (brak strony). Dla 3, 36, 48 d = 1,0, dla 1 i 61 ≈ 0,92,
  dla 14 0,68; przeszedł tylko 10 (d = 0,70 > `CAMPAIGN_CUT`, przypisany przez wspólny identyfikator odczytany z kreacji).
  Naprawa wymaga miary obrazu odpornej na kadrowanie — osobna decyzja.
* **Nieaktualne cechy w bazie**: część zapisanych pHashy (np. klatki wideo 47) pochodzi ze starszej wersji
  przetwarzania; ponowna analiza zbioru (`ftf.cli ingest --force`) by to ujednoliciła. Ewaluację zrobiliśmy celowo
  na zapisanych cechach, bez ponownej analizy.
* **Odstępstwa metody od specyfikacji**: wartość identyfikatora posiadana tylko przez dwa porównywane materiały
  (`df ≤ 2`) zawsze się liczy (inaczej przy N = 2 nic nie mogłoby się połączyć), a identyczny plik (`file_sha`) jest
  traktowany jak wspólny identyfikator (must-link), nie tylko jako duplikat.
