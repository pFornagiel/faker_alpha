import type { ReactNode } from "react"
import { useNavigate } from "react-router"

import type { CampaignViewProfile, DendrogramData, MetricsOverview } from "@/lib/api"
import { fmtP, seriesColor } from "@/lib/format"
import { cn } from "@/lib/utils"

/* Chart conventions (one system for every figure in the panel):
   - marks carry colour, text never does: labels, values and legends use ink tokens
   - plain magnitude bars use one hue (--viz-bar); "rest of the base / no link" is the neutral --viz-neutral
   - every bar prints its value, so nothing is readable only on hover
   - grid and axes are solid hairlines; dashes are reserved for thresholds */

const INK = "#141413"
const INK_MUTED = "#5f5e59"

// ------------------------------------------------------------------ shared pieces
export interface LegendItem {
  label: ReactNode
  color: string
  /** square = filled mark, line = threshold, ring = hollow marker */
  shape?: "square" | "line" | "ring" | "dot"
}

export function ChartLegend({ items, className }: { items: LegendItem[]; className?: string }) {
  return (
    <ul className={cn("flex flex-wrap gap-x-5 gap-y-1.5 text-xs text-muted-foreground", className)}>
      {items.map((it, i) => (
        <li key={i} className="inline-flex items-center gap-1.5">
          {it.shape === "line" ? (
            <span className="w-4 border-t-2 border-dashed" style={{ borderColor: it.color }} />
          ) : it.shape === "ring" ? (
            <span className="size-2.5 rounded-full border-2 bg-card" style={{ borderColor: it.color }} />
          ) : it.shape === "dot" ? (
            <span className="size-2.5 rounded-full" style={{ background: it.color }} />
          ) : (
            <span className="size-2.5 rounded-[2px]" style={{ background: it.color }} />
          )}
          <span>{it.label}</span>
        </li>
      ))}
    </ul>
  )
}

interface BarRow {
  key: string
  label: ReactNode
  /** null = not measured; the row says so instead of drawing a zero */
  value: number | null
  /** printed at the end of the row; defaults to the number */
  display?: ReactNode
  color?: string
  title?: string
}

/**
 * Horizontal bars as a readable list: label · bar · value. Works as its own table view.
 * `head` names the two columns (what a row is, what the number is) so the unit is never implicit.
 */
function BarList({ rows, max, head, ticks, markers, labelWidth = "13rem", valueWidth = "4.5rem" }: {
  rows: BarRow[]
  max: number
  head: [string, string]
  /** axis ticks under the bars, in data units */
  ticks?: { at: number; label: string }[]
  /** thresholds drawn across every bar */
  markers?: { at: number; label: string; strong?: boolean }[]
  labelWidth?: string
  valueWidth?: string
}) {
  const cols = { gridTemplateColumns: `minmax(5rem, min(${labelWidth}, 45%)) minmax(0, 1fr) ${valueWidth}` }
  const pos = (v: number) => `${Math.max(0, Math.min(1, v / (max || 1))) * 100}%`
  return (
    <div role="table" className="text-sm">
      <div role="row" className="grid items-end gap-x-3 pb-2 text-xs text-muted-foreground" style={cols}>
        <span role="columnheader">{head[0]}</span>
        <span role="presentation" className="relative block h-4">
          {markers?.map((m) => (
            <span key={m.label} className="absolute bottom-0 -translate-x-1/2 whitespace-nowrap" style={{ left: pos(m.at) }}>{m.label}</span>
          ))}
        </span>
        <span role="columnheader" className="flex justify-end whitespace-nowrap">{head[1]}</span>
      </div>
      <div role="rowgroup" className="space-y-2.5">
        {rows.map((r) => (
          <div key={r.key} role="row" className="grid items-center gap-x-3" style={cols} title={r.title}>
            <span role="cell" className="min-w-0 leading-snug break-words">{r.label}</span>
            <span role="presentation" className="relative block h-3 border-l border-[var(--axis)]">
              {r.value !== null && r.value > 0 && (
                <span className="absolute inset-y-0 left-0 block min-w-0.5 rounded-r-[4px]" style={{ width: pos(r.value), background: r.color ?? "var(--viz-bar)" }} />
              )}
              {markers?.map((m) => (
                <span key={m.label} className={cn("absolute -inset-y-1 w-px", m.strong ? "bg-foreground/80" : "bg-foreground/45")} style={{ left: pos(m.at) }} />
              ))}
            </span>
            <span role="cell" className={cn("text-right tabular", r.value === null ? "text-xs text-muted-foreground" : "font-medium")}>
              {r.value === null ? "brak danych" : (r.display ?? r.value)}
            </span>
          </div>
        ))}
      </div>
      {ticks && (
        <div aria-hidden className="grid gap-x-3 pt-2 text-[11px] text-muted-foreground tabular" style={cols}>
          <span />
          <span className="relative block h-4 border-t border-[var(--grid)]">
            {ticks.map((t) => (
              <span key={t.at} className={cn("absolute top-1", t.at === 0 ? "" : t.at >= max ? "-translate-x-full" : "-translate-x-1/2")} style={{ left: pos(t.at) }}>{t.label}</span>
            ))}
          </span>
          <span />
        </div>
      )}
    </div>
  )
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>
}

