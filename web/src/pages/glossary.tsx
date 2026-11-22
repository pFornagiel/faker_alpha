import type { ReactNode } from "react"
import { Link } from "react-router"

import type { Methodology } from "@/lib/api"
import { useApi } from "@/lib/format"
import { ErrorState, Loading, PageHeader, RelationBadge } from "@/components/common"

const SECTIONS = [
  ["podstawy", "Podstawowe pojęcia"],
  ["identyfikatory", "Identyfikatory"],
  ["tresc", "Podobieństwo treści"],
  ["opisowe", "Cechy, które nie łączą"],
  ["grupowanie", "Jak powstają kampanie"],
  ["relacje", "Relacja pary"],
  ["nowy", "Nowy materiał"],
  ["porownanie", "Inne metody grupowania"],
  ["ewaluacja", "Ocena wyników"],
] as const

const pct = (x: number) => `${Math.round(x * 100)}%`

/** What each identifier group contains, in plain words. Falls back to the API hint for a group not listed here. */
const GROUP_TEXT: Record<string, string> = {
  ad_library: "Numer reklamy i numer konta reklamodawcy w bibliotece reklam platformy.",
  domains:
    "Domena strony docelowej, domeny z przekierowań, adres systemu rozdzielającego ruch (TDS) i domena widoczna na samej reklamie. " +
    "Porównywana jest domena główna: sklep.example.pl liczy się jako example.pl. Na hostingu współdzielonym porównywany jest pełny adres klienta. " +
    "Domeny popularnych usług, np. CDN i analityki, są pomijane.",
  certificates:
    "Minuta, w której wystawiono certyfikat TLS strony. Operator, który zamawia certyfikaty dla wielu domen naraz, dostaje je w tej samej minucie. " +
    "Liczy się tylko certyfikat wystawiony dla samej domeny, bo platformy hostingowe dają jeden wspólny certyfikat wszystkim klientom.",
  tracking_ids:
    "Numery kont w usługach analitycznych i reklamowych zapisane w kodzie strony (Facebook Pixel, TikTok Pixel, Google Analytics, Tag Manager, Google Ads), " +
    "numer konta w kreatorze stron oraz parametry afiliacyjne i numery kampanii w adresie URL.",
  contacts: "Telefon, e-mail, konto Telegram lub WhatsApp i adres portfela kryptowalut z treści strony albo reklamy.",
  kit_files:
    "To, co kit wnosi na każdą stronę: identyczny skrypt, wzór zapytań wysyłanych do serwera, adres, na który formularz wysyła dane, i wzór ścieżki URL. " +
    "Zmienne części adresów są maskowane.",
  product: "Nazwa reklamowanego produktu albo fikcyjnej platformy, wyciągnięta przez model językowy albo ze słownika.",
}

const RELATION_TEXT = (c: Methodology["constants"]): Record<string, string> => ({
  duplicate: `Ten sam plik, ten sam numer reklamy albo d ≤ ${c.duplicate_cut}.`,
  same_campaign: `Wspólny identyfikator albo d ≤ ${c.campaign_cut}.`,
  similar: `Brak wspólnego identyfikatora, ale podobna treść: d ≤ ${c.family_cut}. Zwykle osobne kampanie z jednej rodziny.`,
  none: `Brak wspólnego identyfikatora i d > ${c.family_cut}.`,
})

const DECISION_TEXT = (c: Methodology["constants"]): Record<string, string> => ({
  duplicate: `Ten sam plik, ten sam numer reklamy albo d ≤ ${c.duplicate_cut} do materiału w bazie.`,
  known_campaign:
    `Wspólny identyfikator z kampanią w bazie albo najbliższy materiał w bazie w odległości d ≤ ${c.campaign_cut}. ` +
    "Nowy materiał dostaje wtedy kampanię tego materiału.",
  merge_proposal: "Wspólne identyfikatory z dwiema kampaniami naraz. Możliwe, że to jedna kampania, więc decyzję podejmuje analityk.",
  new_campaign: `Brak wspólnego identyfikatora i d > ${c.campaign_cut} do każdego materiału w bazie. Prawdopodobnie nowa kampania.`,
})

