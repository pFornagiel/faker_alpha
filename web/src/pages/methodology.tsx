import { ArrowRight } from "lucide-react"
import type { ReactNode } from "react"
import { Link } from "react-router"

import type { Methodology } from "@/lib/api"
import { fmtP, useApi, viewsOfExplanation } from "@/lib/format"
import { ErrorState, Loading, PageHeader, RelationBadge } from "@/components/common"
import { Computation, IdentifierList, ViewBars } from "@/components/evidence"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"

const TOC = [
  ["skrot", "W skrócie"],
  ["kroki", "Metoda krok po kroku"],
  ["identyfikatory", "Identyfikatory"],
  ["widoki", "Widoki treści"],
  ["przyklad", "Przykład krok po kroku"],
  ["progi", "Relacje i decyzje"],
  ["przyklady", "Przykłady w danych"],
  ["ewaluacja", "Ewaluacja"],
  ["stale", "Stałe"],
  ["ograniczenia", "Ograniczenia"],
  ["literatura", "Literatura"],
] as const

const VARIANT_PL: Record<string, string> = {
  creative_only: "tylko kreacja (strona docelowa „martwa”)",
  landing_only: "tylko strona docelowa (brak kreacji)",
  recompressed: "zrzut przycięty i przekompresowany",
  domain_swap: "podmieniona domena i usunięte ID w URL",
  person_swap: "podmienione nazwisko celebryty w tekście",
}

const pct = (x: number) => `${Math.round(x * 100)}%`

