// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, afterEach } from "vitest"
import { render, screen, cleanup, fireEvent } from "@testing-library/react"
import { CaseTimeline } from "@/components/case/CaseTimeline"
import { TraceSegmentType, Trigger } from "@/types/cases"
import type { AgentTrace, TraceSegment } from "@/types/cases"

function toolSegment(evidence: Record<string, unknown> | undefined, extra = {}): TraceSegment {
  return {
    type: TraceSegmentType.Tool,
    tool_name: "odata_read",
    tool_input: '{"entity_set":"A_SupplierInvoice"}',
    tool_result: '{"InvoiceGrossAmount":"1250.00"}',
    ...(evidence ? { evidence } : {}),
    ...extra,
  } as TraceSegment
}

const READ_EVIDENCE = {
  kind: "sap_read",
  at: "2026-07-01T10:00:00Z",
  source: { service: "API_SUPPLIERINVOICE", entity: "A_SupplierInvoice", key: "5100001976" },
  fields: [{ name: "InvoiceGrossAmount", value: "1250.00" }],
  authz: { mode: "LOG_ONLY", via_gateway: true, outcome: "permitted" },
}

const WRITE_EVIDENCE = {
  kind: "sap_write",
  op: "update",
  source: { entity: "A_PurchaseOrderItem", key: "4500000123/10" },
  fields: [{ name: "NetPriceAmount", value: "12.50" }],
  authz: { mode: "ENFORCE", via_gateway: true, outcome: "permitted" },
}

function trace(overrides: Partial<AgentTrace> = {}): AgentTrace {
  return {
    trace_id: "trace-latest",
    timestamp: "2026-07-01T10:00:00Z",
    trigger: Trigger.Poller,
    outcome: "complete",
    segments: [
      { type: TraceSegmentType.Text, content: "Looking up the invoice." } as TraceSegment,
      toolSegment(READ_EVIDENCE),
      toolSegment(WRITE_EVIDENCE, { tool_name: "odata_update" }),
      {
        type: TraceSegmentType.Text,
        content: "Variance within tolerance; released.",
      } as TraceSegment,
    ],
    ...overrides,
  }
}

afterEach(cleanup)

