// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

vi.mock("@/hooks/useDemoEnabled", () => ({
  useDemoFeatures: vi.fn(() => ({ ticketing: false, testData: false })),
}))
vi.mock("react-oidc-context", () => ({
  useAuth: vi.fn(() => ({ isAuthenticated: false, user: undefined, signoutRedirect: vi.fn() })),
}))
vi.mock("@/lib/config", () => ({
  getConfig: vi.fn(async () => ({ client_id: "cid", redirect_uri: "https://example.test/" })),
}))

import { SideRail, idpLabel } from "@/components/SideRail"
import { useDemoFeatures } from "@/hooks/useDemoEnabled"

describe("idpLabel", () => {
  it("names the IdP from the issuer host", () => {
    expect(idpLabel("https://login.microsoftonline.com/tenant-id/v2.0")).toBe("Microsoft Entra ID")
    expect(idpLabel("https://dev-1234.okta.com/oauth2/default")).toBe("Okta")
    expect(idpLabel("https://cognito-idp.us-east-1.amazonaws.com/us-east-1_abc")).toBe(
      "Amazon Cognito"
    )
    expect(idpLabel("https://keycloak.example.com/realms/erp")).toBe("OIDC")
    expect(idpLabel("")).toBeNull()
  })

  it("does not read a known IdP name out of an arbitrary host or path", () => {
    // The old substring match called all three of these Okta/Entra/Cognito.
    expect(idpLabel("https://attacker.example.com/okta.com/oauth2")).toBe("OIDC")
    expect(idpLabel("https://okta.com.attacker.example/oauth2")).toBe("OIDC")
    expect(idpLabel("https://evil.example/?x=login.microsoftonline.com")).toBe("OIDC")
  })
})

function renderRail() {
  // The rail now hosts the agent heartbeat, which owns a query. Wrapping is more
  // honest than mocking it away: the mocked auth reports signed-out, so the query
  // stays disabled and no fetch is attempted.
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/"]}>
        <SideRail />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  localStorage.clear()
  document.documentElement.classList.remove("dark", "compact")
  vi.mocked(useDemoFeatures).mockReturnValue({ ticketing: false, testData: false })
})

afterEach(cleanup)

