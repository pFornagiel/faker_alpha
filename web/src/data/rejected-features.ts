/**
 * Candidate linking features that were examined and not adopted. Static content: the numbers are copied from the
 * experiment write-ups (`research/experiments/*.md` on the `exp/*` branches) and from the corpus profiling notes.
 */

export type Stage = "experiment" | "profiling" | "literature"

export interface Metric {
  label: string
  value: string
}

export interface RejectedFeature {
  name: string
  stage: Stage
  /** what was tried, one sentence */
  tried: string
  metrics: Metric[]
  /** why it was not adopted */
  reason: string
  /** experiment branch holding the script and the write-up */
  branch?: string
}

/** Corpus and product baseline the numbers refer to. */
export const CORPUS = { pages: "1 503", pairs: "1 128 749" }
export const BASELINE = { precision: "0.99", falseLinks: "0.0022", recall: "0.38", largest: "240" }
export const CRITERION = { precision: "0.9", falseLinks: "0.001" }

/** Experiments in the order they are shown; the key is the branch. */
export const EXPERIMENTS: { branch: string; title: string; question: string }[] = [
  { branch: "exp/scan-metadata", title: "Metadane skanu strony", question: "Czy drobne pola zapisu skanu (nagłówki, baner serwera, konsola, certyfikat) wskazują wspólnego operatora?" },
  { branch: "exp/script-skeleton", title: "Szkielet skryptów", question: "Czy skrypt z zamaskowanymi literałami łączy wdrożenia, których nie łączy dokładny skrót pliku?" },
  { branch: "exp/lang-invariant-copy", title: "Cechy tekstu niezależne od języka", question: "Czy liczby, długości bloków tekstu i znaki nieliterowe rozpoznają tę samą stronę po tłumaczeniu?" },
  { branch: "exp/domain-name-generator", title: "Wzorce nazw domen", question: "Czy sam zapis nazwy domeny wskazuje zestaw phishingowy albo operatora?" },
  { branch: "exp/css-class-vocab", title: "Słownik klas CSS", question: "Czy zbiór nazw klas CSS rozpoznaje zestaw phishingowy po zmianie tekstu i marki?" },
  { branch: "exp/fusion-two-groups", title: "Sposób łączenia miar", question: "Czy inna reguła łączenia miar niż średnia pozwala wykorzystać zgodność struktury strony?" },
  { branch: "exp/compression-distance", title: "Odległość kompresji", question: "Czy podobieństwo liczone kompresorem (NCD, LZJD) znajduje to, czego nie znajduje miara struktury HTML?" },
]

const P = "Precyzja"
const F = "Fałszywe połączenia"
const R = "Czułość na parach pewnych"
const M = "Odzyskane pary pominięte"
const N = "Nowe pary"
const NP = "Precyzja nowych par"
const L = "Największa kampania"
const PAIRS = "Połączone pary"

