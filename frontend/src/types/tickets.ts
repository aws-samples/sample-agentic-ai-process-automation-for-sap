// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// Re-export generated types (source of truth: types/tickets.schema.json)
export { TicketStatus, TicketPriority } from "./generated-tickets"
export type { Ticket, TicketComment } from "./generated-tickets"

import { TicketStatus, TicketPriority } from "./generated-tickets"

// UI-only display metadata — not part of the schema
export const TICKET_STATUS_META: Record<
  TicketStatus,
  { label: string; color: string; emoji: string }
> = {
  [TicketStatus.Open]: { label: "Open", color: "bg-blue-100 text-blue-800", emoji: "🔵" },
  [TicketStatus.Assigned]: {
    label: "Assigned",
    color: "bg-yellow-100 text-yellow-800",
    emoji: "🟡",
  },
  [TicketStatus.Approved]: { label: "Approved", color: "bg-green-100 text-green-800", emoji: "✅" },
  [TicketStatus.Denied]: { label: "Denied", color: "bg-red-100 text-red-800", emoji: "🔴" },
  [TicketStatus.Replied]: { label: "Replied", color: "bg-purple-100 text-purple-800", emoji: "💬" },
  [TicketStatus.Closed]: { label: "Closed", color: "bg-gray-100 text-gray-800", emoji: "⚫" },
}

export const TICKET_PRIORITY_META: Record<TicketPriority, { label: string; color: string }> = {
  [TicketPriority.High]: { label: "High", color: "bg-red-100 text-red-800" },
  [TicketPriority.Medium]: { label: "Medium", color: "bg-yellow-100 text-yellow-800" },
  [TicketPriority.Low]: { label: "Low", color: "bg-green-100 text-green-800" },
}
