import { useSearchParams } from "react-router"

import type { Methodology, MetricsOverview } from "@/lib/api"
import { useApi } from "@/lib/format"
import {
  CategoryCountChart, DendrogramChart, DistanceHistogramChart, EvalSummaryCharts, FeatureCoverageChart, SignalAttributionChart,
  ViewComparisonChart,
} from "@/components/charts"
import { ErrorState, Loading, PageHeader, PageTab, PageTabsList, Section } from "@/components/common"
import { Tabs, TabsContent } from "@/components/ui/tabs"
import MethodologyPage from "@/pages/methodology"

const TABS = ["charts", "eval", "method"] as const
type Tab = (typeof TABS)[number]

export default function MetricsHubPage() {
  const [params, setParams] = useSearchParams()
  const raw = params.get("tab") ?? "charts"
  const tab: Tab = (TABS as readonly string[]).includes(raw) ? (raw as Tab) : "charts"
  const setTab = (v: string) => {
    setParams((p) => {
      const next = new URLSearchParams(p)
      next.set("tab", v)
      return next
    }, { replace: true })
  }

  const metrics = useApi<MetricsOverview>("/api/metrics/overview")
  const meth = useApi<Methodology>("/api/methodology")

  const ev = meth.data?.evaluation

  return (
    <>
      <PageHeader
        title="Metryki i metoda"
        description="Skąd biorą się kampanie: drzewo łączenia materiałów, progi cięcia, wkład poszczególnych śladów, kompletność danych i wyniki testów jakości."
      />

      <Tabs value={tab} onValueChange={setTab} className="gap-6">
        <PageTabsList label="Metryki i metoda">
          <PageTab value="charts">Jak powstały kampanie</PageTab>
          <PageTab value="eval">Testy jakości</PageTab>
          <PageTab value="method">Metoda krok po kroku</PageTab>
        </PageTabsList>

        <TabsContent value="charts" className="space-y-6">
          {metrics.isLoading ? (
            <Loading rows={4} />
          ) : metrics.error || !metrics.data ? (
            <ErrorState error={metrics.error} />
          ) : (
            <ChartsTab m={metrics.data} />
          )}
        </TabsContent>

        <TabsContent value="eval" className="space-y-6">
          {meth.isLoading ? (
            <Loading rows={3} />
          ) : meth.error || !meth.data ? (
            <ErrorState error={meth.error} />
          ) : ev ? (
            <>
              <EvalSummaryCharts loo={ev.leave_one_out} variants={ev.variants} labels={ev.labels} />
              <p className="max-w-[80ch] text-xs text-pretty text-muted-foreground">
                Zbiór testowy liczy {meth.data.n_materials} materiałów, więc pojedynczy błąd zmienia wynik o kilka–kilkanaście punktów procentowych.
                Traktuj te liczby jako sprawdzian poprawności, a nie jako szacunek skuteczności na dużej bazie. Raport: <code>{ev.file}</code>.
              </p>
            </>
          ) : (
            <p className="rounded-xl border border-dashed px-5 py-8 text-center text-sm text-muted-foreground">
              Testy jakości nie zostały jeszcze uruchomione. Wymagają ręcznych etykiet kampanii: <code>python tools/evaluate.py --labels data/labels_dane.csv</code>.
            </p>
          )}
        </TabsContent>

        <TabsContent value="method">
          <MethodologyPage embedded />
        </TabsContent>
      </Tabs>
    </>
  )
}

function ChartsTab({ m }: { m: MetricsOverview }) {
  const { campaign_cut: cc, family_cut: fc, duplicate_cut: dc } = m.thresholds
  return (
    <>
      <Section
        title="Drzewo łączenia materiałów (dendrogram)"
        description={`Wszystkie ${m.n_materials} materiałów ułożone tak, by podobne stały obok siebie. Pozioma belka łączy dwie grupy na wysokości równej odległości D między nimi.`}
        howToRead={<>
          im niżej belka, tym bliższe materiały. Materiały ze wspólnym identyfikatorem łączą się na samym dole (D = 0).
          Wszystko, co łączy się poniżej progu {cc}, tworzy jedną kampanię; poniżej progu {fc} — jedną rodzinę kampanii.
          Kliknij materiał, aby go otworzyć.
        </>}
      >
        <DendrogramChart data={m.dendrogram} />
      </Section>

      <div className="grid items-start gap-6 lg:grid-cols-2">
        <Section
          title="Ile par jest jak daleko od siebie"
          description={`Wszystkie ${m.n_pairs} par materiałów według odległości treści d; ${m.n_must_link} z nich ma wspólny identyfikator.`}
          howToRead="słupek = liczba par o danej odległości, kolor = co z parą zrobiono. Przerywane linie to progi. Ciemny kolor daleko po prawej oznacza parę połączoną identyfikatorem mimo zupełnie innej treści."
        >
          <DistanceHistogramChart data={m.distance_histogram} campaignCut={cc} familyCut={fc} duplicateCut={dc} height={200} />
        </Section>

        <Section
          title="Które ślady łączą materiały w kampanie"
          description="Liczba par materiałów połączonych danym rodzajem śladu."
          howToRead="dłuższy słupek = ślad, który spina więcej par. Jedna para może mieć kilka wspólnych śladów, więc liczby się nie sumują."
        >
          <SignalAttributionChart data={m.signal_attribution} />
        </Section>
      </div>

      <div className="grid items-start gap-6 lg:grid-cols-2">
        <Section
          title="Czy treść odróżnia kampanie"
          description="Średnie podobieństwo w każdym z pięciu widoków treści: dla par z tej samej kampanii i dla par z różnych kampanii."
          howToRead="duża przewaga niebieskiego słupka nad szarym oznacza widok, który dobrze rozpoznaje kampanię. Słupki podobnej długości — widok niczego nie rozróżnia."
        >
          <ViewComparisonChart data={m.view_summary.map((v) => ({ label: v.label, inside: v.n_same ? v.mean_same : null, outside: v.n_diff ? v.mean_diff : null }))} />
        </Section>

        <Section
          title="Kompletność danych"
          description="Dla ilu materiałów udało się uzyskać daną warstwę danych."
          howToRead="warstwa z niskim pokryciem rzadziej bierze udział w porównaniu — materiał bez strony docelowej nie ma np. śladów technicznych ani struktury HTML."
        >
          <FeatureCoverageChart data={m.feature_coverage} />
        </Section>
      </div>

      <div className="grid items-start gap-6 lg:grid-cols-2">
        <Section
          title="Rodzaje oszustw"
          description="Liczba materiałów według rodzaju oszustwa rozpoznanego przez model językowy lub reguły słownikowe."
        >
          <CategoryCountChart data={m.scam_types} head={["Rodzaj oszustwa", "materiałów"]} />
        </Section>
        <Section
          title="Osoby, pod które podszywają się reklamy"
          description="W ilu materiałach dana osoba została rozpoznana na obrazie lub wymieniona w tekście. To cecha opisowa — nie łączy materiałów w kampanie."
        >
          <CategoryCountChart data={m.top_persons.map((p) => ({ label: p.name, count: p.count }))} head={["Osoba", "materiałów"]} />
        </Section>
      </div>
    </>
  )
}