describe("SideRail", () => {
  it("renders the primary destinations as a single vertical nav", () => {
    renderRail()
    const nav = screen.getByRole("navigation", { name: "Primary" })
    expect(nav).toBeTruthy()
    expect(screen.getByRole("link", { name: "Workspace" })).toBeTruthy()
    expect(screen.getByRole("link", { name: "Analytics" })).toBeTruthy()
  })

  it("marks the current route with aria-current", () => {
    renderRail()
    expect(screen.getByRole("link", { name: "Workspace" }).getAttribute("aria-current")).toBe(
      "page"
    )
  })

  it("offers Settings regardless of the demo features", () => {
    renderRail()
    // Contacts and tolerances are operator configuration, not a demo: the link has to
    // be there on a deployment that enables nothing.
    expect(screen.getByRole("link", { name: "Settings" }).getAttribute("href")).toBe("/settings")
  })

  it("gates Tickets and Test Data on their demo features", () => {
    renderRail()
    expect(screen.queryByRole("link", { name: "Tickets" })).toBeNull()
    expect(screen.queryByRole("button", { name: "Test Data" })).toBeNull()

    cleanup()
    vi.mocked(useDemoFeatures).mockReturnValue({ ticketing: true, testData: true })
    renderRail()
    expect(screen.getByRole("link", { name: "Tickets" })).toBeTruthy()
    expect(screen.getByRole("button", { name: "Test Data" })).toBeTruthy()
  })

  it("puts the agent status on the shared row geometry, above the nav", () => {
    renderRail()
    const status = screen.getByRole("status")
    // Folded onto itemClass(): same row shape as a nav link, no separate band height.
    expect(status.className).toContain("rounded-md")
  })

  it("has one width and no collapse control", () => {
    renderRail()
    // The rail is icon-only always, so there is no second state to toggle into and no
    // wordmark to hide. A toggle would be a control with one outcome.
    expect(screen.queryByRole("button", { name: /sidebar/i })).toBeNull()
    expect(screen.queryByText("ERP Agent")).toBeNull()
    expect(screen.getByRole("navigation", { name: "Primary" }).className).toContain(
      "w-[var(--rail-w)]"
    )
  })

  it("ignores ⌘B, which no longer addresses anything", () => {
    renderRail()
    fireEvent.keyDown(window, { key: "b", metaKey: true })
    expect(screen.getByRole("navigation", { name: "Primary" }).className).toContain(
      "w-[var(--rail-w)]"
    )
  })

  it("labels every row by tooltip, with the same text the row announces", () => {
    vi.mocked(useDemoFeatures).mockReturnValue({ ticketing: true, testData: true })
    renderRail()

    // Every row's visible label is a tooltip span, so a row whose aria-label has no
    // matching tooltip is unlabelled for sighted operators.
    const rows = [
      ...screen.getAllByRole("link"),
      ...screen.getAllByRole("button"),
      screen.getByRole("status"),
    ]
    expect(rows.length).toBeGreaterThan(5)
    for (const row of rows) {
      const tip = row.querySelector("span.absolute.left-full")
      expect(tip, `no tooltip on ${row.getAttribute("aria-label")}`).toBeTruthy()
      // The heartbeat's tooltip appends its detail; the rest match their name exactly.
      expect(tip?.textContent).toContain(
        row.getAttribute("aria-label") === "Agent status" ? "" : row.getAttribute("aria-label")
      )
    }
  })

  it("does not clip the tooltips it depends on for labelling", () => {
    renderRail()
    // A scroll container computes overflow-x as auto too, which would cut off every
    // tooltip at left-full — invisible when labels existed, fatal now they don't.
    const nav = screen.getByRole("navigation", { name: "Primary" })
    for (const el of nav.querySelectorAll("*")) {
      expect(el.className.toString()).not.toMatch(/overflow-[xy]?-?(auto|hidden|scroll)/)
    }
  })

  // jsdom has no matchMedia, so "system" resolves light here — which is also the
  // path a browser without the API takes, and the one that must not throw.
  it("cycles the theme and drives the class the stylesheet keys off", () => {
    renderRail()
    expect(document.documentElement.classList.contains("dark")).toBe(false)

    fireEvent.click(screen.getByRole("button", { name: "Switch to dark theme" }))
    expect(document.documentElement.classList.contains("dark")).toBe(true)

    fireEvent.click(screen.getByRole("button", { name: "Switch to light theme" }))
    expect(document.documentElement.classList.contains("dark")).toBe(false)

    fireEvent.click(screen.getByRole("button", { name: "Switch to system theme" }))
    expect(screen.getByRole("button", { name: "Switch to dark theme" })).toBeTruthy()
  })

  it("persists the theme choice across remounts", () => {
    renderRail()
    fireEvent.click(screen.getByRole("button", { name: "Switch to dark theme" }))
    cleanup()

    renderRail()
    expect(document.documentElement.classList.contains("dark")).toBe(true)
    expect(screen.getByRole("button", { name: "Switch to light theme" })).toBeTruthy()
  })

  it("toggles density and drives the class the scales key off", () => {
    renderRail()
    const compact = screen.getByRole("button", { name: "Switch to compact density" })
    expect(compact.getAttribute("aria-pressed")).toBe("false")

    fireEvent.click(compact)
    expect(document.documentElement.classList.contains("compact")).toBe(true)

    const comfortable = screen.getByRole("button", { name: "Switch to comfortable density" })
    expect(comfortable.getAttribute("aria-pressed")).toBe("true")
    fireEvent.click(comfortable)
    expect(document.documentElement.classList.contains("compact")).toBe(false)
  })

  it("persists the density choice across remounts", () => {
    renderRail()
    fireEvent.click(screen.getByRole("button", { name: "Switch to compact density" }))
    cleanup()

    renderRail()
    expect(document.documentElement.classList.contains("compact")).toBe(true)
    expect(screen.getByRole("button", { name: "Switch to comfortable density" })).toBeTruthy()
  })
})
