import { AlertTriangle, ArrowRight, ChevronDown, ExternalLink } from "lucide-react"
import { useState } from "react"
import { Link, useParams, useSearchParams } from "react-router"

import type { Features, LinkBrief, MaterialDetail } from "@/lib/api"
import { P_SIMILAR, plural, useApi } from "@/lib/format"
import {
  CampaignBadge, Chips, ErrorState, HelpTip, KV, Loading, MaterialRow, PageHeader, RelationBadge, Section, Strength, StrengthLegend,
  TierBadge, traceHref,
} from "@/components/common"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

export default function MaterialPage() {
  const { id } = useParams()
  const { data: m, error, isLoading } = useApi<MaterialDetail>(`/api/materials/${id}`)
  if (isLoading) return <Loading />
  if (error || !m) return <ErrorState error={error} />
  const f = m.features
  const contents = [
    m.inputs.pages.length > 0 && plural(m.inputs.pages.length, "zapis strony", "zapisy strony", "zapisów strony"),
    m.inputs.images > 0 && plural(m.inputs.images, "zrzut ekranu", "zrzuty ekranu", "zrzutów ekranu"),
    m.inputs.videos > 0 && plural(m.inputs.videos, "wideo", "wideo", "wideo"),
    m.inputs.assets > 0 && plural(m.inputs.assets, "plik zapisanej strony", "pliki zapisanej strony", "plików zapisanej strony"),
  ].filter(Boolean)

  return (
    <>
      <PageHeader
        docTitle={`Materiał ${m.name}`}
        title={<span className="flex flex-wrap items-center gap-x-3 gap-y-1">Materiał {m.name} {m.campaign && <span className="text-base font-normal"><CampaignBadge c={m.campaign} withName /></span>}</span>}
        description={f.text.titles[0] ?? m.title}
      />

      <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
        <Section title="Podsumowanie">
          {f.summary && <p className="mb-3 text-sm leading-relaxed">{f.summary}</p>}
          <dl className="divide-y">
            <KV label="Kampania">{m.campaign ? <CampaignBadge c={m.campaign} withName /> : "—"}</KV>
            <KV label="Typ oszustwa">{m.scam_type_label ?? "—"}</KV>
            <KV label="Produkt / platforma">{m.product ?? "—"}</KV>
            <KV label="Domeny docelowe"><Chips values={f.web.landing_domains} /></KV>
            <KV label="Osoby (twarz)" hint="Rozpoznane na obrazach przez porównanie z bazą referencyjną twarzy osób najczęściej wykorzystywanych w oszustwach.">
              <Chips values={f.persons.faces} />
            </KV>
            <KV label="Osoby (tekst)" hint="Wymienione w treści strony lub w tekście odczytanym z kreacji (OCR).">
              <Chips values={f.persons.named} />
            </KV>
            <KV label="Źródło">
              {m.source_label}
              <span className="block truncate font-mono text-xs text-muted-foreground" title={m.source_ref}>{m.source_ref}</span>
            </KV>
            <KV label="Zawartość">{contents.join(" · ") || "—"}</KV>
          </dl>
          {f.notes.length > 0 && (
            <Alert className="mt-3">
              <AlertTriangle />
              <AlertTitle>Braki danych</AlertTitle>
              <AlertDescription>{f.notes.join("; ")}</AlertDescription>
            </Alert>
          )}
        </Section>

        <SimilarList me={m.id} links={m.links} />
      </div>

      <FeatureTabs f={f} />
    </>
  )
}

