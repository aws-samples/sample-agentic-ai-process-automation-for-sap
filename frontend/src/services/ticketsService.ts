// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Ticket, TicketStatus } from "@/types/tickets"
import { getConfig } from "@/lib/config"
import { apiFetch } from "@/lib/apiFetch"

export async function fetchTickets(
  filter: { status?: TicketStatus | "all"; assigned_to?: string },
  token: string
): Promise<Ticket[]> {
  const { apiUrl } = await getConfig()
  const params = new URLSearchParams()
  if (filter.status && filter.status !== "all") params.set("status", filter.status)
  if (filter.assigned_to) params.set("assigned_to", filter.assigned_to)

  return apiFetch(`${apiUrl}/tickets?${params}`, { token }, "Failed to fetch tickets")
}

export async function fetchTicket(ticketId: string, token: string): Promise<Ticket> {
  const { apiUrl } = await getConfig()
  return apiFetch(`${apiUrl}/tickets/${ticketId}`, { token }, "Failed to fetch ticket")
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
  return apiFetch(
    `${apiUrl}/tickets`,
    { token, method: "POST", body: data },
    "Failed to create ticket"
  )
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
  return apiFetch(
    `${apiUrl}/tickets/${ticketId}`,
    { token, method: "PUT", body: data },
    "Failed to update ticket"
  )
}

export async function submitTicketAction(
  ticketId: string,
  action: "approved" | "denied" | "replied",
  resolution: string,
  token: string,
  responseText?: string
): Promise<{ ticket: Ticket; enqueued: boolean; case_id: string }> {
  const { apiUrl } = await getConfig()
  return apiFetch(
    `${apiUrl}/tickets/${ticketId}/action`,
    {
      token,
      method: "POST",
      body: {
        action,
        resolution,
        // The reviewer's own words, on every action. `resolution` is what reaches the
        // resumed agent, so a canned comment here would only diverge from it.
        comment: resolution,
        ...(responseText ? { response_text: responseText } : {}),
      },
    },
    "Failed to submit ticket action"
  )
}
