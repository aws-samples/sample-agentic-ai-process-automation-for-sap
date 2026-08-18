// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Canonical codec for case identity — the one place `case_id` is built or read.
 *
 * TypeScript twin of `lambdas/layers/shared_types/case_key.py` (and its mirror
 * `agentcore/agent/utils/case_key.py`). See that module for the full rationale;
 * the contract in brief:
 *
 *   - Canonical form is `{document_number}-{item_id}`, e.g. `5100001976-2026`.
 *   - Segments are restricted to `[A-Za-z0-9_]`, which makes a single `-` split
 *     lossless and keeps the id safe in URLs, SQS group ids, and session ids
 *     with no escaping. No more hand-written `%23`.
 *   - Legacy `#` and `/` separators are accepted on read; only `-` is emitted.
 */

/** The one separator between the two key segments. */
export const SEPARATOR = "-"

/** Character class a single key segment is allowed to use. */
const SEGMENT_CHARS = "A-Za-z0-9_"

/** Anchored pattern for a whole canonical case_id. */
export const CASE_ID_PATTERN = `^[${SEGMENT_CHARS}]+${SEPARATOR}[${SEGMENT_CHARS}]+$`

const SEGMENT_RE = new RegExp(`^[${SEGMENT_CHARS}]+$`)
const CASE_ID_RE = new RegExp(CASE_ID_PATTERN)
const ANY_SEPARATOR_RE = new RegExp(`[#/${SEPARATOR}]`)

/** AgentCore Runtime rejects a session id shorter than this. */
export const RUNTIME_SESSION_MIN_LENGTH = 33

const SESSION_PREFIX = "erp-case-"
const SESSION_PAD = "0"

/** A case identity could not be built or parsed. */
export class CaseKeyError extends Error {
  constructor(message: string) {
    super(message)
    this.name = "CaseKeyError"
  }
}

/** The two DynamoDB key segments that identify a case. */
export interface CaseKey {
  document_number: string
  item_id: string
}

/**
 * Build the canonical `case_id` from the two DynamoDB key segments.
 *
 * @throws CaseKeyError if either segment is empty or uses a character outside
 * the allowed set — including the separator, which would make the result
 * impossible to parse back.
 */
export function formatCaseId(documentNumber: string, itemId: string): string {
  const doc = (documentNumber ?? "").trim()
  const item = (itemId ?? "").trim()
  for (const [label, value] of [
    ["document_number", doc],
    ["item_id", item],
  ] as const) {
    if (!value) throw new CaseKeyError(`${label} is required to build a case_id`)
    if (!SEGMENT_RE.test(value)) {
      throw new CaseKeyError(
        `${label}="${value}" is not a valid case_id segment; expected characters in [${SEGMENT_CHARS}]`
      )
    }
  }
  return `${doc}${SEPARATOR}${item}`
}

/** Coerce any accepted case identity form to the canonical one. */
export function normalizeCaseId(caseId: string): string {
  const value = (caseId ?? "").trim()
  if (!value) throw new CaseKeyError("case_id is required")
  if (CASE_ID_RE.test(value)) return value
  const segments = value.split(ANY_SEPARATOR_RE)
  if (segments.length !== 2) {
    throw new CaseKeyError(
      `case_id="${value}" is not a document/item pair; expected {document_number}${SEPARATOR}{item_id}`
    )
  }
  return formatCaseId(segments[0], segments[1])
}

/** Best-effort {@link normalizeCaseId} — `null` instead of throwing. */
export function tryNormalizeCaseId(caseId: string | null | undefined): string | null {
  try {
    return normalizeCaseId(caseId ?? "")
  } catch {
    return null
  }
}

/** Split a `case_id` back into its two key segments. */
export function parseCaseId(caseId: string): CaseKey {
  const [document_number, item_id] = normalizeCaseId(caseId).split(SEPARATOR)
  return { document_number, item_id }
}

/**
 * Best-effort {@link formatCaseId} — `null` instead of throwing.
 *
 * For render paths that derive an id from a fetched record: a row written before
 * the canonical form existed should degrade rather than throw mid-render.
 */
export function tryFormatCaseId(
  documentNumber: string | null | undefined,
  itemId: string | null | undefined
): string | null {
  try {
    return formatCaseId(documentNumber ?? "", itemId ?? "")
  } catch {
    return null
  }
}

/** True if `value` is a well-formed case identity in any accepted form. */
export function isCaseId(value: string | null | undefined): boolean {
  return tryNormalizeCaseId(value) !== null
}

/**
 * Derive a stable AgentCore session id for a case.
 *
 * Deterministic, so every turn for one case lands in the same AgentCore Memory
 * session instead of a fresh random one. Right-padded because AgentCore Runtime
 * rejects ids shorter than {@link RUNTIME_SESSION_MIN_LENGTH}.
 */
export function toRuntimeSessionId(caseId: string): string {
  let base = `${SESSION_PREFIX}${normalizeCaseId(caseId)}`
  if (base.length < RUNTIME_SESSION_MIN_LENGTH) {
    base += SEPARATOR + SESSION_PAD.repeat(RUNTIME_SESSION_MIN_LENGTH - base.length - 1)
  }
  return base
}
