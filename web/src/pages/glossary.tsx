import type { ReactNode } from "react"
import { Link } from "react-router"

import type { Methodology } from "@/lib/api"
import { useApi } from "@/lib/format"
import { ErrorState, Loading, PageHeader, RelationBadge } from "@/components/common"

const SECTIONS = [
  ["dane", "Dane wejściowe"],
  ["identyfikatory", "Cechy: identyfikatory"],
  ["tresc", "Cechy: treść"],
  ["opisowe", "Cechy opisowe"],
  ["grupowanie", "Grupowanie w kampanie"],
  ["relacje", "Relacja pary"],
  ["nowy", "Klasyfikacja nowego materiału"],
  ["porownanie", "Porównanie metod grupowania"],
  ["ewaluacja", "Ewaluacja"],
] as const

const pct = (x: number) => `${Math.round(x * 100)}%`
const sentence = (t: string) => `${t.charAt(0).toUpperCase()}${t.slice(1)}.`

/** What each identifier group contains and where it is read from. The type list under it comes from the API. */
const GROUP_TEXT: Record<string, string> = {
  ad_library: "Numer reklamy i numer konta reklamodawcy nadane przez bibliotekę reklam platformy.",
  domains:
    "Domena rejestrowalna (eTLD+1) strony docelowej, kolejnych przekierowań i systemu dystrybucji ruchu (TDS) oraz domena odczytana z kreacji przez OCR. " +
    "Domeny usług ogólnodostępnych, np. CDN i analityki, są pomijane. Na hostingu współdzielonym porównywany jest pełny host klienta.",
  tracking_ids:
    "Identyfikatory kont w usługach analitycznych i reklamowych zapisane w kodzie strony (Facebook Pixel, TikTok Pixel, Google Analytics, Tag Manager, Google Ads), " +
    "identyfikator konta w kreatorze stron oraz parametry afiliacyjne i identyfikatory kampanii w adresie URL.",
  contacts: "Numer telefonu, adres e-mail, konto Telegram lub WhatsApp, adres portfela kryptowalut znalezione w treści strony albo reklamy.",
  kit_files:
    "Elementy zestawu phishingowego (phishing kit): skrót SHA-1 treści skryptu, żądanie do backendu (metoda i ścieżka, części zmienne zamaskowane), " +
    "adres, na który formularz wysyła dane, oraz szablon ścieżki URL.",
  product: "Nazwa reklamowanego produktu lub platformy, wyodrębniona przez model językowy albo reguły słownikowe.",
}

const DECISION_TEXT = (c: Methodology["constants"]): Record<string, string> => ({
  duplicate: `Ten sam plik, ten sam numer reklamy albo d ≤ ${c.duplicate_cut} względem materiału w bazie.`,
  known_campaign: `Wspólny identyfikator z kampanią w bazie albo najbliższy sąsiad w odległości d ≤ ${c.campaign_cut}.`,
  merge_proposal: "Wspólne identyfikatory z dwiema kampaniami jednocześnie. Kampanie mogą być jedną i wymagają decyzji analityka.",
  new_campaign: `Brak wspólnego identyfikatora i d > ${c.campaign_cut} do każdego materiału w bazie.`,
})

