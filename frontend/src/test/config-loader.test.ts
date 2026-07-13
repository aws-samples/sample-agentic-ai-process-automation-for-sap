// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"

describe("getConfig", () => {
  beforeEach(() => {
    vi.resetModules() // clear the cached/pending singleton between tests
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("fetches aws-exports.json, strips trailing slash from apiUrl, derives feature flags", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        apiUrl: "https://api.test/",
        feedbackApiUrl: "https://fb.test",
        ticketingEnabled: true,
        testDataEnabled: true,
        demoApiUrl: "https://demo.test",
      }),
    })
    vi.stubGlobal("fetch", fetchMock)

    const { getConfig } = await import("@/lib/config")
    const cfg = await getConfig()

    expect(fetchMock).toHaveBeenCalledWith("/aws-exports.json")
    expect(cfg.apiUrl).toBe("https://api.test") // trailing slash stripped
    expect(cfg.ticketingEnabled).toBe(true)
    expect(cfg.testDataEnabled).toBe(true)
  })

  it("derives independent flags — ticketing on, test-data off", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ feedbackApiUrl: "https://fb.test", ticketingEnabled: true }),
      })
    )

    const { getConfig } = await import("@/lib/config")
    const cfg = await getConfig()

    expect(cfg.ticketingEnabled).toBe(true)
    expect(cfg.testDataEnabled).toBe(false)
  })

  it("legacy demoEnabled turns both features on", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ feedbackApiUrl: "https://fb.test", demoEnabled: true }),
      })
    )

    const { getConfig } = await import("@/lib/config")
    const cfg = await getConfig()

    expect(cfg.ticketingEnabled).toBe(true)
    expect(cfg.testDataEnabled).toBe(true)
  })

  it("falls back to feedbackApiUrl when apiUrl is absent", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ feedbackApiUrl: "https://fb.test/" }),
      })
    )

    const { getConfig } = await import("@/lib/config")
    const cfg = await getConfig()

    expect(cfg.apiUrl).toBe("https://fb.test")
    expect(cfg.ticketingEnabled).toBe(false)
    expect(cfg.testDataEnabled).toBe(false) // no demoApiUrl / flags
  })

  it("caches the result — fetch is called only once across calls", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ apiUrl: "https://api.test" }),
    })
    vi.stubGlobal("fetch", fetchMock)

    const { getConfig } = await import("@/lib/config")
    await getConfig()
    await getConfig()

    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it("throws when aws-exports.json fails to load", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) })
    )

    const { getConfig } = await import("@/lib/config")
    await expect(getConfig()).rejects.toThrow(/Failed to load aws-exports.json: 404/)
  })
})
