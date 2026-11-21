import { useMutation, useQueryClient } from "@tanstack/react-query"
import { ExternalLink, Play, Radar, RotateCcw, Search, Square, Timer } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { Link } from "react-router"
import { toast } from "sonner"

import { api, type EventView, type Job, type ScanItem, type ScannerStatus, type WatchResult, type WatchSeed } from "@/lib/api"
import { fmtDate, fmtP, plural, useApi } from "@/lib/format"
import { ErrorState, HelpTip, Loading, PageHeader, Section } from "@/components/common"
import { JobProgress, useJob } from "@/components/job"
import { SeedList, WATCH_HINT, WatchHits } from "@/components/watch"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"

const SOURCES = "lista ostrzeżeń CERT Polska, Microsoft Ad Library, Google Ads Transparency i Meta Ad Library"

export default function ScannerPage() {
  const { data, error, isLoading } = useApi<ScannerStatus>("/api/scanner", { refetchInterval: 15000 })
  const qc = useQueryClient()
  const [kw, setKw] = useState("")
  const [analyse, setAnalyse] = useState(false)
  const [watch, setWatch] = useState(false)
  const [minutes, setMinutes] = useState(30)
  const [jobId, setJobId] = useState<string | null>(null)
  const job = useJob<{ found: number; fresh: number; errors: Record<string, string> }>(jobId)
  const initialised = useRef(false)
  useEffect(() => {
    if (data && !initialised.current) {
      initialised.current = true
      setKw((data.config?.keywords ?? data.default_keywords).join(", "))
    }
  }, [data])
  const keywords = kw.split(",").map((k) => k.trim()).filter(Boolean)
  const minutesOk = minutes >= 5 && minutes <= 1440

  const run = useMutation({
    mutationFn: () => api.post<Job>("/api/scanner/run", { keywords, analyse, watch }),
    onSuccess: (j) => setJobId(j.id),
  })
  const startStop = useMutation({
    mutationFn: (on: boolean) => (on ? api.post<{ message: string }>("/api/scanner/start", { minutes, keywords, analyse, watch }) : api.post<{ message: string }>("/api/scanner/stop")),
    onSuccess: (r) => {
      toast(r.message)
      qc.invalidateQueries({ queryKey: ["/api/scanner"] })
    },
  })

  if (isLoading) return <Loading />
  if (error || !data) return <ErrorState error={error} />
  const busy = run.isPending || job.data?.status === "running" || job.data?.status === "queued"

  return (
    <>
      <PageHeader
        title="Skaner źródeł"
        description="Przeszukuje listę ostrzeżeń CERT Polska oraz biblioteki reklam (Microsoft, Google, Meta) po słowach kluczowych i ocenia, jak podejrzana jest każda znaleziona pozycja. Opcjonalnie od razu analizuje najbardziej podejrzane."
      />

      <div className="grid items-start gap-4 lg:grid-cols-[1.4fr_1fr]">
        <Section title="Ustawienia skanu" description="Te same ustawienia obowiązują dla skanu jednorazowego i cyklicznego.">
          <div className="space-y-4">
            <div className="space-y-1.5">
              <div className="flex items-center justify-between gap-2">
                <Label htmlFor="kw">Słowa kluczowe (oddzielone przecinkami)</Label>
                <Button variant="ghost" size="sm" className="h-7" onClick={() => setKw(data.default_keywords.join(", "))}><RotateCcw /> domyślne</Button>
              </div>
              <Textarea id="kw" rows={2} value={kw} onChange={(e) => setKw(e.target.value)} />
              <p className="text-xs text-muted-foreground">Biblioteki reklam są przeszukiwane po pierwszych 4 słowach; lista CERT Polska jest filtrowana po wszystkich.</p>
            </div>
            <div className="flex items-start gap-2">
              <Checkbox id="an" checked={analyse} onCheckedChange={(v) => setAnalyse(v === true)} className="mt-0.5" />
              <Label htmlFor="an" className="leading-snug font-normal">
                Od razu analizuj nowe pozycje z oceną ≥ 0.50 i zapisz je w bazie (do 5 na skan; używa modelu językowego, trwa kilka minut)
              </Label>
            </div>
            <div className="flex items-start gap-2">
              <Checkbox id="wt" checked={watch} onCheckedChange={(v) => setWatch(v === true)} className="mt-0.5" />
              <Label htmlFor="wt" className="leading-snug font-normal">
                Po skanie po słowach kluczowych szukaj też materiałów znanych kampanii (ich domeny, ID reklamodawców i produkty jako hasła — sekcja niżej)
              </Label>
            </div>
            <div className="space-y-2 border-t pt-4">
              <p className="text-sm">Skan jednorazowy kontaktuje się z: {SOURCES}{data.meta_token ? "" : " (Meta pominięta — brak tokenu)"}. Trwa zwykle 10–60 s.</p>
              <Button onClick={() => run.mutate()} disabled={busy || !keywords.length}>
                <Play /> {busy ? "Skanuję…" : "Skanuj teraz"}
              </Button>
              {!keywords.length && <p className="text-xs text-muted-foreground">Wpisz co najmniej jedno słowo kluczowe.</p>}
            </div>
            {jobId && <JobProgress job={job.data} error={job.error} />}
            {job.data?.status === "done" && job.data.result && (
              <p className="text-sm">
                Znaleziono {job.data.result.found} pozycji, nowych: <span className="font-medium">{job.data.result.fresh}</span>.
                {Object.keys(job.data.result.errors ?? {}).length > 0 && <span className="text-muted-foreground"> Niedostępne źródła: {Object.keys(job.data.result.errors).join(", ")}.</span>}
              </p>
            )}
          </div>
        </Section>
        <Section title="Skan cykliczny" description="Powtarza skan w tle z ustawieniami z lewej, dopóki serwer działa.">
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className={`size-2 rounded-full ${data.running ? "bg-[var(--status-good)]" : "bg-muted-foreground/40"}`} />
              <span className="text-sm font-medium">{data.running ? "Włączony" : "Wyłączony"}</span>
              {data.running && <span className="text-sm text-muted-foreground">{data.next_run ? `następny: ${fmtDate(data.next_run)}` : "brak zaplanowanego uruchomienia — zatrzymaj i włącz ponownie"}</span>}
            </div>
            {data.running && data.config && (
              <p className="text-xs text-muted-foreground">
                co {data.config.minutes} min · słowa: {data.config.keywords.slice(0, 4).join(", ")}{data.config.keywords.length > 4 ? "…" : ""} · analiza: {data.config.analyse ? "tak" : "nie"} · obserwacja kampanii: {data.config.watch ? "tak" : "nie"}
              </p>
            )}
            <div className="flex flex-wrap items-center gap-2">
              <Label htmlFor="min" className="font-normal">co</Label>
              <Input id="min" type="number" min={5} max={1440} value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} className="w-24" aria-invalid={!minutesOk} />
              <span className="text-sm">min</span>
              {data.running ? (
                <Button variant="outline" onClick={() => startStop.mutate(false)}><Square /> Zatrzymaj</Button>
              ) : (
                <Button variant="outline" disabled={!minutesOk || !keywords.length} onClick={() => startStop.mutate(true)}><Timer /> Włącz</Button>
              )}
            </div>
            {!minutesOk && <p className="text-xs text-destructive">Podaj od 5 do 1440 minut.</p>}
            <p className="text-xs text-muted-foreground">
              Meta Ad Library: {data.meta_token ? "token skonfigurowany." : "brak tokenu dostępu — wyszukiwanie Meta jest pomijane (instrukcja uzyskania tokenu w README)."}
            </p>
          </div>
        </Section>
      </div>

      <CampaignWatch metaToken={data.meta_token} />
      {data.watch_found.length > 0 && (
        <Section
          title="Materiały znalezione przez znane kampanie"
          description={`${data.watch_found.length} zapisanych tropów (najnowsze u góry). Kolumna „Weryfikacja” pokazuje wynik zwykłego przypisania — tylko ono łączy materiał z kampanią.`}
        >
          <WatchHits items={data.watch_found} />
        </Section>
      )}
      <LibrarySearch />
      <FoundTable items={data.found} />
      <EventLog title="Dziennik skanów" events={data.events} empty="Jeszcze nie uruchomiono skanu." />
    </>
  )
}

