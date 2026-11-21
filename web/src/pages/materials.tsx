import { useMemo, useState } from "react"
import { Link, useNavigate } from "react-router"

import type { MaterialSummary } from "@/lib/api"
import { useApi } from "@/lib/format"
import { CampaignBadge, ErrorState, Loading, PageHeader, Thumb } from "@/components/common"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

export default function MaterialsPage() {
  const { data, error, isLoading } = useApi<MaterialSummary[]>("/api/materials")
  const [q, setQ] = useState("")
  const [camp, setCamp] = useState("all")
  const navigate = useNavigate()
  const campaigns = useMemo(() => {
    const m = new Map<number, NonNullable<MaterialSummary["campaign"]>>()
    for (const x of data ?? []) if (x.campaign) m.set(x.campaign.id, x.campaign)
    return [...m.values()].sort((a, b) => a.id - b.id)
  }, [data])
  const rows = useMemo(() => {
    const qq = q.trim().toLowerCase()
    return (data ?? []).filter((m) => {
      if (camp !== "all" && String(m.campaign?.id) !== camp) return false
      if (!qq) return true
      return [m.name, m.title, m.product, m.scam_type_label, ...m.domains, ...m.persons].some((v) => v?.toLowerCase().includes(qq))
    })
  }, [data, q, camp])

  if (isLoading) return <Loading />
  if (error || !data) return <ErrorState error={error} />
  return (
    <>
      <PageHeader title="Materiały" description="Wszystkie przeanalizowane materiały (reklamy, strony docelowe, nagrania). Kliknij wiersz, by zobaczyć wyciągnięte ślady i najbardziej podobne materiały." />
      <div className="flex flex-wrap gap-2">
        <Input placeholder="Filtruj: nazwa, domena, osoba, produkt…" value={q} onChange={(e) => setQ(e.target.value)} className="max-w-sm" />
        <Select value={camp} onValueChange={setCamp}>
          <SelectTrigger className="w-64"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Wszystkie kampanie</SelectItem>
            {campaigns.map((c) => (
              <SelectItem key={c.id} value={String(c.id)}>{c.code} · {c.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="self-center text-sm text-muted-foreground">{rows.length} z {data.length} {data.length === 1 ? "materiału" : "materiałów"}</span>
      </div>
      <Card className="hidden py-0 md:flex">
        <div className="w-full overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="pl-4">Materiał</TableHead>
                <TableHead>Kampania</TableHead>
                <TableHead>Typ oszustwa</TableHead>
                <TableHead>Domena docelowa</TableHead>
                <TableHead>Osoby</TableHead>
                <TableHead>Źródło</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((m) => (
                <TableRow key={m.id} className="cursor-pointer" onClick={(e) => { if (!(e.target as HTMLElement).closest("a")) navigate(`/materials/${m.id}`) }}>
                  <TableCell className="max-w-96 pl-4">
                    <Link to={`/materials/${m.id}`} className="flex min-w-0 items-center gap-3 hover:underline underline-offset-4">
                      <Thumb src={m.thumb} alt="" className="size-10 shrink-0" />
                      <span className="min-w-0">
                        <span className="block font-medium">Materiał {m.name}</span>
                        <span className="block truncate text-xs text-muted-foreground">{m.title || "—"}</span>
                      </span>
                    </Link>
                  </TableCell>
                  <TableCell><CampaignBadge c={m.campaign} /></TableCell>
                  <TableCell className="whitespace-normal">{m.scam_type_label ?? "—"}</TableCell>
                  <TableCell className="font-mono text-xs">{m.domains[0] ?? "—"}{m.domains.length > 1 && <span className="text-muted-foreground"> +{m.domains.length - 1}</span>}</TableCell>
                  <TableCell className="max-w-56 truncate text-sm">{m.persons.slice(0, 2).join(", ") || "—"}</TableCell>
                  <TableCell className="text-sm text-muted-foreground">{m.source_label}</TableCell>
                </TableRow>
              ))}
              {!rows.length && (
                <TableRow><TableCell colSpan={6} className="py-8 text-center text-muted-foreground">Brak materiałów spełniających filtr.</TableCell></TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </Card>
      <div className="space-y-2 md:hidden">
        {rows.map((m) => (
          <Link key={m.id} to={`/materials/${m.id}`} className="block">
            <Card size="sm" className="transition-colors hover:bg-muted/50">
              <CardContent className="flex gap-3">
                <Thumb src={m.thumb} alt="" className="size-14 shrink-0" />
                <div className="min-w-0 space-y-0.5">
                  <div className="font-medium">Materiał {m.name} {m.campaign && <span className="font-normal text-muted-foreground">· {m.campaign.code}</span>}</div>
                  <p className="line-clamp-2 text-xs text-muted-foreground">{m.title || "—"}</p>
                  <p className="text-xs">{m.scam_type_label ?? "—"}</p>
                </div>
              </CardContent>
            </Card>
          </Link>
        ))}
        {!rows.length && <p className="py-6 text-center text-sm text-muted-foreground">Brak materiałów spełniających filtr.</p>}
      </div>
    </>
  )
}
