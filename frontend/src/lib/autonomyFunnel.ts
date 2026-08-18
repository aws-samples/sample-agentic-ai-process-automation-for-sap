// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { CaseStatus, Trigger } from "@/types/cases"
import type { WorkItem } from "@/types/cases"

/**
 * How far the agent got on its own, not how often it was triggered.
 *
 * The poller runs on its schedule in either mode and writes every new case as
 * `detected`; only the enqueue is gated on `trigger-mode`. So a count of poller
 * invocations is evidence of scheduling, not of autonomy — three runs that all
 * escalated to a human render identically to three that posted to SAP clean.
 *
 * This splits the two questions the two modes actually ask: in `manual`, how much is
 * piling up that a human has to click through; in `auto`, of what was picked up, how
 * far did it get. Both come off the same `GET /cases` the rail already polls.
 */

export interface AutonomyFunnel {
  /** `detected` — un-started, and the cost of staying in manual. */
  backlog: number

  /** Distinct cases with ≥1 poller-triggered run in the window. The denominator. */
  started: number

  /** `sap_updated` / `complete` — reached without a further agent run. */
  landed: number

  /** `awaiting_human_input` / `manual_review_required`. The SOP said stop — neutral. */
  escalated: number

  /** `error`. */
  failed: number

  /** `processing` — picked up, outcome not yet known. */
  inFlight: number

  /**
   * A status the funnel cannot attribute an outcome to. Real pipeline data carries
   * values the schema does not permit (`resolved`, `investigating`, `analyzing` were
   * 16% of a 50-case benchmark), and a started case still reading `detected`
   * contradicts itself. Neither may be folded into a bucket that implies a fact.
   */
  unrecognised: number

  /** Most recent poller-triggered run in the window, ISO, or null. */
  latest: string | null

  /**
   * True when a case has no traces at all, or `traces_dropped` shows history was
   * evicted. Its runs cannot be attributed to a trigger, so `started` is a floor.
   */
  partial: boolean
}

/**
 * Bucket the autonomous population by where it stopped.
 *
 * @param cases - Whole case records, as `GET /cases` returns them.
 * @param sinceHours - Window width for the funnel. `backlog` ignores it.
 */
export function autonomyFunnel(cases: WorkItem[], sinceHours: number): AutonomyFunnel {
  const cutoff = Date.now() - sinceHours * 3_600_000
  const f: AutonomyFunnel = {
    backlog: 0,
    started: 0,
    landed: 0,
    escalated: 0,
    failed: 0,
    inFlight: 0,
    unrecognised: 0,
    latest: null,
    partial: false,
  }

  for (const c of cases) {
    // Deliberately not windowed. A case detected three days ago and never processed is
    // still in the inbox; ageing it out would let the backlog shrink by neglect.
    if (c.status === CaseStatus.Detected) f.backlog += 1

    const traces = Array.isArray(c.agent_traces) ? c.agent_traces : []
    // A case with no traces is unattributable, not inactive: `traces_dropped` means
    // T.1's cap evicted history that may well have been poller-triggered.
    if (traces.length === 0 || (c.traces_dropped ?? 0) > 0) f.partial = true

    let latestPoller: string | null = null
    let newestAt = -Infinity
    let newestIsPoller = false

    for (const t of traces) {
      // Filter on the trace's own timestamp, not the case's `updated_at`. A case last
      // touched by a human approval an hour ago may hold a poller run from yesterday,
      // and attributing that run's outcome to this window overstates what auto just did.
      const at = Date.parse(t.timestamp ?? "")
      if (!Number.isFinite(at)) continue
      if (at >= newestAt) {
        newestAt = at
        newestIsPoller = t.trigger === Trigger.Poller
      }
      if (t.trigger !== Trigger.Poller || at < cutoff) continue
      if (!latestPoller || (t.timestamp ?? "") > latestPoller) latestPoller = t.timestamp ?? null
    }

    // `status` is the case's *current* status, not the one the autonomous run left it
    // in. A human approval produces its own trace (`ticket-action` / `manual`), so a
    // newer non-poller trace means the case has left the autonomous population — that
    // is what stops a human's `complete` being credited to the agent. Distinct cases,
    // not traces: a re-invoked case is one thing that went somewhere, and its status
    // is singular.
    if (!latestPoller || !newestIsPoller) continue
    f.started += 1
    if (!f.latest || latestPoller > f.latest) f.latest = latestPoller

    if (c.status === CaseStatus.SapUpdated || c.status === CaseStatus.Complete) f.landed += 1
    else if (
      c.status === CaseStatus.AwaitingHumanInput ||
      c.status === CaseStatus.ManualReviewRequired
    )
      f.escalated += 1
    else if (c.status === CaseStatus.Error) f.failed += 1
    else if (c.status === CaseStatus.Processing) f.inFlight += 1
    // Catch-all last, so the buckets partition `started` by construction rather than
    // by hoping the enum is exhaustive — which the real data says it is not.
    else f.unrecognised += 1
  }

  return f
}