export default function MethodologyPage({ embedded = false }: { embedded?: boolean }) {
  const { data: m, error, isLoading } = useApi<Methodology>("/api/methodology")
  if (isLoading) return <Loading />
  if (error || !m) return <ErrorState error={error} />
  const c = m.constants
  const refNo = new Map(m.references.map((r, i) => [r.id, i + 1]))
  return (
    <div className="space-y-6">
      {!embedded && (
        <PageHeader
          title="Metodyka"
          description="Jak FakeTrace łączy pojedyncze podejrzane reklamy w kampanie. Każda miara jest standardowa i cytowalna; liczby na tej stronie pochodzą z bieżącej konfiguracji (ftf/config.py) i bieżącej bazy."
        />
      )}
      <nav className="-mx-4 overflow-x-auto px-4 lg:hidden" aria-label="Spis treści">
        <ul className="flex gap-2 pb-1 text-sm whitespace-nowrap">
          {TOC.map(([id, label]) => <li key={id}><a href={`#${id}`} className="block rounded-full border px-3 py-1 text-muted-foreground">{label}</a></li>)}
        </ul>
      </nav>
      <div className="grid gap-8 lg:grid-cols-[13rem_1fr]">
        <nav className="hidden lg:block" aria-label="Spis treści">
          <ul className="sticky top-20 space-y-1 text-sm">
            {TOC.map(([id, label]) => (
              <li key={id}><a href={`#${id}`} className="block rounded px-2 py-1 text-muted-foreground hover:bg-muted hover:text-foreground">{label}</a></li>
            ))}
          </ul>
        </nav>

        <div className="min-w-0 space-y-10">
          <Block id="skrot" title="W skrócie">
            <ul className="list-disc space-y-2 pl-5">
              <li><b>Nie oceniamy, czy pojedyncza reklama jest fałszywa</b> — szukamy, co łączy reklamy ze sobą.</li>
              <li>
                <b>Wspólny identyfikator</b> (domena, piksel / ID analityki, kontakt, plik lub szablon kitu, ID reklamy, nazwa produktu) łączy dwa materiały
                w jedną kampanię — o ile wartość występuje w co najwyżej {pct(c.max_df)} materiałów.
              </li>
              <li>
                Bez identyfikatora decyduje <b>odległość treści d</b> = 1 − średnia podobieństw w widokach ({m.views.map((v) => v.label).join(", ")}).
              </li>
              <li>
                Grupowanie hierarchiczne (średnie wiązanie): <b>kampanie</b> = cięcie na d = {c.campaign_cut}, <b>rodziny</b> podobnych kampanii = cięcie na d = {c.family_cut}.
              </li>
              <li>Osoby, typ oszustwa, rejestrator czy IP są <b>tylko opisem</b> — nigdy nie łączą materiałów.</li>
            </ul>
          </Block>

          <Block id="kroki" title="Metoda krok po kroku">
            <Steps>
              {m.steps.map((s) => (
                <StepItem key={s.step} title={`${s.step}. ${s.title}`}>
                  <p>{s.text}{s.refs.length > 0 && <Cite ids={s.refs} refNo={refNo} />}</p>
                </StepItem>
              ))}
            </Steps>
          </Block>

          <Block id="identyfikatory" title="Identyfikatory (połączenie pewne)">
            <p>
              Ta sama wartość jednego z poniższych typów w dwóch materiałach łączy je w jedną kampanię (must-link). Wartość liczy się tylko, jeśli występuje w co
              najwyżej {pct(c.max_df)} materiałów (idea IDF) — zbyt popularne wartości są pokazywane w uzasadnieniu jako pominięte.
            </p>
            <div className="divide-y rounded-lg border">
              {m.identifier_groups.map((g) => (
                <div key={g.group} className="grid gap-1 p-3 sm:grid-cols-[11rem_1fr] sm:gap-3">
                  <span className="font-medium">{g.label}</span>
                  <span className="space-y-1">
                    <span className="block text-muted-foreground">{g.hint}</span>
                    <span className="flex flex-wrap gap-1">{g.types.map((t) => <Badge key={t.type} variant="secondary" className="font-normal">{t.label}</Badge>)}</span>
                  </span>
                </div>
              ))}
              <div className="grid gap-1 p-3 sm:grid-cols-[11rem_1fr] sm:gap-3">
                <span className="font-medium">identyczny plik</span>
                <span className="text-muted-foreground">ten sam plik (sha256) — duplikat</span>
              </div>
            </div>
            <p>Dla bieżącej bazy (N = {m.n_materials}):</p>
            <SimpleTable
              head={["wartość w ilu materiałach (df)", "udział df / N", "liczy się?"]}
              rows={m.df_table.map((r) => [String(r.df), pct(r.share), r.counted ? "tak" : "nie — zbyt popularna"])}
            />
          </Block>

          <Block id="widoki" title="Widoki treści (odległość d)">
            <p>
              Każdy widok ma jedną standardową miarę podobieństwa w [0, 1]. Odległość to współczynnik Gowera: <b>d = 1 − średnia z widoków dostępnych po obu stronach</b>.
              Widok niedostępny po jednej stronie jest pomijany (a nie liczony jako 0), więc każdy z k dostępnych widoków wnosi dokładnie s / k. Gdy żaden widok nie jest
              dostępny, d = 1 i para jest oznaczana jako nieporównywalna.
            </p>
            <div className="divide-y rounded-lg border">
              {m.views.map((v) => (
                <div key={v.view} className="grid gap-1 p-3 sm:grid-cols-[11rem_1fr] sm:gap-3">
                  <span className="font-medium">{v.label}</span>
                  <span className="text-muted-foreground">{v.hint}</span>
                </div>
              ))}
            </div>
          </Block>

          {m.worked && (
            <Block id="przyklad" title="Przykład krok po kroku">
              <p>
                Para <Link to={`/pair/${m.worked.a.id}/${m.worked.b.id}`} className="font-medium underline underline-offset-4">materiał {m.worked.a.name} ↔ materiał {m.worked.b.name}</Link> z bieżącej bazy.
                {m.worked.item && (
                  <> {m.worked.item.label} <span className="font-mono text-xs">{m.worked.item.value}</span> występuje w {m.worked.item.df} z {m.worked.item.n} materiałów
                    ({pct(m.worked.item.share)} ≤ {pct(m.worked.item.max_df)}), więc się liczy.</>
                )}
              </p>
              <Card size="sm"><CardContent className="space-y-2"><p className="text-sm font-medium">Wspólne identyfikatory</p><IdentifierList e={m.worked} /></CardContent></Card>
              <div className="grid items-start gap-4 lg:grid-cols-2">
                <Card size="sm"><CardContent className="space-y-3"><p className="text-sm font-medium">Podobieństwo treści</p><ViewBars views={viewsOfExplanation(m.worked)} /></CardContent></Card>
                <Card size="sm"><CardContent><Computation e={m.worked} /></CardContent></Card>
              </div>
              <p>
                <Link to={`/pair/${m.worked.a.id}/${m.worked.b.id}`} className="inline-flex items-center gap-1 font-medium underline underline-offset-4">
                  Zobacz pełne uzasadnienie tej pary <ArrowRight className="size-3.5" />
                </Link>
              </p>
            </Block>
          )}

          <Block id="progi" title="Relacje i decyzje">
            <ThresholdScale dup={c.duplicate_cut} campaign={c.campaign_cut} family={c.family_cut} />
            <div className="divide-y rounded-lg border">
              {m.relations.map((r) => (
                <div key={r.relation} className="grid gap-1 p-3 sm:grid-cols-[11rem_1fr] sm:gap-3">
                  <span><RelationBadge relation={r.relation} /></span>
                  <span>{r.hint}</span>
                </div>
              ))}
            </div>
            <p>Nowy materiał (zbiór otwarty) dostaje jedną z decyzji:</p>
            <div className="divide-y rounded-lg border">
              {m.decisions.map((d) => (
                <div key={d.decision} className="grid gap-1 p-3 sm:grid-cols-[11rem_1fr] sm:gap-3"><span className="font-medium">{d.label}</span><span>{d.hint}</span></div>
              ))}
            </div>
            <p>
              <Link to="/analyse" className="inline-flex items-center gap-1 font-medium underline underline-offset-4">Przeanalizuj nowy materiał <ArrowRight className="size-3.5" /></Link>
            </p>
          </Block>

          <Block id="przyklady" title="Przykłady w danych">
            <p>Każdy przykład ilustruje jedną zasadę na materiałach z bieżącej bazy ({m.n_materials} materiałów).</p>
            <div className="grid gap-3 md:grid-cols-2">
              {m.examples.map((e) => (
                <Link key={e.to} to={e.to} className="group">
                  <Card size="sm" className="h-full transition-colors group-hover:bg-muted/50">
                    <CardContent className="space-y-1">
                      <Badge variant="outline">{e.concept}</Badge>
                      <p className="flex items-center gap-1 font-medium underline-offset-4 group-hover:underline">{e.title} <ArrowRight className="size-3.5" /></p>
                      <p className="text-sm text-muted-foreground">{e.text}</p>
                    </CardContent>
                  </Card>
                </Link>
              ))}
            </div>
          </Block>

          <Block id="ewaluacja" title="Ewaluacja">
            {m.evaluation ? (
              <>
                <p>
                  Organizator nie dostarczył etykiet kampanii, więc stosujemy testy zgodne z planem testów wyzwania. Raport: <code className="text-xs">{m.evaluation.file}</code>.
                </p>
                <div className="divide-y rounded-lg border">
                  {m.evaluation.leave_one_out && Object.entries(m.evaluation.leave_one_out).map(([k, v]) => (
                    <EvalRow key={`loo-${k}`} test="Usuń i przypisz ponownie" what={k === "known_campaign" ? "materiał z kampanii, usunięty z bazy i analizowany od nowa, wraca do swojej kampanii" : "pojedynczy materiał, usunięty i analizowany od nowa, jest rozpoznany jako nowy wzorzec"} result={`${v.ok}/${v.n}`} />
                  ))}
                  {m.evaluation.variants && Object.entries(m.evaluation.variants).map(([k, v]) => (
                    <EvalRow key={`v-${k}`} test="Sztuczny wariant" what={`${VARIANT_PL[k] ?? k} → powinien trafić do kampanii źródłowej`} result={`${v.ok}/${v.n}${v.soft_ok !== v.ok ? ` (${v.soft_ok}/${v.n} licząc propozycję scalenia)` : ""}`} />
                  ))}
                  {m.evaluation.labels && (
                    <EvalRow
                      test="Etykiety referencyjne"
                      what={`zgodność z przynależnością ustaloną ręcznie przez autorów na podstawie surowych plików (data/labels_dane.csv — nie etykiety organizatora)${m.evaluation.labels.ARI_hdbscan_baseline !== undefined ? `; punkt odniesienia HDBSCAN: ARI ${fmtP(m.evaluation.labels.ARI_hdbscan_baseline)}` : ""}`}
                      result={[
                        m.evaluation.labels.pairwise_f1 !== undefined && `F1 par ${fmtP(m.evaluation.labels.pairwise_f1)}`,
                        m.evaluation.labels.bcubed_precision !== undefined && `B-cubed P/R ${fmtP(m.evaluation.labels.bcubed_precision)}/${fmtP(m.evaluation.labels.bcubed_recall)}`,
                        m.evaluation.labels.ARI !== undefined && `ARI ${fmtP(m.evaluation.labels.ARI)}`,
                      ].filter(Boolean).join(" · ")}
                    />
                  )}
                </div>
                <p className="text-muted-foreground">
                  F1 par — trafność decyzji „ta sama kampania / nie” dla każdej pary; B-cubed — precyzja i kompletność kampanii z perspektywy każdego materiału; ARI —
                  zgodność całego podziału (1 = identyczny). Zbiór jest mały ({m.n_materials} przypadków), więc wyniki traktujemy jako test poprawności, nie miarę skuteczności w skali.
                  <Cite ids={["hubert1985", "amigo2009"]} refNo={refNo} />
                </p>
              </>
            ) : (
              <p className="text-muted-foreground">Brak raportu — uruchom <code>python tools/evaluate.py</code>.</p>
            )}
          </Block>

          <Block id="stale" title="Stałe">
            <p>Cała metoda ma kilka stałych (ftf/config.py):</p>
            <SimpleTable
              head={["stała", "wartość"]}
              rows={[
                ["maks. udział materiałów z wartością identyfikatora (MAX_DF)", pct(c.max_df)],
                ["próg duplikatu (d ≤ DUPLICATE_CUT)", String(c.duplicate_cut)],
                ["cięcie kampanii (CAMPAIGN_CUT)", String(c.campaign_cut)],
                ["cięcie rodziny (FAMILY_CUT)", String(c.family_cut)],
                ["obrazy: maks. odległość Hamminga pHash", String(c.phash_hamming)],
                ["twarze: min. wynik detektora / min. bok twarzy (px)", `${c.face_det_threshold} / ${c.face_min_side}`],
                ["twarze: próg dopasowania do galerii (ArcFace)", String(c.face_match_threshold)],
              ]}
            />
          </Block>

          <Block id="ograniczenia" title="Ograniczenia">
            <ul className="list-disc space-y-1.5 pl-5">
              <li><b>Mały zbiór</b>: cięcia {c.campaign_cut} / {c.family_cut} i MAX_DF sprawdzono na {m.n_materials} materiałach — przy większej bazie warto je ponownie zweryfikować.</li>
              <li><b>Ukrywanie treści (cloaking)</b>: część stron pokazuje oszustwo tylko polskim użytkownikom mobilnym przychodzącym z reklamy — zapisujemy to, co zobaczył nasz klient, i profil, który to zobaczył.</li>
              <li><b>Osoby nie łączą</b>: ten sam celebryta pojawia się w wielu niezależnych kampaniach, dlatego rozpoznane twarze i nazwiska są tylko opisem.</li>
              <li><b>Licencje</b>: wagi modelu rozpoznawania twarzy (InsightFace) — tylko do badań niekomercyjnych; pozostałe modele MIT / Apache-2.0.</li>
            </ul>
          </Block>

          <Block id="literatura" title="Literatura">
            <ol className="list-decimal space-y-1 pl-6">
              {m.references.map((r) => (
                <li key={r.id} id={`ref-${r.id}`} className="scroll-mt-20">
                  {r.text}. <a href={r.url} target="_blank" rel="noreferrer" className="break-all text-muted-foreground underline underline-offset-4">{r.url}</a>
                </li>
              ))}
            </ol>
          </Block>
        </div>
      </div>
    </div>
  )
}