export const REJECTED: RejectedFeature[] = [
  // ------------------------------------------------------------------ exp/scan-metadata
  {
    name: "Nazwy nagłówków odpowiedzi HTTP",
    stage: "experiment",
    branch: "exp/scan-metadata",
    tried: "Para stron jest łączona, gdy obie odpowiadają tym samym zestawem nietypowych nagłówków, spotykanym na 2–30 domenach.",
    metrics: [
      { label: PAIRS, value: "750" },
      { label: `${P} (same pary)`, value: "0.83" },
      { label: `${P} (must-link)`, value: "0.99 → 0.91" },
      { label: F, value: "0.0022 → 0.0160" },
      { label: L, value: "240 → 255" },
      { label: NP, value: "0.15" },
    ],
    reason: "Zestaw nagłówków opisuje platformę hostingową i oprogramowanie serwera. Łączy strony różnych operatorów korzystających z tego samego hostingu.",
  },
  {
    name: "Baner serwera",
    stage: "experiment",
    branch: "exp/scan-metadata",
    tried: "Wspólna wartość nagłówków Server, X-Powered-By i Via z zamaskowanymi numerami wersji.",
    metrics: [
      { label: PAIRS, value: "682" },
      { label: `${P} (same pary)`, value: "0.87" },
      { label: `${P} (must-link)`, value: "0.99 → 0.91" },
      { label: F, value: "0.0022 → 0.0176" },
      { label: NP, value: "0.31" },
    ],
    reason: "Wspólne wartości to domyślne strony nginx, Apache i cPanel. Baner wskazuje oprogramowanie, a nie operatora.",
  },
  {
    name: "Nazwy kluczy w pamięci przeglądarki jako must-link",
    stage: "experiment",
    branch: "exp/scan-metadata",
    tried: "Wspólna nazwa klucza zapisanego przez stronę w pamięci przeglądarki, z zamaskowanymi liczbami.",
    metrics: [
      { label: PAIRS, value: "1 338" },
      { label: `${P} (same pary)`, value: "0.97" },
      { label: `${P} (must-link)`, value: "0.99 → 0.91" },
      { label: F, value: "0.0022 → 0.0165" },
      { label: NP, value: "0.25" },
    ],
    reason: "Jako cecha pary jest trafna (83% par to ten sam zestaw phishingowy), ale jako must-link skleja przechodnio różne zestawy. Nadaje się co najwyżej jako jeden z elementów odcisku zestawu.",
  },
  {
    name: "Komunikaty konsoli przeglądarki",
    stage: "experiment",
    branch: "exp/scan-metadata",
    tried: "Wspólny komunikat konsoli z zamaskowanymi adresami i liczbami.",
    metrics: [
      { label: "Pokrycie stron", value: "18%" },
      { label: PAIRS, value: "1 119" },
      { label: P, value: "0.85" },
      { label: NP, value: "0.84" },
    ],
    reason: "Większość wspólnych komunikatów to standardowe komunikaty przeglądarki o nieudanym pobraniu zasobu. Precyzja jest poniżej wymaganego progu.",
  },
  {
    name: "Stos technologiczny",
    stage: "experiment",
    branch: "exp/scan-metadata",
    tried: "Ten sam zestaw technologii wykrytych przez urlscan.io (Wappalyzer).",
    metrics: [
      { label: "Pokrycie stron", value: "80%" },
      { label: PAIRS, value: "965" },
      { label: P, value: "0.97" },
      { label: R, value: "0.03" },
    ],
    reason: "Wynik wskazuje framework (np. Nuxt.js, jQuery), a nie operatora. Czułość jest pomijalna.",
  },
  {
    name: "Czas wystawienia certyfikatu TLS bez filtra własnego certyfikatu",
    stage: "experiment",
    branch: "exp/scan-metadata",
    tried: "Must-link dla stron, których certyfikaty wystawiono w odstępie do 60 s, bez sprawdzania, do kogo należy certyfikat.",
    metrics: [
      { label: PAIRS, value: "1 126, w tym 654 na certyfikatach platform" },
      { label: F, value: "0.0022 → 0.0043" },
      { label: N, value: "7 502" },
      { label: NP, value: "0.66" },
    ],
    reason: "Platformy hostingowe obsługują wszystkich klientów jednym certyfikatem wieloznacznym, więc ich strony mają identyczny czas wystawienia. Wśród takich par ten sam zestaw phishingowy ma tylko 45%. Po ograniczeniu do certyfikatów własnych domeny cecha działa.",
  },
  {
    name: "Certyfikaty TLS wystawione w odstępie od 1 do 60 minut",
    stage: "experiment",
    branch: "exp/scan-metadata",
    tried: "Rozszerzenie okna czasu wystawienia certyfikatu własnego domeny powyżej jednej minuty.",
    metrics: [
      { label: "1–10 min: pary", value: "700" },
      { label: `1–10 min: ${P.toLowerCase()}`, value: "0.89" },
      { label: `1–10 min: ${NP.toLowerCase()}`, value: "0.66" },
      { label: "10–60 min: pary", value: "1 344" },
      { label: `10–60 min: ${P.toLowerCase()}`, value: "0.77" },
      { label: `10–60 min: ${NP.toLowerCase()}`, value: "0.54" },
    ],
    reason: "Precyzja spada wraz z odstępem. Powyżej minuty zbieżność czasu jest zbyt często przypadkowa.",
  },

  // ------------------------------------------------------------------ exp/script-skeleton
  {
    name: "Skrót szkieletu skryptu jako identyfikator",
    stage: "experiment",
    branch: "exp/script-skeleton",
    tried: "Skrót skryptu osadzonego w stronie po usunięciu komentarzy i zamaskowaniu napisów oraz liczb, porównywany dokładnie.",
    metrics: [
      { label: "Pary ponad dokładne skróty", value: "357" },
      { label: M, value: "0.00" },
      { label: `${P} (must-link)`, value: "0.99 → 0.95" },
      { label: F, value: "0.0022 → 0.0083" },
      { label: NP, value: "0.57" },
    ],
    reason: "Ponad dokładne skróty plików nie odzyskuje par pominiętych przez produkt, a jako must-link obniża precyzję. Bez limitu liczby domen 2 628 z 2 645 dodanych par to jedna strona zastępcza dostawcy hostingu.",
  },
  {
    name: "Podobieństwo 5-gramów szkieletu skryptu jako must-link",
    stage: "experiment",
    branch: "exp/script-skeleton",
    tried: "Must-link dla par o wysokim podobieństwie 5-gramów tokenów szkieletu skryptów osadzonych w stronie.",
    metrics: [
      { label: `Próg 0.9: ${P.toLowerCase()}`, value: "0.99 → 0.93" },
      { label: `Próg 0.9: ${F.toLowerCase()}`, value: "0.0159" },
      { label: `Próg 0.6: ${P.toLowerCase()}`, value: "0.99 → 0.85" },
      { label: `Próg 0.6: ${F.toLowerCase()}`, value: "0.0408" },
      { label: L, value: "240 → 246" },
    ],
    reason: "Cecha rozpoznaje zestaw phishingowy, a nie operatora (wspólny dedykowany adres IP ma 8% par). Przechodniość must-link łączy kampanie różnych operatorów używających tego samego zestawu. Jako sama cecha pary pozostaje obiecująca.",
  },

  // ------------------------------------------------------------------ exp/lang-invariant-copy
  {
    name: "Zbiór liczb w tekście strony",
    stage: "experiment",
    branch: "exp/lang-invariant-copy",
    tried: "Liczby z widocznego tekstu (bez lat i numerów telefonów) porównywane ważonym współczynnikiem Jaccarda.",
    metrics: [
      { label: P, value: "1.00" },
      { label: M, value: "0.13" },
      { label: "Z tego poza zasięgiem miar semantycznej i HTML", value: "0.9%" },
      { label: `${N} (szósta miara)`, value: "92" },
      { label: `${F} (must-link)`, value: "0.0022 → 0.0069" },
    ],
    reason: "Wspólne liczby to stałe szablonu strony, który miara struktury HTML rozpoznaje już prawie bezbłędnie na parach w różnych językach (AUC 0.998). Jako szósta miara nie zmienia grupowania, jako must-link skleja kampanie.",
  },
  {
    name: "Długości bloków tekstu",
    stage: "experiment",
    branch: "exp/lang-invariant-copy",
    tried: "Kolejne bloki tekstu zapisane jako znacznik i przedział długości, porównywane jak n-gramy.",
    metrics: [
      { label: "AUC", value: "0.991" },
      { label: "AUC samych znaczników (kontrola)", value: "0.994" },
      { label: M, value: "0.16" },
      { label: `${N} (szósta miara)`, value: "48" },
      { label: `${P} (must-link, próg 0.2)`, value: "0.99 → 0.91" },
      { label: `${F} (must-link, próg 0.2)`, value: "0.0194" },
    ],
    reason: "Długość bloku nie wnosi nic ponad sam znacznik: wariant kontrolny bez długości jest równie dobry. To druga miara struktury HTML. Luźniejszy wariant (2-gramy) jako must-link powiększa największą kampanię z 240 do 335 stron.",
  },
  {
    name: "Znaki nieliterowe w blokach tekstu",
    stage: "experiment",
    branch: "exp/lang-invariant-copy",
    tried: "Interpunkcja, emoji, symbole walut i ciągi cyfr z każdego bloku tekstu, porównywane jak n-gramy.",
    metrics: [
      { label: P, value: "1.00" },
      { label: M, value: "0.07" },
      { label: `${N} (szósta miara)`, value: "35" },
      { label: `${R} (szósta miara)`, value: "0.38 → 0.37" },
    ],
    reason: "Najsłabsza z trzech cech tekstu. Znajduje niewiele par i żadnej, której nie znajdują istniejące miary.",
  },

  // ------------------------------------------------------------------ exp/domain-name-generator
  {
    name: "Podobieństwo n-gramów nazwy domeny",
    stage: "experiment",
    branch: "exp/domain-name-generator",
    tried: "Podobieństwo kosinusowe n-gramów znakowych nazwy domeny jako cecha pary i jako szósta miara.",
    metrics: [
      { label: "AUC", value: "0.54–0.57" },
      { label: `${N} (szósta miara)`, value: "0" },
      { label: `${R} (szósta miara)`, value: "0.38 → 0.34" },
    ],
    reason: "Ranking par jest bliski losowemu (AUC 0.5). Dodanie miary pogarsza grupowanie.",
  },
  {
    name: "Kształt i klasa nazwy domeny",
    stage: "experiment",
    branch: "exp/domain-name-generator",
    tried: "Wspólna końcówka (TLD), maska znaków i długość nazwy albo klasa nazwy (losowa, wymawialna, słownikowa).",
    metrics: [
      { label: P, value: "0.93–0.97" },
      { label: NP, value: "0.23–0.42" },
      { label: `${L} (must-link)`, value: "240 → 1 145" },
      { label: `${P} (must-link)`, value: "0.99 → 0.29" },
    ],
    reason: "Wysoka precyzja pochodzi z jednej rodziny stron, którą produkt już grupuje. Poza nią wzorzec jest zbyt powszechny: popularna końcówka i typowa maska łączą dziesiątki niezależnych zestawów.",
  },
  {
    name: "Wspólny fragment nazwy domeny",
    stage: "experiment",
    branch: "exp/domain-name-generator",
    tried: "Wspólny ciąg 6 lub 8 znaków spoza słownika albo ta sama wymyślona nazwa marki w dwóch domenach.",
    metrics: [
      { label: "Fragment 6 znaków: pary", value: "187" },
      { label: `Fragment 6 znaków: ${P.toLowerCase()}`, value: "0.38" },
      { label: "Ta sama nazwa marki: pary", value: "20" },
      { label: `${P} (must-link)`, value: "0.99 → 0.98" },
      { label: `${R} (must-link)`, value: "0.38 → 0.33" },
    ],
    reason: "Wspólne fragmenty to najczęściej słowa tematyczne. Ta sama wymyślona nazwa marki pojawia się w dwóch różnych zestawach phishingowych, czego żadna referencja nie potrafi potwierdzić. Pozostaje co najwyżej wskazówką opisową.",
  },
  {
    name: "Czas zgłoszenia i ta sama końcówka domeny jako must-link",
    stage: "experiment",
    branch: "exp/domain-name-generator",
    tried: "Must-link dla domen z tą samą końcówką (TLD), które trafiły na listę CERT Polska w odstępie do 60 minut.",
    metrics: [
      { label: `${P} (same pary)`, value: "0.98" },
      { label: `${P} (must-link)`, value: "0.99 → 0.53" },
      { label: F, value: "0.0022 → 0.1937" },
      { label: L, value: "240 → 730" },
      { label: `Okno 10 min: ${P.toLowerCase()}`, value: "0.89" },
    ],
    reason: "Zgłoszenia przychodzą seriami, a must-link łączy przechodnio całe serie niezwiązanych stron. Produkt nie otrzymuje też czasu zgłoszenia jako danej wejściowej.",
  },

  // ------------------------------------------------------------------ exp/css-class-vocab
  {
    name: "Tylko rzadkie nazwy klas CSS",
    stage: "experiment",
    branch: "exp/css-class-vocab",
    tried: "Słownik klas CSS ograniczony do nazw występujących na najwyżej 2% stron, żeby pominąć klasy popularnych frameworków.",
    metrics: [
      { label: "AUC", value: "0.748" },
      { label: "AUC pełnego słownika", value: "0.993" },
      { label: `${N} (szósta miara)`, value: "493 wobec 692" },
    ],
    reason: "Sygnał niesie zestawienie nazw, także tych częstych, a ważenie odwrotną częstością już je osłabia. Odcięcie częstych nazw usuwa większość informacji.",
  },
  {
    name: "Słownik klas CSS jako must-link",
    stage: "experiment",
    branch: "exp/css-class-vocab",
    tried: "Must-link dla par o wysokim podobieństwie słownika klas, także w połączeniu z miarą struktury HTML albo miarą semantyczną.",
    metrics: [
      { label: `Próg 0.8: ${P.toLowerCase()}`, value: "0.99 → 0.97" },
      { label: `Próg 0.8: ${F.toLowerCase()}`, value: "0.0058" },
      { label: `Próg 0.8: ${NP.toLowerCase()}`, value: "0.78" },
      { label: `Z miarą semantyczną: ${P.toLowerCase()}`, value: "0.90" },
      { label: `Z miarą semantyczną: ${F.toLowerCase()}`, value: "0.0230" },
    ],
    reason: "Sama cecha pary jest czysta, ale must-link łączy całe kampanie i powiela błędy już obecne w grupowaniu. Jako szósta miara cecha jest bezpieczna i daje niewielki zysk.",
  },

  // ------------------------------------------------------------------ exp/fusion-two-groups
  {
    name: "Średnia z dwóch najwyższych miar",
    stage: "experiment",
    branch: "exp/fusion-two-groups",
    tried: "Odległość pary liczona z dwóch najwyższych podobieństw spośród sześciu miar zamiast ze średniej wszystkich.",
    metrics: [
      { label: P, value: "0.99 → 0.88" },
      { label: F, value: "0.0022 → 0.0284" },
      { label: N, value: "21 784" },
      { label: NP, value: "0.64" },
    ],
    reason: "Przypadkowa zgodność dwóch miar jest zbyt częsta, żeby wystarczała do połączenia.",
  },
  // ------------------------------------------------------------------ exp/compression-distance
  {
    name: "Odcisk zestawu phishingowego jako must-link",
    stage: "experiment",
    branch: "exp/compression-distance",
    tried: "Must-link dla par o podobieństwie odcisku zestawu co najmniej 0.55.",
    metrics: [
      { label: P, value: "0.99 → 0.87" },
      { label: F, value: "0.0022 → 0.0377" },
      { label: L, value: "240 → 257" },
      { label: NP, value: "0.70" },
    ],
    reason: "Odcisk mówi „ten sam zestaw”, a jeden zestaw bywa używany przez kilku operatorów. Przechodniość must-link łączy ich kampanie.",
  },
  {
    name: "Znormalizowana odległość kompresji (NCD)",
    stage: "experiment",
    branch: "exp/compression-distance",
    tried: "Podobieństwo dwóch stron liczone kompresorem zlib na pierwszych 16 KB kodu, na dwóch próbach po 400 stron.",
    metrics: [
      { label: M, value: "0.79 i 0.73" },
      { label: "Czas na 1000 par", value: "0.60–0.81 s" },
      { label: "Czas LZJD na 1000 par", value: "0.002 s" },
      { label: "Zysk ponad miarę HTML i odcisk zestawu", value: "+0.03" },
    ],
    reason: "Najwyższa czułość ze wszystkich wariantów, ale każda para wymaga wywołania kompresora i nie da się zbudować indeksu. Koszt rośnie z kwadratem liczby stron, a zysk ponad istniejące sygnały jest mały.",
  },
  {
    name: "LZJD na całych plikach i w miejsce miary HTML",
    stage: "experiment",
    branch: "exp/compression-distance",
    tried: "Podobieństwo LZJD liczone na całym kodzie strony oraz użyte zamiast miary struktury HTML.",
    metrics: [
      { label: `${M} (cały kod)`, value: "0.35" },
      { label: `${M} (pierwsze 16 KB)`, value: "0.59" },
      { label: `${R} (w miejsce miary HTML)`, value: "0.38 → 0.35" },
    ],
    reason: "Wariant na całym pliku jest słabszy niż ograniczony do pierwszych 16 KB, a zastąpienie miary HTML pogarsza grupowanie.",
  },
  {
    name: "LZJD jako must-link",
    stage: "experiment",
    branch: "exp/compression-distance",
    tried: "Must-link dla par o podobieństwie LZJD powyżej progu, przy którym sama cecha pary spełnia kryterium.",
    metrics: [
      { label: `Próg 0.4: ${P.toLowerCase()}`, value: "0.99 → 0.87" },
      { label: `Próg 0.4: ${F.toLowerCase()}`, value: "0.0346" },
      { label: `Próg 0.5: ${P.toLowerCase()}`, value: "0.97" },
      { label: `Próg 0.5: ${F.toLowerCase()}`, value: "0.0056" },
    ],
    reason: "Dla pojedynczych par odsetek fałszywych połączeń wynosi 0.0002, po przechodnim łączeniu 0.035. Bezpieczny jest dopiero próg 0.6, który odzyskuje 12% par pominiętych.",
  },

  // ------------------------------------------------------------------ ruled out by profiling the corpus
  {
    name: "Kombinacje protokołu i szyfru TLS",
    stage: "profiling",
    tried: "Wersja protokołu, wymiana kluczy i szyfr połączenia ze stroną jako wspólna cecha.",
    metrics: [{ label: "Różnych kombinacji w korpusie", value: "12" }],
    reason: "Wartości jest zbyt mało, żeby cokolwiek rozróżniały. Wynikają z konfiguracji dostawcy hostingu.",
  },
  {
    name: "Lista nazw w certyfikacie (SAN)",
    stage: "profiling",
    tried: "Wspólne nazwy domen wpisane do jednego certyfikatu.",
    metrics: [{ label: "Certyfikaty z 1–2 nazwami", value: "99%" }],
    reason: "Prawie każdy certyfikat obejmuje tylko własną domenę, więc lista nie łączy stron między sobą.",
  },
  {
    name: "Ślady kopiowania strony (HTTrack)",
    stage: "profiling",
    tried: "Komentarze pozostawiane w kodzie przez narzędzia do kopiowania stron.",
    metrics: [{ label: "Strony ze śladem", value: "0" }],
    reason: "Cecha nie występuje w korpusie.",
  },
  {
    name: "Sygnatury obfuskatorów JavaScript",
    stage: "profiling",
    tried: "Charakterystyczne wzorce kodu po zaciemnieniu popularnymi narzędziami.",
    metrics: [{ label: "Strony z sygnaturą", value: "2" }],
    reason: "Zbyt rzadkie, żeby dało się ocenić. Sygnatura wskazywałaby zresztą narzędzie, a nie operatora.",
  },
  {
    name: "Tokeny botów Telegram",
    stage: "profiling",
    tried: "Token bota Telegram zapisany w kodzie strony jako identyfikator.",
    metrics: [
      { label: "Strony z tokenem", value: "5" },
      { label: "Tokeny wspólne dla dwóch stron", value: "0" },
    ],
    reason: "Nie da się ocenić na tym korpusie. Token pozostaje poprawnym identyfikatorem dokładnym, gdy wystąpi.",
  },
  {
    name: "Adres kanoniczny i og:url wskazujące inną domenę",
    stage: "profiling",
    tried: "Znaczniki canonical i og:url pozostawione po skopiowaniu strony z innej domeny.",
    metrics: [
      { label: "Strony z takim znacznikiem", value: "2% i 1%" },
      { label: "Pary ze wspólną wartością", value: "po 1" },
      { label: "Wskazania innej strony z korpusu", value: "0" },
    ],
    reason: "Zbyt rzadkie, żeby łączyły strony.",
  },
  {
    name: "Znaczniki sieci afiliacyjnych i interfejsów zbierania kontaktów",
    stage: "profiling",
    tried: "Identyfikatory partnerów i adresy interfejsów, do których formularze wysyłają dane.",
    metrics: [{ label: "Strony ze znacznikiem", value: "3" }],
    reason: "Zbyt rzadkie w korpusie, żeby dało się ocenić.",
  },
  {
    name: "Skrót kolejności nagłówków HTTP (HHHash)",
    stage: "profiling",
    tried: "Skrót nazw nagłówków odpowiedzi w kolejności, w jakiej wysyła je serwer.",
    metrics: [],
    reason: "Zapis skanu podaje nagłówki w kolejności alfabetycznej, więc kolejność serwera jest utracona. Sam zbiór nazw sprawdzono w eksperymencie i odrzucono.",
  },
  {
    name: "Treść zewnętrznych skryptów",
    stage: "profiling",
    tried: "Szkielet plików JavaScript pobieranych przez stronę z własnej domeny.",
    metrics: [],
    reason: "Zapisy skanów nie zawierają treści pobranych plików, więc cechy nie da się zmierzyć na tym korpusie. Jedna oznaczona para z danych organizatora potwierdza, że mechanizm istnieje.",
  },

  // ------------------------------------------------------------------ ruled out from the literature
  {
    name: "JARM, JA4S, JA4H",
    stage: "literature",
    tried: "Odciski serwera TLS i żądań HTTP stosowane do wykrywania infrastruktury.",
    metrics: [],
    reason: "Wymagają aktywnego sondowania serwera albo zapisu ruchu sieciowego. Nie da się ich wyliczyć z materiałów, które otrzymuje produkt.",
  },
  {
    name: "JA4X",
    stage: "literature",
    tried: "Odcisk budowy certyfikatu X.509.",
    metrics: [],
    reason: "Opisuje szablon urzędu certyfikacji, wspólny dla wszystkich jego klientów.",
  },
  {
    name: "Skrót percepcyjny PDQ",
    stage: "literature",
    tried: "Zamiennik skrótu pHash dla obrazów.",
    metrics: [],
    reason: "Należy do tej samej rodziny skrótów opartych na transformacie kosinusowej co pHash, więc ma te same słabości przy przycięciu obrazu.",
  },
  {
    name: "Wektory głosu mówcy",
    stage: "literature",
    tried: "Porównywanie głosu w reklamach wideo.",
    metrics: [],
    reason: "Grupują materiały według osoby, pod którą podszywa się reklama, a nie według operatora.",
  },
  {
    name: "Odcisk ścieżki dźwiękowej (Chromaprint)",
    stage: "literature",
    tried: "Wykrywanie tej samej ścieżki dźwiękowej w różnych reklamach wideo.",
    metrics: [{ label: "Wideo w danych", value: "3" }],
    reason: "Przy tak małej liczbie nagrań wyniku nie da się zweryfikować.",
  },
  {
    name: "Rozpoznawanie generatora obrazu lub wideo",
    stage: "literature",
    tried: "Przypisanie syntetycznego obrazu do modelu, który go wytworzył.",
    metrics: [],
    reason: "Wskazuje narzędzie, a nie operatora, i wymaga ciężkich zależności (PyTorch).",
  },
  {
    name: "Marka systemu maskowania ruchu (cloakera)",
    stage: "literature",
    tried: "Wspólny system ukrywania właściwej strony przed moderacją jako połączenie.",
    metrics: [],
    reason: "To narzędzie kupowane przez wielu niezależnych operatorów.",
  },
  {
    name: "Klasy frameworka CSS",
    stage: "literature",
    tried: "Wspólne klasy popularnych frameworków (Bootstrap, Tailwind) jako połączenie.",
    metrics: [],
    reason: "To narzędzie wspólne dla niezależnych stron. Pełny słownik klas, także własnych klas zestawu, sprawdzono osobno w eksperymencie.",
  },
]
