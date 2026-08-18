// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { EvidenceKind, WriteOp } from "@/types/cases"
import type { AgentTrace, EvidenceField, ProposedWrite, TraceSegment } from "@/types/cases"
import { segmentsOf } from "@/lib/caseTimeline"

/**
 * Before/after row models for a SAP write, kept pure of any rendering concern.
 *
 * Two halves reduce to the same rows. A *completed* write's before values come from
 * the read that preceded it in the same run, so they are as deterministic as the
 * write itself. A *proposed* write's come from the model, which is why each one is
 * checked against the run's reads and labelled rather than believed.
 *
 * A before value is never fabricated. When there is none on record the row says so:
 * a blank cell reads as "the field was empty", which is a different claim.
 */

export type RowState =
  /** Baseline read holds a different value. */
  | "changed"
  /** Baseline read holds the same value — the write was a no-op for this field. */
  | "unchanged"
  /** No before value on record: no matching read, or a create. */
  | "no-baseline"
  /** A stated current value that a read in this run agrees with. */
  | "verified"
  /** A stated current value that a read in this run contradicts. */
  | "mismatch"
  /** A stated current value with no read to check it against. */
  | "unverified"

export interface DiffRow {
  name: string
  before?: string
  after: string
  state: RowState
  /**
   * What a read in this run actually holds. Only set on `mismatch`, where knowing
   * the claim is wrong is not enough to act on — the reviewer needs the real value.
   */
  observed?: string
}

export interface FunctionImportCard {
  fn: string
  target?: string
  params: EvidenceField[]
}

/**
 * `fields` arrives as JSON from DynamoDB and `Evidence`'s index signature admits any
 * shape, so a stored scalar would throw in `.map` and blank the route.
 */
function fieldsOf(fields: unknown): EvidenceField[] {
  return Array.isArray(fields) ? (fields as EvidenceField[]).filter(f => f?.name) : []
}

function readSource(segment: TraceSegment | undefined) {
  return segment?.evidence?.kind === EvidenceKind.SapRead ? segment.evidence.source : undefined
}

/**
 * The read this write changed, or `undefined` when the run holds none.
 *
 * ponytail: a linear backward scan over one run's steps. A write whose read happened
 * in an earlier invocation takes the no-baseline path — reaching it would need the
 * case's whole trace list, which no caller has today.
 *
 * A `function_import` never matches: `source.entity` is the function name there
 * (`Post`, not an entity set), so it returns before scanning.
 */
export function baselineFor(write: TraceSegment, steps: TraceSegment[]): TraceSegment | undefined {
  const source = write.evidence?.source
  if (write.evidence?.op === WriteOp.FunctionImport) return undefined
  if (!source?.entity || !source.key) return undefined

  const at = steps.indexOf(write)
  for (let i = (at < 0 ? steps.length : at) - 1; i >= 0; i--) {
    const prior = readSource(steps[i])
    if (prior?.entity === source.entity && prior.key === source.key) return steps[i]
  }
  return undefined
}

/** Rows for a write that already happened: the payload against the baseline read. */
export function appliedRows(write: TraceSegment, baseline?: TraceSegment): DiffRow[] {
  const priorFields = fieldsOf(baseline?.evidence?.fields)
  return fieldsOf(write.evidence?.fields).map(field => {
    const after = field.value ?? ""
    // Per-field, not per-row: MAX_FIELDS caps the extracted read at 12 and $select
    // narrows it further, so a baseline can exist and still not carry this field.
    const prior = priorFields.find(f => f.name === field.name)
    if (!prior) return { name: field.name, after, state: "no-baseline" }
    const before = prior.value ?? ""
    return { name: field.name, before, after, state: before === after ? "unchanged" : "changed" }
  })
}

/** Rows for a write the agent is asking permission to make. */
export function proposedRows(proposal: ProposedWrite, steps: TraceSegment[]): DiffRow[] {
  const reads = steps.filter(s => s?.evidence?.kind === EvidenceKind.SapRead)
  // Scoped to the record the proposal names when it names one — a value read off a
  // different document is not evidence about this one.
  const scoped =
    proposal.entity && proposal.key
      ? reads.filter(s => {
          const source = readSource(s)
          return source?.entity === proposal.entity && source?.key === proposal.key
        })
      : reads

  const fields = Array.isArray(proposal.fields) ? proposal.fields : []
  return fields.map(field => {
    const after = field.proposed ?? ""
    if (field.current === undefined || field.current === null) {
      return { name: field.name, after, state: "no-baseline" }
    }
    const observed = scoped
      .flatMap(s => fieldsOf(s.evidence?.fields))
      .find(f => f.name === field.name)?.value
    if (observed === undefined) {
      return { name: field.name, before: field.current, after, state: "unverified" }
    }
    return observed === field.current
      ? { name: field.name, before: field.current, after, state: "verified" }
      : { name: field.name, before: field.current, after, state: "mismatch", observed }
  })
}

/**
 * The write a case is currently asking permission for, with the run that declared it.
 *
 * The steps come back alongside the proposal because verification is per-run: a
 * `current` value is only checked against reads the agent made while forming this
 * proposal, not against a read from some earlier run that may since be stale.
 */
export function pendingProposal(
  traces: AgentTrace[] | undefined
): { proposal: ProposedWrite; steps: TraceSegment[] } | undefined {
  const sorted = [...(traces ?? [])].sort((a, b) =>
    (b.timestamp ?? "").localeCompare(a.timestamp ?? "")
  )
  for (const trace of sorted) {
    const steps = segmentsOf(trace)
    // Last within the run: a run that escalated twice is asking about the later one.
    for (let i = steps.length - 1; i >= 0; i--) {
      const evidence = steps[i]?.evidence
      if (evidence?.kind === EvidenceKind.Notification && evidence.proposed_write) {
        return { proposal: evidence.proposed_write, steps }
      }
    }
  }
  return undefined
}

/**
 * `Post` and `Release` change no field — they move a document's lifecycle. A
 * two-column table would need a left side that does not exist, so this renders as
 * the action and its parameters instead.
 */
export function functionImportCard(write: TraceSegment): FunctionImportCard {
  const source = write.evidence?.source
  return {
    fn: source?.entity || "Function import",
    target: source?.key || undefined,
    params: fieldsOf(write.evidence?.fields),
  }
}
