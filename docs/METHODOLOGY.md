# FakerAlpha — metodyka (Kolekcjoner Fejków / Follow the Fake)

> Cel: z pojedynczych podejrzanych reklam wydobyć **wspólne ślady** i połączyć materiały w **kampanie**, pokazując
> dla każdego powiązania **przesłanki**. Nie budujemy detektora pojedynczej fałszywej reklamy — budujemy metodę łączenia.
>
> Dokumentacja szczegółowa (EN): [`FEATURES_AND_ML_METHODOLOGY.md`](FEATURES_AND_ML_METHODOLOGY.md) (cechy,
> podobieństwo, klastrowanie) · [`PIPELINE_WALKTHROUGH.md`](PIPELINE_WALKTHROUGH.md) (przebieg krok po kroku) ·
> [`WEB_FETCHING_METHODOLOGY.md`](WEB_FETCHING_METHODOLOGY.md) (pobieranie, cloaking, OSINT).

**Zasada.** Używamy dwóch rodzajów dowodów i niczego więcej:

* **identyfikatory** — dokładne wartości, które operator używa ponownie (piksel, domena, ścieżka API backendu).
  Jeden wspólny, nietrywialny identyfikator łączy dwa materiały (deterministyczne łączenie rekordów [1]);
* **widoki treści** — pięć podobieństw w [0, 1], każde standardową miarą z literatury, uśrednionych z równą wagą
  po widokach dostępnych po obu stronach (współczynnik Gowera [13]).

Pozostałe cechy (osoby, typ oszustwa, rejestrator, słowa kluczowe…) są pokazywane analitykowi, ale **nie łączą
materiałów**, bo w naszych oznaczonych danych powtarzają się w różnych kampaniach. Cała metoda ma pięć stałych:
`MAX_DF`, `PHASH_HAMMING`, `DUPLICATE_CUT`, `CAMPAIGN_CUT`, `FAMILY_CUT` (plus progi detekcji twarzy i limity
ekstrakcji). Wszystkie modele działają na CPU (ONNX Runtime).

## 0. Materiał i pozyskiwanie

* **Materiał (incydent)** = folder przypadku ze zbioru organizatora, przesłany plik (zrzut, wideo, HTML, HAR, MHTML,
  ZIP), przechwycony URL, pozycja z biblioteki reklam albo tekstowa wskazówka (nazwa produktu, treść reklamy).
  Brak strony (404), usunięte wideo czy sam zrzut ekranu to poprawny materiał — brakujące modalności po prostu nie
  biorą udziału w porównaniu.
* **Źródła**: zbiór organizatora / upload; przechwycenie URL (`ftf/capture.py`: ochrona SSRF, łańcuch przekierowań
  w 3 profilach klienta, w tym `fb_mobile` z `fbclid`, klasyfikacja cloakingu, opcjonalny render Playwright); lista
  ostrzeżeń CERT Polska; Microsoft Ad Library API; Google Ads Transparency Center; Meta Ad Library (API z tokenem,
  kreacje przez yt-dlp); metadane domen (RDAP, DNS, crt.sh). Szczegóły: `WEB_FETCHING_METHODOLOGY.md`, `research/`.

## 1. Cechy

### 1.1 Identyfikatory (dokładne dopasowanie → must-link)

Typy wskaźników są mapowane na grupy przez `config.IDENTIFIER_GROUP`:

| Grupa | Typy wskaźników | Skąd |
|---|---|---|
| `ad_library` | `ad_id`, `advertiser_id` | `.info.json` z yt-dlp, URL biblioteki reklam, OCR „Identyfikator biblioteki” |
| `domains` | `landing_domain`, `redirect_domain`, `page_host`, `ocr_domain`, `tds_host` | URL-e, łańcuch przekierowań z HAR, `saved from url=`, domeny odczytane z kreacji (OCR/QR). Domena rejestrowalna (PSL); domeny z OCR/QR przechodzą filtr `web.is_decoy_or_generic_domain` |
| `tracking_ids` | `fb_pixel`, `tiktok_pixel`, `ga`, `gtm`, `gads`, `tenant_uuid`, `affiliate`, `adset`, `campaign_param` | HTML, treści z HAR, zapisane skrypty, parametry URL; ID kanonizowane do gołej postaci, UUID-y sesji usuwane z `tenant_uuid` |
| `contacts` | `phone`, `email`, `telegram`, `whatsapp`, `wallet` | tekst i HTML strony |
| `kit_files` | `script_hash`, `api_template`, `form_endpoint`, `path_template` | SHA-1 skryptów 1st-party (bez bibliotek generycznych); ścieżki POST/formularzy z ID zastąpionymi szablonem, np. `POST /api/v1/trigger/field/{id}/` |
| `product` | `product` | `product_or_platform_name` z LLM (lub reguł), znormalizowane (np. „Orzeł Fundaris”) |