describe("CaseTimeline", () => {
  it("states the zero state and how to leave it", () => {
    render(<CaseTimeline traces={[]} />)
    expect(screen.getByText("No processing history yet.")).toBeInTheDocument()
    expect(screen.getByText(/Process this case/i)).toBeInTheDocument()
  })

  it("shows every step of the latest run without a click", () => {
    render(<CaseTimeline traces={[trace()]} />)
    expect(screen.getByText("Read A_SupplierInvoice 5100001976")).toBeInTheDocument()
    expect(screen.getByText("Updated A_PurchaseOrderItem 4500000123/10")).toBeInTheDocument()
    expect(screen.getByText("Variance within tolerance; released.")).toBeInTheDocument()
  })

  it("renders field values in mono, out of evidence", () => {
    render(<CaseTimeline traces={[trace()]} />)
    // The headline is visible without a click; the field values are one level in.
    fireEvent.click(screen.getByRole("button", { name: /Read A_SupplierInvoice/ }))
    expect(screen.getByText("1250.00")).toHaveClass("font-mono")
  })

  it("expands a write into a before/after diff against the read that preceded it", () => {
    const po = { service: "API_PO", entity: "A_PurchaseOrderItem", key: "4500000123/10" }
    const diffable = trace({
      segments: [
        toolSegment({
          kind: "sap_read",
          source: po,
          fields: [{ name: "NetPriceAmount", value: "12.00" }],
        }),
        toolSegment({ ...WRITE_EVIDENCE, source: po }, { tool_name: "odata_update" }),
      ],
    })
    render(<CaseTimeline traces={[diffable]} />)
    fireEvent.click(screen.getByRole("button", { name: /Updated A_PurchaseOrderItem/ }))
    expect(screen.getByText("Applied")).toBeInTheDocument()
    expect(screen.getByText("12.00")).toHaveClass("font-mono")
    expect(screen.getByText("12.50")).toHaveClass("font-mono")
  })

  it("expands a ticket carrying a proposed write into a proposal diff", () => {
    const asking = trace({
      segments: [
        toolSegment({
          kind: "notification",
          proposed_write: {
            op: "update",
            entity: "A_SupplierInvoice",
            key: "5100001976",
            fields: [{ name: "PaymentBlockingReason", current: "A", proposed: "" }],
          },
        }),
      ],
    })
    render(<CaseTimeline traces={[asking]} />)
    fireEvent.click(screen.getByRole("button", { name: /Notification sent/ }))
    expect(screen.getByText("Proposed")).toBeInTheDocument()
    expect(screen.getByText("PaymentBlockingReason")).toBeInTheDocument()
    expect(screen.getByText("A")).toHaveClass("font-mono")
  })

  it("collapses reasoning behind a disclosure and leaves the conclusion visible", () => {
    render(<CaseTimeline traces={[trace()]} />)
    expect(screen.queryByText("Looking up the invoice.")).not.toBeInTheDocument()
    const toggle = screen.getByRole("button", { name: /Reasoning \(1 step\)/ })
    expect(toggle).toHaveAttribute("aria-expanded", "false")
    fireEvent.click(toggle)
    expect(screen.getByText("Looking up the invoice.")).toBeInTheDocument()
  })

  it("puts the authz chip on the write row only", () => {
    render(<CaseTimeline traces={[trace()]} />)
    expect(screen.getAllByText("Cedar: permitted")).toHaveLength(1)
  })

  it("reports the Cedar decision, not just the mode it ran in", () => {
    const denied = trace({
      segments: [
        toolSegment(
          { ...WRITE_EVIDENCE, authz: { mode: "ENFORCE", via_gateway: true, outcome: "rejected" } },
          { tool_name: "odata_update", status: "error" }
        ),
      ],
    })
    render(<CaseTimeline traces={[denied]} />)
    // A rejected write and a permitted one previously read identically — both said
    // "Cedar: enforced", which is the mode, not the decision.
    expect(screen.getByText("Cedar: rejected")).toHaveClass("bg-red-50")
  })

  it("says a log-only permit did not gate the write", () => {
    const logged = trace({
      segments: [
        toolSegment(
          {
            ...WRITE_EVIDENCE,
            authz: { mode: "LOG_ONLY", via_gateway: true, outcome: "permitted" },
          },
          { tool_name: "odata_update" }
        ),
      ],
    })
    render(<CaseTimeline traces={[logged]} />)
    // Permitted, but the permit was advisory — so it must not take the success tone.
    const chip = screen.getByText(/Cedar: permitted/)
    expect(chip.textContent).toContain("(log only)")
    expect(chip).not.toHaveClass("bg-emerald-50")
  })

  it("distinguishes a write Cedar never saw from one it logged", () => {
    const obo = trace({
      segments: [
        toolSegment(
          { ...WRITE_EVIDENCE, authz: { mode: "LOG_ONLY", via_gateway: false } },
          { tool_name: "odata_update" }
        ),
      ],
    })
    render(<CaseTimeline traces={[obo]} />)
    // The OBO topology bypasses our Gateway. That is not "logged only" — nothing
    // evaluated it — and it previously rendered no chip at all.
    expect(screen.getByText("Cedar: not evaluated")).toBeInTheDocument()
  })

  it("does not report a non-authorization failure as a denial", () => {
    const timedOut = trace({
      segments: [
        toolSegment(
          { ...WRITE_EVIDENCE, authz: { mode: "ENFORCE", via_gateway: true } },
          { tool_name: "odata_update", status: "error" }
        ),
      ],
    })
    render(<CaseTimeline traces={[timedOut]} />)
    expect(screen.getByText("Cedar: no decision")).toBeInTheDocument()
    expect(screen.queryByText("Cedar: rejected")).not.toBeInTheDocument()
  })

  it("marks a recorded tool failure as failed", () => {
    const failing = trace({
      segments: [toolSegment(READ_EVIDENCE, { status: "error" })],
    })
    render(<CaseTimeline traces={[failing]} />)
    expect(screen.getByLabelText("Step failed")).toBeInTheDocument()
  })

  it("leaves an unrecorded status unmarked rather than flagging it", () => {
    render(<CaseTimeline traces={[trace({ segments: [toolSegment(READ_EVIDENCE)] })]} />)
    expect(screen.queryByLabelText("Step failed")).not.toBeInTheDocument()
  })

  it("claims no decision when a log-only evaluation recorded no outcome", () => {
    const logged = trace({
      segments: [
        toolSegment({ ...WRITE_EVIDENCE, authz: { mode: "LOG_ONLY", via_gateway: true } }),
      ],
    })
    render(<CaseTimeline traces={[logged]} />)
    // Cedar ran, but nothing came back to report. Naming the mode alone would imply
    // the write was cleared by a policy that never returned a verdict.
    expect(screen.getByText("Cedar: no decision")).toBeInTheDocument()
  })

  it("treats a stored non-array fields value as no fields", () => {
    // DynamoDB JSON, and `Evidence`'s index signature admits this. Asserting on the
    // disclosure rather than the headline: unguarded, a scalar's truthy `.length` opens
    // a row whose panel throws in `.map`.
    const malformed = trace({
      segments: [toolSegment({ kind: "sap_read", fields: "InvoiceGrossAmount" })],
    })
    render(<CaseTimeline traces={[malformed]} />)
    expect(screen.getByRole("button", { name: /Read from SAP/ })).not.toHaveAttribute(
      "aria-expanded"
    )
  })

  it("renders a trace with no segments without throwing", () => {
    const empty = trace({ segments: undefined as unknown as TraceSegment[] })
    render(<CaseTimeline traces={[empty]} />)
    expect(screen.getByText("This run recorded no steps.")).toBeInTheDocument()
  })

  it("does not claim a disclosure on a row with nothing behind it", () => {
    const bare = trace({
      segments: [toolSegment({ kind: "sap_write", op: "update" })],
    })
    render(<CaseTimeline traces={[bare]} />)
    expect(screen.getByRole("button", { name: /Updated to SAP/ })).not.toHaveAttribute(
      "aria-expanded"
    )
  })

  it("renders a pre-evidence trace on the tool-call path without error", () => {
    const legacy = trace({ segments: [toolSegment(undefined)] })
    render(<CaseTimeline traces={[legacy]} />)
    expect(screen.getByText("odata_read")).toBeInTheDocument()
  })

  it("keeps prior runs collapsed under a date label", () => {
    const older = trace({
      trace_id: "trace-older",
      timestamp: "2026-06-28T09:00:00Z",
      segments: [toolSegment(READ_EVIDENCE, { tool_name: "odata_count" })],
    })
    render(<CaseTimeline traces={[trace(), older]} />)
    const runToggle = screen.getByRole("button", { name: /Jun 28/ })
    expect(runToggle).toHaveAttribute("aria-expanded", "false")
    fireEvent.click(runToggle)
    expect(runToggle).toHaveAttribute("aria-expanded", "true")
  })

  it("labels the trigger of the latest run", () => {
    render(<CaseTimeline traces={[trace()]} />)
    expect(screen.getByText("Poller")).toBeInTheDocument()
  })

  it("dates the latest run, not just its time of day", () => {
    // Otherwise a case opened days after processing reads the bare time as today.
    render(<CaseTimeline traces={[trace()]} />)
    expect(screen.getByText(/Jul 1/)).toBeInTheDocument()
  })
})
