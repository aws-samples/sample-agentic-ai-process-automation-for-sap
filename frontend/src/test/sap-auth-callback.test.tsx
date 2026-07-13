// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Tests for the SAP auth browser-redirect landing page (/auth/callback).
 */

import { describe, it, expect, afterEach, beforeEach, vi } from "vitest"
import { render, screen, cleanup } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import SapAuthCallback from "@/routes/SapAuthCallback"

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <SapAuthCallback />
    </MemoryRouter>
  )
}

describe("SapAuthCallback", () => {
  beforeEach(() => {
    // jsdom's window.close is unimplemented (and can tear down the document); stub it.
    vi.spyOn(window, "close").mockImplementation(() => {})
  })
  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    // @ts-expect-error — reset the opener we may have set on window
    window.opener = null
  })

  it("renders the success confirmation by default", () => {
    renderAt("/auth/callback?code=abc123&state=xyz")
    expect(screen.getByText(/SAP sign-in complete/i)).toBeTruthy()
    expect(screen.getByText(/return to your conversation and retry/i)).toBeTruthy()
    const link = screen.getByRole("link", { name: /Return to workspace/i })
    expect(link.getAttribute("href")).toBe("/")
  })

  it("renders success even when no query params are present", () => {
    renderAt("/auth/callback")
    expect(screen.getByText(/SAP sign-in complete/i)).toBeTruthy()
  })

  it("renders an error state when an error query param is present", () => {
    renderAt("/auth/callback?error=access_denied&error_description=User%20cancelled")
    expect(screen.getByText(/SAP sign-in failed/i)).toBeTruthy()
    expect(screen.getByText(/User cancelled/i)).toBeTruthy()
    expect(screen.queryByText(/SAP sign-in complete/i)).toBeNull()
  })

  it("posts sap-auth-complete to the opener and closes on success", () => {
    const postMessage = vi.fn()
    // @ts-expect-error — simulate being opened as a popup
    window.opener = { postMessage }
    renderAt("/auth/callback?code=abc123")
    expect(postMessage).toHaveBeenCalledWith({ type: "sap-auth-complete" }, window.location.origin)
    expect(window.close).toHaveBeenCalled()
  })

  it("does NOT signal the opener when the callback carries an error", () => {
    const postMessage = vi.fn()
    // @ts-expect-error — simulate being opened as a popup
    window.opener = { postMessage }
    renderAt("/auth/callback?error=access_denied")
    expect(postMessage).not.toHaveBeenCalled()
    expect(window.close).not.toHaveBeenCalled()
  })
})
