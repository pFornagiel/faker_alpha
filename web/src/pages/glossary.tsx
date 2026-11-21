import type { ReactNode } from "react"
import { Link } from "react-router"

import type { Methodology } from "@/lib/api"
import { useApi } from "@/lib/format"
import { ErrorState, Loading, PageHeader, RelationBadge } from "@/components/common"

const SECTIONS = [
  ["pojecia", "Podstawowe pojęcia"],
  ["identyfikatory", "Co porównujemy: identyfikatory"],
  ["widoki", "Co porównujemy: treść"],
  ["miary", "Miary"],
  ["wyniki", "Relacje pary"],
  ["decyzje", "Decyzje"],
  ["grupowanie", "Grupowanie i przestrzeń cech"],
  ["jakosc", "Testy jakości"],
] as const

const pct = (x: number) => `${Math.round(x * 100)}%`

export default function GlossaryPage() {
  const { data: m, error, isLoading } = useApi<Methodology>("/api/methodology")
  if (isLoading) return <Loading rows={4} />
  if (error || !m) return <ErrorState error={error} />
  const c = m.constants

  return (
    <div className="max-w-5xl space-y-8">
      <PageHeader
        title="Słowniczek"
        description={<>
          Krótkie definicje: co porównujemy między dwoma materiałami i jakimi miarami. Progi i listy są pobierane z bieżącej konfiguracji.
          Porównanie metod grupowania na tych samych danych: <Link to="/space" className="underline underline-offset-4">Przestrzeń cech</Link>.
        </>}
      />

      <nav aria-label="Sekcje słowniczka">
        <ul className="flex flex-wrap gap-2 text-sm">
          {SECTIONS.map(([id, label]) => (
            <li key={id}>
              <a href={`#${id}`} className="block rounded-full border px-3 py-1 text-muted-foreground hover:bg-muted hover:text-foreground">{label}</a>
            </li>
          ))}
        </ul>
      </nav>

      <Group id="pojecia" title="Podstawowe pojęcia">
        <Term name="Materiał">Jeden przypadek w bazie: reklama (zrzut, wideo lub tekst) razem z tym, co udało się zebrać ze strony, do której prowadzi.</Term>
        <Term name="Kreacja">To, co widać w samej reklamie: obraz, klatki wideo, tekst reklamy.</Term>
        <Term name="Strona docelowa">Strona, na którą prowadzi reklama (landing page). Daje tekst strony, strukturę HTML i większość śladów technicznych.</Term>
        <Term name="Ślad">Każda wartość wyciągnięta z materiału, np. domena, piksel, telefon, osoba. Ślad jest albo identyfikatorem (łączy), albo opisem (nie łączy).</Term>
        <Term name="Identyfikator">Ślad, który łączy: ta sama wartość w dwóch materiałach oznacza tę samą kampanię (połączenie pewne, must-link).</Term>
        <Term name="Ślad opisowy">
          Osoby, typ oszustwa, rejestrator, IP, nazwa reklamodawcy. Pokazujemy je, ale nie łączą materiałów: ten sam celebryta czy hosting pojawia się
          w wielu niezależnych kampaniach.
        </Term>
        <Term name="Kampania">Grupa materiałów, za którą najpewniej stoi ten sam operator. Łączy je identyfikator albo bardzo podobna treść (d ≤ {c.campaign_cut}).</Term>
        <Term name="Rodzina kampanii">Kampanie o podobnej treści, ale bez wspólnego identyfikatora (d ≤ {c.family_cut}). Często ten sam szablon u różnych operatorów.</Term>
      </Group>

      <Group
        id="identyfikatory"
        title="Co porównujemy: identyfikatory"
        intro={<>
          Porównanie dokładne: wartość jest wspólna albo nie. Liczy się tylko wartość obecna w co najwyżej {pct(c.max_df)} materiałów (zob. <i>df</i> niżej).
        </>}
      >
        {m.identifier_groups.map((g) => (
          <Term key={g.group} name={g.label}>
            {g.hint}
            <span className="mt-0.5 block text-xs text-muted-foreground">{g.types.map((t) => t.label).join(" · ")}</span>
          </Term>
        ))}
        <Term name="identyczny plik">Ten sam plik (skrót sha256) w obu materiałach, czyli duplikat.</Term>
      </Group>

      <Group
        id="widoki"
        title="Co porównujemy: treść"
        intro="Gdy brak wspólnego identyfikatora, porównujemy treść w kilku widokach. Każdy widok daje podobieństwo s od 0 (nic wspólnego) do 1 (identyczne)."
      >
        {m.views.map((v) => <Term key={v.view} name={v.label}>{v.hint}</Term>)}
      </Group>

      <Group id="miary" title="Miary">
        <Term name="Odległość treści d">
          <Formula>d = 1 − średnia s z widoków dostępnych po obu stronach</Formula>
          Brakujący widok jest pomijany, a nie liczony jako 0. Gdy żaden widok nie jest wspólny, d = 1 i para jest nieporównywalna (współczynnik Gowera).
        </Term>
        <Term name="Bliskość p">
          <Formula>p = 1 przy wspólnym identyfikatorze, w przeciwnym razie p = 1 − d</Formula>
          Jedna liczba do sortowania i kolorowania par. Para z p = 1 i dużym d jest połączona identyfikatorem mimo innej treści.
        </Term>
        <Term name="df i MAX_DF">
          <i>df</i> to liczba materiałów, w których występuje dana wartość. Wartość liczy się jako identyfikator tylko, gdy df / N ≤ {pct(c.max_df)}.
          Zbyt popularne wartości, np. wspólny CDN, są pomijane. Wartość, którą mają tylko dwa porównywane materiały, liczy się zawsze.
        </Term>
        <Term name="Jaccard / MinHash">
          <Formula>J(A, B) = |A ∩ B| / |A ∪ B|</Formula>
          Udział wspólnych fragmentów (n-gramów) w obu tekstach. MinHash szybko przybliża J przy pomocy krótkich podpisów.
        </Term>
        <Term name="n-gram">Ciąg n kolejnych elementów: 4 słowa dla tekstu, 5 znaczników dla HTML. Porównanie n-gramów wyłapuje przeklejone fragmenty, a nie tylko te same słowa.</Term>
        <Term name="Maskowanie osób">Przed porównaniem tekstu imiona i nazwiska są zastępowane znacznikiem, żeby ten sam celebryta nie zbliżał niezależnych kampanii.</Term>
        <Term name="Cosinus embeddingów">
          Podobieństwo znaczenia dwóch tekstów jako cosinus kąta między ich wektorami (model multilingual-e5-small). Najpierw odejmujemy średni wektor
          bazy, żeby wspólny „język oszustwa” nie zawyżał wyników.
        </Term>
        <Term name="pHash i odległość Hamminga">
          pHash to 64-bitowy odcisk obrazu odporny na kompresję i skalowanie. Dwa obrazy pasują, gdy odciski różnią się na co najwyżej {c.phash_hamming} bitach.
          Widok „obrazy” to odsetek obrazów mniejszego zbioru, które mają taki odpowiednik.
        </Term>
        <Term name="Odległość do grupowania D">D = 0 dla materiałów połączonych identyfikatorem, także pośrednio przez inne materiały. W pozostałych przypadkach D = d.</Term>
        <Term name="Średnie wiązanie i dendrogram">
          Grupowanie hierarchiczne (UPGMA): krok po kroku łączymy dwie najbliższe grupy, a odległość między grupami to średnie D wszystkich par.
          Dendrogram rysuje te złączenia; cięcie na wysokości {c.campaign_cut} daje kampanie, a na wysokości {c.family_cut} rodziny.
        </Term>
        <Term name="Najbliższy sąsiad (1-NN)">Nowy materiał bez wspólnego identyfikatora trafia do kampanii najbliższego znanego materiału, jeśli d ≤ {c.campaign_cut}. W przeciwnym razie to nowy wzorzec.</Term>
      </Group>

      <Group id="wyniki" title="Relacje pary" intro="Wynik porównania dwóch materiałów z bazy.">
        {m.relations.map((r) => <Term key={r.relation} name={<RelationBadge relation={r.relation} />}>{r.hint}</Term>)}
      </Group>

      <Group id="decyzje" title="Decyzje dla nowego materiału" intro="Wynik analizy nowego materiału względem całej bazy.">
        {m.decisions.map((d) => <Term key={d.decision} name={d.label}>{d.hint}</Term>)}
      </Group>

      <Group id="grupowanie" title="Grupowanie i przestrzeń cech" intro={<>Metody, które można porównać na stronie <Link to="/space" className="underline underline-offset-4">Przestrzeń cech</Link>. Kampanie w całym panelu wyznacza metoda FakeTrace; pozostałe są punktem odniesienia.</>}>
        <Term name="FakeTrace (UPGMA z must-link)">
          Materiały ze wspólnym identyfikatorem są sklejane na stałe (odległość D = 0), resztę łączy średnie wiązanie (UPGMA) na odległości treści d.
          Drzewo jest cięte na wysokości {c.campaign_cut}: wszystko, co połączyło się niżej, to jedna kampania.
        </Term>
        <Term name="Sama treść">To samo średnie wiązanie i ten sam próg, ale bez identyfikatorów. Pokazuje, ile kampanii dałoby się znaleźć wyłącznie po treści.</Term>
        <Term name="Pojedyncze wiązanie">Dwie grupy łączą się, gdy choć jedna para jest bliżej niż próg. Jeden materiał-łącznik potrafi skleić odległe grupy (efekt łańcucha).</Term>
        <Term name="Pełne wiązanie">Dwie grupy łączą się dopiero, gdy każda para jest bliżej niż próg. Daje ciasne, ostrożne grupy.</Term>
        <Term name="HDBSCAN">Szuka gęstych skupisk bez progu odległości. Materiały spoza gęstych skupisk oznacza jako szum zamiast na siłę przypisywać je do grupy.</Term>
        <Term name="Louvain">Wykrywanie społeczności w grafie powiązań: dzieli graf tak, by krawędzi wewnątrz grup było dużo, a między grupami mało.</Term>
        <Term name="MDS">Skalowanie wielowymiarowe: rozkłada materiały na płaszczyźnie tak, by odległości na rysunku jak najwierniej oddawały odległości d. Deterministyczne; dobrze zachowuje duże odległości.</Term>
        <Term name="t-SNE">Rzut zachowujący sąsiedztwo: bliskie materiały lądują obok siebie, ale odległości między dalekimi grupami nic nie znaczą.</Term>
        <Term name="Silhouette">Dla każdego materiału: o ile bliżej mu do własnej grupy niż do najbliższej obcej, od −1 do 1. Średnia mówi, czy grupy są zwarte i rozdzielone.</Term>
        <Term name="ARI">Skorygowany indeks Randa: zgodność dwóch podziałów. 1 = identyczny podział, ok. 0 = jak losowy.</Term>
      </Group>

      <Group id="jakosc" title="Testy jakości" intro={<>Uruchamiane z wiersza poleceń: <code className="text-xs">python tools/evaluate.py --labels data/labels_dane.csv</code>.</>}>
        <Term name="Usuń i przypisz ponownie">Materiał usuwamy z bazy i analizujemy od nowa. Powinien wrócić do swojej kampanii, a materiał, który był w bazie sam, powinien zostać rozpoznany jako nowy wzorzec.</Term>
        <Term name="Sztuczny wariant">Zmieniona kopia materiału (przycięty zrzut, podmieniona domena, inne nazwisko…). Powinna trafić do kampanii materiału źródłowego.</Term>
        <Term name="F1 par">Dla każdej pary: czy decyzja „ta sama kampania / nie” zgadza się z etykietą. F1 łączy precyzję i kompletność tych decyzji (1 = wszystkie trafne).</Term>
        <Term name="B-cubed P / R">
          Liczone z perspektywy każdego materiału. Precyzja: jaka część jego kampanii naprawdę do niej należy. Kompletność: jaką część prawdziwej kampanii odnaleziono.
        </Term>
      </Group>
    </div>
  )
}

function Group({ id, title, intro, children }: { id: string; title: string; intro?: ReactNode; children: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-20 space-y-3">
      <div className="space-y-1">
        <h2 className="text-lg font-semibold">{title}</h2>
        {intro && <p className="max-w-[80ch] text-sm text-pretty text-muted-foreground">{intro}</p>}
      </div>
      <dl className="divide-y rounded-lg border text-sm leading-relaxed">{children}</dl>
    </section>
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

function Formula({ children }: { children: ReactNode }) {
  return <code className="mb-1 block w-fit rounded bg-muted px-2 py-0.5 text-xs text-foreground">{children}</code>
}
