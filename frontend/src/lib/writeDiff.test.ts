// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest"
import { appliedRows, baselineFor, functionImportCard, proposedRows } from "@/lib/writeDiff"
import { TraceSegmentType, WriteOp } from "@/types/cases"
import type { ProposedWrite, TraceSegment } from "@/types/cases"

function segment(evidence: Record<string, unknown>): TraceSegment {
  return { type: TraceSegmentType.Tool, evidence } as unknown as TraceSegment
}

const read = (fields: { name: string; value: string }[], key = "4500000123/10") =>
  segment({
    kind: "sap_read",
    source: { service: "API_PURCHASEORDER_PROCESS_SRV", entity: "A_PurchaseOrderItem", key },
    fields,
  })

const update = (fields: { name: string; value: string }[], key = "4500000123/10") =>
  segment({
    kind: "sap_write",
    op: "update",
    source: { service: "API_PURCHASEORDER_PROCESS_SRV", entity: "A_PurchaseOrderItem", key },
    fields,
  })

describe("baselineFor", () => {
  it("finds the most recent prior read of the same record", () => {
    const stale = read([{ name: "NetPriceAmount", value: "11.00" }])
    const fresh = read([{ name: "NetPriceAmount", value: "12.00" }])
    const write = update([{ name: "NetPriceAmount", value: "12.50" }])
    expect(baselineFor(write, [stale, fresh, write])).toBe(fresh)
  })

  it("ignores a read of a different record", () => {
    const other = read([{ name: "NetPriceAmount", value: "99.00" }], "4500000999/10")
    const write = update([{ name: "NetPriceAmount", value: "12.50" }])
    expect(baselineFor(write, [other, write])).toBeUndefined()
  })

  it("does not match a key whose components came back in the other order", () => {
    // `_key_from` joins values positionally, so a reversed $filter yields '10/4500000123'.
    // Correct-but-degraded: this falls to the no-baseline path rather than mispairing.
    const reversed = read([{ name: "NetPriceAmount", value: "12.00" }], "10/4500000123")
    const write = update([{ name: "NetPriceAmount", value: "12.50" }])
    expect(baselineFor(write, [reversed, write])).toBeUndefined()
  })

  it("never matches a function import, even when an entity-matching read exists", () => {
    // `source.entity` is the function name on that path, so any match would be an alias.
    const prior = read([{ name: "SupplierInvoice", value: "5105600000" }], "5105600000/2026")
    const post = segment({
      kind: "sap_write",
      op: "function_import",
      source: { entity: "A_PurchaseOrderItem", key: "5105600000/2026" },
    })
    expect(baselineFor(post, [prior, post])).toBeUndefined()
  })

  it("ignores a read that came after the write", () => {
    const write = update([{ name: "NetPriceAmount", value: "12.50" }])
    const after = read([{ name: "NetPriceAmount", value: "12.50" }])
    expect(baselineFor(write, [write, after])).toBeUndefined()
  })

  it("returns undefined when the write records no key to match on", () => {
    const write = segment({ kind: "sap_write", op: "update", source: { entity: "A_Item" } })
    expect(baselineFor(write, [read([{ name: "A", value: "1" }]), write])).toBeUndefined()
  })
})

describe("appliedRows", () => {
  it("pairs each written field against the baseline, marking a no-op unchanged", () => {
    const baseline = read([
      { name: "NetPriceAmount", value: "12.00" },
      { name: "PriceUnit", value: "1" },
    ])
    const write = update([
      { name: "NetPriceAmount", value: "12.50" },
      { name: "PriceUnit", value: "1" },
    ])
    expect(appliedRows(write, baseline)).toEqual([
      { name: "NetPriceAmount", before: "12.00", after: "12.50", state: "changed" },
      { name: "PriceUnit", before: "1", after: "1", state: "unchanged" },
    ])
  })

  it("states the absence rather than inventing a before value", () => {
    const write = update([{ name: "NetPriceAmount", value: "12.50" }])
    expect(appliedRows(write, undefined)).toEqual([
      { name: "NetPriceAmount", after: "12.50", state: "no-baseline" },
    ])
  })

  it("marks a single field absent when the baseline read did not carry it", () => {
    // MAX_FIELDS caps the extracted read at 12, so a wide entity can be read and still
    // not hold the written field. That is per-field, not a whole missing baseline.
    const baseline = read([{ name: "PriceUnit", value: "1" }])
    const write = update([
      { name: "NetPriceAmount", value: "12.50" },
      { name: "PriceUnit", value: "1" },
    ])
    expect(appliedRows(write, baseline)).toEqual([
      { name: "NetPriceAmount", after: "12.50", state: "no-baseline" },
      { name: "PriceUnit", before: "1", after: "1", state: "unchanged" },
    ])
  })

  it("gives a create no before column", () => {
    const create = segment({
      kind: "sap_write",
      op: "create",
      source: { entity: "A_SupplierInvoiceItem" },
      fields: [{ name: "SupplierInvoice", value: "5105600000" }],
    })
    expect(appliedRows(create, baselineFor(create, [create]))).toEqual([
      { name: "SupplierInvoice", after: "5105600000", state: "no-baseline" },
    ])
  })

  it("renders a cleared field as a change to empty, not as no baseline", () => {
    const baseline = read([{ name: "PaymentBlockingReason", value: "A" }])
    const write = update([{ name: "PaymentBlockingReason", value: "" }])
    expect(appliedRows(write, baseline)).toEqual([
      { name: "PaymentBlockingReason", before: "A", after: "", state: "changed" },
    ])
  })

  it("treats a stored non-array fields value as no rows", () => {
    expect(appliedRows(segment({ kind: "sap_write", op: "update", fields: "x" }))).toEqual([])
  })
})

