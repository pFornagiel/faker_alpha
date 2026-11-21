import { AlertTriangle, Check, Minus } from "lucide-react"
import { Link } from "react-router"

import type { Features, IndicatorGroup } from "@/lib/api"
import { plural } from "@/lib/format"
import { Chips, KV, Section, traceHref } from "@/components/common"
import { Badge } from "@/components/ui/badge"

/** What each content view asks, in plain words; the technical method stays underneath. */
const VIEW_PLAIN: Record<string, string> = {
  text: "Czy strony docelowe mają ten sam tekst. Oszuści kopiują artykuł-przynętę i podmieniają tylko nazwiska, więc nazwiska są maskowane.",
  ocr: "Czy kreacje (reklama, zrzut ekranu, klatka wideo) mają ten sam napis.",
  semantic: "Czy teksty mówią o tym samym, nawet innymi słowami.",
  html: "Czy strona jest zbudowana z tego samego szablonu: ten sam układ znaczników HTML, niezależnie od treści.",
  images: "Czy na stronach są te same obrazy (logo, zdjęcia, banery), również po przeskalowaniu.",
}

/**
 * Everything the model knows about one material, in the order it uses it:
 * identifiers (link on their own) → content views (make up the distance d) → description (never links).
 */
export function FeatureSections({ f }: { f: Features }) {
  const linking = f.indicators.filter((g) => g.linking)
  const descriptive = f.indicators.filter((g) => !g.linking && g.group !== "images")
  const nViews = f.views.filter((v) => v.available).length

  return (
    <>
      <Section
        title="Identyfikatory"
        description={`Wartości techniczne wyciągnięte ze strony, ruchu sieciowego i adresów. Ta sama rzadka wartość w dwóch materiałach łączy je w kampanię niezależnie od treści. Liczba przy wartości mówi, w ilu z ${f.n_corpus} materiałów bazy występuje; kliknij ją, aby zobaczyć te materiały.`}
      >
        {linking.length ? (
          <div className="divide-y">
            {linking.map((g) => <IndicatorBlock key={g.group} g={g} nCorpus={f.n_corpus} />)}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            Brak identyfikatorów. Tak bywa, gdy materiał to sama kreacja bez zapisu strony docelowej — wtedy łączy go tylko podobna treść.
          </p>
        )}
      </Section>

      <Section
        title="Widoki treści"
        description={`Pięć niezależnych porównań treści. Odległość treści d dwóch materiałów to 1 − średnia podobieństw z widoków dostępnych w obu (ten materiał ma ${nViews} z 5). Brakujący widok nie obniża wyniku — jest pomijany.`}
      >
        <ul className="divide-y">
          {f.views.map((v) => (
            <li key={v.view} className="grid gap-x-6 gap-y-1 py-3 first:pt-0 last:pb-0 sm:grid-cols-[13rem_minmax(0,1fr)]">
              <div className={v.available ? "flex items-start gap-2" : "flex items-start gap-2 text-muted-foreground"}>
                {v.available ? <Check className="mt-0.5 size-4 shrink-0" aria-label="dostępny" /> : <Minus className="mt-0.5 size-4 shrink-0" aria-label="niedostępny" />}
                <div>
                  <p className="font-medium">{v.label}</p>
                  <p className="text-xs text-muted-foreground">{v.available ? v.detail : "brak danych w tym materiale"}</p>
                </div>
              </div>
              <div className="min-w-0 space-y-1 text-sm">
                <p>{VIEW_PLAIN[v.view] ?? v.hint}</p>
                <p className="text-xs text-muted-foreground">Metoda: {v.hint}</p>
                {v.view === "images" && v.available && f.assets.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 pt-1">
                    {f.assets.slice(0, 10).map((a) => (
                      <a key={a} href={a} target="_blank" rel="noreferrer">
                        <img src={a} alt="obraz ze strony" loading="lazy" className="size-11 rounded object-cover ring-1 ring-border" />
                      </a>
                    ))}
                    {f.n_assets_total > 10 && <span className="self-center text-xs text-muted-foreground">+{f.n_assets_total - 10}</span>}
                  </div>
                )}
              </div>
            </li>
          ))}
        </ul>
      </Section>

      <Section
        title="Opis materiału"
        description={`Cechy dla analityka — nie łączą materiałów (poza nazwą produktu, która jest identyfikatorem).${f.llm_backend_label ? ` Źródło opisu: ${f.llm_backend_label}.` : ""}`}
      >
        <dl className="divide-y border-t">
          {f.llm.map((r) => (
            <KV key={r.key} label={r.label}>{Array.isArray(r.value) ? <Chips values={r.value} max={8} /> : r.value}</KV>
          ))}
          <KV label="Słowa kluczowe"><Chips values={f.text.keywords} /></KV>
          {f.text.amounts.length > 0 && <KV label="Kwoty"><Chips values={f.text.amounts} /></KV>}
          {descriptive.flatMap((g) => g.items).map((it) => (
            <KV key={it.type} label={it.type_label}><Chips values={it.values.map((v) => v.display)} /></KV>
          ))}
        </dl>
        {f.text.excerpt && (
          <details className="mt-4 text-sm">
            <summary className="cursor-pointer font-medium text-muted-foreground hover:text-foreground">Fragment tekstu strony ({f.text.n_chars.toLocaleString("pl-PL")} znaków)</summary>
            <p className="mt-2 rounded-md bg-muted p-3.5 text-xs leading-relaxed whitespace-pre-wrap">{f.text.excerpt}</p>
          </details>
        )}
        {f.web.infra.length > 0 && (
          <details className="mt-3 text-sm">
            <summary className="cursor-pointer font-medium text-muted-foreground hover:text-foreground">
              Domeny i serwery ({plural(f.web.infra.length, "domena", "domeny", "domen")})
            </summary>
            <div className="mt-3 grid gap-x-10 gap-y-5 md:grid-cols-2">
              {f.web.infra.map((d) => (
                <div key={d.domain}>
                  <div className="mb-1 flex flex-wrap items-center justify-between gap-2 border-b pb-2">
                    <span className="font-mono text-sm font-medium break-all">{d.domain}</span>
                    {d.cert_pl_listed && <Badge variant="destructive"><AlertTriangle /> lista ostrzeżeń CERT Polska</Badge>}
                  </div>
                  <dl className="divide-y">
                    <KV label="Rejestrator">{d.registrar ?? "—"}</KV>
                    <KV label="Utworzona">{d.created?.slice(0, 10) ?? "—"}</KV>
                    <KV label="Pierwszy certyfikat">{d.first_cert?.slice(0, 10) ?? "—"}</KV>
                    <KV label="Serwery NS"><span className="font-mono text-xs break-all">{d.nameservers?.join(", ") ?? "—"}</span></KV>
                  </dl>
                </div>
              ))}
            </div>
            {f.web.redirect_chains.length > 0 && (
              <div className="mt-3 space-y-1">
                <p className="text-muted-foreground">Przekierowania:</p>
                {f.web.redirect_chains.map((c, i) => <p key={i} className="font-mono text-xs break-all">{c.join(" → ")}</p>)}
              </div>
            )}
          </details>
        )}
      </Section>
    </>
  )
}