function niceStep(max: number): number {
  const raw = Math.max(1, max) / 3
  const mag = 10 ** Math.floor(Math.log10(raw))
  const n = raw / mag
  return Math.max(1, (n >= 5 ? 5 : n >= 2 ? 2 : 1) * mag)
}

// ------------------------------------------------------------------ 1. distance histogram
/**
 * How far apart every pair of materials is (content distance d), with the cuts drawn at their real position.
 * Dark part of a column = pairs that share an identifier (linked whatever their content), light = the rest.
 */
export function DistanceHistogramChart({ data, campaignCut, familyCut, height = 180 }: {
  data: MetricsOverview["distance_histogram"]
  campaignCut: number
  familyCut: number
  height?: number
}) {
  if (!data.length) return <Empty>W bazie nie ma jeszcze żadnej pary materiałów.</Empty>
  const max = Math.max(1, ...data.map((b) => b.total))
  const step = niceStep(max)
  const yTicks: number[] = []
  for (let v = 0; v <= max; v += step) yTicks.push(v)
  const h = (v: number) => (v / max) * (height - 22)
  const cuts = [
    { at: campaignCut, label: `kampania ≤ ${campaignCut}` },
    { at: familyCut, label: `rodzina ≤ ${familyCut}` },
  ]
  return (
    <figure className="space-y-2">
      <div className="grid grid-cols-[2rem_minmax(0,1fr)] gap-x-2">
        <span />
        <div className="relative h-5 text-[11px] text-foreground">
          {cuts.map((c) => (
            <span key={c.label} className="absolute -translate-x-full pr-1.5 whitespace-nowrap" style={{ left: `${c.at * 100}%` }}>{c.label}</span>
          ))}
        </div>
        <div className="relative text-[11px] text-muted-foreground tabular" style={{ height }}>
          {yTicks.map((v) => (
            <span key={v} className="absolute right-0 translate-y-1/2" style={{ bottom: h(v) }}>{v}</span>
          ))}
        </div>
        <div className="relative border-b border-[var(--axis)]" style={{ height }}>
          {yTicks.slice(1).map((v) => (
            <span key={v} className="absolute inset-x-0 border-t border-[var(--grid)]" style={{ bottom: h(v) }} />
          ))}
          {cuts.map((c) => (
            <span key={c.label} className="absolute -top-5 bottom-0 border-l border-dashed border-foreground/70" style={{ left: `${c.at * 100}%` }} />
          ))}
          {data.map((b) => {
            const rest = b.total - b.must_link
            return (
              <div
                key={b.range}
                className="absolute bottom-0 flex flex-col-reverse items-stretch gap-0.5 px-[3px]"
                style={{ left: `${b.lo * 100}%`, width: `${(b.hi - b.lo) * 100}%` }}
                title={`d ${b.range}: ${b.total} par, w tym ${b.must_link} ze wspólnym identyfikatorem`}
              >
                {b.must_link > 0 && <span className="block rounded-t-[3px]" style={{ height: Math.max(3, h(b.must_link) - 2), background: "var(--seq-700)" }} />}
                {rest > 0 && <span className="block rounded-t-[3px]" style={{ height: Math.max(3, h(rest) - 2), background: "var(--seq-200)" }} />}
                {b.total > 0 && <span className="mb-0.5 self-center px-1 text-[11px] leading-4 font-medium text-foreground tabular">{b.total}</span>}
              </div>
            )
          })}
        </div>
        <span />
        <div className="relative h-5 text-[11px] text-muted-foreground tabular">
          {[0, 0.2, 0.4, 0.6, 0.8, 1].map((v) => (
            <span key={v} className={cn("absolute top-1", v === 0 ? "" : v === 1 ? "-translate-x-full" : "-translate-x-1/2")} style={{ left: `${v * 100}%` }}>{v.toFixed(1)}</span>
          ))}
        </div>
        <span />
        <figcaption className="flex justify-between gap-3 text-xs text-muted-foreground">
          <span>← identyczna treść</span>
          <span className="font-medium text-foreground">odległość treści d</span>
          <span>nic wspólnego →</span>
        </figcaption>
      </div>
    </figure>
  )
}

