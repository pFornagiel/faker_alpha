import { useSearchParams } from "react-router"

import { PageHeader, PageTab, PageTabsList } from "@/components/common"
import { Tabs, TabsContent } from "@/components/ui/tabs"
import GraphPage from "@/pages/graph"
import LinksPage from "@/pages/links"
import MatrixPage from "@/pages/matrix"

const TABS = ["graph", "matrix", "pairs"] as const
type Tab = (typeof TABS)[number]

export default function RelationsPage() {
  const [params, setParams] = useSearchParams()
  const raw = params.get("tab") ?? "graph"
  const tab: Tab = (TABS as readonly string[]).includes(raw) ? (raw as Tab) : "graph"
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
        title="Powiązania między materiałami"
        description="Te same pary w trzech ujęciach: graf pokazuje kształt kampanii, macierz — każdą parę naraz, tabela — pary z dowodami do przefiltrowania."
      />
      <Tabs value={tab} onValueChange={setTab} className="gap-5">
        <PageTabsList label="Ujęcie powiązań">
          <PageTab value="graph">Graf</PageTab>
          <PageTab value="matrix">Macierz</PageTab>
          <PageTab value="pairs">Tabela par</PageTab>
        </PageTabsList>

        <TabsContent value="graph">
          <GraphPage embedded />
        </TabsContent>
        <TabsContent value="matrix">
          <MatrixPage embedded />
        </TabsContent>
        <TabsContent value="pairs">
          <LinksPage embedded />
        </TabsContent>
      </Tabs>
    </>
  )
}
