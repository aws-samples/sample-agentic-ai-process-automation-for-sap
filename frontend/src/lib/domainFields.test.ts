// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi } from "vitest"
import { DOMAIN_SOURCE, domainFields } from "@/lib/domainFields"
import { Domain } from "@/types/cases"
import type { WorkItem } from "@/types/cases"

/** `{label: value}`, for the assertions that do not care about attribution. */
const valueMap = (rows: ReturnType<typeof domainFields>) =>
  Object.fromEntries(rows.map(r => [r.label, r.value]))

// Minimal WorkItem fixture; cast to satisfy the type without filling every field.
function makeItem(overrides: Partial<WorkItem> = {}): WorkItem {
  return {
    document_number: "DOC-1",
    item_id: "ITEM-1",
    domain: Domain.FinanceAp,
    company_code: "1000",
    created_at: "2026-01-01T00:00:00",
    updated_at: "2026-01-02T00:00:00",
    supplier_number: "SUP-1",
    amount: 1234.5,
    currency: "USD",
    exception_type: "price_variance",
    document_date: "2026-01-15T00:00:00",
    posting_date: "2026-01-16T00:00:00",
    external_reference: "INV-9",
    ...overrides,
  } as WorkItem
}

describe("domainFields", () => {
  it("returns FinanceAp domain fields followed by common fields, applying fmt to amount", () => {
    const fmt = vi.fn((n?: number | null) => `$${n}`)
    const rows = domainFields(makeItem(), fmt)
    const map = valueMap(rows)

    expect(fmt).toHaveBeenCalledWith(1234.5, "USD")
    expect(map["Supplier"]).toBe("SUP-1")
    expect(map["Amount"]).toBe("$1234.5")
    expect(map["Currency"]).toBe("USD")
    expect(map["Exception"]).toBe("price_variance")
    expect(map["External Ref"]).toBe("INV-9")
    expect(map["Company Code"]).toBe("1000")
    // Relative, so assert the shape — the exact string moves with the wall clock. The
    // stamp it approximates has to stay recoverable, which is what `exact` carries.
    expect(map["Created"]).toMatch(/ago$|^just now$/)
    expect(map["Updated"]).toMatch(/ago$|^just now$/)
    const updated = rows.find(r => r.label === "Updated")
    expect(updated?.exact).toBe("2026-01-02T00:00:00")
    expect(rows.length).toBe(10)
  })

  it("renders em-dash for null/undefined optional fields", () => {
    const fmt = (n?: number | null) => String(n)
    const rows = domainFields(
      makeItem({
        supplier_number: null as unknown as string,
        currency: null as unknown as string,
        exception_type: null as unknown as string,
        external_reference: null as unknown as string,
        company_code: null as unknown as string,
      }),
      fmt
    )
    const map = valueMap(rows)
    expect(map["Supplier"]).toBe("—")
    expect(map["Currency"]).toBe("—")
    expect(map["Exception"]).toBe("—")
    expect(map["External Ref"]).toBe("—")
    expect(map["Company Code"]).toBe("—")
  })

  it("splits document/posting dates at T and em-dashes missing dates", () => {
    const fmt = (n?: number | null) => String(n)
    const map = valueMap(
      domainFields(makeItem({ posting_date: undefined as unknown as string }), fmt)
    )
    expect(map["Doc Date"]).toBe("2026-01-15")
    expect(map["Posting Date"]).toBe("—")
  })

  it("falls back to FinanceAp fields for an unknown domain", () => {
    const fmt = (n?: number | null) => String(n)
    const rows = domainFields(makeItem({ domain: "legacy_domain" as Domain }), fmt)
    expect(valueMap(rows)["Supplier"]).toBe("SUP-1")
    expect(rows.length).toBe(10)
  })

  it("names the SAP field behind every polled figure", () => {
    const rows = domainFields(makeItem(), n => String(n))
    const origin = Object.fromEntries(rows.map(r => [r.label, r.sapField]))
    // These match `field_map` in lambdas/odata_poller/domains/finance_ap.json. A
    // figure an operator cannot trace back to a field is not allowed to render.
    expect(origin["Amount"]).toBe("InvoiceGrossAmount")
    expect(origin["Supplier"]).toBe("InvoicingParty")
    expect(origin["Exception"]).toBe("PaymentBlockingReason")
    expect(origin["External Ref"]).toBe("SupplierInvoiceIDByInvcgParty")
  })

  it("claims no SAP origin for our own bookkeeping", () => {
    const origin = Object.fromEntries(
      domainFields(makeItem(), n => String(n)).map(r => [r.label, r.sapField])
    )
    // Inventing a field name for these would be the same defect in reverse.
    expect(origin["Created"]).toBeUndefined()
    expect(origin["Updated"]).toBeUndefined()
  })

  it("records the service and entity the domain is polled from", () => {
    expect(DOMAIN_SOURCE[Domain.FinanceAp]).toEqual({
      service: "API_SUPPLIERINVOICE_PROCESS_SRV",
      entity: "A_SupplierInvoice",
    })
  })
})
