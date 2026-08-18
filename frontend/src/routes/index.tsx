// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { Suspense, lazy } from "react"
import { Routes, Route } from "react-router"
import WorkspacePage from "./WorkspacePage"
import { AppShell, PageFrame } from "./AppShell"
import { useDemoFeatures } from "@/hooks/useDemoEnabled"

// Workspace is the landing route, so it stays eager — lazy-loading it would only
// add a network round trip to the first paint. The rest are split out: each pulls
// in chart, table, or form code that a user who never leaves Workspace never needs.
const AnalyticsDashboard = lazy(() => import("./AnalyticsDashboard"))
const TicketsDashboard = lazy(() => import("./TicketsDashboard"))
const TestDataPage = lazy(() => import("./TestDataPage"))
const SettingsPage = lazy(() => import("./SettingsPage"))
const SapAuthCallback = lazy(() => import("./SapAuthCallback"))

export default function AppRoutes() {
  // Demo-only routes render only when their backing feature is deployed.
  // Ticketing and test-data are independent (see demo.ticketing / demo.test_data).
  const { ticketing, testData } = useDemoFeatures()
  return (
    <Suspense fallback={<RouteFallback />}>
      <Routes>
        <Route element={<AppShell />}>
          {/* Full-bleed exemption: Workspace's Allotment panes need the whole
              viewport, so it sits outside PageFrame and owns its own box. */}
          <Route path="/" element={<WorkspacePage />} />
          <Route element={<PageFrame />}>
            <Route path="/analytics" element={<AnalyticsDashboard />} />
            {ticketing && <Route path="/tickets" element={<TicketsDashboard />} />}
            {testData && <Route path="/test-data" element={<TestDataPage />} />}
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/auth/callback" element={<SapAuthCallback />} />
          </Route>
        </Route>
      </Routes>
    </Suspense>
  )
}

/**
 * Shown only while a split route chunk is in flight, which on a warm cache is
 * no frames at all. Deliberately not a spinner: a spinner that appears for 80 ms
 * reads as a flicker, and the roadmap reserves motion for causality.
 */
function RouteFallback() {
  return (
    <div className="flex h-full items-center justify-center p-8" role="status" aria-live="polite">
      <span className="sr-only">Loading page</span>
    </div>
  )
}
