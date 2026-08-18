// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi } from "vitest"
import { fireEvent, render, screen } from "@testing-library/react"
import {
  Banner,
  DomainPill,
  DomainTabs,
  EmptyState,
  PageBody,
  PageHeader,
  PageLoader,
  StatMetric,
} from "./page-chrome"
import { DOMAIN_META, Domain } from "@/types/cases"

describe("Banner", () => {
  // An error must interrupt a screen reader; a warning or prompt must not.
  it("only asserts itself for danger", () => {
    const { rerender } = render(<Banner tone="danger">Boom</Banner>)
    expect(screen.getByRole("alert").textContent).toBe("Boom")

    rerender(<Banner tone="progress">Heads up</Banner>)
    expect(screen.queryByRole("alert")).toBeNull()
    expect(screen.getByRole("status").textContent).toBe("Heads up")
  })
})

describe("PageHeader", () => {
  it("renders the title as the page heading", () => {
    render(
      <PageHeader title="Analytics" description="Cost and latency" actions={<button>Go</button>} />
    )
    const heading = screen.getByRole("heading", { level: 1 })
    expect(heading.textContent).toBe("Analytics")
    // Every route header goes through here, so this is where the display face is
    // guaranteed rather than per-route.
    expect(heading.className).toContain("font-display")
    expect(screen.getByText("Cost and latency")).toBeTruthy()
    expect(screen.getByRole("button", { name: "Go" })).toBeTruthy()
  })
})

describe("PageBody", () => {
  it("owns the page inset and scrolls the body", () => {
    render(<PageBody>content</PageBody>)
    const body = screen.getByText("content")
    expect(body.className).toContain("p-4")
    expect(body.className).toContain("overflow-auto")
  })
})

describe("StatMetric", () => {
  // These tiles poll. Without tabular figures the digits have different widths,
  // so the number twitches sideways on every refresh — and because the kit is the
  // only place the metric type is declared, losing it here loses it everywhere.
  it("renders the value in the display face with fixed-width digits", () => {
    render(<StatMetric label="Total cost" value="$1,111.00" />)
    const value = screen.getByText("$1,111.00")
    expect(value.className).toContain("tabular-nums")
    expect(value.className).toContain("font-display")
  })
})

describe("PageLoader", () => {
  it("announces itself as busy", () => {
    render(<PageLoader label="Loading tickets…" />)
    const status = screen.getByRole("status")
    expect(status.getAttribute("aria-busy")).toBe("true")
    expect(status.textContent).toBe("Loading tickets…")
  })
})

describe("EmptyState", () => {
  it("keeps the hint optional", () => {
    const { rerender } = render(<EmptyState message="Nothing here." />)
    expect(screen.getByText("Nothing here.")).toBeTruthy()

    rerender(<EmptyState message="Nothing here." hint="Try the form." />)
    expect(screen.getByText("Try the form.")).toBeTruthy()
  })
})

describe("DomainTabs", () => {
  it("marks the active domain and reports a pick — no everything-option", () => {
    const onChange = vi.fn()
    const active = DOMAIN_META[Domain.FinanceAp].short
    render(<DomainTabs value={Domain.FinanceAp} onChange={onChange} />)
    // A scope has no "All" — that is what separates a persona from a filter.
    expect(screen.queryByText("All")).toBeNull()
    expect(screen.getByText(active).className).toContain("border-foreground")
    fireEvent.click(screen.getByText(active))
    expect(onChange).toHaveBeenCalledWith(Domain.FinanceAp)
  })
})

describe("DomainPill", () => {
  // Cases written before a domain was renamed still carry the old string.
  it("falls back to the raw value for an unknown domain", () => {
    render(<DomainPill domain="legacy_thing" />)
    expect(screen.getByText("legacy_thing")).toBeTruthy()
  })
})
