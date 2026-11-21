import { useMemo, useRef, useState, type KeyboardEvent } from "react"
import { Link, useNavigate } from "react-router"

import type { MatrixData, Relation } from "@/lib/api"
import { fmtP, P_CLASSES, seqColor, seqInk, useApi } from "@/lib/format"
import { CampaignDot, ErrorState, Loading, PageHeader, ReadingNote } from "@/components/common"
import { Card, CardContent } from "@/components/ui/card"

const REL_PL: Record<Relation, string> = {
  duplicate: "duplikat",
  same_campaign: "ta sama kampania",
  similar: "podobna treść",
  none: "brak bezpośredniego powiązania",
}
const HATCH = "repeating-linear-gradient(45deg,#e8e7e2 0 3px,#fcfcfb 3px 6px)"

export default function MatrixPage({ embedded = false }: { embedded?: boolean }) {
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
  const cell = n <= 12 ? 48 : n <= 30 ? 32 : n <= 60 ? 20 : 14
  const showNums = cell >= 30
  const labelW = 132
  const top = 38
  const shortCol = (s: string) => (s.length <= 7 ? s : s.slice(0, 6) + "…")
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
    <div className="space-y-4">
      {!embedded && (
        <PageHeader
          title="Macierz podobieństwa"
          description="Każda komórka to bliskość p = 1 − D jednej pary materiałów — im ciemniej, tym bliżej. Wiersze i kolumny ułożone są według kampanii (ciemne kwadraty na przekątnej). Kliknij komórkę, aby zobaczyć pełne uzasadnienie pary."
        />
      )}
      <div className="grid gap-5 xl:grid-cols-[auto_22rem]">
        <Card className="min-w-0">
          <CardContent className="overflow-x-auto">
            <ReadingNote className="mb-4">
              każdy wiersz i każda kolumna to jeden materiał, a komórka na ich przecięciu to para. Im ciemniejsza komórka, tym bliższa para;
              liczba to bliskość p. Ciemny kwadrat wokół przekątnej to jedna kampania. Macierz jest symetryczna, więc każda para występuje w niej dwa razy.
              Kliknij komórkę, aby porównać parę.
            </ReadingNote>
            <div className="relative inline-block" style={{ paddingLeft: labelW, paddingTop: top }}>
              {data.materials.map((m, j) => (
                <div
                  key={`c-${m.id}`}
                  title={`Materiał ${m.name} (${m.campaign?.code ?? "—"})`}
                  className="absolute flex items-end justify-center gap-0.5 overflow-hidden px-0.5 text-xs font-medium"
                  style={{ left: labelW + j * cell, top: 0, width: cell, height: 34 }}
                >
                  {cell >= 20 && <CampaignDot c={m.campaign} className="mb-0.5 size-2 shrink-0" />}
                  {cell >= 20 && <span className={`truncate ${active && cur.j === j ? "underline" : ""}`}>{shortCol(m.name)}</span>}
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
                  <span className={`truncate ${active && cur.i === i ? "underline" : ""}`}>{m.name}</span>
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
                <p className="text-muted-foreground">Najedź na komórkę, aby zobaczyć tu szczegóły pary. Z klawiatury: Tab przenosi do macierzy, strzałki zmieniają komórkę, Enter otwiera porównanie pary.</p>
              ) : cur.i === cur.j ? (
                <p className="text-muted-foreground">Materiał {a.name} na przecięciu z samym sobą — przekątna nie ma wartości.</p>
              ) : (
                <>
                  <p className="font-medium">Materiał {a.name} ↔ Materiał {b.name}</p>
                  <p className="tabular">bliskość p = <span className="font-medium">{fmtP(p)}</span> · odległość treści d = <span className="font-medium">{fmtP(dist)}</span></p>
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
              <p className="font-medium">Kolory i oznaczenia</p>
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
            Te same pary jako lista z dowodami: <Link to="/relations?tab=pairs&rel=same_campaign,duplicate,similar,none" className="underline">tabela par</Link>
          </p>
        </div>
      </div>
    </div>
  )
}
