import { useMemo, useState } from "react"
import { useNavigate } from "react-router"

import type { ClusterMethod, FeatureSpace, MaterialSummary, MetricsOverview } from "@/lib/api"
import { fmtP, matLabel, plural, seriesColor, useApi } from "@/lib/format"
import { DendrogramChart, ViewComparisonChart } from "@/components/charts"
import { CampaignBadge, ErrorState, Loading, PageHeader, Section } from "@/components/common"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { cn } from "@/lib/utils"

type ProjKey = "mds" | "tsne"

const W = 760
const H = 500
const PAD = 40
const INK = "#0b0b0b"
const EDGE = "#6f6e69"
const NEUTRAL = "#a3a29c"
/** smallest on-screen gap between two points (px in the 760×500 plot) */
const MIN_GAP = 24

export default function SpacePage() {
  const { data, error, isLoading } = useApi<FeatureSpace>("/api/feature-space")
  const metrics = useApi<MetricsOverview>("/api/metrics/overview")
  const [methodKey, setMethodKey] = useState("faketrace")
  const [proj, setProj] = useState<ProjKey>("mds")

  if (isLoading) return <Loading />
  if (error || !data) return <ErrorState error={error} />
  if (data.points.length < 2 || !data.methods.length) {
    return (
      <>
        <PageHeader title="Przestrzeń cech" />
        <p className="text-muted-foreground">Przestrzeń cech wymaga co najmniej dwóch materiałów w bazie.</p>
      </>
    )
  }
  const method = data.methods.find((m) => m.key === methodKey) ?? data.methods[0]
  const projection = data.projections[proj] ?? data.projections.mds
  const projKeys = (["mds", "tsne"] as const).filter((k) => data.projections[k])
  const views = metrics.data?.view_summary ?? []

  return (
    <>
      <PageHeader
        title="Przestrzeń cech"
        description="Każdy punkt to materiał. Na płaszczyźnie leżą tym bliżej, im bardziej podobna jest ich treść (tekst strony, tekst z kreacji, znaczenie, struktura HTML, obrazy). Kolor pokazuje grupy, które wyznacza wybrana metoda grupowania. Linia łączy materiały ze wspólnym identyfikatorem."
      />

      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <ToggleGroup type="single" variant="outline" spacing={0} value={method.key} onValueChange={(v) => v && setMethodKey(v)} aria-label="Metoda grupowania" className="flex-wrap">
          {data.methods.map((m) => <ToggleGroupItem key={m.key} value={m.key} className="px-3">{m.label}</ToggleGroupItem>)}
        </ToggleGroup>
        {projKeys.length > 1 && (
          <ToggleGroup type="single" variant="outline" spacing={0} value={proj} onValueChange={(v) => v && setProj(v as ProjKey)} aria-label="Rzut na płaszczyznę">
            {projKeys.map((k) => <ToggleGroupItem key={k} value={k} className="px-3">{data.projections[k]!.label}</ToggleGroupItem>)}
          </ToggleGroup>
        )}
      </div>

      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <Section
          title={`${method.label} na rzucie ${projection?.label ?? ""}`}
          description={projection ? (
            <>
              {projection.hint}
              {projection.fit !== null && ` Dwie osie zachowują ${Math.round(projection.fit * 100)}% zmienności odległości — reszta ginie przy spłaszczeniu, więc ufaj liczbom z tabeli bardziej niż odległościom na rysunku.`}
            </>
          ) : undefined}
        >
          {projection ? <Scatter points={data.points} xy={projection.xy} method={method} edges={data.identifier_edges} /> : <p className="text-sm text-muted-foreground">Brak rzutu.</p>}
        </Section>
        <MethodPanel method={method} points={data.points} />
      </div>

      <Section
        title="Porównanie metod"
        description="Te same materiały, różne algorytmy. Kliknij wiersz, aby zobaczyć podział na rysunku."
        contentClassName="px-0"
      >
        <ComparisonTable methods={data.methods} current={method.key} onPick={setMethodKey} hasLabels={!!data.labels} />
        <dl className="mt-4 grid gap-x-8 gap-y-3 px-6 text-sm sm:grid-cols-2">
          <div>
            <dt className="font-medium">Silhouette (od −1 do 1)</dt>
            <dd className="text-muted-foreground">Dla każdego materiału: o ile bliżej mu do własnej grupy niż do najbliższej obcej (liczone na odległości D). Wyżej = grupy zwarte i wyraźnie rozdzielone.</dd>
          </div>
          <div>
            <dt className="font-medium">Zgodność ARI (od 0 do 1)</dt>
            <dd className="text-muted-foreground">
              Skorygowany indeks Randa: czy dwa podziały łączą te same pary materiałów. 1 = identyczny podział, 0 = zgodność jak przy losowym przydziale.
              {data.labels && ` Etykiety to ręczne przypisanie kampanii z pliku ${data.labels.file} (${plural(data.labels.n, "materiał", "materiały", "materiałów")}).`}
            </dd>
          </div>
        </dl>
      </Section>

      {metrics.data && (
        <>
          <Section
            title="Drzewo łączenia (UPGMA)"
            description={`Jak metoda FakeTrace skleja materiały: poziomy odcinek łączy dwie grupy na wysokości odległości D, przy której się łączą. Wszystko poniżej progu ${data.campaign_cut} to jedna kampania. Kliknij liść, aby otworzyć materiał.`}
          >
            <DendrogramChart data={metrics.data.dendrogram} />
          </Section>
          {views.length > 0 && (
            <Section
              title="Które cechy odróżniają kampanie"
              description="Średnie podobieństwo w każdym widoku treści dla par z tej samej kampanii i par z różnych kampanii. Im większa różnica między słupkami, tym lepiej cecha rozpoznaje kampanię."
              contentClassName="max-w-3xl"
            >
              <ViewComparisonChart data={views.map((v) => ({ label: v.label, inside: v.n_same ? v.mean_same : null, outside: v.n_diff ? v.mean_diff : null }))} />
            </Section>
          )}
        </>
      )}
    </>
  )
}