export default function GlossaryPage() {
  const { data: m, error, isLoading } = useApi<Methodology>("/api/methodology")
  if (isLoading) return <Loading rows={4} />
  if (error || !m) return <ErrorState error={error} />
  const c = m.constants
  const decisionText = DECISION_TEXT(c)
  const view = (id: string) => m.views.find((v) => v.view === id)?.label ?? id
  const space = <Link to="/space" className="underline underline-offset-4">Przestrzeń cech</Link>

  return (
    <div className="max-w-5xl space-y-8">
      <PageHeader
        title="Słowniczek"
        description="Cechy wyodrębniane z materiału oraz metody ich porównywania i grupowania. Progi są odczytywane z bieżącej konfiguracji."
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

      <Group id="dane" title="Dane wejściowe">
        <Term name="Materiał">Jednostka analizy: reklama (zrzut ekranu, wideo lub tekst) wraz ze stroną docelową, jeśli udało się ją pobrać.</Term>
        <Term name="Kreacja reklamowa">Treść samej reklamy: obraz, klatki wideo, tekst.</Term>
        <Term name="Strona docelowa (landing page)">Strona, do której prowadzi reklama. Źródło tekstu, kodu HTML, obrazów i większości identyfikatorów.</Term>
        <Term name="Kampania">Grupa materiałów przypisanych jednemu operatorowi: mają wspólny identyfikator albo odległość treści d ≤ {c.campaign_cut}.</Term>
        <Term name="Rodzina kampanii">
          Kampanie o podobnej treści, ale bez wspólnego identyfikatora (d ≤ {c.family_cut}). Zwykle ten sam zestaw phishingowy użyty przez różnych operatorów.
        </Term>
      </Group>

      <Group
        id="identyfikatory"
        title="Cechy: identyfikatory"
        intro="Wartości porównywane dokładnie: dwa materiały mają tę samą wartość albo nie. W panelu każda wyodrębniona wartość jest nazywana śladem."
      >
        {m.identifier_groups.map((g) => (
          <Term key={g.group} name={g.label}>
            {GROUP_TEXT[g.group] ?? g.hint}
            <span className="mt-0.5 block text-xs text-muted-foreground">{g.types.map((t) => t.label).join(" · ")}</span>
          </Term>
        ))}
        <Term name="Identyczny plik">Ten sam skrót SHA-256 pliku w obu materiałach. Para jest duplikatem.</Term>
      </Group>

      <Group
        id="tresc"
        title="Cechy: treść"
        intro="Pięć miar podobieństwa treści, każda w skali od 0 do 1. Decydują o grupowaniu, gdy materiały nie mają wspólnego identyfikatora."
      >
        <Term name={view("text")}>
          Współczynnik Jaccarda zbiorów 4-gramów słów w tekście strony docelowej, szacowany metodą MinHash ze 128 permutacjami (Broder 1997).
          Przed porównaniem imiona i nazwiska są zastępowane znacznikiem, żeby ta sama osoba w dwóch tekstach nie zawyżała podobieństwa.
        </Term>
        <Term name={view("ocr")}>Ta sama miara na tekście reklamy: tekst odczytany przez OCR ze zrzutów i klatek wideo oraz treść reklamy.</Term>
        <Term name={view("semantic")}>
          Podobieństwo kosinusowe wektorów tekstu (embeddingów) z modelu multilingual-e5-small. Od każdego wektora odejmowana jest średnia z bazy
          (Mu i Viswanath 2018), ponieważ teksty z jednej dziedziny mają wysokie podobieństwo wyjściowe.
        </Term>
        <Term name={view("html")}>
          Współczynnik Jaccarda 5-gramów kolejnych znaczników HTML, szacowany metodą MinHash (Cui i in. 2017). Wykrywa ten sam szablon strony przy zmienionym tekście.
        </Term>
        <Term name={view("images")}>
          Udział obrazów mniejszego zbioru, które mają w drugim materiale odpowiednik: odległość Hamminga między 64-bitowymi skrótami percepcyjnymi pHash
          nie przekracza {c.phash_hamming} bitów (Zauner 2010). Skrót pHash nie zmienia się istotnie po kompresji i przeskalowaniu obrazu.
        </Term>
        <Term name="Współczynnik Jaccarda">
          <Formula>J(A, B) = |A ∩ B| / |A ∪ B|</Formula>
          Udział elementów wspólnych w sumie dwóch zbiorów. Tutaj elementami są n-gramy.
        </Term>
        <Term name="n-gram">Ciąg n kolejnych elementów: 4 słów w tekście, 5 znaczników w HTML. Zgodne n-gramy oznaczają skopiowany fragment, a nie tylko te same słowa.</Term>
        <Term name="MinHash">Podpis zbioru o stałej długości. Udział zgodnych pozycji w dwóch podpisach jest estymatorem współczynnika Jaccarda.</Term>
      </Group>

      <Group
        id="opisowe"
        title="Cechy opisowe"
        intro="Widoczne w panelu, ale nieużywane do łączenia materiałów, bo ta sama wartość występuje w niezależnych kampaniach."
      >
        <Term name="Osoby">
          Twarze wykrywa detektor SCRFD (wynik ≥ {c.face_det_threshold}, bok twarzy ≥ {c.face_min_side} px). Wektor ArcFace każdej twarzy jest porównywany
          z bazą referencyjną; dopasowanie wymaga podobieństwa kosinusowego ≥ {c.face_match_threshold}. Nazwiska są też wyszukiwane w tekście.
        </Term>
        <Term name="Typ oszustwa, marka, medium">Atrybuty przypisywane przez model językowy albo reguły słownikowe: typ oszustwa oraz marka i medium, pod które podszywa się materiał.</Term>
        <Term name="Adres IP, nazwa reklamodawcy">Zapisywane jako kontekst. Ten sam serwer lub ta sama nazwa nie wskazują jednego operatora.</Term>
      </Group>

      <Group id="grupowanie" title="Grupowanie w kampanie">
        <Term name="Ograniczenie must-link">
          Dwa materiały ze wspólnym identyfikatorem należą do jednej kampanii niezależnie od treści. Relacja jest przechodnia: jeśli A łączy się z B, a B z C,
          wszystkie trzy trafiają do tej samej kampanii.
        </Term>
        <Term name="Częstość dokumentowa (df)">
          Liczba materiałów, w których występuje dana wartość. Wartość jest identyfikatorem tylko wtedy, gdy df / N ≤ {pct(c.max_df)}; wartości powszechne
          nie wskazują operatora (ta sama idea co IDF, Spärck Jones 1972). Wartość obecna w co najwyżej dwóch materiałach jest uwzględniana zawsze.
        </Term>
        <Term name="Odległość treści d">
          <Formula>d = 1 − średnia podobieństw s z miar dostępnych dla obu materiałów</Formula>
          Współczynnik Gowera (1971): miara niedostępna dla jednego z materiałów jest pomijana, a nie liczona jako 0. Gdy żadna miara nie jest dostępna dla obu, d = 1.
        </Term>
        <Term name="Odległość D">
          <Formula>D = 0 dla materiałów połączonych identyfikatorem, w pozostałych parach D = d</Formula>
          Macierz D jest wejściem grupowania.
        </Term>
        <Term name="Grupowanie hierarchiczne, metoda średnich połączeń (UPGMA)">
          W każdym kroku łączone są dwie najbliższe grupy. Odległość między grupami to średnia D po wszystkich parach materiałów z obu grup.
          Kolejność połączeń zapisuje dendrogram.
        </Term>
        <Term name="Progi cięcia dendrogramu">
          Cięcie na wysokości {c.duplicate_cut} wyznacza duplikaty, na {c.campaign_cut} kampanie, na {c.family_cut} rodziny kampanii.
        </Term>
        <Term name="Podobieństwo pary p">
          <Formula>p = 1 przy wspólnym identyfikatorze, w przeciwnym razie p = 1 − d</Formula>
          W panelu podpisane jako bliskość. Służy do sortowania par i wyznacza grubość linii na grafie.
        </Term>
      </Group>

      <Group id="relacje" title="Relacja pary" intro="Wynik porównania dwóch materiałów z bazy, od najsilniejszej.">
        {m.relations.map((r) => <Term key={r.relation} name={<RelationBadge relation={r.relation} />}>{sentence(r.hint)}</Term>)}
      </Group>

      <Group id="nowy" title="Klasyfikacja nowego materiału" intro="Nowy materiał jest porównywany ze wszystkimi materiałami w bazie. Wynikiem jest jedna z czterech decyzji.">
        <Term name="Najbliższy sąsiad (1-NN) z progiem odrzucenia">
          Materiał bez wspólnego identyfikatora otrzymuje kampanię najbliższego materiału w bazie, jeśli d ≤ {c.campaign_cut} (Cover i Hart 1967).
          Powyżej progu nie jest przypisywany do żadnej znanej kampanii (rozpoznawanie w zbiorze otwartym, open-set).
        </Term>
        {m.decisions.map((d) => <Term key={d.decision} name={d.label}>{decisionText[d.decision] ?? d.hint}</Term>)}
      </Group>

      <Group
        id="porownanie"
        title="Porównanie metod grupowania"
        intro={<>Strona {space} stosuje kilka metod do tych samych macierzy odległości. Kampanie w panelu wyznacza pierwsza z nich; pozostałe są punktem odniesienia.</>}
      >
        <Term name="FakeTrace">Metoda średnich połączeń (UPGMA) na odległości D, czyli z ograniczeniami must-link, cięta na wysokości {c.campaign_cut}.</Term>
        <Term name="Sama treść">Ta sama metoda i ten sam próg na odległości d, bez identyfikatorów. Różnica względem FakeTrace pokazuje wkład identyfikatorów.</Term>
        <Term name="Pojedyncze wiązanie (single linkage)">
          Odległość między grupami to odległość najbliższej pary. Grupy mogą łączyć się przez pojedyncze materiały pośrednie (efekt łańcuchowy).
        </Term>
        <Term name="Pełne wiązanie (complete linkage)">Odległość między grupami to odległość najdalszej pary. Grupy są mniejsze i bardziej jednorodne.</Term>
        <Term name="HDBSCAN">
          Grupowanie gęstościowe bez progu odległości, najmniejsza grupa to 2 materiały (Campello i in. 2013). Materiały poza obszarami gęstymi są oznaczane jako szum.
        </Term>
        <Term name="Louvain">
          Wykrywanie społeczności w grafie przez maksymalizację modularności (Blondel i in. 2008). Wierzchołkami są materiały, krawędziami pary powiązane, wagą p.
        </Term>
        <Term name="MDS">
          Klasyczne skalowanie wielowymiarowe (Torgerson 1952): rozmieszcza materiały na płaszczyźnie tak, by odległości na rysunku odpowiadały d.
          Wynik jest deterministyczny i najlepiej zachowuje duże odległości.
        </Term>
        <Term name="t-SNE">
          Rzut zachowujący sąsiedztwo (van der Maaten i Hinton 2008). Bliskie materiały leżą obok siebie; odległości między odległymi grupami nie podlegają interpretacji.
        </Term>
        <Term name="Współczynnik silhouette">
          Dla każdego materiału porównuje średnią odległość do własnej grupy ze średnią odległością do najbliższej obcej grupy, w skali od −1 do 1 (Rousseeuw 1987).
          Wysoka średnia oznacza grupy zwarte i rozdzielone.
        </Term>
        <Term name="Skorygowany indeks Randa (ARI)">Zgodność dwóch podziałów tego samego zbioru (Hubert i Arabie 1985): 1 oznacza podziały identyczne, wartość bliska 0 zgodność losową.</Term>
      </Group>

      <Group id="ewaluacja" title="Ewaluacja" intro={<>Uruchamiana z wiersza poleceń: <code className="text-xs">python tools/evaluate.py --labels data/labels_dane.csv</code>.</>}>
        <Term name="Leave-one-out">
          Każdy materiał jest kolejno usuwany z bazy i klasyfikowany ponownie. Oczekiwany wynik to jego kampania, a dla materiału, który był w kampanii sam, nowa kampania.
        </Term>
        <Term name="Warianty syntetyczne">
          Zmodyfikowane kopie materiału: sama kreacja, sama strona docelowa, obraz po ponownej kompresji, zmieniona domena, zmienione nazwisko.
          Oczekiwany wynik to kampania materiału źródłowego.
        </Term>
        <Term name="Precyzja, czułość i F1 dla par">
          Każda para materiałów jest decyzją binarną „ta sama kampania” i jest porównywana z etykietą. F1 to średnia harmoniczna precyzji i czułości.
        </Term>
        <Term name="B-cubed">
          Precyzja i czułość liczone osobno dla każdego materiału i uśredniane (Bagga i Baldwin 1998). Precyzja: jaka część jego grupy ma tę samą etykietę.
          Czułość: jaka część materiałów z tą etykietą znalazła się w jego grupie.
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
