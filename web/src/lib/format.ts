import { useQuery } from "@tanstack/react-query"
import { api } from "./api"

export const P_LINK = 0.55
export const P_SIMILAR = 0.3

export function fmtP(p: number | null | undefined): string {
  if (p === null || p === undefined) return "—"
  if (p >= 0.995) return "0.99+"     // noisy-OR never reaches 1 (API rounds to 3 places); never show certainty
  return p.toFixed(2)
}

export function fmtDate(s: string | null | undefined): string {
  if (!s) return "—"
  const d = new Date(s.replace(" ", "T") + (s.length === 19 ? "Z" : ""))
  if (Number.isNaN(d.getTime())) return s
  return d.toLocaleString("pl-PL", { dateStyle: "medium", timeStyle: "short" })
}

export function seriesColor(slot: number | null | undefined): string {
  return slot === null || slot === undefined ? "var(--series-none)" : `var(--series-${slot + 1})`
}

/** Similarity classes aligned with the decision thresholds (not arbitrary steps). */
export const P_CLASSES = [
  { from: 0, to: 0.05, color: "var(--seq-0)", label: "brak (< 0.05)" },
  { from: 0.05, to: 0.3, color: "var(--seq-100)", label: "słabe (0.05–0.3)" },
  { from: 0.3, to: 0.55, color: "var(--seq-300)", label: "podobny playbook (0.3–0.55)" },
  { from: 0.55, to: 0.8, color: "var(--seq-500)", label: "silne (0.55–0.8)" },
  { from: 0.8, to: 1.01, color: "var(--seq-700)", label: "bardzo silne (≥ 0.8)" },
]
export function seqColor(p: number | null | undefined): string {
  if (p === null || p === undefined) return "transparent"
  return (P_CLASSES.find((c) => p < c.to) ?? P_CLASSES[P_CLASSES.length - 1]).color
}
export function seqInk(p: number | null | undefined): string {
  return p !== null && p !== undefined && p >= 0.55 ? "#ffffff" : "#0b0b0b"
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