function Cite({ ids, refNo }: { ids: string[]; refNo: Map<string, number> }) {
  const known = ids.filter((id) => refNo.has(id))
  if (!known.length) return null
  return (
    <span className="text-xs text-muted-foreground">
      {" "}[{known.map((id, i) => (
        <span key={id}>{i > 0 && ", "}<a href={`#ref-${id}`} className="underline-offset-2 hover:underline">{refNo.get(id)}</a></span>
      ))}]
    </span>
  )
}

function Block({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-20 space-y-3 text-sm leading-relaxed">
      <h2 className="text-lg font-semibold">{title}</h2>
      {children}
    </section>
  )
}

function Steps({ children }: { children: ReactNode }) {
  return <ol className="space-y-5 border-l pl-5">{children}</ol>
}

function StepItem({ title, children }: { title: string; children: ReactNode }) {
  return (
    <li className="relative space-y-1.5">
      <span className="absolute top-1.5 -left-[25px] size-2 rounded-full bg-foreground" />
      <p className="font-medium">{title}</p>
      <div className="space-y-2 text-muted-foreground">{children}</div>
    </li>
  )
}

function SimpleTable({ head, rows }: { head: string[]; rows: string[][] }) {
  const cols = `1fr repeat(${head.length - 1}, minmax(4.5rem, auto))`
  return (
    <div className="overflow-hidden rounded-md border text-sm">
      <div className="grid gap-2 bg-muted/50 px-3 py-1.5 text-xs font-medium text-muted-foreground" style={{ gridTemplateColumns: cols }}>
        {head.map((h, i) => <span key={h} className={i ? "text-right" : ""}>{h}</span>)}
      </div>
      {rows.map((r, i) => (
        <div key={i} className="grid gap-2 border-t px-3 py-1.5" style={{ gridTemplateColumns: cols }}>
          {r.map((x, j) => <span key={j} className={j ? "text-right tabular" : "text-foreground"}>{x}</span>)}
        </div>
      ))}
    </div>
  )
}

