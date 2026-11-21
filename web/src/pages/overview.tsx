import { useMutation, useQueryClient } from "@tanstack/react-query"
import { ArrowRight, Network, Radar, RefreshCw } from "lucide-react"
import type { ReactNode } from "react"
import { Link } from "react-router"
import { toast } from "sonner"

import { api, type CampaignCard, type CampaignRef, type MetricsOverview, type Overview } from "@/lib/api"
import { CAMPAIGN_CUT, DUPLICATE_CUT, FAMILY_CUT, fmtP, matLabel, plural, useApi } from "@/lib/format"
import { DistanceHistogramChart, SignalAttributionChart } from "@/components/charts"
import {
  CampaignBadge, CampaignDot, Chips, ErrorState, GroupBadge, HelpTip, Loading, PageHeader, PageTab, PageTabsList, ReadingNote, SummaryStrip, Thumb,
  traceHref,
} from "@/components/common"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty"
import { Tabs, TabsContent } from "@/components/ui/tabs"

export default function OverviewPage() {
  const { data, error, isLoading } = useApi<Overview>("/api/overview")
  const metrics = useApi<MetricsOverview>("/api/metrics/overview")
  const qc = useQueryClient()

  const recluster = useMutation({
    mutationFn: () => api.post<{ campaigns: number; seconds: number }>("/api/recluster"),
    onSuccess: (r) => {
      toast.success(`Przeliczono: ${r.campaigns} kampanii (${r.seconds} s)`)
      qc.invalidateQueries()
    },
    onError: (e) => toast.error((e as Error).message),
  })

  if (isLoading) return <Loading />
  if (error || !data) return <ErrorState error={error} />
  if (!data.n_materials) {
    return (
      <Empty className="border bg-card py-16">
        <EmptyHeader>
          <EmptyTitle className="text-xl">W bazie nie ma jeszcze materiałów</EmptyTitle>
          <EmptyDescription className="text-base">Kampanie pojawią się tutaj po dodaniu co najmniej dwóch powiązanych materiałów. Wczytaj gotowy zbiór przypadków albo przeanalizuj pierwszy materiał.</EmptyDescription>
        </EmptyHeader>
        <div className="flex gap-3">
          <Button asChild size="lg"><Link to="/analyse?tab=data">Wczytaj zbiór</Link></Button>
          <Button asChild variant="outline" size="lg"><Link to="/analyse">Analizuj nowy materiał</Link></Button>
        </div>
      </Empty>
    )
  }

  const multi = data.campaigns.filter((c) => c.size > 1)
  const singles = data.campaigns.filter((c) => c.size === 1)
  const dups = data.duplicates ?? []
  const familyOf = new Map<number, CampaignRef[]>()
  for (const f of data.families) for (const c of f.campaigns) familyOf.set(c, f.refs.filter((r) => r.id !== c))
  const t = data.thresholds
  const campCut = t?.campaign_cut ?? CAMPAIGN_CUT
  const famCut = t?.family_cut ?? FAMILY_CUT
  const dupCut = t?.duplicate_cut ?? DUPLICATE_CUT
  const m = metrics.data

  return (
    <>
      <PageHeader
        title="Kampanie"
        description="Kampania to materiały, które łączy wspólny identyfikator (domena, piksel, szablon strony, nazwa produktu) albo bardzo podobna treść. Tu widać, co zostało połączone, na jakiej podstawie i co zostało osobno."
        actions={
          <>
            <Button asChild variant="outline">
              <Link to="/relations?tab=graph"><Network /> Pokaż graf</Link>
            </Button>
            <Button
              variant="outline"
              onClick={() => recluster.mutate()}
              disabled={recluster.isPending}
              title="Porównuje od nowa wszystkie pary materiałów i układa kampanie. Kody kampanii (C1, C2…) mogą się zmienić."
            >
              <RefreshCw className={recluster.isPending ? "animate-spin" : ""} /> {recluster.isPending ? "Przeliczam…" : "Przelicz kampanie"}
            </Button>
          </>
        }
      />

      <SummaryStrip
        items={[
          { label: "Materiały w bazie", value: data.n_materials, hint: "reklamy wraz ze stronami docelowymi, zrzutami i nagraniami", to: "/materials" },
          { label: "Kampanie z 2+ materiałami", value: data.n_multi, hint: `łączą ${plural(data.n_in_multi, "materiał", "materiały", "materiałów")}` },
          { label: "Pojedyncze materiały", value: data.n_singletons, hint: "nie łączą się z żadnym innym — każdy to osobna kampania" },
          { label: "Rodziny kampanii", value: data.families.length, hint: "osobne kampanie o podobnej treści, bez wspólnego identyfikatora" },
          { label: "Duplikaty", value: data.n_duplicate_groups, hint: "ten sam materiał zgłoszony więcej niż raz" },
        ]}
      />

      <Card>
        <CardHeader>
          <CardTitle>Jak powstał ten podział</CardTitle>
          <CardDescription className="max-w-[80ch] text-pretty">
            Każda para materiałów jest porównywana na dwa sposoby. Wspólny rzadki identyfikator łączy parę zawsze.
            Bez niego decyduje odległość treści d: do {campCut} — ta sama kampania, do {famCut} — ta sama rodzina, powyżej — brak powiązania.{" "}
            <Link to="/metrics" className="font-medium whitespace-nowrap text-foreground underline">Dendrogram i wszystkie metryki</Link>
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-x-10 gap-y-8 border-t pt-5 lg:grid-cols-[1.25fr_1fr]">
          <div className="min-w-0 space-y-3">
            <div className="space-y-1">
              <h3 className="font-medium">Ile par jest jak daleko od siebie</h3>
              <ReadingNote>
                słupek = liczba par o danej odległości treści. Przerywane linie to progi. Ciemny kolor daleko po prawej oznacza parę
                połączoną identyfikatorem mimo zupełnie innej treści.
                {m ? ` W bazie jest ${plural(m.n_pairs, "para", "pary", "par")}, z czego ${m.n_must_link} ma wspólny identyfikator.` : ""}
              </ReadingNote>
            </div>
            {m ? (
              <DistanceHistogramChart data={m.distance_histogram} campaignCut={m.thresholds.campaign_cut} familyCut={m.thresholds.family_cut} duplicateCut={dupCut} />
            ) : (
              <Loading rows={1} />
            )}
          </div>
          <div className="min-w-0 space-y-3">
            <div className="space-y-1">
              <h3 className="font-medium">Które ślady łączą materiały w kampanie</h3>
              <ReadingNote>
                liczba par materiałów połączonych danym rodzajem śladu. Jedna para może mieć kilka wspólnych śladów, więc liczby się nie sumują.
              </ReadingNote>
            </div>
            {m ? <SignalAttributionChart data={m.signal_attribution} /> : <Loading rows={1} />}
          </div>
        </CardContent>
      </Card>

      <Tabs defaultValue="multi" className="gap-5">
        <PageTabsList label="Podział bazy">
          <PageTab value="multi" count={multi.length}>Kampanie z 2+ materiałami</PageTab>
          <PageTab value="singletons" count={singles.length}>Pojedyncze materiały</PageTab>
          <PageTab value="families" count={data.families.length}>Rodziny kampanii</PageTab>
          <PageTab value="duplicates" count={dups.length}>Duplikaty</PageTab>
        </PageTabsList>

        <TabsContent value="multi" className="space-y-4">
          {multi.length ? (
            <div className={multi.length > 1 ? "grid gap-5 xl:grid-cols-2" : "grid gap-5"}>
              {multi.map((c) => <CampaignCardView key={c.id} c={c} />)}
            </div>
          ) : (
            <TabEmpty>
              Żadne dwa materiały nie mają wspólnego identyfikatora ani odległości treści d ≤ {campCut}.{" "}
              <Link to="/analyse" className="underline">Dodaj kolejny materiał</Link>, aby sprawdzić, czy łączy się z bazą.
            </TabEmpty>
          )}
        </TabsContent>

        <TabsContent value="singletons" className="space-y-4">
          <TabIntro>
            Materiały bez wspólnego identyfikatora i z treścią odległą od wszystkich pozostałych (d &gt; {campCut}). Każdy tworzy własną,
            jednomateriałową kampanię. „Podobna treść” wskazuje kampanię z tej samej rodziny.
          </TabIntro>
          {singles.length ? (
            <SingletonGrid singles={singles} familyOf={familyOf} />
          ) : (
            <TabEmpty>Każdy materiał w bazie należy do kampanii z co najmniej dwoma materiałami.</TabEmpty>
          )}
        </TabsContent>

        <TabsContent value="families" className="space-y-4">
          <TabIntro>
            Rodzina to osobne kampanie, których treść jest podobna (d ≤ {famCut}), ale które nie mają wspólnego identyfikatora —
            np. ten sam scenariusz oszustwa powielony na innej infrastrukturze.
          </TabIntro>
          {data.families.length ? (
            <ul className="divide-y rounded-xl bg-card ring-1 ring-foreground/10">
              {data.families.map((f) => (
                <li key={f.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3.5">
                  <span className="w-28 shrink-0 font-medium">Rodzina {f.id + 1}</span>
                  <span className="flex min-w-0 flex-1 flex-wrap gap-x-5 gap-y-1.5">
                    {f.refs.map((r) => <CampaignBadge key={r.id} c={r} withName />)}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <TabEmpty>Żadne dwie kampanie nie mają treści podobnej na poziomie d ≤ {famCut}.</TabEmpty>
          )}
        </TabsContent>

        <TabsContent value="duplicates" className="space-y-4">
          <TabIntro>
            Duplikat to ten sam materiał zgłoszony ponownie: identyczny plik, to samo ID reklamy albo niemal identyczna treść (d ≤ {dupCut}).
          </TabIntro>
          {dups.length ? (
            <ul className="divide-y rounded-xl bg-card ring-1 ring-foreground/10">
              {dups.map((grp, i) => (
                <li key={i} className="flex flex-wrap items-center gap-x-6 gap-y-3 px-5 py-3.5">
                  <span className="flex min-w-0 flex-1 flex-wrap gap-x-6 gap-y-3">
                    {grp.map((x) => (
                      <Link key={x.id} to={`/materials/${x.id}`} className="group flex min-w-0 items-center gap-3">
                        <Thumb src={x.thumb} alt="" className="size-12 shrink-0 ring-1 ring-border" />
                        <span className="min-w-0">
                          <span className="block font-medium group-hover:underline">Materiał {matLabel(x)}</span>
                          <span className="block max-w-52 truncate text-xs text-muted-foreground">{x.domains[0] || x.title}</span>
                        </span>
                      </Link>
                    ))}
                  </span>
                  {grp.length >= 2 && (
                    <Button asChild variant="outline" size="sm">
                      <Link to={`/pair/${grp[0].id}/${grp[1].id}`}>Porównaj <ArrowRight /></Link>
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <TabEmpty>W bazie nie ma dwóch zgłoszeń tego samego materiału.</TabEmpty>
          )}
        </TabsContent>
      </Tabs>
    </>
  )
}

function TabIntro({ children }: { children: ReactNode }) {
  return <p className="max-w-[80ch] text-sm text-pretty text-muted-foreground">{children}</p>
}

function TabEmpty({ children }: { children: ReactNode }) {
  return <p className="rounded-xl border border-dashed px-5 py-8 text-center text-sm text-muted-foreground">{children}</p>
}

const MAX_THUMBS = 10

function CampaignCardView({ c }: { c: CampaignCard }) {
  const meta = [
    plural(c.size, "materiał", "materiały", "materiałów"),
    ...c.scam_types.map((s) => s.label),
    c.date_range.length ? `aktywna ${c.date_range[0]} → ${c.date_range[1]}` : null,
  ].filter(Boolean)
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex min-w-0 items-center gap-2.5 text-lg">
          <CampaignDot c={c} className="size-3" />
          <Link to={`/campaigns/${c.id}`} className="min-w-0 break-words hover:underline">
            {c.code} · {c.name}
          </Link>
        </CardTitle>
        <CardDescription className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
          <span>{meta.join(" · ")}</span>
          {c.mean_internal_p !== null && (
            <span className="inline-flex items-center gap-1">
              · średnia bliskość par p = <span className="font-medium text-foreground tabular">{fmtP(c.mean_internal_p)}</span>
              <HelpTip label="Co oznacza średnia bliskość par">
                Średnia z bliskości p wszystkich par materiałów w kampanii. p = 1 przy wspólnym identyfikatorze, w pozostałych przypadkach 1 − d
                (d = odległość treści). Im bliżej 1, tym więcej par jest połączonych bezpośrednio.
              </HelpTip>
            </span>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-x-10 gap-y-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <div className="min-w-0 space-y-5">
          <div className="grid grid-cols-[repeat(auto-fill,minmax(5.25rem,1fr))] gap-3">
            {c.members.slice(0, MAX_THUMBS).map((m) => (
              <Link key={m.id} to={`/materials/${m.id}`} className="group min-w-0" title={`Materiał ${m.name}: ${m.title}`}>
                <Thumb src={m.thumb} alt={`Materiał ${matLabel(m)}`} className="aspect-[6/7] w-full ring-1 ring-border group-hover:ring-foreground/40" />
                <span className="mt-1.5 block truncate text-xs font-medium group-hover:underline">Materiał {matLabel(m)}</span>
                <span className="block truncate text-xs text-muted-foreground">{m.domains[0] ?? "brak domeny"}</span>
              </Link>
            ))}
          </div>
          {c.members.length > MAX_THUMBS && (
            <p className="text-xs text-muted-foreground">
              i {c.members.length - MAX_THUMBS} więcej — <Link to={`/campaigns/${c.id}?tab=members`} className="underline">pokaż wszystkie</Link>
            </p>
          )}
          <dl className="space-y-3 text-sm">
            <div>
              <dt className="mb-1 text-xs text-muted-foreground">Domeny docelowe</dt>
              <dd><Chips values={c.domains} max={4} /></dd>
            </div>
            <div>
              <dt className="mb-1 text-xs text-muted-foreground">Osoby, pod które podszywa się kampania</dt>
              <dd><Chips values={c.persons} max={5} /></dd>
            </div>
          </dl>
        </div>

        <div className="min-w-0">
          <div className="mb-1 flex flex-wrap items-baseline justify-between gap-x-4">
            <h3 className="font-medium">Co łączy te materiały</h3>
            <span className="text-xs text-muted-foreground">
              {c.n_shared} wspólnych wartości w {plural(c.n_shared_kinds, "rodzaju śladów", "rodzajach śladów", "rodzajach śladów")}; pokazano najsilniejsze
            </span>
          </div>
          <ul className="divide-y">
            {c.top_shared.map((s) => (
              <li key={`${s.type}:${s.value}`} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1 py-2.5 text-sm">
                <span className="min-w-0">
                  <span className="mb-0.5 flex items-center gap-2 text-xs text-muted-foreground">
                    <GroupBadge label={s.group_label} linking={s.group !== "images" && s.group !== "descriptive"} /> {s.type_label}
                  </span>
                  <Link to={traceHref(s.type, s.value)} className="block truncate hover:underline" title={s.display}>
                    {s.type === "asset_phash" ? (
                      <span>{plural(s.n_values, "wspólny obraz", "wspólne obrazy", "wspólnych obrazów")}</span>
                    ) : (
                      <span className="font-mono text-xs">{s.display}</span>
                    )}
                    {s.n_values > 1 && s.type !== "asset_phash" && <span className="text-xs text-muted-foreground"> i {s.n_values - 1} więcej</span>}
                  </Link>
                </span>
                <span className="text-xs whitespace-nowrap text-muted-foreground tabular">w {s.count} z {c.size} mat.</span>
              </li>
            ))}
          </ul>
        </div>
      </CardContent>
      <CardFooter className="flex flex-wrap gap-2 border-t py-3">
        <Button asChild size="sm">
          <Link to={`/campaigns/${c.id}`}>Otwórz kampanię <ArrowRight /></Link>
        </Button>
        <Button asChild variant="outline" size="sm">
          <Link to={`/relations?tab=graph&focus=${c.id}`}><Network /> Pokaż w grafie</Link>
        </Button>
        <Button asChild variant="outline" size="sm">
          <Link to={`/campaigns/${c.id}?tab=watch`}><Radar /> Szukaj nowych materiałów tej kampanii</Link>
        </Button>
      </CardFooter>
    </Card>
  )
}

function SingletonGrid({ singles, familyOf }: { singles: CampaignCard[]; familyOf: Map<number, CampaignRef[]> }) {
  return (
    <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {singles.map((c) => {
        const m = c.members[0]
        const fam = familyOf.get(c.id) ?? []
        return (
          <li key={c.id} className="flex gap-4 rounded-xl bg-card p-4 ring-1 ring-foreground/10">
            <Link to={`/materials/${m.id}`} className="shrink-0">
              <Thumb src={m.thumb} alt={`Materiał ${matLabel(m)}`} className="h-24 w-20 ring-1 ring-border" />
            </Link>
            <div className="min-w-0 flex-1 space-y-1">
              <div className="flex items-baseline justify-between gap-2">
                <Link to={`/materials/${m.id}`} className="min-w-0 truncate font-medium hover:underline" title={m.name}>
                  Materiał {matLabel(m)}
                </Link>
                <CampaignBadge c={c} />
              </div>
              {m.scam_type_label && <p className="text-xs text-muted-foreground">{m.scam_type_label}</p>}
              <p className="line-clamp-2 text-sm">{m.product || m.title || "bez tytułu"}</p>
              {m.domains[0] && <p className="truncate font-mono text-xs text-muted-foreground">{m.domains[0]}</p>}
              {m.persons.length > 0 && <p className="truncate text-xs text-muted-foreground">Osoby: {m.persons.slice(0, 2).join(", ")}</p>}
              {fam.length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5 pt-1 text-xs">
                  <span className="text-muted-foreground">Podobna treść:</span>
                  {fam.map((r) => <CampaignBadge key={r.id} c={r} />)}
                </div>
              )}
            </div>
          </li>
        )
      })}
    </ul>
  )
}