Dodatkowo `file_sha` (SHA-256 zapisanej strony lub zrzutu) → **duplikat**; identyczny plik jest też traktowany jak
wspólny identyfikator (must-link, `p = 1`), bo ten sam plik nie może należeć do dwóch kampanii.

Wartości porównujemy w obrębie grupy, więc np. domena odczytana z kreacji (`ocr_domain`) pasuje do `landing_domain`
innego materiału.

**Zbyt popularne wartości.** Wspólna wartość liczy się tylko, gdy `df/N ≤ config.MAX_DF` (= 0,5) albo gdy mają ją
wyłącznie dwa porównywane materiały (`df ≤ 2`) — idea IDF: termin
obecny w większości dokumentów nie rozróżnia [3]. Pominięte wartości są widoczne w uzasadnieniu („w X z N
materiałów, zbyt popularne”).

Dlaczego te cechy: wspólne identyfikatory analityki/pikseli ujawniają wspólnego operatora pozornie niezależnych
stron [2]; zestawy phishingowe (kity) są wielokrotnie używane i rozpoznawalne po plikach i endpointach [4]. W 10
oznaczonych materiałach żadna wartość identyfikatora nie występuje w dwóch różnych kampaniach.

### 1.2 Widoki treści (`similarity.VIEWS = ("text", "ocr", "semantic", "html", "images")`)

| Widok | Reprezentacja | Miara `sim_v(a,b)` |
|---|---|---|
| `text` | sygnatura MinHash (4-gramy słów) **tekstu strony docelowej** (tytuły + tekst HTML) z zamaskowanymi osobami (`<per>`) | estymowany indeks Jaccarda [5, 6] |
| `ocr` | ta sama sygnatura dla **tekstu kreacji**: OCR zrzutów i klatek wideo (+ treść reklamy podana jako tekst i metadane z biblioteki reklam), osoby zamaskowane. Dla materiałów zapisanych wcześniej liczona z zapisanego `text.ocr_text` (bez ponownej analizy) | estymowany indeks Jaccarda [5, 6] |
| `semantic` | embedding multilingual-e5-small [7] tekstu materiału | cosinus po odjęciu zwykłej średniej korpusu [8], obcięty do [0, 1]; surowy cosinus, gdy korpus ma < 3 materiały |
| `html` | MinHash 5-gramów sekwencji tagów HTML, jeden na stronę | estymowany Jaccard [6, 9]; maksimum po parach stron |
| `images` | zbiór 64-bitowych pHash [10] obrazów materiału: kreacje spoza interfejsu platformy (zrzuty, klatki wideo) + obrazy ze strony docelowej (`asset_phash`) | współczynnik pokrycia: liczba obrazów mniejszego zbioru mających odpowiednik w drugim przy odległości Hamminga ≤ `config.PHASH_HAMMING` (= 4), podzielona przez `min(|A|, |B|)` (zawieranie mniejszego zbioru [6]) |

Widok jest **dostępny** dla pary tylko wtedy, gdy obie strony mają daną reprezentację; brak nie jest liczony jako 0.
Dzięki rozdzieleniu `text` i `ocr` kreacja bez strony (strona martwa) jest porównywana OCR-do-OCR, a nie OCR-do-tekstu
strony.
Maskowanie osób wykrywa „ten sam artykuł, podmieniony celebryta”. Centrowanie usuwa anizotropię embeddingów:
surowe cosinusy e5 między niepowiązanymi polskimi stronami scamowymi są bardzo wysokie [8].

### 1.3 Cechy wyłącznie opisowe (pokazywane, nigdy nie łączą)

| Cecha | Źródło | Dlaczego nie łączy |
|---|---|---|
| osoby | ArcFace [11] vs baza referencyjna 29 osób (detekcja SCRFD [11]; twarz użyta, gdy wynik detektora ≥ `FACE_DET_THRESHOLD` i bok ≥ `FACE_MIN_SIDE`; tożsamość, gdy cosinus ≥ `FACE_MATCH_THRESHOLD`) + nazwiska z gazetteera | ci sami celebryci są w wielu niezależnych kampaniach (huby) |
| `scam_type` | LLM / reguły (zamknięty słownik) | wspólny dla różnych kampanii |
| słowa kluczowe | YAKE [12] | tematyka, nie operator |
| kwoty | regex (`zł`, `PLN`, `EUR`) | kontekst |
| rejestrator, data utworzenia, serwery NS, IP, obecność na liście CERT Polska | RDAP, DNS, crt.sh, lista CERT PL | rejestrator wspólny dla różnych kampanii; kontekst dla analityka |
| nazwa reklamodawcy, podszyte medium, marki | OCR, LLM, gazetteer | kontekst; nazwy nie są unikalne |

