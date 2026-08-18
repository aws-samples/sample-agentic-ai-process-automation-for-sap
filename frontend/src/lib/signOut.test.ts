// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, beforeEach } from "vitest"
import { QueryClient } from "@tanstack/react-query"
import { clearOperatorContext } from "@/lib/signOut"
import { getTranscript, setTranscript } from "@/lib/transcript"

/**
 * What a shared workstation must not carry from one operator to the next: the
 * assistant's transcript (which holds SAP tool results — PO numbers, amounts, vendor
 * names), the cached case records, and the focused case in the address bar.
 *
 * The allowlist is the load-bearing part. It is inverted on purpose — a key added
 * later is wiped unless someone names it as layout — so these pin the direction, not
 * just today's key list.
 */
describe("clearOperatorContext", () => {
  beforeEach(() => {
    localStorage.clear()
    setTranscript([])
    window.history.replaceState({}, "", "/")
  })

  it("drops the transcript, which carries SAP tool results", () => {
    setTranscript([
      {
        role: "assistant",
        content: "PO 4500001234 is 8,412.00 EUR to Acme GmbH",
        timestamp: "2026-07-01T00:00:00Z",
      },
    ])
    clearOperatorContext(new QueryClient())
    expect(getTranscript()).toEqual([])
  })

  it("drops cached case records", () => {
    const client = new QueryClient()
    client.setQueryData(["case", "5100001976-2026"], { case_id: "5100001976-2026" })
    clearOperatorContext(client)
    expect(client.getQueryData(["case", "5100001976-2026"])).toBeUndefined()
  })

  it("forgets which case was open and how the queue was filtered", () => {
    localStorage.setItem("workspace.case", "5100001976-2026")
    localStorage.setItem("workspace.status", "awaiting_human_input")
    localStorage.setItem("workspace.handoverHours", "72")
    clearOperatorContext(new QueryClient())
    expect(localStorage.getItem("workspace.case")).toBeNull()
    expect(localStorage.getItem("workspace.status")).toBeNull()
    expect(localStorage.getItem("workspace.handoverHours")).toBeNull()
  })

  it("keeps how the window was arranged", () => {
    const layout: Record<string, string> = {
      "ui.theme": "dark",
      "ui.density": "compact",
      "ui.dock.collapsed": "1",
      "workspace.casesCollapsed": "1",
      "workspace.panelSizes.v2": "[500,900]",
      "workspace.panelSizes.detail.v2": "[380,720]",
      "workspace.domain": "finance_ap",
    }
    for (const [k, v] of Object.entries(layout)) localStorage.setItem(k, v)
    clearOperatorContext(new QueryClient())
    for (const [k, v] of Object.entries(layout)) expect(localStorage.getItem(k)).toBe(v)
  })

  it("wipes an unrecognized app key rather than leaving it behind", () => {
    // The failure this guards: a later feature persists case data under a new key and
    // nobody remembers to add it to a deletion list.
    localStorage.setItem("workspace.somethingAddedLater", "5100001976-2026")
    clearOperatorContext(new QueryClient())
    expect(localStorage.getItem("workspace.somethingAddedLater")).toBeNull()
  })

  it("leaves the OIDC library's own storage alone", () => {
    // oidc-client-ts removes its stored user itself during signout, and clearing its
    // keys underneath it would break the in-flight end-session request.
    localStorage.setItem("oidc.user:https://issuer:client", "{}")
    clearOperatorContext(new QueryClient())
    expect(localStorage.getItem("oidc.user:https://issuer:client")).toBe("{}")
  })

  it("strips the focused case from the address bar", () => {
    window.history.replaceState({}, "", "/?case=5100001976-2026&status=detected")
    clearOperatorContext(new QueryClient())
    expect(window.location.search).toBe("")
    expect(window.location.pathname).toBe("/")
  })
})
