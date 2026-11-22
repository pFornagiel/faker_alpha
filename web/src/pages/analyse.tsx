import { useMutation } from "@tanstack/react-query"
import { ArrowRight, Copy, FileUp, GitMerge, Info, Search, ShieldAlert, Sparkles } from "lucide-react"
import { useEffect, useRef, useState, type ReactNode } from "react"
import { Link, useSearchParams } from "react-router"

import { api, type AnalysisResult, type Decision, type Job } from "@/lib/api"
import { fmtP, matLabel, viewsOfExplanation } from "@/lib/format"
import { CampaignBadge, MaterialRow, PageHeader, RelationBadge, Section, Strength } from "@/components/common"
import { Computation, IdentifierList, ViewBars } from "@/components/evidence"
import { DatasetImport } from "@/components/dataset-import"
import { JobProgress, useJob } from "@/components/job"
import { FeatureSections } from "@/components/features"
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"

type Mode = "url" | "file" | "text"
const MODE_PL: Record<Mode, string> = { url: "adres URL", file: "plik", text: "tekst" }
const ACCEPT = "image/*,video/*,.html,.htm,.mhtml,.har,.zip,.json,.txt"

export default function AnalysePage() {
  const [params, setParams] = useSearchParams()
  const [mode, setMode] = useState<Mode>(params.get("text") ? "text" : "url")
  const [url, setUrl] = useState(params.get("url") ?? "")
  const [text, setText] = useState(params.get("text") ?? "")
  const [file, setFile] = useState<File | null>(null)
  const [keep, setKeep] = useState(true)
  const jobId = params.get("job")
  const job = useJob<AnalysisResult>(jobId)
  const restored = useRef<string | null>(null)

  // reopening a ?job= link restores the inputs that produced the shown result
  useEffect(() => {
    const m = job.data?.meta as { mode?: Mode; source?: string; keep?: boolean } | undefined
    if (!m || !jobId || restored.current === jobId) return
    restored.current = jobId
    if (m.mode) setMode(m.mode)
    if (m.mode === "url") setUrl(m.source ?? "")
    if (m.mode === "text") setText(m.source ?? "")
    if (typeof m.keep === "boolean") setKeep(m.keep)
  }, [job.data, jobId])

  const start = useMutation({
    mutationFn: () => {
      const fd = new FormData()
      fd.set("mode", mode)
      fd.set("url", url)
      fd.set("text", text)
      fd.set("render", "true")
      fd.set("keep", String(keep))
      fd.set("use_llm", "true")
      if (file) fd.set("file", file)
      return api.post<Job>("/api/analyse", fd)
    },
    onSuccess: (j) => {
      restored.current = j.id
      setParams({ job: j.id })
    },
  })
  const busy = start.isPending || job.data?.status === "running" || job.data?.status === "queued"
  const urlOk = /^https?:\/\/\S+\.\S+/.test(url.trim())
  const missing = mode === "url" ? (!url.trim() ? "Wpisz adres URL." : !urlOk ? "Adres musi zaczynać się od http:// lub https://." : "")
    : mode === "file" ? (!file ? "Wybierz plik." : "") : !text.trim() ? "Wpisz tekst." : ""

  return (
    <div className="space-y-6">
      <PageHeader
        title="Analizuj materiał"
        description="Nowa reklama, strona lub nagranie jest porównywane ze wszystkimi materiałami w bazie. Wynik to jedna z czterech decyzji: duplikat, znana kampania, propozycja scalenia dwóch kampanii albo nowy wzorzec — zawsze z dowodami."
      />
      <Card>
        <CardContent className="space-y-5">
          <Tabs value={mode} onValueChange={(v) => setMode(v as Mode)} className="gap-4">
            <TabsList>
              <TabsTrigger value="url">Adres URL</TabsTrigger>
              <TabsTrigger value="file">Plik</TabsTrigger>
              <TabsTrigger value="text">Tekst</TabsTrigger>
            </TabsList>
            <TabsContent value="url" className="space-y-3">
              <div className="space-y-1.5">
                <Label htmlFor="url">Adres reklamy, strony docelowej lub pozycji w bibliotece reklam</Label>
                <Input id="url" type="url" inputMode="url" placeholder="https://…" value={url} onChange={(e) => setUrl(e.target.value)} />
              </div>
            </TabsContent>
            <TabsContent value="file" className="space-y-2">
              <Label htmlFor="file">Zrzut ekranu, wideo, zapisana strona (HTML / MHTML), zapis ruchu (HAR) lub ZIP z folderem przypadku</Label>
              <label htmlFor="file" className="flex cursor-pointer items-center gap-3 rounded-lg border border-dashed p-4 text-sm text-muted-foreground hover:bg-muted/50">
                <FileUp className="size-5" />
                {file ? <span className="text-foreground">{file.name} ({Math.round(file.size / 1024)} KB)</span> : "Kliknij, aby wybrać plik"}
              </label>
              <input id="file" type="file" accept={ACCEPT} className="sr-only" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            </TabsContent>
            <TabsContent value="text" className="space-y-1.5">
              <Label htmlFor="text">Treść reklamy, nazwa produktu lub lista linków</Label>
              <Textarea id="text" rows={4} value={text} onChange={(e) => setText(e.target.value)} placeholder="Wklej treść reklamy lub opis strony…" />
            </TabsContent>
          </Tabs>
          <div className="flex flex-wrap items-center gap-x-6 gap-y-3 border-t pt-4">
            <div className="flex items-center gap-2">
              <Switch id="keep" checked={keep} onCheckedChange={setKeep} />
              <Label htmlFor="keep" className="font-normal">Zapisz materiał w bazie (wyłącz, aby tylko sprawdzić)</Label>
            </div>
            <div className="ml-auto flex items-center gap-3">
              {missing && <span className="text-xs text-muted-foreground">{missing}</span>}
              <Button disabled={!!missing || busy} onClick={() => start.mutate()}>
                <Search /> {busy ? "Analizuję…" : "Analizuj materiał"}
              </Button>
            </div>
          </div>
          {start.error && <Alert variant="destructive"><AlertDescription>{(start.error as Error).message}</AlertDescription></Alert>}
        </CardContent>
      </Card>

      {jobId && <JobProgress job={job.data} error={job.error} />}
      {job.data?.status === "done" && job.data.result && <Result r={job.data.result} />}
      {!jobId && <DatasetImport />}
    </div>
  )
}

