// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { Domain } from "@/types/cases"
import type { WorkItem } from "@/types/cases"
import { timeAgo } from "@/lib/timeAgo"

type Fmt = (n?: number | null, currency?: string | null) => string

/**
 * A money figure, or an em-dash when there is none. Two decimals always, so a
 * column of amounts lines up and `1200` never reads as a different precision from
 * `1200.50`.
 *
 * With no `currency`, the leading `$` is a shape rather than a claim — the case's own
 * currency is rendered beside the figure by the caller. Pass `currency` where the
 * figure is a total that would otherwise be read as dollars: a EUR sum printed with a
 * `$` is a wrong number, not an unlabelled one.
 */
export function formatAmount(n?: number | null, currency?: string | null): string {
  if (n == null) return "—"
  const figure = n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  if (!currency) return `$${figure}`
  return currency === "USD" ? `$${figure}` : `${figure} ${currency}`
}

export interface DomainField {
  label: string
  value: string
  /**
   * The precise value behind an approximated `value`, for a `title` attribute. A
   * relative age is scannable; the stamp it came from still has to be recoverable.
   */
  exact?: string
  /**
   * The SAP field this figure was read from, or `undefined` when the case record
   * is itself the source. Mirrors `field_map` in
   * `lambdas/odata_poller/domains/<domain>.json` — if a path moves there it moves
   * here, and a figure with no entry renders unattributed rather than guessing.
   */
  sapField?: string
}

/**
 * The service and entity a domain's figures were polled from, for the panel-level
 * statement. One line beats repeating the entity on every row.
 */
export const DOMAIN_SOURCE: Partial<Record<Domain, { service: string; entity: string }>> = {
  [Domain.FinanceAp]: { service: "API_SUPPLIERINVOICE_PROCESS_SRV", entity: "A_SupplierInvoice" },
}

/** Return display fields appropriate for the case's domain, each with its origin. */
export function domainFields(c: WorkItem, fmt: Fmt): DomainField[] {
  // `Created` and `Updated` are our own bookkeeping, so they carry no `sapField`.
  // Claiming an SAP origin for them is the same defect as leaving a real SAP
  // figure unattributed.
  const common: DomainField[] = [
    { label: "Company Code", value: c.company_code ?? "—", sapField: "CompanyCode" },
    { label: "Created", value: timeAgo(c.created_at), exact: c.created_at },
    { label: "Updated", value: timeAgo(c.updated_at), exact: c.updated_at },
  ]

  const fields: Record<Domain, DomainField[]> = {
    [Domain.FinanceAp]: [
      { label: "Supplier", value: c.supplier_number ?? "—", sapField: "InvoicingParty" },
      { label: "Amount", value: fmt(c.amount, c.currency), sapField: "InvoiceGrossAmount" },
      { label: "Currency", value: c.currency ?? "—", sapField: "DocumentCurrency" },
      { label: "Exception", value: c.exception_type ?? "—", sapField: "PaymentBlockingReason" },
      { label: "Doc Date", value: c.document_date?.split("T")[0] ?? "—", sapField: "DocumentDate" },
      {
        label: "Posting Date",
        value: c.posting_date?.split("T")[0] ?? "—",
        sapField: "PostingDate",
      },
      {
        label: "External Ref",
        value: c.external_reference ?? "—",
        sapField: "SupplierInvoiceIDByInvcgParty",
      },
    ],
  }

  return [...(fields[c.domain] ?? fields[Domain.FinanceAp]), ...common]
}
