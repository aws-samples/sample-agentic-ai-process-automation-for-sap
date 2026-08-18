// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Behavioural twin of `tests/unit/test_case_key.py`. The Python codec and this one
 * cannot be diffed byte-for-byte, so both suites assert the same cases — if the
 * UI and the backend ever disagree about an id, one of these fails.
 */

import { describe, it, expect } from "vitest"
import {
  CASE_ID_PATTERN,
  CaseKeyError,
  RUNTIME_SESSION_MIN_LENGTH,
  formatCaseId,
  isCaseId,
  normalizeCaseId,
  parseCaseId,
  toRuntimeSessionId,
  tryFormatCaseId,
  tryNormalizeCaseId,
} from "./caseKey"

// The real AP shape: document_number=SupplierInvoice, item_id=FiscalYear.
const REAL_CASE_ID = "5100001976-2026"

describe("formatCaseId", () => {
  it("round-trips through parseCaseId", () => {
    expect(formatCaseId("5100001976", "2026")).toBe(REAL_CASE_ID)
    expect(parseCaseId(REAL_CASE_ID)).toEqual({
      document_number: "5100001976",
      item_id: "2026",
    })
  })

  it("preserves leading zeros in item ids", () => {
    expect(formatCaseId("4500012345", "00010")).toBe("4500012345-00010")
    expect(parseCaseId("4500012345-00010").item_id).toBe("00010")
  })

  it("trims surrounding whitespace", () => {
    expect(formatCaseId(" 5100001976 ", " 2026 ")).toBe(REAL_CASE_ID)
  })

  it.each([
    ["", "2026"],
    ["5100001976", ""],
  ])("rejects missing segments (%s, %s)", (doc, item) => {
    expect(() => formatCaseId(doc, item)).toThrow(CaseKeyError)
  })

  it.each([
    ["5100-001976", "2026", "a separator inside a segment would not parse back"],
    ["5100001976", "20#26", "legacy separator inside a segment"],
    ["5100001976", "20/26", "path separator inside a segment"],
    ["510000 1976", "2026", "whitespace inside a segment"],
    ["5100001976", "../etc", "traversal characters"],
  ])("refuses to mint an unparseable id: %s / %s", (doc, item) => {
    expect(() => formatCaseId(doc, item)).toThrow(CaseKeyError)
  })
})

describe("normalizeCaseId", () => {
  it.each([
    "5100001976#2026", // original SQS/ticket wire form
    "5100001976/2026", // observability trace form
    "5100001976-2026", // already canonical
    "  5100001976#2026  ",
  ])("normalizes every historical form: %s", legacy => {
    expect(normalizeCaseId(legacy)).toBe(REAL_CASE_ID)
  })

  it("treats legacy and canonical forms as the same case", () => {
    expect(parseCaseId("5100001976#2026")).toEqual(parseCaseId("5100001976-2026"))
  })

  it.each([
    ["", "empty"],
    ["   ", "blank"],
    ["5100001976", "single segment is not a case identity"],
    ["5100001976-2026-1", "three segments are ambiguous"],
    ["5100001976-2026 OR 1=1", "injection payload"],
    ["../../5100001976-2026", "traversal prefix"],
  ])("rejects malformed identity %s (%s)", bad => {
    expect(() => normalizeCaseId(bad)).toThrow(CaseKeyError)
  })

  it("returns null from tryNormalizeCaseId instead of throwing", () => {
    expect(tryNormalizeCaseId("5100001976#2026")).toBe(REAL_CASE_ID)
    expect(tryNormalizeCaseId("not a case")).toBeNull()
    expect(tryNormalizeCaseId(null)).toBeNull()
    expect(tryNormalizeCaseId(undefined)).toBeNull()
    expect(isCaseId(REAL_CASE_ID)).toBe(true)
    expect(isCaseId("not a case")).toBe(false)
  })

  it("degrades instead of throwing in render paths", () => {
    // A row written before the canonical form existed must not break a render.
    expect(tryFormatCaseId("5100001976", "2026")).toBe(REAL_CASE_ID)
    expect(tryFormatCaseId("5100001976", "")).toBeNull()
    expect(tryFormatCaseId("5100-001976", "2026")).toBeNull()
    expect(tryFormatCaseId(null, undefined)).toBeNull()
  })
})

describe("the properties that motivated the format", () => {
  it("needs no URL encoding", () => {
    // The `%23` hand-encoding in the old case→tickets link had no reason to exist.
    expect(encodeURIComponent(REAL_CASE_ID)).toBe(REAL_CASE_ID)
  })

  it("survives the AgentCore Memory actor/session charset filter", () => {
    expect(REAL_CASE_ID).not.toMatch(/[^a-zA-Z0-9\-_/:]/)
  })

  it("exports an anchored pattern that rejects legacy forms", () => {
    expect(CASE_ID_PATTERN.startsWith("^")).toBe(true)
    expect(CASE_ID_PATTERN.endsWith("$")).toBe(true)
    expect(new RegExp(CASE_ID_PATTERN).test(REAL_CASE_ID)).toBe(true)
    expect(new RegExp(CASE_ID_PATTERN).test("5100001976#2026")).toBe(false)
  })
})

describe("toRuntimeSessionId", () => {
  it("is deterministic for a case, whatever form the id arrives in", () => {
    expect(toRuntimeSessionId(REAL_CASE_ID)).toBe(toRuntimeSessionId("5100001976#2026"))
  })

  it("clears the AgentCore Runtime minimum length", () => {
    // A bare `case-5100001976-2026` is 20 chars and the Runtime rejects it.
    const sessionId = toRuntimeSessionId(REAL_CASE_ID)
    expect(sessionId.length).toBeGreaterThanOrEqual(RUNTIME_SESSION_MIN_LENGTH)
    expect(sessionId).toContain(REAL_CASE_ID)
    expect(sessionId).not.toMatch(/[^a-zA-Z0-9\-_/:]/)
  })

  it("does not pad an already long case id", () => {
    const longId = toRuntimeSessionId("510000197600000000-2026000000000")
    expect(longId.length).toBeGreaterThan(RUNTIME_SESSION_MIN_LENGTH)
    expect(longId.endsWith("0-0")).toBe(false)
  })

  it("is distinct across cases", () => {
    expect(toRuntimeSessionId("5100001976-2026")).not.toBe(toRuntimeSessionId("5100001976-2027"))
  })

  it("rejects a malformed case id", () => {
    expect(() => toRuntimeSessionId("not a case")).toThrow(CaseKeyError)
  })
})
