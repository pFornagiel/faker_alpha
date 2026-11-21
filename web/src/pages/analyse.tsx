import { useMutation } from "@tanstack/react-query"
import { ArrowRight, Copy, FileUp, GitMerge, Info, Search, ShieldAlert, Sparkles } from "lucide-react"
import { useEffect, useRef, useState, type ReactNode } from "react"
import { Link, useSearchParams } from "react-router"

import { api, type AnalysisResult, type Decision, type Job } from "@/lib/api"
import { fmtP, viewsOfExplanation } from "@/lib/format"
import { CampaignBadge, HelpTip, MaterialRow, PageHeader, RelationBadge, Section, Strength, StrengthLegend } from "@/components/common"
import { Computation, IdentifierList, ViewBars } from "@/components/evidence"
import { JobProgress, useJob } from "@/components/job"
import { FeatureTabs } from "@/pages/material"
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
  const [render, setRender] = useState(true)
  const [useLlm, setUseLlm] = useState(true)
  const [keep, setKeep] = useState(true)
  const jobId = params.get("job")
  const job = useJob<AnalysisResult>(jobId)
  const restored = useRef<string | null>(null)

  // reopening a ?job= link restores the inputs that produced the shown result
  useEffect(() => {
    const m = job.data?.meta as { mode?: Mode; source?: string; use_llm?: boolean; keep?: boolean; render?: boolean } | undefined
    if (!m || !jobId || restored.current === jobId) return
    restored.current = jobId
    if (m.mode) setMode(m.mode)
    if (m.mode === "url") setUrl(m.source ?? "")
    if (m.mode === "text") setText(m.source ?? "")
    if (typeof m.use_llm === "boolean") setUseLlm(m.use_llm)
    if (typeof m.keep === "boolean") setKeep(m.keep)
    if (typeof m.render === "boolean") setRender(m.render)
  }, [job.data, jobId])

  const start = useMutation({
    mutationFn: () => {
      const fd = new FormData()
      fd.set("mode", mode)
      fd.set("url", url)
      fd.set("text", text)
      fd.set("render", String(render))
      fd.set("keep", String(keep))
      fd.set("use_llm", String(useLlm))
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
    <>
      <PageHeader
        title="Analizuj nowy materiał"
        description="Nowa reklama, strona lub nagranie jest porównywane ze wszystkimi materiałami w bazie. Wynik: duplikat, znana kampania, propozycja scalenia dwóch kampanii albo nowy wzorzec — wraz z dowodami."
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
              <div className="flex items-center gap-2">
                <Switch id="render" checked={render} onCheckedChange={setRender} />
                <Label htmlFor="render" className="font-normal">Otwórz w przeglądarce (zapis ruchu sieciowego i zrzut ekranu)</Label>
                <HelpTip label="Jak pobierana jest strona">Strona jest pobierana w 3 profilach (bot, komputer z Polski, aplikacja Facebook na Androidzie). Różna treść dla różnych profili oznacza cloaking — ukrywanie oszustwa przed moderacją.</HelpTip>
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
              <Switch id="llm" checked={useLlm} onCheckedChange={setUseLlm} />
              <Label htmlFor="llm" className="font-normal">Model językowy (LLM)</Label>
              <HelpTip label="Co daje model językowy">Rozpoznaje typ oszustwa, nazwy produktów i platform, podszyte osoby i media. Wolniejsze; bez niego działają tylko reguły słownikowe, które nie rozpoznają nazw produktów.</HelpTip>
            </div>
            <div className="flex items-center gap-2">
              <Switch id="keep" checked={keep} onCheckedChange={setKeep} />
              <Label htmlFor="keep" className="font-normal">Zapisz w bazie po analizie</Label>
              <HelpTip label="Co oznacza zapis">Zapisany materiał staje się częścią bazy i może zmienić kampanie. Wyłącz, aby tylko sprawdzić materiał.</HelpTip>
            </div>
            <div className="ml-auto flex items-center gap-3">
              {missing && <span className="text-xs text-muted-foreground">{missing}</span>}
              <Button disabled={!!missing || busy} onClick={() => start.mutate()}>
                <Search /> {busy ? "Analizuję…" : "Analizuj"}
              </Button>
            </div>
          </div>
          {start.error && <Alert variant="destructive"><AlertDescription>{(start.error as Error).message}</AlertDescription></Alert>}
        </CardContent>
      </Card>

      {jobId && <JobProgress job={job.data} error={job.error} />}
      {job.data?.status === "done" && job.data.result && <Result r={job.data.result} />}
    </>
  )
}

const DECISION_STYLE: Record<Decision, { color: string; icon: ReactNode }> = {
  known_campaign: { color: "var(--status-critical)", icon: <ShieldAlert className="size-5" /> },
  merge_proposal: { color: "var(--status-serious)", icon: <GitMerge className="size-5" /> },
  new_campaign: { color: "#52514e", icon: <Sparkles className="size-5" /> },
  duplicate: { color: "#52514e", icon: <Copy className="size-5" /> },
}

function Result({ r }: { r: AnalysisResult }) {
  const st = DECISION_STYLE[r.decision]
  const t = r.thresholds
  const shown = r.links.filter((l) => l.p >= 0.05 || l.relation !== "none").slice(0, 6)
  const anyLinked = shown.some((l) => l.relation !== "none")
  return (
    <>
      <Card className="border-l-4" style={{ borderLeftColor: st.color }}>
        <CardContent className="flex flex-wrap items-start gap-4">
          <span className="mt-0.5" style={{ color: st.color }}>{st.icon}</span>
          <div className="min-w-0 flex-1 space-y-1.5">
            <p className="text-xs text-muted-foreground">
              Decyzja · wejście: {MODE_PL[r.input.mode]} „{r.input.source.slice(0, 80)}{r.input.source.length > 80 ? "…" : ""}” · model językowy: {r.input.use_llm ? "wł." : "wył."} · {r.kept ? "zapisano w bazie" : "nie zapisano w bazie"}
            </p>
            <p className="flex flex-wrap items-center gap-x-2 text-xl font-semibold">
              {r.decision_label}
              {r.campaign && <><span>→</span><CampaignBadge c={r.campaign} withName /></>}
            </p>
            <p className="text-sm text-muted-foreground">{r.decision_hint}</p>
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

      <div className="grid items-start gap-4 lg:grid-cols-[1fr_1.3fr]">
        <Section
          title="Dopasowanie do kampanii"
          description="Dla każdej kampanii: bliskość 1 − d do jej najbliższego materiału (najbliższy sąsiad). Wspólny identyfikator przypisuje do kampanii niezależnie od treści."
          aside={
            <div className="flex flex-wrap gap-x-4 text-xs text-muted-foreground">
              <span>Progi:</span>
              <span className="inline-flex items-center gap-1.5"><span className="h-3 w-px bg-foreground/50" /> {t.similar} ta sama rodzina (d ≤ {t.family_cut})</span>
              <span className="inline-flex items-center gap-1.5"><span className="h-3 w-px bg-foreground" /> {t.link} przypisanie (d ≤ {t.campaign_cut})</span>
            </div>
          }
        >
          {r.scores.length ? (
            <div className="space-y-3">
              {r.scores.map((s) => (
                <div key={s.id} className="space-y-1">
                  <div className="flex items-center justify-between gap-2 text-sm">
                    <span className="min-w-0"><CampaignBadge c={s} withName /></span>
                    <span className="shrink-0 font-medium tabular">d = {fmtP(s.distance)}</span>
                  </div>
                  <div className="relative h-2.5 rounded-sm bg-muted" aria-hidden>
                    <div className="absolute inset-y-0 left-0 rounded-sm" style={{ width: `${Math.max(1, s.score * 100)}%`, background: s.score >= t.link ? "var(--seq-500)" : "var(--seq-300)" }} />
                    <span className="absolute -top-1 h-4.5 w-px bg-foreground/50" style={{ left: `${t.similar * 100}%` }} />
                    <span className="absolute -top-1 h-4.5 w-px bg-foreground" style={{ left: `${t.link * 100}%` }} />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">Baza jest pusta — brak kampanii do porównania.</p>
          )}
        </Section>

        <Section title="Najbardziej podobne materiały" description="Rozwiń, aby zobaczyć wspólne identyfikatory, podobieństwo w każdym widoku treści i obliczenie." aside={<StrengthLegend />}>
          {shown.length ? (
            <>
              {!anyLinked && <p className="mb-2 text-sm text-muted-foreground">Żaden materiał nie jest powiązany: brak wspólnego identyfikatora i d &gt; {t.family_cut}.</p>}
              <Accordion type="single" collapsible className="w-full">
                {shown.map((l) => (
                  <AccordionItem key={l.other.id} value={l.other.id}>
                    <AccordionTrigger className="hover:no-underline">
                      <div className="grid w-full grid-cols-1 items-center gap-2 pr-2 sm:grid-cols-[1fr_9rem]">
                        <MaterialRow m={l.other} link={false} />
                        <div className="space-y-1">
                          <Strength p={l.p} />
                          <RelationBadge relation={l.relation} plain />
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
                      <Button asChild variant="outline" size="sm"><Link to={`/materials/${l.other.id}`}>Otwórz materiał {l.other.name} <ArrowRight /></Link></Button>
                    </AccordionContent>
                  </AccordionItem>
                ))}
              </Accordion>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Brak podobnych materiałów.</p>
          )}
        </Section>
      </div>

      <div className="space-y-2">
        <h2 className="text-lg font-semibold">Wyciągnięte ślady</h2>
        <FeatureTabs f={r.features} />
      </div>
    </>
  )
}
