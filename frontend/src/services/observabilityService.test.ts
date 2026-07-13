// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest"
import { fetchMetrics, fetchHealth, fetchTraces } from "@/services/observabilityService"

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

describe("observabilityService", () => {
  it("fetchMetrics uses default hours/period and by_model", async () => {
    const fetchMock = okJson({ summary: {} })
    vi.stubGlobal("fetch", fetchMock)
    await fetchMetrics("tok")
    expect(fetchMock.mock.calls[0][0]).toBe(
      "https://api.test/observability/metrics?hours=24&period=3600&by_model=true"
    )
  })

  it("fetchMetrics reflects custom hours/period", async () => {
    const fetchMock = okJson({})
    vi.stubGlobal("fetch", fetchMock)
    await fetchMetrics("tok", 6, 300)
    expect(fetchMock.mock.calls[0][0]).toBe(
      "https://api.test/observability/metrics?hours=6&period=300&by_model=true"
    )
  })

  it("fetchMetrics throws on non-ok", async () => {
    vi.stubGlobal("fetch", errResponse(502))
    await expect(fetchMetrics("tok")).rejects.toThrow(/Metrics fetch failed: 502/)
  })

  it("fetchHealth GETs the health endpoint", async () => {
    const fetchMock = okJson({ lambdas: [] })
    vi.stubGlobal("fetch", fetchMock)
    await fetchHealth("tok")
    expect(fetchMock.mock.calls[0][0]).toBe("https://api.test/observability/health")
  })

  it("fetchTraces appends hours only when provided", async () => {
    const fetchMock = okJson({ traces: [], total_cases_scanned: 0 })
    vi.stubGlobal("fetch", fetchMock)
    await fetchTraces("tok")
    expect(fetchMock.mock.calls[0][0]).toBe("https://api.test/observability/traces")
    await fetchTraces("tok", 12)
    expect(fetchMock.mock.calls[1][0]).toBe("https://api.test/observability/traces?hours=12")
  })

  it("fetchTraces throws on non-ok", async () => {
    vi.stubGlobal("fetch", errResponse(500))
    await expect(fetchTraces("tok")).rejects.toThrow(/Traces fetch failed: 500/)
  })
})