Odporność ekstrakcji na formaty: klatki wideo z pominięciem czarnych klatek (technika omijania moderacji); wycięcie kreacji z pionowego zrzutu feedu; zrzuty interfejsu biblioteki reklam rozpoznawane po OCR
i wyłączane z `images` (zostaje OCR, `ad_id`, reklamodawca); tekst po NFKC, bez diakrytyków i znaków zero-width;
filtr adresów CDN. Schemat LLM (Claude Haiku przez `claude -p` → Gemini → reguły): `scam_type`,
`impersonated_persons`, `impersonated_brands`, `spoofed_media_outlet`, `product_or_platform_name` (+ `summary_pl`).
Do łączenia trafia wyłącznie nazwa produktu.

## 2. Podobieństwo (`ftf/similarity.py`)

1. **Must-link**: para dzieląca ≥ 1 liczony identyfikator jest połączona; domknięcie przechodnie union-find →
   składowe must-link [1, 2].
2. **Odległość treściowa** (Gower [13], średnia po dostępnych widokach):
   ```
   d(a,b) = 1 − (1/k) · Σ_{v ∈ V(a,b)} sim_v(a,b),   V(a,b) = widoki dostępne po obu stronach, k = |V(a,b)|
   ```
   Gdy `k = 0`: `d = 1,0` i `comparable = False` — niekompletne dane nigdy nie tworzą powiązania.
3. **Odległość do klastrowania**: `D(a,b) = 0`, gdy `a` i `b` są w tej samej składowej must-link, inaczej `d(a,b)`.

Brak wag i priorytetów: każdy dostępny widok wnosi dokładnie `sim_v / k`.

## 3. Grupowanie (`ftf/cluster.py`)

* **Algorytm**: aglomeracyjne klastrowanie ze **średnim wiązaniem** (UPGMA) na `D`, `scipy.cluster.hierarchy` [14].
  Odległość dwóch klastrów to średnia `D` po wszystkich parach między nimi — pojedyncze przypadkowe podobieństwo nie
  skleja klastrów (w przeciwieństwie do single linkage). Składowe must-link łączą się najpierw (na wysokości 0) i żadne cięcie ich nie dzieli.
* **Kampanie** = cięcie dendrogramu (`fcluster`) na wysokości `config.CAMPAIGN_CUT` (= 0,6).
* **Rodziny** (grupy podobnych kampanii) = cięcie **tego samego dendrogramu** na `config.FAMILY_CUT` (= 0,93) —
  „podobna treść, brak wspólnego śladu operatora”; raportowane osobno.
* **Duplikaty**: wspólny `file_sha` lub `ad_id`, albo `d ≤ config.DUPLICATE_CUT` (= 0,05); grupy union-find.
* **Relacja pary** (`Link.relation`): `duplicate` | `same_campaign` (wspólny identyfikator lub `d ≤ CAMPAIGN_CUT`) |
  `similar` (`d ≤ FAMILY_CUT`) | `none`. Przynależność do kampanii wynika z dendrogramu, więc dwa materiały jednej
  kampanii mogą być połączone tylko pośrednio.
* **Baseline**: HDBSCAN [15] na tej samej macierzy `D`, pokazywany w UI do porównania.

## 4. Nowy materiał — przypisanie otwarte (`cluster.assign`)

Grupowanie wsadowe odpowiada na pytanie „które materiały tworzą grupę” (średnie wiązanie). Przypisanie nowego
materiału odpowiada na inne pytanie — „czy to wariant materiału, który już znamy?” — dlatego używa **najbliższego
sąsiada** (1-NN [19]) z progiem odrzucenia (zbiór otwarty [16]). Średnia odległość do całej kampanii karałaby wariant
kampanii, którą spajają tylko identyfikatory, a której materiały mają różną treść.

1. wspólny identyfikator z materiałami dokładnie jednej kampanii → `known_campaign`; z ≥ 2 kampaniami →
   `merge_proposal`;
2. w przeciwnym razie najbliższy znany materiał `m*` według odległości treści `d`:
   * `d ≤ CAMPAIGN_CUT` → `known_campaign` (kampania `m*`);
   * inaczej → **`new_campaign`** z podaniem najbliższego materiału, jego kampanii i odległości; gdy
     `d ≤ FAMILY_CUT`, dodatkowo `similar_family` (kampania `m*`);
