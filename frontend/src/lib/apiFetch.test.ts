// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest"
import { apiFetch } from "@/lib/apiFetch"

function okJson(body: unknown, status = 200) {
  return vi.fn().mockResolvedValue({
    ok: true,
    status,
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

describe("apiFetch", () => {
  it("attaches the bearer token and returns parsed JSON", async () => {
    const fetchMock = okJson({ ok: true })
    vi.stubGlobal("fetch", fetchMock)
    const result = await apiFetch("https://api.test/x", { token: "tok" }, "Failed")
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("https://api.test/x")
    expect(opts.headers.Authorization).toBe("Bearer tok")
    expect(result).toEqual({ ok: true })
  })

  it("JSON-encodes body and sets Content-Type only when a body is given", async () => {
    const fetchMock = okJson({})
    vi.stubGlobal("fetch", fetchMock)
    await apiFetch("https://api.test/x", { token: "tok", method: "POST", body: { a: 1 } }, "Failed")
    const [, opts] = fetchMock.mock.calls[0]
    expect(opts.headers["Content-Type"]).toBe("application/json")
    expect(opts.body).toBe(JSON.stringify({ a: 1 }))
  })

  it("omits Content-Type when no body is given", async () => {
    const fetchMock = okJson({})
    vi.stubGlobal("fetch", fetchMock)
    await apiFetch("https://api.test/x", { token: "tok" }, "Failed")
    const [, opts] = fetchMock.mock.calls[0]
    expect(opts.headers["Content-Type"]).toBeUndefined()
  })

  it("returns undefined for a 204 response without calling .json()", async () => {
    const json = vi.fn()
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 204, json }))
    const result = await apiFetch("https://api.test/x", { token: "tok" }, "Failed")
    expect(result).toBeUndefined()
    expect(json).not.toHaveBeenCalled()
  })

  it("throws '<errorMessage>: <status>' on failure when no parseError is given", async () => {
    vi.stubGlobal("fetch", errResponse(500))
    await expect(apiFetch("https://api.test/x", { token: "tok" }, "Failed")).rejects.toThrow(
      "Failed: 500"
    )
  })

  it("uses parseError's detail when it resolves a truthy string", async () => {
    vi.stubGlobal("fetch", errResponse(400, { error: "bad payload" }))
    await expect(
      apiFetch(
        "https://api.test/x",
        { token: "tok" },
        "Failed",
        async res => (await res.json()).error
      )
    ).rejects.toThrow("bad payload")
  })

  it("falls back to the status message when parseError throws", async () => {
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
    await expect(
      apiFetch(
        "https://api.test/x",
        { token: "tok" },
        "Failed",
        async res => (await res.json()).error
      )
    ).rejects.toThrow("Failed: 500")
  })
})
