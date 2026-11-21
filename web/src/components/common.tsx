import { useEffect, useRef, useState, type ReactNode } from "react"
import { Link } from "react-router"
import { AlertCircle, CircleHelp, ImageOff } from "lucide-react"

import type { CampaignRef, MaterialSummary, Relation, Tier } from "@/lib/api"
import { fmtP, P_LINK, P_SIMILAR, seriesColor } from "@/lib/format"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

// ------------------------------------------------------------------ page scaffolding
export function PageHeader({ title, description, actions, children, docTitle }: {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  children?: ReactNode
  /** browser-tab title; defaults to `title` when it is a string */
  docTitle?: string
}) {
  const t = docTitle ?? (typeof title === "string" ? title : undefined)
  useEffect(() => {
    document.title = t ? `${t} · FakeTrace` : "FakeTrace"
  }, [t])
  return (
    <div className="flex flex-col gap-3 pb-2">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight break-words">{title}</h1>
          {description && <div className="max-w-3xl text-sm text-muted-foreground">{description}</div>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {children}
    </div>
  )
}

export function Section({ title, description, children, className, contentClassName, aside }: {
  title: ReactNode
  description?: ReactNode
  children: ReactNode
  className?: string
  contentClassName?: string
  /** small secondary element shown under the description (e.g. a legend) — never squeezes the title */
  aside?: ReactNode
}) {
  return (
    <Card className={cn("min-w-0", className)}>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
        {aside && <div className="pt-1">{aside}</div>}
      </CardHeader>
      <CardContent className={cn("min-w-0", contentClassName)}>{children}</CardContent>
    </Card>
  )
}

export function Loading({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-3" aria-busy="true" aria-label="Ładowanie">
      <Skeleton className="h-8 w-64" />
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-24 w-full" />
      ))}
    </div>
  )
}

export function ErrorState({ error }: { error: unknown }) {
  const msg = error instanceof Error ? error.message : String(error)
  return (
    <Alert variant="destructive">
      <AlertCircle />
      <AlertTitle>Nie udało się pobrać danych</AlertTitle>
      <AlertDescription>{msg}</AlertDescription>
    </Alert>
  )
}

/** Explanation bubble that opens on hover (desktop) AND on tap/click/keyboard (mobile, a11y). */
export function InfoPop({ trigger, children, label, className }: { trigger: ReactNode; children: ReactNode; label: string; className?: string }) {
  const [open, setOpen] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  const enter = () => {
    window.clearTimeout(timer.current)
    setOpen(true)
  }
  const leave = () => {
    timer.current = window.setTimeout(() => setOpen(false), 120)
  }
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button type="button" aria-label={label} onMouseEnter={enter} onMouseLeave={leave} className={cn("inline-flex cursor-help rounded-sm align-middle focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none", className)}>
          {trigger}
        </button>
      </PopoverTrigger>
      <PopoverContent onMouseEnter={enter} onMouseLeave={leave} onOpenAutoFocus={(e) => e.preventDefault()} className="w-72 text-sm text-pretty">
        {children}
      </PopoverContent>
    </Popover>
  )
}

export function HelpTip({ children, label = "Wyjaśnienie" }: { children: ReactNode; label?: string }) {
  return (
    <InfoPop label={label} trigger={<CircleHelp className="size-3.5 text-muted-foreground hover:text-foreground" />}>
      {children}
    </InfoPop>
  )
}

// ------------------------------------------------------------------ identity
export function CampaignDot({ c, className }: { c: CampaignRef | null | undefined; className?: string }) {
  const multi = c && c.size > 1
  return (
    <span
      aria-hidden
      className={cn("inline-block size-2.5 shrink-0 rounded-full", !multi && "ring-1 ring-inset ring-[var(--series-none)]", className)}
      style={{ background: multi ? seriesColor(c?.color) : "transparent" }}
    />
  )
}

