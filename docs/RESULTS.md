# Wyniki na zbiorze przykładowym organizatora (DANE.zip, 10 przypadków)

Reprodukcja: `python -m ftf.cli ingest data/organizer/dane` → `python tools/evaluate.py --labels data/labels_dane.csv`
(raporty: `data/eval/report_full_run.json`, `data/eval/report_only_1_48_61.json`).
CPU laptop (i5-8365U, bez GPU), ~1–3 min / przypadek (OCR + twarze + CLIP/DINO + LLM Haiku).

## Wykryte kampanie

| Kampania | Przypadki | Warianty przekazu | Kluczowe wspólne ślady (uzasadnienie) |
|---|---|---|---|
| **C1** — operator fałszywych artykułów „Gazeta.pl/TVN24” → fikcyjne platformy inwestycyjne | 1, 2, 3, 48, 61 | {1,2} „Wiem, kto strzelał” (Brzoska) · {48,61} „37 minut po emisji…” · {3} Olejnik/TVN24 | ten sam **Facebook Pixel 2012165449475163** i 2 **UUID tenanta landing-buildera** (1↔2); ta sama **domena healthlinkq.pro** + **seria rejestracji** NICENIC + para NS Cloudflare `braelyn/kurt` z 2026-10-08 (2↔3); ta sama fikcyjna platforma **„Orzeł Fundaris”** (3↔48); 5 identycznych obrazów na stronach (48↔61); ten sam **backend API** `POST /api/v1/trigger/field/{id}/` i ta sama **sygnatura TDS** `utm_id=A20&utm_medium=A10&…&utm_visit=U` (1/2/48/61). Rotujące nazwy platform: „Świtowin Zyskarnia”, „Orzeł Fundaris”, „Trwały Działunek”, „Polska Platforma Aktywnego Oszczędzania Emerytalnego”. Domeny rejestrowane dzień przed reklamą. |
| C2 | 47 (Uromexil Forte) | — | singleton |
| C3 | 5 (wideo z Biblioteki Reklam Meta, „lekarz” n. med. Jarosław Czubak) | — | singleton |
| C4 | 36 (Poland Invest Summit 2026) | — | singleton |
| C5 | 14 (Metabo RX, reklamodawca „Sustain Studio”) | — | singleton |
| C6 | 10 (Sweet Bonanza – kasyno, deepfake Ronaldo) | — | singleton |

**Rodziny (ten sam playbook, brak dowodów wspólnego operatora):** {47, 5, 14} — „cudowny lek” z
fałszywym autorytetem medycznym; {1,2,3,48,61}. Takie materiały dostają decyzję *nowa kampania,
podobny playbook do Cx* — zgodnie z wymaganiem, by nie łączyć materiałów bez wspólnych śladów.

## Metryki

| Test | Wynik |
|---|---|
| Etykiety referencyjne (`data/labels_dane.csv`, ustalone ręcznie na podstawie surowych plików*) | pairwise P = R = F1 = **1.00**, B-cubed P = R = **1.00**, ARI = **1.00** (baseline HDBSCAN na 1−p: ARI 0.35) |
| Leave-one-out (usuń materiał → przypisz ponownie) | **10/10** (5/5 wraca do swojej kampanii, 5/5 singletonów → „nowa kampania”) |
| Warianty: tylko kreacja (strona „martwa”) | **8/8** |
| Warianty: tylko strona (kreacja brakująca) | **8/8** |
| Warianty: podmieniona domena + usunięte ID w URL | **9/9** |
| Warianty: podmienione nazwisko celebryty w tekście | **5/5** |
| Warianty: zrzut przycięty 8 %, ×0.6, JPEG q55 | 5/7 ściśle, **7/7** z „do weryfikacji” (2 przypadki: przycięcie usuwa linię reklamodawcy, zostaje tylko twarz/układ → słusznie „candidate_review”) |
| **Łącznie warianty** | **35/37 (94.6 %)** ściśle, **37/37** łagodnie |

\* Etykiety ustalone przez ręczną weryfikację faktów w surowych plikach (ten sam piksel w HTML 1 i 2,
`healthlinkq.pro` w HAR 2 i HTML 3, „Orzeł Fundaris” w 3 i 48, ten sam artykuł w 48 i 61/strona_1)
— nie są to etykiety organizatora; zbiór jest mały (10), więc wyniki traktujemy jako sanity check.

## Co pomogło (ablacje jakościowe w trakcie strojenia)
* **Centrowanie embeddingów** średnią korpusu: surowe cos e5 dla niepowiązanych stron 0.89–0.93
  (zero separacji) → po centrowaniu niepowiązane ≤ 0.39.
* **Wycięcie kreacji ze zrzutów feedu + wyłączenie zrzutów interfejsu** (szczegóły reklamy,
  komentarze): usunęło fałszywe podobieństwo CLIP 0.83 / DINOv2 0.93 między kasynem a suplementem.
* **Szablony endpointów bez ID sesji**, **UUID tenantów** i **sygnatura kształtu parametrów TDS** —
  to one łączą różne narracje jednego operatora (Brzoska ↔ „37 minut” ↔ Olejnik).
* **Filtr generycznych fraz LLM** („dowiedz się więcej”) — wcześniej sklejał warianty przekazu.
* **Reguła „sam playbook ≠ kampania”** — obniżyła fałszywe „możliwe warianty” z 4/5 do 0/5 singletonów.

## LLM — przykład augmentacji cech
Haiku (przez `claude -p`) wyciągnął m.in. nazwy fikcyjnych platform, personę „n. med. Jarosław
Czubak” z klatek wideo, podszyte media, dosłowne frazy szablonowe. Pętla `tools/llm_refine.py`
zaproponowała 7 nowych atrybutów rozróżniających (np. `price_anchor` 274→137 PLN vs 138→69 PLN,
`product_name_morphology` „latin brand forte suffix” vs „rx suffix pharma brand”,
`celebrity_role` „fake speaker lineup” vs „fabricated tv interview quote”, `domain_name_style`),
które weszły do schematu ekstrakcji kolejnych materiałów.
