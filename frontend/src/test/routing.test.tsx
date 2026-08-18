// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, afterEach, vi } from "vitest"
import { render, screen, cleanup } from "@testing-library/react"
import { MemoryRouter } from "react-router"

// Stub heavy route modules so the test isolates routing, not page internals.
// The rail and the assistant are part of the layout route now; each has its own test.
vi.mock("@/components/SideRail", () => ({ SideRail: () => <div>rail-stub</div> }))
vi.mock("@/components/AssistantDock", () => ({ AssistantDock: () => <div>dock-stub</div> }))
// The shell mounts the conversation. Stubbed here so routing does not need the auth
// and query providers the real hook pulls in.
vi.mock("@/hooks/useAgentChat", () => ({ useAgentChat: () => ({}) }))
vi.mock("@/routes/WorkspacePage", () => ({ default: () => <div>workspace-stub</div> }))
vi.mock("@/routes/AnalyticsDashboard", () => ({ default: () => <div>analytics-stub</div> }))
vi.mock("@/routes/TicketsDashboard", () => ({ default: () => <div>tickets-stub</div> }))
vi.mock("@/routes/TestDataPage", () => ({ default: () => <div>testdata-stub</div> }))
vi.mock("@/routes/SettingsPage", () => ({ default: () => <div>settings-stub</div> }))
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

  it("wraps every route in the shell", async () => {
    renderAt("/")
    expect(screen.getByText("rail-stub")).toBeTruthy()
    expect(screen.getByText("dock-stub")).toBeTruthy()
    cleanup()
    renderAt("/analytics")
    expect(await screen.findByText("analytics-stub")).toBeTruthy()
    expect(screen.getByText("rail-stub")).toBeTruthy()
    // The assistant is available from every route, not just the workspace — that is
    // what makes it ambient rather than a home screen.
    expect(screen.getByText("dock-stub")).toBeTruthy()
  })

  it("exempts Workspace from the dashboard page frame", async () => {
    // Workspace's Allotment panes need the full viewport, so it must not inherit
    // the header/body column the dashboards share.
    renderAt("/")
    const workspaceParent = screen.getByText("workspace-stub").parentElement
    expect(workspaceParent?.tagName).toBe("MAIN")

    cleanup()
    renderAt("/analytics")
    const analyticsParent = (await screen.findByText("analytics-stub")).parentElement
    expect(analyticsParent?.tagName).toBe("DIV")
    expect(analyticsParent?.className).toContain("flex-col")
  })

  it("renders AnalyticsDashboard at /analytics", async () => {
    renderAt("/analytics")
    expect(await screen.findByText("analytics-stub")).toBeTruthy()
  })

  it("renders SapAuthCallback at /auth/callback", async () => {
    renderAt("/auth/callback")
    expect(await screen.findByText("sapauth-stub")).toBeTruthy()
  })

  it("renders SettingsPage at /settings with no demo feature enabled", async () => {
    // Settings edits the contacts and tolerances the SOPs cite, so it is not a demo
    // surface — it must be reachable on a deployment with every demo feature off.
    renderAt("/settings")
    expect(await screen.findByText("settings-stub")).toBeTruthy()
  })

  it("hides demo routes when both features are disabled", async () => {
    vi.mocked(useDemoFeatures).mockReturnValue({ ticketing: false, testData: false })
    renderAt("/tickets")
    // Assert absence only after the Suspense boundary has had a chance to
    // resolve, otherwise this would pass merely because the chunk is in flight.
    await expect(screen.findByText("tickets-stub")).rejects.toThrow()
  })

  it.each([
    ["/tickets", "tickets-stub"],
    ["/test-data", "testdata-stub"],
  ])("renders demo route %s when both features are enabled", async (path, stub) => {
    vi.mocked(useDemoFeatures).mockReturnValue({ ticketing: true, testData: true })
    renderAt(path)
    expect(await screen.findByText(stub)).toBeTruthy()
  })

  it("gates ticketing and test-data independently", async () => {
    vi.mocked(useDemoFeatures).mockReturnValue({ ticketing: true, testData: false })
    renderAt("/tickets")
    expect(await screen.findByText("tickets-stub")).toBeTruthy()
    cleanup()
    renderAt("/test-data")
    await expect(screen.findByText("testdata-stub")).rejects.toThrow()
  })
})
