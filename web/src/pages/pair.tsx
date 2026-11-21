import { ArrowLeftRight } from "lucide-react"
import { Link, useParams } from "react-router"

import type { MaterialSummary, PairDetail } from "@/lib/api"
import { fmtP, useApi, viewsOfExplanation } from "@/lib/format"
import { CampaignBadge, ErrorState, Loading, PageHeader, RelationBadge, Section, Strength, StrengthLegend, Thumb } from "@/components/common"
import { Computation, IdentifierList, NotComparable, ViewBars } from "@/components/evidence"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"

export default function PairPage() {
  const { a, b } = useParams()
  const { data: d, error, isLoading } = useApi<PairDetail>(`/api/pair/${a}/${b}`)
  if (isLoading) return <Loading />
  if (error || !d) return <ErrorState error={error} />
  const sameCampaign = d.a.campaign && d.b.campaign && d.a.campaign.id === d.b.campaign.id

  return (
    <>
      <PageHeader
        title={`Powiązanie: materiał ${d.a.name} ↔ materiał ${d.b.name}`}
        description="Co łączy te dwa materiały: wspólne identyfikatory (wymuszają tę samą kampanię) i podobieństwo treści w każdym widoku, z którego liczona jest odległość d."
      />

      <div className="grid items-stretch gap-4 md:grid-cols-[1fr_auto_1fr]">
        <MaterialSide m={d.a} />
        <Card className="justify-center md:w-64">
          <CardContent className="space-y-3 text-center">
            <ArrowLeftRight className="mx-auto size-5 text-muted-foreground" />
            <div>
              <div className="text-xs text-muted-foreground">odległość treści</div>
              <div className="text-4xl font-semibold tabular">d = {fmtP(d.distance)}</div>
              {d.must_link && <div className="mt-1 text-xs text-muted-foreground">wspólny identyfikator → p = 1</div>}
            </div>
            <RelationBadge relation={d.relation} />
            <Strength p={d.p} />
            <StrengthLegend />
          </CardContent>
        </Card>
        <MaterialSide m={d.b} />
      </div>

      <Card size="sm" className="bg-muted/40">
        <CardContent className="space-y-1 text-sm">
          <p className="flex flex-wrap items-center gap-2">
            <span className="font-medium">Werdykt: {d.relation_label}.</span>
            <span className="text-muted-foreground">Podstawa:</span> <Badge variant="outline">{d.basis}</Badge>
          </p>
          <p>{d.rule}</p>
          {sameCampaign && d.relation !== "same_campaign" && d.relation !== "duplicate" && (
            <p className="text-muted-foreground">
              Oba materiały są jednak w tej samej kampanii {d.a.campaign!.code} — łączą je inne materiały tej kampanii (powiązanie pośrednie).{" "}
              <Link to={`/campaigns/${d.a.campaign!.id}`} className="underline underline-offset-4">Zobacz kampanię</Link>.
            </p>
          )}
          {!sameCampaign && d.a.campaign && d.b.campaign && (
            <p className="text-muted-foreground">
              Materiały należą do różnych kampanii ({d.a.campaign.code} i {d.b.campaign.code}).
            </p>
          )}
        </CardContent>
      </Card>

      {!d.comparable && <NotComparable />}

      <Section title="Wspólne identyfikatory" description="Ta sama wartość w obu materiałach (obecna w co najwyżej połowie bazy) wymusza tę samą kampanię.">
        <IdentifierList e={d} />
      </Section>

      <div className="grid items-start gap-4 lg:grid-cols-2">
        <Section title="Podobieństwo treści" description="Każdy widok ma jedną standardową miarę podobieństwa w [0, 1]. „Brak danych” — widok niedostępny po jednej ze stron, pomijany w średniej.">
          <ViewBars views={viewsOfExplanation(d)} />
        </Section>
        <Section title="Jak powstaje wynik">
          <Computation e={d} />
        </Section>
      </div>
    </>
  )
}

function MaterialSide({ m }: { m: MaterialSummary }) {
  return (
    <Card>
      <CardContent className="flex gap-3">
        <Thumb src={m.thumb} alt={`Materiał ${m.name}`} className="h-28 w-20 shrink-0" />
        <div className="min-w-0 space-y-1.5">
          <Link to={`/materials/${m.id}`} className="font-semibold hover:underline underline-offset-4">Materiał {m.name}</Link>
          <div><CampaignBadge c={m.campaign} withName /></div>
          <p className="line-clamp-2 text-xs text-muted-foreground">{m.title}</p>
          <p className="font-mono text-xs break-all text-muted-foreground">{m.domains.join(", ") || m.source_label}</p>
        </div>
      </CardContent>
    </Card>
  )
}
