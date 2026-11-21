import { ArrowRight, Check } from "lucide-react"
import { Link, useParams } from "react-router"

import type { CampaignDetail, MaterialSummary, MatrixRow } from "@/lib/api"
import { FAMILY_CUT, fmtP, matLabel, useApi } from "@/lib/format"
import { CampaignViewProfileChart } from "@/components/charts"
import { CampaignBadge, CampaignDot, ErrorState, GroupBadge, Loading, PageHeader, Section, Stats, Strength, Thumb, traceHref } from "@/components/common"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

export default function CampaignPage() {
  const { id } = useParams()
  const { data: c, error, isLoading } = useApi<CampaignDetail>(`/api/campaigns/${id}`)
  if (isLoading) return <Loading />
  if (error || !c) return <ErrorState error={error} />
  const byId = new Map(c.members.map((m) => [m.id, m]))
  const single = c.size === 1
  const linked = c.links.filter((l) => l.relation !== "none").length

  return (
    <>
      <PageHeader
        docTitle={`${c.code} · ${c.name}`}
        title={
          <span className="flex min-w-0 items-center gap-3">
            <CampaignDot c={c} className="size-3.5" />
            <span className="min-w-0">{c.code} · {c.name}</span>
          </span>
        }
        description={[
          c.scam_types.map((s) => s.label).join(", "),
          c.persons.length ? `podszywa się pod: ${c.persons.slice(0, 3).join(", ")}` : null,
          c.date_range.length ? `aktywna ${c.date_range[0]} → ${c.date_range[1]}` : null,
        ].filter(Boolean).join(" · ") || undefined}
      />

      {!single && (
        <Stats
          items={[
            { label: "Materiały", value: c.size },
            { label: "Pary połączone bezpośrednio", value: `${linked} z ${c.n_pairs}` },
            { label: "Średnia bliskość par p", value: fmtP(c.mean_internal_p) },
            { label: "Wspólne wartości śladów", value: c.n_shared },
          ]}
        />
      )}

      <section className="space-y-3">
        <h2 className="text-lg font-medium">{single ? "Materiał" : "Materiały"}</h2>
        <ul className="grid grid-cols-[repeat(auto-fill,minmax(8.5rem,1fr))] gap-4">
          {c.members.map((m) => <MemberTile key={m.id} m={m} />)}
        </ul>
      </section>

      {!single && (
        <Section
          title="Co łączy materiały"
          description="Wartości obecne w co najmniej dwóch materiałach kampanii. Ciemna etykieta = identyfikator, który sam łączy materiały; jasna = ślad pomocniczy. Kliknij wartość, aby zobaczyć wszystkie materiały, które ją mają."
          contentClassName="px-0"
        >
          <EvidenceMatrix c={c} byId={byId} />
        </Section>
      )}

      {!single && (
        <div className="grid items-start gap-5 xl:grid-cols-2">
          {c.view_profile && c.view_profile.length > 0 && (
            <Section
              title="W czym materiały są do siebie podobne"
              description="Średnie podobieństwo (0–1) w każdym widoku treści: między materiałami kampanii i między nimi a resztą bazy. Duża przewaga pierwszego słupka = cecha, która wyróżnia tę kampanię."
            >
              <CampaignViewProfileChart profile={c.view_profile} />
            </Section>
          )}
          <Section
            title="Jak kampania się trzyma"
            description="Najmniejszy zestaw najsilniejszych par, który spina wszystkie materiały. Pozostałe pary łączą się pośrednio."
          >
            <ul className="divide-y">
              {c.chain.map((s) => (
                <li key={`${s.a}-${s.b}`} className="grid gap-x-4 gap-y-1.5 py-3 first:pt-0 sm:grid-cols-[minmax(0,1fr)_11rem]">
                  <div className="min-w-0 space-y-1">
                    <Link to={`/pair/${s.a}/${s.b}`} className="inline-flex flex-wrap items-center gap-2 font-medium hover:underline">
                      Materiał {s.a_name} ↔ {s.b_name}
                      <Badge variant={s.basis === "wspólny identyfikator" || s.basis === "duplikat" ? "default" : "secondary"}>{s.basis}</Badge>
                    </Link>
                    {s.reasons[0] && <p className="line-clamp-2 text-sm break-words text-muted-foreground">{s.reasons[0]}</p>}
                  </div>
                  <Strength p={s.p} distance={s.distance} />
                </li>
              ))}
            </ul>
          </Section>
        </div>
      )}

      <Section
        title="Najbliżej, ale poza kampanią"
        description={`Materiały z podobną treścią (d ≤ ${c.thresholds?.family_cut ?? FAMILY_CUT}), które nie dołączyły: brakuje im wspólnego identyfikatora i treść jest za daleko.`}
      >
        {c.nearest_outside.length ? (
          <ul className="divide-y">
            {c.nearest_outside.map((l) => {
              const out = l.a === l.inside ? l.b_info : l.a_info
              return (
                <li key={`${l.a}-${l.b}`} className="grid items-center gap-x-4 gap-y-1.5 py-3 first:pt-0 sm:grid-cols-[minmax(0,1fr)_11rem_auto]">
                  <span className="inline-flex flex-wrap items-center gap-2">
                    Materiał {matLabel(byId.get(l.inside))} ↔ Materiał {out?.name} <CampaignBadge c={l.outside_campaign} />
                  </span>
                  <Strength p={l.p} distance={l.distance} />
                  <Link to={`/pair/${l.a}/${l.b}`} className="inline-flex items-center gap-1 text-sm hover:underline">Porównaj <ArrowRight className="size-3.5" /></Link>
                </li>
              )
            })}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">Żaden materiał spoza kampanii nie ma podobnej treści.</p>
        )}
        {c.siblings.length > 0 && (
          <p className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1 border-t pt-3 text-sm">
            <span className="text-muted-foreground">Ta sama rodzina (podobna treść, inna infrastruktura):</span>
            {c.siblings.map((s) => <CampaignBadge key={s.id} c={s} withName />)}
          </p>
        )}
      </Section>
    </>
  )
}

