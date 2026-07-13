// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi } from "vitest"
import { domainFields } from "@/lib/domainFields"
import { Domain } from "@/types/cases"
import type { WorkItem } from "@/types/cases"

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
    const map = Object.fromEntries(rows)

    expect(fmt).toHaveBeenCalledWith(1234.5)
    expect(map["Supplier"]).toBe("SUP-1")
    expect(map["Amount"]).toBe("$1234.5")
    expect(map["Currency"]).toBe("USD")
    expect(map["Exception"]).toBe("price_variance")
    expect(map["External Ref"]).toBe("INV-9")
    expect(map["Company Code"]).toBe("1000")
    expect(map["Created"]).toBe("2026-01-01T00:00:00")
    expect(map["Updated"]).toBe("2026-01-02T00:00:00")
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
    const map = Object.fromEntries(rows)
    expect(map["Supplier"]).toBe("—")
    expect(map["Currency"]).toBe("—")
    expect(map["Exception"]).toBe("—")
    expect(map["External Ref"]).toBe("—")
    expect(map["Company Code"]).toBe("—")
  })

  it("splits document/posting dates at T and em-dashes missing dates", () => {
    const fmt = (n?: number | null) => String(n)
    const map = Object.fromEntries(
      domainFields(makeItem({ posting_date: undefined as unknown as string }), fmt)
    )
    expect(map["Doc Date"]).toBe("2026-01-15")
    expect(map["Posting Date"]).toBe("—")
  })

  it("falls back to FinanceAp fields for an unknown domain", () => {
    const fmt = (n?: number | null) => String(n)
    const rows = domainFields(makeItem({ domain: "legacy_domain" as Domain }), fmt)
    const map = Object.fromEntries(rows)
    expect(map["Supplier"]).toBe("SUP-1")
    expect(rows.length).toBe(10)
  })
})
