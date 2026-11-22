import type { ReactNode } from "react"
import { Link } from "react-router"

import { PageHeader } from "@/components/common"

type Group = { title: string; intro?: string; items: [name: string, why: string][] }

const GROUPS: Group[] = [
  {
    title: "Wskazują hosting albo narzędzie, a nie operatora",
    intro: "Te same wartości mają tysiące niezależnych stron, które korzystają z tego samego hostingu lub oprogramowania.",
    items: [
      ["Nagłówki HTTP i baner serwera", "Zestaw nagłówków zależy od hostingu, a wspólne banery to domyślne strony nginx, Apache i cPanel. Jako identyfikator obniżały precyzję z 0.99 do 0.91."],
      ["Stos technologiczny (Wappalyzer)", "Mówi, że strona używa jQuery albo Nuxt.js. Połączył tylko 3% par potwierdzonych innymi śladami."],
      ["Komunikaty konsoli przeglądarki", "Powtarzają się głównie standardowe błędy pobierania zasobów."],
      ["Czas wystawienia dowolnego certyfikatu TLS", "Platformy hostingowe dają wszystkim klientom jeden wspólny certyfikat, więc ich strony mają ten sam czas wystawienia. Po zawężeniu do własnych certyfikatów domeny cecha działa i jest w produkcie."],
      ["Szyfry i budowa certyfikatu TLS (JA4X)", "W całym zbiorze jest tylko 12 kombinacji szyfrów. Ustawia je hosting albo urząd certyfikacji."],
      ["Klasy frameworków CSS (Bootstrap, Tailwind)", "Używają ich niezależne strony. Pełny zestaw klas strony, razem z jej własnymi, jest w produkcie jako widok."],
      ["Cloaker, obfuskator skryptów, generator obrazów AI", "To narzędzia, które kupuje wielu niezależnych oszustów."],
      ["Głos w reklamach wideo", "Grupuje reklamy według osoby, pod którą się podszywają, a nie według tego, kto je wypuścił."],
    ],
  },
  {
    title: "Trafne dla pary, ale jako identyfikator sklejają kampanie",
    intro:
      "Identyfikator łączy materiały także przez pośredników: jeśli A pasuje do B, a B do C, wszystkie trzy trafiają do jednej kampanii. " +
      "Te cechy dobrze rozpoznają ten sam kit, ale jeden kit kupuje wielu operatorów, więc ich kampanie zlewały się w jedną.",
    items: [
      ["Klucze w pamięci przeglądarki", "Precyzja spadała z 0.99 do 0.91."],
      ["Szkielet skryptów", "Precyzja spadała z 0.99 do 0.93, a przy luźniejszym progu do 0.85. Jako widok treści jest w produkcie."],
      ["Klasy CSS", "Fałszywych połączeń przybywało ponad dwukrotnie. Jako widok treści jest w produkcie."],
      ["Podobny kod strony (odcisk kitu)", "Precyzja spadała z 0.99 do 0.87."],
      ["Odległość kompresji (LZJD)", "Pojedyncze pary były prawie zawsze trafne, ale po połączeniu przez pośredników precyzja spadała z 0.99 do 0.87."],
      ["Czas zgłoszenia do CERT Polska", "Zgłoszenia przychodzą seriami, więc łączyły całe serie niezwiązanych stron. Największa kampania rosła z 240 do 730 stron. Produkt i tak nie zna czasu zgłoszenia."],
    ],
  },
  {
    title: "Nie wnoszą nic nowego",
    intro: "Działały, ale znajdowały te same pary co widoki, które produkt już ma.",
    items: [
      ["Liczby, długości bloków i znaki w tekście", "Miały rozpoznać tę samą stronę po tłumaczeniu. Rozpoznawały jednak szablon strony, a to widok struktury HTML robi już prawie bezbłędnie."],
      ["Dokładny skrót szkieletu skryptu", "Nie znalazł żadnej pary, której produkt by nie miał, a obniżał precyzję do 0.95."],
      ["Tylko rzadkie klasy CSS", "Sygnał niosą właśnie częste nazwy w połączeniu z rzadkimi. Po odcięciu częstych zostało niewiele."],
      ["Odległość kompresji (NCD)", "Najwyższa czułość ze wszystkich wariantów, ale każdą parę trzeba osobno kompresować, a zysk ponad widok HTML i odcisk kitu wynosił 3 punkty procentowe."],
      ["Skrót PDQ zamiast pHash", "To ta sama rodzina skrótów, z tą samą słabością przy przycięciu. Przycięte obrazy rozpoznaje teraz dopasowanie punktów charakterystycznych."],
      ["Osobna średnia dla widoków struktury", "Odległość pary jako mniejsza z dwóch średnich: wszystkich widoków i samych widoków struktury (HTML, klasy CSS, szkielet skryptów). Wynik zależy od progu: przy 0.5 zamiast 0.6 precyzja spada z 0.99 do 0.92. Większość zysku dają te same widoki w zwykłej średniej."],
    ],
  },
  {
    title: "Za słabe",
    items: [
      ["Nazwy domen", "Podobieństwo samych nazw jest prawie losowe. Wspólna końcówka i podobny wzór nazwy łączyły dziesiątki niezależnych kitów, a największa kampania rosła z 240 do 1145 stron."],
      ["Certyfikaty wystawione w odstępie dłuższym niż minuta", "Im dłuższe okno, tym więcej przypadkowych zbieżności: precyzja 0.89 do 10 minut i 0.77 do godziny. W produkcie liczy się ta sama minuta."],
      ["Dwa najmocniejsze widoki zamiast średniej", "Dwa widoki zgadzają się przypadkiem zbyt często. Precyzja spadła z 0.99 do 0.88."],
      ["pHash czterech wycinków środka obrazu", "Rozpoznaje kopię tylko wtedy, gdy obraz przycięto po równo z każdej strony. Dopasowanie punktów charakterystycznych (ORB) radzi sobie też z nierównym przycięciem i to ono jest w produkcie."],
      ["Punkty charakterystyczne SIFT zamiast ORB", "Rozpoznaje trochę więcej kopii, ale przy tym samym progu uznał za ten sam obraz 4.9% par różnych obrazów, a ORB żadnej. Jego dane zajmują też 16 razy więcej miejsca."],
    ],
  },
  {
    title: "Za mało danych albo nie da się policzyć",
    items: [
      ["Rzadkie ślady w kodzie strony", "Adres kanoniczny innej domeny, komentarze HTTrack, znaczniki sieci afiliacyjnych, tokeny botów Telegram. Każdy występuje na kilku stronach albo wcale. Token Telegrama nadal byłby dobrym identyfikatorem, gdyby się powtórzył."],
      ["Odcisk kitu jako widok", "Wymaga statystyk z całego zbioru i pełnego zapisu skanu, których nie ma przesłana strona. To, co da się policzyć z jednego pliku HTML, niosą widoki klas CSS i szkieletu skryptów."],
      ["Lista domen w certyfikacie", "99% certyfikatów obejmuje tylko własną domenę, więc nie ma czego porównywać."],
      ["Ścieżka dźwiękowa (Chromaprint)", "W danych są tylko 3 nagrania wideo."],
      ["Kolejność nagłówków HTTP", "urlscan.io zapisuje nagłówki alfabetycznie, więc kolejność z serwera ginie."],
      ["Treść zewnętrznych skryptów", "Skany nie zawierają pobranych plików JavaScript."],
      ["Odciski serwera TLS i HTTP (JARM, JA4S, JA4H)", "Wymagają aktywnego sondowania serwera albo zapisu ruchu, a produkt dostaje tylko zapisane strony i reklamy."],
    ],
  },
]

