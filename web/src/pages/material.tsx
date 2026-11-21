import { AlertTriangle, ArrowRight, Check, ChevronDown, Minus, Network, Search } from "lucide-react"
import { useState } from "react"
import { Link, useParams, useSearchParams } from "react-router"

import type { Features, LinkBrief, MaterialDetail, MaterialSeed, MaterialSeedsResponse, ScanItem } from "@/lib/api"
import { FAMILY_CUT, fmtP, matLabel, plural, useApi } from "@/lib/format"
import {
  CampaignBadge, Chips, ErrorState, GroupBadge, HelpTip, KV, Loading, MaterialRow, PageHeader, PageTab, PageTabsList, ReadingNote, RelationBadge,
  Section, Strength, StrengthLegend, traceHref,
} from "@/components/common"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tabs, TabsContent } from "@/components/ui/tabs"

const KIND_PL: Record<string, string> = {
  screenshot: "zrzut ekranu",
  keyframe: "klatka wideo",
  ui_screenshot: "zrzut interfejsu platformy",
  creative: "kreacja",
  capture: "przechwycenie",
}

export default function MaterialPage() {
  const { id } = useParams()
  const { data: m, error, isLoading } = useApi<MaterialDetail>(`/api/materials/${id}`)
  const [imgIdx, setImgIdx] = useState(0)

  if (isLoading) return <Loading />
  if (error || !m) return <ErrorState error={error} />
  const f = m.features
  const lbl = matLabel(m)
  const gallery = f.images.filter((im) => im.url)
  const activeImg = gallery[Math.min(imgIdx, Math.max(0, gallery.length - 1))]
  const contents = [
    m.inputs.pages.length > 0 && plural(m.inputs.pages.length, "zapis strony", "zapisy strony", "zapisów strony"),
    m.inputs.images > 0 && plural(m.inputs.images, "zrzut ekranu", "zrzuty ekranu", "zrzutów ekranu"),
    m.inputs.videos > 0 && plural(m.inputs.videos, "wideo", "wideo", "wideo"),
    m.inputs.assets > 0 && plural(m.inputs.assets, "plik strony", "pliki strony", "plików strony"),
  ].filter(Boolean)

  const coverage = [
    { label: "zapis strony docelowej", ok: f.web.has_web },
    { label: "obrazy kreacji", ok: f.images.length > 0 },
    { label: "tekst odczytany z obrazu (OCR)", ok: f.images.some((i) => i.ocr.trim().length > 0) },
    { label: "rozpoznane twarze", ok: f.persons.faces.length > 0 },
    { label: "identyfikatory techniczne", ok: f.indicators.some((g) => g.linking) },
    { label: "dane o domenach", ok: f.web.infra.length > 0 },
    { label: "opis z modelu językowego", ok: f.llm_backend !== "rules" && f.llm_backend !== "none" && f.llm.length > 0 },
  ]

  return (
    <>
      <PageHeader
        docTitle={`Materiał ${lbl}`}
        title={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <span>Materiał {lbl}</span>
            {m.campaign && (
              <span className="text-base font-normal tracking-normal">
                <CampaignBadge c={m.campaign} withName />
              </span>
            )}
          </span>
        }
        description={f.text.titles[0] ?? m.title}
        actions={
          <>
            {m.campaign && (
              <Button asChild variant="outline">
                <Link to={`/campaigns/${m.campaign.id}`}>Otwórz kampanię {m.campaign.code}</Link>
              </Button>
            )}
            {m.campaign && (
              <Button asChild variant="outline">
                <Link to={`/relations?tab=graph&focus=${m.campaign.id}`}><Network /> Pokaż w grafie</Link>
              </Button>
            )}
          </>
        }
      />

      <div className="grid items-start gap-6 xl:grid-cols-[1fr_1.35fr]">
        <Section
          title="Podgląd"
          description={gallery.length
            ? `${plural(gallery.length, "obraz", "obrazy", "obrazów")}${gallery.length > 1 ? " — wybierz miniaturę, aby zmienić podgląd" : ""}. Kliknięcie obrazu otwiera go w pełnym rozmiarze.`
            : "Materiał nie zawiera zrzutu ekranu ani klatki wideo."}
        >
          {activeImg?.url ? (
            <div className="space-y-3">
              <a href={activeImg.url} target="_blank" rel="noreferrer" className="block overflow-hidden rounded-lg border bg-muted">
                <img src={activeImg.url} alt={`Materiał ${lbl}`} className="mx-auto max-h-[380px] w-full object-contain" />
              </a>
              <dl className="space-y-1.5 text-sm">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <dt className="text-muted-foreground">Rodzaj obrazu:</dt>
                  <dd>{KIND_PL[activeImg.kind] ?? activeImg.kind}</dd>
                </div>
                {activeImg.faces.length > 0 && (
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <dt className="text-muted-foreground">Twarze na obrazie:</dt>
                    <dd className="flex flex-wrap gap-1.5">
                      {activeImg.faces.map((fc, j) => (
                        <Badge key={j} variant={fc.identity ? "secondary" : "outline"} title={fc.identity ? "Zgodność z twarzą z bazy referencyjnej" : undefined}>
                          {fc.identity ? `${fc.identity} · zgodność ${Math.round(fc.sim * 100)}%` : "twarz nierozpoznana"}
                        </Badge>
                      ))}
                    </dd>
                  </div>
                )}
                {activeImg.ocr && (
                  <div>
                    <dt className="text-muted-foreground">Tekst odczytany z obrazu (OCR):</dt>
                    <dd className="mt-0.5 text-xs leading-relaxed">{activeImg.ocr}</dd>
                  </div>
                )}
              </dl>
              {gallery.length > 1 && (
                <div className="flex gap-2 overflow-x-auto pt-1">
                  {gallery.map((im, idx) => (
                    <button
                      key={idx}
                      type="button"
                      aria-label={`Pokaż obraz ${idx + 1}`}
                      aria-pressed={idx === imgIdx}
                      onClick={() => setImgIdx(idx)}
                      className={`shrink-0 overflow-hidden rounded-md border-2 ${idx === imgIdx ? "border-foreground" : "border-transparent opacity-70 hover:opacity-100"}`}
                    >
                      <img src={im.url!} alt="" className="size-16 object-cover" />
                    </button>
                  ))}
                </div>
              )}
            </div>
          ) : m.thumb ? (
            <img src={m.thumb} alt={`Materiał ${lbl}`} className="mx-auto max-h-72 rounded-lg border bg-muted object-contain" />
          ) : (
            <div className="flex h-40 items-center justify-center rounded-lg border border-dashed text-sm text-muted-foreground">
              Brak obrazów do pokazania
            </div>
          )}
        </Section>

        <Section title="Podsumowanie">
          {f.summary && <p className="mb-4 max-w-[75ch] leading-relaxed text-pretty">{f.summary}</p>}

          <dl className="divide-y border-t">
            <KV label="Rodzaj oszustwa">{m.scam_type_label ?? "nie rozpoznano"}</KV>
            <KV label="Produkt lub platforma">{m.product ?? "nie rozpoznano"}</KV>
            <KV label="Domeny docelowe"><Chips values={f.web.landing_domains} empty="brak — materiał nie zawiera strony docelowej" /></KV>
            <KV label="Osoby na obrazach" hint="Twarze rozpoznane przez porównanie z bazą referencyjną zdjęć osób publicznych (ArcFace).">
              <Chips values={f.persons.faces} empty="nie rozpoznano" />
            </KV>
            <KV label="Osoby w tekście" hint="Nazwiska wymienione w treści strony albo odczytane z kreacji (OCR).">
              <Chips values={f.persons.named} empty="nie znaleziono" />
            </KV>
            <KV label="Źródło">
              {m.source_label}
              <span className="block truncate font-mono text-xs text-muted-foreground" title={m.source_ref}>{m.source_ref}</span>
            </KV>
            <KV label="Pliki wejściowe">{contents.join(" · ") || "brak"}</KV>
            <KV label="Dostępne dane" hint="Warstwy danych, które udało się wyciągnąć z materiału. Od nich zależy, na czym można go porównać z innymi: materiał bez zapisu strony nie ma np. śladów technicznych.">
              <ul className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
                {coverage.map((c) => (
                  <li key={c.label} className={c.ok ? "flex items-center gap-1.5" : "flex items-center gap-1.5 text-muted-foreground"}>
                    {c.ok ? <Check className="size-3.5 shrink-0" aria-label="jest" /> : <Minus className="size-3.5 shrink-0" aria-label="brak" />}
                    {c.label}
                  </li>
                ))}
              </ul>
            </KV>
          </dl>

          {f.notes.length > 0 && (
            <Alert className="mt-4">
              <AlertTriangle />
              <AlertTitle>Niekompletne dane wejściowe</AlertTitle>
              <AlertDescription>{f.notes.join("; ")}</AlertDescription>
            </Alert>
          )}
        </Section>
      </div>

      <div className="space-y-4">
        <h2 className="text-lg font-medium">Ślady i powiązania tego materiału</h2>
        <FeatureTabs f={f} similarSlot={<SimilarList me={m.id} links={m.links} />} />
      </div>

      <FurtherSearchPanel materialId={m.id} campaign={m.campaign} ocrLinks={f.ocr_links} />
    </>
  )
}

