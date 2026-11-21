import cytoscape, { type Core, type ElementDefinition } from "cytoscape"
import fcose from "cytoscape-fcose"
import { ArrowRight, Maximize2, X } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { Link } from "react-router"

import type { GraphData, GraphEdge, GraphNode, Relation } from "@/lib/api"
import { fmtP, useApi } from "@/lib/format"
import { CampaignBadge, ErrorState, Loading, PageHeader, RelationBadge, Strength } from "@/components/common"
import { EvidenceBrief } from "@/components/evidence"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"

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

type Sel = { kind: "node"; node: GraphNode } | { kind: "edge"; edge: GraphEdge } | null

export default function GraphPage() {
  const { data, error, isLoading } = useApi<GraphData>("/api/graph")
  const [sel, setSel] = useState<Sel>(null)
  const [showSimilar, setShowSimilar] = useState(true)
  const box = useRef<HTMLDivElement>(null)
  const cyRef = useRef<Core | null>(null)

  const elements = useMemo<ElementDefinition[]>(() => {
    if (!data) return []
    // "similar" lines inside one campaign box add nothing: the box already says they belong together
    const edges = data.edges.filter((e) => e.kind === "link" && !(e.relation === "similar" && e.same_campaign_box))
    const multi = new Set(data.nodes.filter((n) => n.kind === "campaign" && (n.campaign?.size ?? 0) > 1).map((n) => n.id))
    const out: ElementDefinition[] = []
    for (const n of data.nodes) {
      if (n.kind === "campaign" && multi.has(n.id)) {
        out.push({ data: { id: n.id, label: `${n.label}  (${n.campaign?.size} mat.)`, kind: "campaign", color: n.campaign?.color ?? null } })
      } else if (n.kind === "material") {
        const inBox = !!n.parent && multi.has(n.parent)
        out.push({
          data: {
            id: n.id, kind: "material", parent: inBox ? (n.parent ?? undefined) : undefined, thumb: n.thumb ?? undefined,
            label: inBox ? `mat. ${n.label}` : `mat. ${n.label} · ${n.campaign?.code ?? ""}`,
            color: n.campaign?.size && n.campaign.size > 1 ? n.campaign.color : null,
          },
          position: seeded(n.id),
        })
      }
    }
    for (const e of edges) {
      out.push({ data: { id: e.id, source: e.source, target: e.target, kind: e.kind, relation: e.relation, p: e.p ?? 0, label: e.p !== undefined ? fmtP(e.p) : "" } })
    }
    return out
  }, [data])

  useEffect(() => {
    setSel(null)
    if (!box.current || !data) return
    const series = Array.from({ length: 8 }, (_, i) => cssVar(`--series-${i + 1}`))
    const none = cssVar("--series-none")
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
        { selector: "edge", style: { "curve-style": "bezier", "line-color": "#3a3a38", width: 1.5, opacity: 0.9 } },
        { selector: "edge[relation='same_campaign']", style: { width: "mapData(p, 0.4, 1, 2, 6)" } },
        { selector: "edge[relation='duplicate']", style: { width: 7, "line-color": "#0b0b0b" } },
        { selector: "edge[relation='similar']", style: { "line-color": "#b4b3ad", width: 1 } },
        { selector: ".faded", style: { opacity: 0.15 } },
        { selector: ".off", style: { display: "none" } },
        { selector: "edge:selected", style: { "line-color": "#256abf", label: "data(label)", "font-size": 11, "text-background-color": "#fff", "text-background-opacity": 1, "text-background-padding": "2px" } },
        { selector: "node[kind='material']:selected", style: { "border-color": "#256abf", "border-width": 4 } },
      ],
      layout: {
        name: "fcose", quality: "proof", randomize: false, animate: false, nodeDimensionsIncludeLabels: true, packComponents: true,
        nodeRepulsion: () => 9000, idealEdgeLength: (e: cytoscape.EdgeSingular) => (e.data("relation") === "similar" ? 190 : 110),
        edgeElasticity: (e: cytoscape.EdgeSingular) => (e.data("relation") === "similar" ? 0.1 : 0.45), nestingFactor: 0.6, tile: true,
        tilingPaddingVertical: 30, tilingPaddingHorizontal: 30, padding: 30,
      } as cytoscape.LayoutOptions,
    })
    cyRef.current = cy
    const byId = new Map(data.nodes.map((n) => [n.id, n]))
    const eById = new Map(data.edges.map((e) => [e.id, e]))
    const focus = (els: cytoscape.Collection) => {
      cy.elements().addClass("faded")
      els.union(els.nodes().ancestors()).removeClass("faded")
    }
    cy.on("tap", "node[kind='material'], node[kind='campaign']", (ev) => {
      const n = byId.get(ev.target.id())
      if (n) setSel({ kind: "node", node: n })
      focus(ev.target.closedNeighborhood().union(ev.target.descendants()))
    })
    cy.on("tap", "edge", (ev) => {
      const e = eById.get(ev.target.id())
      setSel(e ? { kind: "edge", edge: e } : null)
      focus(ev.target.union(ev.target.connectedNodes()))
    })
    cy.on("tap", (ev) => {
      if (ev.target === cy) {
        setSel(null)
        cy.elements().removeClass("faded")
      }
    })
    cy.on("mouseover", "node[kind='material'], edge", () => { if (box.current) box.current.style.cursor = "pointer" })
    cy.on("mouseout", "node, edge", () => { if (box.current) box.current.style.cursor = "default" })
    return () => {
      cy.destroy()
      cyRef.current = null
    }
  }, [elements, data])

  // hiding is a style change, not a new layout: the nodes stay where they are
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.edges("[relation='similar']").toggleClass("off", !showSimilar)
    if (!showSimilar) {
      setSel((s) => (s?.kind === "edge" && s.edge.relation === "similar" ? null : s))
      cy.elements().removeClass("faded")
    }
  }, [showSimilar, elements, data])

  if (isLoading && !data) return <Loading />
  if (error || !data) return <ErrorState error={error} />

  const close = () => {
    setSel(null)
    cyRef.current?.elements().removeClass("faded").unselect()
  }

  return (
    <>
      <PageHeader
        title="Graf powiązań"
        description="Kółko to materiał, ramka to kampania. Ciemna linia: ta sama kampania (grubsza = bliżej), cienka szara: podobna treść w różnych kampaniach. Kliknij materiał lub linię, aby zobaczyć dlaczego."
      />
      <Card className="relative overflow-hidden py-0">
        <div ref={box} className="h-[70vh] min-h-[480px] w-full bg-[#fcfcfb]" aria-label="Graf powiązań materiałów" role="img" />
        <div className="absolute top-3 left-3 flex items-center gap-2">
          <Button variant="outline" size="icon" className="bg-card" onClick={() => cyRef.current?.fit(undefined, 30)} aria-label="Dopasuj widok" title="Dopasuj widok">
            <Maximize2 />
          </Button>
          <div className="flex h-9 items-center gap-2 rounded-md border bg-card px-3">
            <Switch id="show-similar" checked={showSimilar} onCheckedChange={setShowSimilar} />
            <Label htmlFor="show-similar" className="text-sm font-normal">Podobna treść między kampaniami</Label>
          </div>
        </div>
        {sel && (
          <div className="absolute top-3 right-3 bottom-3 w-[22rem] max-w-[calc(100%-1.5rem)] overflow-y-auto">
            <SelectionPanel sel={sel} data={data} onClose={close} />
          </div>
        )}
      </Card>
    </>
  )
}

