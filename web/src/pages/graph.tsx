import cytoscape, { type Core, type ElementDefinition } from "cytoscape"
import fcose from "cytoscape-fcose"
import { ArrowRight, Maximize2, X } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { Link, useSearchParams } from "react-router"

import type { GraphData, GraphEdge, GraphNode, Relation } from "@/lib/api"
import { CAMPAIGN_CUT, FAMILY_CUT, fmtP, useApi } from "@/lib/format"
import { CampaignBadge, ErrorState, GroupBadge, Loading, PageHeader, RelationBadge, Strength, StrengthLegend, traceHref } from "@/components/common"
import { EvidenceBrief } from "@/components/evidence"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"

cytoscape.use(fcose)

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#999"
}

/** deterministic pseudo-random start position per node id → the same layout on every load */
function seeded(id: string): { x: number; y: number } {
  let h = 2166136261
  for (let i = 0; i < id.length; i++) h = Math.imul(h ^ id.charCodeAt(i), 16777619)
  const a = ((h >>> 0) % 3600) / 3600
  const b = ((h >>> 12) % 1000) / 1000
  return { x: Math.cos(a * 2 * Math.PI) * (200 + 300 * b), y: Math.sin(a * 2 * Math.PI) * (200 + 300 * b) }
}

const isLinkingGroup = (g: string | undefined) => !!g && g !== "images" && g !== "descriptive"

type Sel = { kind: "node"; node: GraphNode } | { kind: "edge"; edge: GraphEdge } | null
const ALL_RELS: Relation[] = ["same_campaign", "duplicate", "similar"]

