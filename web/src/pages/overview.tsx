import { Link } from "react-router"

import type { CampaignCard, MetricsOverview, Overview } from "@/lib/api"
import { CAMPAIGN_CUT, fmtP, matLabel, plural, useApi } from "@/lib/format"
import { DistanceHistogramChart, SignalAttributionChart } from "@/components/charts"
import { CampaignBadge, CampaignDot, ErrorState, Loading, PageHeader, Section, Stats, Thumb } from "@/components/common"
import { DatasetImport } from "@/components/dataset-import"
import { Button } from "@/components/ui/button"
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty"

export default function OverviewPage() {
  const { data, error, isLoading } = useApi<Overview>("/api/overview")
  const metrics = useApi<MetricsOverview>("/api/metrics/overview")

  if (isLoading) return <Loading />
  if (error || !data) return <ErrorState error={error} />
  if (!data.n_materials) {
    return (
      <div className="space-y-6">
        <Empty className="border bg-card py-12">
          <EmptyHeader>
            <EmptyTitle className="text-xl">W bazie nie ma jeszcze materiałów</EmptyTitle>
            <EmptyDescription className="text-base">
              Wczytaj poniżej zbiór przypadków albo zbiór demonstracyjny. Możesz też przeanalizować pojedynczy materiał: adres URL, plik lub tekst.
            </EmptyDescription>
          </EmptyHeader>
          <Button asChild variant="outline"><Link to="/analyse">Analizuj pojedynczy materiał</Link></Button>
        </Empty>
        <DatasetImport showResultLink={false} />
      </div>
    )
  }

  const multi = data.campaigns.filter((c) => c.size > 1)
  const singles = data.campaigns.filter((c) => c.size === 1)
  const m = metrics.data
  const campCut = data.thresholds?.campaign_cut ?? CAMPAIGN_CUT

  return (
    <>
      <PageHeader
        title="Kampanie"
        description={`Kampania to materiały połączone wspólnym rzadkim identyfikatorem (domena, piksel, kontakt, szablon strony, produkt) albo treścią bliższą niż d ≤ ${campCut}.`}
      />

      <Stats
        items={[
          { label: "Materiały", value: data.n_materials, to: "/materials" },
          { label: "Kampanie z 2+ materiałami", value: data.n_multi },
          { label: "Pojedyncze materiały", value: data.n_singletons },
          { label: "Pary ze wspólnym identyfikatorem", value: m ? `${m.n_must_link} z ${m.n_pairs}` : "…" },
        ]}
      />

      {multi.length > 0 ? (
        <div className={multi.length > 1 ? "grid gap-5 xl:grid-cols-2" : "grid gap-5"}>
          {multi.map((c) => <CampaignCardView key={c.id} c={c} />)}
        </div>
      ) : (
        <p className="rounded-xl border border-dashed px-5 py-8 text-center text-sm text-muted-foreground">
          Żadne dwa materiały nie mają wspólnego identyfikatora ani odległości treści d ≤ {campCut}.
        </p>
      )}

      {m && (
        <div className="grid items-start gap-5 lg:grid-cols-[1.3fr_1fr]">
          <Section
            title="Jak daleko od siebie są pary"
            description={`Wszystkie ${m.n_pairs} par według odległości treści d. Ciemna część słupka to pary ze wspólnym identyfikatorem — łączą się niezależnie od treści.`}
          >
            <DistanceHistogramChart data={m.distance_histogram} campaignCut={m.thresholds.campaign_cut} familyCut={m.thresholds.family_cut} />
          </Section>
          <Section title="Co łączy materiały w kampanie" description="Liczba połączonych par według rodzaju wspólnego śladu. Para może mieć kilka śladów naraz.">
            <SignalAttributionChart data={m.signal_attribution} />
          </Section>
        </div>
      )}

      {singles.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-lg font-medium">Pojedyncze materiały</h2>
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {singles.map((c) => {
              const x = c.members[0]
              return (
                <li key={c.id}>
                  <Link to={`/materials/${x.id}`} className="group flex items-center gap-3 rounded-xl bg-card p-3 ring-1 ring-foreground/10 hover:ring-foreground/30">
                    <Thumb src={x.thumb} alt="" className="size-14 shrink-0 ring-1 ring-border" />
                    <span className="min-w-0">
                      <span className="flex items-center gap-2">
                        <span className="truncate font-medium group-hover:underline">Materiał {matLabel(x)}</span>
                        <CampaignBadge c={c} link={false} />
                      </span>
                      <span className="block truncate text-xs text-muted-foreground">{x.product || x.domains[0] || x.title || "bez tytułu"}</span>
                    </span>
                  </Link>
                </li>
              )
            })}
          </ul>
        </section>
      )}
    </>
  )
}

function CampaignCardView({ c }: { c: CampaignCard }) {
  const meta = [
    plural(c.size, "materiał", "materiały", "materiałów"),
    c.scam_types[0]?.label,
    c.mean_internal_p !== null ? `średnia bliskość p = ${fmtP(c.mean_internal_p)}` : null,
  ].filter(Boolean)
  return (
    <Link to={`/campaigns/${c.id}`} className="group block rounded-xl bg-card p-5 ring-1 ring-foreground/10 transition-shadow hover:ring-foreground/30">
      <h3 className="flex min-w-0 items-center gap-2.5 text-lg font-medium">
        <CampaignDot c={c} className="size-3" />
        <span className="min-w-0 truncate group-hover:underline">{c.code} · {c.name}</span>
      </h3>
      <p className="mt-0.5 text-sm text-muted-foreground">{meta.join(" · ")}</p>
      <div className="mt-4 flex gap-2 overflow-hidden">
        {c.members.slice(0, 8).map((x) => (
          <Thumb key={x.id} src={x.thumb} alt={`Materiał ${matLabel(x)}`} className="aspect-[6/7] w-16 shrink-0 ring-1 ring-border" />
        ))}
        {c.members.length > 8 && <span className="self-center text-sm text-muted-foreground">+{c.members.length - 8}</span>}
      </div>
      <ul className="mt-4 space-y-1.5 text-sm">
        {c.top_shared.slice(0, 3).map((s) => (
          <li key={`${s.type}:${s.value}`} className="flex min-w-0 items-baseline gap-2">
            <span className="shrink-0 text-muted-foreground">{s.type_label}:</span>
            <span className={s.type === "asset_phash" ? "truncate" : "truncate font-mono text-xs"} title={s.display}>
              {s.type === "asset_phash" ? plural(s.n_values, "wspólny obraz", "wspólne obrazy", "wspólnych obrazów") : s.display}
            </span>
            <span className="ml-auto shrink-0 text-xs text-muted-foreground tabular">w {s.count} z {c.size}</span>
          </li>
        ))}
      </ul>
    </Link>
  )
}

