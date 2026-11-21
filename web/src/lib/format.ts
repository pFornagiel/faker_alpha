import { useQuery } from "@tanstack/react-query"
import { api, type Evidence, type Explanation } from "./api"

// Cuts mirrored from ftf/config.py (CAMPAIGN_CUT, FAMILY_CUT, DUPLICATE_CUT). Pages that receive `thresholds`
// from the API use those; these defaults only label static hints.
export const CAMPAIGN_CUT = 0.6
export const FAMILY_CUT = 0.93
export const DUPLICATE_CUT = 0.05
/** the same cuts in closeness units p = 1 − D */
export const P_LINK = 0.4
export const P_SIMILAR = 0.07

/** Clean short display label for a material (prevents raw URLs from overflowing cards/tables/axes). */
export function matLabel(m: { name: string; display_name?: string } | null | undefined): string {
  if (!m) return "—"
  return m.display_name || m.name
}

/** closeness p, distance d or a view similarity — all in [0, 1] */
export function fmtP(p: number | null | undefined): string {
  if (p === null || p === undefined) return "—"
  return p.toFixed(2)
}

export function seriesColor(slot: number | null | undefined): string {
  return slot === null || slot === undefined ? "var(--series-none)" : `var(--series-${slot + 1})`
}

/** Closeness classes (p = 1 − D) aligned with the relation cuts, not arbitrary steps. */
export const P_CLASSES = [
  { from: 0, to: P_SIMILAR, color: "var(--seq-0)", label: `brak powiązania (d > ${FAMILY_CUT})` },
  { from: P_SIMILAR, to: P_LINK, color: "var(--seq-200)", label: `podobna treść (d ≤ ${FAMILY_CUT})` },
  { from: P_LINK, to: 0.7, color: "var(--seq-400)", label: `ta sama kampania — treść (d ≤ ${CAMPAIGN_CUT})` },
  { from: 0.7, to: 0.95, color: "var(--seq-500)", label: "bardzo bliska treść (d ≤ 0.3)" },
  { from: 0.95, to: 1.01, color: "var(--seq-700)", label: `wspólny identyfikator (p = 1) lub duplikat (d ≤ ${DUPLICATE_CUT})` },
]
export function seqColor(p: number | null | undefined): string {
  if (p === null || p === undefined) return "transparent"
  return (P_CLASSES.find((c) => p < c.to) ?? P_CLASSES[P_CLASSES.length - 1]).color
}
export function seqInk(p: number | null | undefined): string {
  return p !== null && p !== undefined && p >= 0.7 ? "#ffffff" : "#0b0b0b"
}

export function useApi<T>(url: string | null, opts?: { refetchInterval?: number | false }) {
  return useQuery<T>({
    queryKey: [url],
    queryFn: () => api.get<T>(url as string),
    enabled: !!url,
    refetchInterval: opts?.refetchInterval,
  })
}

export function plural(n: number, one: string, few: string, many: string): string {
  if (n === 1) return `${n} ${one}`
  const d = n % 10
  const t = n % 100
  if (d >= 2 && d <= 4 && !(t >= 12 && t <= 14)) return `${n} ${few}`
  return `${n} ${many}`
}

export interface ViewRow {
  key: string
  label: string
  /** null = the view is missing on at least one side */
  score: number | null
  hint?: string
  thumbs?: string[]
}

/** View rows of a link's `evidence` list (only views available on both sides are listed there). */
export function viewsOf(evidence: Evidence[]): ViewRow[] {
  return evidence.flatMap((e) => (e.kind === "view" ? [{ key: e.key, label: e.label, score: e.score }] : []))
}

export function viewsOfExplanation(e: Explanation): ViewRow[] {
  return e.views.map((v) => ({ key: v.view, label: v.label, score: v.available ? v.score : null, hint: v.hint, thumbs: v.thumbs }))
}
