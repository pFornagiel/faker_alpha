import { Link, useParams } from "react-router"

import type { MaterialSummary, PairDetail } from "@/lib/api"
import { fmtP, matLabel, useApi, viewsOfExplanation } from "@/lib/format"
import { CampaignBadge, ErrorState, Loading, PageHeader, RelationBadge, Section, Strength, Thumb } from "@/components/common"
import { Computation, IdentifierList, NotComparable, ViewBars } from "@/components/evidence"
import { Card, CardContent } from "@/components/ui/card"

export default function PairPage() {
  const { a, b } = useParams()
  const { data: d, error, isLoading } = useApi<PairDetail>(`/api/pair/${a}/${b}`)
  if (isLoading) return <Loading />
  if (error || !d) return <ErrorState error={error} />
  const sameCampaign = d.a.campaign && d.b.campaign && d.a.campaign.id === d.b.campaign.id

  const nIds = d.identifiers.reduce((acc, g) => acc + g.items.length, 0)

  return (
    <>
      <PageHeader
        title={`Materiał ${matLabel(d.a)} ↔ Materiał ${matLabel(d.b)}`}
        description="Dlaczego ta para jest albo nie jest połączona: wspólne identyfikatory, podobieństwo treści w pięciu widokach i reguła, która rozstrzygnęła."
      />

      <Card>
        <CardContent className="grid gap-x-10 gap-y-5 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
          <div className="min-w-0 space-y-2">
            <h2 className="flex flex-wrap items-center gap-2.5 text-lg font-medium">
              Relacja pary: <RelationBadge relation={d.relation} />
            </h2>
            <p className="max-w-[70ch] text-pretty">{d.rule}</p>
            {sameCampaign && d.relation !== "same_campaign" && d.relation !== "duplicate" && (
              <p className="max-w-[70ch] text-pretty text-muted-foreground">
                Oba materiały są mimo to w kampanii {d.a.campaign!.code}: łączą je inne materiały tej kampanii (połączenie pośrednie).{" "}
                <Link to={`/campaigns/${d.a.campaign!.id}`} className="underline">Otwórz kampanię</Link>.
              </p>
            )}
            {!sameCampaign && d.a.campaign && d.b.campaign && (
              <p className="text-muted-foreground">Materiały należą do różnych kampanii: {d.a.campaign.code} i {d.b.campaign.code}.</p>
            )}
          </div>
          <dl className="grid grid-cols-[auto_minmax(0,1fr)] items-baseline gap-x-5 gap-y-2.5 text-sm">
            <dt className="text-muted-foreground">Wspólne identyfikatory</dt>
            <dd className="font-medium">{d.must_link ? `${nIds} — łączą parę niezależnie od treści` : "brak — decyduje treść"}</dd>
            <dt className="text-muted-foreground">Odległość treści d</dt>
            <dd>
              <span className="font-medium tabular">{fmtP(d.distance)}</span>{" "}
              <span className="text-muted-foreground">{d.comparable ? "(0 = identyczna, 1 = nic wspólnego)" : "(brak danych do porównania)"}</span>
            </dd>
            <dt className="text-muted-foreground">Bliskość pary p</dt>
            <dd>
              <Strength p={d.p} className="max-w-56" />
              <span className="mt-1 block text-xs text-muted-foreground">{d.must_link ? "1, bo para ma wspólny identyfikator" : `1 − d = ${fmtP(d.p)}`}</span>
            </dd>
          </dl>
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <MaterialSide m={d.a} />
        <MaterialSide m={d.b} />
      </div>

      {!d.comparable && <NotComparable />}

      <Section
        title="Wspólne identyfikatory"
        description="Wartości znalezione w obu materiałach. Jedna taka wartość wystarczy, by połączyć materiały w kampanię — pod warunkiem, że nie jest zbyt popularna (występuje w najwyżej połowie bazy)."
      >
        <IdentifierList e={d} />
      </Section>

      <div className="grid items-start gap-6 lg:grid-cols-2">
        <Section
          title="Podobieństwo treści w pięciu widokach"
          description="Każdy widok porównuje inną warstwę materiału i daje wynik od 0 (nic wspólnego) do 1 (identyczne). Odległość treści d = 1 − średnia z widoków dostępnych po obu stronach; „brak danych” nie wchodzi do średniej."
        >
          <ViewBars views={viewsOfExplanation(d)} />
        </Section>
        <Section title="Obliczenie krok po kroku" description="Trzy kroki w kolejności, w jakiej system je wykonuje.">
          <Computation e={d} />
        </Section>
      </div>
    </>
  )
}

function MaterialSide({ m }: { m: MaterialSummary }) {
  const lbl = matLabel(m)
  return (
    <Card>
      <CardContent className="flex gap-4">
        <Thumb src={m.thumb} alt={`Materiał ${lbl}`} className="h-28 w-22 shrink-0 ring-1 ring-border" />
        <div className="min-w-0 space-y-1.5">
          <Link to={`/materials/${m.id}`} className="block truncate text-base font-medium hover:underline" title={m.name}>Materiał {lbl}</Link>
          <div><CampaignBadge c={m.campaign} withName /></div>
          <p className="line-clamp-2 text-sm text-muted-foreground">{m.title}</p>
          <p className="font-mono text-xs break-all text-muted-foreground">{m.domains.join(", ") || m.source_label}</p>
        </div>
      </CardContent>
    </Card>
  )
}
