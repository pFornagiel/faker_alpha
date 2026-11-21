import { ArrowRight, ChevronRight } from "lucide-react"
import type { ReactNode } from "react"
import { Link } from "react-router"

import type { Methodology } from "@/lib/api"
import { fmtP, useApi } from "@/lib/format"
import { ErrorState, Loading, PageHeader, RelationBadge, TierBadge } from "@/components/common"
import { Computation, FamilyBars } from "@/components/evidence"
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"

const TOC = [
  ["skrot", "W skrócie"],
  ["przebieg", "Przebieg analizy"],
  ["poziomy", "Siła śladów: 3 poziomy"],
  ["rodziny", "Rodziny dowodów i wagi"],
  ["p", "Jak liczymy siłę powiązania p"],
  ["przyklad", "Przykład krok po kroku"],
  ["progi", "Relacje i progi"],
  ["grupowanie", "Grupowanie w kampanie"],
  ["decyzja", "Nowy materiał: decyzja"],
  ["przyklady", "Przykłady w danych"],
  ["ewaluacja", "Ewaluacja"],
  ["ograniczenia", "Ograniczenia"],
] as const

const CONT_PL: Record<string, string> = {
  text_minhash: "prawie identyczny tekst (MinHash)",
  masked_minhash: "ten sam tekst po zamaskowaniu nazwisk",
  title_template: "ten sam szablon tytułu",
  text_embedding: "podobna narracja (model e5)",
  clip: "podobny wygląd kreacji (model CLIP)",
  dinov2: "podobny układ graficzny (model DINOv2)",
  phash: "prawie identyczny obraz (pHash)",
  dom_template: "ten sam szablon HTML strony",
  face_unknown: "ta sama nieznana twarz (ArcFace)",
}

const VARIANT_PL: Record<string, string> = {
  creative_only: "tylko kreacja (strona docelowa „martwa”)",
  landing_only: "tylko strona docelowa (brak kreacji)",
  recompressed: "zrzut przycięty i przekompresowany",
  domain_swap: "podmieniona domena i usunięte ID w URL",
  person_swap: "podmienione nazwisko celebryty w tekście",
}

