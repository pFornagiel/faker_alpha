import { useSearchParams } from "react-router"

import { PageHeader, PageTab, PageTabsList } from "@/components/common"
import { Tabs, TabsContent } from "@/components/ui/tabs"
import AnalysePage from "@/pages/analyse"
import DataPage from "@/pages/data"
import ScannerPage from "@/pages/scanner"

const TABS = ["new", "scanner", "data"] as const
type Tab = (typeof TABS)[number]

export default function AnalyseHubPage() {
  const [params, setParams] = useSearchParams()
  const raw = params.get("tab") ?? "new"
  const tab: Tab = (TABS as readonly string[]).includes(raw) ? (raw as Tab) : "new"
  const setTab = (v: string) => {
    setParams((p) => {
      const next = new URLSearchParams(p)
      next.set("tab", v)
      return next
    }, { replace: true })
  }

  return (
    <>
      <PageHeader
        title="Analiza i skaner"
        description="Trzy sposoby na powiększenie bazy: sprawdź pojedynczy materiał, przeszukaj publiczne biblioteki reklam i listę ostrzeżeń CERT Polska albo wczytaj cały zbiór przypadków. Tu też eksportujesz wyniki."
      />
      <Tabs value={tab} onValueChange={setTab} className="gap-6">
        <PageTabsList label="Analiza i skaner">
          <PageTab value="new">Analizuj nowy materiał</PageTab>
          <PageTab value="scanner">Skaner źródeł publicznych</PageTab>
          <PageTab value="data">Baza, import i eksport</PageTab>
        </PageTabsList>

        <TabsContent value="new">
          <AnalysePage embedded />
        </TabsContent>
        <TabsContent value="scanner">
          <ScannerPage embedded />
        </TabsContent>
        <TabsContent value="data">
          <DataPage embedded />
        </TabsContent>
      </Tabs>
    </>
  )
}
