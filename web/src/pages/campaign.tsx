import { useMutation } from "@tanstack/react-query"
import { ArrowRight, Check, Network, Radar } from "lucide-react"
import { useState } from "react"
import { Link, useParams, useSearchParams } from "react-router"

import { api, type CampaignDetail, type Job, type MaterialSummary, type MatrixRow, type WatchResult, type WatchSeed } from "@/lib/api"
import { CAMPAIGN_CUT, FAMILY_CUT, fmtP, matLabel, plural, useApi } from "@/lib/format"
import { CampaignViewProfileChart } from "@/components/charts"
import {
  CampaignBadge, CampaignDot, Chips, ErrorState, GroupBadge, HelpTip, KV, Loading, PageHeader, PageTab, PageTabsList, RelationBadge, Section,
  Strength, StrengthLegend, Thumb, traceHref,
} from "@/components/common"
import { JobProgress, useJob } from "@/components/job"
import { SeedList, WATCH_HINT, WatchHits } from "@/components/watch"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tabs, TabsContent } from "@/components/ui/tabs"

export default function CampaignPage() {
  const { id } = useParams()
  const [params, setParams] = useSearchParams()
  const { data: c, error, isLoading } = useApi<CampaignDetail>(`/api/campaigns/${id}`)
  if (isLoading) return <Loading />
  if (error || !c) return <ErrorState error={error} />
  const byId = new Map(c.members.map((m) => [m.id, m]))
  const single = c.size === 1
  const validTabs = single ? ["overview", "members", "watch"] : ["overview", "members", "matrix", "watch"]
  const requested = params.get("tab") ?? "overview"
  const tab = validTabs.includes(requested) ? requested : "overview"
  const setTab = (v: string) => setParams((p) => { p.set("tab", v); return p }, { replace: true })
  const t = c.thresholds

  const campCut = t?.campaign_cut ?? CAMPAIGN_CUT
  const famCut = t?.family_cut ?? FAMILY_CUT

  return (
    <>
      <PageHeader
        docTitle={`${c.code} · ${c.name}`}
        title={
          <span className="flex min-w-0 items-center gap-3">
            <CampaignDot c={c} className="size-3.5" />
            <span className="min-w-0">{c.code} · {c.name}</span>
          </span>
        }
        description={
          single
            ? "Kampania z jednym materiałem: nie ma on wspólnego identyfikatora ani bliskiej treści z żadnym innym materiałem w bazie."
            : `${plural(c.size, "materiał", "materiały", "materiałów")}, które łączy ${c.n_shared} wspólnych wartości w ${plural(c.n_shared_kinds, "rodzaju śladów", "rodzajach śladów", "rodzajach śladów")}.`
        }
        actions={
          <>
            <Button asChild variant="outline">
              <Link to={`/relations?tab=graph&focus=${c.id}`}><Network /> Pokaż w grafie</Link>
            </Button>
            <Button variant="outline" onClick={() => setTab("watch")}>
              <Radar /> Szukaj nowych materiałów
            </Button>
          </>
        }
      />

      <Card>
        <CardContent>
          <dl className="grid gap-x-10 md:grid-cols-2">
            <KV label="Rodzaj oszustwa"><Chips values={c.scam_types.map((s) => s.label)} /></KV>
            <KV label="Produkty i platformy"><Chips values={c.products} /></KV>
            <KV label="Domeny docelowe"><Chips values={c.domains} max={6} /></KV>
            <KV label="Osoby, pod które się podszywa"><Chips values={c.persons} max={8} /></KV>
            <KV label="Okres aktywności">{c.date_range.length ? `${c.date_range[0]} → ${c.date_range[1]}` : "materiały nie zawierają dat"}</KV>
            {!single && c.mean_internal_p !== null && (
              <KV
                label="Średnia bliskość par"
                hint="Średnia z bliskości p wszystkich par materiałów w kampanii. p = 1 przy wspólnym identyfikatorze, w pozostałych przypadkach 1 − d (d = odległość treści). Im bliżej 1, tym więcej par jest połączonych bezpośrednio, a nie przez materiały-łączniki."
              >
                <span className="font-medium tabular">p = {fmtP(c.mean_internal_p)}</span>{" "}
                <span className="text-muted-foreground">z {plural(c.n_pairs, "pary", "par", "par")}</span>
              </KV>
            )}
          </dl>
        </CardContent>
      </Card>

      <Tabs value={tab} onValueChange={setTab} className="gap-6">
        <PageTabsList label="Kampania">
          <PageTab value="overview">{single ? "Otoczenie kampanii" : "Dlaczego to jedna kampania"}</PageTab>
          <PageTab value="members" count={c.size}>Materiały</PageTab>
          {!single && <PageTab value="matrix" count={c.matrix.length}>Wspólne ślady</PageTab>}
          <PageTab value="watch">Szukaj nowych materiałów</PageTab>
        </PageTabsList>

        <TabsContent value="overview" className="space-y-6">
          {!single && (
            <div className="grid items-start gap-6 xl:grid-cols-[1.2fr_1fr]">
              <Section
                title="Powiązania, które spinają kampanię"
                description="Najmniejszy zestaw par, który łączy wszystkie materiały w całość. Każda para poniżej jest połączona bezpośrednio — wspólnym identyfikatorem albo bliską treścią."
                aside={<StrengthLegend />}
              >
                <ul className="divide-y border-t">
                  {c.chain.map((s) => (
                    <li key={`${s.a}-${s.b}`} className="grid gap-x-6 gap-y-2 py-4 sm:grid-cols-[minmax(0,1fr)_auto]">
                      <div className="min-w-0 space-y-2">
                        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
                          <span className="font-medium">Materiał {s.a_name} ↔ Materiał {s.b_name}</span>
                          <Badge variant={s.basis === "wspólny identyfikator" || s.basis === "duplikat" ? "default" : "secondary"}>{s.basis}</Badge>
                        </div>
                        <Strength p={s.p} distance={s.distance} className="max-w-64" />
                        <ul className="list-disc space-y-0.5 pl-4 text-sm text-muted-foreground">
                          {s.reasons.map((r) => <li key={r} className="break-words">{r}</li>)}
                        </ul>
                      </div>
                      <Button asChild variant="outline" size="sm" className="justify-self-start">
                        <Link to={`/pair/${s.a}/${s.b}`}>Porównaj parę <ArrowRight /></Link>
                      </Button>
                    </li>
                  ))}
                </ul>
              </Section>

              <div className="space-y-6">
                {c.view_profile && c.view_profile.length > 0 && (
                  <Section
                    title="W czym materiały kampanii są do siebie podobne"
                    description="Średnie podobieństwo w każdym z pięciu widoków treści: między materiałami tej kampanii i między nimi a resztą bazy."
                    howToRead="niebieski słupek wyraźnie dłuższy od szarego = w tym widoku materiały kampanii są do siebie podobne bardziej niż do reszty bazy. „Brak danych” = widok nie jest dostępny po obu stronach żadnej pary."
                  >
                    <CampaignViewProfileChart profile={c.view_profile} />
                  </Section>
                )}
                <Outside c={c} byId={byId} campCut={campCut} famCut={famCut} />
              </div>
            </div>
          )}

          {single && <Outside c={c} byId={byId} campCut={campCut} famCut={famCut} />}

          {!single && (
            <Section
              title={`Wszystkie pary w kampanii (${c.links.length})`}
              description="Para może nie mieć żadnego wspólnego śladu i mimo to należeć do kampanii — wtedy łączą ją inne materiały (połączenie pośrednie)."
              contentClassName="px-0"
            >
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="pl-4">Para</TableHead>
                    <TableHead className="w-56">Bliskość p i odległość treści d</TableHead>
                    <TableHead>Relacja pary</TableHead>
                    <TableHead>Najmocniejszy dowód</TableHead>
                    <TableHead className="w-36 pr-4" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {c.links.map((l) => (
                    <TableRow key={`${l.a}-${l.b}`}>
                      <TableCell className="pl-4 font-medium whitespace-nowrap">Materiał {matLabel(byId.get(l.a))} ↔ {matLabel(byId.get(l.b))}</TableCell>
                      <TableCell><Strength p={l.p} distance={l.distance} /></TableCell>
                      <TableCell><RelationBadge relation={l.relation} /></TableCell>
                      <TableCell className="max-w-md whitespace-normal text-muted-foreground" title={l.reasons.map((r) => r.detail).join("\n")}>
                        <span className="line-clamp-2">{l.reasons[0]?.detail ?? "brak wspólnych śladów — połączenie pośrednie przez inne materiały"}</span>
                      </TableCell>
                      <TableCell className="pr-4 text-right">
                        <Button asChild variant="ghost" size="sm">
                          <Link to={`/pair/${l.a}/${l.b}`}>Porównaj parę <ArrowRight /></Link>
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Section>
          )}
        </TabsContent>

        <TabsContent value="members">
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {c.members.map((m) => <MemberCard key={m.id} m={m} />)}
          </ul>
        </TabsContent>

        {!single && (
          <TabsContent value="matrix">
            <EvidenceMatrix c={c} byId={byId} />
          </TabsContent>
        )}

        <TabsContent value="watch">
          <CampaignWatch ci={c.id} />
        </TabsContent>
      </Tabs>
    </>
  )
}

/** What sits just outside the campaign: nearest materials that were not joined, and sibling campaigns of the same family. */
function Outside({ c, byId, campCut, famCut }: { c: CampaignDetail; byId: Map<string, MaterialSummary>; campCut: number; famCut: number }) {
  return (
    <Section
      title="Co jest blisko, ale poza kampanią"
      description={`Materiały o podobnej treści (d ≤ ${famCut}), które nie zostały dołączone: do kampanii potrzeba wspólnego identyfikatora albo d ≤ ${campCut}.`}
    >
      {c.nearest_outside.length ? (
        <ul className="divide-y border-t">
          {c.nearest_outside.map((l) => {
            const insideName = matLabel(byId.get(l.inside))
            const out = l.a === l.inside ? l.b_info : l.a_info
            return (
              <li key={`${l.a}-${l.b}`} className="space-y-2 py-3.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="inline-flex flex-wrap items-center gap-2 font-medium">
                    Materiał {insideName} ↔ Materiał {out?.name} <CampaignBadge c={l.outside_campaign} />
                  </span>
                  <Button asChild variant="ghost" size="sm">
                    <Link to={`/pair/${l.a}/${l.b}`}>Porównaj parę <ArrowRight /></Link>
                  </Button>
                </div>
                <div className="flex flex-wrap items-start gap-x-4 gap-y-2">
                  <Strength p={l.p} distance={l.distance} className="w-52" />
                  <RelationBadge relation={l.relation} />
                </div>
                <p className="text-xs text-muted-foreground">{l.reasons.map((r) => r.detail).join(" · ") || "brak wspólnych śladów"}</p>
              </li>
            )
          })}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">Żaden materiał spoza kampanii nie ma treści podobnej na poziomie d ≤ {famCut}.</p>
      )}
      <div className="mt-4 border-t pt-4">
        <h3 className="flex items-center gap-1.5 font-medium">
          Kampanie z tej samej rodziny
          <HelpTip label="Co to jest rodzina kampanii">
            Rodzina to osobne kampanie o podobnej treści (d ≤ {famCut}), ale bez wspólnego identyfikatora — np. ten sam scenariusz oszustwa na innej infrastrukturze.
          </HelpTip>
        </h3>
        {c.siblings.length ? (
          <ul className="mt-2 flex flex-col gap-1.5">
            {c.siblings.map((s) => <li key={s.id}><CampaignBadge c={s} withName /></li>)}
          </ul>
        ) : (
          <p className="mt-1 text-sm text-muted-foreground">Ta kampania nie ma rodziny — żadna inna kampania nie ma podobnej treści.</p>
        )}
      </div>
    </Section>
  )
}

function MemberCard({ m }: { m: MaterialSummary }) {
  const lbl = matLabel(m)
  const facts = [
    m.signals?.has_web ? "zapis strony" : null,
    m.signals?.has_faces ? plural(m.signals.n_faces, "twarz", "twarze", "twarzy") : null,
    m.signals?.n_linking_indicators ? plural(m.signals.n_linking_indicators, "identyfikator", "identyfikatory", "identyfikatorów") : null,
  ].filter(Boolean)
  return (
    <li>
      <Link to={`/materials/${m.id}`} className="group flex h-full gap-4 rounded-xl bg-card p-4 ring-1 ring-foreground/10 transition-shadow hover:ring-foreground/30">
        <Thumb src={m.thumb} alt={`Materiał ${lbl}`} className="h-28 w-24 shrink-0 ring-1 ring-border" />
        <div className="min-w-0 flex-1 space-y-1">
          <div className="font-medium group-hover:underline" title={m.name}>Materiał {lbl}</div>
          <p className="line-clamp-2 text-sm text-muted-foreground">{m.title || "bez tytułu"}</p>
          <p className="truncate font-mono text-xs text-muted-foreground">{m.domains[0] ?? m.source_label}</p>
          {m.persons.length > 0 && <p className="truncate text-xs text-muted-foreground">Osoby: {m.persons.slice(0, 3).join(", ")}</p>}
          {facts.length > 0 && <p className="pt-0.5 text-xs text-muted-foreground">{facts.join(" · ")}</p>}
        </div>
      </Link>
    </li>
  )
}

function TraceValue({ r }: { r: MatrixRow }) {
  const first = r.values[0]
  if (r.type === "asset_phash") {
    return (
      <div className="flex flex-wrap gap-1.5">
        {r.thumbs.slice(0, 8).map((t) => (
          <a key={t} href={t} target="_blank" rel="noreferrer"><img src={t} alt="wspólny obraz" loading="lazy" className="size-12 rounded object-cover ring-1 ring-border" /></a>
        ))}
        {r.values.length > 8 && <span className="self-center text-xs text-muted-foreground">+{r.values.length - 8}</span>}
      </div>
    )
  }
  return (
    <div className="flex min-w-0 items-center gap-2">
      <Link to={traceHref(r.type, first.value)} className="block min-w-0 truncate font-mono text-xs underline-offset-4 hover:underline" title={first.display}>
        {first.display}
      </Link>
      {r.values.length > 1 && (
        <Popover>
          <PopoverTrigger asChild>
            <Button variant="link" size="sm" className="h-auto shrink-0 p-0 text-xs">+{r.values.length - 1} więcej</Button>
          </PopoverTrigger>
          <PopoverContent className="w-96 max-w-[90vw]">
            <p className="mb-2 text-sm font-medium">{r.type_label} — {r.values.length} wartości</p>
            <ul className="max-h-64 space-y-1 overflow-y-auto">
              {r.values.map((v) => (
                <li key={v.value}>
                  <Link to={traceHref(r.type, v.value)} className="font-mono text-xs break-all underline-offset-4 hover:underline">{v.display}</Link>
                </li>
              ))}
            </ul>
          </PopoverContent>
        </Popover>
      )}
    </div>
  )
}

function EvidenceMatrix({ c, byId }: { c: CampaignDetail; byId: Map<string, MaterialSummary> }) {
  return (
    <Section
      title="Który ślad występuje w których materiałach"
      description="Każdy wiersz to wartość obecna w co najmniej dwóch materiałach kampanii. Na górze identyfikatory, które same łączą materiały; niżej wspólne obrazy i cechy opisowe, które tylko wspierają ocenę."
      howToRead="znak ✓ w kolumnie materiału = ta wartość została w nim znaleziona. Ciemna etykieta = identyfikator łączący, jasna = ślad pomocniczy. Kliknij wartość, aby zobaczyć wszystkie materiały w bazie, które ją zawierają."
      contentClassName="px-0"
    >
      <div className="hidden overflow-x-auto md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-44 pl-4">Rodzaj śladu</TableHead>
              <TableHead>Wspólna wartość</TableHead>
              {c.members.map((m) => (
                <TableHead key={m.id} className="w-20 text-center">
                  <Link to={`/materials/${m.id}`} className="underline-offset-4 hover:underline" title={`Materiał ${m.name}`}>Mat. {matLabel(m)}</Link>
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {c.matrix.map((r) => (
              <TableRow key={`${r.type}:${r.members.join()}:${r.values[0].value}`}>
                <TableCell className="pl-4"><GroupBadge label={r.group_label} linking={r.linking} /></TableCell>
                <TableCell className="max-w-lg space-y-1">
                  <div className="text-xs text-muted-foreground">
                    {r.type_label}{r.values.length > 1 && <span className="font-medium text-foreground"> ×{r.values.length}</span>}
                  </div>
                  <TraceValue r={r} />
                </TableCell>
                {c.members.map((m) => (
                  <TableCell key={m.id} className="text-center">
                    {r.members.includes(m.id) ? <Check className="mx-auto size-5 text-primary" aria-label="występuje" /> : <span className="text-muted-foreground/40" aria-label="brak">·</span>}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <ul className="divide-y border-t md:hidden">
        {c.matrix.map((r) => (
          <li key={`${r.type}:${r.members.join()}:${r.values[0].value}`} className="space-y-1.5 px-4 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <GroupBadge label={r.group_label} linking={r.linking} />
              <span className="text-xs text-muted-foreground">{r.type_label}{r.values.length > 1 && ` ×${r.values.length}`}</span>
            </div>
            <TraceValue r={r} />
            <p className="text-xs">w materiałach: <span className="font-medium">{r.members.map((m) => matLabel(byId.get(m))).join(", ")}</span></p>
          </li>
        ))}
      </ul>
    </Section>
  )
}

function CampaignWatch({ ci }: { ci: number }) {
  const [analyse, setAnalyse] = useState(false)
  const [jobId, setJobId] = useState<string | null>(null)
  const job = useJob<WatchResult>(jobId)
  const seeds = useApi<{ seeds: WatchSeed[] }>(`/api/scanner/seeds?campaign=${ci}`)
  const run = useMutation({
    mutationFn: () => api.post<Job>("/api/scanner/watch", { campaign: ci, analyse }),
    onSuccess: (j) => setJobId(j.id),
  })
  const busy = run.isPending || job.data?.status === "running" || job.data?.status === "queued"
  const res = job.data?.status === "done" ? job.data.result : null
  const list = res?.seeds ?? seeds.data?.seeds ?? []
  return (
    <Section
      title={<span className="flex items-center gap-1.5">Szukaj nowych materiałów tej kampanii w źródłach publicznych <HelpTip label="Jak działa wyszukiwanie">{WATCH_HINT}</HelpTip></span>}
      description="Identyfikatory tej kampanii (domeny, ID reklamodawców, nazwy produktów) są wysyłane jako zapytania do bibliotek reklam i porównywane z listą ostrzeżeń CERT Polska. Każde takie zapytanie to „ziarno”."
    >
      <div className="space-y-5">
        <div>
          <h3 className="mb-2 font-medium">{res ? "Zapytania użyte w tym wyszukiwaniu" : "Zapytania, które zostaną wysłane"}</h3>
          {seeds.isLoading ? <Loading /> : <SeedList seeds={list} showCampaign={false} />}
        </div>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-3 border-t pt-4">
          <Button onClick={() => run.mutate()} disabled={busy || !list.length}>
            <Radar /> {busy ? "Przeszukuję źródła…" : "Szukaj w źródłach"}
          </Button>
          <div className="flex items-start gap-2">
            <Checkbox id={`wan-${ci}`} checked={analyse} onCheckedChange={(v) => setAnalyse(v === true)} className="mt-0.5" />
            <Label htmlFor={`wan-${ci}`} className="leading-snug font-normal">Od razu przeanalizuj nowe trafienia i zapisz je w bazie (najwyżej 5)</Label>
          </div>
        </div>
        {jobId && <JobProgress job={job.data} error={job.error} />}
        {res && (
          <div className="space-y-3">
            <p className="text-sm">
              Znaleziono {res.found}, nowych <span className="font-semibold">{res.fresh}</span>
              {res.analysed.length > 0 && <>, przeanalizowano {res.analysed.length}, potwierdzono <span className="font-semibold">{res.confirmed}</span></>}.
              {Object.keys(res.errors).length > 0 && <span className="text-muted-foreground"> Niedostępne: {Object.keys(res.errors).slice(0, 4).join(", ")}.</span>}
              {" "}<Link to="/analyse?tab=scanner" className="underline underline-offset-4">Otwórz pełny skaner</Link>
            </p>
            {res.hits.length ? <WatchHits items={res.hits} showSeedCampaign={false} /> : <p className="text-sm text-muted-foreground">Źródła nie zwróciły żadnych pozycji dla tych ziaren.</p>}
          </div>
        )}
      </div>
    </Section>
  )
}
