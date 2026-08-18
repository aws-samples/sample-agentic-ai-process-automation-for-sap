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
   * Append-only audit trail, one entry per update_case_state call. Written by
   * case_management_lambda on every update.
   */
  action_log?: ActionLogEntry[]
  /**
   * Historical agent thought-process traces, one per invocation.
   */
  agent_traces?: AgentTrace[]
  /**
   * AP: Transaction amount.
   */
  amount?: number | null
  /**
   * Canonical case identity and the table's sole partition key: {document_number}-{item_id}.
   * Also the form used off-table — SQS bodies and MessageGroupId, ticket correlation,
   * prompts, URLs, session ids. Built and parsed only via the case_key codec
   * (lambdas/layers/shared_types/case_key.py, frontend/src/lib/caseKey.ts).
   */
  case_id: string
  /**
   * SAP company code.
   */
  company_code?: null | string
  /**
   * Per-case accumulated agent cost. Written by basic_agent._save_trace_to_ddb.
   */
  cost_summary?: CostSummary
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
   * SAP document number (e.g. supplier invoice). An attribute, not identity — SAP calls and
   * display need it.
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
   * ISO timestamp of the outbound inquiry that put the case into awaiting_human_input.
   * Server-owned: stamped by case_management_lambda on entry to that status and cleared on
   * leaving it, never taken from model-authored updates — it is what lets the handover claim
   * 'waiting 6d' rather than 'last activity 6d'.
   */
  inquiry_sent_at?: null | string
  /**
   * AP: Invoiced quantity in PO unit.
   */
  invoice_quantity?: number | null
  /**
   * Item identifier within the document. An attribute, not identity.
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
   * Related demo ticket ID while the case awaits a supervised response.
   */
  ticket_id?: null | string
  /**
   * Human-readable summary for display.
   */
  title?: string
  /**
   * Count of oldest traces evicted by the per-case trace cap, so the UI can state that
   * history was thinned rather than thinning it silently.
   */
  traces_dropped?: number | null
  /**
   * DynamoDB TTL (epoch seconds). Only set by the eval regression harness on seeded synthetic
   * cases (7-day expiry) so they self-clean; real cases never carry this.
   */
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

export interface ActionLogEntry {
  /**
   * Action name the caller supplied, e.g. sap_updated, invoice_released.
   */
  action: string
  timestamp: string
}

export interface AgentTrace {
  /**
   * DEPRECATED — no longer produced. Was the clause-number baseline a `per §N.N` citation was
   * graded against, which passed a fabricated rule wearing a real number; `Evidence.citation`
   * grades the quoted span instead. The key stays declared because AgentTrace forbids extra
   * keys, so removing it would make every already-persisted trace fail validation.
   */
  clauses_available?: string[]
  /**
   * Invocation result: complete, stopped, cancelled, error, disconnected.
   */
  outcome?: string
  prompt?: string
  segments: TraceSegment[]
  /**
   * Version the injected SOP declared in its own header, read at resolve_skill time. Names
   * the authority this run actually followed, which a precedent row citing the case must
   * reproduce even after the SOP is revised.
   */
  sop_version?: string
  timestamp: string
  trace_id: string
  /**
   * What initiated this invocation.
   */
  trigger?: Trigger
}

export interface TraceSegment {
  content?: string
  /**
   * Structured provenance for this tool step. Absent on any trace stored before the T.1
   * migration.
   */
  evidence?: Evidence
  /**
   * ToolResult.status as reported by the SDK. On the segment rather than inside evidence
   * because it is SDK-native, not derived.
   */
  status?: Status
  /**
   * SDK toolUseId. Joins a stream-folded segment to the evidence the AfterToolCallEvent hook
   * extracted.
   */
  tool_call_id?: string
  tool_input?: string
  tool_name?: string
  tool_result?: string
  type: Type
  [property: string]: any
}

/**
 * Structured provenance for this tool step. Absent on any trace stored before the T.1
 * migration.
 *
 * Deterministic provenance for one tool call. Only `kind` is required — an unknown tool
 * falls through to `computation` with no source rather than failing.
 */
export interface Evidence {
  /**
   * ISO timestamp of the tool call.
   */
  at?: string
  authz?: EvidenceAuthz
  /**
   * notification and case_update only — the SOP sentence the agent quoted, checked against
   * the text this run was given.
   */
  citation?: Citation
  /**
   * sop_lookup only — numbered clauses found in the retrieved SOP text. A human locator, not
   * a verification key: most SOPs carry no numbers, so `citation` is what grades.
   */
  clauses_retrieved?: string[]
  /**
   * Field values read or written. The timeline renders these, never model prose.
   */
  fields?: EvidenceField[]
  kind: EvidenceKind
  /**
   * sap_write only — the three write shapes do not render as the same kind of diff.
   */
  op?: WriteOp
  /**
   * notification only — the write the agent is asking permission to make. The one
   * model-supplied key in an otherwise deterministic model, so its `current` values are
   * verified client-side against the run's reads rather than trusted.
   */
  proposed_write?: ProposedWrite
  source?: EvidenceSource
  /**
   * True when the tool_input or tool_result preview hit its size budget.
   */
  truncated?: boolean
  [property: string]: any
}

