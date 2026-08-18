// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest"
import { fieldValue, rowHeadline, segmentsOf, splitProse, segmentStatus } from "@/lib/caseTimeline"
import { TraceSegmentType } from "@/types/cases"
import type { AgentTrace, TraceSegment } from "@/types/cases"

// `extra` is deliberately untyped rather than `Partial<TraceSegment>`: `status` is a
// string enum, so `{ status: "error" }` does not assign to it, and the point of these
// factories is to feed the raw JSON shapes DynamoDB actually returns.
function tool(evidence: Record<string, unknown> | undefined, extra: Record<string, unknown> = {}) {
  return {
    type: TraceSegmentType.Tool,
    tool_name: "some_tool",
    ...(evidence ? { evidence } : {}),
    ...extra,
  } as TraceSegment
}

function text(content: string): TraceSegment {
  return { type: TraceSegmentType.Text, content } as TraceSegment
}

describe("rowHeadline", () => {
  it("names the entity and key for a SAP read", () => {
    const segment = tool({
      kind: "sap_read",
      source: { service: "API_SUPPLIERINVOICE", entity: "A_SupplierInvoice", key: "5100001976" },
    })
    expect(rowHeadline(segment)).toBe("Read A_SupplierInvoice 5100001976")
  })

  it("falls back to the service when no entity was recorded", () => {
    expect(rowHeadline(tool({ kind: "sap_read", source: { service: "API_X" } }))).toBe("Read API_X")
  })

  it("distinguishes the three write ops", () => {
    const src = { entity: "A_PurchaseOrderItem", key: "4500000123/10" }
    expect(rowHeadline(tool({ kind: "sap_write", op: "update", source: src }))).toBe(
      "Updated A_PurchaseOrderItem 4500000123/10"
    )
    expect(rowHeadline(tool({ kind: "sap_write", op: "create", source: src }))).toBe(
      "Created A_PurchaseOrderItem 4500000123/10"
    )
    expect(
      rowHeadline(tool({ kind: "sap_write", op: "function_import", source: { entity: "Post" } }))
    ).toBe("Called Post")
  })

  it("counts retrieved clauses on a SOP lookup", () => {
    expect(rowHeadline(tool({ kind: "sop_lookup", clauses_retrieved: ["1.1", "2.3"] }))).toBe(
      "SOP consulted · 2 clauses"
    )
    expect(rowHeadline(tool({ kind: "sop_lookup", clauses_retrieved: ["1.1"] }))).toBe(
      "SOP consulted · 1 clause"
    )
    expect(rowHeadline(tool({ kind: "sop_lookup" }))).toBe("SOP consulted")
    // A stored scalar would otherwise count characters: "SOP consulted · 3 clauses".
    expect(rowHeadline(tool({ kind: "sop_lookup", clauses_retrieved: "1.1" }))).toBe(
      "SOP consulted"
    )
  })

  it("states the status transition for a case update", () => {
    const segment = tool({
      kind: "case_update",
      fields: [{ name: "status", value: "sap_updated" }],
    })
    expect(rowHeadline(segment)).toBe("Case status → sap_updated")
  })

  it("names the recipient of a notification", () => {
    const segment = tool({
      kind: "notification",
      fields: [{ name: "recipient", value: "ap-team@example.com" }],
    })
    expect(rowHeadline(segment)).toBe("Notified ap-team@example.com")
  })

  it("shows the derived value for a computation", () => {
    const segment = tool({ kind: "computation", fields: [{ name: "result", value: "42.00" }] })
    expect(rowHeadline(segment)).toBe("Computed 42.00")
  })

  it("never promotes a multi-line or long result into the headline", () => {
    // get_case_state has no kind mapping, so it lands in `computation` and its
    // `result` field is 120 bytes of indented JSON. That is not a headline.
    const blob = tool(
      {
        kind: "computation",
        fields: [{ name: "result", value: '{\n  "case_id": "5100001976-1",\n  "status": "proc' }],
      },
      { tool_name: "get_case_state" }
    )
    expect(rowHeadline(blob)).toBe("Ran get_case_state")

    const long = tool({
      kind: "computation",
      fields: [{ name: "result", value: "x".repeat(41) }],
    })
    expect(rowHeadline(long)).toBe("Ran some_tool")
  })

  it("names the tool when a computation recorded no result", () => {
    expect(rowHeadline(tool({ kind: "computation" }))).toBe("Ran some_tool")
  })

  it("falls back to the tool name when evidence is absent", () => {
    expect(rowHeadline(tool(undefined))).toBe("some_tool")
  })

  it("falls back to the tool name when the kind is unrecognised", () => {
    expect(rowHeadline(tool({ kind: "something_new" }))).toBe("some_tool")
  })
})

