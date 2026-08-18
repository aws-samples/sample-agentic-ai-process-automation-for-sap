// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest"
import { fetchRuntimeConfig, saveRuntimeConfig } from "@/services/configService"

vi.mock("@/lib/config", () => ({
  getConfig: vi.fn().mockResolvedValue({ apiUrl: "https://api.test" }),
}))

function okJson(body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => body,
  })
}

function errResponse(status: number, body: unknown = {}) {
  return vi.fn().mockResolvedValue({
    ok: false,
    status,
    json: async () => body,
  })
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("configService", () => {
  it("fetchRuntimeConfig GETs /config with the bearer token", async () => {
    const fetchMock = okJson({ defaults: {}, overrides: {}, bounds: {} })
    vi.stubGlobal("fetch", fetchMock)

    await fetchRuntimeConfig("tok")

    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("https://api.test/config")
    expect(opts.headers.Authorization).toBe("Bearer tok")
  })

  it("saveRuntimeConfig PUTs the patch as-is", async () => {
    const fetchMock = okJson({ updated: 2, updated_by: "ops@example.com" })
    vi.stubGlobal("fetch", fetchMock)

    const patch = {
      contacts: { ap_team: "new@example.com" },
      constants: { finance_ap: { QTY_VARIANCE_PCT: 7 } },
    }
    const result = await saveRuntimeConfig(patch, "tok")

    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("https://api.test/config")
    expect(opts.method).toBe("PUT")
    expect(JSON.parse(opts.body)).toEqual(patch)
    expect(result.updated).toBe(2)
  })

  it("sends null through rather than dropping it — that is how a revert is expressed", async () => {
    const fetchMock = okJson({ updated: 1, updated_by: "ops@example.com" })
    vi.stubGlobal("fetch", fetchMock)

    await saveRuntimeConfig({ constants: { finance_ap: { QTY_VARIANCE_PCT: null } } }, "tok")

    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      constants: { finance_ap: { QTY_VARIANCE_PCT: null } },
    })
  })

  it("surfaces every field the API refused, not just the status", async () => {
    // The API rejects a request whole and names each bad field. Collapsing that to
    // "400" would leave the operator guessing which row it disagreed with.
    vi.stubGlobal(
      "fetch",
      errResponse(400, {
        error: "Invalid fields",
        details: ["Contact 'ap_team' must be an email address", "Unknown skill 'nope'"],
      })
    )

    await expect(saveRuntimeConfig({ contacts: { ap_team: "bad" } }, "tok")).rejects.toThrow(
      /must be an email address; Unknown skill 'nope'/
    )
  })

  it("falls back to the error field when there are no per-field details", async () => {
    vi.stubGlobal("fetch", errResponse(400, { error: "No valid fields provided" }))
    await expect(saveRuntimeConfig({}, "tok")).rejects.toThrow("No valid fields provided")
  })

  it("still throws with the status when the error body is unreadable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 502,
        json: async () => {
          throw new Error("not json")
        },
      })
    )
    await expect(saveRuntimeConfig({}, "tok")).rejects.toThrow(/Failed to save configuration: 502/)
  })
})