export default function GlossaryPage() {
  const { data: m, error, isLoading } = useApi<Methodology>("/api/methodology")
  if (isLoading) return <Loading rows={4} />
  if (error || !m) return <ErrorState error={error} />
  const c = m.constants
  const relationText = RELATION_TEXT(c)
  const decisionText = DECISION_TEXT(c)
  const view = (id: string) => m.views.find((v) => v.view === id)?.label ?? id
  const newCampaign = m.decisions.find((d) => d.decision === "new_campaign")?.label ?? "nowa kampania"
  const space = <Link to="/space" className="underline underline-offset-4">Przestrzeń cech</Link>

  return (
    <div className="max-w-5xl space-y-8">
      <PageHeader
        title="Słowniczek"
        description="Pojęcia, które pojawiają się w panelu, i sposób, w jaki materiały łączą się w kampanie. Progi pochodzą z bieżącej konfiguracji."
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

      <Group id="podstawy" title="Podstawowe pojęcia">
        <Term name="Materiał">Jedna zgłoszona reklama (zrzut ekranu, wideo albo tekst) razem ze stroną, na którą prowadzi, jeśli udało się ją pobrać.</Term>
        <Term name="Kreacja">Sama reklama: obraz, klatki wideo i tekst.</Term>
        <Term name="Strona docelowa">Strona, na którą prowadzi reklama. Z niej pochodzi tekst, kod HTML, obrazy i większość identyfikatorów.</Term>
        <Term name="Kampania">Materiały jednego operatora, czyli osoby lub grupy, która je wypuściła. Łączy je wspólny identyfikator albo bardzo podobna treść.</Term>
        <Term name="Rodzina kampanii">Kampanie o podobnej treści, ale bez wspólnego identyfikatora. Zwykle ten sam kit u różnych operatorów.</Term>
        <Term name="Kit">Gotowy szablon strony oszustwa, który można kupić i postawić na wielu domenach. Jednego kitu może używać wielu operatorów.</Term>
        <Term name="Ślad">
          Pojedyncza wartość wyciągnięta z materiału, np. domena, numer telefonu albo numer piksela. Kliknięcie śladu pokazuje wszystkie materiały, które go mają.
        </Term>
      </Group>

      <Group
        id="identyfikatory"
        title="Identyfikatory"
        intro="Ślady porównywane dokładnie: dwa materiały mają tę samą wartość albo nie. Ta sama rzadka wartość łączy materiały w kampanię bez względu na treść."
      >
        {m.identifier_groups.map((g) => <Term key={g.group} name={g.label}>{GROUP_TEXT[g.group] ?? g.hint}</Term>)}
        <Term name="Identyczny plik">Ten sam plik w obu materiałach (ten sam skrót SHA-256). Para jest duplikatem.</Term>
      </Group>

      <Group
        id="tresc"
        title="Podobieństwo treści"
        intro="Porównania treści, w panelu nazywane widokami. Każde daje wynik od 0 (nic wspólnego) do 1 (to samo). Decydują, gdy materiały nie mają wspólnego identyfikatora."
      >
        <Term name={view("text")}>
          Ile wspólnych fragmentów po 4 kolejne słowa mają teksty stron docelowych. Imiona i nazwiska są przed porównaniem zastępowane, bo oszuści kopiują
          ten sam artykuł i zmieniają tylko osobę.
        </Term>
        <Term name={view("ocr")}>To samo dla tekstu reklamy: napisy odczytane ze zrzutów ekranu i klatek wideo oraz treść reklamy.</Term>
        <Term name={view("semantic")}>
          Czy teksty mówią o tym samym, nawet innymi słowami. Porównuje wektory znaczenia z modelu multilingual-e5-small. Od wektorów odejmowana jest
          średnia z bazy, bo teksty o oszustwach i tak są do siebie podobne.
        </Term>
        <Term name={view("html")}>Czy strony zbudowano z tego samego szablonu. Porównuje fragmenty po 5 kolejnych znaczników HTML, bez tekstu.</Term>
        <Term name={view("css")}>
          Ile wspólnych nazw klas CSS mają strony. Automatycznie generowane części nazw są maskowane. Kit przerobiony na inną markę i inny język zwykle
          zachowuje swoje nazwy klas. Strona musi mieć co najmniej {c.min_class_names} różnych nazw.
        </Term>
        <Term name={view("js")}>
          Czy strony mają te same własne skrypty, jeśli pominąć wpisane w nie wartości. Komentarze są usuwane, a napisy i liczby maskowane, więc dwie
          instalacje tego samego kitu różnią się tylko danymi. Skrypty popularnych usług (analityka, zgody na ciasteczka, CDN) są pomijane.
        </Term>
        <Term name={view("images")}>
          Jaka część obrazów jednego materiału ma odpowiednik w drugim. Dwa obrazy pasują, gdy ich skróty pHash różnią się najwyżej na {c.phash_hamming} z 64
          bitów. Taki skrót prawie się nie zmienia po kompresji i zmianie rozmiaru. Gdy skróty się różnią, porównywane są punkty charakterystyczne obrazu,
          co rozpoznaje też kopie przycięte.
        </Term>
        <Term name="Teksty w różnych językach">
          Porównania słów ({view("text")}, {view("ocr")}) dają 0 dla tłumaczenia tej samej strony. Dlatego, gdy oba teksty mają rozpoznany, różny język,
          te dwa porównania są pomijane. Język rozpoznawany jest po spójnikach i przyimkach, więc przy krótkim tekście zostaje nieznany.
        </Term>
        <Term name="Współczynnik Jaccarda">
          <Formula>J(A, B) = |A ∩ B| / |A ∪ B|</Formula>
          Udział wspólnych elementów wśród wszystkich elementów dwóch zbiorów.
        </Term>
        <Term name="n-gram">Ciąg n kolejnych elementów, np. 4 słów albo 5 znaczników HTML. Wspólne n-gramy znaczą skopiowany fragment, a nie tylko te same słowa.</Term>
        <Term name="MinHash">Krótki podpis zbioru, z którego da się szybko oszacować współczynnik Jaccarda bez porównywania całych zbiorów.</Term>
      </Group>

      <Group
        id="opisowe"
        title="Cechy, które nie łączą"
        intro="Są widoczne w panelu, ale nie łączą materiałów, bo ta sama wartość pojawia się w niezależnych kampaniach."
      >
        <Term name="Osoby">
          Twarze z obrazów są porównywane z bazą zdjęć znanych osób (modele SCRFD i ArcFace, próg podobieństwa {c.face_match_threshold}). Nazwiska są też
          szukane w tekście.
        </Term>
        <Term name="Typ oszustwa, marka, medium">Rodzaj oszustwa oraz marka i medium, pod które podszywa się materiał. Przypisuje je model językowy albo słownik.</Term>
        <Term name="Adres IP, nazwa reklamodawcy">Zapisywane dla kontekstu. Ten sam serwer albo ta sama nazwa nie znaczą, że to ten sam operator.</Term>
      </Group>

      <Group id="grupowanie" title="Jak powstają kampanie">
        <Term name="Wspólny identyfikator (must-link)">
          Dwa materiały z tą samą rzadką wartością trafiają do jednej kampanii, bez względu na treść. Działa to też przez pośredników: jeśli A łączy się
          z B, a B z C, wszystkie trzy są w jednej kampanii.
        </Term>
        <Term name="Rzadkość wartości">
          Wartość łączy tylko wtedy, gdy ma ją najwyżej {pct(c.max_df)} materiałów w bazie, bo częste wartości nic nie mówią o operatorze. Wartość obecna
          w jednym albo dwóch materiałach łączy zawsze.
        </Term>
        <Term name="Odległość treści d">
          <Formula>d = 1 − średnia wyników widoków dostępnych dla obu materiałów</Formula>
          Widok, którego brakuje w jednym z materiałów (np. strona bez obrazów), jest pomijany, a nie liczony jako 0. Gdy nie ma żadnego wspólnego widoku, d = 1.
        </Term>
        <Term name="Odległość D">To samo co d, ale 0 dla materiałów połączonych identyfikatorem, także przez pośredników. Na tej odległości działa grupowanie.</Term>
        <Term name="Średnie wiązanie (UPGMA)">
          Grupowanie zaczyna od pojedynczych materiałów i za każdym razem łączy dwie najbliższe grupy. Odległość dwóch grup to średnia D ze wszystkich par
          między nimi. Kolejne połączenia rysuje dendrogram.
        </Term>
        <Term name="Progi">
          Grupy połączone przy odległości do {c.duplicate_cut} to duplikaty, do {c.campaign_cut} kampanie, a do {c.family_cut} rodziny kampanii.
        </Term>
        <Term name="Bliskość p">
          1, gdy para ma wspólny identyfikator, a w przeciwnym razie 1 − d. Służy do sortowania par i wyznacza grubość linii na grafie.
        </Term>
      </Group>

      <Group id="relacje" title="Relacja pary" intro="Jak panel opisuje dwa materiały z bazy, od najsilniejszego powiązania.">
        {m.relations.map((r) => <Term key={r.relation} name={<RelationBadge relation={r.relation} />}>{relationText[r.relation] ?? r.hint}</Term>)}
      </Group>

      <Group id="nowy" title="Nowy materiał" intro="Nowy materiał jest porównywany z całą bazą i dostaje jedną z czterech decyzji.">
        {m.decisions.map((d) => <Term key={d.decision} name={d.label}>{decisionText[d.decision] ?? d.hint}</Term>)}
      </Group>

      <Group
        id="porownanie"
        title="Inne metody grupowania"
        intro={<>Strona {space} pokazuje te same materiały pogrupowane kilkoma metodami. Kampanie w panelu wyznacza pierwsza, pozostałe służą do porównania.</>}
      >
        <Term name="FakerAlpha">Metoda używana w całym panelu: wspólne identyfikatory i średnie wiązanie na odległości D, z progiem {c.campaign_cut}.</Term>
        <Term name="Sama treść">To samo bez identyfikatorów, na odległości d. Różnica względem FakerAlpha pokazuje, ile wnoszą identyfikatory.</Term>
        <Term name="Pojedyncze wiązanie">
          Odległość dwóch grup to odległość ich najbliższej pary. Grupy łatwo łączą się w długie łańcuchy przez pojedyncze materiały.
        </Term>
        <Term name="Pełne wiązanie">Odległość dwóch grup to odległość ich najdalszej pary. Grupy wychodzą mniejsze i bardziej jednolite.</Term>
        <Term name="HDBSCAN">
          Szuka gęstych skupisk bez progu odległości. Najmniejsza grupa to 2 materiały, a materiały poza skupiskami zostają bez grupy (szum).
        </Term>
        <Term name="Louvain">
          Dzieli graf na społeczności, czyli zbiory gęsto połączonych wierzchołków. Wierzchołki to materiały, krawędzie to powiązane pary, a waga krawędzi to bliskość p.
        </Term>
        <Term name="MDS">
          Układa materiały na płaszczyźnie tak, żeby odległości na rysunku jak najlepiej oddawały d. Dobrze zachowuje duże odległości i za każdym razem
          daje ten sam wynik.
        </Term>
        <Term name="t-SNE">Też układa materiały na płaszczyźnie, ale dba tylko o najbliższych sąsiadów. Odległości między dalekimi grupami nic nie znaczą.</Term>
        <Term name="Silhouette">
          Dla każdego materiału porównuje, jak blisko mu do własnej grupy i do najbliższej innej. Skala od −1 do 1, a wyższy wynik znaczy grupy zwarte
          i dobrze rozdzielone.
        </Term>
        <Term name="ARI">Zgodność dwóch podziałów tych samych materiałów: 1 to podziały identyczne, około 0 to zgodność przypadkowa.</Term>
      </Group>

      <Group id="ewaluacja" title="Ocena wyników" intro={<>Uruchamiana z wiersza poleceń: <code className="text-xs">python tools/evaluate.py --labels data/labels_dane.csv</code>.</>}>
        <Term name="Leave-one-out">
          Każdy materiał po kolei jest wyjmowany z bazy i klasyfikowany od nowa. Powinien wrócić do swojej kampanii, a jeśli był w niej sam, dostać
          decyzję „{newCampaign}”.
        </Term>
        <Term name="Warianty syntetyczne">
          Przerobione kopie materiału: sama reklama, sama strona docelowa, obraz po ponownej kompresji, zmieniona domena, zmienione nazwisko. Każda powinna
          trafić do kampanii oryginału.
        </Term>
        <Term name="Precyzja, czułość, F1">
          Liczone na parach materiałów. Precyzja: jaka część połączonych par naprawdę należy do jednej kampanii. Czułość: jaka część par z jednej kampanii
          została połączona. F1 łączy obie w jedną liczbę.
        </Term>
        <Term name="B-cubed">Precyzja i czułość liczone dla każdego materiału osobno, a potem uśrednione. Duże kampanie ważą tu mniej niż przy liczeniu par.</Term>
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