export default function MethodologyPage() {
  const { data: m, error, isLoading } = useApi<Methodology>("/api/methodology")
  if (isLoading) return <Loading />
  if (error || !m) return <ErrorState error={error} />
  const t = m.thresholds

  return (
    <>
      <PageHeader
        title="Metodyka"
        description="Jak FakeTrace zamienia pojedyncze podejrzane reklamy w kampanie i jak ocenić, czy danemu powiązaniu można ufać. Liczby na tej stronie są odczytywane z bieżącej konfiguracji (ftf/config.py, progi w kodzie) i z bieżącej bazy."
      />
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
              <li>Z każdego materiału wyciągamy <b>ślady</b>: techniczne (piksele reklamowe, domeny, backend strony), wizualne (kreacja, twarze), tekstowe (narracja, frazy) i opisowe (typ oszustwa rozpoznany przez model językowy).</li>
              <li>Dla każdej pary materiałów liczymy <b>siłę powiązania p</b> (0–1) z listą dowodów. <b>Rzadkie</b> wspólne wartości ważą dużo, popularne — mało albo nic.</li>
              <li>
                Materiały połączone <b>śladem operatora</b> albo kilkoma niezależnymi śladami <b>kit/treść</b> tworzą <b>kampanię</b>. Ten sam schemat oszustwa bez wspólnej
                infrastruktury to tylko <b>podobny playbook</b> (rodzina kampanii).
              </li>
              <li>Nowy materiał trafia do znanej kampanii, do weryfikacji przez analityka albo jest oznaczany jako <b>nowy wzorzec</b>.</li>
            </ul>
          </Block>

          <Block id="przebieg" title="Przebieg analizy">
            <div className="grid gap-3 md:grid-cols-5">
              {[
                ["1. Wejście", "Adres URL (pobierany jak przez 3 różnych użytkowników, by wykryć ukrywanie treści), zrzut, wideo, zapis strony, ZIP, tekst, biblioteki reklam."],
                ["2. Ślady", "Infrastruktura strony, obrazy (podobieństwo, OCR), twarze, tekst, atrybuty z modelu językowego."],
                ["3. Pary", "Każda para materiałów → dowody pogrupowane w rodziny → siła powiązania p z uzasadnieniem."],
                ["4. Grupowanie", "Duplikaty → kampanie (wspólny operator) → rodziny (ten sam schemat)."],
                ["5. Decyzja", "Nowy materiał: duplikat / znana kampania / do weryfikacji / nowy wzorzec."],
              ].map(([h, d], i, arr) => (
                <div key={h} className="relative">
                  <Card size="sm" className="h-full">
                    <CardContent className="space-y-1">
                      <p className="font-medium">{h}</p>
                      <p className="text-xs text-muted-foreground">{d}</p>
                    </CardContent>
                  </Card>
                  {i < arr.length - 1 && <ChevronRight className="absolute top-1/2 -right-3 z-10 hidden size-4 -translate-y-1/2 text-muted-foreground md:block" />}
                </div>
              ))}
            </div>
          </Block>

          <Block id="poziomy" title="Siła śladów: 3 poziomy">
            <p>Każdy rodzaj śladu ma przypisany poziom. Poziom decyduje, czy ślad może sam połączyć materiały w kampanię.</p>
            <div className="grid gap-3 md:grid-cols-3">
              {m.tiers.map((x) => (
                <Card key={x.tier} size="sm">
                  <CardContent className="space-y-2">
                    <TierBadge tier={x.tier} />
                    <p className="text-sm">{x.hint}.</p>
                  </CardContent>
                </Card>
              ))}
            </div>
          </Block>

          <Block id="rodziny" title="Rodziny dowodów i wagi">
            <p>
              Ślady są pogrupowane w rodziny. <b>Waga bazowa</b> to ocena ekspercka: jak mocno wspólna, <i>rzadka</i> wartość tego typu wskazuje na tego samego operatora
              (0–1). Rozwiń rodzinę, aby zobaczyć wszystkie typy śladów i ich wagi.
            </p>
            <Accordion type="multiple" className="rounded-lg border px-4">
              {m.families.map((f) => (
                <AccordionItem key={f.family} value={f.family}>
                  <AccordionTrigger className="hover:no-underline">
                    <span className="grid min-w-0 flex-1 gap-1 text-left sm:grid-cols-[11rem_7rem_1fr] sm:items-center sm:gap-3">
                      <span className="font-medium">{f.label}</span>
                      <span><TierBadge tier={f.tier} /></span>
                      <span className="text-sm font-normal text-muted-foreground">{f.hint}</span>
                    </span>
                  </AccordionTrigger>
                  <AccordionContent className="space-y-3">
                    {f.indicators.length > 0 && (
                      <WeightTable head={["Wspólna wartość / zgodność", "Waga bazowa"]} rows={f.indicators.map((i) => [i.label, fmtP(i.weight)])} />
                    )}
                    {f.continuous.length > 0 && (
                      <>
                        <p className="text-xs text-muted-foreground">Podobieństwa ciągłe: poniżej progu „od” nie liczą się wcale, powyżej progu „do” dają pełną wagę, pomiędzy — proporcjonalnie.</p>
                        <WeightTable head={["Podobieństwo", "od", "do", "waga max"]} rows={f.continuous.map((c) => [CONT_PL[c.name] ?? c.name, fmtP(c.lo), fmtP(c.hi), fmtP(c.max_weight)])} />
                      </>
                    )}
                  </AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
          </Block>

          <Block id="p" title="Jak liczymy siłę powiązania p">
            <Steps>
              <StepItem title="1. Rzadkość wspólnej wartości">
                <Formula>rzadkość = log(N / df) / log(N / 2)</Formula>
                <p>
                  N — liczba materiałów w bazie, df — w ilu z nich występuje dana wartość. Wartość obecna tylko w 2 materiałach ma rzadkość 1. Im częstsza, tym rzadkość
                  mniejsza. Wartości obecne w ponad {Math.round(t.hub_fraction * 100)}% materiałów (i w co najmniej {t.hub_min}) to <b>huby</b> — pomijane i pokazywane
                  jako „zbyt popularne” (np. Cloudflare, popularny celebryta). Zasada jak w klasycznym łączeniu rekordów (Fellegi–Sunter): zgodność na rzadkiej wartości
                  jest mocnym dowodem, na pospolitej — prawie żadnym.
                </p>
                <p>Dla bieżącej bazy (N = {m.n_materials}):</p>
                <WeightTable
                  head={["wartość w ilu materiałach (df)", "rzadkość", "mnożnik wagi"]}
                  rows={m.rarity_table.map((r) => [r.hub ? `${r.df}+ (hub)` : String(r.df), fmtP(r.rarity), r.hub ? "0 — pomijana" : `× ${fmtP(r.mult)}`])}
                />
              </StepItem>
              <StepItem title="2. Waga pojedynczego dowodu">
                <Formula>waga = waga bazowa × (0.35 + 0.65 × rzadkość)</Formula>
                <p>Nawet częsta (ale nie „hubowa”) wartość zachowuje 35% wagi bazowej. Podobieństwa ciągłe (tekst, obraz) zamieniane są na wagę według progów z tabeli rodzin.</p>
              </StepItem>
              <StepItem title="3. Łączenie dowodów">
                <Formula>{"wynik rodziny = 1 − (1 − waga₁) × (1 − waga₂) × …\np = 1 − (1 − wynik rodziny₁) × (1 − wynik rodziny₂) × …"}</Formula>
                <p>
                  Każdy niezależny dowód zmniejsza szansę, że zgodność jest przypadkowa (tzw. noisy-OR). Dwa dowody po 0.5 dają 0.75, a nie 1.0; wynik nigdy nie przekracza 1.
                </p>
              </StepItem>
              <StepItem title="4. Zabezpieczenia">
                <ul className="list-disc space-y-1 pl-5">
                  <li>Tylko słabe rodziny (osoby, koncepcja, hosting) → p ≤ <b>{t.weak_cap}</b>. Sam celebryta niczego nie łączy.</li>
                  <li>Sprzeczny typ oszustwa bez śladu operatora → p × <b>{t.conflict}</b>.</li>
                  <li>Pary, których nie da się porównać (brak wspólnego rodzaju danych, np. sam zrzut vs sam zapis strony), nie zaniżają średnich przy grupowaniu.</li>
                </ul>
              </StepItem>
            </Steps>
          </Block>

          {m.worked && (
            <Block id="przyklad" title="Przykład krok po kroku">
              <p>
                Para <Link to={`/pair/${m.worked.a.id}/${m.worked.b.id}`} className="font-medium underline underline-offset-4">materiał {m.worked.a.name} ↔ materiał {m.worked.b.name}</Link> z bieżącej bazy.
              </p>
              {m.worked.item && (
                <Card size="sm">
                  <CardContent className="space-y-1 text-sm">
                    <p className="font-medium">Waga jednego dowodu (krok 1–2)</p>
                    <p className="text-muted-foreground">
                      {m.worked.item.label}: <span className="font-mono text-xs text-foreground">{m.worked.item.value}</span> — występuje w {m.worked.item.df} z {m.worked.item.n} materiałów.
                    </p>
                    <p className="font-mono text-xs break-words">
                      rzadkość = log({m.worked.item.n}/{m.worked.item.df}) / log({m.worked.item.n}/2) = {fmtP(m.worked.item.rarity)}; waga = {fmtP(m.worked.item.prior)} × (0.35 + 0.65 × {fmtP(m.worked.item.rarity)}) = <b>{fmtP(m.worked.item.weight)}</b>
                    </p>
                  </CardContent>
                </Card>
              )}
              <div className="grid items-start gap-4 lg:grid-cols-2">
                <Card size="sm"><CardContent><p className="mb-3 text-sm font-medium">Wyniki rodzin (krok 3)</p><FamilyBars families={m.worked.groups.map((g) => ({ family: g.family, label: g.label, tier: g.tier, score: g.score }))} /></CardContent></Card>
                <Card size="sm"><CardContent><Computation e={m.worked} /></CardContent></Card>
              </div>
              <p>
                <Link to={`/pair/${m.worked.a.id}/${m.worked.b.id}`} className="inline-flex items-center gap-1 font-medium underline underline-offset-4">
                  Zobacz wszystkie dowody tej pary <ArrowRight className="size-3.5" />
                </Link>
              </p>
            </Block>
          )}

          <Block id="progi" title="Relacje i progi">
            <ThresholdScale similar={t.similar} link={t.link} />
            <div className="divide-y rounded-lg border">
              {m.relations.map((r) => (
                <div key={r.relation} className="grid gap-1 p-3 sm:grid-cols-[11rem_1fr] sm:gap-3">
                  <span><RelationBadge relation={r.relation} /></span>
                  <span>{r.hint}</span>
                </div>
              ))}
            </div>
            <p className="text-muted-foreground">
              Sam wynik p ≥ {t.link} nie wystarcza do „tej samej kampanii” — potrzebny jest też ślad operatora (≥ 0.5), bardzo silny ślad kit/treść (≥ 0.7) albo dwie
              niezależne rodziny śladów (≥ 0.3). Dzięki temu dwie reklamy z tym samym celebrytą i tą samą narracją pozostają osobno.
            </p>
          </Block>

          <Block id="grupowanie" title="Grupowanie w kampanie">
            <Steps>
              <StepItem title="Poziom 0 — duplikaty">Materiały z relacją „duplikat” są scalane (to samo zgłoszenie wysłane wiele razy).</StepItem>
              <StepItem title="Poziom 1 — kampanie">
                Najpierw <b>rdzenie</b>: materiały połączone śladem operatora o wyniku ≥ {t.core_s}. Potem rdzenie są łączone, jeśli <b>średnia</b> siła powiązań między
                nimi (tylko z par, które da się porównać) wynosi ≥ {t.link}, albo jeśli istnieje pojedyncze bardzo silne powiązanie (p ≥ {t.strong_merge}). Średnia, a nie
                najsilniejsza para, zapobiega „sklejaniu łańcuchem” — jedna przypadkowa para nie łączy dwóch kampanii.
              </StepItem>
              <StepItem title="Poziom 2 — rodziny (podobny playbook)">
                Kampanie podobne wyłącznie narracją, koncepcją, wizualiami lub osobami (średnio ≥ {t.family_merge}). Raportowane osobno — ten sam przepis na oszustwo, możliwie inny operator.
              </StepItem>
              <StepItem title="Kontrola">Dla porównania liczony jest też standardowy algorytm grupowania HDBSCAN na odległości 1 − p (punkt odniesienia w ewaluacji).</StepItem>
            </Steps>
          </Block>

          <Block id="decyzja" title="Nowy materiał: decyzja">
            <p>
              Wynik kampanii = średnia z dwóch najsilniejszych powiązań nowego materiału z materiałami tej kampanii. Pojedyncze powiązanie ≥ {t.single_assign} wystarcza do
              przypisania; pojedyncze {t.assign}–{t.single_assign} daje co najmniej „do weryfikacji”.
            </p>
            <div className="divide-y rounded-lg border">
              {[
                ["Duplikat", "istnieje powiązanie „duplikat”"],
                ["Znana kampania", `wynik kampanii ≥ ${t.assign}`],
                ["Propozycja scalenia", `dwie kampanie mają wynik ≥ ${t.assign}`],
                ["Do weryfikacji", `wynik ${t.candidate}–${t.assign} i jest ślad operatora, kit lub treści (nie tylko zgodność koncepcji)`],
                ["Nowy wzorzec", `wynik < ${t.candidate} albo tylko wspólny schemat — wtedy wskazujemy kampanię o podobnym playbooku`],
              ].map(([d, w]) => (
                <div key={d} className="grid gap-1 p-3 sm:grid-cols-[11rem_1fr] sm:gap-3"><span className="font-medium">{d}</span><span>{w}</span></div>
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
                    <EvalRow key={`v-${k}`} test="Sztuczny wariant" what={`${VARIANT_PL[k] ?? k} → powinien trafić do kampanii źródłowej`} result={`${v.ok}/${v.n}${v.soft_ok !== v.ok ? ` (${v.soft_ok}/${v.n} licząc „do weryfikacji”)` : ""}`} />
                  ))}
                  {m.evaluation.labels && (
                    <EvalRow
                      test="Etykiety referencyjne"
                      what={`zgodność z przynależnością ustaloną ręcznie przez autorów na podstawie surowych plików (data/labels_dane.csv — nie etykiety organizatora); punkt odniesienia HDBSCAN: ${fmtP(m.evaluation.labels.ARI_hdbscan_baseline)}`}
                      result={`F1 par ${fmtP(m.evaluation.labels.pairwise_f1)} · ARI ${fmtP(m.evaluation.labels.ARI)}`}
                    />
                  )}
                </div>
                <p className="text-muted-foreground">
                  F1 par — trafność decyzji „ta sama kampania / nie” dla każdej pary; ARI — zgodność całego podziału na kampanie (1 = identyczny). Zbiór jest mały (10 przypadków),
                  więc wyniki traktujemy jako test poprawności, nie miarę skuteczności w skali.
                </p>
              </>
            ) : (
              <p className="text-muted-foreground">Brak raportu — uruchom <code>python tools/evaluate.py</code>.</p>
            )}
          </Block>

          <Block id="ograniczenia" title="Ograniczenia">
            <ul className="list-disc space-y-1.5 pl-5">
              <li><b>Ukrywanie treści (cloaking)</b>: część stron pokazuje oszustwo tylko polskim użytkownikom mobilnym przychodzącym z reklamy — zapisujemy to, co zobaczył nasz klient, i profil, który to zobaczył.</li>
              <li><b>Wagi są ocenami eksperckimi</b>. Z etykietami można je dopasować regresją logistyczną bez utraty czytelności uzasadnień.</li>
              <li><b>Detektory deepfake / tekstu AI nie są werdyktem</b> (słaba skuteczność na danych z sieci); rozpoznana twarz + narracja oszustwa + niezwiązana domena to pewniejszy sygnał podszycia.</li>
              <li><b>Licencje</b>: wagi modelu rozpoznawania twarzy (InsightFace) — tylko do badań niekomercyjnych; pozostałe modele MIT / Apache-2.0.</li>
            </ul>
          </Block>
        </div>
      </div>
    </>
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

function Formula({ children }: { children: ReactNode }) {
  return <div className="overflow-x-auto rounded-md bg-muted px-3 py-2 font-mono text-xs whitespace-pre text-foreground">{children}</div>
}

function WeightTable({ head, rows }: { head: string[]; rows: string[][] }) {
  return (
    <div className="overflow-hidden rounded-md border text-sm">
      <div className="grid gap-2 bg-muted/50 px-3 py-1.5 text-xs font-medium text-muted-foreground" style={{ gridTemplateColumns: `1fr repeat(${head.length - 1}, minmax(3.5rem, auto))` }}>
        {head.map((h, i) => <span key={h} className={i ? "text-right" : ""}>{h}</span>)}
      </div>
      {rows.map((r, i) => (
        <div key={i} className="grid gap-2 border-t px-3 py-1.5" style={{ gridTemplateColumns: `1fr repeat(${head.length - 1}, minmax(3.5rem, auto))` }}>
          {r.map((c, j) => <span key={j} className={j ? "text-right tabular" : "text-foreground"}>{c}</span>)}
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

function ThresholdScale({ similar, link }: { similar: number; link: number }) {
  const bands = [
    { from: 0, to: similar, label: "brak powiązania", bg: "var(--seq-0)" },
    { from: similar, to: link, label: "podobny playbook", bg: "var(--seq-300)" },
    { from: link, to: 1, label: "ta sama kampania*", bg: "var(--seq-500)", ink: "#fff" },
  ]
  return (
    <div className="space-y-1" role="img" aria-label={`Skala p: poniżej ${similar} brak, ${similar}–${link} podobny playbook, od ${link} ta sama kampania (z dodatkowym warunkiem)`}>
      <div className="flex h-9 overflow-hidden rounded-md text-xs font-medium">
        {bands.map((b) => (
          <div key={b.label} className="flex items-center justify-center px-1 text-center leading-tight" style={{ width: `${(b.to - b.from) * 100}%`, background: b.bg, color: b.ink ?? "#0b0b0b" }}>{b.label}</div>
        ))}
      </div>
      <div className="relative h-4 text-xs text-muted-foreground tabular">
        <span className="absolute left-0">0</span>
        <span className="absolute -translate-x-1/2" style={{ left: `${similar * 100}%` }}>{similar}</span>
        <span className="absolute -translate-x-1/2" style={{ left: `${link * 100}%` }}>{link}</span>
        <span className="absolute right-0">1</span>
      </div>
      <p className="text-xs text-muted-foreground">* przy spełnieniu dodatkowego warunku opisanego poniżej.</p>
    </div>
  )
}