describe("proposedRows", () => {
  const proposal = (fields: ProposedWrite["fields"], scoped = true): ProposedWrite => ({
    op: WriteOp.Update,
    fields,
    ...(scoped ? { entity: "A_PurchaseOrderItem", key: "4500000123/10" } : {}),
  })

  it("verifies a stated current value against a read of the same record", () => {
    const steps = [read([{ name: "NetPriceAmount", value: "12.00" }])]
    expect(
      proposedRows(
        proposal([{ name: "NetPriceAmount", current: "12.00", proposed: "12.50" }]),
        steps
      )
    ).toEqual([{ name: "NetPriceAmount", before: "12.00", after: "12.50", state: "verified" }])
  })

  it("flags a stated current value the run's reads contradict, and shows the real one", () => {
    const steps = [read([{ name: "NetPriceAmount", value: "11.00" }])]
    expect(
      proposedRows(
        proposal([{ name: "NetPriceAmount", current: "12.00", proposed: "12.50" }]),
        steps
      )
    ).toEqual([
      {
        name: "NetPriceAmount",
        before: "12.00",
        after: "12.50",
        state: "mismatch",
        observed: "11.00",
      },
    ])
  })

  it("leaves a value with nothing to check it against unverified", () => {
    expect(
      proposedRows(proposal([{ name: "NetPriceAmount", current: "12.00", proposed: "12.50" }]), [])
    ).toEqual([{ name: "NetPriceAmount", before: "12.00", after: "12.50", state: "unverified" }])
  })

  it("does not verify against a read of a different record", () => {
    const steps = [read([{ name: "NetPriceAmount", value: "12.00" }], "4500000999/10")]
    expect(
      proposedRows(
        proposal([{ name: "NetPriceAmount", current: "12.00", proposed: "12.50" }]),
        steps
      )
    ).toEqual([{ name: "NetPriceAmount", before: "12.00", after: "12.50", state: "unverified" }])
  })

  it("falls back to any read in the run when the proposal names no record", () => {
    const steps = [read([{ name: "NetPriceAmount", value: "12.00" }], "4500000999/10")]
    const rows = proposedRows(
      proposal([{ name: "NetPriceAmount", current: "12.00", proposed: "12.50" }], false),
      steps
    )
    expect(rows[0].state).toBe("verified")
  })

  it("carries no before value when the agent omitted current", () => {
    expect(proposedRows(proposal([{ name: "NetPriceAmount", proposed: "12.50" }]), [])).toEqual([
      { name: "NetPriceAmount", after: "12.50", state: "no-baseline" },
    ])
  })
})

describe("functionImportCard", () => {
  it("reads the function and its target off the source", () => {
    const post = segment({
      kind: "sap_write",
      op: "function_import",
      source: {
        service: "API_SUPPLIERINVOICE_PROCESS_SRV",
        entity: "Post",
        key: "5105600000/2026",
      },
      fields: [{ name: "SupplierInvoice", value: "5105600000" }],
    })
    expect(functionImportCard(post)).toEqual({
      fn: "Post",
      target: "5105600000/2026",
      params: [{ name: "SupplierInvoice", value: "5105600000" }],
    })
  })

  it("names itself when the source recorded nothing", () => {
    expect(functionImportCard(segment({ kind: "sap_write", op: "function_import" }))).toEqual({
      fn: "Function import",
      target: undefined,
      params: [],
    })
  })
})
