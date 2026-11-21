import { ChevronDown, ShieldAlert } from "lucide-react"
import { Fragment, useState } from "react"

import type { Explanation, FamilyScore } from "@/lib/api"
import { fmtP } from "@/lib/format"
import { HelpTip, TierBadge } from "@/components/common"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"

/** Horizontal bars: score of each evidence family (0–1). One hue; label + tier carry identity. */
export function FamilyBars({ families, compact = false }: { families: FamilyScore[]; compact?: boolean }) {
  if (!families.length) return <p className="text-sm text-muted-foreground">Brak wspólnych śladów.</p>
  return (
    <div className="space-y-3 sm:space-y-2" role="table" aria-label="Siła rodzin dowodów (0–1)">
      {families.map((f) => (
        <div key={f.family} role="row" className="grid grid-cols-[1fr_2.75rem] items-center gap-x-3 gap-y-1 text-sm sm:grid-cols-[minmax(10rem,15rem)_1fr_2.75rem]">
          <div role="cell" className="col-span-2 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 sm:col-span-1">
            <span>{f.label}</span>
            {!compact && <TierBadge tier={f.tier} />}
          </div>
          <div role="cell" className="relative h-2 rounded-full bg-muted" aria-hidden>
            <div className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${Math.max(2, f.score * 100)}%`, background: f.tier === "W" ? "var(--seq-200)" : "var(--seq-500)" }} />
          </div>
          <span role="cell" className="text-right font-medium tabular">{fmtP(f.score)}</span>
        </div>
      ))}
      <p className="pt-1 text-xs text-muted-foreground">Ciemny słupek — ślad operatora lub kit/treść; jasny — sam kontekst (słaby).</p>
    </div>
  )
}

/** Step-by-step: family scores → combination → guards → final p → relation rule. */
export function Computation({ e }: { e: Explanation }) {
  const terms = e.groups.map((g) => `(1 − ${fmtP(g.score)})`)
  const weakOnly = e.groups.length > 0 && e.groups.every((g) => g.tier === "W")
  let guardText: string
  if (e.guards.length) guardText = ""
  else if (!e.groups.length) guardText = "Nie dotyczy — brak wspólnych śladów."
  else if (weakOnly) guardText = `Są tylko słabe dowody (kontekst). Wynik ${fmtP(e.p_raw)} jest już poniżej limitu 0.45 dla samego kontekstu, więc limit nic nie zmienia.`
  else guardText = "Nie zadziałało żadne: są dowody operatora lub kit/treść, a typy oszustwa nie są sprzeczne."
  return (
    <ol className="space-y-3 text-sm">
      <StepLi n={1} title="Każda rodzina dowodów dostaje wynik 0–1">
        Dowody w rodzinie łączą się tak, że każdy kolejny niezależny dowód zmniejsza szansę „przypadkowej zgodności” — wynik rośnie, ale nigdy nie przekracza 1
        (tzw. noisy-OR). Wyniki rodzin: wykres „Siła rodzin dowodów”.
      </StepLi>
      <StepLi n={2} title="Rodziny łączą się w jedną ocenę p">
        <span className="block font-mono text-xs break-words">
          p = 1 − {terms.length ? terms.join(" × ") : "1"} = <span className="font-semibold text-foreground">{fmtP(e.p_raw)}</span>
        </span>
      </StepLi>
      <StepLi n={3} title="Zabezpieczenia">
        {e.guards.map((g) => (
          <span key={g.name} className="block">
            <span className="font-medium text-foreground">{g.label}.</span> {g.detail}
          </span>
        ))}
        {guardText && <span className="block">{guardText}</span>}
        <span className="block text-foreground">Wynik końcowy: <span className="font-semibold tabular">p = {fmtP(e.p)}</span></span>
      </StepLi>
      <StepLi n={4} title={`Relacja: ${e.relation_label}`}>{e.rule}</StepLi>
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

/** Evidence grouped by family (strongest first). Works without horizontal scroll on phones. */
export function EvidenceTable({ e }: { e: Explanation }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="space-y-4">
      <div className="overflow-hidden rounded-lg border">
        <div className="grid grid-cols-[1fr_auto] gap-3 border-b bg-muted/40 px-3 py-2 text-xs font-medium text-muted-foreground">
          <span>Dowód — co dokładnie jest wspólne</span>
          <span className="flex items-center gap-1">
            waga <HelpTip label="Co oznacza waga">Wkład pojedynczego dowodu (0–1). Dla wspólnych wartości: waga bazowa typu śladu × rzadkość wartości w bazie.</HelpTip>
          </span>
        </div>
        {e.groups.map((g) => (
          <Fragment key={g.family}>
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b bg-muted/20 px-3 py-2 text-sm">
              <span className="font-medium">{g.label}</span>
              <TierBadge tier={g.tier} />
              <span className="ml-auto text-xs text-muted-foreground tabular">wynik rodziny {fmtP(g.score)}</span>
            </div>
            {g.items.map((it, i) => (
              <EvidenceRow key={i} detail={it.detail} weight={it.weight} values={it.values} thumbs={it.thumbs} />
            ))}
          </Fragment>
        ))}
        {!e.groups.length && <p className="px-3 py-3 text-sm text-muted-foreground">Brak wspólnych śladów.</p>}
      </div>
      {e.ignored.length > 0 && (
        <Collapsible open={open} onOpenChange={setOpen}>
          <CollapsibleTrigger asChild>
            <Button variant="ghost" size="sm" className="-ml-2 h-auto text-left whitespace-normal text-muted-foreground">
              <ChevronDown className={open ? "rotate-180 transition-transform" : "transition-transform"} />
              Pominięte wspólne wartości ({e.ignored.length}) — występują w zbyt wielu materiałach, by cokolwiek znaczyć
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <ul className="mt-2 space-y-1 text-sm text-muted-foreground">
              {e.ignored.map((x, i) => (
                <li key={i} className="break-words">• {x.detail}</li>
              ))}
            </ul>
          </CollapsibleContent>
        </Collapsible>
      )}
    </div>
  )
}

function EvidenceRow({ detail, weight, values, thumbs }: { detail: string; weight: number; values?: string[]; thumbs?: string[] }) {
  const [open, setOpen] = useState(false)
  const many = (values?.length ?? 0) > 1
  return (
    <div className="grid grid-cols-[1fr_auto] gap-3 border-b px-3 py-2 text-sm last:border-b-0">
      <div className="min-w-0 space-y-1.5 break-words">
        <span>{detail}</span>
        {thumbs && thumbs.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {thumbs.slice(0, 8).map((t) => (
              <a key={t} href={t} target="_blank" rel="noreferrer"><img src={t} alt="wspólny obraz" loading="lazy" className="size-12 rounded object-cover ring-1 ring-border" /></a>
            ))}
          </div>
        )}
        {many && (
          <>
            <button type="button" className="block text-xs text-muted-foreground underline underline-offset-4" onClick={() => setOpen(!open)}>
              {open ? "ukryj wartości" : `pokaż wartości (${values!.length})`}
            </button>
            {open && (
              <ul className="space-y-0.5 font-mono text-xs text-muted-foreground">
                {values!.map((v) => <li key={v} className="break-all">{v}</li>)}
              </ul>
            )}
          </>
        )}
      </div>
      <span className="text-right tabular">{fmtP(weight)}</span>
    </div>
  )
}

export function NotComparable() {
  return (
    <Alert>
      <ShieldAlert />
      <AlertTitle>Pary nie da się w pełni porównać</AlertTitle>
      <AlertDescription>
        Materiały nie mają wspólnego rodzaju danych (np. sam zrzut ekranu vs sam zapis strony). Niski wynik nie oznacza, że to różne kampanie — po prostu brak danych.
      </AlertDescription>
    </Alert>
  )
}
