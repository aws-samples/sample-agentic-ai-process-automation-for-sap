// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useState } from "react"
import { ChevronDown, ChevronRight, RefreshCw } from "lucide-react"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { EmptyState } from "@/components/ui/page-chrome"
import type { WorkItem } from "@/types/cases"
import type { Ticket } from "@/types/tickets"
import { digest, WINDOWS, UNKNOWN_CURRENCY, type DigestGroup, type DigestRow } from "@/lib/digest"
import { formatAmount } from "@/lib/domainFields"
import { shortAge } from "@/lib/timeAgo"

/**
 * What happened while you were away, as the queue it actually is.
 *
 * The AP benchmark puts 24 of 32 cases in `awaiting_human_input` — the SOPs escalate
 * every above-tolerance variance — so this is not a retrospective with a to-do list
 * underneath. The waiting groups are the body; what the agent cleared collapses to a
 * count.
 *
 * Rows navigate and nothing more. Approval lives in the case detail, where both
 * buttons stay disabled until the reviewer writes a reason; a second approval surface
 * here would either bypass that or duplicate it.
 *
 * The rail already states blocked / needs-you / working as numbers. This panel's
 * contribution is the rows and who holds them.
 */

const HOURS_KEY = "workspace.handoverHours"

function Row({ row, onOpen }: { row: DigestRow; onOpen: (caseId: string) => void }) {
  return (
    <button
      onClick={() => onOpen(row.caseId)}
      className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-accent/60"
    >
      <span className="w-36 flex-none truncate font-medium">{row.caseId}</span>
      <span className="w-24 flex-none text-right tabular-nums">
        {formatAmount(row.amount, row.currency)}
      </span>
      <span className="flex-1 truncate text-muted-foreground">{row.reason}</span>
      {/* The age label names its own source. `inquiry_sent_at` means someone was asked
          then; `updated_at` only means we wrote the record then, and calling that a wait
          is the claim this panel could most easily make without grounds. */}
      <span
        className="w-20 flex-none text-right tabular-nums text-muted-foreground"
        title={
          row.ageSource === "inquiry"
            ? "Since the inquiry was sent"
            : "Since we last touched the case"
        }
      >
        {row.ageSource === "inquiry" ? "waiting " : "activity "}
        {shortAge(row.since)}
      </span>
    </button>
  )
}

function SectionHeader({ title, count }: { title: string; count: number }) {
  return (
    <div className="flex items-center gap-2 border-b bg-muted/40 px-3 py-1">
      <span className="text-2xs font-semibold uppercase tracking-wider text-muted-foreground">
        {title}
      </span>
      <span className="ml-auto text-2xs font-medium tabular-nums text-muted-foreground">
        {count}
      </span>
    </div>
  )
}

/** Rows past this per group fold behind a "… N more" — the panel is a glance, not a list. */
const ROWS_PER_GROUP = 6

function Group({ group, onOpen }: { group: DigestGroup; onOpen: (caseId: string) => void }) {
  const [expanded, setExpanded] = useState(false)
  const shown = expanded ? group.rows : group.rows.slice(0, ROWS_PER_GROUP)
  const hidden = group.rows.length - shown.length

  return (
    <div>
      <SectionHeader
        title={group.ownerKnown ? `Waiting on ${group.label}` : `Waiting — ${group.label}`}
        count={group.rows.length}
      />
      {shown.map(row => (
        <Row key={row.caseId} row={row} onOpen={onOpen} />
      ))}
      {hidden > 0 && (
        <button
          onClick={() => setExpanded(true)}
          className="w-full px-3 py-1 text-left text-2xs text-muted-foreground hover:text-foreground"
        >
          … {hidden} more
        </button>
      )}
    </div>
  )
}

export interface HandoverPanelProps {
  cases: WorkItem[]
  /** Undefined when ticketing is off — the digest then groups by process type and says so. */
  tickets?: Ticket[]
  loading: boolean
  onRefresh: () => void
  onOpenCase: (caseId: string) => void
  /** Whether the test-data route exists, for the zero-case hint. */
  testDataEnabled: boolean
}

