import { lazy, Suspense } from "react"
import { BrowserRouter, Route, Routes } from "react-router"

import { Loading } from "@/components/common"
import { AppLayout } from "@/components/layout"
import OverviewPage from "@/pages/overview"

const CampaignPage = lazy(() => import("@/pages/campaign"))
const MaterialsPage = lazy(() => import("@/pages/materials"))
const MaterialPage = lazy(() => import("@/pages/material"))
const PairPage = lazy(() => import("@/pages/pair"))
const LinksPage = lazy(() => import("@/pages/links"))
const GraphPage = lazy(() => import("@/pages/graph"))
const MatrixPage = lazy(() => import("@/pages/matrix"))
const TracePage = lazy(() => import("@/pages/trace"))
const AnalysePage = lazy(() => import("@/pages/analyse"))
const ScannerPage = lazy(() => import("@/pages/scanner"))
const DataPage = lazy(() => import("@/pages/data"))
const MethodologyPage = lazy(() => import("@/pages/methodology"))

function NotFound() {
  return <p className="text-muted-foreground">Nie ma takiej strony.</p>
}

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<div className="p-6"><Loading /></div>}>
        <Routes>
          <Route element={<AppLayout />}>
            <Route index element={<OverviewPage />} />
            <Route path="campaigns/:id" element={<CampaignPage />} />
            <Route path="materials" element={<MaterialsPage />} />
            <Route path="materials/:id" element={<MaterialPage />} />
            <Route path="pair/:a/:b" element={<PairPage />} />
            <Route path="links" element={<LinksPage />} />
            <Route path="graph" element={<GraphPage />} />
            <Route path="matrix" element={<MatrixPage />} />
            <Route path="trace" element={<TracePage />} />
            <Route path="analyse" element={<AnalysePage />} />
            <Route path="scanner" element={<ScannerPage />} />
            <Route path="data" element={<DataPage />} />
            <Route path="methodology" element={<MethodologyPage />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}