3. powiązanie-duplikat (ten sam plik, ten sam `ad_id` lub `d ≤ DUPLICATE_CUT`) zmienia decyzję na `duplicate`,
   z wyjątkiem `merge_proposal`.

Wynik zawiera listę najbardziej podobnych materiałów z uzasadnieniem.

## 5. Uzasadnienie powiązania

Każda para to obiekt `Link`: `distance` (odległość Gowera `d`), `p` (`1 − D` dla tej pary: 1,0 przy wspólnym
identyfikatorze, inaczej `1 − distance`), `relation`, `shared_ids` (lista `SharedId(group, type, value, df,
ignored)`), `views` (podobieństwa dostępnych widoków), `comparable`, `same_file` (identyczny plik). `Link.explain()` daje krótki tekst po polsku:
wspólne wartości identyfikatorów z `df/N` (także pominięte jako zbyt popularne), potem podobieństwa widoków.
Ponieważ `d` jest zwykłą średnią, analityk może je przeliczyć ręcznie. To samo uzasadnienie trafia do UI, grafu,
CSV i eksportu Neo4j (`ftf/graph.py`: węzły `Material`, `Campaign`, `Family`, `Domain`, `Indicator`, `Person`,
`Product`; krawędzie `LINKED {p, distance, relation, explanation}`).

## 6. Co usunęliśmy i dlaczego

Poprzednia wersja miała ~50 sygnałów i 92 ręcznie ustawione stałe. Sprawdzenie na 10 własnoręcznie oznaczonych
materiałach (`data/labels_dane.csv`, kampanie A–F):

| Usunięte | Dowód / powód |
|---|---|
| embeddingi kreacji CLIP i DINOv2; stopniowane podobieństwo pHash kreacji | brak separacji: pary z różnych kampanii miały wyniki ≥ par z tej samej kampanii. Zostało tylko dokładne ponowne użycie obrazu (pHash, Hamming ≤ 4) w `images` |
| osoby jako dowód (tożsamość z bazy, dopasowanie nieznanych twarzy, ten sam kadr twarzy), kategorie LLM (`scam_type`, szablon narracji, format kreacji), rejestrator / NS / IP / seria rejestracji | wspólne dla różnych kampanii (huby) → tylko opis |
| frazy LLM i dodatkowe pola LLM; iteracyjne dopisywanie atrybutów przez LLM (`tools/llm_refine.py`, `llm_extra_*`) | atrybuty były proponowane na podstawie tych samych klastrów, które miały rozdzielać (rozumowanie w kółko); frazy dublują widok `text` |
| drugi embedding tekstu (EmbeddingGemma-2) | dubluje widok `semantic`, ~4–6× wolniejszy na CPU |
| osobne MinHash (surowy / zamaskowany / OCR) łączone maksimum; szablon tytułu | zostały dwie zamaskowane sygnatury jako osobne widoki (`text` — strona, `ocr` — kreacja), bez fuzji maksimum |
| sygnatura kształtu parametrów TDS, build ID, favicon, nazwy skryptów/CSS, listy pól formularzy, drobne trackery (Sentry, reCAPTCHA, Clarity, Hotjar, Yandex Metrika, AdSense) | dublowały mocniejsze identyfikatory lub miały niejasną specyficzność dla operatora |
| mechanika punktacji: tiery S/M/W, wagi a priori typów, rampy, wzór rzadkości, predykat hubów, noisy-OR, limit „tylko słabe dowody”, kara za sprzeczność, wynik playbooka, poziom wariantów przekazu, centrowanie ważone gęstością, blocking kandydatów, decyzja `candidate_review`, iloczynowy wzór jakości twarzy i margines galerii | ręcznie ustawione stałe, nigdy niedopasowane do danych. Zastąpione przez must-link + średnią Gowera + średnie wiązanie, przypisanie 1-NN z progiem, jeden próg IDF (`MAX_DF`) i zwykłe centrowanie średnią |

Na tych samych etykietach uproszczona metoda odtwarza podział referencyjny: ARI = 1,00 dla każdego `CAMPAIGN_CUT`
z przedziału [0,05; 0,90] (zob. [`RESULTS.md`](RESULTS.md)).

## 7. Ewaluacja i ograniczenia (`tools/evaluate.py`, `ftf.cli eval`)

Protokół zgodny z planem testów organizatora:

