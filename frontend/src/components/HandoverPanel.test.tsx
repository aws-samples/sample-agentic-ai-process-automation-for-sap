// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { render, screen, cleanup, fireEvent } from "@testing-library/react"
import { HandoverPanel } from "@/components/HandoverPanel"
import { CaseStatus, Domain, Trigger } from "@/types/cases"
import type { WorkItem } from "@/types/cases"

/**
 * What the panel says about the numbers, as distinct from how it derives them
 * (`digest.test.ts`). Every assertion here is a claim an AP manager would act on:
 * whether someone was actually asked, whether a total can be trusted, and whether
 * the label above a group names a person.
 */

const NOW = Date.parse("2026-07-31T12:00:00Z")
const hoursAgo = (h: number) => new Date(NOW - h * 3_600_000).toISOString()

function awaitingCase(overrides: Partial<WorkItem> = {}): WorkItem {
  return {
    case_id: "5100000001-2026",
    document_number: "5100000001",
    item_id: "2026",
    domain: Domain.FinanceAp,
    process_type: "price_variance",
    exception_type: "price_variance",
    status: CaseStatus.AwaitingHumanInput,
    created_at: hoursAgo(8),
    updated_at: hoursAgo(2),
    amount: 1200,
    currency: "USD",
    agent_traces: [
      { trace_id: "t1", timestamp: hoursAgo(2), segments: [], trigger: Trigger.Poller },
    ],
    cost_summary: { total_cost_usd: 0.05 },
    ...overrides,
  } as WorkItem
}

function renderPanel(cases: WorkItem[], props: Partial<Parameters<typeof HandoverPanel>[0]> = {}) {
  return render(
    <HandoverPanel
      cases={cases}
      tickets={[]}
      loading={false}
      onRefresh={vi.fn()}
      onOpenCase={vi.fn()}
      testDataEnabled={false}
      {...props}
    />
  )
}

beforeEach(() => {
  localStorage.clear()
  vi.useFakeTimers()
  vi.setSystemTime(NOW)
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe("HandoverPanel age label", () => {
  it("says 'waiting' only when an inquiry was actually sent", () => {
    renderPanel([awaitingCase({ inquiry_sent_at: hoursAgo(6) })])
    expect(screen.getByTitle("Since the inquiry was sent")).toHaveTextContent("waiting 6h")
  })

  it("says 'activity' when the only timestamp is our own write", () => {
    // `updated_at` means we touched the record, not that anybody was asked. Labelling
    // that as a wait is the claim this panel could most easily make without grounds.
    renderPanel([awaitingCase()])
    expect(screen.getByTitle("Since we last touched the case")).toHaveTextContent("activity 2h")
  })
})

describe("HandoverPanel headline", () => {
  it("states throughput, waiting and blocked without restating them as the rail's counts", () => {
    renderPanel([
      awaitingCase(),
      awaitingCase({ case_id: "b", status: CaseStatus.Complete }),
      awaitingCase({ case_id: "c", status: CaseStatus.ManualReviewRequired }),
    ])
    expect(screen.getByText(/posted without a human/)).toBeInTheDocument()
    expect(screen.getByText(/waiting on someone/)).toBeInTheDocument()
    expect(screen.getByText(/blocked/)).toBeInTheDocument()
  })

  it("marks a mixed-currency total as per-currency and unsigned", () => {
    renderPanel([
      awaitingCase({ case_id: "a", status: CaseStatus.Complete, amount: 100, currency: "USD" }),
      awaitingCase({ case_id: "b", status: CaseStatus.Complete, amount: 200, currency: "EUR" }),
    ])
    const line = screen.getByText(/gross invoice value posted/)
    expect(line.textContent).toContain("$100.00")
    expect(line.textContent).toContain("200.00 EUR")
    expect(line.textContent).toContain("(gross, unsigned)")
  })

  it("calls the spend a floor when a case recorded no cost", () => {
    renderPanel([awaitingCase({ cost_summary: undefined })])
    expect(screen.getByText(/some cases have no recorded cost/)).toBeInTheDocument()
  })
})

describe("HandoverPanel grouping", () => {
  it("names the owner when a ticket recorded one", () => {
    renderPanel([awaitingCase({ ticket_id: "TKT-1" })], {
      tickets: [
        {
          ticket_id: "TKT-1",
          title: "t",
          status: "open",
          priority: "medium",
          created_by: "agent",
          created_at: hoursAgo(2),
          updated_at: hoursAgo(2),
          assigned_to: "dana@example.com",
        },
      ] as Parameters<typeof HandoverPanel>[0]["tickets"],
    })
    expect(screen.getByText("Waiting on dana@example.com")).toBeInTheDocument()
  })

  it("says why it grouped by process type when ticketing is off", () => {
    renderPanel([awaitingCase()], { tickets: undefined })
    expect(screen.getByText("Waiting — price_variance")).toBeInTheDocument()
    expect(screen.getByText(/ticketing is disabled/)).toBeInTheDocument()
  })

  it("distinguishes an unrecorded recipient from a named one", () => {
    renderPanel([awaitingCase()])
    expect(screen.getByText("Waiting — recipient not recorded")).toBeInTheDocument()
  })
})

describe("HandoverPanel rows", () => {
  it("routes to the case rather than acting on it", () => {
    const onOpenCase = vi.fn()
    renderPanel([awaitingCase()], { onOpenCase })
    fireEvent.click(screen.getByText("5100000001-2026"))
    expect(onOpenCase).toHaveBeenCalledWith("5100000001-2026")
    // G.3 is the only approval surface; a second one here would bypass its reason gate.
    expect(screen.queryByRole("button", { name: /approve/i })).not.toBeInTheDocument()
  })

  it("folds a long group behind a count and expands on request", () => {
    const many = Array.from({ length: 9 }, (_, i) =>
      awaitingCase({ case_id: `510000000${i}-2026`, updated_at: hoursAgo(i + 1) })
    )
    renderPanel(many)
    expect(screen.getAllByTitle("Since we last touched the case")).toHaveLength(6)
    fireEvent.click(screen.getByText(/3 more/))
    expect(screen.getAllByTitle("Since we last touched the case")).toHaveLength(9)
  })
})

describe("HandoverPanel empty window", () => {
  it("says nothing happened, not that there is nothing to show", () => {
    renderPanel([])
    expect(screen.getByText(/No cases were processed in this window/)).toBeInTheDocument()
    expect(screen.getByText(/wait for the poller/)).toBeInTheDocument()
  })

  it("points at the seeding route only when that route exists", () => {
    renderPanel([], { testDataEnabled: true })
    expect(screen.getByText(/Seed exceptions from Test Data/)).toBeInTheDocument()
  })
})

describe("HandoverPanel window", () => {
  it("remembers the chosen window across mounts", () => {
    localStorage.setItem("workspace.handoverHours", "1")
    // A case older than the stored window has to fall out of it, or the pref is decorative.
    renderPanel([awaitingCase({ updated_at: hoursAgo(5) })])
    expect(screen.getByText(/No cases were processed in this window/)).toBeInTheDocument()
  })
})
