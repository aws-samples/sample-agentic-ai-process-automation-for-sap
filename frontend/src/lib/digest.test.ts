// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { digest, UNKNOWN_CURRENCY, UNRECORDED_OWNER } from "@/lib/digest"
import { CaseStatus, Domain, Trigger } from "@/types/cases"
import type { AgentTrace, WorkItem } from "@/types/cases"
import type { Ticket } from "@/types/tickets"

/**
 * Every figure the handover renders comes from here, so this is where the honesty
 * rules are pinned: a case a human approved is not "posted without a human", two
 * currencies are not one total, and an unassigned ticket is not an owner.
 */

const NOW = Date.parse("2026-07-31T12:00:00Z")
const hoursAgo = (h: number) => new Date(NOW - h * 3_600_000).toISOString()

function trace(overrides: Partial<AgentTrace> = {}): AgentTrace {
  return {
    trace_id: "t1",
    timestamp: hoursAgo(1),
    segments: [],
    trigger: Trigger.Poller,
    ...overrides,
  }
}

function makeCase(overrides: Partial<WorkItem> = {}): WorkItem {
  return {
    case_id: "5100000001-2026",
    document_number: "5100000001",
    item_id: "2026",
    domain: Domain.FinanceAp,
    process_type: "price_variance",
    status: CaseStatus.Complete,
    created_at: hoursAgo(3),
    updated_at: hoursAgo(1),
    agent_traces: [trace()],
    cost_summary: { total_cost_usd: 0.05 },
    ...overrides,
  } as WorkItem
}

function makeTicket(overrides: Partial<Ticket> = {}): Ticket {
  return {
    ticket_id: "TKT-1",
    title: "Price variance above tolerance",
    status: "open",
    priority: "medium",
    created_by: "agent",
    created_at: hoursAgo(2),
    updated_at: hoursAgo(2),
    ...overrides,
  } as Ticket
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(NOW)
})
afterEach(() => vi.useRealTimers())

describe("digest window", () => {
  it("counts only cases touched inside the window", () => {
    const d = digest([makeCase(), makeCase({ case_id: "old", updated_at: hoursAgo(48) })], 24)
    expect(d.total).toBe(1)
  })

  it("reports zero rather than throwing on an unparseable updated_at", () => {
    const d = digest([makeCase({ updated_at: "not a date" })], 24)
    expect(d.total).toBe(0)
  })
})

describe("digest posted", () => {
  it("counts a terminal case the poller drove", () => {
    const d = digest([makeCase({ status: CaseStatus.SapUpdated })], 24)
    expect(d.postedCount).toBe(1)
  })

  it("does not count a terminal case a human drove through a ticket", () => {
    // Both end `complete`; only the last run's trigger distinguishes them, and calling
    // an approved case "posted without a human" is the claim that matters most here.
    const d = digest([makeCase({ agent_traces: [trace({ trigger: Trigger.TicketAction })] })], 24)
    expect(d.postedCount).toBe(0)
  })

  it("judges by the most recent trace, not the first", () => {
    const d = digest(
      [
        makeCase({
          agent_traces: [
            trace({ trace_id: "first", timestamp: hoursAgo(5), trigger: Trigger.Poller }),
            trace({ trace_id: "second", timestamp: hoursAgo(1), trigger: Trigger.Manual }),
          ],
        }),
      ],
      24
    )
    expect(d.postedCount).toBe(0)
  })

  it("does not count a case that has never been run", () => {
    const d = digest([makeCase({ agent_traces: [] })], 24)
    expect(d.postedCount).toBe(0)
  })

  it("excludes an errored case from posted", () => {
    const d = digest([makeCase({ status: CaseStatus.Error })], 24)
    expect(d.postedCount).toBe(0)
    expect(d.total).toBe(1)
  })

  it("groups value by currency instead of summing across them", () => {
    const d = digest(
      [
        makeCase({ amount: 100, currency: "USD" }),
        makeCase({ case_id: "b", amount: 50, currency: "USD" }),
        makeCase({ case_id: "c", amount: 200, currency: "EUR" }),
      ],
      24
    )
    expect([...d.postedValue.entries()].sort()).toEqual([
      ["EUR", 200],
      ["USD", 150],
    ])
  })

  it("buckets an amount with no currency rather than assuming dollars", () => {
    const d = digest([makeCase({ amount: 100, currency: undefined })], 24)
    expect(d.postedValue.get(UNKNOWN_CURRENCY)).toBe(100)
  })

  it("flags the total as unsigned whenever any amount contributed", () => {
    // `abs_decimal` discarded the sign upstream, so a credit memo added rather than
    // subtracted and the figure is a magnitude.
    expect(digest([makeCase({ amount: 100 })], 24).signUnknown).toBe(true)
    expect(digest([makeCase({ amount: undefined })], 24).signUnknown).toBe(false)
  })

  it("flags value as partial when a posted case carries no amount", () => {
    const d = digest(
      [
        makeCase({ amount: 100, currency: "USD" }),
        makeCase({ case_id: "b", amount: undefined, currency: "USD" }),
      ],
      24
    )
    // The amount-less case contributes nothing at all — no zero row, no bucket of its own.
    expect(d.postedValue.get(UNKNOWN_CURRENCY)).toBeUndefined()
    expect(d.postedValue.get("USD")).toBe(100)
    expect(d.postedCount).toBe(2)
    expect(d.valuePartial).toBe(true)
  })
})