export function HandoverPanel({
  cases,
  tickets,
  loading,
  onRefresh,
  onOpenCase,
  testDataEnabled,
}: HandoverPanelProps) {
  const [hours, setHours] = useState(() => localStorage.getItem(HOURS_KEY) ?? "24")
  const setWindow = (next: string) => {
    localStorage.setItem(HOURS_KEY, next)
    setHours(next)
  }

  const d = digest(cases, Number(hours), tickets)
  const [postedOpen, setPostedOpen] = useState(false)

  const valueParts = [...d.postedValue.entries()].map(([currency, total]) =>
    currency === UNKNOWN_CURRENCY
      ? `${formatAmount(total)} (currency not recorded)`
      : formatAmount(total, currency)
  )

  return (
    <div className="flex h-full flex-col overflow-auto border-r">
      <div className="flex flex-none items-center justify-between gap-2 border-b px-3 py-2">
        <Select value={hours} onValueChange={setWindow}>
          <SelectTrigger className="h-7 w-28 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {WINDOWS.map(w => (
              <SelectItem key={w.value} value={w.value}>
                {w.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <button
          onClick={onRefresh}
          disabled={loading}
          className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-50"
          title="Refresh"
          aria-label="Refresh handover"
        >
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      {d.total === 0 ? (
        <EmptyState
          message="No cases were processed in this window."
          hint={
            testDataEnabled
              ? "Seed exceptions from Test Data, or widen the window above."
              : "Widen the window above, or wait for the poller's next run."
          }
        />
      ) : (
        <>
          <div className="flex-none space-y-1 border-b px-3 py-3">
            <p className="text-sm">
              <span className="font-semibold tabular-nums">{d.postedCount}</span> posted without a
              human · <span className="font-semibold tabular-nums">{d.waitingCount}</span> waiting
              on someone · <span className="font-semibold tabular-nums">{d.blocked.length}</span>{" "}
              blocked
            </p>
            <p className="text-xs text-muted-foreground">
              {/* "Gross invoice value posted", not "value accrued": the poller reads
                  InvoiceGrossAmount, so this is throughput. And abs_decimal discards the
                  sign, so a credit memo adds rather than subtracts. */}
              {valueParts.length > 0
                ? `${valueParts.join(" · ")} gross invoice value posted`
                : "No amounts on the posted cases"}
              {d.signUnknown && " (gross, unsigned)"}
              {d.valuePartial && " · some posted cases carry no amount"}
              {" · "}
              {formatAmount(d.spend, "USD")} agent spend
              {d.spendPartial && " (at least — some cases have no recorded cost)"}
            </p>
            {d.groupedByProcess && (
              <p className="text-2xs text-muted-foreground">
                Grouped by process type: ticketing is disabled, so no recipient was recorded.
              </p>
            )}
          </div>

          <div className="flex-1">
            {d.waiting.map(g => (
              <Group key={g.label} group={g} onOpen={onOpenCase} />
            ))}

            {d.blocked.length > 0 && (
              <div>
                <SectionHeader title="Blocked" count={d.blocked.length} />
                {d.blocked.map(row => (
                  <Row key={row.caseId} row={row} onOpen={onOpenCase} />
                ))}
              </div>
            )}

            {d.postedCount > 0 && (
              <div>
                <button
                  onClick={() => setPostedOpen(v => !v)}
                  className="flex w-full items-center gap-1 border-b bg-muted/40 px-3 py-1 text-left"
                  aria-expanded={postedOpen}
                >
                  {postedOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                  <span className="text-2xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Posted without a human
                  </span>
                  <span className="ml-auto text-2xs font-medium tabular-nums text-muted-foreground">
                    {d.postedCount}
                  </span>
                </button>
                {/* ponytail: the count only. The digest carries no rows for posted cases —
                    nobody needs to act on them, and the cases list is one click away.
                    Add rows here if an auditor asks to see them without leaving. */}
                {postedOpen && (
                  <p className="px-3 py-2 text-xs text-muted-foreground">
                    Cleared by the agent with no human in the loop. Filter the cases list by
                    Complete to see them.
                  </p>
                )}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