const DECISION_ICON: Record<Decision, ReactNode> = {
  known_campaign: <ShieldAlert className="size-5" />,
  merge_proposal: <GitMerge className="size-5" />,
  new_campaign: <Sparkles className="size-5" />,
  duplicate: <Copy className="size-5" />,
}

function Result({ r }: { r: AnalysisResult }) {
  const t = r.thresholds
  const shown = r.links.filter((l) => l.p >= 0.05 || l.relation !== "none").slice(0, 6)
  const anyLinked = shown.some((l) => l.relation !== "none")
  return (
    <>
      <Card>
        <CardContent className="flex flex-wrap items-start gap-4">
          <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-full bg-muted">{DECISION_ICON[r.decision]}</span>
          <div className="min-w-0 flex-1 space-y-1.5">
            <h2 className="flex flex-wrap items-center gap-x-2 text-lg font-medium">
              Decyzja: {r.decision_label}
              {r.campaign && <><span aria-hidden>→</span><CampaignBadge c={r.campaign} withName /></>}
            </h2>
            <p className="max-w-[75ch] text-sm text-pretty">{r.decision_hint}</p>
            <p className="text-xs text-muted-foreground">
              Sprawdzono: {MODE_PL[r.input.mode]} „{r.input.source.slice(0, 80)}{r.input.source.length > 80 ? "…" : ""}” · model językowy {r.input.use_llm ? "włączony" : "wyłączony"} · {r.kept ? "materiał zapisany w bazie" : "materiał nie został zapisany"}
            </p>
            {r.decision === "new_campaign" && r.nearest && (
              <p className="text-sm">
                Najbliższy znany materiał:{" "}
                <Link to={`/materials/${r.nearest.material_id}`} className="font-medium underline underline-offset-4">materiał {r.nearest.material_name}</Link>{" "}
                z <CampaignBadge c={r.nearest} withName /> — odległość treści d = {fmtP(r.nearest.distance)},
                a do przypisania potrzeba d ≤ {t.campaign_cut}.
              </p>
            )}
            {r.similar_family && (
              <p className="text-sm">
                Podobna treść (ta sama rodzina) co <CampaignBadge c={r.similar_family} withName /> — d ≤ {t.family_cut}, ale bez wspólnego identyfikatora.
              </p>
            )}
          </div>
          {r.kept && <Button asChild variant="outline"><Link to={`/materials/${r.material_id}`}>Otwórz w bazie <ArrowRight /></Link></Button>}
        </CardContent>
      </Card>

      {!r.input.use_llm && (
        <Alert>
          <Info />
          <AlertTitle>Model językowy był wyłączony</AlertTitle>
          <AlertDescription>
            Atrybuty opisowe pochodzą z reguł słownikowych, które nie rozpoznają nazw produktów i fikcyjnych platform — identyfikator „produkt” może nie zostać znaleziony.
          </AlertDescription>
        </Alert>
      )}

        <Section title="Najbliższe materiały w bazie" description="Rozwiń wiersz, aby zobaczyć wspólne identyfikatory, podobieństwo w każdym widoku treści i obliczenie.">
          {shown.length ? (
            <>
              {!anyLinked && <p className="mb-2 text-sm text-muted-foreground">Żaden materiał w bazie nie jest powiązany z tym: nie ma wspólnego identyfikatora, a odległość treści wszędzie przekracza {t.family_cut}.</p>}
              <Accordion type="single" collapsible className="w-full">
                {shown.map((l) => (
                  <AccordionItem key={l.other.id} value={l.other.id}>
                    <AccordionTrigger className="hover:no-underline">
                      <div className="grid w-full grid-cols-1 items-center gap-2 pr-2 sm:grid-cols-[1fr_13rem]">
                        <MaterialRow m={l.other} link={false} />
                        <div className="space-y-1">
                          <Strength p={l.p} distance={l.distance} />
                          <RelationBadge relation={l.relation} />
                        </div>
                      </div>
                    </AccordionTrigger>
                    <AccordionContent className="space-y-4">
                      <div className="space-y-2">
                        <p className="text-sm font-medium">Wspólne identyfikatory</p>
                        <IdentifierList e={l.explain} />
                      </div>
                      <div className="space-y-2">
                        <p className="text-sm font-medium">Podobieństwo treści</p>
                        <ViewBars views={viewsOfExplanation(l.explain)} />
                      </div>
                      <Computation e={l.explain} />
                      <Button asChild variant="outline" size="sm"><Link to={`/materials/${l.other.id}`}>Otwórz materiał {matLabel(l.other)} <ArrowRight /></Link></Button>
                    </AccordionContent>
                  </AccordionItem>
                ))}
              </Accordion>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">W bazie nie ma jeszcze materiałów, z którymi można porównać ten.</p>
          )}
        </Section>

      <FeatureSections f={r.features} />
    </>
  )
}
