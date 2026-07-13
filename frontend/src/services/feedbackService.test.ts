// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest"
import { submitFeedback } from "@/services/feedbackService"

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

const payload = {
  sessionId: "s1",
  message: "m",
  feedbackType: "positive" as const,
}

describe("feedbackService", () => {
  it("POSTs feedback to /feedback and returns json", async () => {
    const fetchMock = okJson({ success: true, feedbackId: "f1" })
    vi.stubGlobal("fetch", fetchMock)
    const res = await submitFeedback(payload, "tok")
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("https://api.test/feedback")
    expect(opts.method).toBe("POST")
    expect(opts.headers.Authorization).toBe("Bearer tok")
    expect(res).toEqual({ success: true, feedbackId: "f1" })
  })

  it("throws errorData.error when the error body provides one", async () => {
    vi.stubGlobal("fetch", errResponse(400, { error: "bad payload" }))
    await expect(submitFeedback(payload, "tok")).rejects.toThrow(/bad payload/)
  })

  it("falls back to status message when error body is not JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        json: async () => {
          throw new Error("not json")
        },
      })
    )
    await expect(submitFeedback(payload, "tok")).rejects.toThrow(/HTTP error! status: 500/)
  })
})
