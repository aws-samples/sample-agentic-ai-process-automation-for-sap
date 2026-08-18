// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fetchAutonomy, saveTriggerMode } from "@/services/autonomyService"
import { fetchCases } from "@/services/casesService"
import { TONE_TEXT } from "@/lib/statusTone"
import { CaseStatus, Trigger } from "@/types/cases"
import type { WorkItem } from "@/types/cases"

/**
 * `auto` lets the agent write to SAP with nobody watching, so the exit condition has
 * two halves and both are pinned here: an operator can see and change the mode, and
 * cannot arm it by accident. The asymmetry is deliberate and tested — leaving auto is
 * one click, entering it is not.
 *
 * The readout is the third: each mode is asked a different question, and neither answer
 * may overstate what ran unattended.
 */

vi.mock("@/services/autonomyService", async importOriginal => ({
  ...(await importOriginal<typeof import("@/services/autonomyService")>()),
  fetchAutonomy: vi.fn(),
  saveTriggerMode: vi.fn(),
}))
vi.mock("@/services/casesService", () => ({ fetchCases: vi.fn() }))
vi.mock("@/hooks/useFreshToken", () => ({
  useFreshToken: () => async () => ({ idToken: "id" }),
}))
vi.mock("react-oidc-context", () => ({ useAuth: () => ({ isAuthenticated: true }) }))

import { AutonomyGovernor } from "@/components/AutonomyGovernor"

const hoursAgo = (n: number) => new Date(Date.now() - n * 3_600_000).toISOString()

function pollerCase(id: string, status: string = CaseStatus.Complete): WorkItem {
  return {
    case_id: id,
    status,
    updated_at: hoursAgo(1),
    agent_traces: [
      { trace_id: `${id}-0`, timestamp: hoursAgo(1), trigger: Trigger.Poller, segments: [] },
    ],
  } as unknown as WorkItem
}

/** Detected and never started — the backlog, in either mode. */
function waitingCase(id: string): WorkItem {
  return {
    case_id: id,
    status: CaseStatus.Detected,
    updated_at: hoursAgo(1),
    agent_traces: [],
  } as unknown as WorkItem
}

function renderGovernor() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <AutonomyGovernor />
    </QueryClientProvider>
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(fetchAutonomy).mockResolvedValue({ "trigger-mode": "manual" })
  vi.mocked(saveTriggerMode).mockResolvedValue({ "trigger-mode": "auto" })
  vi.mocked(fetchCases).mockResolvedValue([])
})

afterEach(cleanup)

