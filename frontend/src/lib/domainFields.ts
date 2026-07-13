// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { Domain } from "@/types/cases"
import type { WorkItem } from "@/types/cases"

type Fmt = (n?: number | null) => string

/** Return display field tuples appropriate for the case's domain. */
export function domainFields(c: WorkItem, fmt: Fmt): [string, string][] {
  const common: [string, string][] = [
    ["Company Code", c.company_code ?? "—"],
    ["Created", c.created_at],
    ["Updated", c.updated_at],
  ]

  const fields: Record<Domain, [string, string][]> = {
    [Domain.FinanceAp]: [
      ["Supplier", c.supplier_number ?? "—"],
      ["Amount", fmt(c.amount)],
      ["Currency", c.currency ?? "—"],
      ["Exception", c.exception_type ?? "—"],
      ["Doc Date", c.document_date?.split("T")[0] ?? "—"],
      ["Posting Date", c.posting_date?.split("T")[0] ?? "—"],
      ["External Ref", c.external_reference ?? "—"],
    ],
  }

  return [...(fields[c.domain] ?? fields[Domain.FinanceAp]), ...common]
}
