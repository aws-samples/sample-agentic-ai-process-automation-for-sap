// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, afterEach, vi } from "vitest"
import { render, screen, cleanup } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"

// Stub heavy route modules so the test isolates routing, not page internals.
vi.mock("@/routes/WorkspacePage", () => ({ default: () => <div>workspace-stub</div> }))
vi.mock("@/routes/AnalyticsDashboard", () => ({ default: () => <div>analytics-stub</div> }))
vi.mock("@/routes/TicketsDashboard", () => ({ default: () => <div>tickets-stub</div> }))
vi.mock("@/routes/TestDataPage", () => ({ default: () => <div>testdata-stub</div> }))
vi.mock("@/routes/SapAuthCallback", () => ({ default: () => <div>sapauth-stub</div> }))

// Controllable demo gating.
vi.mock("@/hooks/useDemoEnabled", () => ({
  useDemoFeatures: vi.fn(() => ({ ticketing: false, testData: false })),
}))

import AppRoutes from "@/routes"
import { useDemoFeatures } from "@/hooks/useDemoEnabled"

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>
  )
}

describe("AppRoutes", () => {
  afterEach(() => {
    cleanup()
    vi.mocked(useDemoFeatures).mockReturnValue({ ticketing: false, testData: false })
  })

  it("renders WorkspacePage at /", () => {
    renderAt("/")
    expect(screen.getByText("workspace-stub")).toBeTruthy()
  })

  it("renders AnalyticsDashboard at /analytics", () => {
    renderAt("/analytics")
    expect(screen.getByText("analytics-stub")).toBeTruthy()
  })

  it("renders SapAuthCallback at /auth/callback", () => {
    renderAt("/auth/callback")
    expect(screen.getByText("sapauth-stub")).toBeTruthy()
  })

  it("hides demo routes when both features are disabled", () => {
    vi.mocked(useDemoFeatures).mockReturnValue({ ticketing: false, testData: false })
    renderAt("/tickets")
    expect(screen.queryByText("tickets-stub")).toBeNull()
  })

  it.each([
    ["/tickets", "tickets-stub"],
    ["/test-data", "testdata-stub"],
  ])("renders demo route %s when both features are enabled", (path, stub) => {
    vi.mocked(useDemoFeatures).mockReturnValue({ ticketing: true, testData: true })
    renderAt(path)
    expect(screen.getByText(stub)).toBeTruthy()
  })

  it("gates ticketing and test-data independently", () => {
    vi.mocked(useDemoFeatures).mockReturnValue({ ticketing: true, testData: false })
    renderAt("/tickets")
    expect(screen.getByText("tickets-stub")).toBeTruthy()
    cleanup()
    renderAt("/test-data")
    expect(screen.queryByText("testdata-stub")).toBeNull()
  })
})
