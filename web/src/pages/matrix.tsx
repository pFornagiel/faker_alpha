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
const HATCH = "repeating-linear-gradient(45deg,#e8e7e2 0 3px,#fcfcfb 3px 6px)"

export default function MatrixPage() {
  const { data, error, isLoading } = useApi<MatrixData>("/api/matrix")
  const [cur, setCur] = useState<{ i: number; j: number }>({ i: 0, j: 1 })
  const [active, setActive] = useState(false)
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
  const cell = n <= 12 ? 52 : n <= 30 ? 30 : n <= 60 ? 18 : 12
  const showNums = cell >= 30
  const labelW = 92
  const top = 34
  const boundary = new Set(blocks.map((b) => b.start).filter((s) => s > 0))

  const focusCell = (i: number, j: number) => {
    setCur({ i, j })
    setActive(true)
    grid.current?.querySelector<HTMLButtonElement>(`[data-cell="${i}-${j}"]`)?.focus()
  }
  const onKey = (e: KeyboardEvent) => {
    const d: Record<string, [number, number]> = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] }
    if (d[e.key]) {
      e.preventDefault()
      focusCell(Math.max(0, Math.min(n - 1, cur.i + d[e.key][0])), Math.max(0, Math.min(n - 1, cur.j + d[e.key][1])))
    }
  }
  const a = data.materials[cur.i]
  const b = data.materials[cur.j]
  const p = data.p[cur.i][cur.j]
  const r = data.relation[cur.i][cur.j]
  const dist = data.distance[cur.i][cur.j]
  const t = data.thresholds
  const sameCamp = a.campaign && b.campaign && a.campaign.id === b.campaign.id

  return (
    <>
      <PageHeader
        title="Macierz podobieństwa"
        description="Każda komórka to bliskość p = 1 − D jednej pary materiałów (1 przy wspólnym identyfikatorze, inaczej 1 − d, gdzie d to odległość treści) — im ciemniej, tym bliżej. Wiersze i kolumny to te same materiały, ułożone według kampanii, więc kampania jest widoczna jako ciemny kwadrat na przekątnej (obrysowany na czarno). Kliknij komórkę, aby zobaczyć uzasadnienie pary."
      />
      <div className="grid gap-4 xl:grid-cols-[auto_18rem]">
        <Card className="min-w-0">
          <CardContent className="overflow-x-auto">
            <p className="mb-2 text-xs text-muted-foreground">Wiersze i kolumny: numer materiału (przy wierszu kod kampanii).</p>
            <div className="relative inline-block" style={{ paddingLeft: labelW, paddingTop: top }}>
              {data.materials.map((m, j) => (
                <div key={`c-${m.id}`} className="absolute flex items-end justify-center gap-1 text-xs font-medium" style={{ left: labelW + j * cell, top: 0, width: cell, height: 30 }}>
                  {cell >= 18 && <CampaignDot c={m.campaign} className="size-2" />}
                  {cell >= 18 && <span className={active && cur.j === j ? "underline" : ""}>{m.name}</span>}
                </div>
              ))}
              {data.materials.map((m, i) => (
                <Link
                  key={`r-${m.id}`}
                  to={`/materials/${m.id}`}
                  tabIndex={-1}
                  className="absolute flex items-center justify-end gap-1.5 pr-2 text-xs font-medium hover:underline"
                  style={{ left: 0, top: top + i * cell, width: labelW, height: cell }}
                  title={`Materiał ${m.name} — ${m.campaign?.code ?? ""}`}
                >
                  <span className={active && cur.i === i ? "underline" : ""}>mat. {m.name}</span>
                  <span className="text-muted-foreground">{m.campaign?.code}</span>
                  <CampaignDot c={m.campaign} className="size-2" />
                </Link>
              ))}
              <div
                ref={grid}
                role="grid"
                aria-label="Macierz bliskości par materiałów"
                className="grid"
                style={{ gridTemplateColumns: `repeat(${n}, ${cell}px)`, gridAutoRows: `${cell}px` }}
                onMouseLeave={() => setActive(false)}
                onKeyDown={onKey}
              >
                {data.materials.map((ra, i) =>
                  data.materials.map((rb, j) => {
                    const v = data.p[i][j]
                    const diag = i === j
                    const isCur = cur.i === i && cur.j === j
                    const cross = active && (cur.i === i || cur.j === j) && !isCur
                    return (
                      <button
                        key={`${i}-${j}`}
                        type="button"
                        data-cell={`${i}-${j}`}
                        role="gridcell"
                        tabIndex={isCur ? 0 : -1}
                        aria-disabled={diag}
                        aria-label={diag ? `materiał ${ra.name} (ten sam)` : `materiał ${ra.name} i materiał ${rb.name}: p ${fmtP(v)}`}
                        onMouseEnter={() => { setCur({ i, j }); setActive(true) }}
                        onFocus={() => { setCur({ i, j }); setActive(true) }}
                        onClick={() => !diag && navigate(`/pair/${ra.id}/${rb.id}`)}
                        className="flex items-center justify-center text-[11px] font-medium tabular focus-visible:z-10 focus-visible:outline-3 focus-visible:-outline-offset-3 focus-visible:outline-[#f5b400]"
                        style={{
                          background: diag ? HATCH : seqColor(v ?? 0),
                          color: seqInk(v),
                          borderRight: "2px solid #fcfcfb",
                          borderBottom: "2px solid #fcfcfb",
                          borderLeft: boundary.has(j) ? "2px solid #898781" : undefined,
                          borderTop: boundary.has(i) ? "2px solid #898781" : undefined,
                          cursor: diag ? "default" : "pointer",
                          boxShadow: cross ? "inset 0 0 0 1px rgba(11,11,11,.22)" : isCur && active && !diag ? "inset 0 0 0 2px #0b0b0b" : undefined,
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
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card size="sm" aria-live="polite">
            <CardContent className="space-y-2 text-sm">
              {!active ? (
                <p className="text-muted-foreground">Najedź na komórkę albo przejdź do macierzy klawiszem Tab i poruszaj się strzałkami. Enter lub kliknięcie otwiera uzasadnienie pary.</p>
              ) : cur.i === cur.j ? (
                <p className="text-muted-foreground">Materiał {a.name} — ta sama pozycja (przekątna macierzy nie ma wartości).</p>
              ) : (
                <>
                  <p className="font-medium">Materiał {a.name} ↔ materiał {b.name}</p>
                  <p className="text-2xl font-semibold tabular">p = {fmtP(p)}</p>
                  <p className="text-muted-foreground tabular">odległość treści d = {fmtP(dist)}</p>
                  <p className="text-muted-foreground">
                    {r ? REL_PL[r] : "nie porównano"}
                    {r === "none" && sameCamp ? ` — ale oba w ${a.campaign!.code} przez inne materiały` : ""}
                    {!sameCamp && ` · ${a.campaign?.code} i ${b.campaign?.code}`}
                  </p>
                </>
              )}
            </CardContent>
          </Card>
          <Card size="sm">
            <CardContent className="space-y-3 text-sm">
              <p className="font-medium">Legenda</p>
              <ul className="space-y-1.5 text-xs">
                {P_CLASSES.map((c) => (
                  <li key={c.label} className="flex items-center gap-2">
                    <span className="size-4 shrink-0 rounded-sm ring-1 ring-border" style={{ background: c.color }} />
                    {c.label}
                  </li>
                ))}
                <li className="flex items-center gap-2"><span className="size-4 shrink-0 rounded-sm ring-1 ring-border" style={{ background: HATCH }} /> przekątna — materiał sam ze sobą</li>
                <li className="flex items-center gap-2"><span className="size-4 shrink-0 rounded-sm outline-2 outline-[#0b0b0b]" /> obrys — kampania wielomateriałowa</li>
                <li className="flex items-center gap-2"><span className="h-4 w-0.5 shrink-0 bg-[#898781]" /> szara linia — granica między kampaniami</li>
                <li className="flex items-center gap-2"><CampaignDot c={{ id: 0, code: "", name: "", size: 2, color: 0 }} /> kolorowa kropka — kampania wielomateriałowa; pusta — jednomateriałowa</li>
              </ul>
              <p className="text-xs text-muted-foreground">
                p = 1 — wspólny identyfikator (lub duplikat). Bez identyfikatora decyduje treść: p ≥ {t.link} (d ≤ {t.campaign_cut}) — ta sama kampania, p ≥ {t.similar} (d ≤ {t.family_cut}) — podobna treść.
                {showNums && ` Liczby pokazano tylko dla p ≥ ${t.similar}.`}
              </p>
            </CardContent>
          </Card>
          <p className="text-xs text-muted-foreground">
            Te same dane w tabeli: <Link to="/links?rel=same_campaign,duplicate,similar,none" className="underline underline-offset-4">Powiązania (pary)</Link>
          </p>
        </div>
      </div>
    </>
  )
}
