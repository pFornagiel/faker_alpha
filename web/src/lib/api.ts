// Typed client for the FakeTrace API (ftf/api.py).

export type Relation = "duplicate" | "same_campaign" | "similar" | "none"
export type Decision = "duplicate" | "known_campaign" | "merge_proposal" | "new_campaign"

export interface CampaignRef {
  id: number
  code: string
  name: string
  size: number
  color: number | null
}

export interface MaterialSignals {
  has_web: boolean
  has_infra: boolean
  has_faces: boolean
  has_ocr: boolean
  has_llm: boolean
  has_images: boolean
  n_indicators: number
  n_linking_indicators: number
  n_faces: number
  n_domains: number
}

export interface MaterialSummary {
  id: string
  name: string
  display_name?: string
  title: string
  source: string
  source_label: string
  created_at: string | null
  campaign: CampaignRef | null
  scam_type: string | null
  scam_type_label: string | null
  product: string | null
  persons: string[]
  domains: string[]
  thumb: string | null
  thumb_kind: string | null
  counts: { pages: number; images: number; videos: number }
  signals?: MaterialSignals
}

/** One piece of evidence behind a link: a shared identifier value or one content view's similarity. */
export type Evidence =
  | { kind: "identifier"; key: string; label: string; type: string; type_label: string; value: string; df: number; ignored: boolean }
  | { kind: "view"; key: string; label: string; score: number; contribution: number }

export interface Reason {
  detail: string
  weight: number
  kind: "identifier" | "view"
  key: string
}

export interface LinkBrief {
  a: string
  b: string
  /** clustering similarity 1 − D: 1 when a counted identifier is shared, else 1 − distance */
  p: number
  /** content (Gower) distance d in [0, 1] */
  distance: number
  relation: Relation
  relation_label: string
  evidence: Evidence[]
  reasons: Reason[]
  comparable: boolean
  other?: MaterialSummary
  a_info?: { id: string; name: string; campaign: CampaignRef | null }
  b_info?: { id: string; name: string; campaign: CampaignRef | null }
}

export interface SharedTrace {
  type: string
  type_label: string
  group: string
  group_label: string
  value: string
  display: string
  n_values: number
  count: number
}

export interface CampaignCard extends CampaignRef {
  members: MaterialSummary[]
  scam_types: { value: string; label: string; n: number }[]
  products: string[]
  persons: string[]
  domains: string[]
  date_range: string[]
  mean_internal_p: number | null
  n_shared: number
  n_shared_kinds: number
  top_shared: SharedTrace[]
  family: number | null
}

export interface Example {
  kind: "campaign" | "pair"
  to: string
  title: string
  concept: string
  text: string
}

export interface Overview {
  n_materials: number
  n_campaigns: number
  n_multi: number
  n_singletons: number
  n_in_multi: number
  n_duplicate_groups: number
  duplicates?: MaterialSummary[][]
  links: Record<Relation, number>
  /** families of similar campaigns (only those spanning 2+ campaigns) */
  families: { id: number; campaigns: number[]; refs: CampaignRef[]; size: number }[]
  campaigns: CampaignCard[]
  examples: Example[]
  thresholds?: Thresholds
}

export interface MatrixRow {
  type: string
  type_label: string
  values: { value: string; display: string }[]
  thumbs: string[]
  group: string
  group_label: string
  /** identifier that forces same campaign (false for landing-page images, which are a content view) */
  linking: boolean
  members: string[]
}

export interface ChainStep {
  a: string
  b: string
  a_name: string
  b_name: string
  p: number
  distance: number
  relation: Relation
  basis: string
  reasons: string[]
}

export interface CampaignViewProfile {
  view: string
  label: string
  inside: number | null
  outside: number | null
  n_inside: number
  n_outside: number
}

export interface CampaignDetail extends CampaignCard {
  matrix: MatrixRow[]
  chain: ChainStep[]
  links: LinkBrief[]
  nearest_outside: (LinkBrief & { inside: string; outside_campaign: CampaignRef | null })[]
  siblings: CampaignRef[]
  titles: string[]
  view_profile?: CampaignViewProfile[]
  thresholds?: Thresholds
  n_pairs: number
}

export interface MaterialSeed {
  kind: string
  kind_label: string
  value: string
  query: string
  can_library_search: boolean
  can_analyse_url: boolean
}

export interface MaterialSeedsResponse {
  material_id: string
  campaign: CampaignRef | null
  seeds: MaterialSeed[]
}

export interface DendrogramLeaf {
  idx: number
  x: number
  id: string
  name: string
  title: string
  campaign: CampaignRef | null
}

export interface DendrogramMerge {
  id: number
  left_x: number
  right_x: number
  x: number
  left_y: number
  right_y: number
  y: number
}

export interface DendrogramData {
  leaves: DendrogramLeaf[]
  merges: DendrogramMerge[]
  max_d: number
  thresholds: Thresholds
}

