import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Download, FolderInput, RefreshCw, Share2 } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"

import { api, type DataStatus, type Job } from "@/lib/api"
import { fmtDate, useApi } from "@/lib/format"
import { ErrorState, KV, Loading, PageHeader, Section } from "@/components/common"
import { JobProgress, useJob } from "@/components/job"
import { EventLog } from "@/pages/scanner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"

export default function DataPage() {
  const { data, error, isLoading } = useApi<DataStatus>("/api/data")
  const qc = useQueryClient()
  const [path, setPath] = useState("")
  const [useLlm, setUseLlm] = useState(true)
  const [force, setForce] = useState(false)
  const [jobId, setJobId] = useState<string | null>(null)
  const job = useJob<{ n: number; campaigns: number }>(jobId)
  const initialised = useRef(false)
  useEffect(() => {
    if (data && !initialised.current) {
      initialised.current = true
      setPath(data.default_dataset)
    }
  }, [data])

  const load = useMutation({
    mutationFn: () => api.post<Job>("/api/dataset", { path, use_llm: useLlm, force }),
    onSuccess: (j) => setJobId(j.id),
    onError: (e) => toast.error((e as Error).message),
  })
  const recluster = useMutation({
    mutationFn: () => api.post<{ campaigns: number; seconds: number }>("/api/recluster"),
    onSuccess: (r) => {
      toast.success(`Przeliczono: ${r.campaigns} kampanii (${r.seconds} s)`)
      qc.invalidateQueries()
    },
  })
  const neo = useMutation({
    mutationFn: () => api.post<{ message: string }>("/api/neo4j"),
    onSuccess: (r) => toast(r.message),
    onError: (e) => toast.error((e as Error).message),
  })

  if (isLoading) return <Loading />
  if (error || !data) return <ErrorState error={error} />
  const busy = load.isPending || job.data?.status === "running" || job.data?.status === "queued"

  return (
    <>
      <PageHeader title="Dane i eksport" description="Stan bazy, wczytywanie zbioru przypadków, przeliczanie kampanii i eksport wyników do dalszej analizy." />

      <div className="grid items-start gap-4 lg:grid-cols-2">
        <Section title="Stan bazy">
          <dl className="divide-y">
            <KV label="Materiały">{data.n_materials}</KV>
            <KV label="Kampanie">{data.n_campaigns} <span className="text-muted-foreground">({data.n_multi} wielomateriałowe)</span></KV>
            <KV label="Według źródła">
              <div className="flex flex-wrap gap-1">{Object.entries(data.by_source).map(([k, v]) => <Badge key={k} variant="secondary">{k}: {v}</Badge>)}</div>
            </KV>
            <KV label="Ostatnio dodany">{fmtDate(data.last_added)}</KV>
            <KV label="Plik bazy"><span className="font-mono text-xs break-all">{data.store}</span></KV>
            <KV label="Model językowy" hint="Kolejność prób: Claude (Claude Code CLI) → Gemini (wymaga klucza GEMINI_API_KEY) → reguły słownikowe (zawsze dostępne). Zmiana przez zmienną FTF_LLM.">
              {data.llm_backend_label}
              <span className="block text-xs text-muted-foreground">
                Claude CLI: {data.llm_available.claude_cli ? "dostępny" : "niedostępny"} · Gemini: {data.llm_available.gemini ? "klucz ustawiony" : "brak klucza"}
              </span>
            </KV>
          </dl>
        </Section>

        <Section title="Wczytaj zbiór przypadków" description="Folder, w którym każdy podfolder to jeden przypadek (np. zbiór organizatora). Przypadki już obecne w bazie są pomijane.">
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="path">Ścieżka do folderu (względem katalogu projektu lub bezwzględna)</Label>
              <Input id="path" value={path} onChange={(e) => setPath(e.target.value)} className="font-mono text-xs" />
            </div>
            <div className="flex flex-wrap gap-x-6 gap-y-2">
              <div className="flex items-center gap-2"><Switch id="dllm" checked={useLlm} onCheckedChange={setUseLlm} /><Label htmlFor="dllm" className="font-normal">Model językowy</Label></div>
              <div className="flex items-center gap-2"><Switch id="force" checked={force} onCheckedChange={setForce} /><Label htmlFor="force" className="font-normal">Przetwórz ponownie przypadki już w bazie</Label></div>
            </div>
            <p className="text-xs text-muted-foreground">Ekstrakcja trwa ok. 0,5–3 min na przypadek na CPU. Po imporcie kampanie są przeliczane automatycznie.</p>
            <Button onClick={() => load.mutate()} disabled={busy || !path.trim()}><FolderInput /> {busy ? "Wczytuję…" : "Wczytaj"}</Button>
            {jobId && <JobProgress job={job.data} error={job.error} />}
            {job.data?.status === "done" && job.data.result && <p className="text-sm">Przetworzono {job.data.result.n} przypadków → {job.data.result.campaigns} kampanii.</p>}
          </div>
        </Section>
      </div>

      <div className="grid items-start gap-4 lg:grid-cols-2">
        <Section title="Przelicz kampanie" description="Ponownie porównuje wszystkie pary i grupuje materiały — np. po zmianie wag w ftf/config.py. Kody kampanii (C1, C2…) mogą się zmienić.">
          <Button
            variant="outline"
            disabled={recluster.isPending}
            onClick={() => { if (window.confirm("Przeliczyć kampanie? Kody kampanii (C1, C2…) mogą się zmienić.")) recluster.mutate() }}
          >
            <RefreshCw className={recluster.isPending ? "animate-spin" : ""} /> Przelicz
          </Button>
        </Section>
        <Section title="Eksport" description="Pliki do dalszej analizy: lista kampanii, lista par z uzasadnieniem, graf dla bazy Neo4j.">
          <div className="flex flex-wrap gap-2">
            <Button asChild variant="outline"><a href="/api/export/campaigns.json"><Download /> Kampanie (JSON)</a></Button>
            <Button asChild variant="outline"><a href="/api/export/links.csv"><Download /> Pary z uzasadnieniem (CSV)</a></Button>
            <Button asChild variant="outline"><a href="/api/export/graph.cypher"><Download /> Graf (Cypher / Neo4j)</a></Button>
            {data.neo4j && <Button variant="outline" onClick={() => neo.mutate()} disabled={neo.isPending}><Share2 /> Wyślij do Neo4j</Button>}
          </div>
          {!data.neo4j && <p className="mt-2 text-xs text-muted-foreground">Bezpośredni zapis do Neo4j jest dostępny po uruchomieniu bazy Neo4j (instrukcja w README).</p>}
        </Section>
      </div>

      <EventLog title="Ostatnie zdarzenia" events={data.recent} empty="Brak zdarzeń — import zbioru, analizy i skany pojawią się tutaj." />
    </>
  )
}
