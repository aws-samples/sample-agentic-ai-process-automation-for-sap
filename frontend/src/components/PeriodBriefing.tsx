// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { Link } from "react-router"
import { CaseStatus } from "@/types/cases"
import type { WorkItem } from "@/types/cases"
import { digest, windowProse, UNKNOWN_CURRENCY } from "@/lib/digest"
import { formatAmount } from "@/lib/domainFields"

/**
 * What the period amounted to, in a sentence, above the charts.
 *
 * The charts answer "how is the system running"; this answers "what did the agent get
 * done", which is the question the page is opened with. So it states the outcome and
 * the charts below stay as the drill-down.
 *
 * Derived from `lib/digest.ts` — the same function the shift handover renders, so the
 * two surfaces cannot report different numbers for the same window. Nothing here calls
 * a model: the figures are deterministic from stored cases.
 */

/** Bold, tabular figure — these sit mid-sentence, where a shifting width is a jitter. */
function N({ children }: { children: React.ReactNode }) {
  return <span className="font-semibold tabular-nums">{children}</span>
}

/** A count that routes to the workspace filtered to that status, which already reads `?status=`. */
function CountLink({ count, status }: { count: number; status: CaseStatus }) {
  return (
    <Link to={`/?status=${status}`} className="underline decoration-dotted hover:decoration-solid">
      <N>{count}</N>
    </Link>
  )
}

export interface PeriodBriefingProps {
  /** Every case, unfiltered — the digest applies the window itself. */
  cases: WorkItem[]
  /** Hours, as the Analytics selector holds it. */
  hours: string
  /**
   * Whether the case query has settled. False covers both "first fetch in flight" and
   * "the fetch failed": neither is grounds for stating that nothing happened.
   */
  known: boolean
}

export function PeriodBriefing({ cases, hours, known }: PeriodBriefingProps) {
  const period = windowProse(hours)

  if (!known) {
    return (
      <Briefing>
        <p className="text-sm text-muted-foreground">
          What the agent did in the {period} is unavailable — the briefing reads the case list, and
          it has not loaded.
        </p>
      </Briefing>
    )
  }

  const d = digest(cases, Number(hours))

  if (d.total === 0) {
    return (
      <Briefing>
        <p className="text-sm">No cases were processed in the {period}.</p>
        <p className="text-xs text-muted-foreground">
          The charts below cover the same period, so they are empty too. Widen the window, or wait
          for the poller's next run.
        </p>
      </Briefing>
    )
  }

  const valueParts = [...d.postedValue.entries()].map(([currency, total]) =>
    currency === UNKNOWN_CURRENCY
      ? `${formatAmount(total)} (currency not recorded)`
      : formatAmount(total, currency)
  )

  return (
    <Briefing>
      <p className="text-sm leading-relaxed">
        In the {period} the agent cleared <N>{d.postedCount}</N> of <N>{d.total}</N>{" "}
        {d.total === 1 ? "case" : "cases"} without a human.{" "}
        {d.waitingCount === 0 && d.blocked.length === 0 ? (
          "Nothing is waiting on a person and nothing is blocked."
        ) : (
          <>
            {d.waitingCount > 0 && (
              <>
                <CountLink count={d.waitingCount} status={CaseStatus.AwaitingHumanInput} />{" "}
                {d.waitingCount === 1 ? "is" : "are"} waiting on someone
              </>
            )}
            {d.waitingCount > 0 && d.blocked.length > 0 && "; "}
            {d.blocked.length > 0 && (
              <>
                <CountLink count={d.blocked.length} status={CaseStatus.ManualReviewRequired} />{" "}
                could not be cleared
              </>
            )}
            .
          </>
        )}
      </p>
      <p className="text-xs text-muted-foreground">
        {/* "Gross invoice value posted", not "value accrued": the poller reads
            InvoiceGrossAmount, and abs_decimal discards the sign, so this is throughput
            and a credit memo adds rather than subtracts. */}
        {valueParts.length > 0
          ? `${valueParts.join(" · ")} gross invoice value posted`
          : "No amounts on the posted cases"}
        {d.signUnknown && " (gross, unsigned)"}
        {d.valuePartial && " · some posted cases carry no amount"}
        {" · "}
        <span title="Lifetime cost of the cases touched in this window — the cost chart below is the window's own spend">
          {formatAmount(d.spend, "USD")} agent spend
        </span>
        {d.spendPartial && " (at least — some cases have no recorded cost)"}
      </p>
    </Briefing>
  )
}

function Briefing({ children }: { children: React.ReactNode }) {
  return (
    <section aria-label="Period briefing" className="space-y-1">
      {children}
    </section>
  )
}
