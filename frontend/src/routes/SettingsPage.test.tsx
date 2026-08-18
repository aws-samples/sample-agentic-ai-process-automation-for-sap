// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fetchRuntimeConfig, saveRuntimeConfig } from "@/services/configService"

/**
 * The settings form edits values that decide whether money moves, so the parts
 * pinned here are the ones whose failure is silent: an empty field must mean
 * "revert to the deployed default" rather than "store a blank", only changed
 * fields may travel, and a value the API would refuse must not be offered.
 */

vi.mock("@/services/configService", () => ({
  fetchRuntimeConfig: vi.fn(),
  saveRuntimeConfig: vi.fn(async () => ({ updated: 1, updated_by: "ops@example.com" })),
}))
vi.mock("@/hooks/useFreshToken", () => ({
  useFreshToken: () => async () => ({ idToken: "id" }),
}))
vi.mock("react-oidc-context", () => ({ useAuth: () => ({ isAuthenticated: true }) }))

import SettingsPage from "@/routes/SettingsPage"

const CONFIG = {
  defaults: {
    contacts: { ap_team: "ap@example.com", procurement: "buy@example.com" },
    constants: { finance_ap: { QTY_VARIANCE_PCT: 5, LINE_AMOUNT_TOLERANCE_USD: 100 } },
  },
  overrides: { contacts: { ap_team: "edited@example.com" }, constants: {} },
  bounds: { QTY_VARIANCE_PCT: [0, 100] as [number, number] },
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <SettingsPage />
    </QueryClientProvider>
  )
}

/** The one field this suite drives most; `capitalize` is CSS, so the name is raw. */
function tolerance() {
  return screen.findByLabelText(/QTY_VARIANCE_PCT/)
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(fetchRuntimeConfig).mockResolvedValue(structuredClone(CONFIG))
  vi.mocked(saveRuntimeConfig).mockResolvedValue({ updated: 1, updated_by: "ops@example.com" })
})

afterEach(cleanup)

describe("SettingsPage", () => {
  it("shows the deployed value as the placeholder and the override as the value", async () => {
    renderPage()
    // The distinction is the whole point of returning defaults and overrides
    // separately: an operator has to be able to see which fields they changed.
    const contact = (await screen.findByLabelText(/ap team/i)) as HTMLInputElement
    expect(contact.value).toBe("edited@example.com")
    expect(contact.placeholder).toBe("ap@example.com")

    const untouched = screen.getByLabelText(/procurement/i) as HTMLInputElement
    expect(untouched.value).toBe("")
    expect(untouched.placeholder).toBe("buy@example.com")
  })

  it("marks only the fields that differ from the deployment", async () => {
    renderPage()
    await screen.findByLabelText(/ap team/i)
    expect(screen.getAllByText("Overridden")).toHaveLength(1)
  })

  it("sends only the fields that changed", async () => {
    renderPage()
    fireEvent.change(await tolerance(), { target: { value: "7" } })
    fireEvent.click(screen.getByRole("button", { name: /^Save/ }))

    await waitFor(() => expect(saveRuntimeConfig).toHaveBeenCalled())
    // ap_team already carries an override; leaving it alone must not re-send it,
    // or every save would rewrite rows nobody touched and restamp their audit trail.
    expect(vi.mocked(saveRuntimeConfig).mock.calls[0][0]).toEqual({
      constants: { finance_ap: { QTY_VARIANCE_PCT: 7 } },
    })
  })

  it("clearing an overridden field sends null so the row is deleted", async () => {
    renderPage()
    fireEvent.change(await screen.findByLabelText(/ap team/i), { target: { value: "" } })
    fireEvent.click(screen.getByRole("button", { name: /^Save/ }))

    await waitFor(() => expect(saveRuntimeConfig).toHaveBeenCalled())
    // Storing "" would substitute a blank address into the SOP — the agent would
    // notify nobody and the prompt would read as if it had a target.
    expect(vi.mocked(saveRuntimeConfig).mock.calls[0][0]).toEqual({ contacts: { ap_team: null } })
  })

  it("refuses to save a tolerance outside the range the API accepts", async () => {
    renderPage()
    fireEvent.change(await tolerance(), { target: { value: "500" } })

    expect(screen.getByRole("button", { name: /^Save/ }).hasAttribute("disabled")).toBe(true)
    expect(screen.getByText(/between 0 and 100/)).toBeTruthy()
    expect(saveRuntimeConfig).not.toHaveBeenCalled()
  })

  it("has nothing to save until something changes", async () => {
    renderPage()
    await screen.findByLabelText(/ap team/i)
    expect(screen.getByRole("button", { name: "Save" }).hasAttribute("disabled")).toBe(true)
    expect(screen.queryByRole("button", { name: "Discard" })).toBeNull()
  })

  it("discard restores the persisted overrides", async () => {
    renderPage()
    const contact = (await screen.findByLabelText(/ap team/i)) as HTMLInputElement
    fireEvent.change(contact, { target: { value: "other@example.com" } })
    fireEvent.click(screen.getByRole("button", { name: "Discard" }))
    expect(contact.value).toBe("edited@example.com")
  })

  it("surfaces a rejected save and keeps the edit on screen", async () => {
    vi.mocked(saveRuntimeConfig).mockRejectedValue(new Error("Unknown contact 'cfo'"))
    renderPage()
    const contact = (await screen.findByLabelText(/ap team/i)) as HTMLInputElement
    fireEvent.change(contact, { target: { value: "new@example.com" } })
    fireEvent.click(screen.getByRole("button", { name: /^Save/ }))

    expect(await screen.findByText("Unknown contact 'cfo'")).toBeTruthy()
    // Discarding the operator's typing on a failed write would make them retype it
    // to find out whether the second attempt is refused for the same reason.
    expect(contact.value).toBe("new@example.com")
  })

  it("a skill that declares no constants renders no tolerance section", async () => {
    vi.mocked(fetchRuntimeConfig).mockResolvedValue({
      ...structuredClone(CONFIG),
      defaults: { contacts: {}, constants: { example_finance_accruals: {} } },
    })
    renderPage()
    expect(await screen.findByText(/No contacts declared/)).toBeTruthy()
    expect(screen.queryByText(/Tolerances/)).toBeNull()
  })
})
