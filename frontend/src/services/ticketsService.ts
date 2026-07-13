// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Ticket, TicketStatus } from "@/types/tickets"
import { getConfig } from "@/lib/config"

export async function fetchTickets(
  filter: { status?: TicketStatus | "all"; assigned_to?: string },
  token: string
): Promise<Ticket[]> {
  const { apiUrl } = await getConfig()
  const params = new URLSearchParams()
  if (filter.status && filter.status !== "all") params.set("status", filter.status)
  if (filter.assigned_to) params.set("assigned_to", filter.assigned_to)

  const res = await fetch(`${apiUrl}/tickets?${params}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error(`Failed to fetch tickets: ${res.status}`)
  return res.json()
}

export async function fetchTicket(ticketId: string, token: string): Promise<Ticket> {
  const { apiUrl } = await getConfig()
  const res = await fetch(`${apiUrl}/tickets/${ticketId}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error(`Failed to fetch ticket: ${res.status}`)
  return res.json()
}

export async function createTicket(
  data: {
    title: string
    description: string
    priority?: string
    assigned_to?: string
    category?: string
  },
  token: string
): Promise<Ticket> {
  const { apiUrl } = await getConfig()
  const res = await fetch(`${apiUrl}/tickets`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(`Failed to create ticket: ${res.status}`)
  return res.json()
}

export async function updateTicket(
  ticketId: string,
  data: {
    status?: string
    assigned_to?: string
    resolution?: string
    comment?: string
    comment_author?: string
  },
  token: string
): Promise<Ticket> {
  const { apiUrl } = await getConfig()
  const res = await fetch(`${apiUrl}/tickets/${ticketId}`, {
    method: "PUT",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(`Failed to update ticket: ${res.status}`)
  return res.json()
}

export async function submitTicketAction(
  ticketId: string,
  action: "approved" | "denied" | "replied",
  resolution: string,
  token: string,
  responseText?: string
): Promise<{ ticket: Ticket; enqueued: boolean; case_id: string }> {
  const { apiUrl } = await getConfig()
  const res = await fetch(`${apiUrl}/tickets/${ticketId}/action`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      action,
      resolution,
      comment: action === "replied" ? `Reply: ${resolution}` : `Ticket ${action} by user`,
      ...(responseText ? { response_text: responseText } : {}),
    }),
  })
  if (!res.ok) throw new Error(`Failed to submit ticket action: ${res.status}`)
  return res.json()
}