export default function GraphPage({ embedded = false }: { embedded?: boolean }) {
  const [params, setParams] = useSearchParams()
  const focus = params.get("focus")
  const traces = params.get("traces") === "1"
  const hideIsolated = params.get("hide") === "1"
  const relParam = params.get("rel")
  const rels = useMemo(() => (relParam === null ? ALL_RELS : (relParam.split(",").filter(Boolean) as Relation[])), [relParam])
  const setParam = (k: string, v: string | null) => setParams((p) => { if (v !== null) p.set(k, v); else p.delete(k); return p }, { replace: true })
  const { data, error, isLoading } = useApi<GraphData>(`/api/graph?traces=${traces}`)
  const [sel, setSel] = useState<Sel>(null)
  const box = useRef<HTMLDivElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const cyRef = useRef<Core | null>(null)

  const elements = useMemo<ElementDefinition[]>(() => {
    if (!data) return []
    const edges = data.edges.filter((e) => e.kind === "trace" || (rels.includes(e.relation as Relation) && !(e.relation === "similar" && e.same_campaign_box)))
    const connected = new Set(edges.flatMap((e) => [e.source, e.target]))
    const multi = new Set(data.nodes.filter((n) => n.kind === "campaign" && (n.campaign?.size ?? 0) > 1).map((n) => n.id))
    const out: ElementDefinition[] = []
    for (const n of data.nodes) {
      if (n.kind === "campaign") {
        if (multi.has(n.id)) out.push({ data: { id: n.id, label: `${n.label}  (${n.campaign?.size} mat.)`, kind: "campaign", color: n.campaign?.color ?? null } })
      } else if (n.kind === "material") {
        if (hideIsolated && !connected.has(n.id)) continue
        const inBox = !!n.parent && multi.has(n.parent)
        out.push({
          data: {
            id: n.id, kind: "material", parent: inBox ? (n.parent ?? undefined) : undefined, thumb: n.thumb ?? undefined,
            label: inBox ? `mat. ${n.label}` : `mat. ${n.label} · ${n.campaign?.code ?? ""}`,
            color: n.campaign?.size && n.campaign.size > 1 ? n.campaign.color : null,
          },
          position: seeded(n.id),
        })
      } else {
        const label = `${n.type_label}: ${n.label}`
        out.push({ data: { id: n.id, kind: "trace", label, linking: isLinkingGroup(n.group), w: Math.min(170, 16 + label.length * 5.4) }, position: seeded(n.id) })
      }
    }
    const ids = new Set(out.map((e) => e.data.id))
    for (const e of edges) {
      if (!ids.has(e.source) || !ids.has(e.target)) continue
      out.push({ data: { id: e.id, source: e.source, target: e.target, kind: e.kind, relation: e.relation, p: e.p ?? 0, label: e.p !== undefined ? fmtP(e.p) : "" } })
    }
    return out
  }, [data, rels, hideIsolated])
  const nMaterials = elements.filter((e) => e.data.kind === "material").length

  useEffect(() => {
    setSel(null)
    if (!box.current || !data || !nMaterials) return
    const series = Array.from({ length: 8 }, (_, i) => cssVar(`--series-${i + 1}`))
    const none = cssVar("--series-none")
    const ink = "#3a3a38"
    const cy = cytoscape({
      container: box.current,
      elements,
      minZoom: 0.2,
      maxZoom: 3,
      style: [
        {
          selector: "node[kind='campaign']",
          style: {
            shape: "round-rectangle", label: "data(label)", "text-valign": "top", "text-halign": "center", "font-size": 13, "font-weight": 600,
            color: "#0b0b0b", "text-margin-y": -6, "background-opacity": 0.07, "border-width": 1.5, padding: "18px",
            "text-wrap": "ellipsis", "text-max-width": "320px",
            "background-color": (e) => (e.data("color") !== null ? series[e.data("color")] : none),
            "border-color": (e) => (e.data("color") !== null ? series[e.data("color")] : none),
          },
        },
        {
          selector: "node[kind='material']",
          style: {
            width: 46, height: 46, shape: "ellipse", label: "data(label)", "font-size": 12, "font-weight": 500, color: "#0b0b0b",
            "text-valign": "bottom", "text-margin-y": 5, "background-color": "#f0efec", "background-fit": "cover", "background-clip": "node",
            "border-width": 3, "border-color": (e) => (e.data("color") !== null && e.data("color") !== undefined ? series[e.data("color")] : none),
            "text-background-color": "#ffffff", "text-background-opacity": 0.85, "text-background-padding": "2px", "text-background-shape": "roundrectangle",
          },
        },
        { selector: "node[kind='material'][thumb]", style: { "background-image": "data(thumb)" } },
        {
          selector: "node[kind='trace']",
          style: {
            shape: "round-rectangle", width: "data(w)", height: 22, label: "data(label)", "font-size": 11, "text-valign": "center",
            "text-halign": "center", "text-wrap": "ellipsis", "text-max-width": "data(w)", color: "#52514e", "background-color": "#ffffff",
            "border-width": 1, "border-color": "#c3c2b7",
          },
        },
        { selector: "node[kind='trace'][?linking]", style: { "border-color": "#0b0b0b", color: "#0b0b0b", "border-width": 1.5 } },
        { selector: "edge", style: { "curve-style": "bezier", "line-color": ink, width: 1.5, opacity: 0.9 } },
        { selector: "edge[relation='same_campaign']", style: { width: "mapData(p, 0.4, 1, 2, 6)" } },
        { selector: "edge[relation='duplicate']", style: { width: 7, "line-color": "#0b0b0b", label: "duplikat", "font-size": 10, "text-background-color": "#fff", "text-background-opacity": 1, "text-background-padding": "2px" } },
        { selector: "edge[relation='similar']", style: { "line-style": "dashed", "line-color": "#8a8984", width: 1.5, "line-dash-pattern": [6, 4] } },
        { selector: "edge[kind='trace']", style: { "line-color": "#d6d5ce", width: 1, opacity: 1 } },
        { selector: ".faded", style: { opacity: 0.15 } },
        { selector: "edge[kind='link']:selected", style: { "line-color": "#256abf", label: "data(label)", "font-size": 11, "text-background-color": "#fff", "text-background-opacity": 1, "text-background-padding": "2px" } },
        { selector: "node[kind='material']:selected", style: { "border-color": "#256abf", "border-width": 4 } },
        { selector: "node[kind='trace']:selected", style: { "border-color": "#256abf", "border-width": 2 } },
      ],
      layout: {
        name: "fcose", quality: "proof", randomize: false, animate: false, nodeDimensionsIncludeLabels: true, packComponents: true,
        nodeRepulsion: () => 9000, idealEdgeLength: (e: cytoscape.EdgeSingular) => (e.data("kind") === "trace" ? 80 : e.data("relation") === "similar" ? 190 : 110),
        edgeElasticity: (e: cytoscape.EdgeSingular) => (e.data("relation") === "similar" ? 0.1 : 0.45), nestingFactor: 0.6, tile: true,
        tilingPaddingVertical: 30, tilingPaddingHorizontal: 30, padding: 30,
      } as cytoscape.LayoutOptions,
    })
    cyRef.current = cy
    const byId = new Map(data.nodes.map((n) => [n.id, n]))
    const eById = new Map(data.edges.map((e) => [e.id, e]))
    const reveal = () => {
      if (window.innerWidth < 1024) setTimeout(() => panel.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50)
    }
    cy.on("tap", "node", (ev) => {
      const n = byId.get(ev.target.id())
      if (n) setSel({ kind: "node", node: n })
      const nb = ev.target.closedNeighborhood().union(ev.target.ancestors()).union(ev.target.descendants())
      cy.elements().addClass("faded")
      nb.removeClass("faded")
      nb.ancestors().removeClass("faded")
      reveal()
    })
    cy.on("tap", "edge", (ev) => {
      const e = eById.get(ev.target.id())
      setSel(e && e.kind === "link" ? { kind: "edge", edge: e } : null)
      cy.elements().addClass("faded")
      ev.target.union(ev.target.connectedNodes()).union(ev.target.connectedNodes().ancestors()).removeClass("faded")
      if (e?.kind === "link") reveal()
    })
    cy.on("tap", (ev) => {
      if (ev.target === cy) {
        setSel(null)
        cy.elements().removeClass("faded")
      }
    })
    cy.on("mouseover", "node[kind='material'], node[kind='trace'], edge[kind='link']", () => { if (box.current) box.current.style.cursor = "pointer" })
    cy.on("mouseout", "node, edge", () => { if (box.current) box.current.style.cursor = "default" })
    if (focus !== null) {
      const c = cy.getElementById(`C${focus}`)
      const target = c.nonempty() ? c.union(c.descendants()) : cy.nodes("[kind='material']").filter((n) => byId.get(n.id())?.campaign?.id === Number(focus))
      if (target.nonempty()) {
        cy.fit(target, 80)
        if (cy.zoom() > 1.3) {
          const bb = target.boundingBox()
          cy.zoom({ level: 1.3, position: { x: (bb.x1 + bb.x2) / 2, y: (bb.y1 + bb.y2) / 2 } })
        }
      }
    }
    return () => {
      cy.destroy()
      cyRef.current = null
    }
  }, [elements, data, focus, nMaterials])

  if (isLoading && !data) return <Loading />
  if (error || !data) return <ErrorState error={error} />
  const counts = data.counts ?? {}

  return (
    <div className="space-y-4">
      {!embedded && (
        <PageHeader
          title="Graf powiązań"
          description="Każde kółko to materiał (z miniaturą kreacji). Ramka z nazwą = kampania wielomateriałowa. Linia = powiązanie pary; grubsza = bliższa. Kliknij materiał lub linię, aby zobaczyć uzasadnienie."
        />
      )}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-3 rounded-xl border bg-card p-3.5 shadow-xs">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-muted-foreground">Pokaż linie dla relacji:</span>
          <ToggleGroup type="multiple" variant="outline" size="sm" className="flex-wrap" value={rels} onValueChange={(v) => setParam("rel", v.length === ALL_RELS.length ? null : v.join(","))}>
            <ToggleGroupItem value="same_campaign" className="px-3">Ta sama kampania <span className="opacity-70">{counts.same_campaign ?? 0}</span></ToggleGroupItem>
            <ToggleGroupItem value="duplicate" className="px-3">Duplikaty <span className="opacity-70">{counts.duplicate ?? 0}</span></ToggleGroupItem>
            <ToggleGroupItem value="similar" className="px-3">Podobna treść <span className="opacity-70">{counts.similar ?? 0}</span></ToggleGroupItem>
          </ToggleGroup>
        </div>
        <div className="flex items-center gap-2">
          <Switch id="traces" checked={traces} onCheckedChange={(v) => setParam("traces", v ? "1" : null)} />
          <Label htmlFor="traces" className="font-normal">Dorysuj wspólne ślady (piksele, domeny…) jako osobne węzły</Label>
        </div>
        <div className="flex items-center gap-2">
          <Switch id="iso" checked={hideIsolated} onCheckedChange={(v) => setParam("hide", v ? "1" : null)} />
          <Label htmlFor="iso" className="font-normal">Ukryj materiały bez żadnego powiązania</Label>
        </div>
        <Button variant="outline" size="sm" onClick={() => cyRef.current?.fit(undefined, 30)}>
          <Maximize2 /> Dopasuj widok
        </Button>
        {focus !== null && <Button variant="ghost" size="sm" onClick={() => setParam("focus", null)}>Pokaż całość</Button>}
      </div>
      <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
        <Card className="relative overflow-hidden py-0 shadow-xs">
          <div ref={box} className="h-[62vh] min-h-[460px] w-full bg-[#fcfcfb] md:h-[72vh] md:min-h-[560px]" aria-label="Graf powiązań materiałów" role="img" />
          {!nMaterials && (
            <div className="absolute inset-0 flex items-center justify-center p-6 text-center text-sm text-muted-foreground">
              Nic do pokazania — włącz co najmniej jeden rodzaj linii albo wyłącz „Ukryj materiały bez powiązań”.
            </div>
          )}
        </Card>
        <div ref={panel} className="scroll-mt-20 space-y-4">
          {sel ? <SelectionPanel sel={sel} data={data} onClose={() => { setSel(null); cyRef.current?.elements().removeClass("faded"); cyRef.current?.elements().unselect() }} /> : <Legend traces={traces} />}
        </div>
      </div>
    </div>
  )
}