function CampaignWatch({ metaToken }: { metaToken: boolean }) {
  const [analyse, setAnalyse] = useState(false)
  const [jobId, setJobId] = useState<string | null>(null)
  const job = useJob<WatchResult>(jobId)
  const seeds = useApi<{ seeds: WatchSeed[]; max_campaigns: number; max_seeds: number }>("/api/scanner/seeds")
  const run = useMutation({
    mutationFn: () => api.post<Job>("/api/scanner/watch", { analyse }),
    onSuccess: (j) => setJobId(j.id),
  })
  const busy = run.isPending || job.data?.status === "running" || job.data?.status === "queued"
  const res = job.data?.status === "done" ? job.data.result : null
  return (
    <Section
      title={<span className="flex items-center gap-1">Szukaj materiałów znanych kampanii <HelpTip label="Skąd biorą się ziarna">{WATCH_HINT}</HelpTip></span>}
      description={`Wyszukiwanie po identyfikatorach wykrytych kampanii: domeny → Google Ads Transparency, Microsoft Ad Library i nowe wpisy CERT Polska; ID reklamodawcy Google → Google Ads Transparency; nazwy produktów → Microsoft Ad Library${metaToken ? ", Meta Ad Library" : ""} i CERT Polska. Do ${seeds.data?.max_campaigns ?? 8} największych kampanii, po ${seeds.data?.max_seeds ?? 4} ziarna.`}
    >
      <div className="grid items-start gap-6 lg:grid-cols-[1fr_1.2fr]">
        <div className="space-y-3">
          <div className="flex items-start gap-2">
            <Checkbox id="wan" checked={analyse} onCheckedChange={(v) => setAnalyse(v === true)} className="mt-0.5" />
            <Label htmlFor="wan" className="leading-snug font-normal">
              Od razu przeanalizuj nowe trafienia (do 5) i sprawdź zwykłym przypisaniem, czy należą do kampanii — zapisuje je w bazie
            </Label>
          </div>
          <Button onClick={() => run.mutate()} disabled={busy || !seeds.data?.seeds.length}>
            <Radar /> {busy ? "Szukam…" : "Szukaj materiałów znanych kampanii"}
          </Button>
          {jobId && <JobProgress job={job.data} error={job.error} />}
          {res && (
            <p className="text-sm">
              {plural(res.seeds.length, "ziarno", "ziarna", "ziaren")} · znaleziono {res.found}, nowych <span className="font-medium">{res.fresh}</span>
              {res.analysed.length > 0 && <>, przeanalizowano {res.analysed.length}, potwierdzono <span className="font-medium">{res.confirmed}</span></>}.
              {Object.keys(res.errors).length > 0 && <span className="text-muted-foreground"> Niedostępne: {Object.keys(res.errors).slice(0, 4).join(", ")}{Object.keys(res.errors).length > 4 ? "…" : ""}.</span>}
            </p>
          )}
        </div>
        <div className="space-y-2">
          <p className="text-sm font-medium">Ziarna wyszukiwania</p>
          {seeds.isLoading ? <Loading /> : <div className="max-h-72 overflow-y-auto"><SeedList seeds={seeds.data?.seeds ?? []} /></div>}
        </div>
      </div>
    </Section>
  )
}

