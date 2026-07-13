// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// Re-export generated types (source of truth: types/cases.schema.json)
export { CaseStatus, Domain, Priority, Trigger, Type as TraceSegmentType } from "./generated-cases"
export type { WorkItem, AgentTrace, TraceSegment } from "./generated-cases"

import { CaseStatus, Domain } from "./generated-cases"

// UI-only display metadata — not part of the schema
export const CASE_STATUSES = Object.values(CaseStatus)

// `color` styles the pill (bg + text); `dot` is the leading status dot color.
export const STATUS_META: Record<CaseStatus, { label: string; color: string; dot: string }> = {
  [CaseStatus.Detected]: {
    label: "Detected",
    color: "bg-blue-50 text-blue-700",
    dot: "bg-blue-500",
  },
  [CaseStatus.Processing]: {
    label: "Processing",
    color: "bg-amber-50 text-amber-700",
    dot: "bg-amber-500",
  },
  [CaseStatus.AwaitingHumanInput]: {
    label: "Awaiting Input",
    color: "bg-orange-50 text-orange-700",
    dot: "bg-orange-500",
  },
  [CaseStatus.SapUpdated]: {
    label: "SAP Updated",
    color: "bg-green-50 text-green-700",
    dot: "bg-green-500",
  },
  [CaseStatus.Complete]: {
    label: "Complete",
    color: "bg-emerald-50 text-emerald-700",
    dot: "bg-emerald-500",
  },
  [CaseStatus.ManualReviewRequired]: {
    label: "Manual Review",
    color: "bg-red-50 text-red-700",
    dot: "bg-red-500",
  },
}

export const DOMAIN_META: Record<Domain, { label: string; short: string }> = {
  [Domain.FinanceAp]: { label: "Accounts Payable", short: "AP" },
}

export const DOMAINS = Object.values(Domain)
