// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { render, screen, cleanup } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { PeriodBriefing } from "@/components/PeriodBriefing"
import { CaseStatus, Domain, Trigger } from "@/types/cases"
import type { WorkItem } from "@/types/cases"

/**
 * X.6's exit condition is a claim about order — prose before any chart — and about what
 * the prose is allowed to assert. So: that the sentence states the period's outcome,
 * that a window with nothing in it says so rather than reading as a load, and that a
 * figure the data cannot support arrives with its caveat attached.
 */

const NOW = Date.parse("2026-07-31T12:00:00Z")
const hoursAgo = (h: number) => new Date(NOW - h * 3_600_000).toISOString()

function caseAt(overrides: Partial<WorkItem> = {}): WorkItem {
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

const posted = (overrides: Partial<WorkItem> = {}) =>
  caseAt({ status: CaseStatus.Complete, ...overrides })

function renderBriefing(
  cases: WorkItem[],
  props: Partial<Parameters<typeof PeriodBriefing>[0]> = {}
) {
  return render(
    <MemoryRouter>
      <PeriodBriefing cases={cases} hours="24" known={true} {...props} />
    </MemoryRouter>
  )
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(NOW)
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe("PeriodBriefing sentence", () => {
  it("states the period's outcome in prose, naming the window", () => {
    renderBriefing([
      posted({ case_id: "a" }),
      posted({ case_id: "b" }),
      caseAt({ case_id: "c" }),
      caseAt({ case_id: "d", status: CaseStatus.ManualReviewRequired }),
    ])
    const sentence = screen.getByText(/cleared/).textContent ?? ""
    expect(sentence).toContain("last 24 hours")
    expect(sentence).toContain("2")
    expect(sentence).toContain("4")
    expect(sentence).toMatch(/waiting on someone/)
    expect(sentence).toMatch(/could not be cleared/)
  })

  it("describes the window the selector is on, not a fixed one", () => {
    renderBriefing([posted()], { hours: "1" })
    // The case is 2h old, so the 1h window is genuinely empty — the period has to
    // change with the selector or the briefing and the charts describe different spans.
    expect(screen.getByText(/No cases were processed in the last hour/)).toBeInTheDocument()
  })

  it("says so plainly when there is nothing waiting or blocked", () => {
    renderBriefing([posted()])
    expect(screen.getByText(/Nothing is waiting on a person/)).toBeInTheDocument()
  })

  it("links a waiting count to the workspace filtered to that status", () => {
    renderBriefing([caseAt()])
    expect(screen.getByRole("link", { name: "1" })).toHaveAttribute(
      "href",
      "/?status=awaiting_human_input"
    )
  })
})

describe("PeriodBriefing honesty flags", () => {
  it("keeps currencies apart and marks the total unsigned", () => {
    renderBriefing([
      posted({ case_id: "a", amount: 100, currency: "USD" }),
      posted({ case_id: "b", amount: 200, currency: "EUR" }),
    ])
    const line = screen.getByText(/gross invoice value posted/)
    expect(line.textContent).toContain("$100.00")
    expect(line.textContent).toContain("200.00 EUR")
    expect(line.textContent).toContain("(gross, unsigned)")
  })

  it("calls the value under-counted when a posted case carries no amount", () => {
    renderBriefing([posted({ case_id: "a", amount: 100 }), posted({ case_id: "b", amount: null })])
    expect(screen.getByText(/some posted cases carry no amount/)).toBeInTheDocument()
  })

  it("calls the spend a floor when a case recorded no cost", () => {
    renderBriefing([caseAt({ cost_summary: undefined })])
    expect(screen.getByText(/some cases have no recorded cost/)).toBeInTheDocument()
  })

  it("counts only what the agent cleared, not everything that ended complete", () => {
    // A case a human approved through a ticket also ends complete. Counting it as
    // cleared-without-a-human is the one number on this page that would overstate the
    // agent, so the trigger — not the status — decides.
    renderBriefing([
      posted({ case_id: "a" }),
      posted({
        case_id: "b",
        agent_traces: [
          { trace_id: "t2", timestamp: hoursAgo(1), segments: [], trigger: Trigger.TicketAction },
        ],
      }),
    ])
    expect(screen.getByText(/cleared/).textContent).toMatch(/cleared\s*1\s*of\s*2/)
  })
})

describe("PeriodBriefing zero and unknown states", () => {
  it("states that nothing happened rather than showing an empty frame", () => {
    renderBriefing([])
    expect(screen.getByText(/No cases were processed in the last 24 hours/)).toBeInTheDocument()
  })

  it("does not claim nothing happened while the case list is unknown", () => {
    // A failed or in-flight fetch renders zero cases. Reporting that as "no activity"
    // would state an outcome the page has no grounds for.
    renderBriefing([], { known: false })
    expect(screen.queryByText(/No cases were processed/)).not.toBeInTheDocument()
    expect(screen.getByText(/has not loaded/)).toBeInTheDocument()
  })
})