export function EventLog({ title, events, empty }: { title: string; events: EventView[]; empty: string }) {
  return (
    <Section title={title}>
      {events.length ? (
        <ul className="max-h-80 divide-y overflow-y-auto text-sm">
          {events.map((e, i) => (
            <li key={i} className="grid gap-x-3 gap-y-0.5 py-2 sm:grid-cols-[10rem_9rem_1fr]">
              <span className="text-xs text-muted-foreground tabular sm:text-sm">{fmtDate(e.ts)}</span>
              <span className="font-medium sm:font-normal">{e.label}</span>
              <span className="min-w-0 break-words text-muted-foreground">{e.text}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">{empty}</p>
      )}
    </Section>
  )
}

function LibrarySearch() {
  const [q, setQ] = useState("")
  const [sub, setSub] = useState<string | null>(null)
  const { data, isFetching, error } = useApi<{ results: ScanItem[]; errors: Record<string, string> }>(sub ? `/api/library-search?q=${encodeURIComponent(sub)}` : null)
  return (
    <Section
      title="Szukaj w bibliotekach reklam"
      description="Jednorazowe wyszukiwanie w Microsoft Ad Library, Google Ads Transparency i Meta Ad Library: nazwa produktu, platformy, nazwisko, hasło reklamy. Wyniki nie są zapisywane."
    >
      <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); if (q.trim().length >= 2) setSub(q.trim()) }}>
        <Input placeholder="np. Świtowin, Uromexil, Brzoska…" value={q} onChange={(e) => setQ(e.target.value)} className="max-w-sm" />
        <Button type="submit" variant="outline" disabled={isFetching || q.trim().length < 2}><Search /> {isFetching ? "Szukam…" : "Szukaj"}</Button>
      </form>
      {error && <Alert variant="destructive" className="mt-3"><AlertDescription>{(error as Error).message}</AlertDescription></Alert>}
      {data && (
        <div className="mt-4 space-y-2">
          {Object.entries(data.errors).length > 0 && (
            <p className="text-xs text-muted-foreground">Niedostępne źródła: {Object.entries(data.errors).map(([k, v]) => `${k} (${v.slice(0, 80)})`).join("; ")}</p>
          )}
          {data.results.length ? <ItemsList items={data.results} /> : <p className="text-sm text-muted-foreground">Brak wyników dla „{sub}”.</p>}
        </div>
      )}
    </Section>
  )
}

