import { Grid2x2, List, Search } from "lucide-react"
import { useMemo, useState } from "react"
import { Link, useNavigate } from "react-router"

import type { MaterialSummary } from "@/lib/api"
import { matLabel, plural, useApi } from "@/lib/format"
import { CampaignBadge, ErrorState, Loading, PageHeader, Thumb } from "@/components/common"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"

type FeatureFilter = "all" | "web" | "faces" | "ocr" | "ids"

export default function MaterialsPage() {
  const { data, error, isLoading } = useApi<MaterialSummary[]>("/api/materials")
  const [q, setQ] = useState("")
  const [camp, setCamp] = useState("all")
  const [feat, setFeat] = useState<FeatureFilter>("all")
  const [view, setView] = useState<"cards" | "table">("cards")
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
      if (feat === "web" && !m.signals?.has_web) return false
      if (feat === "faces" && !m.signals?.has_faces) return false
      if (feat === "ocr" && !m.signals?.has_ocr) return false
      if (feat === "ids" && !(m.signals?.n_linking_indicators ?? 0)) return false
      if (!qq) return true
      return [m.name, m.display_name, m.title, m.product, m.scam_type_label, ...m.domains, ...m.persons].some((v) => v?.toLowerCase().includes(qq))
    })
  }, [data, q, camp, feat])

  if (isLoading) return <Loading />
  if (error || !data) return <ErrorState error={error} />

  return (
    <>
      <PageHeader
        title="Materiały"
        description="Materiał to jedno zgłoszenie: reklama razem ze stroną docelową, zrzutami ekranu i nagraniami. Otwórz materiał, aby zobaczyć wyciągnięte z niego ślady i poszukać podobnych."
        actions={
          <ToggleGroup type="single" variant="outline" aria-label="Układ listy" value={view} onValueChange={(v) => v && setView(v as "cards" | "table")}>
            <ToggleGroupItem value="cards" className="gap-1.5 px-3"><Grid2x2 className="size-4" /> Karty</ToggleGroupItem>
            <ToggleGroupItem value="table" className="gap-1.5 px-3"><List className="size-4" /> Tabela</ToggleGroupItem>
          </ToggleGroup>
        }
      />

      <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
        <div className="relative min-w-60 flex-1 sm:max-w-xs">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            aria-label="Filtruj materiały"
            placeholder="Filtruj: numer, domena, osoba, produkt…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="pl-9"
          />
        </div>
        <Select value={camp} onValueChange={setCamp}>
          <SelectTrigger className="w-64" aria-label="Kampania"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Wszystkie kampanie ({campaigns.length})</SelectItem>
            {campaigns.map((c) => (
              <SelectItem key={c.id} value={String(c.id)}>{c.code} · {c.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="flex flex-wrap items-center gap-2.5">
          <span id="feat-filter" className="text-sm text-muted-foreground">Tylko materiały, które mają:</span>
          <ToggleGroup
            type="single"
            variant="outline"
            size="sm"
            aria-labelledby="feat-filter"
            value={feat === "all" ? "" : feat}
            onValueChange={(v) => setFeat((v || "all") as FeatureFilter)}
            className="flex-wrap"
          >
            <ToggleGroupItem value="web" className="px-3">zapis strony</ToggleGroupItem>
            <ToggleGroupItem value="faces" className="px-3">rozpoznane twarze</ToggleGroupItem>
            <ToggleGroupItem value="ocr" className="px-3">tekst z obrazu</ToggleGroupItem>
            <ToggleGroupItem value="ids" className="px-3">identyfikatory</ToggleGroupItem>
          </ToggleGroup>
        </div>
        <span className="ml-auto text-sm text-muted-foreground tabular">
          {rows.length === data.length ? plural(data.length, "materiał", "materiały", "materiałów") : `${rows.length} z ${data.length} materiałów`}
        </span>
      </div>

      {!rows.length ? (
        <p className="rounded-xl border border-dashed px-5 py-10 text-center text-sm text-muted-foreground">
          Żaden materiał nie pasuje do wybranych filtrów.{" "}
          <button type="button" className="underline" onClick={() => { setQ(""); setCamp("all"); setFeat("all") }}>Wyczyść filtry</button>
        </p>
      ) : view === "cards" ? (
        <ul className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {rows.map((m) => <AdCard key={m.id} m={m} />)}
        </ul>
      ) : (
        <Card className="overflow-hidden py-0">
          <div className="w-full overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-4">Materiał</TableHead>
                  <TableHead>Kampania</TableHead>
                  <TableHead>Rodzaj oszustwa</TableHead>
                  <TableHead>Domena docelowa</TableHead>
                  <TableHead>Osoby</TableHead>
                  <TableHead>Dostępne dane</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((m) => {
                  const lbl = matLabel(m)
                  return (
                    <TableRow
                      key={m.id}
                      className="cursor-pointer"
                      onClick={(e) => { if (!(e.target as HTMLElement).closest("a")) navigate(`/materials/${m.id}`) }}
                    >
                      <TableCell className="max-w-80 pl-4">
                        <Link to={`/materials/${m.id}`} className="flex min-w-0 items-center gap-3 hover:underline">
                          <Thumb src={m.thumb} alt="" className="size-12 shrink-0 ring-1 ring-border" />
                          <span className="min-w-0">
                            <span className="block truncate font-medium" title={m.name}>Materiał {lbl}</span>
                            <span className="block truncate text-xs text-muted-foreground">{m.title || "—"}</span>
                          </span>
                        </Link>
                      </TableCell>
                      <TableCell><CampaignBadge c={m.campaign} /></TableCell>
                      <TableCell className="max-w-44 whitespace-normal text-sm">{m.scam_type_label ?? "—"}</TableCell>
                      <TableCell className="max-w-48 truncate font-mono text-xs" title={m.domains.join(", ")}>
                        {m.domains[0] ?? "—"}{m.domains.length > 1 && <span className="text-muted-foreground"> +{m.domains.length - 1}</span>}
                      </TableCell>
                      <TableCell className="max-w-48 truncate text-sm">{m.persons.slice(0, 2).join(", ") || "—"}</TableCell>
                      <TableCell className="text-xs whitespace-normal text-muted-foreground">
                        <DataFacts m={m} />
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </div>
        </Card>
      )}
    </>
  )
}

/** Which data layers the material has, in words: these decide what it can be compared on. */
function DataFacts({ m }: { m: MaterialSummary }) {
  const s = m.signals
  if (!s) return null
  const facts = [
    s.has_web ? "zapis strony" : null,
    s.has_ocr ? "tekst z obrazu" : null,
    s.has_faces ? plural(s.n_faces, "twarz", "twarze", "twarzy") : null,
    s.n_linking_indicators > 0 ? plural(s.n_linking_indicators, "identyfikator", "identyfikatory", "identyfikatorów") : null,
  ].filter(Boolean) as string[]
  // non-breaking spaces keep "15 identyfikatorów" on one line
  return <>{facts.length ? facts.map((x) => x.replace(/ /g, "\u00a0")).join(" · ") : "sama kreacja, bez dodatkowych danych"}</>
}

function AdCard({ m }: { m: MaterialSummary }) {
  const lbl = matLabel(m)
  return (
    <li>
      <Link to={`/materials/${m.id}`} className="group flex h-full flex-col overflow-hidden rounded-xl bg-card ring-1 ring-foreground/10 transition-shadow hover:ring-foreground/30">
        <div className="h-40 w-full overflow-hidden border-b bg-muted">
          {m.thumb ? (
            <img src={m.thumb} alt={`Materiał ${lbl}`} loading="lazy" className="h-full w-full object-cover object-top" />
          ) : (
            <div className="flex h-full w-full items-center justify-center text-sm text-muted-foreground">brak obrazu</div>
          )}
        </div>
        <div className="flex flex-1 flex-col gap-1.5 p-4">
          <div className="flex items-baseline justify-between gap-2">
            <span className="min-w-0 truncate font-medium group-hover:underline" title={m.name}>Materiał {lbl}</span>
            <CampaignBadge c={m.campaign} link={false} />
          </div>
          {m.scam_type_label && <p className="text-xs text-muted-foreground">{m.scam_type_label}</p>}
          <p className="line-clamp-2 text-sm">{m.title || m.product || "bez tytułu"}</p>
          {m.domains[0] && (
            <p className="truncate font-mono text-xs text-muted-foreground" title={m.domains.join(", ")}>
              {m.domains[0]}{m.domains.length > 1 ? ` i ${m.domains.length - 1} więcej` : ""}
            </p>
          )}
          {m.persons.length > 0 && <p className="truncate text-xs text-muted-foreground">Osoby: {m.persons.slice(0, 3).join(", ")}</p>}
          <p className="mt-auto border-t pt-2 text-xs text-muted-foreground"><DataFacts m={m} /></p>
        </div>
      </Link>
    </li>
  )
}