/**
 * The three authorization facts that are actually available. The matched Cedar policy id is
 * not obtainable from the Gateway.
 */
export interface EvidenceAuthz {
  /**
   * Whether a denial would have blocked.
   */
  mode?: Mode
  /**
   * Absent when a call failed for a non-authorization reason.
   */
  outcome?: Outcome
  /**
   * The call traversed policy evaluation.
   */
  via_gateway?: boolean
  [property: string]: any
}

/**
 * Whether a denial would have blocked.
 */
export enum Mode {
  Enforce = "ENFORCE",
  LogOnly = "LOG_ONLY",
}

/**
 * Absent when a call failed for a non-authorization reason.
 */
export enum Outcome {
  Permitted = "permitted",
  Rejected = "rejected",
}

/**
 * notification and case_update only — the SOP sentence the agent quoted, checked against
 * the text this run was given.
 *
 * A quoted SOP sentence and whether it is present in the text the run was given. Absent
 * when the agent quoted nothing gradeable — which is a different state from quoting
 * something absent.
 */
export interface Citation {
  /**
   * The span as the agent wrote it, before normalization.
   */
  quote: string
  /**
   * False means the span is not in what the agent was shown. It is NOT on its own proof the
   * SOP was violated — a compliant agent that paraphrases lands here too, so the render must
   * never present it as one.
   */
  verified: boolean
  [property: string]: any
}

export interface EvidenceField {
  name: string
  value?: string
  [property: string]: any
}

/**
 * Drives the timeline's row rendering, so the UI never pattern-matches tool names.
 */
export enum EvidenceKind {
  CaseUpdate = "case_update",
  Computation = "computation",
  Notification = "notification",
  SapRead = "sap_read",
  SapWrite = "sap_write",
  SopLookup = "sop_lookup",
}

/**
 * sap_write only — the three write shapes do not render as the same kind of diff.
 *
 * Shares the record half's discriminator — a proposal and a record describe the same three
 * write shapes.
 */
export enum WriteOp {
  Create = "create",
  FunctionImport = "function_import",
  Update = "update",
}

/**
 * notification only — the write the agent is asking permission to make. The one
 * model-supplied key in an otherwise deterministic model, so its `current` values are
 * verified client-side against the run's reads rather than trusted.
 *
 * A write declared as structured intent at escalation time, so an approval can render as a
 * diff instead of prose.
 */
export interface ProposedWrite {
  entity?: string
  fields: ProposedField[]
  key?: string
  /**
   * Shares the record half's discriminator — a proposal and a record describe the same three
   * write shapes.
   */
  op: WriteOp
  service?: string
  [property: string]: any
}

export interface ProposedField {
  /**
   * Absent on a create, and absent whenever the agent did not read the value in this run.
   */
  current?: string
  name: string
  proposed: string
  [property: string]: any
}

/**
 * Where a value came from in SAP.
 */
export interface EvidenceSource {
  entity?: string
  key?: string
  service?: string
  [property: string]: any
}

/**
 * ToolResult.status as reported by the SDK. On the segment rather than inside evidence
 * because it is SDK-native, not derived.
 */
export enum Status {
  Error = "error",
  Success = "success",
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
  Batch = "batch",
  Manual = "manual",
  Poller = "poller",
  TicketAction = "ticket-action",
  WebhookJira = "webhook-jira",
  WebhookServicenow = "webhook-servicenow",
  WebhookSes = "webhook-ses",
}

/**
 * Per-case accumulated agent cost. Written by basic_agent._save_trace_to_ddb.
 *
 * Per-case accumulated agent cost and token counts, summed across every invocation.
 */
export interface CostSummary {
  invocation_count?: number
  total_cache_read_tokens?: number
  total_cost_usd?: number
  total_input_tokens?: number
  total_output_tokens?: number
  [property: string]: any
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

/**
 * `error` is terminal-until-retried: the SOPs and skill prompts instruct the agent to write
 * it when a tool call fails irrecoverably, so it must be a first-class state rather than a
 * value the UI silently renders as 'Detected'.
 */
export enum CaseStatus {
  AwaitingHumanInput = "awaiting_human_input",
  Complete = "complete",
  Detected = "detected",
  Error = "error",
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
