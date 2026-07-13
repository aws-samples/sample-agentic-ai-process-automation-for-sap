// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
// AUTO-GENERATED from types/cases.schema.json — do not edit manually.
// Regenerate with: make generate-types

/**
 * Single source of truth for ERP automation work item types. Generated into TS and Python
 * via `make generate-types`.
 */
export interface WorkItem {
  /**
   * Historical agent thought-process traces, one per invocation.
   */
  agent_traces?: AgentTrace[]
  /**
   * AP: Transaction amount.
   */
  amount?: number | null
  /**
   * SAP company code.
   */
  company_code?: null | string
  created_at: string
  /**
   * AP: Currency code (e.g. USD).
   */
  currency?: null | string
  /**
   * Short detail text.
   */
  description?: null | string
  /**
   * AP: Invoice document date.
   */
  document_date?: null | string
  /**
   * SAP document number (e.g. supplier invoice). Partition key.
   */
  document_number: string
  /**
   * Skill domain this item belongs to.
   */
  domain: Domain
  /**
   * AP: Payment blocking reason.
   */
  exception_type?: null | string
  /**
   * AP: Supplier's own invoice ID.
   */
  external_reference?: null | string
  /**
   * ISO timestamp of an outbound inquiry, if the workflow sent one.
   */
  inquiry_sent_at?: null | string
  /**
   * AP: Invoiced quantity in PO unit.
   */
  invoice_quantity?: number | null
  /**
   * Item identifier within the document. Sort key.
   */
  item_id: string
  /**
   * AP: PO line item number.
   */
  po_line_item?: null | string
  /**
   * AP: Posting date.
   */
  posting_date?: null | string
  priority?: Priority
  /**
   * Specific process type for skill routing, e.g. invoice_matching, price_variance.
   */
  process_type: string
  /**
   * AP: PO number referenced on the invoice line item.
   */
  purchase_order?: null | string
  status: CaseStatus
  /**
   * AP: Supplier/vendor number.
   */
  supplier_number?: null | string
  /**
   * Human-readable summary for display.
   */
  title?: string
  ttl?: number | null
  updated_at: string
  /**
   * Case-level resolution quality rating from a human reviewer.
   */
  user_rating?: UserRating
  /**
   * ISO timestamp of when the rating was submitted.
   */
  user_rating_at?: null | string
  /**
   * Optional comment explaining the rating.
   */
  user_rating_comment?: null | string
}

export interface AgentTrace {
  /**
   * Invocation result: complete, stopped, cancelled, error, disconnected.
   */
  outcome?: string
  prompt?: string
  segments: TraceSegment[]
  timestamp: string
  trace_id: string
  /**
   * What initiated this invocation.
   */
  trigger?: Trigger
}

export interface TraceSegment {
  content?: string
  tool_input?: string
  tool_name?: string
  tool_result?: string
  type: Type
  [property: string]: any
}

export enum Type {
  Text = "text",
  Tool = "tool",
}

/**
 * What initiated this invocation.
 *
 * What initiated an agent invocation.
 */
export enum Trigger {
  Manual = "manual",
  Poller = "poller",
  TicketAction = "ticket-action",
  WebhookJira = "webhook-jira",
  WebhookServicenow = "webhook-servicenow",
  WebhookSes = "webhook-ses",
  WebhookSlack = "webhook-slack",
}

/**
 * Skill domain this item belongs to.
 *
 * Skill domain — aligns with skills/ folder names.
 */
export enum Domain {
  FinanceAp = "finance_ap",
}

export enum Priority {
  High = "high",
  Low = "low",
  Medium = "medium",
}

export enum CaseStatus {
  AwaitingHumanInput = "awaiting_human_input",
  Complete = "complete",
  Detected = "detected",
  ManualReviewRequired = "manual_review_required",
  Processing = "processing",
  SapUpdated = "sap_updated",
}

/**
 * Case-level resolution quality rating from a human reviewer.
 */
export enum UserRating {
  Negative = "negative",
  Positive = "positive",
}
