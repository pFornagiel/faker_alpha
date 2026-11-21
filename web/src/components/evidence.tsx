import { ChevronDown, ShieldAlert } from "lucide-react"
import { useState } from "react"
import { Link } from "react-router"

import type { Evidence, Explanation } from "@/lib/api"
import { fmtP, type ViewRow, viewsOf } from "@/lib/format"
import { HelpTip, traceHref } from "@/components/common"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"

/** One bar per content view, similarity 0–1. Unavailable views say so instead of showing 0. */
export function ViewBars({ views }: { views: ViewRow[] }) {
  if (!views.length) return <p className="text-sm text-muted-foreground">Brak widoku treści dostępnego po obu stronach.</p>
  return (
    <div className="space-y-3 sm:space-y-2" role="table" aria-label="Podobieństwo w widokach treści (0–1)">
      {views.map((v) => (
        <div key={v.key} role="row" className="grid grid-cols-[1fr_4.5rem] items-center gap-x-3 gap-y-1 text-sm sm:grid-cols-[minmax(9rem,13rem)_1fr_4.5rem]">
          <div role="cell" className="col-span-2 flex min-w-0 items-center gap-1.5 sm:col-span-1">
            <span>{v.label}</span>
            {v.hint && <HelpTip label={`Miara: ${v.label}`}>{v.hint}</HelpTip>}
          </div>
          <div role="cell" className="relative h-2 rounded-full bg-muted" aria-hidden>
            {v.score !== null && <div className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${Math.max(1, v.score * 100)}%`, background: "var(--seq-500)" }} />}
          </div>
          <span role="cell" className={v.score === null ? "text-right text-xs text-muted-foreground" : "text-right font-medium tabular"}>
            {v.score === null ? "brak danych" : fmtP(v.score)}
          </span>
          {v.thumbs && v.thumbs.length > 0 && (
            <div className="col-span-full flex flex-wrap gap-1.5 sm:col-start-2">
              {v.thumbs.slice(0, 8).map((t) => (
                <a key={t} href={t} target="_blank" rel="noreferrer"><img src={t} alt="wspólny obraz" loading="lazy" className="size-10 rounded object-cover ring-1 ring-border" /></a>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

/** Shared identifier values of a pair, grouped (counted ones), plus the too-common ones that were ignored. */
export function IdentifierList({ e }: { e: Explanation }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="space-y-3">
      {e.identifiers.length ? (
        <div className="overflow-hidden rounded-lg border">
          {e.identifiers.map((g) => (
            <div key={g.group} className="border-b last:border-b-0">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1 bg-muted/30 px-3 py-2 text-sm">
                <span className="font-medium">{g.label}</span>
                {g.hint && <span className="text-xs text-muted-foreground">— {g.hint}</span>}
              </div>
              {g.items.map((it) => (
                <div key={`${it.type}:${it.value}`} className="grid gap-x-3 gap-y-0.5 border-t px-3 py-2 text-sm sm:grid-cols-[12rem_1fr_auto]">
                  <span className="text-muted-foreground">{it.type_label}</span>
                  <Link to={traceHref(it.type, it.value)} className="min-w-0 font-mono text-xs break-all underline-offset-4 hover:underline">{it.display}</Link>
                  <span className="text-xs whitespace-nowrap text-muted-foreground tabular">w {it.df} z {it.n} materiałów</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">Brak wspólnego identyfikatora — o relacji decyduje odległość treści.</p>
      )}
      {e.ignored.length > 0 && (
        <Collapsible open={open} onOpenChange={setOpen}>
          <CollapsibleTrigger asChild>
            <Button variant="ghost" size="sm" className="-ml-2 h-auto text-left whitespace-normal text-muted-foreground">
              <ChevronDown className={open ? "rotate-180 transition-transform" : "transition-transform"} />
              Pominięte wspólne wartości ({e.ignored.length}) — zbyt popularne, by coś znaczyć
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <ul className="mt-2 space-y-1 text-sm text-muted-foreground">
              {e.ignored.map((x, i) => <li key={i} className="break-words">• {x.detail}</li>)}
            </ul>
          </CollapsibleContent>
        </Collapsible>
      )}
    </div>
  )
}

/** Compact evidence of a link brief: identifiers first, then one bar per available view. */
export function EvidenceBrief({ evidence }: { evidence: Evidence[] }) {
  const ids = evidence.filter((e) => e.kind === "identifier" && !e.ignored)
  const views = viewsOf(evidence)
  return (
    <div className="space-y-3">
      {ids.length > 0 && (
        <ul className="space-y-1 text-sm">
          {ids.map((e, i) => e.kind === "identifier" && (
            <li key={i} className="break-words">
              {e.key === "file_sha" ? <span>{e.label}</span> : (
                <>
                  <span className="text-muted-foreground">{e.type_label}:</span> <span className="font-mono text-xs">{e.value}</span>
                  <span className="text-xs text-muted-foreground"> · w {e.df} mat.</span>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      {views.length > 0 && <ViewBars views={views} />}
    </div>
  )
}

/** Step-by-step: identifiers → content distance (Gower) → relation rule. */
export function Computation({ e }: { e: Explanation }) {
  const nIds = e.identifiers.reduce((a, g) => a + Math.max(1, g.items.length), 0)
  return (
    <ol className="space-y-3 text-sm">
      <StepLi n={1} title="Wspólne identyfikatory">
        {e.must_link
          ? `Tak (${nIds}) — wspólny identyfikator łączy materiały w jedną kampanię niezależnie od treści (p = 1).`
          : "Brak — o relacji decyduje odległość treści."}
      </StepLi>
      <StepLi n={2} title="Odległość treści (Gower)">
        <span className="block">d = 1 − średnia podobieństw z widoków dostępnych po obu stronach ({e.n_views}); każdy widok wnosi s / {e.n_views || "k"}.</span>
        <span className="block font-mono text-xs break-words text-foreground">{e.formula}</span>
      </StepLi>
      <StepLi n={3} title={`Relacja: ${e.relation_label}`}>{e.rule}</StepLi>
    </ol>
  )
}

function StepLi({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <li className="flex gap-3">
      <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-medium">{n}</span>
      <div className="min-w-0 space-y-1">
        <p className="font-medium">{title}</p>
        <div className="space-y-1 text-muted-foreground">{children}</div>
      </div>
    </li>
  )
}

export function NotComparable() {
  return (
    <Alert>
      <ShieldAlert />
      <AlertTitle>Treści tej pary nie da się porównać</AlertTitle>
      <AlertDescription>
        Żaden widok treści nie jest dostępny po obu stronach (np. sam zrzut ekranu vs sam zapis strony), więc d = 1 oznacza brak danych, a nie różne kampanie.
      </AlertDescription>
    </Alert>
  )
}
