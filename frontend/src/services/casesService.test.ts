// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest"
import {
  fetchCases,
  fetchCase,
  enqueueCases,
  submitCaseRating,
  saveAgentTrace,
} from "@/services/casesService"
import { Domain } from "@/types/cases"

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

describe("casesService", () => {
  it("fetchCases builds query, sets auth header, returns json", async () => {
    const fetchMock = okJson([{ id: 1 }])
    vi.stubGlobal("fetch", fetchMock)

    const result = await fetchCases({ status: "open" as never, domain: Domain.FinanceAp }, "tok")

    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("https://api.test/cases?status=open&domain=finance_ap")
    expect(opts.headers.Authorization).toBe("Bearer tok")
    expect(result).toEqual([{ id: 1 }])
  })

  it("fetchCases throws on non-ok", async () => {
    vi.stubGlobal("fetch", errResponse(500))
    await expect(fetchCases({}, "tok")).rejects.toThrow(/Failed to fetch cases: 500/)
  })

  it("fetchCase hits the case_id path", async () => {
    const fetchMock = okJson({ id: "x" })
    vi.stubGlobal("fetch", fetchMock)
    await fetchCase("DOC1-ITEM1", "tok")
    expect(fetchMock.mock.calls[0][0]).toBe("https://api.test/cases/DOC1-ITEM1")
  })

  it("enqueueCases POSTs one request per id with case_id body", async () => {
    const fetchMock = okJson({})
    vi.stubGlobal("fetch", fetchMock)
    await enqueueCases(["a", "b"], "tok")
    expect(fetchMock).toHaveBeenCalledTimes(2)
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("https://api.test/cases/enqueue")
    expect(opts.method).toBe("POST")
    expect(JSON.parse(opts.body)).toEqual({ case_id: "a" })
  })

  it("enqueueCases surfaces error body text on failure", async () => {
    vi.stubGlobal("fetch", errResponse(409, "duplicate"))
    await expect(enqueueCases(["a"], "tok")).rejects.toThrow(/duplicate/)
  })

  it("submitCaseRating PUTs rating and comment", async () => {
    const fetchMock = okJson({})
    vi.stubGlobal("fetch", fetchMock)
    await submitCaseRating("DOC1-ITEM1", "positive", "nice", "tok")
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("https://api.test/cases/DOC1-ITEM1/rating")
    expect(opts.method).toBe("PUT")
    expect(JSON.parse(opts.body)).toEqual({ rating: "positive", comment: "nice" })
  })

  it("saveAgentTrace POSTs to the traces endpoint", async () => {
    const fetchMock = okJson({})
    vi.stubGlobal("fetch", fetchMock)
    const trace = { trace_id: "t1", segments: [] } as never
    await saveAgentTrace("DOC1-ITEM1", trace, "tok")
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("https://api.test/cases/DOC1-ITEM1/traces")
    expect(opts.method).toBe("POST")
  })

  it("saveAgentTrace throws on non-ok", async () => {
    vi.stubGlobal("fetch", errResponse(500))
    await expect(saveAgentTrace("DOC1-ITEM1", {} as never, "tok")).rejects.toThrow(
      /Failed to save trace: 500/
    )
  })

  it("fetchCases with no filter produces a trailing ? URL", async () => {
    const fetchMock = okJson([])
    vi.stubGlobal("fetch", fetchMock)
    await fetchCases({}, "tok")
    expect(fetchMock.mock.calls[0][0]).toBe("https://api.test/cases?")
  })
})
