// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest"
import { autonomyFunnel } from "@/lib/autonomyFunnel"
import { CaseStatus, Trigger } from "@/types/cases"
import type { WorkItem } from "@/types/cases"

/**
 * The readout is the governor's only claim that a setting cannot also make, so what is
 * pinned here is every way it could overstate what ran unattended: counting a run a
 * human asked for, counting an old run because the case was touched recently, crediting
 * a human's approval to the agent, or reporting a floor as a total.
 *
 * Escalation is the modal outcome in real data (24 of 50 in the AP cost benchmark), not
 * an exception — so it is its own bucket, and the buckets must partition rather than
 * assume the status enum is exhaustive. That same sample carries three statuses the
 * schema does not permit, which is why `unrecognised` exists.
 */

const hoursAgo = (n: number) => new Date(Date.now() - n * 3_600_000).toISOString()

function caseWith(
  id: string,
  status: string,
  traces: { trigger?: string; at: string }[],
  extra = {}
): WorkItem {
  return {
    case_id: id,
    status,
    updated_at: hoursAgo(0),
    agent_traces: traces.map((t, i) => ({
      trace_id: `${id}-${i}`,
      timestamp: t.at,
      trigger: t.trigger,
      segments: [],
    })),
    ...extra,
  } as unknown as WorkItem
}

/** The common shape: one poller run inside the window. */
const started = (id: string, status: string, extra = {}) =>
  caseWith(id, status, [{ trigger: Trigger.Poller, at: hoursAgo(2) }], extra)

describe("autonomyFunnel", () => {
  it("counts distinct cases the poller started", () => {
    const f = autonomyFunnel(
      [started("a", CaseStatus.Complete), started("b", CaseStatus.Error)],
      24
    )
    expect(f.started).toBe(2)
    expect(f.partial).toBe(false)
  })

  it("ignores runs a human asked for", () => {
    // Unattended work is the whole claim. A manual invocation counted here would let a
    // manual-mode deployment report a funnel.
    const f = autonomyFunnel(
      [caseWith("a", CaseStatus.Complete, [{ trigger: Trigger.Manual, at: hoursAgo(1) }])],
      24
    )
    expect(f.started).toBe(0)
    expect(f.landed).toBe(0)
    expect(f.latest).toBeNull()
  })

  it("filters on the trace timestamp, not the case's updated_at", () => {
    const f = autonomyFunnel(
      [
        caseWith("a", CaseStatus.Complete, [{ trigger: Trigger.Poller, at: hoursAgo(50) }], {
          updated_at: hoursAgo(0),
        }),
      ],
      24
    )
    expect(f.started).toBe(0)
  })

  it("two poller runs on one case are one started case", () => {
    // Traces are not the denominator: a re-invoked case is one thing that went
    // somewhere, and its status is singular.
    const f = autonomyFunnel(
      [
        caseWith("a", CaseStatus.Complete, [
          { trigger: Trigger.Poller, at: hoursAgo(3) },
          { trigger: Trigger.Poller, at: hoursAgo(1) },
        ]),
      ],
      24
    )
    expect(f.started).toBe(1)
    expect(f.landed).toBe(1)
  })

  it("reports the most recent poller run", () => {
    const recent = hoursAgo(1)
    const f = autonomyFunnel(
      [
        caseWith("a", CaseStatus.Complete, [
          { trigger: Trigger.Poller, at: hoursAgo(9) },
          { trigger: Trigger.Poller, at: recent },
        ]),
      ],
      24
    )
    expect(f.latest).toBe(recent)
  })

  it("flags partial when a case has no traces to attribute", () => {
    const f = autonomyFunnel([caseWith("a", CaseStatus.Complete, [])], 24)
    expect(f.started).toBe(0)
    // Zero here means "we cannot say", which the panel has to tell apart from a
    // grounded zero or the governor under-states what it has been doing.
    expect(f.partial).toBe(true)
  })

  it("flags partial when trace history was evicted", () => {
    const f = autonomyFunnel([started("a", CaseStatus.Complete, { traces_dropped: 3 })], 24)
    expect(f.started).toBe(1)
    expect(f.partial).toBe(true)
  })

  it("a trace with no timestamp is not counted", () => {
    const f = autonomyFunnel(
      [caseWith("a", CaseStatus.Complete, [{ trigger: Trigger.Poller, at: "" }])],
      24
    )
    expect(f.started).toBe(0)
  })

  it("counts the detected backlog regardless of the window", () => {
    // The backlog is what makes arming auto a considered decision. Ageing a stale case
    // out of it would let the number shrink by neglect.
    const f = autonomyFunnel(
      [
        caseWith("a", CaseStatus.Detected, [], { updated_at: hoursAgo(200) }),
        caseWith("b", CaseStatus.Detected, [], { updated_at: hoursAgo(1) }),
      ],
      24
    )
    expect(f.backlog).toBe(2)
  })

  it("groups both escalation statuses, and neither is a failure", () => {
    const f = autonomyFunnel(
      [
        started("a", CaseStatus.AwaitingHumanInput),
        started("b", CaseStatus.ManualReviewRequired),
        started("c", CaseStatus.Error),
      ],
      24
    )
    expect(f.escalated).toBe(2)
    expect(f.failed).toBe(1)
  })

  it("an off-enum status is unrecognised, not landed and not failed", () => {
    // `resolved` was 6 of 50 in the benchmark. A switch whose default implies an
    // outcome would invent one for 16% of real cases.
    const f = autonomyFunnel([started("a", "resolved")], 24)
    expect(f.unrecognised).toBe(1)
    expect(f.landed).toBe(0)
    expect(f.failed).toBe(0)
  })

  it("processing is in flight, never landed", () => {
    // `agent_invoker` writes `processing` before invoking, so it means "picked up" —
    // either running now or abandoned mid-run, indistinguishable from status alone.
    const f = autonomyFunnel([started("a", CaseStatus.Processing)], 24)
    expect(f.inFlight).toBe(1)
    expect(f.landed).toBe(0)
  })

  it("a case a human then acted on leaves the autonomous population", () => {
    // The overstatement this shape exists to prevent: the poller starts a case, a human
    // approves it to `complete`, and a naive read credits that to autonomy.
    const f = autonomyFunnel(
      [
        caseWith("a", CaseStatus.Complete, [
          { trigger: Trigger.Poller, at: hoursAgo(3) },
          { trigger: Trigger.TicketAction, at: hoursAgo(1) },
        ]),
      ],
      24
    )
    expect(f.started).toBe(0)
    expect(f.landed).toBe(0)
  })

  it("the buckets partition the started population", () => {
    const f = autonomyFunnel(
      [
        started("a", CaseStatus.Complete),
        started("b", CaseStatus.SapUpdated),
        started("c", CaseStatus.AwaitingHumanInput),
        started("d", CaseStatus.Error),
        started("e", CaseStatus.Processing),
        started("f", "investigating"),
        // A started case still reading `detected` contradicts itself — it must land
        // somewhere countable rather than vanish from the funnel's arithmetic.
        started("g", CaseStatus.Detected),
      ],
      24
    )
    expect(f.landed + f.escalated + f.failed + f.inFlight + f.unrecognised).toBe(f.started)
    expect(f.started).toBe(7)
  })
})
