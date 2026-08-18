// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { EvidenceKind, SegmentStatus, TraceSegmentType, WriteOp } from "@/types/cases"
import type { AgentTrace, EvidenceField, TraceSegment } from "@/types/cases"
import type { ToolCallStatus } from "@/components/chat/types"

/**
 * Row headlines and the prose split for the case timeline.
 *
 * Every headline is derived from `evidence` — the tool name is only a fallback for
 * a trace stored before the evidence model landed. That is what makes attribution
 * structural: nothing on a row originates in model prose.
 */

/**
 * Value of a named field, treating a recorded empty string as absent.
 *
 * `_scalar_fields` records `""` for a null SAP attribute, and every caller here is
 * building display text where an empty value would render a dangling label
 * ("Case status → "). Callers that must tell "recorded as empty" from "not recorded"
 * have to read `fields` directly.
 *
 * `fields` is not just optional but untrusted: it arrives as JSON from DynamoDB, and
 * `Evidence`'s index signature means the compiler cannot rule out a non-array here.
 */
export function fieldValue(fields: EvidenceField[] | undefined, name: string): string | undefined {
  if (!Array.isArray(fields)) return undefined
  const found = fields.find(f => f?.name === name)
  return found?.value || undefined
}

function target(source: { entity?: string; service?: string; key?: string } | undefined): string {
  const what = source?.entity || source?.service
  if (!what) return ""
  return source?.key ? `${what} ${source.key}` : what
}

const WRITE_VERB: Record<string, string> = {
  [WriteOp.Update]: "Updated",
  [WriteOp.Create]: "Created",
  [WriteOp.FunctionImport]: "Called",
}

/** One line describing what this tool step did. Never longer than one line at compact density. */
export function rowHeadline(segment: TraceSegment): string {
  const fallback = segment.tool_name || "Step"
  const evidence = segment.evidence
  if (!evidence) return fallback

  switch (evidence.kind) {
    case EvidenceKind.SapRead: {
      const what = target(evidence.source)
      return what ? `Read ${what}` : "Read from SAP"
    }
    case EvidenceKind.SapWrite: {
      const verb = WRITE_VERB[evidence.op ?? ""] ?? "Wrote"
      const what = target(evidence.source)
      return what ? `${verb} ${what}` : `${verb} to SAP`
    }
    case EvidenceKind.SopLookup: {
      // Same untrusted JSON as `fields`: a stored scalar's `.length` would count
      // characters and label the row "10 clauses".
      const n = Array.isArray(evidence.clauses_retrieved) ? evidence.clauses_retrieved.length : 0
      return n > 0 ? `SOP consulted · ${n} clause${n === 1 ? "" : "s"}` : "SOP consulted"
    }
    case EvidenceKind.CaseUpdate: {
      const status = fieldValue(evidence.fields, "status")
      return status ? `Case status → ${status}` : "Case updated"
    }
    case EvidenceKind.Notification: {
      const to = fieldValue(evidence.fields, "recipient")
      return to ? `Notified ${to}` : "Notification sent"
    }
    case EvidenceKind.Computation: {
      // `computation` is also the unknown-tool fallthrough, and its `result` field is
      // the raw tool result cut to 120 bytes — for a tool like get_case_state that is
      // pretty-printed JSON, newlines and all. Only promote a result that reads as a
      // value; anything else keeps the tool's own name, which at least is true.
      const result = fieldValue(evidence.fields, "result")
      const scalar = result && !result.includes("\n") && result.length <= 40
      if (scalar) return `Computed ${result}`
      return segment.tool_name ? `Ran ${segment.tool_name}` : "Computed"
    }
    default:
      // A kind this build does not know about — a newer agent writing into an older
      // console. Name the tool rather than inventing a description for it.
      return fallback
  }
}

/**
 * A trace's segments, tolerating a stored trace that has none.
 *
 * `segments` is non-optional in the schema but arrives as JSON from DynamoDB, and a
 * throw during render blanks the whole route — there is no error boundary above this.
 */
export function segmentsOf(trace: AgentTrace): TraceSegment[] {
  return Array.isArray(trace.segments) ? trace.segments : []
}

/**
 * Segment status as the tool-call renderer wants it.
 *
 * An absent status means the trace predates the evidence model, not that the call is
 * in doubt — so it keeps today's rendering. Only a recorded failure renders as one.
 */
export function segmentStatus(segment: TraceSegment): ToolCallStatus {
  return segment.status === SegmentStatus.Error ? "error" : "complete"
}

/**
 * The final text segment is the decision statement and renders as one line; every
 * earlier text segment folds into the collapsed reasoning disclosure.
 *
 * A run whose last real step was a tool call has no conclusion — it stopped mid-work,
 * and `OutcomeBadge` carries that instead. "Last real step" ignores whitespace-only
 * text segments: the stream opens a fresh segment for a trailing empty delta, and
 * testing the raw last element would demote a genuine conclusion into the disclosure.
 */
export function splitProse(trace: AgentTrace): { conclusion: string | null; reasoning: string[] } {
  const meaningful = segmentsOf(trace).filter(
    s => s && (s.type !== TraceSegmentType.Text || Boolean(s.content?.trim()))
  )
  const prose = meaningful.filter(s => s.type === TraceSegmentType.Text).map(s => s.content!.trim())

  const endedOnText = meaningful[meaningful.length - 1]?.type === TraceSegmentType.Text
  if (!endedOnText || prose.length === 0) return { conclusion: null, reasoning: prose }

  return { conclusion: prose[prose.length - 1], reasoning: prose.slice(0, -1) }
}
