import { ArrowRight, Lightbulb } from "lucide-react"
import { Link } from "react-router"

import type { CampaignCard, CampaignRef, Example, Overview } from "@/lib/api"
import { plural, useApi } from "@/lib/format"
import {
  CampaignBadge, CampaignDot, Chips, ErrorState, HelpTip, Loading, PageHeader, Stat, Thumb, TierBadge, traceHref,
} from "@/components/common"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

export default function OverviewPage() {
  const { data, error, isLoading } = useApi<Overview & { examples: Example[] }>("/api/overview")
  if (isLoading) return <Loading />
  if (error || !data) return <ErrorState error={error} />
  if (!data.n_materials)
    return (
      <Empty className="border">
        <EmptyHeader>
          <EmptyTitle>Baza jest pusta</EmptyTitle>
          <EmptyDescription>Wczytaj zbiór przypadków albo przeanalizuj pierwszy materiał.</EmptyDescription>
        </EmptyHeader>
        <div className="flex gap-2">
          <Button asChild><Link to="/data">Wczytaj zbiór</Link></Button>
          <Button asChild variant="outline"><Link to="/analyse">Analizuj materiał</Link></Button>
        </div>
      </Empty>
    )

  const multi = data.campaigns.filter((c) => c.size > 1)
  const singles = data.campaigns.filter((c) => c.size === 1)
  const familyOf = new Map<number, CampaignRef[]>()
  for (const f of data.families) for (const c of f.campaigns) familyOf.set(c, f.refs.filter((r) => r.id !== c))

  return (
    <>
      <PageHeader
        title="Przegląd kampanii"
        description="Każdy materiał (reklama, strona docelowa, nagranie) jest porównywany z każdym innym. Materiały, które łączą wspólne ślady operatora — ten sam piksel reklamowy, domena, backend strony, obraz — tworzą kampanię. Każde powiązanie ma uzasadnienie."
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Materiały w bazie" value={data.n_materials} hint="zgłoszenia i przechwycenia →" to="/materials" />
        <Stat label="Kampanie" value={data.n_campaigns} hint={`${data.n_multi} wielomateriałowe · ${data.n_singletons} jednomateriałowe →`} to="#kampanie" />
        <Stat label="Pary „ta sama kampania”" value={data.links.same_campaign} hint="powiązania z dowodem →" to="/links?rel=same_campaign,duplicate" />
        <Stat label="Pary „podobny playbook”" value={data.links.similar} hint="ten sam schemat, inny operator →" to="/links?rel=similar" />
      </div>

      {data.examples.length > 0 && <Examples examples={data.examples} />}

      <section id="kampanie" className="scroll-mt-20 space-y-3">
        <div>
          <h2 className="text-lg font-semibold">Kampanie wielomateriałowe</h2>
          <p className="text-sm text-muted-foreground">Materiały połączone śladami operatora. Posortowane według liczby materiałów.</p>
        </div>
        {multi.length ? (
          <div className={multi.length > 1 ? "grid gap-4 lg:grid-cols-2" : "grid gap-4"}>
            {multi.map((c) => <CampaignCardView key={c.id} c={c} />)}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Brak kampanii z więcej niż jednym materiałem.</p>
        )}
      </section>

      {singles.length > 0 && (
        <section className="space-y-3">
          <div>
            <h2 className="text-lg font-semibold">Kampanie jednomateriałowe</h2>
            <p className="text-sm text-muted-foreground">
              Materiały bez wspólnych śladów operatora z resztą bazy — każdy to osobna kampania (nowy wzorzec). Kolumna „Podobny playbook” wskazuje kampanie o tym
              samym schemacie oszustwa, ale bez dowodu wspólnej infrastruktury.
            </p>
          </div>
          {/* desktop: table */}
          <Card className="hidden py-0 md:flex">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-20 pl-4">Kampania</TableHead>
                  <TableHead>Materiał</TableHead>
                  <TableHead>Typ oszustwa</TableHead>
                  <TableHead>Osoby</TableHead>
                  <TableHead>
                    <span className="inline-flex items-center gap-1">Podobny playbook <HelpTip label="Co to jest podobny playbook">Kampanie z tą samą narracją, koncepcją, wizualiami lub osobami, ale bez wspólnych śladów operatora. Ten sam „przepis na oszustwo”, możliwie inny wykonawca.</HelpTip></span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {singles.map((c) => {
                  const m = c.members[0]
                  return (
                    <TableRow key={c.id}>
                      <TableCell className="pl-4"><CampaignBadge c={c} /></TableCell>
                      <TableCell className="max-w-80">
                        <Link to={`/materials/${m.id}`} className="flex min-w-0 items-center gap-3 underline-offset-4 hover:underline">
                          <Thumb src={m.thumb} alt="" className="size-9 shrink-0" />
                          <span className="min-w-0">
                            <span className="block font-medium">Materiał {m.name}</span>
                            <span className="block truncate text-xs text-muted-foreground" title={m.product || m.title}>{m.product || m.title}</span>
                          </span>
                        </Link>
                      </TableCell>
                      <TableCell className="whitespace-normal">{m.scam_type_label ?? "—"}</TableCell>
                      <TableCell className="max-w-56 text-sm whitespace-normal">{m.persons.slice(0, 3).join(", ") || "—"}</TableCell>
                      <TableCell><Siblings refs={familyOf.get(c.id) ?? []} /></TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </Card>
          {/* mobile: cards */}
          <div className="space-y-2 md:hidden">
            {singles.map((c) => {
              const m = c.members[0]
              return (
                <Card key={c.id} size="sm">
                  <CardContent className="space-y-2">
                    <Link to={`/materials/${m.id}`} className="flex min-w-0 items-center gap-3">
                      <Thumb src={m.thumb} alt="" className="size-11 shrink-0" />
                      <span className="min-w-0">
                        <span className="block font-medium">Materiał {m.name} <span className="font-normal text-muted-foreground">· {c.code}</span></span>
                        <span className="block truncate text-xs text-muted-foreground">{m.product || m.title}</span>
                      </span>
                    </Link>
                    <p className="text-sm">{m.scam_type_label ?? "—"}{m.persons.length > 0 && <span className="text-muted-foreground"> · {m.persons.slice(0, 2).join(", ")}</span>}</p>
                    {(familyOf.get(c.id) ?? []).length > 0 && (
                      <p className="flex flex-wrap items-center gap-2 text-sm"><span className="text-muted-foreground">Podobny playbook:</span> <Siblings refs={familyOf.get(c.id) ?? []} /></p>
                    )}
                  </CardContent>
                </Card>
              )
            })}
          </div>
        </section>
      )}
    </>
  )
}

function Siblings({ refs }: { refs: CampaignRef[] }) {
  if (!refs.length) return <span className="text-muted-foreground">—</span>
  return (
    <span className="inline-flex flex-wrap gap-2">
      {refs.map((r) => <CampaignBadge key={r.id} c={r} />)}
    </span>
  )
}

function Examples({ examples }: { examples: Example[] }) {
  return (
    <Card className="bg-muted/40">
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Lightbulb className="size-4" /> Od czego zacząć — przykłady z tej bazy</CardTitle>
        <CardDescription>Każdy link pokazuje jedną zasadę metody na prawdziwych danych. Pełny opis: <Link to="/methodology" className="underline underline-offset-4">Metodyka</Link>.</CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="grid gap-x-6 gap-y-4 md:grid-cols-2 xl:grid-cols-3">
          {examples.map((e) => (
            <li key={e.to}>
              <Link to={e.to} className="group block rounded-md">
                <div className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{e.concept}</div>
                <div className="flex items-center gap-1 font-medium underline-offset-4 group-hover:underline">
                  {e.title} <ArrowRight className="size-3.5 shrink-0" />
                </div>
                <p className="text-sm text-muted-foreground">{e.text}</p>
              </Link>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}

function CampaignCardView({ c }: { c: CampaignCard }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex min-w-0 items-start gap-2">
          <CampaignDot c={c} className="mt-1.5 size-3" />
          <Link to={`/campaigns/${c.id}`} className="min-w-0 break-words underline-offset-4 hover:underline">
            {c.code} · {c.name}
          </Link>
        </CardTitle>
        <CardDescription className="flex flex-wrap gap-1.5">
          <Badge variant="secondary">{plural(c.size, "materiał", "materiały", "materiałów")}</Badge>
          {c.scam_types.map((s) => <Badge key={s.value} variant="outline">{s.label}</Badge>)}
          {c.date_range.length > 0 && <Badge variant="outline">aktywna: {c.date_range[0]} → {c.date_range[1]}</Badge>}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex gap-2 overflow-x-auto pb-1">
          {c.members.map((m) => (
            <Link key={m.id} to={`/materials/${m.id}`} className="group shrink-0 text-center" title={`Materiał ${m.name}: ${m.title}`}>
              <Thumb src={m.thumb} alt={`Materiał ${m.name}`} className="h-20 w-16 ring-1 ring-border group-hover:ring-foreground/40" />
              <span className="mt-1 block text-xs font-medium">mat. {m.name}</span>
            </Link>
          ))}
        </div>
        <div>
          <p className="mb-2 text-sm font-medium">
            Dlaczego razem <span className="font-normal text-muted-foreground">— najmocniejsze wspólne ślady ({c.n_shared} wspólnych wartości łącznie)</span>
          </p>
          <ul className="space-y-1.5">
            {c.top_shared.map((s) => (
              <li key={`${s.type}:${s.value}`} className="grid grid-cols-[auto_1fr] items-center gap-x-2 gap-y-0.5 text-sm sm:grid-cols-[auto_1fr_auto]">
                <TierBadge tier={s.tier} />
                <Link to={traceHref(s.type, s.value)} className="min-w-0 truncate underline-offset-4 hover:underline" title={s.display}>
                  <span className="text-muted-foreground">{s.type_label}:</span>{" "}
                  {s.type === "asset_phash" ? <span>{s.n_values} {s.n_values === 1 ? "obraz" : "obrazów"}</span> : <span className="font-mono text-xs">{s.display}</span>}
                  {s.n_values > 1 && s.type !== "asset_phash" && <span className="text-muted-foreground"> +{s.n_values - 1}</span>}
                </Link>
                <span className="col-start-2 text-xs whitespace-nowrap text-muted-foreground tabular sm:col-start-auto">w {s.count} z {c.size} mat.</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="space-y-1 text-sm">
          <span className="text-muted-foreground">Wykorzystane osoby:</span>
          <Chips values={c.persons} max={6} />
        </div>
      </CardContent>
      <CardFooter className="border-t">
        <Button asChild variant="link" className="h-auto px-0">
          <Link to={`/campaigns/${c.id}`}>Pełne uzasadnienie kampanii <ArrowRight /></Link>
        </Button>
      </CardFooter>
    </Card>
  )
}
