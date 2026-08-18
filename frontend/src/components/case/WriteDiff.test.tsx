// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, afterEach } from "vitest"
import { render, screen, cleanup } from "@testing-library/react"
import { WriteDiff } from "@/components/case/WriteDiff"
import type { DiffRow } from "@/lib/writeDiff"

afterEach(cleanup)

const CHANGED: DiffRow = {
  name: "NetPriceAmount",
  before: "12.00",
  after: "12.50",
  state: "changed",
}

describe("WriteDiff", () => {
  it("renders both sides of a change in mono", () => {
    render(<WriteDiff rows={[CHANGED]} label="Applied" />)
    expect(screen.getByText("12.00")).toHaveClass("font-mono")
    expect(screen.getByText("12.50")).toHaveClass("font-mono")
    expect(screen.getByText("Applied")).toBeInTheDocument()
  })

  it("marks a write that changed nothing", () => {
    render(
      <WriteDiff
        rows={[{ name: "PriceUnit", before: "1", after: "1", state: "unchanged" }]}
        label="Applied"
      />
    )
    expect(screen.getByText("unchanged")).toBeInTheDocument()
  })

  it("states the absence rather than rendering a half-empty table", () => {
    render(
      <WriteDiff
        rows={[{ name: "NetPriceAmount", after: "12.50", state: "no-baseline" }]}
        label="Applied"
      />
    )
    expect(screen.getByText(/No read of this record in this run/)).toBeInTheDocument()
    expect(screen.getByText("12.50")).toBeInTheDocument()
    expect(screen.queryByLabelText("to")).not.toBeInTheDocument()
  })

  it("carries the danger tone and the observed value on a mismatch", () => {
    render(
      <WriteDiff
        rows={[
          {
            name: "NetPriceAmount",
            before: "12.00",
            after: "12.50",
            state: "mismatch",
            observed: "11.00",
          },
        ]}
        label="Proposed"
      />
    )
    expect(screen.getByText("12.00")).toHaveClass("text-red-700")
    expect(screen.getByText("11.00")).toBeInTheDocument()
  })

  it("says a stated value could not be verified without claiming it is wrong", () => {
    render(
      <WriteDiff
        rows={[{ name: "NetPriceAmount", before: "12.00", after: "12.50", state: "unverified" }]}
        label="Proposed"
      />
    )
    expect(screen.getByText("not verified against a read in this run")).toBeInTheDocument()
    expect(screen.getByText("12.00")).not.toHaveClass("text-red-700")
  })

  it("renders a function import as an action with its parameters, not as a diff", () => {
    render(
      <WriteDiff
        rows={[]}
        label="Applied"
        card={{
          fn: "Post",
          target: "5105600000/2026",
          params: [{ name: "SupplierInvoice", value: "5105600000" }],
        }}
      />
    )
    expect(screen.getByText("Post")).toBeInTheDocument()
    expect(screen.getByText("5105600000/2026")).toBeInTheDocument()
    expect(screen.getByText(/changes no field values/)).toBeInTheDocument()
    expect(screen.queryByLabelText("to")).not.toBeInTheDocument()
  })

  it("distinguishes a value cleared to empty from one with no value on record", () => {
    render(
      <WriteDiff
        rows={[{ name: "PaymentBlockingReason", before: "A", after: "", state: "changed" }]}
        label="Applied"
      />
    )
    expect(screen.getByText("(empty)")).toBeInTheDocument()
  })

  it("states a write that recorded no fields at all", () => {
    render(<WriteDiff rows={[]} label="Applied" />)
    expect(screen.getByText("This write recorded no field values.")).toBeInTheDocument()
  })

  it("states a proposal that recorded no fields at all", () => {
    render(<WriteDiff rows={[]} label="Proposed" />)
    expect(screen.getByText("The agent recorded no fields for this proposal.")).toBeInTheDocument()
  })

  it("renders a caller's own note beneath the table", () => {
    render(<WriteDiff rows={[CHANGED]} label="Proposed" note="Awaiting your decision." />)
    expect(screen.getByText("Awaiting your decision.")).toBeInTheDocument()
  })
})
