import { ArrowRight } from "lucide-react"
import { useMemo } from "react"
import { Link, useSearchParams } from "react-router"

import type { LinkBrief, Relation } from "@/lib/api"
import { useApi } from "@/lib/format"
import { CampaignDot, ErrorState, Loading, PageHeader, RelationBadge, Strength, StrengthLegend } from "@/components/common"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"

const REL: { value: Relation; label: string }[] = [
  { value: "same_campaign", label: "Ta sama kampania" },
  { value: "duplicate", label: "Duplikat" },
  { value: "similar", label: "Podobny playbook" },
  { value: "none", label: "Brak powiązania" },
]

function PairName({ l }: { l: LinkBrief }) {
  const sameCamp = l.a_info?.campaign?.id === l.b_info?.campaign?.id
  return (
    <div className="space-y-0.5">
      <span className="inline-flex flex-wrap items-center gap-x-1.5">
        <CampaignDot c={l.a_info?.campaign} />
        <Link to={`/materials/${l.a}`} className="font-medium underline-offset-4 hover:underline">mat. {l.a_info?.name}</Link>
        <span className="text-muted-foreground">↔</span>
        <CampaignDot c={l.b_info?.campaign} />
        <Link to={`/materials/${l.b}`} className="font-medium underline-offset-4 hover:underline">mat. {l.b_info?.name}</Link>
      </span>
      <div className="text-xs text-muted-foreground">
        {sameCamp ? `obie w ${l.a_info?.campaign?.code}` : `${l.a_info?.campaign?.code} i ${l.b_info?.campaign?.code}`}
      </div>
    </div>
  )
}

export default function LinksPage() {
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
    <>
      <PageHeader
        title="Powiązania (pary materiałów)"
        description="Każda para materiałów dostaje siłę powiązania p (0–1) i relację. To tabelaryczna wersja grafu i macierzy — kliknij „Dlaczego?”, by zobaczyć pełne uzasadnienie pary."
      />
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm text-muted-foreground">Pokaż relacje:</span>
          <ToggleGroup type="multiple" variant="outline" value={rel} onValueChange={(v) => setParam("rel", v.join(","))} className="flex-wrap">
            {REL.map((r) => (
              <ToggleGroupItem key={r.value} value={r.value} className="px-3">
                {r.label} <span className="tabular opacity-70">{counts[r.value] ?? 0}</span>
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Input placeholder="Filtruj: materiał, kampania (C1), dowód…" value={q} onChange={(e) => setParam("q", e.target.value)} className="max-w-xs" />
          <span className="text-sm text-muted-foreground">{rows.length} par</span>
        </div>
        <div className="flex flex-wrap gap-x-6 gap-y-1">
          <StrengthLegend />
          <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
            <span className="size-2.5 rounded-full" style={{ background: "var(--series-1)" }} /> kampania wielomateriałowa
            <span className="ml-2 size-2.5 rounded-full ring-1 ring-inset ring-[var(--series-none)]" /> kampania jednomateriałowa
          </span>
        </div>
      </div>

      {/* desktop */}
      <Card className="hidden py-0 md:flex">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="pl-4">Para</TableHead>
              <TableHead className="w-48">Siła p</TableHead>
              <TableHead>Relacja</TableHead>
              <TableHead>Najmocniejsze dowody</TableHead>
              <TableHead className="w-28" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((l) => (
              <TableRow key={`${l.a}-${l.b}`}>
                <TableCell className="pl-4 whitespace-nowrap"><PairName l={l} /></TableCell>
                <TableCell><Strength p={l.p} /></TableCell>
                <TableCell><RelationBadge relation={l.relation} /></TableCell>
                <TableCell className="max-w-xl">
                  <ul className="space-y-0.5 text-sm">
                    {l.reasons.slice(0, 2).map((r, i) => <li key={i} className="truncate" title={r.detail}>{r.detail}</li>)}
                    {!l.reasons.length && <li className="text-muted-foreground">brak wspólnych śladów</li>}
                  </ul>
                </TableCell>
                <TableCell>
                  <Button asChild variant="ghost" size="sm"><Link to={`/pair/${l.a}/${l.b}`}>Dlaczego? <ArrowRight /></Link></Button>
                </TableCell>
              </TableRow>
            ))}
            {!rows.length && (
              <TableRow><TableCell colSpan={5} className="py-8 text-center text-muted-foreground">Brak par dla wybranych filtrów.</TableCell></TableRow>
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
              <Strength p={l.p} />
              <p className="text-sm text-muted-foreground">{l.reasons[0]?.detail ?? "brak wspólnych śladów"}</p>
              <Button asChild variant="outline" size="sm" className="w-full"><Link to={`/pair/${l.a}/${l.b}`}>Dlaczego? <ArrowRight /></Link></Button>
            </CardContent>
          </Card>
        ))}
        {!rows.length && <p className="py-6 text-center text-sm text-muted-foreground">Brak par dla wybranych filtrów.</p>}
      </div>
    </>
  )
}