function SelectionPanel({ sel, data, onClose }: { sel: NonNullable<Sel>; data: GraphData; onClose: () => void }) {
  const name = (id: string) => data.nodes.find((n) => n.id === id)?.label ?? id
  const title = sel.kind === "edge" ? `Materiał ${name(sel.edge.source)} ↔ ${name(sel.edge.target)}`
    : sel.node.kind === "material" ? `Materiał ${sel.node.label}` : sel.node.label
  return (
    <Card className="shadow-md">
      <CardHeader className="flex flex-row items-start justify-between gap-2">
        <CardTitle>{title}</CardTitle>
        <Button variant="ghost" size="icon" className="-mt-1 -mr-2 size-7" onClick={onClose} aria-label="Zamknij"><X /></Button>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {sel.kind === "edge" && (
          <>
            <div className="flex items-center gap-3">
              <RelationBadge relation={sel.edge.relation as Relation} />
              <Strength p={sel.edge.p ?? 0} distance={sel.edge.distance} className="flex-1" />
            </div>
            <EvidenceBrief evidence={sel.edge.evidence ?? []} />
            <Button asChild size="sm" className="w-full"><Link to={`/pair/${sel.edge.source}/${sel.edge.target}`}>Pełne porównanie <ArrowRight /></Link></Button>
          </>
        )}
        {sel.kind === "node" && sel.node.kind === "material" && (
          <>
            {sel.node.thumb && <img src={sel.node.thumb} alt="" className="max-h-48 w-full rounded-md bg-muted object-contain" />}
            <CampaignBadge c={sel.node.campaign} withName />
            <p className="text-muted-foreground">{sel.node.title}</p>
            <Button asChild size="sm" className="w-full"><Link to={`/materials/${sel.node.id}`}>Otwórz materiał <ArrowRight /></Link></Button>
          </>
        )}
        {sel.kind === "node" && sel.node.kind === "campaign" && sel.node.campaign && (
          <Button asChild size="sm" className="w-full"><Link to={`/campaigns/${sel.node.campaign.id}`}>Otwórz kampanię <ArrowRight /></Link></Button>
        )}
      </CardContent>
    </Card>
  )
}
