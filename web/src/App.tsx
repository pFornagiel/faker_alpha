import { lazy, Suspense } from "react"
import { BrowserRouter, Navigate, Route, Routes, useSearchParams } from "react-router"

import { Loading } from "@/components/common"
import { AppLayout } from "@/components/layout"
import OverviewPage from "@/pages/overview"

const CampaignPage = lazy(() => import("@/pages/campaign"))
const MaterialsPage = lazy(() => import("@/pages/materials"))
const MaterialPage = lazy(() => import("@/pages/material"))
const PairPage = lazy(() => import("@/pages/pair"))
const RelationsPage = lazy(() => import("@/pages/relations"))
const TracePage = lazy(() => import("@/pages/trace"))
const AnalyseHubPage = lazy(() => import("@/pages/analyse-hub"))
const MetricsHubPage = lazy(() => import("@/pages/metrics"))
const GlossaryPage = lazy(() => import("@/pages/glossary"))

function RedirectWithTab({ to, tab }: { to: string; tab: string }) {
  const [params] = useSearchParams()
  const next = new URLSearchParams(params)
  next.set("tab", tab)
  return <Navigate to={`${to}?${next.toString()}`} replace />
}

function NotFound() {
  return <p className="text-muted-foreground">Nie ma takiej strony.</p>
}

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<div className="p-8"><Loading /></div>}>
        <Routes>
          <Route element={<AppLayout />}>
            {/* 5 simplified primary workspaces */}
            <Route index element={<OverviewPage />} />
            <Route path="campaigns/:id" element={<CampaignPage />} />
            <Route path="materials" element={<MaterialsPage />} />
            <Route path="materials/:id" element={<MaterialPage />} />
            <Route path="trace" element={<TracePage />} />
            <Route path="relations" element={<RelationsPage />} />
            <Route path="pair/:a/:b" element={<PairPage />} />
            <Route path="analyse" element={<AnalyseHubPage />} />
            <Route path="metrics" element={<MetricsHubPage />} />
            <Route path="glossary" element={<GlossaryPage />} />

            {/* Backward-compatible redirects for old URLs */}
            <Route path="graph" element={<RedirectWithTab to="/relations" tab="graph" />} />
            <Route path="matrix" element={<RedirectWithTab to="/relations" tab="matrix" />} />
            <Route path="links" element={<RedirectWithTab to="/relations" tab="pairs" />} />
            <Route path="scanner" element={<RedirectWithTab to="/analyse" tab="scanner" />} />
            <Route path="data" element={<RedirectWithTab to="/analyse" tab="data" />} />
            <Route path="methodology" element={<RedirectWithTab to="/metrics" tab="method" />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}
