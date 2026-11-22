import type { ReactNode } from "react"
import { Link } from "react-router"

import { PageHeader } from "@/components/common"
import { BASELINE, CORPUS, CRITERION, EXPERIMENTS, REJECTED, type RejectedFeature, type Stage } from "@/data/rejected-features"

const SECTIONS: { id: string; stage: Stage; title: string; intro: string }[] = [
  {
    id: "eksperymenty",
    stage: "experiment",
    title: "Odrzucone po eksperymencie",
    intro: "Cechy i warianty zmierzone na korpusie. Każda grupa odpowiada jednemu eksperymentowi; nazwa gałęzi wskazuje skrypt i pełny opis wyników.",
  },
  {
    id: "profilowanie",
    stage: "profiling",
    title: "Wykluczone po przeglądzie korpusu",
    intro: "Cechy sprawdzone przed eksperymentami przez policzenie, jak często występują. Okazały się zbyt rzadkie albo zbyt jednolite, żeby je mierzyć.",
  },
  {
    id: "literatura",
    stage: "literature",
    title: "Wykluczone na podstawie literatury",
    intro: "Cechy opisane w publikacjach i narzędziach, których nie testowano, bo nie da się ich wyliczyć z materiałów produktu albo wskazują narzędzie zamiast operatora.",
  },
]

const count = (stage: Stage) => REJECTED.filter((f) => f.stage === stage).length

export default function RejectedFeaturesPage() {
  const glossary = <Link to="/glossary" className="underline underline-offset-4">Słowniczku</Link>
  return (
    <div className="max-w-5xl space-y-8">
      <PageHeader
        title="Odrzucone cechy"
        description="Cechy, które rozważano jako dodatkowe sygnały łączenia materiałów w kampanie i których nie przyjęto, wraz z wynikami i powodem odrzucenia."
      />

      <div className="max-w-[80ch] space-y-2 text-sm leading-relaxed text-pretty text-muted-foreground">
        <p>
          Liczby pochodzą z {CORPUS.pages} stron z listy CERT Polska zeskanowanych w urlscan.io, czyli z {CORPUS.pairs} par stron z różnych domen.
          Na tych samych stronach obecna metoda produktu ma precyzję {BASELINE.precision}, odsetek fałszywych połączeń {BASELINE.falseLinks} i
          czułość na parach pewnych {BASELINE.recall}; największa kampania liczy {BASELINE.largest} stron.
        </p>
        <p>
          Cechę uznawano za działającą, gdy osiągała precyzję co najmniej {CRITERION.precision} przy odsetku fałszywych połączeń najwyżej{" "}
          {CRITERION.falseLinks}, znajdowała pary pomijane przez produkt i po dodaniu do grupowania nie łączyła niezwiązanych kampanii.
          Zapis „a → b” oznacza zmianę wartości po dodaniu cechy do grupowania produktu.
        </p>
      </div>

      <nav aria-label="Sekcje strony">
        <ul className="flex flex-wrap gap-2 text-sm">
          {SECTIONS.map((s) => (
            <li key={s.id}>
              <a href={`#${s.id}`} className="block rounded-full border px-3 py-1 text-muted-foreground hover:bg-muted hover:text-foreground">
                {s.title} <span className="tabular-nums">({count(s.stage)})</span>
              </a>
            </li>
          ))}
          <li>
            <a href="#miary" className="block rounded-full border px-3 py-1 text-muted-foreground hover:bg-muted hover:text-foreground">Jak czytać liczby</a>
          </li>
        </ul>
      </nav>

      {SECTIONS.map((s) => (
        <section key={s.id} id={s.id} className="scroll-mt-20 space-y-4">
          <div className="space-y-1">
            <h2 className="text-lg font-semibold">{s.title}</h2>
            <p className="max-w-[80ch] text-sm text-pretty text-muted-foreground">{s.intro}</p>
          </div>
          {s.stage === "experiment" ? (
            EXPERIMENTS.map((e) => {
              const items = REJECTED.filter((f) => f.stage === "experiment" && f.branch === e.branch)
              if (!items.length) return null
              return (
                <div key={e.branch} className="space-y-2">
                  <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
                    <h3 className="font-medium">{e.title}</h3>
                    <code className="text-xs text-muted-foreground">{e.branch}</code>
                  </div>
                  <p className="max-w-[80ch] text-sm text-pretty text-muted-foreground">{e.question}</p>
                  <FeatureList items={items} nested />
                </div>
              )
            })
          ) : (
            <FeatureList items={REJECTED.filter((f) => f.stage === s.stage)} />
          )}
        </section>
      ))}

      <section id="miary" className="scroll-mt-20 space-y-3">
        <div className="space-y-1">
          <h2 className="text-lg font-semibold">Jak czytać liczby</h2>
          <p className="max-w-[80ch] text-sm text-pretty text-muted-foreground">
            Korpus nie ma etykiet operatorów. Pary ocenia się według pięciu niezależnych wskazań (referencji): ten sam szablon tytułu strony po
            zamaskowaniu nazwy marki, ten sam dedykowany adres IP, certyfikaty TLS wystawione w tej samej minucie, niemal identyczny zrzut ekranu
            oraz ten sam odcisk zestawu phishingowego. Większość referencji wskazuje ten sam zestaw, a nie tego samego operatora.
            Pojęcia must-link i miary treści są opisane w {glossary}.
          </p>
        </div>
        <dl className="divide-y rounded-lg border text-sm leading-relaxed">
          <Term name="Precyzja">Udział par połączonych przez cechę, które potwierdza co najmniej jedna referencja, wśród par dających się ocenić.</Term>
          <Term name="Fałszywe połączenia">
            Udział par uznanych za niepowiązane, które cecha mimo to łączy. Para jest uznana za niepowiązaną, gdy obie strony mają dość cech kodu,
            żeby dało się je porównać, nie potwierdza jej żadna referencja, mają różne zestawy phishingowe i różnych dostawców hostingu.
          </Term>
          <Term name="Pary pewne">Pary potwierdzone przez co najmniej dwie referencje.</Term>
          <Term name="Czułość na parach pewnych">Udział par pewnych, które metoda łączy.</Term>
          <Term name="Odzyskane pary pominięte">Udział par pewnych pomijanych przez produkt, które cecha łączy.</Term>
          <Term name="Nowe pary, precyzja nowych par">Pary, których produkt nie umieszcza w jednej kampanii, oraz precyzja liczona tylko na nich.</Term>
          <Term name="Największa kampania">
            Liczba stron w największej grupie po dodaniu cechy. Wzrost oznacza, że cecha łączy przechodnio kampanie, które produkt rozdziela.
          </Term>
          <Term name="AUC">
            Prawdopodobieństwo, że para pewna otrzyma wyższy wynik niż para niepowiązana. Wartość 0.5 oznacza ranking losowy, 1 bezbłędny.
          </Term>
          <Term name="Szósta miara">Cecha dodana jako kolejna miara podobieństwa treści do średniej, z której liczona jest odległość d.</Term>
          <Term name="Odcisk zestawu">
            Zbiór cech kodu strony (między innymi identyfikatory elementów i skróty skryptów) porównywany ważonym współczynnikiem Jaccarda.
            W badaniu służy jako referencja i nie jest częścią produktu.
          </Term>
        </dl>
      </section>

      <p className="max-w-[80ch] text-sm text-pretty text-muted-foreground">
        Cechy, które się sprawdziły, są opisane na gałęziach eksperymentów w katalogu <code className="text-xs">research/experiments/</code>.
      </p>
    </div>
  )
}

