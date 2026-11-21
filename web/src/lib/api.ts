// Typed client for the FakeTrace API (ftf/api.py).

export type Tier = "S" | "M" | "W"
export type Relation = "duplicate" | "same_campaign" | "similar" | "none"
export type Decision = "duplicate" | "known_campaign" | "merge_proposal" | "candidate_review" | "new_campaign"

export interface CampaignRef {
  id: number
  code: string
  name: string
  size: number
  color: number | null
}

export interface MaterialSummary {
  id: string
  name: string
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
}

export interface FamilyScore {
  family: string
  label: string
  tier: Tier
  score: number
}

export interface Reason {
  detail: string
  weight: number
  family: string
}

export interface LinkBrief {
  a: string
  b: string
  p: number
  relation: Relation
  relation_label: string
  families: FamilyScore[]
  reasons: Reason[]
  comparable: boolean
  other?: MaterialSummary
  a_info?: { id: string; name: string; campaign: CampaignRef | null }
  b_info?: { id: string; name: string; campaign: CampaignRef | null }
}

export interface SharedTrace {
  type: string
  type_label: string
  tier: Tier
  value: string
  display: string
  n_values: number
  count: number
}

export interface CampaignCard extends CampaignRef {
  members: MaterialSummary[]
  scam_types: { value: string; label: string; n: number }[]
  narratives: { value: string; label: string; n: number }[]
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

export interface Overview {
  n_materials: number
  n_campaigns: number
  n_multi: number
  n_singletons: number
  n_in_multi: number
  n_duplicate_groups: number
  links: Record<Relation, number>
  families: { id: number; campaigns: number[]; refs: CampaignRef[]; size: number }[]
  campaigns: CampaignCard[]
}

export interface MatrixRow {
  type: string
  type_label: string
  values: { value: string; display: string }[]
  thumbs: string[]
  family: string
  family_label: string
  tier: Tier
  members: string[]
}

export interface ChainStep {
  a: string
  b: string
  a_name: string
  b_name: string
  p: number
  relation: Relation
  basis: string
  reasons: string[]
}

export interface CampaignDetail extends CampaignCard {
  matrix: MatrixRow[]
  chain: ChainStep[]
  links: LinkBrief[]
  nearest_outside: (LinkBrief & { inside: string; outside_campaign: CampaignRef | null })[]
  siblings: CampaignRef[]
  variants: string[][]
  titles: string[]
  n_pairs: number
}

export interface IndicatorGroup {
  family: string
  label: string
  tier: Tier
  hint: string
  items: { type: string; type_label: string; values: { value: string; display: string; df: number; thumb: string | null }[]; more: number }[]
}

export interface Features {
  summary: string | null
  llm_backend: string | null
  llm_backend_label: string | null
  llm: { key: string; label: string; value: string | string[]; discovered?: boolean }[]
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

export interface EvidenceItem {
  signal: string
  signal_label: string
  detail: string
  value: string
  weight: number
  values?: string[]
  thumbs?: string[]
}

export interface Explanation {
  p: number
  p_raw: number
  relation: Relation
  relation_label: string
  relation_hint: string
  rule: string
  basis: string
  weak_only: boolean
  playbook: number
  comparable: boolean
  groups: { family: string; label: string; tier: Tier; tier_label: string; hint: string; score: number; items: EvidenceItem[] }[]
  ignored: { detail: string; signal: string; family: string }[]
  guards: { name: string; label: string; detail: string }[]
  strongest_operator: number
  strongest_sm: number
  n_independent: number
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
  tier?: Tier
  n?: number
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  kind: "link" | "trace"
  p?: number
  relation?: Relation
  relation_label?: string
  reasons?: Reason[]
  families?: FamilyScore[]
  same_campaign_box?: boolean
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
  thresholds: { link: number; similar: number }
  counts: Partial<Record<Relation, number>>
}

export interface MatrixData {
  materials: { id: string; name: string; campaign: CampaignRef | null }[]
  p: (number | null)[][]
  relation: (Relation | null)[][]
  thresholds: { link: number; similar: number }
}

export interface TraceDetail {
  type: string
  type_label: string
  value: string
  display: string
  thumbs: string[]
  family: string
  family_label: string
  tier: Tier
  prior: number | null
  rarity: number
  hub: boolean
  weight: number | null
  df: number
  n: number
  materials: MaterialSummary[]
}

export interface SearchResult {
  materials: (MaterialSummary & { hits: { field: string; value: string }[] })[]
  campaigns: CampaignRef[]
  traces: { type: string; type_label: string; value: string; display: string; n: number }[]
}

export interface Example {
  kind: "campaign" | "pair"
  to: string
  title: string
  concept: string
  text: string
}

export interface Methodology {
  tiers: { tier: Tier; label: string; hint: string }[]
  families: {
    family: string
    label: string
    tier: Tier
    hint: string
    indicators: { type: string; label: string; weight: number }[]
    continuous: { name: string; lo: number; hi: number; max_weight: number }[]
  }[]
  thresholds: {
    link: number
    similar: number
    duplicate: number
    assign: number
    candidate: number
    weak_cap: number
    hub_fraction: number
    hub_min: number
    core_s: number
    strong_merge: number
    single_assign: number
    conflict: number
    playbook: number
    family_merge: number
  }
  rarity_table: { df: number; rarity: number; mult: number; hub?: boolean }[]
  relations: { relation: Relation; label: string; hint: string }[]
  decisions: { decision: Decision; label: string; hint: string }[]
  examples: Example[]
  worked: (PairDetail & { item?: { label: string; value: string; prior: number; df: number; n: number; rarity: number; weight: number; family: string } }) | null
  evaluation: {
    file: string
    labels: Record<string, number> | null
    leave_one_out: Record<string, { n: number; ok: number; soft_ok: number; acc: number; soft_acc: number }> | null
    variants: Record<string, { n: number; ok: number; soft_ok: number; acc: number; soft_acc: number }> | null
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
  similar_playbook: CampaignRef | null
  closest: (CampaignRef & { score: number }) | null
  scores: (CampaignRef & { score: number })[]
  links: { p: number; relation: Relation; relation_label: string; families: FamilyScore[]; other: MaterialSummary; explain: Explanation }[]
  kept: boolean
  material_id: string
  name: string
  input: { mode: "url" | "file" | "text"; source: string; use_llm: boolean; keep: boolean; render: boolean }
  features: Features
  thresholds: { assign: number; candidate: number; similar: number; link: number }
}

export interface EventView {
  ts: string
  kind: string
  label: string
  text: string
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
}

export interface ScannerStatus {
  running: boolean
  next_run: string | null
  config: { minutes: number; keywords: string[]; analyse: boolean } | null
  default_keywords: string[]
  meta_token: boolean
  found: ScanItem[]
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