export default function RejectedFeaturesPage() {
  const glossary = <Link to="/glossary" className="underline underline-offset-4">Słowniczek</Link>
  return (
    <div className="max-w-5xl space-y-8">
      <PageHeader title="Odrzucone cechy" description="Pomysły na nowe sygnały, które sprawdziliśmy i nie dodaliśmy do produktu." />

      <div className="max-w-[80ch] space-y-2 text-sm leading-relaxed text-pretty text-muted-foreground">
        <p>
          Większość testowaliśmy na 1503 stronach z listy ostrzeżeń CERT Polska, zeskanowanych w urlscan.io. Te strony nie mają etykiet kampanii,
          więc połączenia sprawdzaliśmy innymi śladami wspólnego pochodzenia: tym samym szablonem tytułu, tym samym serwerem, certyfikatami z tej
          samej minuty, niemal identycznym zrzutem ekranu i podobnym kodem strony. Cecha przechodziła, jeśli znajdowała pary pomijane przez produkt
          i nie sklejała niezwiązanych kampanii. Precyzja to udział trafnych połączeń, a obecna metoda ma na tych stronach 0.99.
        </p>
        <p>
          Część pomysłów z tych samych eksperymentów weszła do produktu: klasy CSS, szkielet skryptów, certyfikaty z tej samej minuty, osobne
          traktowanie tekstów w różnych językach i dopasowanie przyciętych obrazów. Opisuje je {glossary}.
        </p>
      </div>

      {GROUPS.map((g) => (
        <section key={g.title} className="space-y-3">
          <div className="space-y-1">
            <h2 className="text-lg font-semibold">{g.title}</h2>
            {g.intro && <p className="max-w-[80ch] text-sm text-pretty text-muted-foreground">{g.intro}</p>}
          </div>
          <dl className="divide-y rounded-lg border text-sm leading-relaxed">
            {g.items.map(([name, why]) => <Term key={name} name={name}>{why}</Term>)}
          </dl>
        </section>
      ))}

      <p className="max-w-[80ch] text-sm text-pretty text-muted-foreground">
        Pełne wyniki są w katalogu <code className="text-xs">research/experiments/</code>: wdrożenie i jego efekt w{" "}
        <code className="text-xs">integration.md</code>, pozostałe eksperymenty na gałęziach <code className="text-xs">exp/*</code>.
      </p>
    </div>
  )
}

function Term({ name, children }: { name: ReactNode; children: ReactNode }) {
  return (
    <div className="grid gap-1 px-4 py-3 sm:grid-cols-[16rem_1fr] sm:gap-4">
      <dt className="font-medium">{name}</dt>
      <dd className="text-pretty text-muted-foreground">{children}</dd>
    </div>
  )
}
