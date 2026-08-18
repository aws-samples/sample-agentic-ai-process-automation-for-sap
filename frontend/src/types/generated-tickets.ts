// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
// AUTO-GENERATED from types/tickets.schema.json — do not edit manually.
// Regenerate with: make generate-types

/**
 * Single source of truth for ticket management types. Generated into TS and Python via
 * `make generate-types`.
 */
export interface Ticket {
  /**
   * Person or team assigned to the ticket.
   */
  assigned_to?: null | string
  /**
   * Related ERP case identity for correlation, canonical {document_number}-{item_id} form.
   * Built and parsed only via the case_key codec.
   */
  case_id?: null | string
  /**
   * Ticket category (e.g. approval_request, exception, inquiry).
   */
  category?: null | string
  /**
   * Chronological list of comments on the ticket.
   */
  comments?: TicketComment[]
  /**
   * ISO timestamp of creation.
   */
  created_at: string
  /**
   * User or agent that created the ticket.
   */
  created_by?: null | string
  /**
   * Detailed description of the issue or request.
   */
  description: string
  priority: TicketPriority
  /**
   * Resolution notes.
   */
  resolution?: null | string
  /**
   * Expected response type: 'approval' shows approve/deny buttons, 'free_text' shows a reply
   * textarea.
   */
  response_type?: ResponseType
  status: TicketStatus
  /**
   * Unique ticket identifier (e.g. TKT-A1B2C3D4).
   */
  ticket_id: string
  /**
   * Short summary of the ticket.
   */
  title: string
  /**
   * ISO timestamp of last update.
   */
  updated_at: string
}

export interface TicketComment {
  /**
   * Comment author (user alias or 'agent').
   */
  author: string
  /**
   * Comment body.
   */
  text: string
  /**
   * ISO timestamp.
   */
  timestamp: string
}

/**
 * Ticket priority level.
 */
export enum TicketPriority {
  High = "high",
  Low = "low",
  Medium = "medium",
}

/**
 * Expected response type: 'approval' shows approve/deny buttons, 'free_text' shows a reply
 * textarea.
 */
export enum ResponseType {
  Approval = "approval",
  FreeText = "free_text",
}

/**
 * Ticket lifecycle status.
 */
export enum TicketStatus {
  Approved = "approved",
  Assigned = "assigned",
  Closed = "closed",
  Denied = "denied",
  Open = "open",
  Replied = "replied",
}
