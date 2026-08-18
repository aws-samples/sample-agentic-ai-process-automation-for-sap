// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// Re-export generated types (source of truth: types/tickets.schema.json)
export { TicketStatus, TicketPriority } from "./generated-tickets"
export type { Ticket, TicketComment } from "./generated-tickets"

import { TicketStatus, TicketPriority } from "./generated-tickets"
import type { StatusTone } from "@/lib/statusTone"

// UI-only display metadata — not part of the schema.
// `tone` selects the shared state colour — see lib/statusTone.ts. Emoji were
// dropped with the shared badge: screen readers announce them literally
// ("large blue circle"), and the badge already carries a colour-coded dot.
export const TICKET_STATUS_META: Record<TicketStatus, { label: string; tone: StatusTone }> = {
  [TicketStatus.Open]: { label: "Open", tone: "info" },
  [TicketStatus.Assigned]: { label: "Assigned", tone: "progress" },
  [TicketStatus.Approved]: { label: "Approved", tone: "success" },
  [TicketStatus.Denied]: { label: "Denied", tone: "danger" },
  // A human has answered and the agent is expected to pick it back up.
  [TicketStatus.Replied]: { label: "Replied", tone: "info" },
  [TicketStatus.Closed]: { label: "Closed", tone: "neutral" },
}

/** Display metadata for a ticket status, tolerating unknown values from older records. */
export function ticketStatusMeta(status: TicketStatus | string): {
  label: string
  tone: StatusTone
} {
  return TICKET_STATUS_META[status as TicketStatus] ?? TICKET_STATUS_META[TicketStatus.Open]
}

// Priority is urgency, not state, but it is still colour-as-meaning, so it maps
// onto the same tone vocabulary rather than carrying its own palette classes.
export const TICKET_PRIORITY_META: Record<TicketPriority, { label: string; tone: StatusTone }> = {
  [TicketPriority.High]: { label: "High", tone: "danger" },
  [TicketPriority.Medium]: { label: "Medium", tone: "progress" },
  [TicketPriority.Low]: { label: "Low", tone: "neutral" },
}

/** Display metadata for a ticket priority, tolerating unknown values from older records. */
export function ticketPriorityMeta(priority: TicketPriority | string): {
  label: string
  tone: StatusTone
} {
  return (
    TICKET_PRIORITY_META[priority as TicketPriority] ?? TICKET_PRIORITY_META[TicketPriority.Medium]
  )
}