export interface MetricsOverview {
  n_materials: number
  n_campaigns: number
  n_multi: number
  n_singletons: number
  n_pairs: number
  n_must_link: number
  thresholds: Thresholds
  distance_histogram: { range: string; lo: number; hi: number; must_link: number; same_campaign: number; similar: number; none: number; total: number }[]
  signal_attribution: { group: string; label: string; pairs: number }[]
  feature_coverage: { key: string; label: string; count: number; total: number; pct: number }[]
  scam_types: { label: string; count: number }[]
  top_persons: { name: string; count: number; visual: number; named: number }[]
  view_summary: { view: string; label: string; mean_same: number; mean_diff: number; n_same: number; n_diff: number }[]
  dendrogram: DendrogramData | null
}

export interface IndicatorGroup {
  group: string
  label: string
  linking: boolean
  hint: string
  items: { type: string; type_label: string; values: { value: string; display: string; df: number; thumb: string | null }[]; more: number }[]
}

export interface Features {
  summary: string | null
  llm_backend: string | null
  llm_backend_label: string | null
  llm: { key: string; label: string; value: string | string[] }[]
  text: { titles: string[]; excerpt: string; keywords: string[]; amounts: string[]; brands: string[]; media: string[]; n_chars: number }
  persons: { faces: string[]; named: string[] }
  web: {
    landing_urls: string[]
    landing_domains: string[]
    redirect_chains: string[][]
    ips: string[]
    server_headers: string[]
    behind_cloudflare: boolean | null
    infra: { domain: string; registrar?: string; created?: string; nameservers?: string[]; A?: string[]; first_cert?: string; cert_pl_listed?: boolean }[]
    has_web: boolean
  }
  indicators: IndicatorGroup[]
  n_corpus: number
  images: { url: string | null; kind: string; ocr: string; qr: string[]; faces: { identity: string | null; sim: number }[] }[]
  assets: string[]
  n_assets_total: number
  ocr_links: string[]
  notes: string[]
  dates: string[]
  elapsed_s: number | null
}

export interface MaterialDetail extends MaterialSummary {
  source_ref: string
  inputs: { pages: string[]; images: number; videos: number; assets: number; urls: string[] }
  features: Features
  links: LinkBrief[]
}

export interface IdentifierGroupEvidence {
  group: string
  label: string
  hint: string
  items: { type: string; type_label: string; value: string; display: string; df: number; n: number; detail: string }[]
}

export interface ViewEvidence {
  view: string
  label: string
  hint: string
  available: boolean
  score: number | null
  contribution: number | null
  thumbs: string[]
}

export interface Explanation {
  p: number
  distance: number
  relation: Relation
  relation_label: string
  relation_hint: string
  rule: string
  basis: string
  comparable: boolean
  must_link: boolean
  identifiers: IdentifierGroupEvidence[]
  ignored: { detail: string; type: string; group: string; df: number }[]
  views: ViewEvidence[]
  n_views: number
  formula: string
  evidence: Evidence[]
}

export interface PairDetail extends Explanation {
  a: MaterialSummary
  b: MaterialSummary
}

export interface GraphNode {
  id: string
  kind: "campaign" | "material" | "trace"
  label: string
  parent?: string | null
  title?: string
  campaign?: CampaignRef | null
  thumb?: string | null
  scam_type_label?: string | null
  full?: string
  full_display?: string
  n_values?: number
  type?: string
  type_label?: string
  group?: string
  group_label?: string
  n?: number
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  kind: "link" | "trace"
  p?: number
  distance?: number
  relation?: Relation
  relation_label?: string
  reasons?: Reason[]
  evidence?: Evidence[]
  same_campaign_box?: boolean
}

/** link/similar/duplicate in p units (p = 1 − D); *_cut are the raw distance cuts */
export interface Thresholds {
  link: number
  similar: number
  duplicate: number
  campaign_cut: number
  family_cut: number
  duplicate_cut: number
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
  thresholds: Thresholds
  counts: Partial<Record<Relation, number>>
}

export interface MatrixData {
  materials: { id: string; name: string; campaign: CampaignRef | null }[]
  p: (number | null)[][]
  distance: (number | null)[][]
  relation: (Relation | null)[][]
  thresholds: Thresholds
}

export interface TraceDetail {
  type: string
  type_label: string
  value: string
  display: string
  thumbs: string[]
  group: string
  group_label: string
  /** an identifier type (can force same campaign) */
  linking: boolean
  /** linking and df/N <= max_df */
  counted: boolean
  max_df: number
  df: number
  n: number
  materials: MaterialSummary[]
}

export interface SearchResult {
  materials: (MaterialSummary & { hits: { field: string; value: string }[] })[]
  campaigns: CampaignRef[]
  traces: { type: string; type_label: string; value: string; display: string; n: number }[]
}

export interface EvalSummary {
  n: number
  ok: number
  soft_ok: number
  acc: number
  soft_acc: number
}

