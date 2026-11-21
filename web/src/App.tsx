import { lazy, Suspense } from "react"
import { BrowserRouter, Navigate, Route, Routes } from "react-router"

import { Loading } from "@/components/common"
import { AppLayout } from "@/components/layout"
import OverviewPage from "@/pages/overview"

const CampaignPage = lazy(() => import("@/pages/campaign"))
const SpacePage = lazy(() => import("@/pages/space"))
const GraphPage = lazy(() => import("@/pages/graph"))
const MatrixPage = lazy(() => import("@/pages/matrix"))
const MaterialsPage = lazy(() => import("@/pages/materials"))
const MaterialPage = lazy(() => import("@/pages/material"))
const PairPage = lazy(() => import("@/pages/pair"))
const TracePage = lazy(() => import("@/pages/trace"))
const AnalysePage = lazy(() => import("@/pages/analyse"))
const GlossaryPage = lazy(() => import("@/pages/glossary"))

function NotFound() {
  return <p className="text-muted-foreground">Nie ma takiej strony.</p>
}

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<div className="p-8"><Loading /></div>}>
        <Routes>
          <Route element={<AppLayout />}>
            <Route index element={<OverviewPage />} />
            <Route path="campaigns/:id" element={<CampaignPage />} />
            <Route path="space" element={<SpacePage />} />
            <Route path="graph" element={<GraphPage />} />
            <Route path="matrix" element={<MatrixPage />} />
            <Route path="materials" element={<MaterialsPage />} />
            <Route path="materials/:id" element={<MaterialPage />} />
            <Route path="pair/:a/:b" element={<PairPage />} />
            <Route path="trace" element={<TracePage />} />
            <Route path="analyse" element={<AnalysePage />} />
            <Route path="glossary" element={<GlossaryPage />} />
            {/* old workspace URLs */}
            <Route path="relations" element={<Navigate to="/graph" replace />} />
            <Route path="metrics" element={<Navigate to="/space" replace />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}