export function CampaignBadge({ c, withName = false, link = true }: { c: CampaignRef | null | undefined; withName?: boolean; link?: boolean }) {
  if (!c) return <span className="text-xs text-muted-foreground">brak kampanii</span>
  const body = (
    <span className="inline-flex max-w-full min-w-0 items-center gap-1.5">
      <CampaignDot c={c} />
      <span className="shrink-0 font-medium tabular">{c.code}</span>
      {withName && <span className="min-w-0 truncate font-normal text-muted-foreground">{c.name}</span>}
    </span>
  )
  return link ? (
    <Link to={`/campaigns/${c.id}`} title={`${c.code} · ${c.name}`} className="inline-flex max-w-full min-w-0 rounded-sm text-sm underline-offset-4 hover:underline">
      {body}
    </Link>
  ) : (
    <span title={`${c.code} · ${c.name}`} className="inline-flex max-w-full min-w-0 text-sm">{body}</span>
  )
}

export const TIER_META: Record<Tier, { label: string; variant: "default" | "secondary" | "outline"; hint: string }> = {
  S: { label: "operator", variant: "default", hint: "Ślad operatora — praktycznie zawsze należy do jednej grupy (piksel reklamowy, domena, endpoint formularza, ID reklamy). Sam wystarcza, by połączyć materiały." },
  M: { label: "kit / treść", variant: "secondary", hint: "Ten sam zestaw narzędzi strony lub ta sama treść/kreacja. Mocny, ale może być skopiowany — łączy, gdy jest bardzo silny albo gdy są co najmniej dwa niezależne." },
  W: { label: "kontekst", variant: "outline", hint: "Zgodność kontekstu (ta sama osoba, typ oszustwa, hosting). Sam niczego nie łączy — najwyżej sugeruje podobny schemat." },
}

export function TierBadge({ tier }: { tier: Tier }) {
  const t = TIER_META[tier]
  return (
    <InfoPop label={`Siła śladu: ${t.label}`} trigger={<Badge variant={t.variant}>{t.label}</Badge>}>
      <p className="mb-1 font-medium">Siła śladu: {t.label}</p>
      {t.hint}
    </InfoPop>
  )
}

const REL_META: Record<Relation, { variant: "default" | "secondary" | "outline" | "ghost"; label: string; hint: string }> = {
  duplicate: { variant: "secondary", label: "duplikat", hint: "Ten sam materiał zgłoszony ponownie (identyczny plik albo ta sama treść, obraz i domena)." },
  same_campaign: { variant: "default", label: "ta sama kampania", hint: `p ≥ ${P_LINK} oraz dowód operatora, bardzo silny dowód kit/treść albo dwie niezależne rodziny dowodów.` },
  similar: { variant: "outline", label: "podobny playbook", hint: `p ≥ ${P_SIMILAR} albo ten sam schemat (narracja, koncepcja, wizualia, osoby) — ale bez dowodu wspólnego operatora.` },
  none: { variant: "ghost", label: "brak powiązania", hint: `p < ${P_SIMILAR} i brak wspólnego schematu.` },
}

export function RelationBadge({ relation, plain = false }: { relation: Relation; plain?: boolean }) {
  const r = REL_META[relation]
  if (plain) return <Badge variant={r.variant} title={r.hint} className={cn(relation === "none" && "text-muted-foreground")}>{r.label}</Badge>
  return (
    <InfoPop label={`Relacja: ${r.label}`} trigger={<Badge variant={r.variant} className={cn(relation === "none" && "text-muted-foreground")}>{r.label}</Badge>}>
      <p className="mb-1 font-medium">Relacja: {r.label}</p>
      {r.hint}
    </InfoPop>
  )
}

