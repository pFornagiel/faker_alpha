import { Search } from "lucide-react"
import { useMemo, useState } from "react"
import { Link } from "react-router"

import type { MaterialSummary } from "@/lib/api"
import { matLabel, plural, useApi } from "@/lib/format"
import { CampaignBadge, ErrorState, Loading, PageHeader } from "@/components/common"
import { Input } from "@/components/ui/input"

export default function MaterialsPage() {
  const { data, error, isLoading } = useApi<MaterialSummary[]>("/api/materials")
  const [q, setQ] = useState("")

  const rows = useMemo(() => {
    const qq = q.trim().toLowerCase()
    if (!qq) return data ?? []
    return (data ?? []).filter((m) =>
      [m.name, m.display_name, m.title, m.product, m.scam_type_label, m.campaign?.code, m.campaign?.name, ...m.domains, ...m.persons]
        .some((v) => v?.toLowerCase().includes(qq)),
    )
  }, [data, q])

  if (isLoading) return <Loading />
  if (error || !data) return <ErrorState error={error} />

  return (
    <>
      <PageHeader
        title="Materiały"
        description="Materiał to jedno zgłoszenie: reklama razem ze stroną docelową, zrzutami ekranu i nagraniami. Otwórz materiał, aby zobaczyć jego cechy i najbliższe materiały."
      />

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="relative w-full sm:max-w-sm">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input aria-label="Szukaj materiałów" placeholder="Numer, kampania, domena, osoba, produkt…" value={q} onChange={(e) => setQ(e.target.value)} className="pl-9" />
        </div>
        <span className="text-sm text-muted-foreground" aria-live="polite">
          {q.trim() ? `${rows.length} z ${data.length}` : plural(data.length, "materiał", "materiały", "materiałów")}
        </span>
      </div>

      {rows.length ? (
        <ul className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {rows.map((m) => <MaterialCard key={m.id} m={m} />)}
        </ul>
      ) : (
        <p className="rounded-xl border border-dashed px-5 py-8 text-center text-sm text-muted-foreground">Nic nie pasuje do „{q}”.</p>
      )}
    </>
  )
}

function MaterialCard({ m }: { m: MaterialSummary }) {
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
          <p className="line-clamp-2 text-sm">{m.product || m.title || "bez tytułu"}</p>
          {m.domains[0] && <p className="mt-auto truncate font-mono text-xs text-muted-foreground" title={m.domains.join(", ")}>{m.domains[0]}</p>}
        </div>
      </Link>
    </li>
  )
}