function SimilarList({ me, links }: { me: string; links: LinkBrief[] }) {
  const [showWeak, setShowWeak] = useState(false)
  const strong = links.filter((l) => l.p >= P_SIMILAR)
  const weak = links.filter((l) => l.p < P_SIMILAR)
  const row = (l: LinkBrief) => (
    <li key={l.other!.id} className="space-y-1.5">
      <MaterialRow
        m={l.other!}
        right={<Button asChild variant="ghost" size="sm"><Link to={`/pair/${me}/${l.other!.id}`}>Dlaczego? <ArrowRight /></Link></Button>}
      />
      <div className="flex items-center gap-2 pl-14">
        <Strength p={l.p} className="max-w-56 flex-1" />
        <RelationBadge relation={l.relation} />
      </div>
    </li>
  )
  return (
    <Section title="Najbardziej podobne materiały" description="Posortowane według siły powiązania p (0–1)." aside={<StrengthLegend />}>
      {strong.length ? <ul className="space-y-3">{strong.map(row)}</ul> : <p className="text-sm text-muted-foreground">Żaden materiał nie przekracza progu {P_SIMILAR} — brak istotnych powiązań.</p>}
      {weak.length > 0 && (
        <div className="mt-3">
          <Button variant="ghost" size="sm" className="-ml-2 text-muted-foreground" onClick={() => setShowWeak(!showWeak)}>
            <ChevronDown className={showWeak ? "rotate-180 transition-transform" : "transition-transform"} />
            {showWeak ? "Ukryj" : "Pokaż"} słabsze ({weak.length}, p &lt; {P_SIMILAR})
          </Button>
          {showWeak && <ul className="mt-2 space-y-3">{weak.map(row)}</ul>}
        </div>
      )}
    </Section>
  )
}

const KIND_PL: Record<string, string> = {
  screenshot: "zrzut ekranu",
  keyframe: "klatka wideo",
  ui_screenshot: "zrzut interfejsu platformy",
  creative: "kreacja",
  capture: "przechwycenie",
}