function FoundTable({ items }: { items: ScanItem[] }) {
  const [min, setMin] = useState(0.3)
  const safeMin = Math.max(0, Math.min(1, Number.isFinite(min) ? min : 0))
  const rows = useMemo(() => items.filter((r) => r.score >= safeMin), [items, safeMin])
  return (
    <Section
      title={<span className="flex items-center gap-1">Znalezione podejrzane pozycje <HelpTip label="Jak liczona jest ocena">Ocena 0–1 to szybka selekcja, nie werdykt: +0.6 za obecność na liście CERT Polska, +0.3 za znaną osobę, +0.2 za słownictwo typowe dla oszustw, +0.15 za ryzykowną końcówkę domeny (np. .live, .top), +0.1 za markę.</HelpTip></span>}
      description={`${rows.length} z ${items.length} zapisanych pozycji (z wcześniejszych skanów).`}
      aside={
        <div className="flex items-center gap-2 text-sm">
          <Label htmlFor="minscore" className="font-normal text-muted-foreground">pokaż z oceną ≥</Label>
          <Input id="minscore" type="number" step={0.1} min={0} max={1} value={min} onChange={(e) => setMin(Number(e.target.value))} className="h-8 w-20" />
        </div>
      }
    >
      {rows.length ? <ItemsList items={rows} /> : <p className="text-sm text-muted-foreground">{items.length ? "Brak pozycji powyżej wybranej oceny." : "Brak pozycji — uruchom skan."}</p>}
    </Section>
  )
}

function ItemsList({ items }: { items: ScanItem[] }) {
  const target = (r: ScanItem) => r.url || (r.domain ? `https://${r.domain}/` : "")
  return (
    <>
      <div className="hidden overflow-x-auto md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-20">Ocena</TableHead>
              <TableHead>Źródło</TableHead>
              <TableHead>Pozycja</TableHead>
              <TableHead>Dlaczego podejrzana</TableHead>
              <TableHead className="w-28" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.slice(0, 200).map((r, i) => (
              <TableRow key={i}>
                <TableCell className="font-medium tabular">{fmtP(r.score)}</TableCell>
                <TableCell className="text-sm whitespace-nowrap">{r.source_label ?? r.source}</TableCell>
                <TableCell className="max-w-md">
                  <div className="truncate font-medium" title={r.title || r.name || r.domain}>{r.title || r.name || r.domain || r.advertiser || "—"}</div>
                  <div className="truncate font-mono text-xs text-muted-foreground">{r.domain || r.url || r.advertiser}</div>
                </TableCell>
                <TableCell className="max-w-sm"><div className="flex flex-wrap gap-1">
                  {r.seed && <Badge variant="outline" className="font-normal" title={r.seed.campaign_label}>ziarno {r.seed.campaign_label.split(" · ")[0]}: {r.seed.value}</Badge>}
                  {r.why.map((w) => <Badge key={w} variant="secondary" className="font-normal">{w}</Badge>)}
                </div></TableCell>
                <TableCell>
                  {target(r) && (
                    <div className="flex items-center gap-1">
                      <Button asChild variant="ghost" size="sm"><Link to={`/analyse?url=${encodeURIComponent(target(r))}`}>Analizuj</Link></Button>
                      <a href={target(r)} target="_blank" rel="noreferrer noopener" className="text-muted-foreground hover:text-foreground" aria-label="Otwórz źródło w nowej karcie"><ExternalLink className="size-4" /></a>
                    </div>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <ul className="space-y-3 md:hidden">
        {items.slice(0, 100).map((r, i) => (
          <li key={i} className="space-y-1.5 rounded-lg border p-3 text-sm">
            <div className="flex items-start justify-between gap-2">
              <span className="min-w-0 font-medium break-words">{r.title || r.name || r.domain || r.advertiser || "—"}</span>
              <span className="shrink-0 font-semibold tabular">{fmtP(r.score)}</span>
            </div>
            <div className="font-mono text-xs break-all text-muted-foreground">{r.domain || r.url || r.advertiser}</div>
            <div className="text-xs text-muted-foreground">{r.source_label ?? r.source}</div>
            <div className="flex flex-wrap gap-1">{r.why.map((w) => <Badge key={w} variant="secondary" className="font-normal">{w}</Badge>)}</div>
            {target(r) && <Button asChild variant="outline" size="sm" className="w-full"><Link to={`/analyse?url=${encodeURIComponent(target(r))}`}>Analizuj</Link></Button>}
          </li>
        ))}
      </ul>
    </>
  )
}