// ------------------------------------------------------------------ strength of a link
/** p as a number + a thin meter with the two decision thresholds marked. */
export function Strength({ p, className }: { p: number; className?: string }) {
  const pct = Math.max(0, Math.min(1, p)) * 100
  return (
    <div className={cn("flex items-center gap-2", className)} title={`Siła powiązania p = ${fmtP(p)} (0–1). Progi: ${P_SIMILAR} podobny playbook, ${P_LINK} ta sama kampania.`}>
      <span className="w-10 shrink-0 text-right text-sm font-medium tabular">{fmtP(p)}</span>
      <div className="relative h-1.5 w-full min-w-12 rounded-full bg-muted" role="meter" aria-label="siła powiązania" aria-valuenow={p} aria-valuemin={0} aria-valuemax={1}>
        <div className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${pct}%`, background: p >= P_LINK ? "var(--seq-500)" : p >= P_SIMILAR ? "var(--seq-300)" : "var(--seq-200)" }} />
        <span className="absolute -top-0.5 h-2.5 w-px bg-foreground/40" style={{ left: `${P_SIMILAR * 100}%` }} />
        <span className="absolute -top-0.5 h-2.5 w-px bg-foreground/70" style={{ left: `${P_LINK * 100}%` }} />
      </div>
    </div>
  )
}

export function StrengthLegend() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
      <span>Siła powiązania pary p (0–1); kreski na pasku:</span>
      <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-px bg-foreground/40" /> {P_SIMILAR} podobny playbook</span>
      <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-px bg-foreground/70" /> {P_LINK} ta sama kampania</span>
    </div>
  )
}

// ------------------------------------------------------------------ materials
export function Thumb({ src, alt, className }: { src: string | null | undefined; alt: string; className?: string }) {
  if (!src)
    return (
      <div className={cn("flex items-center justify-center rounded-md bg-muted text-muted-foreground", className)} aria-label="brak obrazu">
        <ImageOff className="size-4" />
      </div>
    )
  return <img src={src} alt={alt} loading="lazy" className={cn("rounded-md bg-muted object-cover object-top", className)} />
}

export function MaterialRow({ m, right, showCampaign = true, link = true }: { m: MaterialSummary; right?: ReactNode; showCampaign?: boolean; link?: boolean }) {
  return (
    <div className="flex min-w-0 items-center gap-3">
      <Thumb src={m.thumb} alt={`Materiał ${m.name}`} className="size-11 shrink-0" />
      <div className="min-w-0 flex-1 text-left">
        <div className="flex min-w-0 flex-wrap items-center gap-x-2">
          {link ? (
            <Link to={`/materials/${m.id}`} className="font-medium underline-offset-4 hover:underline">Materiał {m.name}</Link>
          ) : (
            <span className="font-medium">Materiał {m.name}</span>
          )}
          {showCampaign && m.campaign && (link ? <CampaignBadge c={m.campaign} /> : <CampaignBadge c={m.campaign} link={false} />)}
        </div>
        <p className="truncate text-xs text-muted-foreground">{m.title || m.domains.join(", ") || "—"}</p>
      </div>
      {right}
    </div>
  )
}

export function KV({ label, children, hint }: { label: ReactNode; children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-x-3 gap-y-0.5 py-1.5 text-sm sm:grid-cols-[minmax(7rem,11rem)_1fr]">
      <dt className="text-muted-foreground">
        {label} {hint && <HelpTip label={`Wyjaśnienie: ${typeof label === "string" ? label : ""}`}>{hint}</HelpTip>}
      </dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  )
}

/** Short tokens as chips; anything sentence-like becomes a wrapping list (chips would clip it). */
export function Chips({ values, empty = "—", max = 12 }: { values: (string | null | undefined)[]; empty?: string; max?: number }) {
  const v = values.filter(Boolean) as string[]
  if (!v.length) return <span className="text-muted-foreground">{empty}</span>
  if (v.some((x) => x.length > 40))
    return (
      <ul className="list-disc space-y-0.5 pl-4">
        {v.slice(0, max).map((x) => <li key={x}>{x}</li>)}
        {v.length > max && <li className="list-none text-xs text-muted-foreground">+{v.length - max} więcej</li>}
      </ul>
    )
  return (
    <div className="flex min-w-0 flex-wrap gap-1">
      {v.slice(0, max).map((x) => (
        <Badge key={x} variant="secondary" className="max-w-full justify-start font-normal" title={x}>
          <span className="truncate">{x}</span>
        </Badge>
      ))}
      {v.length > max && <span className="text-xs text-muted-foreground">+{v.length - max} więcej</span>}
    </div>
  )
}

export function Stat({ label, value, hint, to }: { label: string; value: ReactNode; hint?: string; to?: string }) {
  const body = (
    <Card size="sm" className={cn("h-full", to && "transition-colors hover:bg-muted/50")}>
      <CardContent className="space-y-1">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="text-2xl font-semibold">{value}</p>
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  )
  if (!to) return body
  return to.startsWith("#") ? <a href={to} className="block">{body}</a> : <Link to={to} className="block">{body}</Link>
}

export function traceHref(type: string, value: string): string {
  return `/trace?type=${encodeURIComponent(type)}&value=${encodeURIComponent(value)}`
}
