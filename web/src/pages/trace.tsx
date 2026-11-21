import { AlertTriangle, Info } from "lucide-react"
import { useSearchParams } from "react-router"

import type { TraceDetail } from "@/lib/api"
import { fmtP, plural, useApi } from "@/lib/format"
import { ErrorState, KV, Loading, MaterialRow, PageHeader, Section, TierBadge } from "@/components/common"
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
      {t.hub && (
        <Alert>
          <AlertTriangle />
          <AlertTitle>Wartość zbyt popularna („hub”)</AlertTitle>
          <AlertDescription>Występuje w ponad połowie materiałów, więc jest ignorowana przy łączeniu — nie odróżnia jednego operatora od innych.</AlertDescription>
        </Alert>
      )}
      {t.tier === "W" && !t.hub && (
        <Alert>
          <Info />
          <AlertTitle>Ten ślad sam niczego nie łączy</AlertTitle>
          <AlertDescription>
            To ślad kontekstowy ({t.family_label}). Materiały poniżej mogą należeć do różnych kampanii — łączy się je dopiero, gdy mają też wspólne ślady operatora lub kit/treść.
          </AlertDescription>
        </Alert>
      )}
      <div className="grid gap-4 lg:grid-cols-[1fr_1.4fr]">
        <Card size="sm">
          <CardContent>
            <dl className="divide-y">
              <KV label="Rodzina dowodów">{t.family_label}</KV>
              <KV label="Siła śladu"><TierBadge tier={t.tier} /></KV>
              <KV label="Waga bazowa">
                {t.prior !== null ? fmtP(t.prior) : "—"}
                <span className="block text-xs text-muted-foreground">jak mocno ten typ śladu wskazuje na jednego operatora, gdy wartość jest rzadka (ustalone eksperckie)</span>
              </KV>
              <KV label="Rzadkość">
                {fmtP(t.rarity)}
                <span className="block text-xs text-muted-foreground">wartość w {t.df} z {t.n} materiałów; 1 = tylko w dwóch, 0 = w ponad połowie (pomijana)</span>
              </KV>
              <KV label="Waga przy łączeniu">
                <span className="font-semibold">{t.weight !== null ? fmtP(t.weight) : "—"}</span>
                <span className="block text-xs text-muted-foreground">waga bazowa × (0.35 + 0.65 × rzadkość) — tyle ten ślad wnosi do powiązania dwóch materiałów</span>
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
