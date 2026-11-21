import { AlertTriangle, Info } from "lucide-react"
import { useSearchParams } from "react-router"

import type { TraceDetail } from "@/lib/api"
import { plural, useApi } from "@/lib/format"
import { ErrorState, GroupBadge, KV, Loading, MaterialRow, PageHeader, Section } from "@/components/common"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Card, CardContent } from "@/components/ui/card"
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty"

export default function TracePage() {
  const [params] = useSearchParams()
  const type = params.get("type") ?? ""
  const value = params.get("value") ?? ""
  const { data: t, error, isLoading } = useApi<TraceDetail>(type && value ? `/api/trace?type=${encodeURIComponent(type)}&value=${encodeURIComponent(value)}` : null)
  if (!type || !value) return <ErrorState error="Brak parametrów śladu (type, value)." />
  if (isLoading) return <Loading />
  if (error || !t) return <ErrorState error={error} />
  const campaigns = [...new Set(t.materials.map((m) => m.campaign?.code).filter(Boolean))]
  const isPerson = t.type === "person"

  if (!t.df)
    return (
      <>
        <PageHeader docTitle="Ślad" title={<span className="break-all">{t.type_label}: {t.display}</span>} />
        <Empty className="border">
          <EmptyHeader>
            <EmptyTitle>Ta wartość nie występuje w żadnym materiale</EmptyTitle>
            <EmptyDescription>Sprawdź pisownię albo użyj wyszukiwarki w nagłówku.</EmptyDescription>
          </EmptyHeader>
        </Empty>
      </>
    )

  return (
    <>
      <PageHeader
        docTitle={`${t.type_label}: ${t.display}`}
        title={<span className="break-all">{t.type_label}: <span className={isPerson ? "" : "font-mono text-xl"}>{t.display}</span></span>}
        description={`Wszystkie materiały, w których występuje ta wartość: ${t.df} z ${t.n}${campaigns.length ? ` (kampanie: ${campaigns.join(", ")})` : ""}.`}
      />
      {t.thumbs.length > 0 && <img src={t.thumbs[0]} alt="wspólny obraz" className="max-h-56 rounded-md ring-1 ring-border" />}
      {t.linking && !t.counted && (
        <Alert>
          <AlertTriangle />
          <AlertTitle>Wartość zbyt popularna</AlertTitle>
          <AlertDescription>
            Występuje w {t.df} z {t.n} materiałów — w ponad {pct(t.max_df)} bazy — więc jest pomijana przy łączeniu: nie odróżnia jednej kampanii od innych.
          </AlertDescription>
        </Alert>
      )}
      {!t.linking && (
        <Alert>
          <Info />
          <AlertTitle>Ten ślad sam niczego nie łączy</AlertTitle>
          <AlertDescription>
            {t.group === "images"
              ? "Obrazy ze stron docelowych są porównywane w widoku treści „obrazy” (pHash): wspólny obraz zwiększa podobieństwo treści, ale sam nie wymusza tej samej kampanii."
              : `To cecha opisowa (${t.group_label}) — pokazywana analitykowi, nigdy nie służy do łączenia. Materiały poniżej mogą należeć do różnych kampanii.`}
          </AlertDescription>
        </Alert>
      )}
      <div className="grid gap-4 lg:grid-cols-[1fr_1.4fr]">
        <Card size="sm">
          <CardContent>
            <dl className="divide-y">
              <KV label="Rodzaj śladu"><GroupBadge label={t.group_label} linking={t.linking} /></KV>
              <KV label="Częstość">
                w {t.df} z {t.n} materiałów ({pct(t.df / Math.max(1, t.n))})
                <span className="block text-xs text-muted-foreground">identyfikator liczy się tylko, gdy występuje w co najwyżej {pct(t.max_df)} materiałów (zasada IDF)</span>
              </KV>
              <KV label="Łączy materiały">
                {t.counted ? "tak — wspólna wartość wymusza tę samą kampanię" : t.linking ? "nie — zbyt popularna" : t.group === "images" ? "nie — wpływa na widok treści „obrazy”" : "nie — cecha opisowa"}
              </KV>
            </dl>
          </CardContent>
        </Card>
        <Section title={plural(t.materials.length, "materiał z tym śladem", "materiały z tym śladem", "materiałów z tym śladem")}>
          <ul className="space-y-3">
            {t.materials.map((m) => <li key={m.id}><MaterialRow m={m} /></li>)}
          </ul>
        </Section>
      </div>
    </>
  )
}

function pct(x: number): string {
  return `${Math.round(x * 100)}%`
}