function IndicatorBlock({ g, nCorpus }: { g: IndicatorGroup; nCorpus: number }) {
  return (
    <section className="grid gap-x-6 gap-y-2 py-3 first:pt-0 last:pb-0 sm:grid-cols-[13rem_minmax(0,1fr)]">
      <div>
        <h3 className="font-medium first-letter:uppercase">{g.label}</h3>
        <p className="text-xs text-muted-foreground">{g.hint}</p>
      </div>
      <dl className="min-w-0 space-y-2">
        {g.items.map((it) => (
          <div key={it.type} className="min-w-0">
            <dt className="text-xs text-muted-foreground">{it.type_label}</dt>
            <dd>
              <ul className="space-y-1">
                {it.values.map((v) => (
                  <li key={v.value} className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-0.5">
                    <span className="min-w-0 font-mono text-xs break-all">{v.display}</span>
                    {v.df > 1 ? (
                      <Link to={traceHref(it.type, v.value)} title={`Wartość występuje w ${v.df} z ${nCorpus} materiałów`}>
                        <Badge className="shrink-0 hover:opacity-80">w {v.df} mat.</Badge>
                      </Link>
                    ) : (
                      <span className="shrink-0 text-xs text-muted-foreground">tylko tutaj</span>
                    )}
                  </li>
                ))}
              </ul>
              {it.more > 0 && <p className="mt-1 text-xs text-muted-foreground">+{it.more} więcej</p>}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  )
}