// ------------------------------------------------------------------ 2. what links the pairs
export function SignalAttributionChart({ data }: { data: MetricsOverview["signal_attribution"] }) {
  if (!data.length) return <Empty>Żadna para nie została jeszcze połączona w kampanię.</Empty>
  const max = Math.max(...data.map((d) => d.pairs))
  return (
    <BarList
      head={["Rodzaj śladu", "połączonych par"]}
      max={max}
      rows={data.map((d) => ({ key: d.group, label: d.label, value: d.pairs, title: `${d.label}: ${d.pairs} par` }))}
    />
  )
}

// ------------------------------------------------------------------ 3. content views: inside vs outside
const SHORT_VIEW_LABEL: Record<string, string> = {
  "tekst strony": "Tekst strony",
  "tekst kreacji (OCR)": "Tekst kreacji (OCR)",
  "znaczenie tekstu (e5)": "Znaczenie tekstu",
  "struktura HTML": "Struktura HTML",
  "obrazy": "Obrazy",
}

/** Per content view: mean similarity of pairs inside a campaign vs pairs across campaigns (0–1). */
export function ViewComparisonChart({ data, insideLabel = "pary z tej samej kampanii", outsideLabel = "pary z różnych kampanii" }: {
  data: { label: string; inside: number | null; outside: number | null }[]
  insideLabel?: string
  outsideLabel?: string
}) {
  if (!data.length) return <Empty>Brak widoków treści do porównania.</Empty>
  const bar = (v: number | null, color: string, name: string) => (
    <div className="grid grid-cols-[minmax(0,1fr)_3.75rem] items-center gap-x-3" title={`${name}: ${v === null ? "brak danych" : fmtP(v)}`}>
      <span className="relative block h-2.5 border-l border-[var(--axis)]">
        {v !== null && v > 0 && <span className="absolute inset-y-0 left-0 block min-w-0.5 rounded-r-[3px]" style={{ width: `${Math.min(1, v) * 100}%`, background: color }} />}
      </span>
      <span className={cn("text-right tabular", v === null ? "text-xs text-muted-foreground" : "text-sm font-medium")}>{v === null ? "brak danych" : fmtP(v)}</span>
    </div>
  )
  return (
    <figure className="space-y-3">
      <ChartLegend items={[{ label: insideLabel, color: "var(--viz-bar)" }, { label: outsideLabel, color: "var(--viz-neutral)" }]} />
      <div className="space-y-3 text-sm">
        {data.map((d) => (
          <div key={d.label} className="grid grid-cols-[minmax(6rem,10rem)_minmax(0,1fr)] items-center gap-x-3">
            <span className="leading-snug">{SHORT_VIEW_LABEL[d.label] ?? d.label}</span>
            <div className="space-y-1">
              {bar(d.inside, "var(--viz-bar)", insideLabel)}
              {bar(d.outside, "var(--viz-neutral)", outsideLabel)}
            </div>
          </div>
        ))}
      </div>
      <div aria-hidden className="grid grid-cols-[minmax(6rem,10rem)_minmax(0,1fr)] gap-x-3 text-[11px] text-muted-foreground tabular">
        <span />
        <div className="grid grid-cols-[minmax(0,1fr)_3.75rem] gap-x-3">
          <span className="relative block h-4 border-t border-[var(--grid)]">
            <span className="absolute top-1 left-0">0 — nic wspólnego</span>
            <span className="absolute top-1 right-0">1 — identyczne</span>
          </span>
          <span />
        </div>
      </div>
    </figure>
  )
}

export function CampaignViewProfileChart({ profile }: { profile: CampaignViewProfile[] }) {
  return (
    <ViewComparisonChart
      data={profile.map((p) => ({ label: p.label, inside: p.inside, outside: p.outside }))}
      insideLabel="pary wewnątrz tej kampanii"
      outsideLabel="pary z materiałami spoza kampanii"
    />
  )
}

// ------------------------------------------------------------------ 8. dendrogram
/**
 * UPGMA dendrogram: leaves are materials, a horizontal bar joins two groups at the distance D they merge at.
 * Branches below the campaign cut take the campaign colour; the two dashed lines are the cuts.
 */
