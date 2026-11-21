import { useMemo, useRef, useState, type KeyboardEvent } from "react"
import { Link, useNavigate } from "react-router"

import type { MatrixData, Relation } from "@/lib/api"
import { fmtP, P_CLASSES, seqColor, seqInk, useApi } from "@/lib/format"
import { CampaignDot, ErrorState, Loading, PageHeader } from "@/components/common"
import { Card, CardContent } from "@/components/ui/card"

const REL_PL: Record<Relation, string> = {
  duplicate: "duplikat",
  same_campaign: "ta sama kampania",
  similar: "podobna treść",
  none: "brak bezpośredniego powiązania",
}
const DIAG = "#e8e7e2"

export default function MatrixPage() {
  const { data, error, isLoading } = useApi<MatrixData>("/api/matrix")
  const [cur, setCur] = useState<{ i: number; j: number } | null>(null)
  const grid = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()

  const blocks = useMemo(() => {
    if (!data) return []
    const out: { start: number; end: number; code: string; multi: boolean }[] = []
    data.materials.forEach((m, i) => {
      const code = m.campaign?.code ?? "—"
      const last = out[out.length - 1]
      if (last && last.code === code) last.end = i
      else out.push({ start: i, end: i, code, multi: (m.campaign?.size ?? 0) > 1 })
    })
    return out
  }, [data])

  if (isLoading) return <Loading />
  if (error || !data) return <ErrorState error={error} />
  const n = data.materials.length
  const cell = n <= 12 ? 48 : n <= 30 ? 32 : n <= 60 ? 20 : 14
  const showNums = cell >= 30
  const labelW = 120
  const top = 30

  const focusCell = (i: number, j: number) => {
    setCur({ i, j })
    grid.current?.querySelector<HTMLButtonElement>(`[data-cell="${i}-${j}"]`)?.focus()
  }
  const onKey = (e: KeyboardEvent) => {
    const d: Record<string, [number, number]> = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] }
    if (d[e.key] && cur) {
      e.preventDefault()
      focusCell(Math.max(0, Math.min(n - 1, cur.i + d[e.key][0])), Math.max(0, Math.min(n - 1, cur.j + d[e.key][1])))
    }
  }
  const a = cur && data.materials[cur.i]
  const b = cur && data.materials[cur.j]
  const r = cur && data.relation[cur.i][cur.j]

  return (
    <>
      <PageHeader
        title="Macierz bliskości"
        description="Każda komórka to para materiałów; im ciemniejsza, tym bliższa (p = 1 przy wspólnym identyfikatorze, inaczej 1 − d). Materiały są ułożone według kampanii, więc kampania to ciemny kwadrat na przekątnej. Kliknij komórkę, aby zobaczyć uzasadnienie."
      />
      <Card className="min-w-0">
        <CardContent className="space-y-4 overflow-x-auto">
          <p className="min-h-5 text-sm" aria-live="polite">
            {a && b && cur && cur.i !== cur.j ? (
              <>
                <span className="font-medium">Materiał {a.name} ↔ {b.name}</span>
                <span className="text-muted-foreground tabular"> · p = {fmtP(data.p[cur.i][cur.j])} · d = {fmtP(data.distance[cur.i][cur.j])} · {r ? REL_PL[r] : "nie porównano"}</span>
              </>
            ) : (
              <span className="text-muted-foreground">Najedź na komórkę, aby zobaczyć parę.</span>
            )}
          </p>
          <div className="relative inline-block" style={{ paddingLeft: labelW, paddingTop: top }}>
            {data.materials.map((m, j) => (
              <div
                key={`c-${m.id}`}
                title={`Materiał ${m.name} (${m.campaign?.code ?? "—"})`}
                className="absolute flex items-end justify-center overflow-hidden text-xs font-medium"
                style={{ left: labelW + j * cell, top: 0, width: cell, height: top - 4 }}
              >
                {cell >= 20 && <span className={`truncate ${cur?.j === j ? "underline" : ""}`}>{m.name.length <= 6 ? m.name : `${m.name.slice(0, 5)}…`}</span>}
              </div>
            ))}
            {data.materials.map((m, i) => (
              <Link
                key={`r-${m.id}`}
                to={`/materials/${m.id}`}
                tabIndex={-1}
                className="absolute flex items-center justify-end gap-1.5 overflow-hidden pr-2.5 text-xs font-medium hover:underline"
                style={{ left: 0, top: top + i * cell, width: labelW, height: cell }}
                title={`Materiał ${m.name} — ${m.campaign?.code ?? ""}`}
              >
                <span className={`truncate ${cur?.i === i ? "underline" : ""}`}>{m.name}</span>
                <span className="shrink-0 text-muted-foreground">{m.campaign?.code}</span>
                <CampaignDot c={m.campaign} className="size-2 shrink-0" />
              </Link>
            ))}
            <div
              ref={grid}
              role="grid"
              aria-label="Macierz bliskości par materiałów"
              className="grid"
              style={{ gridTemplateColumns: `repeat(${n}, ${cell}px)`, gridAutoRows: `${cell}px` }}
              onMouseLeave={() => setCur(null)}
              onKeyDown={onKey}
            >
              {data.materials.map((ra, i) =>
                data.materials.map((rb, j) => {
                  const v = data.p[i][j]
                  const diag = i === j
                  const isCur = cur?.i === i && cur?.j === j
                  return (
                    <button
                      key={`${i}-${j}`}
                      type="button"
                      data-cell={`${i}-${j}`}
                      role="gridcell"
                      tabIndex={(cur ? isCur : i === 0 && j === 1) ? 0 : -1}
                      aria-disabled={diag}
                      aria-label={diag ? `materiał ${ra.name}` : `materiał ${ra.name} i materiał ${rb.name}: p ${fmtP(v)}`}
                      onMouseEnter={() => setCur({ i, j })}
                      onFocus={() => setCur({ i, j })}
                      onClick={() => !diag && navigate(`/pair/${ra.id}/${rb.id}`)}
                      className="flex items-center justify-center text-[11px] font-medium tabular focus-visible:z-10 focus-visible:outline-3 focus-visible:-outline-offset-3 focus-visible:outline-[#f5b400]"
                      style={{
                        background: diag ? DIAG : seqColor(v ?? 0),
                        color: seqInk(v),
                        borderRight: "2px solid #fcfcfb",
                        borderBottom: "2px solid #fcfcfb",
                        cursor: diag ? "default" : "pointer",
                        boxShadow: isCur && !diag ? "inset 0 0 0 2px #0b0b0b" : undefined,
                      }}
                    >
                      {showNums && !diag && v !== null && v >= data.thresholds.similar ? fmtP(v) : ""}
                    </button>
                  )
                }),
              )}
            </div>
            {blocks.filter((bl) => bl.multi).map((bl) => (
              <div
                key={bl.code}
                className="pointer-events-none absolute rounded-sm"
                style={{ left: labelW + bl.start * cell - 2, top: top + bl.start * cell - 2, width: (bl.end - bl.start + 1) * cell + 2, height: (bl.end - bl.start + 1) * cell + 2, outline: "2px solid #0b0b0b" }}
              />
            ))}
          </div>
          <ColourScale />
        </CardContent>
      </Card>
    </>
  )
}

/** Key to the five colour classes (cuts are the real thresholds). */
function ColourScale() {
  return (
    <ul className="flex flex-wrap gap-x-5 gap-y-1.5 text-xs text-muted-foreground" aria-label="Skala kolorów">
      {P_CLASSES.map((c) => (
        <li key={c.label} className="flex items-center gap-1.5">
          <span className="size-3 rounded-[3px] ring-1 ring-foreground/10" style={{ background: c.color }} aria-hidden />
          {c.label}
        </li>
      ))}
    </ul>
  )
}