describe("segmentStatus", () => {
  it("maps a recorded error to error", () => {
    expect(segmentStatus(tool({ kind: "sap_read" }, { status: "error" }))).toBe("error")
  })

  it("maps a recorded success to complete", () => {
    expect(segmentStatus(tool({ kind: "sap_read" }, { status: "success" }))).toBe("complete")
  })

  it("treats an unrecorded status as complete, not as unconfirmed", () => {
    expect(segmentStatus(tool(undefined))).toBe("complete")
  })
})

describe("segmentsOf", () => {
  it("returns the segments of a well-formed trace", () => {
    const segments = [text("Done.")]
    expect(segmentsOf({ trace_id: "t1", timestamp: "2026-07-01T00:00:00Z", segments })).toBe(
      segments
    )
  })

  it("returns an empty array when segments were never stored", () => {
    const malformed = { trace_id: "t1", timestamp: "2026-07-01T00:00:00Z" } as AgentTrace
    expect(segmentsOf(malformed)).toEqual([])
  })
})

describe("splitProse", () => {
  function trace(segments: TraceSegment[]): AgentTrace {
    return { trace_id: "t1", timestamp: "2026-07-01T00:00:00Z", segments }
  }

  it("takes the final text segment as the conclusion", () => {
    const result = splitProse(
      trace([text("Checking the PO."), tool(undefined), text("Variance is within tolerance.")])
    )
    expect(result.conclusion).toBe("Variance is within tolerance.")
    expect(result.reasoning).toEqual(["Checking the PO."])
  })

  it("has no conclusion when the run ended on a tool call", () => {
    const result = splitProse(trace([text("Checking the PO."), tool(undefined)]))
    expect(result.conclusion).toBeNull()
    expect(result.reasoning).toEqual(["Checking the PO."])
  })

  it("returns an empty split for a tool-only run", () => {
    expect(splitProse(trace([tool(undefined)]))).toEqual({ conclusion: null, reasoning: [] })
  })

  it("ignores empty text segments", () => {
    const result = splitProse(trace([text(""), text("   "), text("Done.")]))
    expect(result.conclusion).toBe("Done.")
    expect(result.reasoning).toEqual([])
  })

  it("keeps the conclusion when a whitespace-only segment trails it", () => {
    // A trailing empty delta opens a fresh text segment. Testing the raw last element
    // would hide the decision statement behind the reasoning disclosure.
    const result = splitProse(
      trace([tool(undefined), text("Variance is within tolerance."), text("\n")])
    )
    expect(result.conclusion).toBe("Variance is within tolerance.")
    expect(result.reasoning).toEqual([])
  })

  it("tolerates a trace with no segments", () => {
    expect(splitProse(trace([]))).toEqual({ conclusion: null, reasoning: [] })
  })

  it("tolerates a segments field that is not an array", () => {
    const malformed = {
      trace_id: "t1",
      timestamp: "x",
      segments: undefined,
    } as unknown as AgentTrace
    expect(splitProse(malformed)).toEqual({ conclusion: null, reasoning: [] })
  })

  it("tolerates a null element inside segments", () => {
    const withHole = trace([null as unknown as TraceSegment, text("Done.")])
    expect(splitProse(withHole)).toEqual({ conclusion: "Done.", reasoning: [] })
  })
})

describe("fieldValue", () => {
  it("finds a named value", () => {
    expect(fieldValue([{ name: "status", value: "complete" }], "status")).toBe("complete")
  })

  it("treats a recorded empty string as absent", () => {
    expect(fieldValue([{ name: "status", value: "" }], "status")).toBeUndefined()
  })

  it("returns undefined for a missing name, an absent list, or a non-array", () => {
    expect(fieldValue([{ name: "other", value: "x" }], "status")).toBeUndefined()
    expect(fieldValue(undefined, "status")).toBeUndefined()
    expect(fieldValue({} as unknown as [], "status")).toBeUndefined()
  })
})