describe("digest spend", () => {
  it("sums recorded cost across every case in the window", () => {
    const d = digest(
      [makeCase(), makeCase({ case_id: "b", cost_summary: { total_cost_usd: 0.25 } })],
      24
    )
    expect(d.spend).toBeCloseTo(0.3)
    expect(d.spendPartial).toBe(false)
  })

  it("calls the total a floor when a case has no cost_summary", () => {
    const d = digest([makeCase({ cost_summary: undefined })], 24)
    expect(d.spend).toBe(0)
    expect(d.spendPartial).toBe(true)
  })
})

describe("digest waiting groups", () => {
  const awaiting = (caseId: string, ticketId?: string, extra: Partial<WorkItem> = {}) =>
    makeCase({
      case_id: caseId,
      status: CaseStatus.AwaitingHumanInput,
      ticket_id: ticketId,
      ...extra,
    })

  it("groups by the ticket's assignee", () => {
    const d = digest([awaiting("a", "TKT-1"), awaiting("b", "TKT-1"), awaiting("c", "TKT-2")], 24, [
      makeTicket({ ticket_id: "TKT-1", assigned_to: "dana@example.com" }),
      makeTicket({ ticket_id: "TKT-2", assigned_to: "sam@example.com" }),
    ])
    expect(d.waiting.map(g => [g.label, g.ownerKnown, g.rows.length])).toEqual([
      ["dana@example.com", true, 2],
      ["sam@example.com", true, 1],
    ])
    expect(d.waitingCount).toBe(3)
  })

  it("does not invent an owner for an awaiting case with no ticket", () => {
    const d = digest([awaiting("a")], 24, [])
    expect(d.waiting).toEqual([
      expect.objectContaining({ label: UNRECORDED_OWNER, ownerKnown: false }),
    ])
  })

  it("does not invent an owner for a ticket nobody is assigned to", () => {
    const d = digest([awaiting("a", "TKT-1")], 24, [makeTicket({ assigned_to: undefined })])
    expect(d.waiting[0].label).toBe(UNRECORDED_OWNER)
    expect(d.waiting[0].ownerKnown).toBe(false)
    // Having tickets and none assigned is still ticket data — not the no-ticketing fallback.
    expect(d.groupedByProcess).toBe(false)
  })

  it("falls back to process type and says so when there is no ticket data at all", () => {
    const d = digest([awaiting("a", "TKT-1", { process_type: "quantity_variance" })], 24)
    expect(d.groupedByProcess).toBe(true)
    expect(d.waiting[0].label).toBe("quantity_variance")
    expect(d.waiting[0].ownerKnown).toBe(false)
  })

  it("sinks the unowned group below every real owner", () => {
    const d = digest([awaiting("a"), awaiting("b"), awaiting("c", "TKT-1")], 24, [
      makeTicket({ ticket_id: "TKT-1", assigned_to: "dana@example.com" }),
    ])
    // The unowned group is larger, and still last: it is a data gap, not the top queue.
    expect(d.waiting.map(g => g.label)).toEqual(["dana@example.com", UNRECORDED_OWNER])
  })

  it("orders rows oldest first", () => {
    const d = digest(
      [
        awaiting("recent", undefined, { updated_at: hoursAgo(1) }),
        awaiting("stale", undefined, { updated_at: hoursAgo(20) }),
      ],
      24,
      []
    )
    expect(d.waiting[0].rows.map(r => r.caseId)).toEqual(["stale", "recent"])
  })

  it("ages off the inquiry when one was sent, and names that source", () => {
    const d = digest(
      [awaiting("a", undefined, { inquiry_sent_at: hoursAgo(6), updated_at: hoursAgo(1) })],
      24,
      []
    )
    expect(d.waiting[0].rows[0]).toMatchObject({
      since: hoursAgo(6),
      ageSource: "inquiry",
    })
  })

  it("falls back to last activity and says that is what it is", () => {
    const d = digest([awaiting("a", undefined, { updated_at: hoursAgo(2) })], 24, [])
    expect(d.waiting[0].rows[0]).toMatchObject({
      since: hoursAgo(2),
      ageSource: "activity",
    })
  })
})

describe("digest blocked", () => {
  it("lists cases needing manual review with the run's outcome as the reason", () => {
    const d = digest(
      [
        makeCase({
          status: CaseStatus.ManualReviewRequired,
          agent_traces: [trace({ outcome: "error" })],
        }),
      ],
      24
    )
    expect(d.blocked).toEqual([expect.objectContaining({ reason: "error" })])
  })

  it("says no reason was recorded rather than leaving the cell blank", () => {
    const d = digest([makeCase({ status: CaseStatus.ManualReviewRequired, agent_traces: [] })], 24)
    expect(d.blocked[0].reason).toBe("no reason recorded")
  })
})