function FeatureList({ items, nested = false }: { items: RejectedFeature[]; nested?: boolean }) {
  const Heading = nested ? "h4" : "h3"
  return (
    <ul className="divide-y rounded-lg border text-sm leading-relaxed">
      {items.map((f) => (
        <li key={f.name} className="space-y-2 px-4 py-3">
          <Heading className="font-medium">{f.name}</Heading>
          <p className="max-w-[80ch] text-pretty text-muted-foreground">{f.tried}</p>
          {f.metrics.length > 0 && (
            <dl className="flex flex-wrap gap-1.5">
              {f.metrics.map((m) => (
                <div key={m.label} className="flex items-baseline gap-1.5 rounded bg-muted px-2 py-0.5 text-xs">
                  <dt className="text-muted-foreground">{m.label}</dt>
                  <dd className="font-medium tabular-nums">{m.value}</dd>
                </div>
              ))}
            </dl>
          )}
          <p className="max-w-[80ch] text-pretty">
            <span className="font-medium">Powód odrzucenia: </span>
            {f.reason}
          </p>
        </li>
      ))}
    </ul>
  )
}

function Term({ name, children }: { name: ReactNode; children: ReactNode }) {
  return (
    <div className="grid gap-1 px-4 py-3 sm:grid-cols-[13rem_1fr] sm:gap-4">
      <dt className="font-medium">{name}</dt>
      <dd className="text-pretty text-muted-foreground">{children}</dd>
    </div>
  )
}
