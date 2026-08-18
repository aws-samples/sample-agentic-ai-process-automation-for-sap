// SPDX-License-Identifier: Apache-2.0

import { useEffect, useState } from "react"
import { Link } from "react-router"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { fetchTicket, submitTicketAction } from "@/services/ticketsService"
import { fetchCase } from "@/services/casesService"
import { TONE_BANNER, TONE_TEXT } from "@/lib/statusTone"
import { pendingProposal, proposedRows } from "@/lib/writeDiff"
import { WriteDiff } from "@/components/case/WriteDiff"
import type { AgentTrace } from "@/types/cases"
import type { Ticket } from "@/types/tickets"

export type TicketAction = "approved" | "denied" | "replied"

interface TicketResponseControlsProps {
  ticket: Ticket
  submitting?: boolean
  /** The case's runs, for the diff. Absent while they load, or on a ticket with no case. */
  traces?: AgentTrace[]
  onAction: (
    action: TicketAction,
    resolution: string,
    responseText?: string
  ) => Promise<void> | void
}

/**
 * What the agent is asking to write, above the decision it is asking for.
 *
 * A ticket created before writes were declared as structured intent has no proposal —
 * that is most of them at first, so the absence is stated rather than hidden. Silence
 * would read as "this write changes nothing".
 */
function ProposalDiff({ traces }: { traces?: AgentTrace[] }) {
  const pending = traces && pendingProposal(traces)
  if (!pending) {
    return (
      <p className="text-2xs text-muted-foreground">
        The agent recorded no structured write for this request — read the description above for
        what it is asking.
      </p>
    )
  }
  return <WriteDiff rows={proposedRows(pending.proposal, pending.steps)} label="Proposed" />
}

/** Render the response control requested by a pending ticket. */
export function TicketResponseControls({
  ticket,
  submitting = false,
  traces,
  onAction,
}: TicketResponseControlsProps) {
  const [replyText, setReplyText] = useState("")
  const actionable = ticket.status === "open" || ticket.status === "assigned"

  useEffect(() => setReplyText(""), [ticket.ticket_id])

  if (!actionable) return null

  if (ticket.response_type === "free_text") {
    const reply = replyText.trim()
    return (
      <div className="space-y-2">
        <label htmlFor={`ticket-reply-${ticket.ticket_id}`} className="text-xs font-medium">
          Your response
        </label>
        <Textarea
          id={`ticket-reply-${ticket.ticket_id}`}
          placeholder="Type your reply…"
          value={replyText}
          disabled={submitting}
          onChange={event => setReplyText(event.target.value)}
          className="min-h-[72px] resize-y"
        />
        <Button
          size="sm"
          disabled={submitting || !reply}
          onClick={() => onAction("replied", reply, reply)}
        >
          {submitting ? "Sending…" : "Send Reply"}
        </Button>
      </div>
    )
  }

  // Both decisions are gated on a reason: a denial with no stated cause strands the
  // case in manual review with nothing for the next person to act on, which is the
  // same defect as an unexplained approval.
  const reason = replyText.trim()
  return (
    <div className="space-y-2">
      <ProposalDiff traces={traces} />
      <label htmlFor={`ticket-reply-${ticket.ticket_id}`} className="block text-xs font-medium">
        Why you are approving or denying
      </label>
      <Textarea
        id={`ticket-reply-${ticket.ticket_id}`}
        placeholder="e.g. Variance is within the 5% tolerance and the GR matches"
        value={replyText}
        disabled={submitting}
        onChange={event => setReplyText(event.target.value)}
        className="min-h-[72px] resize-y"
      />
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          disabled={submitting || !reason}
          onClick={() => onAction("approved", reason)}
        >
          Approve
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={submitting || !reason}
          onClick={() => onAction("denied", reason)}
        >
          Deny
        </Button>
        {!reason && <span className="text-2xs text-muted-foreground">A reason is required.</span>}
      </div>
    </div>
  )
}

interface InlineCaseTicketProps {
  ticketId: string
  token: string
  onSubmitted?: () => Promise<void> | void
}

/** Load and render the supervised response associated with a case. */
export function InlineCaseTicket({ ticketId, token, onSubmitted }: InlineCaseTicketProps) {
  const [ticket, setTicket] = useState<Ticket | null>(null)
  const [traces, setTraces] = useState<AgentTrace[] | undefined>(undefined)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitted, setSubmitted] = useState(false)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError(null)
    setSubmitted(false)
    fetchTicket(ticketId, token)
      .then(async result => {
        if (!active) return
        setTicket(result)
        if (!result.case_id) return
        // The proposal lives in the case's traces, not on the ticket. A failure here
        // costs the diff, not the decision — ProposalDiff states the absence.
        const item = await fetchCase(result.case_id, token).catch(() => undefined)
        if (active) setTraces(item?.agent_traces)
      })
      .catch(reason => {
        if (active) setError(reason instanceof Error ? reason.message : "Failed to load ticket")
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [ticketId, token])

  async function respond(action: TicketAction, resolution: string, responseText?: string) {
    setSubmitting(true)
    setError(null)
    try {
      const result = await submitTicketAction(ticketId, action, resolution, token, responseText)
      if (!result.enqueued) throw new Error("Response was saved but the agent was not resumed")
      setTicket(result.ticket)
      setSubmitted(true)
      await onSubmitted?.()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Failed to submit response")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className={`space-y-2 rounded-md border-l-4 p-3 ${TONE_BANNER.attention}`}>
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wider">Reviewer response</h3>
        <Link
          className="text-xs underline"
          to={
            ticket?.case_id ? `/tickets?case_id=${encodeURIComponent(ticket.case_id)}` : "/tickets"
          }
        >
          Open ticket
        </Link>
      </div>
      {loading ? (
        <p className="text-xs opacity-80">Loading request…</p>
      ) : error ? (
        <p role="alert" className={`text-xs ${TONE_TEXT.danger}`}>
          {error}
        </p>
      ) : ticket ? (
        <div className="space-y-2">
          <div>
            <p className="text-sm font-medium">{ticket.title}</p>
            <p className="whitespace-pre-wrap text-xs opacity-90">{ticket.description}</p>
          </div>
          {submitted && (
            <p role="status" className={`text-xs font-medium ${TONE_TEXT.success}`}>
              Response submitted. The agent has been resumed.
            </p>
          )}
          <TicketResponseControls
            ticket={ticket}
            submitting={submitting}
            traces={traces}
            onAction={respond}
          />
        </div>
      ) : null}
    </section>
  )
}