export interface Methodology {
  steps: { step: number; title: string; text: string; refs: string[] }[]
  references: { id: string; text: string; url: string }[]
  identifier_groups: { group: string; label: string; hint: string; types: { type: string; label: string }[] }[]
  views: { view: string; label: string; hint: string }[]
  constants: {
    max_df: number
    phash_hamming: number
    duplicate_cut: number
    campaign_cut: number
    family_cut: number
    face_det_threshold: number
    face_min_side: number
    face_match_threshold: number
  }
  df_table: { df: number; share: number; counted: boolean }[]
  thresholds: Thresholds
  relations: { relation: Relation; label: string; hint: string }[]
  decisions: { decision: Decision; label: string; hint: string }[]
  examples: Example[]
  worked: (PairDetail & {
    item?: { label: string; group: string; group_label: string; value: string; df: number; n: number; share: number; max_df: number }
  }) | null
  evaluation: {
    file: string
    labels: Record<string, number> | null
    leave_one_out: Record<string, EvalSummary> | null
    variants: Record<string, EvalSummary> | null
  } | null
  n_materials: number
}

export interface Job<T = unknown> {
  id: string
  kind: string
  label: string
  meta: Record<string, unknown>
  status: "queued" | "running" | "done" | "error"
  progress: string[]
  result: T | null
  error: string | null
  started: number
  finished: number | null
}

export interface AnalysisResult {
  decision: Decision
  decision_label: string
  decision_hint: string
  campaign: CampaignRef | null
  /** new pattern, but the nearest campaign is within the family cut */
  similar_family: CampaignRef | null
  /** campaign of the nearest known material (1-NN by content distance d) */
  nearest: (CampaignRef & { distance: number; material_id: string; material_name: string }) | null
  closest: (CampaignRef & { score: number; distance: number }) | null
  scores: (CampaignRef & { score: number; distance: number })[]
  links: { p: number; distance: number; relation: Relation; relation_label: string; evidence: Evidence[]; other: MaterialSummary; explain: Explanation }[]
  kept: boolean
  material_id: string
  name: string
  input: { mode: "url" | "file" | "text"; source: string; use_llm: boolean; keep: boolean; render: boolean }
  features: Features
  thresholds: Thresholds
}

export interface EventView {
  ts: string
  kind: string
  label: string
  text: string
}

/** Campaign-watch seed: a counted identifier of a known campaign used as a search term in public sources. */
export interface WatchSeed {
  campaign: number
  campaign_label: string
  group: string
  group_label: string
  type: string
  type_label: string
  value: string
  df?: number
  n_members?: number
  campaign_size?: number
  sources?: string[]
  sources_label?: string[]
  cert_stem?: string | null
  note?: string | null
  /** on a hit: the source that returned it */
  source?: string
  source_label?: string
}

/** Result of the normal assignment (capture -> analyse_new -> assign) of a seed hit. */
export interface WatchOutcome {
  decision: Decision | null
  decision_label: string
  campaign?: number | null
  campaign_label?: string | null
  confirmed: boolean
  material?: string
  note?: string
}

export interface ScanItem {
  source: string
  source_label?: string
  score: number
  why: string[]
  url?: string
  domain?: string
  title?: string
  text?: string
  advertiser?: string
  name?: string
  ad_id?: string
  seed?: WatchSeed
  outcome?: WatchOutcome
  /** watch job result only: not seen in earlier scans */
  new?: boolean
}

export interface WatchResult {
  campaigns: string[]
  seeds: WatchSeed[]
  found: number
  fresh: number
  hits: ScanItem[]
  analysed: unknown[]
  confirmed: number
  errors: Record<string, string>
}

export interface ScannerStatus {
  running: boolean
  next_run: string | null
  config: { minutes: number; keywords: string[]; analyse: boolean; watch?: boolean } | null
  default_keywords: string[]
  meta_token: boolean
  found: ScanItem[]
  watch_found: ScanItem[]
  watch_last: { ts: string; campaigns: number[] | null; seeds: WatchSeed[] } | null
  events: EventView[]
}

export interface DataStatus {
  n_materials: number
  n_campaigns: number
  n_multi: number
  by_source: Record<string, number>
  last_added: string | null
  store: string
  default_dataset: string
  llm_backend: string
  llm_backend_label: string
  llm_available: { claude_cli: boolean; gemini: boolean }
  neo4j: boolean
  recent: EventView[]
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init)
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`
    try {
      const j = await r.json()
      if (j?.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail)
    } catch {
      /* not JSON */
    }
    throw new Error(msg)
  }
  return r.json() as Promise<T>
}

export const api = {
  get: <T,>(url: string) => request<T>(url),
  post: <T,>(url: string, body?: unknown) =>
    request<T>(url, {
      method: "POST",
      headers: body instanceof FormData ? undefined : { "Content-Type": "application/json" },
      body: body instanceof FormData ? body : JSON.stringify(body ?? {}),
    }),
}