/** Inline "Conduct Further Search" panel right inside the Ad Inspector. */
function FurtherSearchPanel({
  materialId,
  campaign,
  ocrLinks,
}: {
  materialId: string
  campaign: MaterialDetail["campaign"]
  ocrLinks: string[]
}) {
  const { data: seedData } = useApi<MaterialSeedsResponse>(`/api/materials/${materialId}/seeds`)
  const [query, setQuery] = useState("")
  const [submitted, setSubmitted] = useState<string | null>(null)
  const { data: res, isFetching, error } = useApi<{ results: ScanItem[]; errors: Record<string, string> }>(
    submitted ? `/api/library-search?q=${encodeURIComponent(submitted)}` : null,
  )

  const runSearch = (q: string) => {
    const clean = q.trim()
    if (clean.length < 2) return
    setQuery(clean)
    setSubmitted(clean)
  }

  const seeds: MaterialSeed[] = seedData?.seeds ?? []
  const target = (r: ScanItem) => r.url || (r.domain ? `https://${r.domain}/` : "")

  return (
    <Card>
      <CardHeader>
        <CardTitle>Szukaj podobnych reklam w publicznych bibliotekach reklam</CardTitle>
        <CardDescription className="max-w-[80ch] text-pretty">
          Wybierz wartość wyciągniętą z tego materiału albo wpisz własne hasło. Zapytanie trafia do bibliotek reklam Microsoft, Google i Meta.
          Wyniki nie są zapisywane w bazie — każdy można potem przeanalizować osobno.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {seeds.length > 0 && (
          <div className="space-y-2">
            <p id="seed-label" className="text-sm text-muted-foreground">Szukaj po wartości z tego materiału:</p>
            <div className="flex flex-wrap gap-2" role="group" aria-labelledby="seed-label">
              {seeds.map((s) => (
                <Button
                  key={`${s.kind}:${s.value}`}
                  type="button"
                  variant={submitted === s.query ? "default" : "outline"}
                  size="sm"
                  className="h-auto py-1.5 font-normal"
                  onClick={() => runSearch(s.query)}
                >
                  <span className="opacity-70">{s.kind_label}:</span>
                  <span className={s.kind === "domain" ? "max-w-48 truncate font-mono text-xs" : "max-w-48 truncate font-medium"}>{s.value}</span>
                </Button>
              ))}
            </div>
          </div>
        )}

        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            runSearch(query)
          }}
        >
          <div className="w-full max-w-md space-y-1.5">
            <Label htmlFor="lib-q">Własne hasło</Label>
            <Input id="lib-q" placeholder="np. domena, nazwa produktu, nazwisko" value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
          <Button type="submit" variant="outline" disabled={isFetching || query.trim().length < 2}>
            <Search /> {isFetching ? "Przeszukuję biblioteki…" : "Szukaj"}
          </Button>
        </form>

        {ocrLinks.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 border-t pt-4 text-sm">
            <span className="text-muted-foreground">Adresy odczytane z obrazu lub kodu QR — kliknij, aby przeanalizować stronę:</span>
            {ocrLinks.map((u) => (
              <Button key={u} asChild variant="outline" size="sm" className="font-mono text-xs">
                <Link to={`/analyse?url=${encodeURIComponent(u.startsWith("http") ? u : `https://${u}/`)}`}>
                  {u} <ArrowRight />
                </Link>
              </Button>
            ))}
          </div>
        )}

        {campaign && (
          <p className="border-t pt-4 text-sm text-muted-foreground">
            Chcesz szukać po wszystkich identyfikatorach kampanii naraz?{" "}
            <Link to={`/campaigns/${campaign.id}?tab=watch`} className="font-medium text-foreground underline">Szukaj nowych materiałów kampanii {campaign.code}</Link>
          </p>
        )}

        {error && <Alert variant="destructive"><AlertDescription>{(error as Error).message}</AlertDescription></Alert>}

        {res && (
          <div className="space-y-2 border-t pt-4">
            <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span className="font-medium">
                Wyniki dla „{submitted}”: {plural(res.results.length, "pozycja", "pozycje", "pozycji")}
              </span>
              {Object.keys(res.errors).length > 0 && (
                <span className="text-xs text-muted-foreground">
                  Źródła, które nie odpowiedziały: {Object.entries(res.errors).map(([k]) => k).join(", ")}
                </span>
              )}
            </div>
            {res.results.length ? (
              <div className="max-h-96 overflow-auto rounded-lg border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-24" title="Ocena podejrzaności pozycji od 0 do 1 — im wyżej, tym więcej sygnałów oszustwa">Ocena 0–1</TableHead>
                      <TableHead>Źródło</TableHead>
                      <TableHead>Pozycja</TableHead>
                      <TableHead>Dlaczego podejrzana</TableHead>
                      <TableHead className="w-36" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {res.results.slice(0, 30).map((r, i) => (
                      <TableRow key={i}>
                        <TableCell className="font-medium tabular">{fmtP(r.score)}</TableCell>
                        <TableCell className="text-xs whitespace-nowrap">{r.source_label ?? r.source}</TableCell>
                        <TableCell className="max-w-sm">
                          <div className="truncate font-medium">{r.title || r.name || r.domain || r.advertiser || "—"}</div>
                          <div className="truncate font-mono text-xs text-muted-foreground">{r.domain || r.url || r.advertiser}</div>
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-wrap gap-1">
                            {r.why.map((w) => <Badge key={w} variant="secondary" className="text-[11px] font-normal">{w}</Badge>)}
                          </div>
                        </TableCell>
                        <TableCell>
                          {target(r) && (
                            <Button asChild size="sm" variant="outline">
                              <Link to={`/analyse?url=${encodeURIComponent(target(r))}`}>Analizuj <ArrowRight className="size-3.5" /></Link>
                            </Button>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">Biblioteki reklam nie zwróciły żadnej pozycji dla hasła „{submitted}”. Spróbuj krótszego hasła albo samej domeny.</p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function SimilarList({ me, links }: { me: string; links: LinkBrief[] }) {
  const [showWeak, setShowWeak] = useState(false)
  const strong = links.filter((l) => l.relation !== "none")
  const weak = links.filter((l) => l.relation === "none")
  const row = (l: LinkBrief) => (
    <li key={l.other!.id} className="space-y-2 py-3.5">
      <MaterialRow
        m={l.other!}
        right={<Button asChild variant="outline" size="sm"><Link to={`/pair/${me}/${l.other!.id}`}>Porównaj parę <ArrowRight /></Link></Button>}
      />
      <div className="flex flex-wrap items-start gap-x-4 gap-y-2 pl-[4.125rem]">
        <Strength p={l.p} distance={l.distance} className="w-56" />
        <RelationBadge relation={l.relation} />
      </div>
      {l.reasons.length > 0 && (
        <p className="pl-[4.125rem] text-xs text-muted-foreground">Najmocniejszy dowód: {l.reasons[0].detail}</p>
      )}
    </li>
  )
  return (
    <Section
      title="Materiały najbliższe temu"
      description="Wszystkie materiały w bazie, z którymi ten ma wspólny identyfikator albo podobną treść — od najbliższego."
      aside={<StrengthLegend />}
    >
      {strong.length ? (
        <ul className="divide-y border-t">{strong.map(row)}</ul>
      ) : (
        <p className="text-sm text-muted-foreground">
          Ten materiał nie jest powiązany z żadnym innym: nie ma wspólnego identyfikatora, a odległość treści do każdego materiału przekracza {FAMILY_CUT}.
        </p>
      )}
      {weak.length > 0 && (
        <div className="mt-3 border-t pt-3">
          <Button variant="ghost" size="sm" className="-ml-2 text-muted-foreground" aria-expanded={showWeak} onClick={() => setShowWeak(!showWeak)}>
            <ChevronDown className={showWeak ? "rotate-180 transition-transform" : "transition-transform"} />
            {showWeak ? "Ukryj" : "Pokaż"} materiały bez powiązania ({weak.length}) — odległość treści d &gt; {FAMILY_CUT}
          </Button>
          {showWeak && <ul className="mt-1 divide-y">{weak.map(row)}</ul>}
        </div>
      )}
    </Section>
  )
}

/** Shared by the material page and the analysis result. */
export function FeatureTabs({ f, similarSlot }: { f: Features; similarSlot?: React.ReactNode }) {
  const [params, setParams] = useSearchParams()
  const nInd = f.indicators.reduce((a, g) => a + g.items.reduce((b, i) => b + i.values.length + i.more, 0), 0)
  const nImg = f.images.length + f.assets.length
  const tabs = [
    { id: "traces", label: "Ślady techniczne", count: nInd, show: true, has: nInd > 0 },
    ...(similarSlot ? [{ id: "similar", label: "Najbliższe materiały", count: undefined, show: true, has: true }] : []),
    { id: "content", label: "Treść i opis", count: undefined, show: true, has: true },
    { id: "infra", label: "Domeny i serwery", count: f.web.landing_domains.length, show: f.web.has_web, has: f.web.has_web },
    { id: "images", label: "Obrazy", count: nImg, show: nImg > 0 || f.ocr_links.length > 0, has: nImg > 0 },
  ].filter((t) => t.show)
  const requested = params.get("tab")
  const tab = tabs.some((t) => t.id === requested) ? requested! : (tabs.find((t) => t.has) ?? tabs[0]).id
  const setTab = (v: string) => setParams((p) => { p.set("tab", v); return p }, { replace: true })

  return (
    <Tabs value={tab} onValueChange={setTab} className="gap-5">
      <PageTabsList label="Ślady i powiązania">
        {tabs.map((t) => <PageTab key={t.id} value={t.id} count={t.count}>{t.label}</PageTab>)}
      </PageTabsList>

      <TabsContent value="traces">
        <Card className="py-0">
          <CardContent className="px-0">
            <div className="space-y-1.5 border-b px-5 py-4">
              <p className="max-w-[85ch] text-sm text-pretty text-muted-foreground">
                Wartości wyciągnięte z kodu strony, zapisu ruchu sieciowego, adresów URL i treści materiału.
              </p>
              <ReadingNote>
                <Badge className="mx-0.5">w 2 z {f.n_corpus} mat.</Badge> = ta sama wartość występuje też w innych materiałach, więc może łączyć je w kampanię.
                „Tylko tutaj” = wartość unikalna dla tego materiału. Ciemna etykieta grupy = identyfikator, który łączy; jasna = ślad tylko opisowy.
                Kliknij wartość, aby zobaczyć wszystkie materiały, które ją zawierają.
              </ReadingNote>
            </div>
            {f.indicators.length ? (
              <div className="divide-y">
                {f.indicators.map((g) => (
                  <section key={g.group} className="px-5 py-4">
                    <h3 className="mb-3 flex flex-wrap items-center gap-2 text-sm font-semibold">
                      <GroupBadge label={g.label} linking={g.linking} /> <HelpTip label={`Co to jest: ${g.label}`}>{g.hint}</HelpTip>
                    </h3>
                    <dl className="space-y-2.5">
                      {g.items.map((it) => (
                        <div key={it.type} className="grid gap-x-4 gap-y-1 sm:grid-cols-[14rem_1fr]">
                          <dt className="text-sm text-muted-foreground">{it.type_label}</dt>
                          <dd className="min-w-0">
                            {it.type === "asset_phash" && it.values.some((v) => v.thumb) ? (
                              <div className="flex flex-wrap gap-2">
                                {it.values.map((v) => (
                                  <Link key={v.value} to={traceHref(it.type, v.value)} className="relative" title={v.df > 1 ? `w ${v.df} z ${f.n_corpus} materiałów` : "tylko w tym materiale"}>
                                    {v.thumb ? <img src={v.thumb} alt="obraz ze strony" loading="lazy" className="size-14 rounded object-cover ring-1 ring-border" /> : <span className="flex size-14 items-center justify-center rounded bg-muted font-mono text-[9px] break-all">{v.display.slice(0, 8)}</span>}
                                    {v.df > 1 && <span className="absolute -top-1.5 -right-1.5 rounded-full bg-primary px-1.5 text-[10px] font-semibold text-primary-foreground">{v.df}</span>}
                                  </Link>
                                ))}
                              </div>
                            ) : (
                              <ul className="space-y-1.5">
                                {it.values.map((v) => (
                                  <li key={v.value} className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-0.5">
                                    <Link to={traceHref(it.type, v.value)} className="min-w-0 font-mono text-xs break-all underline-offset-4 hover:underline">{v.display}</Link>
                                    {v.df > 1 ? <Badge className="shrink-0" title={`Wartość występuje w ${v.df} z ${f.n_corpus} materiałów bazy`}>w {v.df} z {f.n_corpus} mat.</Badge> : <span className="shrink-0 text-xs text-muted-foreground">tylko tutaj</span>}
                                  </li>
                                ))}
                              </ul>
                            )}
                            {it.more > 0 && <p className="mt-1 text-xs text-muted-foreground">+{it.more} więcej</p>}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  </section>
                ))}
              </div>
            ) : (
              <p className="p-5 text-sm text-muted-foreground">Nie znaleziono śladów technicznych. Tak bywa, gdy materiał to sama kreacja bez zapisu strony docelowej — można go wtedy porównać tylko po obrazie i tekście.</p>
            )}
          </CardContent>
        </Card>
      </TabsContent>

      {similarSlot && (
        <TabsContent value="similar">
          {similarSlot}
        </TabsContent>
      )}

      <TabsContent value="content" className="space-y-4">
        <div className="grid gap-5 lg:grid-cols-2">
          <Section title="Tekst i słowa kluczowe">
            <dl className="divide-y">
              <KV label="Tytuły">{f.text.titles.length ? <ul className="space-y-1">{f.text.titles.map((t) => <li key={t}>{t}</li>)}</ul> : "—"}</KV>
              <KV label="Słowa kluczowe" hint="Wyrazy i frazy najbardziej charakterystyczne dla tego tekstu, wyznaczone automatycznie (algorytm YAKE)."><Chips values={f.text.keywords} /></KV>
              <KV label="Kwoty"><Chips values={f.text.amounts} /></KV>
              <KV label="Marki"><Chips values={f.text.brands} /></KV>
              <KV label="Media"><Chips values={f.text.media} /></KV>
            </dl>
            {f.text.excerpt && (
              <details className="mt-4 text-sm">
                <summary className="cursor-pointer font-medium text-muted-foreground hover:text-foreground">Pokaż fragment treści ({f.text.n_chars.toLocaleString("pl-PL")} znaków łącznie)</summary>
                <p className="mt-2 rounded-md bg-muted p-3.5 text-xs leading-relaxed whitespace-pre-wrap">{f.text.excerpt}</p>
              </details>
            )}
          </Section>
          <Section
            title={<span className="flex items-center gap-1.5">Opis materiału <HelpTip label="Skąd pochodzi opis">Model językowy (albo reguły słownikowe, gdy model jest wyłączony) rozpoznaje rodzaj oszustwa, produkt, osoby, marki i media. Tylko nazwa produktu jest identyfikatorem łączącym materiały; pozostałe pola służą analitykowi do oceny.</HelpTip></span>}
            description={f.llm_backend_label ? `Źródło: ${f.llm_backend_label}` : undefined}
          >
            {f.llm_backend === "rules" && (
              <p className="mb-2 text-xs text-muted-foreground">Model językowy był wyłączony. Opis pochodzi z reguł słownikowych, które są mniej dokładne i nie rozpoznają nazw produktów.</p>
            )}
            <dl className="divide-y">
              {f.llm.map((r) => (
                <KV key={r.key} label={r.label}>
                  {Array.isArray(r.value) ? <Chips values={r.value} max={8} /> : r.value}
                </KV>
              ))}
              {!f.llm.length && <p className="py-2 text-sm text-muted-foreground">Z tego materiału nie udało się wyciągnąć opisu.</p>}
            </dl>
          </Section>
        </div>
      </TabsContent>

      {f.web.has_web && (
        <TabsContent value="infra" className="space-y-4">
          <Section title="Domeny docelowe" description="Publicznie dostępne dane o każdej domenie: rejestracja (RDAP), serwery nazw (DNS), pierwszy certyfikat (crt.sh) i obecność na liście ostrzeżeń CERT Polska. Świeża data utworzenia i wpis na liście CERT wzmacniają podejrzenie.">
            {f.web.infra.length ? (
              <div className="grid gap-x-10 gap-y-6 md:grid-cols-2">
                {f.web.infra.map((d) => (
                  <div key={d.domain}>
                    <div className="mb-1 flex flex-wrap items-center justify-between gap-2 border-b pb-2">
                      <span className="font-mono text-sm font-medium break-all">{d.domain}</span>
                      {d.cert_pl_listed ? <Badge variant="destructive"><AlertTriangle /> na liście ostrzeżeń CERT Polska</Badge> : <span className="text-xs text-muted-foreground">nie ma jej na liście CERT Polska</span>}
                    </div>
                    <dl className="divide-y">
                      <KV label="Rejestrator">{d.registrar ?? "—"}</KV>
                      <KV label="Utworzona">{d.created?.slice(0, 10) ?? "—"}</KV>
                      <KV label="Serwery NS"><span className="font-mono text-xs break-all">{d.nameservers?.join(", ") ?? "—"}</span></KV>
                      <KV label="Pierwszy certyfikat">{d.first_cert?.slice(0, 10) ?? "—"}</KV>
                    </dl>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">Nie udało się pobrać danych o domenach: sprawdzanie było wyłączone albo domena już nie odpowiada.</p>
            )}
          </Section>
          <Section title="Adresy URL, przekierowania i serwery">
            <dl className="divide-y">
              <KV label="Adresy URL">
                {f.web.landing_urls.length ? (
                  <ul className="space-y-1">{f.web.landing_urls.map((u) => <li key={u} className="font-mono text-xs break-all">{u}</li>)}</ul>
                ) : "—"}
              </KV>
              <KV label="Przekierowania">
                {f.web.redirect_chains.length ? f.web.redirect_chains.map((c, i) => <div key={i} className="font-mono text-xs break-all">{c.join(" → ")}</div>) : "brak"}
              </KV>
              <KV label="IP serwerów"><Chips values={f.web.ips} /></KV>
              <KV label="Nagłówki serwera"><Chips values={f.web.server_headers} /></KV>
              <KV label="Za Cloudflare" hint="Strona schowana za Cloudflare nie ujawnia prawdziwego adresu IP serwera.">{f.web.behind_cloudflare ? "tak" : "nie"}</KV>
            </dl>
          </Section>
        </TabsContent>
      )}

      <TabsContent value="images" className="space-y-4">
        {f.images.length > 0 && (
          <Section title="Kreacje, zrzuty ekranu i klatki wideo" description="Pod każdym obrazem: jego rodzaj, rozpoznane twarze i tekst odczytany z obrazu (OCR).">
            <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
              {f.images.map((im, i) => (
                <figure key={i} className="space-y-2">
                  {im.url ? (
                    <a href={im.url} target="_blank" rel="noreferrer" className="block">
                      <img src={im.url} alt={`Obraz ${i + 1}`} loading="lazy" className="max-h-72 w-full rounded-md border bg-muted object-contain" />
                    </a>
                  ) : (
                    <div className="flex h-36 items-center justify-center rounded-md bg-muted text-xs text-muted-foreground">plik niedostępny</div>
                  )}
                  <figcaption className="space-y-1.5 text-xs">
                    <div className="flex flex-wrap gap-1">
                      <Badge variant="outline">{KIND_PL[im.kind] ?? im.kind}</Badge>
                      {im.faces.map((fc, j) => <Badge key={j} variant={fc.identity ? "secondary" : "outline"}>{fc.identity ?? "twarz nierozpoznana"}</Badge>)}
                    </div>
                    {im.ocr && <p className="line-clamp-4 text-muted-foreground">OCR: {im.ocr}</p>}
                  </figcaption>
                </figure>
              ))}
            </div>
          </Section>
        )}
        {f.assets.length > 0 && (
          <Section
            title="Obrazy ze strony docelowej"
            description={`Pokazano ${f.assets.length} z ${f.n_assets_total} obrazów zapisanej strony. Te obrazy są porównywane między materiałami (odcisk pHash), więc ten sam obraz na dwóch stronach zbliża je do siebie.`}
          >
            <div className="grid grid-cols-3 gap-3 sm:grid-cols-4 lg:grid-cols-6">
              {f.assets.map((a) => (
                <a key={a} href={a} target="_blank" rel="noreferrer">
                  <img src={a} alt="obraz ze strony" loading="lazy" className="aspect-square w-full rounded-md bg-muted object-cover ring-1 ring-border" />
                </a>
              ))}
            </div>
          </Section>
        )}
      </TabsContent>
    </Tabs>
  )
}
