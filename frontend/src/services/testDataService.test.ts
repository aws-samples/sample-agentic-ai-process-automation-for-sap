// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest"
import { createApTestCase } from "@/services/testDataService"
import { getConfig } from "@/lib/config"

vi.mock("@/lib/config", () => ({
  getConfig: vi.fn().mockResolvedValue({
    apiUrl: "https://api.test",
    demoApiUrl: "https://demo.test",
  }),
}))

function okJson(body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => body,
    text: async () => JSON.stringify(body),
  })
}

function errResponse(status: number, body: unknown = {}) {
  return vi.fn().mockResolvedValue({
    ok: false,
    status,
    json: async () => body,
    text: async () => (typeof body === "string" ? body : JSON.stringify(body)),
  })
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

const payload = { po_amount: 100, invoice_amount: 110 }

describe("testDataService", () => {
  it("POSTs to the demo endpoint and returns json", async () => {
    const fetchMock = okJson({ domain: "finance_ap", po_amount: 100, invoice_amount: 110 })
    vi.stubGlobal("fetch", fetchMock)
    await createApTestCase(payload, "tok")
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("https://demo.test/demo/test-data/ap-cases")
    expect(opts.method).toBe("POST")
  })

  it("throws early when demoApiUrl is not configured", async () => {
    vi.mocked(getConfig).mockResolvedValueOnce({ apiUrl: "https://api.test" } as never)
    const fetchMock = okJson({})
    vi.stubGlobal("fetch", fetchMock)
    await expect(createApTestCase(payload, "tok")).rejects.toThrow(/Demo API not configured/)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("throws parsed error body on non-ok", async () => {
    vi.stubGlobal("fetch", errResponse(400, { error: "bad scenario" }))
    await expect(createApTestCase(payload, "tok")).rejects.toThrow(/bad scenario/)
  })
})
