import { ArrowRight } from "lucide-react"
import { useMemo } from "react"
import { Link, useSearchParams } from "react-router"

import type { LinkBrief, Relation } from "@/lib/api"
import { plural, useApi } from "@/lib/format"
import { CampaignDot, ErrorState, Loading, PageHeader, RelationBadge, Strength, StrengthLegend } from "@/components/common"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"

const REL: { value: Relation; label: string }[] = [
  { value: "same_campaign", label: "Ta sama kampania" },
  { value: "duplicate", label: "Duplikat" },
  { value: "similar", label: "Podobna treść" },
  { value: "none", label: "Brak powiązania" },
]

function PairName({ l }: { l: LinkBrief }) {
  const sameCamp = l.a_info?.campaign?.id === l.b_info?.campaign?.id
  return (
    <div className="space-y-0.5">
      <span className="inline-flex flex-wrap items-center gap-x-1.5">
        <CampaignDot c={l.a_info?.campaign} />
        <Link to={`/materials/${l.a}`} className="font-medium hover:underline">Materiał {l.a_info?.name}</Link>
        <span className="text-muted-foreground">↔</span>
        <CampaignDot c={l.b_info?.campaign} />
        <Link to={`/materials/${l.b}`} className="font-medium hover:underline">Materiał {l.b_info?.name}</Link>
      </span>
      <div className="text-xs text-muted-foreground">
        {sameCamp ? `oba w kampanii ${l.a_info?.campaign?.code}` : `kampanie ${l.a_info?.campaign?.code} i ${l.b_info?.campaign?.code}`}
      </div>
    </div>
  )
}

export default function LinksPage({ embedded = false }: { embedded?: boolean }) {
  const { data, error, isLoading } = useApi<LinkBrief[]>("/api/links")
  const [params, setParams] = useSearchParams()
  const relParam = params.get("rel")
  const rel = useMemo(() => (relParam?.split(",").filter(Boolean) ?? ["same_campaign", "duplicate", "similar"]) as Relation[], [relParam])
  const q = params.get("q") ?? ""
  const setParam = (k: string, v: string) => setParams((p) => { if (v) p.set(k, v); else p.delete(k); return p }, { replace: true })
  const counts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const l of data ?? []) c[l.relation] = (c[l.relation] ?? 0) + 1
    return c
  }, [data])
  const rows = useMemo(() => {
    const qq = q.trim().toLowerCase()
    return (data ?? []).filter((l) => {
      if (!rel.includes(l.relation)) return false
      if (!qq) return true
      return [l.a_info?.name, l.b_info?.name, l.a_info?.campaign?.code, l.b_info?.campaign?.code, ...l.reasons.map((r) => r.detail)]
        .some((v) => v?.toLowerCase().includes(qq))
    })
  }, [data, rel, q])

  if (isLoading) return <Loading />
  if (error || !data) return <ErrorState error={error} />
  return (
    <div className="space-y-4">
      {!embedded && (
        <PageHeader
          title="Pary materiałów"
          description="Każda para materiałów dostaje relację, odległość treści d i bliskość p. „Porównaj parę” otwiera pełne uzasadnienie."
        />
      )}
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
          <div className="flex flex-wrap items-center gap-2.5">
            <span id="rel-filter" className="text-sm text-muted-foreground">Pokaż pary o relacji:</span>
            <ToggleGroup type="multiple" variant="outline" size="sm" aria-labelledby="rel-filter" value={rel} onValueChange={(v) => setParam("rel", v.join(","))} className="flex-wrap">
              {REL.map((r) => (
                <ToggleGroupItem key={r.value} value={r.value} className="px-3">
                  {r.label} <span className="tabular opacity-70">{counts[r.value] ?? 0}</span>
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </div>
          <Input aria-label="Filtruj pary" placeholder="Filtruj: numer materiału, kod kampanii (C1), treść dowodu…" value={q} onChange={(e) => setParam("q", e.target.value)} className="h-8 max-w-sm" />
          <span className="text-sm text-muted-foreground tabular">{plural(rows.length, "para", "pary", "par")} z {data.length}</span>
        </div>
        <StrengthLegend />
        <p className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1.5"><span className="size-2.5 rounded-full" style={{ background: "var(--series-1)" }} /> kolorowa kropka = materiał z kampanii wielomateriałowej (kolor kampanii)</span>
          <span className="inline-flex items-center gap-1.5"><span className="size-2.5 rounded-full ring-1 ring-inset ring-[var(--series-none)]" /> pusta kropka = pojedynczy materiał</span>
        </p>
      </div>

      {/* desktop */}
      <Card className="hidden py-0 md:flex">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="pl-4">Para</TableHead>
              <TableHead className="min-w-56">Bliskość p i odległość treści d</TableHead>
              <TableHead>Relacja pary</TableHead>
              <TableHead>Najmocniejsze dowody</TableHead>
              <TableHead className="pr-4" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((l) => (
              <TableRow key={`${l.a}-${l.b}`}>
                <TableCell className="pl-4 whitespace-nowrap"><PairName l={l} /></TableCell>
                <TableCell><Strength p={l.p} distance={l.distance} /></TableCell>
                <TableCell><RelationBadge relation={l.relation} /></TableCell>
                <TableCell className="w-full max-w-0">
                  <ul className="space-y-0.5 text-sm">
                    {l.reasons.slice(0, 2).map((r, i) => <li key={i} className="line-clamp-2 break-words whitespace-normal" title={r.detail}>{r.detail}</li>)}
                    {!l.reasons.length && <li className="text-muted-foreground">brak wspólnych śladów</li>}
                  </ul>
                </TableCell>
                <TableCell className="pr-4 text-right">
                  <Button asChild variant="ghost" size="sm"><Link to={`/pair/${l.a}/${l.b}`}>Porównaj parę <ArrowRight /></Link></Button>
                </TableCell>
              </TableRow>
            ))}
            {!rows.length && (
              <TableRow><TableCell colSpan={5} className="py-8 text-center text-muted-foreground">Żadna para nie pasuje do wybranych relacji i filtra. Włącz więcej relacji albo wyczyść filtr.</TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </Card>

      {/* mobile */}
      <div className="space-y-2 md:hidden">
        {rows.map((l) => (
          <Card key={`${l.a}-${l.b}`} size="sm">
            <CardContent className="space-y-2">
              <div className="flex items-start justify-between gap-2">
                <PairName l={l} />
                <RelationBadge relation={l.relation} />
              </div>
              <Strength p={l.p} distance={l.distance} />
              <p className="text-sm text-muted-foreground">{l.reasons[0]?.detail ?? "brak wspólnych śladów"}</p>
              <Button asChild variant="outline" size="sm" className="w-full"><Link to={`/pair/${l.a}/${l.b}`}>Porównaj parę <ArrowRight /></Link></Button>
            </CardContent>
          </Card>
        ))}
        {!rows.length && <p className="py-6 text-center text-sm text-muted-foreground">Żadna para nie pasuje do wybranych relacji i filtra.</p>}
      </div>
    </div>
  )
}
