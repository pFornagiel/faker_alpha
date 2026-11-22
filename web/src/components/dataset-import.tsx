import { useMutation } from "@tanstack/react-query"
import { ArrowRight, FlaskConical, FolderInput } from "lucide-react"
import { useState } from "react"
import { Link } from "react-router"

import { api, type DataStatus, type Job } from "@/lib/api"
import { plural, useApi } from "@/lib/format"
import { Section } from "@/components/common"
import { JobProgress, useJob } from "@/components/job"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"

interface ImportResult {
  n: number
  campaigns: number
}

/** Import of a whole dataset folder (a path on the server) or of the synthetic demo dataset shipped with the code. */
export function DatasetImport({ showResultLink = true }: { showResultLink?: boolean }) {
  const status = useApi<DataStatus>("/api/data")
  const [typed, setTyped] = useState<string | null>(null)
  const [llmChoice, setLlmChoice] = useState<boolean | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const job = useJob<ImportResult>(jobId)

  const llmAvailable = !!status.data && (status.data.llm_available.claude_cli || status.data.llm_available.gemini) && status.data.llm_backend !== "none"
  const path = typed ?? (status.data?.default_dataset_exists ? status.data.default_dataset : "")
  const useLlm = llmAvailable && (llmChoice ?? true)

  const start = useMutation({
    mutationFn: (demo: boolean) =>
      demo ? api.post<Job>("/api/demo") : api.post<Job>("/api/dataset", { path: path.trim(), use_llm: useLlm, force: false }),
    onSuccess: (j) => setJobId(j.id),
  })
  const busy = start.isPending || job.data?.status === "running" || job.data?.status === "queued"
  const done = job.data?.status === "done" ? job.data.result : null

  return (
    <Section
      title="Wczytaj zbiór przypadków"
      description="Folder, w którym każdy podfolder to jeden przypadek: zapisane strony, zrzuty ekranu, wideo, zapis ruchu (HAR) albo pliki tekstowe. Przypadki, które już są w bazie, są pomijane."
      className="text-left"
    >
      <div className="space-y-5">
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (path.trim() && !busy) start.mutate(false)
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="dataset-path">Folder zbioru na komputerze, na którym działa serwer</Label>
            <div className="flex flex-wrap gap-2">
              <Input
                id="dataset-path"
                className="min-w-0 flex-1 basis-64 font-mono text-sm"
                placeholder={status.data?.default_dataset ?? "data/organizer/dane"}
                value={path}
                onChange={(e) => setTyped(e.target.value)}
                spellCheck={false}
                autoComplete="off"
              />
              <Button type="submit" disabled={!path.trim() || busy}>
                <FolderInput /> {busy && job.data?.meta?.path !== "demo" ? "Importuję…" : "Importuj zbiór"}
              </Button>
            </div>
            <p className="max-w-[80ch] text-xs text-pretty text-muted-foreground">
              Ścieżka względem katalogu projektu albo bezwzględna. W Dockerze katalog <code>./data</code> z komputera jest widoczny jako <code>data/</code>,
              więc zbiór skopiowany do <code>./data/moj_zbior</code> wpisz jako <code>data/moj_zbior</code>. Import trwa około 20 s na przypadek na CPU.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Switch id="dataset-llm" checked={useLlm} disabled={!llmAvailable} onCheckedChange={setLlmChoice} />
            <Label htmlFor="dataset-llm" className="font-normal">
              {llmAvailable
                ? "Użyj modelu językowego (tekst przypadków trafia do zewnętrznej usługi)"
                : "Model językowy nie jest skonfigurowany — atrybuty opisowe powstaną z reguł słownikowych"}
            </Label>
          </div>
        </form>

        {status.data?.demo_available && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t pt-4">
            <Button variant="outline" disabled={busy} onClick={() => start.mutate(true)}>
              <FlaskConical /> {busy && job.data?.meta?.path === "demo" ? "Wczytuję…" : "Wczytaj zbiór demonstracyjny"}
            </Button>
            <p className="min-w-0 flex-1 basis-64 text-sm text-pretty text-muted-foreground">
              8 zmyślonych przypadków dołączonych do kodu. Kilkanaście sekund, bez modelu językowego i bez zapytań do sieci.
            </p>
          </div>
        )}

        {start.error && <Alert variant="destructive"><AlertDescription>{(start.error as Error).message}</AlertDescription></Alert>}
        {jobId && <JobProgress job={job.data} error={job.error} />}
        {done && showResultLink && (
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
            <span>
              Przetworzono {plural(done.n, "przypadek", "przypadki", "przypadków")}. Kampanii w bazie: {done.campaigns}.
            </span>
            <Button asChild variant="link" size="sm" className="h-auto p-0"><Link to="/">Zobacz kampanie <ArrowRight /></Link></Button>
          </p>
        )}
      </div>
    </Section>
  )
}