function MemberTile({ m }: { m: MaterialSummary }) {
  return (
    <li>
      <Link to={`/materials/${m.id}`} className="group block min-w-0" title={m.title}>
        <Thumb src={m.thumb} alt={`Materiał ${matLabel(m)}`} className="aspect-[6/7] w-full ring-1 ring-border group-hover:ring-foreground/40" />
        <span className="mt-1.5 block truncate text-sm font-medium group-hover:underline">Materiał {matLabel(m)}</span>
        <span className="block truncate text-xs text-muted-foreground">{m.domains[0] ?? m.source_label}</span>
      </Link>
    </li>
  )
}

function TraceValue({ r }: { r: MatrixRow }) {
  if (r.type === "asset_phash") {
    return (
      <div className="flex flex-wrap gap-1.5">
        {r.thumbs.slice(0, 6).map((t) => <img key={t} src={t} alt="wspólny obraz" loading="lazy" className="size-10 rounded object-cover ring-1 ring-border" />)}
        {r.values.length > 6 && <span className="self-center text-xs text-muted-foreground">+{r.values.length - 6}</span>}
      </div>
    )
  }
  const first = r.values[0]
  return (
    <span className="flex min-w-0 items-baseline gap-2">
      <Link to={traceHref(r.type, first.value)} className="min-w-0 truncate font-mono text-xs hover:underline" title={first.display}>{first.display}</Link>
      {r.values.length > 1 && <span className="shrink-0 text-xs text-muted-foreground" title={r.values.map((v) => v.display).join("\n")}>+{r.values.length - 1}</span>}
    </span>
  )
}

function EvidenceMatrix({ c, byId }: { c: CampaignDetail; byId: Map<string, MaterialSummary> }) {
  return (
    <>
      <div className="hidden overflow-x-auto md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-48 pl-6">Ślad</TableHead>
              <TableHead>Wspólna wartość</TableHead>
              {c.members.map((m) => (
                <TableHead key={m.id} className="w-16 text-center">
                  <Link to={`/materials/${m.id}`} className="hover:underline" title={`Materiał ${m.name}`}>{matLabel(m)}</Link>
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {c.matrix.map((r) => (
              <TableRow key={`${r.type}:${r.members.join()}:${r.values[0].value}`}>
                <TableCell className="pl-6">
                  <div className="flex flex-col items-start gap-1">
                    <GroupBadge label={r.group_label} linking={r.linking} />
                    <span className="text-xs text-muted-foreground">{r.type_label}</span>
                  </div>
                </TableCell>
                <TableCell className="max-w-md"><TraceValue r={r} /></TableCell>
                {c.members.map((m) => (
                  <TableCell key={m.id} className="text-center">
                    {r.members.includes(m.id) ? <Check className="mx-auto size-4 text-primary" aria-label="występuje" /> : <span className="text-muted-foreground/40" aria-label="brak">·</span>}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <ul className="divide-y border-t md:hidden">
        {c.matrix.map((r) => (
          <li key={`${r.type}:${r.members.join()}:${r.values[0].value}`} className="space-y-1.5 px-4 py-3">
            <span className="text-xs text-muted-foreground">{r.type_label}</span>
            <TraceValue r={r} />
            <p className="text-xs">w materiałach: <span className="font-medium">{r.members.map((m) => matLabel(byId.get(m))).join(", ")}</span></p>
          </li>
        ))}
      </ul>
      {!c.matrix.length && <p className="px-6 text-sm text-muted-foreground">Materiały nie mają wspólnych wartości — łączy je tylko bliska treść.</p>}
    </>
  )
}

