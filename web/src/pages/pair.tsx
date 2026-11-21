import { ArrowLeftRight } from "lucide-react"
import { Link, useParams } from "react-router"

import type { MaterialSummary, PairDetail } from "@/lib/api"
import { fmtP, useApi } from "@/lib/format"
import { CampaignBadge, ErrorState, Loading, PageHeader, RelationBadge, Section, Strength, StrengthLegend, Thumb } from "@/components/common"
import { Computation, EvidenceTable, FamilyBars, NotComparable } from "@/components/evidence"
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
        description="Co łączy te dwa materiały, jak silny jest każdy dowód i jak z dowodów powstaje końcowa ocena siły powiązania p (0–1)."
      />

      <div className="grid items-stretch gap-4 md:grid-cols-[1fr_auto_1fr]">
        <MaterialSide m={d.a} />
        <Card className="justify-center md:w-64">
          <CardContent className="space-y-3 text-center">
            <ArrowLeftRight className="mx-auto size-5 text-muted-foreground" />
            <div>
              <div className="text-xs text-muted-foreground">siła powiązania</div>
              <div className="text-4xl font-semibold">{fmtP(d.p)}</div>
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
          {d.weak_only && (
            <p className="text-muted-foreground">
              Uwaga: to podobieństwo opiera się wyłącznie na kontekście (osoby, typ oszustwa) — nie wskazuje wspólnego operatora.
            </p>
          )}
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

      <div className="grid items-start gap-4 lg:grid-cols-2">
        <Section title="Siła rodzin dowodów" description="Każda rodzina to inny rodzaj śladu; wynik 0–1 mówi, jak mocno ten rodzaj śladu łączy parę.">
          <FamilyBars families={d.groups.map((g) => ({ family: g.family, label: g.label, tier: g.tier, score: g.score }))} />
        </Section>
        <Section title="Jak powstaje wynik">
          <Computation e={d} />
        </Section>
      </div>

      <Section title="Wszystkie dowody" description="Każdy wiersz to jedna konkretna zgodność między materiałami, z wagą jej wkładu.">
        <EvidenceTable e={d} />
      </Section>
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
