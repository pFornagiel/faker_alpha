import { ArrowRight, Check, Network } from "lucide-react"
import { Link, useParams } from "react-router"

import type { CampaignDetail, MaterialSummary, MatrixRow } from "@/lib/api"
import { fmtP, P_LINK, plural, useApi } from "@/lib/format"
import {
  CampaignBadge, CampaignDot, Chips, ErrorState, HelpTip, KV, Loading, PageHeader, RelationBadge, Section, Strength, StrengthLegend,
  Thumb, TierBadge, traceHref,
} from "@/components/common"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

export default function CampaignPage() {
  const { id } = useParams()
  const { data: c, error, isLoading } = useApi<CampaignDetail>(`/api/campaigns/${id}`)
  if (isLoading) return <Loading />
  if (error || !c) return <ErrorState error={error} />
  const byId = new Map(c.members.map((m) => [m.id, m]))
  const single = c.size === 1

  return (
    <>
      <PageHeader
        docTitle={`${c.code} · ${c.name}`}
        title={
          <span className="flex min-w-0 items-start gap-2">
            <CampaignDot c={c} className="mt-2.5 size-3.5" />
            <span className="min-w-0">{c.code} · {c.name}</span>
          </span>
        }
        description={
          single
            ? "Kampania jednomateriałowa: materiał nie dzieli śladów operatora z żadnym innym materiałem w bazie, więc tworzy osobną kampanię (nowy wzorzec)."
            : `${plural(c.size, "materiał", "materiały", "materiałów")} połączonych ${c.n_shared} wspólnymi wartościami (${c.n_shared_kinds} rodzajów śladów). Poniżej: jak materiały dołączyły do kampanii, który ślad łączy które materiały i jak silne jest każde powiązanie.`
        }
        actions={
          <Button asChild variant="outline" size="sm">
            <Link to={`/graph?focus=${c.id}`}><Network /> Pokaż w grafie</Link>
          </Button>
        }
      />

      <Card size="sm">
        <CardContent>
          <dl className="grid gap-x-8 md:grid-cols-2">
            <KV label="Typ oszustwa"><Chips values={c.scam_types.map((s) => s.label)} /></KV>
            <KV label="Szablon narracji"><Chips values={c.narratives.map((s) => s.label)} /></KV>
            <KV label="Produkty / platformy"><Chips values={c.products} /></KV>
            <KV label="Domeny docelowe"><Chips values={c.domains} max={6} /></KV>
            <KV label="Wykorzystane osoby"><Chips values={c.persons} max={8} /></KV>
            <KV label="Okres aktywności">{c.date_range.length ? `${c.date_range[0]} → ${c.date_range[1]}` : "brak dat w materiałach"}</KV>
            {!single && c.mean_internal_p !== null && (
              <KV label="Średnia siła powiązań" hint="Średnie p wszystkich par materiałów w kampanii. Niska średnia przy wysokich pojedynczych p oznacza kampanię spiętą przez kilka materiałów-łączników.">
                {fmtP(c.mean_internal_p)} <span className="text-muted-foreground">({plural(c.n_pairs, "para", "pary", "par")})</span>
              </KV>
            )}
          </dl>
        </CardContent>
      </Card>

      {!single && (
        <Section
          title="Jak materiały trafiły do kampanii"
          description="Najsilniejsze powiązania, które razem spinają wszystkie materiały kampanii. Każdy krok podaje rodzaj dowodu i najważniejsze wspólne ślady."
        >
          <ol className="space-y-4">
            {c.chain.map((s, i) => (
              <li key={`${s.a}-${s.b}`} className="grid gap-x-4 gap-y-1.5 md:grid-cols-[1.5rem_11rem_1fr_auto]">
                <span className="hidden size-6 items-center justify-center rounded-full bg-muted text-xs font-medium md:flex">{i + 1}</span>
                <div className="space-y-1">
                  <div className="font-medium">mat. {s.a_name} ↔ mat. {s.b_name}</div>
                  <Strength p={s.p} className="max-w-44" />
                </div>
                <div className="min-w-0 space-y-1 text-sm">
                  <Badge variant={s.basis === "ślad operatora" ? "default" : "secondary"}>{s.basis}</Badge>
                  <ul className="text-muted-foreground">
                    {s.reasons.map((r) => <li key={r} className="break-words">{r}</li>)}
                  </ul>
                </div>
                <Button asChild variant="ghost" size="sm" className="justify-self-start">
                  <Link to={`/pair/${s.a}/${s.b}`}>Dlaczego? <ArrowRight /></Link>
                </Button>
              </li>
            ))}
          </ol>
        </Section>
      )}

      <Section
        title="Materiały w kampanii"
        description={c.variants.length > 1 ? "Pogrupowane w warianty przekazu: ten sam tekst lub ta sama kreacja w obrębie kampanii." : undefined}
      >
        <div className="space-y-4">
          {(c.variants.length ? c.variants : [c.members.map((m) => m.id)]).map((g, gi) => (
            <div key={gi} className="space-y-2">
              {c.variants.length > 1 && (
                <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                  Wariant {String.fromCharCode(65 + gi)} · {g.length === 1 ? "unikalny przekaz" : `ten sam przekaz w ${g.length} materiałach`}
                </p>
              )}
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {g.map((mid) => byId.get(mid)).filter(Boolean).map((m) => <MemberCard key={m!.id} m={m!} />)}
              </div>
            </div>
          ))}
        </div>
      </Section>

      {!single && <EvidenceMatrix c={c} byId={byId} />}

      {!single && (
        <Section
          title="Wszystkie pary materiałów w kampanii"
          description="Para może mieć niskie p, a i tak należeć do kampanii — łączą ją inne materiały (np. A↔B przez wspólny piksel, B↔C przez wspólną domenę)."
          aside={<StrengthLegend />}
        >
          <ul className="divide-y">
            {c.links.map((l) => (
              <li key={`${l.a}-${l.b}`} className="grid items-center gap-x-4 gap-y-1.5 py-2.5 md:grid-cols-[8rem_11rem_1fr_auto]">
                <span className="font-medium">mat. {byId.get(l.a)?.name} ↔ {byId.get(l.b)?.name}</span>
                <Strength p={l.p} />
                <span className="min-w-0 text-sm text-muted-foreground md:truncate" title={l.reasons.map((r) => r.detail).join("\n")}>
                  {l.reasons[0]?.detail ?? "brak bezpośrednich wspólnych śladów"}
                </span>
                <span className="flex items-center gap-2">
                  <RelationBadge relation={l.relation} />
                  <Button asChild variant="ghost" size="sm">
                    <Link to={`/pair/${l.a}/${l.b}`}>Dlaczego? <ArrowRight /></Link>
                  </Button>
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section
        title="Najbliższe materiały spoza kampanii"
        description={`Dlaczego nie zostały dołączone: do kampanii potrzeba p ≥ ${P_LINK} oraz śladu operatora albo kilku niezależnych śladów kit/treść. Wspólna osoba czy typ oszustwa to za mało.`}
        aside={<StrengthLegend />}
      >
        {c.nearest_outside.length ? (
          <ul className="divide-y">
            {c.nearest_outside.map((l) => {
              const insideName = byId.get(l.inside)?.name
              const out = l.a === l.inside ? l.b_info : l.a_info
              return (
                <li key={`${l.a}-${l.b}`} className="grid items-center gap-x-4 gap-y-1.5 py-2.5 md:grid-cols-[12rem_11rem_1fr_auto]">
                  <span className="flex min-w-0 flex-wrap items-center gap-x-2">
                    <span className="font-medium">mat. {insideName} ↔ {out?.name}</span>
                    <CampaignBadge c={l.outside_campaign} />
                  </span>
                  <Strength p={l.p} />
                  <span className="min-w-0 text-sm text-muted-foreground md:truncate" title={l.reasons.map((r) => r.detail).join("\n")}>
                    {l.reasons.map((r) => r.detail).join(" · ") || "brak wspólnych śladów"}
                  </span>
                  <span className="flex items-center gap-2">
                    <RelationBadge relation={l.relation} />
                    <Button asChild variant="ghost" size="sm">
                      <Link to={`/pair/${l.a}/${l.b}`}>Dlaczego? <ArrowRight /></Link>
                    </Button>
                  </span>
                </li>
              )
            })}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">Brak materiałów z jakimkolwiek istotnym podobieństwem (p ≥ 0.15).</p>
        )}
      </Section>

      {c.siblings.length > 0 && (
        <Section
          title={<span className="flex items-center gap-1">Podobny playbook (ta sama rodzina) <HelpTip label="Co to jest rodzina">Rodzina = kampanie połączone wyłącznie narracją, koncepcją, wizualiami lub osobami. To ten sam „przepis na oszustwo”, ale bez dowodu, że stoi za nim ten sam operator — dlatego są to osobne kampanie.</HelpTip></span>}
          description="Kampanie o podobnym schemacie oszustwa, bez wspólnej infrastruktury."
        >
          <div className="flex flex-wrap gap-2">
            {c.siblings.map((s) => (
              <Badge key={s.id} variant="outline" asChild className="h-auto max-w-full px-3 py-1">
                <Link to={`/campaigns/${s.id}`} className="min-w-0">
                  <CampaignDot c={s} /> <span className="truncate">{s.code} · {s.name}</span>
                </Link>
              </Badge>
            ))}
          </div>
        </Section>
      )}
    </>
  )
}

function MemberCard({ m }: { m: MaterialSummary }) {
  return (
    <Link to={`/materials/${m.id}`} className="group flex gap-3 rounded-lg border p-2.5 transition-colors hover:bg-muted/50">
      <Thumb src={m.thumb} alt={`Materiał ${m.name}`} className="h-20 w-16 shrink-0" />
      <div className="min-w-0 space-y-1">
        <div className="font-medium underline-offset-4 group-hover:underline">Materiał {m.name}</div>
        <p className="line-clamp-2 text-xs text-muted-foreground">{m.title || "—"}</p>
        <p className="truncate font-mono text-xs text-muted-foreground">{m.domains[0] ?? m.source_label}</p>
      </div>
    </Link>
  )
}

function TraceValue({ r }: { r: MatrixRow }) {
  const first = r.values[0]
  if (r.type === "asset_phash")
    return (
      <div className="flex flex-wrap gap-1">
        {r.thumbs.slice(0, 6).map((t) => (
          <a key={t} href={t} target="_blank" rel="noreferrer"><img src={t} alt="wspólny obraz" loading="lazy" className="size-9 rounded object-cover ring-1 ring-border" /></a>
        ))}
        {r.values.length > 6 && <span className="self-center text-xs text-muted-foreground">+{r.values.length - 6}</span>}
      </div>
    )
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
      title="Który ślad łączy które materiały"
      description="Każdy wiersz to rodzaj śladu z wartością występującą w co najmniej dwóch materiałach kampanii. Ślady operatora (najmocniejsze) są na górze. Kliknij wartość, by zobaczyć wszystkie materiały, które ją zawierają."
      contentClassName="px-0"
    >
      {/* desktop: matrix */}
      <div className="hidden overflow-x-auto md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-28 pl-4">Siła śladu</TableHead>
              <TableHead>Wspólny ślad</TableHead>
              {c.members.map((m) => (
                <TableHead key={m.id} className="w-14 text-center">
                  <Link to={`/materials/${m.id}`} className="underline-offset-4 hover:underline" title={`Materiał ${m.name}`}>mat. {m.name}</Link>
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {c.matrix.map((r) => (
              <TableRow key={`${r.type}:${r.members.join()}:${r.values[0].value}`}>
                <TableCell className="pl-4"><TierBadge tier={r.tier} /></TableCell>
                <TableCell className="max-w-md space-y-1">
                  <div className="text-xs text-muted-foreground">
                    {r.type_label}{r.values.length > 1 && <span className="font-medium text-foreground"> ×{r.values.length}</span>}
                  </div>
                  <TraceValue r={r} />
                </TableCell>
                {c.members.map((m) => (
                  <TableCell key={m.id} className="text-center">
                    {r.members.includes(m.id) ? <Check className="mx-auto size-4" aria-label="występuje" /> : <span className="text-muted-foreground/40" aria-label="brak">·</span>}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      {/* mobile: list */}
      <ul className="divide-y border-t md:hidden">
        {c.matrix.map((r) => (
          <li key={`${r.type}:${r.members.join()}:${r.values[0].value}`} className="space-y-1.5 px-4 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <TierBadge tier={r.tier} />
              <span className="text-xs text-muted-foreground">{r.type_label}{r.values.length > 1 && ` ×${r.values.length}`}</span>
            </div>
            <TraceValue r={r} />
            <p className="text-xs">w materiałach: <span className="font-medium">{r.members.map((m) => byId.get(m)?.name).join(", ")}</span></p>
          </li>
        ))}
      </ul>
    </Section>
  )
}
