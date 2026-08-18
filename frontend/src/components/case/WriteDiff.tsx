// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { ArrowRight, Play } from "lucide-react"
import type { DiffRow, FunctionImportCard } from "@/lib/writeDiff"
import { TONE_TEXT } from "@/lib/statusTone"
import { cn } from "@/lib/utils"

/**
 * A SAP write as a before/after table — the record half and the proposal half in one
 * component, differing only in their label.
 *
 * Before is muted, after is foreground; neither is a state colour. Only a *mismatch*
 * takes a tone, because only a mismatch is a fact the reviewer has to act on. Both
 * sides are `font-mono`: an operator compares these against SAP GUI character by
 * character, so column alignment is correctness, not decoration.
 */

const NOTE: Partial<Record<DiffRow["state"], string>> = {
  "no-baseline": "no prior value on record",
  unverified: "not verified against a read in this run",
}

/** An empty SAP value is a value; a missing one is not, and they must not look alike. */
function Value({ value, className }: { value: string; className: string }) {
  return value ? (
    <span className={cn("font-mono break-all", className)}>{value}</span>
  ) : (
    <span className="font-mono text-muted-foreground" title="empty">
      (empty)
    </span>
  )
}

function Row({ row, quiet }: { row: DiffRow; quiet?: boolean }) {
  // `quiet` when the whole table already states the absence — repeating it on every
  // row buries the field names the reviewer is here to read.
  const note = quiet ? undefined : NOTE[row.state]
  return (
    <div className="contents">
      <dt className="text-muted-foreground">{row.name}</dt>
      <dd className="min-w-0">
        <span className="flex flex-wrap items-baseline gap-1.5">
          {row.before !== undefined && (
            <>
              <Value
                value={row.before}
                className={row.state === "mismatch" ? TONE_TEXT.danger : "text-muted-foreground"}
              />
              <ArrowRight size={10} className="flex-none text-muted-foreground" aria-label="to" />
            </>
          )}
          <Value value={row.after} className="text-foreground" />
          {row.state === "unchanged" && (
            <span className="text-3xs text-muted-foreground">unchanged</span>
          )}
          {note && <span className="text-3xs italic text-muted-foreground">{note}</span>}
        </span>
        {row.state === "mismatch" && (
          <span className={cn("block text-3xs", TONE_TEXT.danger)}>
            SAP read in this run returned{" "}
            <span className="font-mono">{row.observed || "(empty)"}</span>, not the stated value
          </span>
        )}
      </dd>
    </div>
  )
}

/**
 * Stated once for the whole table when no row has a before value, rather than repeated
 * per row. Derived here, not passed in, so a mount point cannot forget to say it.
 */
function absenceNote(rows: DiffRow[], label: string): string | undefined {
  if (rows.length === 0 || rows.some(r => r.before !== undefined)) return undefined
  return label === "Proposed"
    ? "The agent stated no current values, so there is nothing to compare against."
    : "No read of this record in this run, so the previous values are not on record."
}

export function WriteDiff({
  rows,
  label,
  card,
  note,
}: {
  rows: DiffRow[]
  label: "Applied" | "Proposed"
  card?: FunctionImportCard
  note?: string
}) {
  const absence = card ? undefined : absenceNote(rows, label)
  return (
    <div className="space-y-1">
      <p className="text-3xs font-semibold uppercase tracking-wider text-muted-foreground">
        {label}
      </p>

      {card ? (
        <div className="space-y-1 rounded-md border px-2 py-1.5">
          <p className="flex items-center gap-1.5 text-2xs">
            <Play size={10} className="flex-none text-muted-foreground" />
            <span className="font-mono text-foreground">{card.fn}</span>
            {card.target && <span className="font-mono text-muted-foreground">{card.target}</span>}
          </p>
          {card.params.length > 0 ? (
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-2xs">
              {card.params.map((p, i) => (
                <div key={`${p.name}-${i}`} className="contents">
                  <dt className="text-muted-foreground">{p.name}</dt>
                  <dd className="font-mono break-all text-foreground">{p.value || "—"}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="text-2xs text-muted-foreground">This action took no parameters.</p>
          )}
          {/* A lifecycle action changes no field, so there is nothing to diff. Saying so
              is the point: a two-column table here would need a left side that does not
              exist, and inventing one would misreport what SAP holds. */}
          <p className="text-3xs italic text-muted-foreground">
            A lifecycle action changes no field values, so there is nothing to compare.
          </p>
        </div>
      ) : rows.length === 0 ? (
        <p className="text-2xs text-muted-foreground">
          {label === "Proposed"
            ? "The agent recorded no fields for this proposal."
            : "This write recorded no field values."}
        </p>
      ) : (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-2xs">
          {rows.map((row, i) => (
            <Row key={`${row.name}-${i}`} row={row} quiet={Boolean(absence)} />
          ))}
        </dl>
      )}

      {absence && <p className="text-3xs italic text-muted-foreground">{absence}</p>}
      {note && <p className="text-3xs italic text-muted-foreground">{note}</p>}
    </div>
  )
}
