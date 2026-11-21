import { AlertTriangle, ArrowRight, ChevronDown } from "lucide-react"
import { useState } from "react"
import { Link, useParams } from "react-router"

import type { LinkBrief, MaterialDetail } from "@/lib/api"
import { FAMILY_CUT, matLabel, plural, useApi } from "@/lib/format"
import { CampaignBadge, Chips, ErrorState, KV, Loading, MaterialRow, PageHeader, RelationBadge, Section, Strength } from "@/components/common"
import { FeatureSections } from "@/components/features"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"

const KIND_PL: Record<string, string> = {
  screenshot: "zrzut ekranu",
  keyframe: "klatka wideo",
  ui_screenshot: "zrzut interfejsu platformy",
  creative: "kreacja",
  capture: "przechwycenie",
}

export default function MaterialPage() {
  const { id } = useParams()
  const { data: m, error, isLoading } = useApi<MaterialDetail>(`/api/materials/${id}`)
  const [imgIdx, setImgIdx] = useState(0)

  if (isLoading) return <Loading />
  if (error || !m) return <ErrorState error={error} />
  const f = m.features
  const lbl = matLabel(m)
  const gallery = f.images.filter((im) => im.url)
  const activeImg = gallery[Math.min(imgIdx, Math.max(0, gallery.length - 1))]
  const contents = [
    m.inputs.pages.length > 0 && plural(m.inputs.pages.length, "zapis strony", "zapisy strony", "zapisów strony"),
    m.inputs.images > 0 && plural(m.inputs.images, "zrzut ekranu", "zrzuty ekranu", "zrzutów ekranu"),
    m.inputs.videos > 0 && plural(m.inputs.videos, "wideo", "wideo", "wideo"),
    m.inputs.assets > 0 && plural(m.inputs.assets, "plik strony", "pliki strony", "plików strony"),
  ].filter(Boolean)


  return (
    <>
      <PageHeader
        docTitle={`Materiał ${lbl}`}
        title={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <span>Materiał {lbl}</span>
            {m.campaign && (
              <span className="text-base font-normal tracking-normal">
                <CampaignBadge c={m.campaign} withName />
              </span>
            )}
          </span>
        }
        description={f.text.titles[0] ?? m.title}
        actions={m.campaign && m.campaign.size > 1 ? (
          <Button asChild variant="outline">
            <Link to={`/campaigns/${m.campaign.id}`}>Kampania {m.campaign.code} <ArrowRight /></Link>
          </Button>
        ) : undefined}
      />

      <div className="grid items-start gap-6 xl:grid-cols-[1fr_1.35fr]">
        <Section
          title="Podgląd"
          description={gallery.length
            ? `${plural(gallery.length, "obraz", "obrazy", "obrazów")}${gallery.length > 1 ? " — wybierz miniaturę, aby zmienić podgląd" : ""}. Kliknięcie obrazu otwiera go w pełnym rozmiarze.`
            : "Materiał nie zawiera zrzutu ekranu ani klatki wideo."}
        >
          {activeImg?.url ? (
            <div className="space-y-3">
              <a href={activeImg.url} target="_blank" rel="noreferrer" className="block overflow-hidden rounded-lg border bg-muted">
                <img src={activeImg.url} alt={`Materiał ${lbl}`} className="mx-auto max-h-[380px] w-full object-contain" />
              </a>
              <dl className="space-y-1.5 text-sm">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <dt className="text-muted-foreground">Rodzaj obrazu:</dt>
                  <dd>{KIND_PL[activeImg.kind] ?? activeImg.kind}</dd>
                </div>
                {activeImg.faces.length > 0 && (
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <dt className="text-muted-foreground">Twarze na obrazie:</dt>
                    <dd className="flex flex-wrap gap-1.5">
                      {activeImg.faces.map((fc, j) => (
                        <Badge key={j} variant={fc.identity ? "secondary" : "outline"} title={fc.identity ? "Zgodność z twarzą z bazy referencyjnej" : undefined}>
                          {fc.identity ? `${fc.identity} · zgodność ${Math.round(fc.sim * 100)}%` : "twarz nierozpoznana"}
                        </Badge>
                      ))}
                    </dd>
                  </div>
                )}
                {activeImg.ocr && (
                  <div>
                    <dt className="text-muted-foreground">Tekst odczytany z obrazu (OCR):</dt>
                    <dd className="mt-0.5 text-xs leading-relaxed">{activeImg.ocr}</dd>
                  </div>
                )}
              </dl>
              {gallery.length > 1 && (
                <div className="flex gap-2 overflow-x-auto pt-1">
                  {gallery.map((im, idx) => (
                    <button
                      key={idx}
                      type="button"
                      aria-label={`Pokaż obraz ${idx + 1}`}
                      aria-pressed={idx === imgIdx}
                      onClick={() => setImgIdx(idx)}
                      className={`shrink-0 overflow-hidden rounded-md border-2 ${idx === imgIdx ? "border-foreground" : "border-transparent opacity-70 hover:opacity-100"}`}
                    >
                      <img src={im.url!} alt="" className="size-16 object-cover" />
                    </button>
                  ))}
                </div>
              )}
            </div>
          ) : m.thumb ? (
            <img src={m.thumb} alt={`Materiał ${lbl}`} className="mx-auto max-h-72 rounded-lg border bg-muted object-contain" />
          ) : (
            <div className="flex h-40 items-center justify-center rounded-lg border border-dashed text-sm text-muted-foreground">
              Brak obrazów do pokazania
            </div>
          )}
        </Section>

        <Section title="Podsumowanie">
          {f.summary && <p className="mb-4 max-w-[75ch] leading-relaxed text-pretty">{f.summary}</p>}

          <dl className="divide-y border-t">
            <KV label="Rodzaj oszustwa">{m.scam_type_label ?? "nie rozpoznano"}</KV>
            <KV label="Produkt lub platforma">{m.product ?? "nie rozpoznano"}</KV>
            <KV label="Domeny docelowe"><Chips values={f.web.landing_domains} empty="brak — materiał nie zawiera strony docelowej" /></KV>
            <KV label="Osoby na obrazach" hint="Twarze rozpoznane przez porównanie z bazą referencyjną zdjęć osób publicznych (ArcFace).">
              <Chips values={f.persons.faces} empty="nie rozpoznano" />
            </KV>
            <KV label="Osoby w tekście" hint="Nazwiska wymienione w treści strony albo odczytane z kreacji (OCR).">
              <Chips values={f.persons.named} empty="nie znaleziono" />
            </KV>
            <KV label="Źródło">
              {m.source_label}
              <span className="block truncate font-mono text-xs text-muted-foreground" title={m.source_ref}>{m.source_ref}</span>
            </KV>
            <KV label="Pliki wejściowe">{contents.join(" · ") || "brak"}</KV>
          </dl>

          {f.notes.length > 0 && (
            <Alert className="mt-4">
              <AlertTriangle />
              <AlertTitle>Niekompletne dane wejściowe</AlertTitle>
              <AlertDescription>{f.notes.join("; ")}</AlertDescription>
            </Alert>
          )}
        </Section>
      </div>

      <SimilarList me={m.id} links={m.links} />
      <FeatureSections f={f} />
    </>
  )
}