function EvalRow({ test, what, result }: { test: string; what: string; result: string }) {
  return (
    <div className="grid gap-1 p-3 sm:grid-cols-[11rem_1fr_auto] sm:gap-3">
      <span className="font-medium">{test}</span>
      <span>{what}</span>
      <span className="font-medium tabular sm:text-right">{result}</span>
    </div>
  )
}

/** Distance scale d ∈ [0, 1] with the duplicate / campaign / family cuts (no shared identifier). */
function ThresholdScale({ dup, campaign, family }: { dup: number; campaign: number; family: number }) {
  const bands = [
    { from: 0, to: dup, label: "", bg: "var(--seq-700)" },
    { from: dup, to: campaign, label: "ta sama kampania", bg: "var(--seq-500)", ink: "#fff" },
    { from: campaign, to: family, label: "podobna treść", bg: "var(--seq-200)" },
    { from: family, to: 1, label: "brak", bg: "var(--seq-0)" },
  ]
  return (
    <div className="space-y-1" role="img" aria-label={`Skala odległości treści d: do ${dup} duplikat, do ${campaign} ta sama kampania, do ${family} podobna treść, powyżej brak powiązania`}>
      <div className="flex h-9 overflow-hidden rounded-md text-xs font-medium">
        {bands.map((b, i) => (
          <div key={i} className="flex items-center justify-center px-1 text-center leading-tight" style={{ width: `${(b.to - b.from) * 100}%`, background: b.bg, color: b.ink ?? "#0b0b0b" }}>{b.label}</div>
        ))}
      </div>
      <div className="relative h-4 text-xs text-muted-foreground tabular">
        <span className="absolute left-0">d = 0</span>
        <span className="absolute -translate-x-1/2" style={{ left: `${campaign * 100}%` }}>{campaign}</span>
        <span className="absolute -translate-x-1/2" style={{ left: `${family * 100}%` }}>{family}</span>
        <span className="absolute right-0">1</span>
      </div>
      <p className="text-xs text-muted-foreground">
        Skala dotyczy par bez wspólnego identyfikatora; d ≤ {dup} — duplikat (ciemny pasek przy 0). Wspólny identyfikator oznacza tę samą kampanię niezależnie od d.
      </p>
    </div>
  )
}