function Legend({ traces }: { traces: boolean }) {
  return (
    <Card>
      <CardHeader><CardTitle>Jak czytać graf</CardTitle></CardHeader>
      <CardContent className="space-y-3.5 text-sm">
        <LegendRow sample={<svg width="44" height="20"><circle cx="22" cy="10" r="8" fill="#f0efec" stroke="var(--series-1)" strokeWidth="3" /></svg>}>
          Materiał (numer pod spodem). Kolorowa obwódka = należy do kampanii wielomateriałowej.
        </LegendRow>
        <LegendRow sample={<svg width="44" height="20"><circle cx="22" cy="10" r="8" fill="#f0efec" stroke="var(--series-none)" strokeWidth="3" /></svg>}>
          Szara obwódka = kampania jednomateriałowa (jej kod obok numeru, np. „mat. 10 · C6”).
        </LegendRow>
        <LegendRow sample={<svg width="44" height="20"><rect x="2" y="2" width="40" height="16" rx="4" fill="var(--series-1)" fillOpacity="0.08" stroke="var(--series-1)" strokeWidth="1.5" /></svg>}>
          Ramka = kampania (materiały połączone wspólnym identyfikatorem lub bliską treścią).
        </LegendRow>
        <LegendRow sample={<svg width="44" height="20"><line x1="2" y1="10" x2="42" y2="10" stroke="#3a3a38" strokeWidth="4" /></svg>}>
          Ta sama kampania — wspólny identyfikator albo odległość treści d ≤ {CAMPAIGN_CUT}; im grubsza, tym bliższa.
        </LegendRow>
        <LegendRow sample={<svg width="44" height="20"><line x1="2" y1="10" x2="42" y2="10" stroke="#0b0b0b" strokeWidth="7" /></svg>}>
          Duplikat — ten sam materiał zgłoszony ponownie (podpisany „duplikat”).
        </LegendRow>
        <LegendRow sample={<svg width="44" height="20"><line x1="2" y1="10" x2="42" y2="10" stroke="#8a8984" strokeWidth="1.5" strokeDasharray="6 4" /></svg>}>
          Podobna treść między kampaniami (d ≤ {FAMILY_CUT}), bez wspólnego identyfikatora.
        </LegendRow>
        {traces && (
          <LegendRow sample={<svg width="44" height="20"><rect x="2" y="3" width="19" height="14" rx="3" fill="#fff" stroke="#0b0b0b" strokeWidth="1.5" /><rect x="24" y="3" width="18" height="14" rx="3" fill="#fff" stroke="#c3c2b7" strokeWidth="1" /></svg>}>
            Wspólny ślad dzielony przez materiały. Czarna ramka = identyfikator (łączy), szara = obraz ze strony (widok treści).
          </LegendRow>
        )}
        <p className="text-xs text-muted-foreground">
          Kliknięty element jest podświetlony na niebiesko, a reszta wyszarzona. Kliknij tło, aby wyczyścić. Przewijaj, aby przybliżyć; przeciągaj tło, aby przesunąć.
        </p>
      </CardContent>
    </Card>
  )
}