describe("AutonomyGovernor", () => {
  it("states the stored mode", async () => {
    vi.mocked(fetchAutonomy).mockResolvedValue({ "trigger-mode": "auto" })
    renderGovernor()
    expect(await screen.findByText("auto")).toBeTruthy()
    expect(screen.getByText(/acts on new cases unattended/)).toBeTruthy()
  })

  it("distinguishes an unset mode from manual", async () => {
    // The CDK seeds this parameter, so absence means something removed it and the
    // poller's own fallback is what is in force. Rendering that as "manual" would
    // claim a stored decision that does not exist.
    vi.mocked(fetchAutonomy).mockResolvedValue({ "trigger-mode": null })
    renderGovernor()
    expect(await screen.findByText("not set")).toBeTruthy()
    expect(screen.getByText(/falls back to manual/)).toBeTruthy()
  })

  it("cannot flip to auto without typing the word", async () => {
    renderGovernor()
    fireEvent.click(await screen.findByRole("button", { name: /Switch to auto/ }))

    const all = screen.getAllByRole("button", { name: /Switch to auto/ })
    const confirm = all[all.length - 1]
    expect(confirm.hasAttribute("disabled")).toBe(true)

    // A near miss must not arm it either — this is the accident the row is about.
    fireEvent.change(screen.getByLabelText(/Type/), { target: { value: "auto" } })
    expect(confirm.hasAttribute("disabled")).toBe(true)
    expect(saveTriggerMode).not.toHaveBeenCalled()
  })

  it("arms auto once the word is typed", async () => {
    renderGovernor()
    fireEvent.click(await screen.findByRole("button", { name: /Switch to auto/ }))
    fireEvent.change(screen.getByLabelText(/Type/), { target: { value: "AUTO" } })
    const buttons = screen.getAllByRole("button", { name: /Switch to auto/ })
    fireEvent.click(buttons[buttons.length - 1])

    await waitFor(() => expect(saveTriggerMode).toHaveBeenCalledWith("auto", "id"))
  })

  it("leaving auto takes one click and no confirmation", async () => {
    // Asymmetric on purpose: a mode that is hard to leave is a worse failure than one
    // that is hard to enter.
    vi.mocked(fetchAutonomy).mockResolvedValue({ "trigger-mode": "auto" })
    renderGovernor()
    fireEvent.click(await screen.findByRole("button", { name: /Switch to manual/ }))

    await waitFor(() => expect(saveTriggerMode).toHaveBeenCalledWith("manual", "id"))
  })

  describe("the readout", () => {
    // Each mode is asked a different question. A count of invocations answers neither:
    // the poller runs on its timer in both, so it is evidence of scheduling.

    it("in manual, leads with what is piling up", async () => {
      vi.mocked(fetchCases).mockResolvedValue([waitingCase("a"), waitingCase("b")])
      renderGovernor()
      expect(await screen.findByText(/2 cases waiting/)).toBeTruthy()
      expect(screen.getByText(/needs a human to click Process/)).toBeTruthy()
    })

    it("in auto, states where cases ended up rather than how often it fired", async () => {
      vi.mocked(fetchAutonomy).mockResolvedValue({ "trigger-mode": "auto" })
      vi.mocked(fetchCases).mockResolvedValue([
        pollerCase("a", CaseStatus.Complete),
        pollerCase("b", CaseStatus.AwaitingHumanInput),
        pollerCase("c", CaseStatus.Processing),
      ])
      renderGovernor()
      expect(await screen.findByText(/3 cases picked up in the last 24h/)).toBeTruthy()
      expect(screen.getByText(/reached SAP without a further agent run/)).toBeTruthy()
      expect(screen.getByText(/stopped for a human as the SOP requires/)).toBeTruthy()
      expect(screen.getByText(/still running/)).toBeTruthy()
    })

    it("escalation does not read as failure", async () => {
      // The modal outcome in real data — 24 of 50. Red here would show the agent failing
      // half the time while doing exactly what the SOPs prescribe.
      vi.mocked(fetchAutonomy).mockResolvedValue({ "trigger-mode": "auto" })
      vi.mocked(fetchCases).mockResolvedValue([
        pollerCase("a", CaseStatus.AwaitingHumanInput),
        pollerCase("b", CaseStatus.ManualReviewRequired),
      ])
      renderGovernor()
      const line = await screen.findByText(/stopped for a human as the SOP requires/)
      const cls = (tone: string) => `.${CSS.escape(tone.split(" ")[0])}`
      expect(line.querySelector(cls(TONE_TEXT.attention))).toBeTruthy()
      // Both escalation statuses, so this paragraph's only outcome is escalation —
      // any danger tone in it could only have come from that.
      expect(line.closest("p")?.querySelector(cls(TONE_TEXT.danger))).toBeNull()
    })

    it("names an unrecognised status instead of absorbing it", async () => {
      // 16% of the benchmark sample carries a status the schema does not permit. Folding
      // those into any bucket would invent an outcome for them.
      vi.mocked(fetchAutonomy).mockResolvedValue({ "trigger-mode": "auto" })
      vi.mocked(fetchCases).mockResolvedValue([pollerCase("a", "resolved")])
      renderGovernor()
      expect(await screen.findByText(/with an unrecognised status/)).toBeTruthy()
    })

    it("says auto is on while nothing is being enqueued", async () => {
      // The one diagnostic a count of runs cannot show: the poller is finding cases and
      // handing none of them over.
      vi.mocked(fetchAutonomy).mockResolvedValue({ "trigger-mode": "auto" })
      vi.mocked(fetchCases).mockResolvedValue([waitingCase("a"), waitingCase("b")])
      renderGovernor()
      expect(await screen.findByText(/Nothing picked up in the last 24h/)).toBeTruthy()
      expect(screen.getByText(/auto is on but nothing is being enqueued/)).toBeTruthy()
    })

    it("says so when the started count is a floor rather than a total", async () => {
      vi.mocked(fetchAutonomy).mockResolvedValue({ "trigger-mode": "auto" })
      vi.mocked(fetchCases).mockResolvedValue([
        pollerCase("a"),
        { case_id: "b", updated_at: hoursAgo(1), agent_traces: [] } as unknown as WorkItem,
      ])
      renderGovernor()
      expect(await screen.findByText(/At least this many/)).toBeTruthy()
    })

    it("does not qualify the backlog as a floor — it is counted from status", async () => {
      // `partial` is about trace attribution, so it bounds `started` and nothing else.
      // Hedging an exact number would train the operator to distrust the honest ones.
      vi.mocked(fetchCases).mockResolvedValue([waitingCase("a")])
      renderGovernor()
      expect(await screen.findByText(/1 case waiting/)).toBeTruthy()
      expect(screen.queryByText(/At least this many/)).toBeNull()
    })

    it("a grounded zero does not read as missing data", async () => {
      renderGovernor()
      expect(await screen.findByText(/No cases waiting/)).toBeTruthy()
      expect(screen.queryByText(/At least this many/)).toBeNull()
    })
  })

  describe("deployments that cannot trigger unattended", () => {
    // The trigger-mode SSM parameter is seeded unconditionally, but the poller that
    // consumes it exists only when the auth profile declares `autonomous`. So `auto`
    // can be stored and inert, and reading the mode alone would render the panel's
    // most consequential claim — plus a disarm button whose endpoint 405s.

    it("does not claim unattended writes when nothing can trigger", async () => {
      vi.mocked(fetchAutonomy).mockResolvedValue({
        "trigger-mode": "auto",
        "autonomous-capable": false,
      })
      renderGovernor()
      expect(await screen.findByText(/Unattended triggering is not deployed/)).toBeTruthy()
      expect(screen.queryByText(/acts on new cases unattended/)).toBeNull()
    })

    it("does not style an inert mode as dangerous", async () => {
      // Red here would be the same overstatement in a new place.
      vi.mocked(fetchAutonomy).mockResolvedValue({
        "trigger-mode": "auto",
        "autonomous-capable": false,
      })
      renderGovernor()
      const pill = await screen.findByText("auto")
      expect(pill.className).not.toMatch(/destructive/)
    })

    it("says the stored mode is ignored rather than hiding it", async () => {
      vi.mocked(fetchAutonomy).mockResolvedValue({
        "trigger-mode": "auto",
        "autonomous-capable": false,
      })
      renderGovernor()
      expect(await screen.findByText(/nothing acts on it/)).toBeTruthy()
    })

    it("cannot be armed, and does not invite the click", async () => {
      vi.mocked(fetchAutonomy).mockResolvedValue({
        "trigger-mode": "manual",
        "autonomous-capable": false,
      })
      renderGovernor()
      const arm = await screen.findByRole("button", { name: /Switch to auto/ })
      expect(arm.hasAttribute("disabled")).toBe(true)
      expect(screen.getByText(/Requires an autonomous auth profile/)).toBeTruthy()

      fireEvent.click(arm)
      expect(saveTriggerMode).not.toHaveBeenCalled()
    })
  })

  describe("the maturity rung", () => {
    it("names the rung and points at the tolerances that widen it", async () => {
      // Rung 3 has no switch — it is tolerance width in the /config section above.
      // The panel points rather than restating a value it does not own.
      vi.mocked(fetchAutonomy).mockResolvedValue({
        "trigger-mode": "auto",
        "autonomous-capable": true,
      })
      renderGovernor()
      expect(await screen.findByText(/Rung 2 of 3/)).toBeTruthy()
      expect(screen.getByText(/Tolerances section above/)).toBeTruthy()
    })

    it("claims no rung in manual", async () => {
      vi.mocked(fetchAutonomy).mockResolvedValue({
        "trigger-mode": "manual",
        "autonomous-capable": true,
      })
      renderGovernor()
      await screen.findByText("manual")
      expect(screen.queryByText(/Rung 2 of 3/)).toBeNull()
    })

    it("an unknown capability earns no new claim in either direction", async () => {
      // A backend deployed before the field existed. Absent is UNKNOWN, never "not
      // capable" — reporting a capable stack as incapable is a confident wrong answer.
      vi.mocked(fetchAutonomy).mockResolvedValue({ "trigger-mode": "auto" })
      renderGovernor()
      expect(await screen.findByText(/acts on new cases unattended/)).toBeTruthy()
      expect(screen.queryByText(/Unattended triggering is not deployed/)).toBeNull()
      expect(screen.queryByRole("button", { name: /Switch to manual/ })).toBeTruthy()
    })
  })

  it("surfaces a refused flip", async () => {
    vi.mocked(saveTriggerMode).mockRejectedValue(new Error("Invalid mode"))
    renderGovernor()
    fireEvent.click(await screen.findByRole("button", { name: /Switch to auto/ }))
    fireEvent.change(screen.getByLabelText(/Type/), { target: { value: "AUTO" } })
    const buttons = screen.getAllByRole("button", { name: /Switch to auto/ })
    fireEvent.click(buttons[buttons.length - 1])

    // Silence after a failed flip would leave the operator believing the mode changed.
    expect(await screen.findByText("Invalid mode")).toBeTruthy()
  })
})