1. **Leave-one-out**: usuwamy materiał, przebudowujemy, przypisujemy go ponownie (`cluster.assign`) → wraca do swojej
   kampanii albo — jeśli był singletonem — jest rozpoznany jako `new_campaign`.
2. **Syntetyczne warianty** („nowe odsłony znanych kampanii”): tylko kreacja (strona martwa), tylko strona, zrzut
   przycięty i przekompresowany, podmieniona domena z usuniętymi ID w URL, podmienione nazwisko → oczekiwane
   `known_campaign`.
3. **Materiały niepowiązane** → oczekiwane `new_campaign`.
4. **Z etykietami**: ARI [17] i B-cubed P/R [18] względem etykiet oraz baseline'u HDBSCAN; pairwise P/R/F1 z tej
   samej tablicy zliczeń par co ARI.

**Ograniczenia**

* 10 materiałów i **nasze własne** etykiety — wyniki to sanity check, nie benchmark.
* **Łańcuchowanie must-link**: jeden błędny lub przypadkowo wspólny identyfikator scala dwie kampanie. Ograniczamy
  to progiem `MAX_DF` i zawsze pokazujemy analitykowi wartość identyfikatora i jej `df/N`.
* `product` zależy od ekstrakcji przez LLM (bez LLM — reguły).
* Brak embeddingów wizualnych: **przerysowana** kreacja tej samej kampanii nie zostanie dopasowana wizualnie — łączą
  ją tylko identyczne obrazy, tekst, HTML i identyfikatory.
* Równe wagi widoków i progi cięcia to decyzje projektowe, nie wartości dopasowane; stabilność progów sprawdzamy na
  oznaczonych danych.
* Cloaking: część stron pokazuje treść tylko polskim IP mobilnym — zapisujemy to, co widział crawler, i profil,
  który to zobaczył.
* Licencje: wagi InsightFace (SCRFD/ArcFace) tylko do badań niekomercyjnych; pozostałe modele MIT/Apache-2.0.

## 8. Literatura

1. Christen, *Data Matching*, Springer 2012. <https://doi.org/10.1007/978-3-642-31164-2>
2. Starov i in., *Betrayed by Your Dashboard*, WWW 2018. <https://doi.org/10.1145/3178876.3186089>
3. Spärck Jones, *A statistical interpretation of term specificity*, J. Documentation 1972. <https://doi.org/10.1108/eb026526>
4. Bijmans i in., *Catching Phishers By Their Bait*, USENIX Security 2021. <https://www.usenix.org/conference/usenixsecurity21/presentation/bijmans>
5. Jaccard, New Phytologist 1912. <https://doi.org/10.1111/j.1469-8137.1912.tb05611.x>
6. Broder, *On the resemblance and containment of documents*, 1997. <https://doi.org/10.1109/SEQUEN.1997.666900>
7. Wang i in., *Multilingual E5*, 2024. <https://arxiv.org/abs/2402.05672>
8. Mu, Viswanath, *All-but-the-Top*, ICLR 2018. <https://arxiv.org/abs/1702.01417>
9. Cui i in., *Tracking Phishing Attacks Over Time*, WWW 2017. <https://doi.org/10.1145/3038912.3052654>
10. Zauner, *Implementation and Benchmarking of Perceptual Image Hash Functions*, 2010. <https://phash.org/docs/pubs/thesis_zauner.pdf>
11. Deng i in., *ArcFace*, CVPR 2019. <https://arxiv.org/abs/1801.07698> · Guo i in., SCRFD. <https://arxiv.org/abs/2105.04714>
12. Campos i in., *YAKE!*, Information Sciences 2020. <https://doi.org/10.1016/j.ins.2019.09.013>
13. Gower, *A general coefficient of similarity*, Biometrics 1971. <https://doi.org/10.2307/2528823>
14. Müllner, *Modern hierarchical, agglomerative clustering algorithms*, 2011. <https://arxiv.org/abs/1109.2378>
15. Campello i in., HDBSCAN, PAKDD 2013. <https://doi.org/10.1007/978-3-642-37456-2_14>
16. Bendale, Boult, *Towards Open World Recognition*, CVPR 2015. <https://arxiv.org/abs/1412.5687>
17. Hubert, Arabie, *Comparing partitions* (ARI), 1985. <https://doi.org/10.1007/BF01908075>
18. Amigó i in., B-cubed, Information Retrieval 2009. <https://doi.org/10.1007/s10791-008-9066-8>
19. Cover, Hart, *Nearest neighbor pattern classification*, IEEE Trans. Inf. Theory 13(1):21–27, 1967. <https://doi.org/10.1109/TIT.1967.1053964>