function LegendRow({ sample, children }: { sample: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[44px_1fr] items-start gap-3">
      <span className="pt-0.5">{sample}</span>
      <span className="text-muted-foreground">{children}</span>
    </div>
  )
}

function SelectionPanel({ sel, data, onClose }: { sel: NonNullable<Sel>; data: GraphData; onClose: () => void }) {
  const name = (id: string) => data.nodes.find((n) => n.id === id)?.label ?? id
  const title = sel.kind === "edge" ? `Powiązanie: mat. ${name(sel.edge.source)} ↔ mat. ${name(sel.edge.target)}`
    : sel.node.kind === "material" ? `Materiał ${sel.node.label}` : sel.node.kind === "trace" ? "Wspólny ślad" : sel.node.label
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-2">
        <CardTitle>{title}</CardTitle>
        <Button variant="ghost" size="icon" className="-mt-1 -mr-2 size-7" onClick={onClose} aria-label="Zamknij szczegóły"><X /></Button>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {sel.kind === "edge" && (
          <>
            <Strength p={sel.edge.p ?? 0} />
            <StrengthLegend />
            <p className="flex flex-wrap items-center gap-2">
              <RelationBadge relation={sel.edge.relation as Relation} />
              <span className="text-xs text-muted-foreground tabular">odległość treści d = {fmtP(sel.edge.distance)}</span>
            </p>
            <div>
              <p className="mb-2 font-medium">Najważniejsze dowody</p>
              <EvidenceBrief evidence={sel.edge.evidence ?? []} />
            </div>
            <Button asChild size="sm" className="w-full"><Link to={`/pair/${sel.edge.source}/${sel.edge.target}`}>Porównaj parę <ArrowRight /></Link></Button>
          </>
        )}
        {sel.kind === "node" && sel.node.kind === "material" && (
          <>
            {sel.node.thumb && <img src={sel.node.thumb} alt="" className="max-h-48 w-full rounded-md bg-muted object-contain" />}
            <CampaignBadge c={sel.node.campaign} withName />
            <p className="text-muted-foreground">{sel.node.title}</p>
            {sel.node.scam_type_label && <p>Typ oszustwa: {sel.node.scam_type_label}</p>}
            <Button asChild size="sm" className="w-full"><Link to={`/materials/${sel.node.id}`}>Otwórz materiał <ArrowRight /></Link></Button>
          </>
        )}
        {sel.kind === "node" && sel.node.kind === "trace" && (
          <>
            <p className="flex flex-wrap items-center gap-2 text-muted-foreground">{sel.node.type_label} {sel.node.group_label && <GroupBadge label={sel.node.group_label} linking={isLinkingGroup(sel.node.group)} />}</p>
            <p className="font-mono text-xs break-all">
              {sel.node.full_display}
              {(sel.node.n_values ?? 1) > 1 && <span className="font-sans text-muted-foreground"> (+{(sel.node.n_values ?? 1) - 1} innych wartości)</span>}
            </p>
            <p>Występuje w {sel.node.n} materiałach.</p>
            <Button asChild size="sm" className="w-full"><Link to={traceHref(sel.node.type ?? "", sel.node.full ?? "")}>Pokaż materiały z tym śladem <ArrowRight /></Link></Button>
          </>
        )}
        {sel.kind === "node" && sel.node.kind === "campaign" && sel.node.campaign && (
          <Button asChild size="sm" className="w-full"><Link to={`/campaigns/${sel.node.campaign.id}`}>Otwórz kampanię <ArrowRight /></Link></Button>
        )}
      </CardContent>
    </Card>
  )
}
