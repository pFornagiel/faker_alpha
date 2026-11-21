import { useQuery, useQueryClient } from "@tanstack/react-query"
import { CheckCircle2, Loader2, XCircle } from "lucide-react"
import { useEffect, useState } from "react"

import { api, type Job } from "@/lib/api"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Card, CardContent } from "@/components/ui/card"

/** Polls a background job; invalidates cached data when it finishes. */
export function useJob<T>(id: string | null) {
  const qc = useQueryClient()
  const q = useQuery<Job<T>>({
    queryKey: ["job", id],
    queryFn: () => api.get<Job<T>>(`/api/jobs/${id}`),
    enabled: !!id,
    refetchInterval: (query) => {
      const s = query.state.data?.status
      return s === "done" || s === "error" ? false : 1000
    },
  })
  const status = q.data?.status
  useEffect(() => {
    if (status === "done") qc.invalidateQueries({ predicate: (x) => x.queryKey[0] !== "job" })
  }, [status, qc])
  return q
}

export function JobProgress({ job, error }: { job: Job | undefined; error?: unknown }) {
  const [now, setNow] = useState(() => Date.now())
  const running = job && (job.status === "running" || job.status === "queued")
  useEffect(() => {
    if (!running) return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [running])
  if (error)
    return (
      <Alert variant="destructive">
        <XCircle />
        <AlertTitle>Zadanie niedostępne</AlertTitle>
        <AlertDescription>{error instanceof Error ? error.message : String(error)} (serwer mógł zostać zrestartowany).</AlertDescription>
      </Alert>
    )
  if (!job) return null
  const secs = Math.round(((job.finished ? job.finished * 1000 : now) - job.started * 1000) / 1000)
  if (job.status === "error")
    return (
      <Alert variant="destructive">
        <XCircle />
        <AlertTitle>{job.label} — błąd</AlertTitle>
        <AlertDescription className="break-words">{job.error}</AlertDescription>
      </Alert>
    )
  return (
    <Card size="sm">
      <CardContent className="space-y-2">
        <div className="flex items-center gap-2 text-sm font-medium">
          {job.status === "done" ? <CheckCircle2 className="size-4 text-[var(--status-good)]" /> : <Loader2 className="size-4 animate-spin" />}
          <span className="min-w-0 truncate" title={job.label}>{job.label}</span>
          <span className="ml-auto shrink-0 text-xs font-normal text-muted-foreground tabular">
            {job.status === "done" ? `gotowe w ${secs} s` : job.status === "queued" ? "w kolejce…" : `${secs} s`}
          </span>
        </div>
        {job.status !== "done" && job.progress.length > 0 && (
          <ul className="max-h-40 space-y-0.5 overflow-y-auto font-mono text-xs text-muted-foreground">
            {job.progress.slice(-8).map((p, i) => (
              <li key={i} className="truncate">{p}</li>
            ))}
          </ul>
        )}
        {job.status === "running" && job.kind === "analyse" && (
          <p className="text-xs text-muted-foreground">
            {job.meta?.mode === "text"
              ? "Analiza tekstu trwa zwykle kilka sekund (dłużej przy pierwszym uruchomieniu i z modelem językowym)."
              : "Ekstrakcja (OCR, twarze, embeddingi obrazu i tekstu, model językowy) trwa zwykle 0,5–3 min na materiał na CPU."}
          </p>
        )}
      </CardContent>
    </Card>
  )
}