/** Shared by the material page and the analysis result. */
export function FeatureTabs({ f }: { f: Features }) {
  const [params, setParams] = useSearchParams()
  const nInd = f.indicators.reduce((a, g) => a + g.items.reduce((b, i) => b + i.values.length + i.more, 0), 0)
  const nImg = f.images.length + f.assets.length
  const tabs = [
    { id: "traces", label: `Ślady techniczne (${nInd})`, show: true, has: nInd > 0 },
    { id: "infra", label: `Infrastruktura (${f.web.landing_domains.length})`, show: f.web.has_web, has: f.web.has_web },
    { id: "content", label: "Treść i atrybuty", show: true, has: true },
    { id: "images", label: `Obrazy (${nImg})`, show: nImg > 0 || f.ocr_links.length > 0, has: nImg > 0 },
  ].filter((t) => t.show)
  const requested = params.get("tab")
  const tab = tabs.some((t) => t.id === requested) ? requested! : (tabs.find((t) => t.has) ?? tabs[0]).id
  const setTab = (v: string) => setParams((p) => { p.set("tab", v); return p }, { replace: true })

  return (
    <Tabs value={tab} onValueChange={setTab} className="gap-4">
      <TabsList className="h-auto flex-wrap justify-start">
        {tabs.map((t) => <TabsTrigger key={t.id} value={t.id}>{t.label}</TabsTrigger>)}
      </TabsList>

      <TabsContent value="traces">
        <Card className="py-0">
          <CardContent className="px-0">
            <p className="border-b px-4 py-3 text-sm text-muted-foreground">
              Wartości wyciągnięte z kodu strony, ruchu sieciowego (HAR), adresów URL i treści. Odznaka <Badge className="mx-0.5">w 2 z {f.n_corpus} mat.</Badge> oznacza,
              że ta sama wartość występuje też w innych materiałach — to ona je łączy; im rzadsza, tym mocniej. Kliknij wartość, by zobaczyć te materiały.
            </p>
            {f.indicators.length ? (
              <div className="divide-y">
                {f.indicators.map((g) => (
                  <section key={g.family} className="px-4 py-3">
                    <h3 className="mb-2 flex flex-wrap items-center gap-2 text-sm font-medium">
                      {g.label} <TierBadge tier={g.tier} /> <HelpTip label={`Co to jest: ${g.label}`}>{g.hint}</HelpTip>
                    </h3>
                    <dl className="space-y-2">
                      {g.items.map((it) => (
                        <div key={it.type} className="grid gap-x-4 gap-y-1 sm:grid-cols-[13rem_1fr]">
                          <dt className="text-sm text-muted-foreground">{it.type_label}</dt>
                          <dd className="min-w-0">
                            {it.type === "asset_phash" && it.values.some((v) => v.thumb) ? (
                              <div className="flex flex-wrap gap-1.5">
                                {it.values.map((v) => (
                                  <Link key={v.value} to={traceHref(it.type, v.value)} className="relative" title={v.df > 1 ? `w ${v.df} z ${f.n_corpus} materiałów` : "tylko w tym materiale"}>
                                    {v.thumb ? <img src={v.thumb} alt="obraz ze strony" loading="lazy" className="size-12 rounded object-cover ring-1 ring-border" /> : <span className="flex size-12 items-center justify-center rounded bg-muted font-mono text-[9px] break-all">{v.display.slice(0, 8)}</span>}
                                    {v.df > 1 && <span className="absolute -top-1.5 -right-1.5 rounded-full bg-primary px-1 text-[10px] text-primary-foreground">{v.df}</span>}
                                  </Link>
                                ))}
                              </div>
                            ) : (
                              <ul className="space-y-1">
                                {it.values.map((v) => (
                                  <li key={v.value} className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
                                    <Link to={traceHref(it.type, v.value)} className="min-w-0 font-mono text-xs break-all underline-offset-4 hover:underline">{v.display}</Link>
                                    {v.df > 1 ? <Badge className="shrink-0">w {v.df} z {f.n_corpus} mat.</Badge> : <span className="shrink-0 text-xs text-muted-foreground">tylko tutaj</span>}
                                  </li>
                                ))}
                              </ul>
                            )}
                            {it.more > 0 && <p className="text-xs text-muted-foreground">+{it.more} więcej</p>}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  </section>
                ))}
              </div>
            ) : (
              <p className="p-4 text-sm text-muted-foreground">Nie znaleziono śladów technicznych (np. brak zapisu strony docelowej — sama kreacja).</p>
            )}
          </CardContent>
        </Card>
      </TabsContent>

      {f.web.has_web && (
        <TabsContent value="infra" className="space-y-4">
          <Section title="Domeny" description="Rejestracja (RDAP), serwery nazw (DNS), certyfikaty (crt.sh) i obecność na liście ostrzeżeń CERT Polska.">
            {f.web.infra.length ? (
              <div className="grid gap-3 md:grid-cols-2">
                {f.web.infra.map((d) => (
                  <div key={d.domain} className="rounded-lg border p-3">
                    <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
                      <span className="font-mono text-sm break-all">{d.domain}</span>
                      {d.cert_pl_listed ? <Badge variant="destructive">na liście CERT Polska</Badge> : <span className="text-xs text-muted-foreground">brak na liście CERT</span>}
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
              <p className="text-sm text-muted-foreground">Brak metadanych domen (wzbogacanie wyłączone lub domena niedostępna).</p>
            )}
          </Section>
          <Section title="Adresy i serwery">
            <dl className="divide-y">
              <KV label="Adresy URL">
                {f.web.landing_urls.length ? (
                  <ul className="space-y-1">{f.web.landing_urls.map((u) => <li key={u} className="font-mono text-xs break-all">{u}</li>)}</ul>
                ) : "—"}
              </KV>
              <KV label="Przekierowania">
                {f.web.redirect_chains.length ? f.web.redirect_chains.map((c, i) => <div key={i} className="font-mono text-xs break-all">{c.join(" → ")}</div>) : "brak"}
              </KV>
              <KV label="IP serwerów" hint="Z ruchu sieciowego (HAR). Adresy sieci CDN (Cloudflare, Meta, Google…) nie są traktowane jako ślad operatora."><Chips values={f.web.ips} /></KV>
              <KV label="Nagłówki serwera"><Chips values={f.web.server_headers} /></KV>
              <KV label="Za Cloudflare">{f.web.behind_cloudflare ? "tak" : "nie"}</KV>
            </dl>
          </Section>
        </TabsContent>
      )}

      <TabsContent value="content" className="space-y-4">
        <div className="grid gap-4 lg:grid-cols-2">
          <Section title="Tekst">
            <dl className="divide-y">
              <KV label="Tytuły">{f.text.titles.length ? <ul className="space-y-1">{f.text.titles.map((t) => <li key={t}>{t}</li>)}</ul> : "—"}</KV>
              <KV label="Słowa kluczowe" hint="Wyznaczone automatycznie (YAKE) — mogą zawierać elementy menu strony."><Chips values={f.text.keywords} /></KV>
              <KV label="Kwoty"><Chips values={f.text.amounts} /></KV>
              <KV label="Marki"><Chips values={f.text.brands} /></KV>
              <KV label="Media"><Chips values={f.text.media} /></KV>
            </dl>
            {f.text.excerpt && (
              <details className="mt-3 text-sm">
                <summary className="cursor-pointer text-muted-foreground">Fragment treści ({f.text.n_chars.toLocaleString("pl-PL")} znaków łącznie)</summary>
                <p className="mt-2 rounded-md bg-muted p-3 text-xs leading-relaxed whitespace-pre-wrap">{f.text.excerpt}</p>
              </details>
            )}
          </Section>
          <Section
            title={<span className="flex items-center gap-1">Atrybuty opisowe <HelpTip label="Skąd są atrybuty opisowe">Model językowy (albo — gdy wyłączony — reguły słownikowe) czyta treść i zwraca atrybuty z zamkniętych list. Zgodność atrybutów to słaby dowód (rodzina „koncepcja”).</HelpTip></span>}
            description={f.llm_backend_label ? `Źródło: ${f.llm_backend_label}` : undefined}
          >
            {f.llm_backend === "rules" && (
              <p className="mb-2 text-xs text-muted-foreground">Model językowy był wyłączony — atrybuty z reguł słownikowych są mniej dokładne (np. nie rozpoznają nazw produktów).</p>
            )}
            <dl className="divide-y">
              {f.llm.map((r) => (
                <KV key={r.key} label={<>{r.label}{r.discovered && <Badge variant="outline" className="ml-1">odkryty</Badge>}</>}>
                  {Array.isArray(r.value) ? <Chips values={r.value} max={8} /> : r.value}
                </KV>
              ))}
              {!f.llm.length && <p className="py-2 text-sm text-muted-foreground">Brak atrybutów.</p>}
            </dl>
          </Section>
        </div>
      </TabsContent>

      <TabsContent value="images" className="space-y-4">
        {f.images.length > 0 && (
          <Section title="Kreacje, zrzuty ekranu, klatki wideo" description="Tekst odczytany z obrazu (OCR) i twarze rozpoznane na obrazie.">
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {f.images.map((im, i) => (
                <figure key={i} className="space-y-2">
                  {im.url ? (
                    <a href={im.url} target="_blank" rel="noreferrer" className="block">
                      <img src={im.url} alt={`Obraz ${i + 1}`} loading="lazy" className="max-h-72 w-full rounded-md bg-muted object-contain ring-1 ring-border" />
                    </a>
                  ) : (
                    <div className="flex h-32 items-center justify-center rounded-md bg-muted text-xs text-muted-foreground">plik niedostępny</div>
                  )}
                  <figcaption className="space-y-1 text-xs">
                    <div className="flex flex-wrap gap-1">
                      <Badge variant="outline">{KIND_PL[im.kind] ?? im.kind}</Badge>
                      {im.faces.map((fc, j) => <Badge key={j} variant={fc.identity ? "secondary" : "outline"}>{fc.identity ?? "nieznana twarz"}</Badge>)}
                    </div>
                    {im.ocr && <p className="line-clamp-3 text-muted-foreground">OCR: {im.ocr}</p>}
                  </figcaption>
                </figure>
              ))}
            </div>
          </Section>
        )}
        {f.assets.length > 0 && (
          <Section
            title="Obrazy ze strony docelowej"
            description={`Pokazano ${f.assets.length} z ${f.n_assets_total} plików zapisanej strony. Ten sam obraz na dwóch stronach to ślad „wspólne obrazy”.`}
          >
            <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-6">
              {f.assets.map((a) => (
                <a key={a} href={a} target="_blank" rel="noreferrer">
                  <img src={a} alt="obraz ze strony" loading="lazy" className="aspect-square w-full rounded-md bg-muted object-cover ring-1 ring-border" />
                </a>
              ))}
            </div>
          </Section>
        )}
        {f.ocr_links.length > 0 && (
          <Section title="Linki odczytane z kreacji (OCR / QR)" description="Można je przechwycić i przeanalizować jako nowy materiał.">
            <ul className="space-y-1">
              {f.ocr_links.map((u) => (
                <li key={u} className="flex flex-wrap items-center gap-2 font-mono text-xs">
                  {u}
                  <Link to={`/analyse?url=${encodeURIComponent(u.startsWith("http") ? u : `https://${u}/`)}`} className="inline-flex items-center gap-1 font-sans text-foreground underline underline-offset-4">
                    analizuj <ExternalLink className="size-3" />
                  </Link>
                </li>
              ))}
            </ul>
          </Section>
        )}
      </TabsContent>
    </Tabs>
  )
}