/** groups of one method: multi-material groups by size, then the rest */
function groupsOf(method: ClusterMethod) {
  const by = new Map<number, number[]>()
  method.cluster.forEach((c, i) => {
    if (method.noise[i]) return
    by.set(c, [...(by.get(c) ?? []), i])
  })
  const multi = [...by.values()].filter((g) => g.length > 1).sort((a, b) => b.length - a.length || a[0] - b[0])
  const alone = [...by.values()].filter((g) => g.length === 1).map((g) => g[0])
  const noise = method.noise.flatMap((x, i) => (x ? [i] : []))
  return { multi, alone, noise }
}

function fill(method: ClusterMethod, i: number, multi: Set<number>): string | null {
  if (method.noise[i] || !multi.has(i)) return null
  return method.color[i] === null ? "#52514e" : seriesColor(method.color[i])
}

function Scatter({ points, xy, method, edges }: { points: MaterialSummary[]; xy: [number, number][]; method: ClusterMethod; edges: [number, number][] }) {
  const navigate = useNavigate()
  const [hover, setHover] = useState<number | null>(null)
  const inMulti = useMemo(() => new Set(groupsOf(method).multi.flat()), [method])

  // fit the points into the plot with one scale for both axes, so distances stay honest;
  // then nudge apart points that would sit on top of each other, so every material stays visible and clickable
  const pos = useMemo(() => {
    const xs = xy.map((p) => p[0])
    const ys = xy.map((p) => p[1])
    const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)]
    const s = Math.min((W - 2 * PAD) / Math.max(1e-9, x1 - x0), (H - 2 * PAD) / Math.max(1e-9, y1 - y0))
    const ox = (W - (x1 - x0) * s) / 2
    const oy = (H - (y1 - y0) * s) / 2
    const P = xy.map(([x, y]) => ({ x: ox + (x - x0) * s, y: oy + (y - y0) * s }))
    for (let it = 0; it < 80; it++) {
      let moved = false
      for (let i = 0; i < P.length; i++) {
        for (let j = i + 1; j < P.length; j++) {
          let dx = P[j].x - P[i].x
          let dy = P[j].y - P[i].y
          let d = Math.hypot(dx, dy)
          if (d >= MIN_GAP) continue
          if (d < 1e-6) {
            dx = Math.cos(j * 2.399)
            dy = Math.sin(j * 2.399)
            d = 1
          }
          const push = (MIN_GAP - d) / 2
          P[i].x -= (dx / d) * push
          P[i].y -= (dy / d) * push
          P[j].x += (dx / d) * push
          P[j].y += (dy / d) * push
          moved = true
        }
      }
      if (!moved) break
    }
    return P.map((p) => ({ x: Math.max(PAD / 2, Math.min(W - PAD / 2, p.x)), y: Math.max(PAD / 2, Math.min(H - PAD / 2, p.y)) }))
  }, [xy])

  // each label goes right, left, above or below its point — the first spot that hits nothing
  const placed = useMemo(() => {
    const boxes: { x0: number; x1: number; y0: number; y1: number }[] = []
    return points.map((m, i) => {
      const full = matLabel(m)
      const text = full.length > 12 ? `${full.slice(0, 11)}…` : full
      const w = text.length * 6.7 + 2
      const cands = [
        { dx: 13, dy: 4, anchor: "start" as const },
        { dx: -13, dy: 4, anchor: "end" as const },
        { dx: 0, dy: -14, anchor: "middle" as const },
        { dx: 0, dy: 24, anchor: "middle" as const },
      ]
      const boxOf = (c: (typeof cands)[number]) => {
        const x = pos[i].x + c.dx
        const x0 = c.anchor === "start" ? x : c.anchor === "end" ? x - w : x - w / 2
        return { x0, x1: x0 + w, y0: pos[i].y + c.dy - 11, y1: pos[i].y + c.dy + 3 }
      }
      const hits = (b: { x0: number; x1: number; y0: number; y1: number }) =>
        b.x0 < 0 || b.x1 > W || b.y0 < 0 || b.y1 > H ||
        boxes.some((o) => b.x0 < o.x1 && b.x1 > o.x0 && b.y0 < o.y1 && b.y1 > o.y0) ||
        pos.some((p, k) => k !== i && p.x + 9 > b.x0 && p.x - 9 < b.x1 && p.y + 9 > b.y0 && p.y - 9 < b.y1)
      const c = cands.find((c) => !hits(boxOf(c))) ?? cands[0]
      boxes.push(boxOf(c))
      return { text, ...c }
    })
  }, [points, pos])

  const labels = points.length <= 40
  const h = hover !== null ? points[hover] : null
  const hp = hover !== null ? pos[hover] : null

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full rounded-lg bg-[#fcfcfb] ring-1 ring-border" role="img" aria-label={`Rzut ${points.length} materiałów na płaszczyznę, kolor według metody ${method.label}`}>
        {edges.map(([a, b]) => (
          <line key={`${a}-${b}`} x1={pos[a].x} y1={pos[a].y} x2={pos[b].x} y2={pos[b].y} stroke={EDGE} strokeWidth={1.25} strokeOpacity={hover === null || hover === a || hover === b ? 0.6 : 0.15} />
        ))}
        {points.map((m, i) => {
          const f = fill(method, i, inMulti)
          const noise = method.noise[i]
          const faded = hover !== null && hover !== i
          return (
            <g
              key={m.id}
              transform={`translate(${pos[i].x} ${pos[i].y})`}
              className="cursor-pointer"
              opacity={faded ? 0.45 : 1}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(i)}
              onBlur={() => setHover(null)}
              onClick={() => navigate(`/materials/${m.id}`)}
              onKeyDown={(e) => e.key === "Enter" && navigate(`/materials/${m.id}`)}
              tabIndex={0}
              role="link"
              aria-label={`Materiał ${matLabel(m)}`}
            >
              <circle r={16} fill="transparent" />
              <circle
                r={hover === i ? 10 : 8}
                fill={f ?? "#ffffff"}
                stroke={f ? "#ffffff" : NEUTRAL}
                strokeWidth={2}
                strokeDasharray={noise ? "3 2" : undefined}
                style={{ transition: "fill 200ms" }}
              />
              {labels && (
                <text x={placed[i].dx} y={placed[i].dy} textAnchor={placed[i].anchor} fontSize={12} fontWeight={500} fill={INK} stroke="#fcfcfb" strokeWidth={3} paintOrder="stroke">
                  {placed[i].text}
                </text>
              )}
            </g>
          )
        })}
      </svg>
      {h && hp && (
        <div
          className="pointer-events-none absolute z-10 w-60 rounded-lg bg-popover p-3 text-sm shadow-md ring-1 ring-foreground/10"
          style={{
            left: `${(hp.x / W) * 100}%`,
            top: `${(hp.y / H) * 100}%`,
            transform: `translate(${hp.x > W * 0.6 ? "calc(-100% - 14px)" : "14px"}, ${hp.y > H * 0.6 ? "calc(-100% + 10px)" : "-10px"})`,
          }}
        >
          <div className="flex items-start gap-3">
            {h.thumb && <img src={h.thumb} alt="" className="size-12 shrink-0 rounded object-cover ring-1 ring-border" />}
            <div className="min-w-0">
              <p className="font-medium">Materiał {matLabel(h)}</p>
              <p className="line-clamp-2 text-xs text-muted-foreground">{h.product || h.title}</p>
            </div>
          </div>
          <p className="mt-2 flex items-center gap-2 text-xs">
            <span className="text-muted-foreground">FakeTrace:</span> <CampaignBadge c={h.campaign} link={false} />
          </p>
          {method.key !== "faketrace" && (
            <p className="mt-1 text-xs">
              <span className="text-muted-foreground">{method.label}:</span>{" "}
              {method.noise[hover!] ? "szum" : inMulti.has(hover!) ? "w grupie" : "osobno"}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

function MethodPanel({ method, points }: { method: ClusterMethod; points: MaterialSummary[] }) {
  const { multi, alone, noise } = groupsOf(method)
  const names = (ix: number[]) => ix.map((i) => matLabel(points[i])).join(", ")
  return (
    <Section title={method.label} description={method.hint}>
      <dl className="grid grid-cols-3 gap-2 text-center">
        {[
          { label: "grupy", value: method.n_clusters },
          { label: "osobno", value: method.n_singletons },
          { label: "silhouette", value: method.silhouette === null ? "—" : fmtP(method.silhouette) },
        ].map((s) => (
          <div key={s.label} className="rounded-lg bg-muted/60 px-2 py-2">
            <dd className="text-xl font-semibold tabular">{s.value}</dd>
            <dt className="text-xs text-muted-foreground">{s.label}</dt>
          </div>
        ))}
      </dl>
      <ul className="mt-4 space-y-3 text-sm">
        {multi.map((g) => {
          const codes = [...new Set(g.map((i) => points[i].campaign?.code).filter(Boolean))]
          const c = method.color[g[0]]
          return (
            <li key={g.join()} className="flex gap-2.5">
              <span className="mt-1 size-3 shrink-0 rounded-full" style={{ background: c === null ? "#52514e" : seriesColor(c) }} aria-hidden />
              <div className="min-w-0">
                <p className="font-medium">{plural(g.length, "materiał", "materiały", "materiałów")}: {names(g)}</p>
                <p className="text-xs text-muted-foreground">kampanie FakeTrace: {codes.join(", ") || "—"}</p>
              </div>
            </li>
          )
        })}
        {alone.length > 0 && (
          <li className="flex gap-2.5">
            <span className="mt-1 size-3 shrink-0 rounded-full border-2" style={{ borderColor: NEUTRAL }} aria-hidden />
            <p><span className="font-medium">Osobno:</span> <span className="text-muted-foreground">{names(alone)}</span></p>
          </li>
        )}
        {noise.length > 0 && (
          <li className="flex gap-2.5">
            <span className="mt-1 size-3 shrink-0 rounded-full border-2 border-dashed" style={{ borderColor: NEUTRAL }} aria-hidden />
            <p><span className="font-medium">Szum:</span> <span className="text-muted-foreground">{names(noise)}</span></p>
          </li>
        )}
      </ul>
    </Section>
  )
}

function ComparisonTable({ methods, current, onPick, hasLabels }: { methods: ClusterMethod[]; current: string; onPick: (k: string) => void; hasLabels: boolean }) {
  const num = (v: number | null) => (v === null ? "—" : fmtP(v))
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="pl-6">Metoda</TableHead>
            <TableHead className="text-right">Grupy</TableHead>
            <TableHead className="text-right">Osobno</TableHead>
            <TableHead className="text-right">Silhouette</TableHead>
            <TableHead className="text-right">Zgodność z FakeTrace</TableHead>
            {hasLabels && <TableHead className="pr-6 text-right">Zgodność z etykietami</TableHead>}
          </TableRow>
        </TableHeader>
        <TableBody>
          {methods.map((m) => (
            <TableRow
              key={m.key}
              onClick={() => onPick(m.key)}
              className={cn("cursor-pointer", m.key === current && "bg-muted/70 hover:bg-muted/70")}
              aria-selected={m.key === current}
            >
              <TableCell className="pl-6 font-medium">{m.label}</TableCell>
              <TableCell className="text-right tabular">{m.n_clusters}</TableCell>
              <TableCell className="text-right tabular">{m.n_singletons + m.n_noise}</TableCell>
              <TableCell className="text-right tabular">{num(m.silhouette)}</TableCell>
              <TableCell className="text-right tabular">{num(m.ari_faketrace)}</TableCell>
              {hasLabels && <TableCell className="pr-6 text-right tabular">{num(m.ari_labels)}</TableCell>}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
