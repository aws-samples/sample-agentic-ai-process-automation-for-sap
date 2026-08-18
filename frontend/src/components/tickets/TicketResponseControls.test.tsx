// SPDX-License-Identifier: Apache-2.0

import { beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import {
  InlineCaseTicket,
  TicketResponseControls,
} from "@/components/tickets/TicketResponseControls"
import { fetchTicket, submitTicketAction } from "@/services/ticketsService"
import { fetchCase } from "@/services/casesService"
import { TicketPriority, TicketStatus, type Ticket } from "@/types/tickets"
import { TraceSegmentType, type AgentTrace } from "@/types/cases"

vi.mock("@/services/ticketsService", () => ({
  fetchTicket: vi.fn(),
  submitTicketAction: vi.fn(),
}))

vi.mock("@/services/casesService", () => ({
  fetchCase: vi.fn(),
}))

const ticket = (overrides: Partial<Ticket> = {}): Ticket => ({
  ticket_id: "TKT-1",
  title: "Confirm invoice release",
  description: "Approve release of invoice 5100001976",
  status: TicketStatus.Open,
  priority: TicketPriority.Medium,
  response_type: "approval" as Ticket["response_type"],
  case_id: "5100001976#2026",
  created_at: "2026-07-29T00:00:00Z",
  updated_at: "2026-07-29T00:00:00Z",
  ...overrides,
})

beforeEach(() => {
  vi.clearAllMocks()
})

const REASON_LABEL = "Why you are approving or denying"

/** A case whose newest run escalated with a structured write. */
const TRACES = [
  {
    trace_id: "t1",
    timestamp: "2026-07-29T00:00:00Z",
    segments: [
      {
        type: TraceSegmentType.Tool,
        evidence: {
          kind: "sap_read",
          source: { entity: "A_SupplierInvoice", key: "5100001976" },
          fields: [{ name: "PaymentBlockingReason", value: "A" }],
        },
      },
      {
        type: TraceSegmentType.Tool,
        evidence: {
          kind: "notification",
          proposed_write: {
            op: "update",
            entity: "A_SupplierInvoice",
            key: "5100001976",
            fields: [{ name: "PaymentBlockingReason", current: "A", proposed: "" }],
          },
        },
      },
    ],
  },
] as unknown as AgentTrace[]

describe("TicketResponseControls", () => {
  it("submits the reviewer's own words on both decisions", () => {
    const onAction = vi.fn()
    render(<TicketResponseControls ticket={ticket()} onAction={onAction} />)

    fireEvent.change(screen.getByLabelText(REASON_LABEL), {
      target: { value: "  Within the 5% tolerance  " },
    })

    fireEvent.click(screen.getByRole("button", { name: "Approve" }))
    expect(onAction).toHaveBeenCalledWith("approved", "Within the 5% tolerance")

    fireEvent.click(screen.getByRole("button", { name: "Deny" }))
    expect(onAction).toHaveBeenCalledWith("denied", "Within the 5% tolerance")
  })

  it("refuses either decision until a reason is written", () => {
    render(<TicketResponseControls ticket={ticket()} onAction={vi.fn()} />)
    const approve = screen.getByRole("button", { name: "Approve" }) as HTMLButtonElement
    const deny = screen.getByRole("button", { name: "Deny" }) as HTMLButtonElement

    expect(approve.disabled).toBe(true)
    expect(deny.disabled).toBe(true)
    expect(screen.getByText("A reason is required.")).toBeInTheDocument()

    // Whitespace is not a reason.
    fireEvent.change(screen.getByLabelText(REASON_LABEL), { target: { value: "   \n  " } })
    expect(approve.disabled).toBe(true)
    expect(deny.disabled).toBe(true)

    fireEvent.change(screen.getByLabelText(REASON_LABEL), {
      target: { value: "Confirmed with AP" },
    })
    expect(approve.disabled).toBe(false)
    expect(deny.disabled).toBe(false)
  })

  it("puts the proposed write above the decision, verified against the run's reads", () => {
    render(<TicketResponseControls ticket={ticket()} traces={TRACES} onAction={vi.fn()} />)
    expect(screen.getByText("Proposed")).toBeInTheDocument()
    expect(screen.getByText("PaymentBlockingReason")).toBeInTheDocument()
    // Cleared to empty, and the stated current value matched the read — not flagged.
    expect(screen.getByText("A")).not.toHaveClass("text-red-700")
    expect(screen.getByText("(empty)")).toBeInTheDocument()
  })

  it("states the absence when the agent declared no structured write", () => {
    render(<TicketResponseControls ticket={ticket()} traces={[]} onAction={vi.fn()} />)
    expect(screen.getByText(/recorded no structured write/)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument()
  })

  it("requires and preserves a free-text reply", () => {
    const onAction = vi.fn()
    render(
      <TicketResponseControls
        ticket={ticket({ response_type: "free_text" as Ticket["response_type"] })}
        onAction={onAction}
      />
    )

    const send = screen.getByRole("button", { name: "Send Reply" })
    expect((send as HTMLButtonElement).disabled).toBe(true)

    fireEvent.change(screen.getByLabelText("Your response"), {
      target: { value: "  Use PO 4500002664  " },
    })
    fireEvent.click(send)

    expect(onAction).toHaveBeenCalledWith("replied", "Use PO 4500002664", "Use PO 4500002664")
  })
})

describe("InlineCaseTicket", () => {
  /** Write a reason, then take the decision — the only path to either button now. */
  function decide(name: "Approve" | "Deny", reason: string) {
    fireEvent.change(screen.getByLabelText(REASON_LABEL), { target: { value: reason } })
    fireEvent.click(screen.getByRole("button", { name }))
  }

  it("loads the correlated ticket and resumes the agent from the case detail", async () => {
    const current = ticket()
    vi.mocked(fetchTicket).mockResolvedValue(current)
    vi.mocked(fetchCase).mockResolvedValue({ agent_traces: TRACES } as never)
    vi.mocked(submitTicketAction).mockResolvedValue({
      ticket: { ...current, status: TicketStatus.Approved },
      enqueued: true,
      case_id: "5100001976#2026",
    })
    const onSubmitted = vi.fn().mockResolvedValue(undefined)

    render(
      <MemoryRouter>
        <InlineCaseTicket ticketId="TKT-1" token="token" onSubmitted={onSubmitted} />
      </MemoryRouter>
    )

    await screen.findByText("Confirm invoice release")
    // The case's proposal reaches the reviewer before the decision does.
    await screen.findByText("Proposed")
    decide("Approve", "GR matches, releasing")

    await waitFor(() =>
      expect(submitTicketAction).toHaveBeenCalledWith(
        "TKT-1",
        "approved",
        "GR matches, releasing",
        "token",
        undefined
      )
    )
    expect((await screen.findByRole("status")).textContent).toContain("agent has been resumed")
    expect(onSubmitted).toHaveBeenCalledOnce()
  })

  it("keeps the decision available when the case cannot be read", async () => {
    vi.mocked(fetchTicket).mockResolvedValue(ticket())
    vi.mocked(fetchCase).mockRejectedValue(new Error("Case unavailable"))

    render(
      <MemoryRouter>
        <InlineCaseTicket ticketId="TKT-1" token="token" />
      </MemoryRouter>
    )

    await screen.findByText("Confirm invoice release")
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
    expect(await screen.findByText(/recorded no structured write/)).toBeInTheDocument()
  })

  it("surfaces a ticket action failure", async () => {
    vi.mocked(fetchTicket).mockResolvedValue(ticket())
    vi.mocked(fetchCase).mockResolvedValue({ agent_traces: [] } as never)
    vi.mocked(submitTicketAction).mockRejectedValue(new Error("Resume failed"))

    render(
      <MemoryRouter>
        <InlineCaseTicket ticketId="TKT-1" token="token" />
      </MemoryRouter>
    )

    await screen.findByText("Confirm invoice release")
    decide("Deny", "Variance exceeds tolerance")

    expect((await screen.findByRole("alert")).textContent).toContain("Resume failed")
  })

  it("surfaces a ticket load failure", async () => {
    vi.mocked(fetchTicket).mockRejectedValue(new Error("Ticket unavailable"))

    render(
      <MemoryRouter>
        <InlineCaseTicket ticketId="TKT-1" token="token" />
      </MemoryRouter>
    )

    expect((await screen.findByRole("alert")).textContent).toContain("Ticket unavailable")
  })
})
