// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { Routes, Route } from "react-router-dom"
import WorkspacePage from "./WorkspacePage"
import AnalyticsDashboard from "./AnalyticsDashboard"
import TicketsDashboard from "./TicketsDashboard"
import TestDataPage from "./TestDataPage"
import SapAuthCallback from "./SapAuthCallback"
import { useDemoFeatures } from "@/hooks/useDemoEnabled"

export default function AppRoutes() {
  // Demo-only routes render only when their backing feature is deployed.
  // Ticketing and test-data are independent (see demo.ticketing / demo.test_data).
  const { ticketing, testData } = useDemoFeatures()
  return (
    <Routes>
      <Route path="/" element={<WorkspacePage />} />
      <Route path="/analytics" element={<AnalyticsDashboard />} />
      {ticketing && <Route path="/tickets" element={<TicketsDashboard />} />}
      {testData && <Route path="/test-data" element={<TestDataPage />} />}
      <Route path="/auth/callback" element={<SapAuthCallback />} />
    </Routes>
  )
}
