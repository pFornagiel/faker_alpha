import { CheckCircle2, CircleDashed, ExternalLink, XCircle } from "lucide-react"
import { Link } from "react-router"

import type { ScanItem, WatchOutcome, WatchSeed } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

export const WATCH_HINT =
  "Ziarna to identyfikatory samej kampanii, które już teraz ją łączą (wartości liczone przy powiązaniach: występują w najwyżej połowie materiałów): domeny, ID reklamodawców Google i nazwy produktów. Domeny ogólne / podszywane media i nazwy prawdziwych marek są pomijane. Znaleziona pozycja to tylko trop — do kampanii trafia dopiero wtedy, gdy zwykła analiza (pobranie → cechy → przypisanie) przypisze ją do tej kampanii."

/** "domena healthlinkq.pro kampanii C1" (+ source that returned the hit). */
export function SeedText({ seed, withSource = false }: { seed: WatchSeed; withSource?: boolean }) {
  return (
    <span className="min-w-0 break-words">
      {seed.group_label} <span className="font-mono text-xs">{seed.value}</span> kampanii{" "}
      <Link to={`/campaigns/${seed.campaign}`} className="font-medium hover:underline" title={seed.campaign_label}>
        {seed.campaign_label.split(" · ")[0]}
      </Link>
      {withSource && seed.source_label && <span className="text-muted-foreground"> · {seed.source_label}</span>}
    </span>
  )
}

export function OutcomeBadge({ outcome }: { outcome?: WatchOutcome }) {
  if (!outcome)
    return (
      <Badge variant="outline" className="font-normal text-muted-foreground" title="Pozycja nie była jeszcze analizowana — to tylko trop.">
        <CircleDashed /> trop, nieprzeanalizowany
      </Badge>
    )
  if (outcome.confirmed)
    return (
      <Badge className="font-normal" title={`Zwykłe przypisanie: ${outcome.decision_label}`}>
        <CheckCircle2 /> potwierdzone: {outcome.campaign_label}
      </Badge>
    )
  return (
    <Badge variant="secondary" className="font-normal" title={outcome.note ?? undefined}>
      <XCircle /> nie potwierdzono ({outcome.decision_label}{outcome.campaign_label ? ` ${outcome.campaign_label}` : ""})
    </Badge>
  )
}

/** Seeds a watch run uses, grouped per campaign. */
export function SeedList({ seeds, showCampaign = true }: { seeds: WatchSeed[]; showCampaign?: boolean }) {
  if (!seeds.length) return <p className="text-sm text-muted-foreground">Brak ziaren: kampania nie ma domeny, ID reklamodawcy ani nazwy produktu, którą można by wyszukać.</p>
  const byCampaign = new Map<string, WatchSeed[]>()
  for (const s of seeds) byCampaign.set(s.campaign_label, [...(byCampaign.get(s.campaign_label) ?? []), s])
  return (
    <ul className="space-y-3 text-sm">
      {[...byCampaign.entries()].map(([label, list]) => (
        <li key={label} className="space-y-1">
          {showCampaign && (
            <Link to={`/campaigns/${list[0].campaign}`} className="font-medium hover:underline">{label}</Link>
          )}
          <ul className="space-y-1">
            {list.map((s) => (
              <li key={`${s.group}-${s.value}`} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <Badge variant="outline" className="font-normal">{s.group_label}</Badge>
                <span className="font-mono text-xs break-all">{s.value}</span>
                <span className="text-xs text-muted-foreground">
                  {s.sources_label?.length ? `→ ${s.sources_label.join(", ")}` : "→ brak pasującego źródła"}
                  {s.cert_stem ? ` (CERT: „${s.cert_stem}”)` : ""}
                  {s.note ? ` · ${s.note}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </li>
      ))}
    </ul>
  )
}

const title = (r: ScanItem) => r.title || r.name || r.domain || r.advertiser || "—"
const target = (r: ScanItem) => r.url || (r.domain ? `https://${r.domain}/` : "")

/** Hits found by campaign seeds: the seed that found each one and the outcome of the normal assignment. */
export function WatchHits({ items, showSeedCampaign = true }: { items: ScanItem[]; showSeedCampaign?: boolean }) {
  return (
    <>
      <div className="hidden overflow-x-auto md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Znalezione przez</TableHead>
              <TableHead>Pozycja</TableHead>
              <TableHead>Weryfikacja</TableHead>
              <TableHead className="w-28" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.slice(0, 200).map((r, i) => (
              <TableRow key={i}>
                <TableCell className="max-w-xs text-sm">
                  {r.seed && (showSeedCampaign ? <SeedText seed={r.seed} withSource /> : (
                    <span>{r.seed.group_label} <span className="font-mono text-xs">{r.seed.value}</span> <span className="text-muted-foreground">· {r.seed.source_label}</span></span>
                  ))}
                </TableCell>
                <TableCell className="max-w-md">
                  <div className="truncate font-medium" title={title(r)}>{title(r)}{r.new === false && <span className="ml-1 text-xs font-normal text-muted-foreground">(znane z wcześniejszego skanu)</span>}</div>
                  <div className="truncate font-mono text-xs text-muted-foreground">{r.domain || r.url || r.advertiser}</div>
                </TableCell>
                <TableCell><OutcomeBadge outcome={r.outcome} /></TableCell>
                <TableCell>
                  {target(r) && (
                    <div className="flex items-center gap-1">
                      <Button asChild variant="ghost" size="sm"><Link to={`/analyse?url=${encodeURIComponent(target(r))}`}>Analizuj</Link></Button>
                      <a href={target(r)} target="_blank" rel="noreferrer noopener" className="text-muted-foreground hover:text-foreground" aria-label="Otwórz źródło w nowej karcie"><ExternalLink className="size-4" /></a>
                    </div>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <ul className="space-y-3 md:hidden">
        {items.slice(0, 100).map((r, i) => (
          <li key={i} className="space-y-1.5 rounded-lg border p-3 text-sm">
            <div className="min-w-0 font-medium break-words">{title(r)}</div>
            <div className="font-mono text-xs break-all text-muted-foreground">{r.domain || r.url || r.advertiser}</div>
            {r.seed && <div className="text-xs">znalezione przez: <SeedText seed={r.seed} withSource /></div>}
            <OutcomeBadge outcome={r.outcome} />
            {target(r) && <Button asChild variant="outline" size="sm" className="w-full"><Link to={`/analyse?url=${encodeURIComponent(target(r))}`}>Analizuj</Link></Button>}
          </li>
        ))}
      </ul>
    </>
  )
}