function SimilarList({ me, links }: { me: string; links: LinkBrief[] }) {
  const [showWeak, setShowWeak] = useState(false)
  const strong = links.filter((l) => l.relation !== "none")
  const weak = links.filter((l) => l.relation === "none")
  const row = (l: LinkBrief) => (
    <li key={l.other!.id} className="space-y-2 py-3.5">
      <MaterialRow
        m={l.other!}
        right={<Button asChild variant="outline" size="sm"><Link to={`/pair/${me}/${l.other!.id}`}>Porównaj parę <ArrowRight /></Link></Button>}
      />
      <div className="flex flex-wrap items-start gap-x-4 gap-y-2 pl-[4.125rem]">
        <Strength p={l.p} distance={l.distance} className="w-56" />
        <RelationBadge relation={l.relation} />
      </div>
      {l.reasons.length > 0 && (
        <p className="pl-[4.125rem] text-xs text-muted-foreground">Najmocniejszy dowód: {l.reasons[0].detail}</p>
      )}
    </li>
  )
  return (
    <Section
      title="Materiały najbliższe temu"
      description="Materiały ze wspólnym identyfikatorem albo podobną treścią, od najbliższego. Bliskość p = 1 przy wspólnym identyfikatorze, inaczej 1 − d."
    >
      {strong.length ? (
        <ul className="divide-y border-t">{strong.map(row)}</ul>
      ) : (
        <p className="text-sm text-muted-foreground">
          Ten materiał nie jest powiązany z żadnym innym: nie ma wspólnego identyfikatora, a odległość treści do każdego materiału przekracza {FAMILY_CUT}.
        </p>
      )}
      {weak.length > 0 && (
        <div className="mt-3 border-t pt-3">
          <Button variant="ghost" size="sm" className="-ml-2 text-muted-foreground" aria-expanded={showWeak} onClick={() => setShowWeak(!showWeak)}>
            <ChevronDown className={showWeak ? "rotate-180 transition-transform" : "transition-transform"} />
            {showWeak ? "Ukryj" : "Pokaż"} materiały bez powiązania ({weak.length}) — odległość treści d &gt; {FAMILY_CUT}
          </Button>
          {showWeak && <ul className="mt-1 divide-y">{weak.map(row)}</ul>}
        </div>
      )}
    </Section>
  )
}