export function DendrogramChart({ data }: { data: DendrogramData | null }) {
  const navigate = useNavigate()
  if (!data || data.leaves.length < 2) {
    return <Empty>Dendrogram wymaga co najmniej dwóch materiałów w bazie.</Empty>
  }
  const n = data.leaves.length
  const colW = Math.max(76, Math.min(110, 960 / n))
  const padL = 44
  const padR = 150
  const padT = 30
  const padB = 50
  const plotW = Math.max(480, (n - 1) * colW)
  const plotH = 250
  const width = padL + plotW + padR
  const height = padT + plotH + padB
  const maxD = Math.max(1.0, data.max_d)
  const sx = (x: number) => padL + (n === 1 ? plotW / 2 : (x / (n - 1)) * plotW)
  const sy = (d: number) => padT + plotH - (d / maxD) * plotH
  const { campaign_cut: campCut, family_cut: famCut } = data.thresholds
  const leafAt = (x: number) => data.leaves.reduce((best, l) => (Math.abs(l.x - x) < Math.abs(best.x - x) ? l : best))
  const NEUTRAL = "#a3a29c"

  return (
    <figure className="space-y-3">
      <div className="w-full overflow-x-auto">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="w-full min-w-[680px]"
          role="img"
          aria-label={`Dendrogram ${n} materiałów z progami kampanii (${campCut}) i rodziny (${famCut})`}
        >
          {/* y axis */}
          <text x={padL - 8} y={14} textAnchor="end" fontSize={11} fill={INK_MUTED}>D</text>
          {[0, 0.2, 0.4, 0.6, 0.8, 1.0].map((tick) => {
            const y = sy(tick)
            return (
              <g key={tick}>
                <line x1={padL} x2={padL + plotW} y1={y} y2={y} stroke="#ecebe6" strokeWidth={1} />
                <text x={padL - 8} y={y + 4} textAnchor="end" fontSize={11} fill={INK_MUTED}>{tick.toFixed(1)}</text>
              </g>
            )
          })}

          {/* cuts: the only dashed lines; labels in ink */}
          {[
            { y: sy(campCut), title: `próg kampanii ${campCut}`, sub: "niżej = ta sama kampania" },
            { y: sy(famCut), title: `próg rodziny ${famCut}`, sub: "niżej = podobna treść" },
          ].map((c) => (
            <g key={c.title}>
              <line x1={padL} x2={padL + plotW + 8} y1={c.y} y2={c.y} stroke={INK} strokeWidth={1.25} strokeDasharray="5 4" />
              <text x={padL + plotW + 14} y={c.y + 1} fontSize={11.5} fontWeight={600} fill={INK}>{c.title}</text>
              <text x={padL + plotW + 14} y={c.y + 15} fontSize={11} fill={INK_MUTED}>{c.sub}</text>
            </g>
          ))}

          {/* merges */}
          {data.merges.map((m) => {
            const x1 = sx(m.left_x)
            const x2 = sx(m.right_x)
            const ym = sy(m.y)
            const inCampaign = m.y <= campCut
            const inFamily = !inCampaign && m.y <= famCut
            const camp = inCampaign ? leafAt(m.left_x).campaign : null
            const stroke = inCampaign ? seriesColor(camp?.color) : inFamily ? "#52514e" : NEUTRAL
            return (
              <g key={m.id}>
                <title>{`połączenie przy D = ${m.y.toFixed(2)}`}</title>
                <path
                  d={`M ${x1} ${sy(m.left_y)} L ${x1} ${ym} L ${x2} ${ym} L ${x2} ${sy(m.right_y)}`}
                  fill="none"
                  stroke={stroke}
                  strokeWidth={inCampaign ? 2.5 : inFamily ? 2 : 1.25}
                  strokeLinejoin="round"
                />
                {/* label only the merges that mean something; the rest (above the family cut) stay in the tooltip */}
                {inFamily && (
                  <text x={(x1 + x2) / 2} y={ym + 14} textAnchor="middle" fontSize={11} fontWeight={600} fill={INK}>D = {m.y.toFixed(2)}</text>
                )}
              </g>
            )
          })}

          {/* leaves */}
          {data.leaves.map((leaf) => {
            const x = sx(leaf.x)
            const y = sy(0)
            const multi = (leaf.campaign?.size ?? 0) > 1
            const color = multi ? seriesColor(leaf.campaign?.color) : NEUTRAL
            const name = leaf.name.length > 12 ? `${leaf.name.slice(0, 11)}…` : leaf.name
            return (
              <g key={leaf.id} className="cursor-pointer" onClick={() => navigate(`/materials/${leaf.id}`)}>
                <title>{`Materiał ${leaf.name} (${leaf.campaign?.code ?? "bez kampanii"}): ${leaf.title}`}</title>
                <circle cx={x} cy={y} r={14} fill="transparent" />
                <circle cx={x} cy={y} r={6.5} fill={multi ? color : "#ffffff"} stroke={multi ? "#ffffff" : color} strokeWidth={2} />
                {!multi && <circle cx={x} cy={y} r={6.5} fill="none" stroke={color} strokeWidth={2} />}
                <text x={x} y={y + 24} textAnchor="middle" fontSize={12} fontWeight={600} fill={INK}>{name}</text>
                {leaf.campaign && <text x={x} y={y + 39} textAnchor="middle" fontSize={11} fill={INK_MUTED}>{leaf.campaign.code}</text>}
              </g>
            )
          })}
        </svg>
      </div>
    </figure>
  )
}
