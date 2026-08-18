// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen, cleanup, act } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import {
  AGENT_PULSE_KEY,
  AgentHeartbeat,
  msSinceEnqueue,
  notifyWorkEnqueued,
  pollIntervalMs,
} from "@/components/AgentHeartbeat"
import { setAgentActivity } from "@/lib/agentActivity"
import { CaseStatus, Domain } from "@/types/cases"
import type { WorkItem } from "@/types/cases"
import { fetchCases } from "@/services/casesService"

vi.mock("@/services/casesService", () => ({ fetchCases: vi.fn(async () => []) }))
vi.mock("@/hooks/useFreshToken", () => ({
  useFreshToken: () => async () => ({ idToken: "id", accessToken: "access" }),
}))
vi.mock("react-oidc-context", () => ({ useAuth: () => ({ isAuthenticated: true }) }))

function makeCase(status: CaseStatus): WorkItem {
  return {
    case_id: `5100001976-${status}`,
    document_number: "5100001976",
    item_id: "1",
    domain: Domain.FinanceAp,
    process_type: "price_variance",
    status,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
  }
}

function renderHeartbeat() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <AgentHeartbeat />
    </QueryClientProvider>
  )
}

beforeEach(() => {
  setAgentActivity({ kind: "idle" })
  vi.mocked(fetchCases).mockReset()
  vi.mocked(fetchCases).mockResolvedValue([])
})
afterEach(cleanup)

describe("AgentHeartbeat", () => {
  it("reads idle when nothing is running and nothing is waiting", async () => {
    renderHeartbeat()
    expect(await screen.findByText("Idle")).toBeInTheDocument()
  })

  it("announces the label and not the icon", async () => {
    renderHeartbeat()
    const label = await screen.findByText("Idle")
    const region = screen.getByRole("status")
    // role="status" is already an implicit aria-live="polite" region. The label is
    // the only thing inside it that is not aria-hidden, so the label is what a
    // screen reader announces on a state change.
    expect(region).toContainElement(label)
    expect(region.querySelector("[aria-hidden='true']")).toBeInTheDocument()
    expect(screen.getByText("Idle")).not.toHaveAttribute("aria-hidden")
  })

  it("distinguishes the states by shape, not only by colour", async () => {
    // The label is sr-only, so until the operator hovers for the tooltip the icon is
    // all they have. blocked, needs-you and unknown are red, orange, orange — the protan/deutan
    // confusion set — so hue alone cannot tell them apart. Every pair is compared,
    // not just one: a collision between any two is the same defect.
    //
    // The svg's own geometry, not its class: the class also carries the tone colour,
    // so two identical shapes in different tones would compare unequal and the
    // assertion would pass without testing anything.
    //
    // The two live states share the spinner deliberately and are both violet, so they
    // are outside this set.
    const states: Array<[string, WorkItem[] | null]> = [
      ["Status unknown", null],
      ["Working · 1 case", [makeCase(CaseStatus.Processing)]],
      ["Blocked · 1", [makeCase(CaseStatus.ManualReviewRequired)]],
      ["Needs you · 1", [makeCase(CaseStatus.AwaitingHumanInput)]],
      ["Idle", []],
    ]

    const shapes = new Map<string, string>()
    for (const [label, cases] of states) {
      if (cases === null) {
        vi.mocked(fetchCases).mockReturnValue(new Promise(() => {}))
      } else {
        vi.mocked(fetchCases).mockResolvedValue(cases)
      }
      renderHeartbeat()
      await screen.findByText(label)
      shapes.set(label, screen.getByRole("status").querySelector("svg")?.innerHTML ?? "")
      cleanup()
    }

    expect(new Set(shapes.values()).size).toBe(states.length)
  })

  it("names the tool in flight rather than claiming SAP work", async () => {
    // Most gateway tools never touch SAP. update_case_state writes a DynamoDB row.
    renderHeartbeat()
    await screen.findByText("Idle")
    act(() => setAgentActivity({ kind: "tool", name: "update_case_state" }))
    expect(screen.getByText("Calling update_case_state")).toBeInTheDocument()
    expect(screen.queryByText(/Calling SAP/)).not.toBeInTheDocument()
  })

  it("reports reasoning while the model is thinking", async () => {
    renderHeartbeat()
    await screen.findByText("Idle")
    act(() => setAgentActivity({ kind: "reasoning" }))
    expect(screen.getByText("Reasoning")).toBeInTheDocument()
  })

  it("reports a background run from a case in processing", async () => {
    vi.mocked(fetchCases).mockResolvedValue([makeCase(CaseStatus.Processing)])
    renderHeartbeat()
    expect(await screen.findByText("Working · 1 case")).toBeInTheDocument()
  })

  it("reports blocked cases when nothing is running", async () => {
    vi.mocked(fetchCases).mockResolvedValue([makeCase(CaseStatus.ManualReviewRequired)])
    renderHeartbeat()
    expect(await screen.findByText("Blocked · 1")).toBeInTheDocument()
  })

  it("reports cases waiting on a human", async () => {
    vi.mocked(fetchCases).mockResolvedValue([makeCase(CaseStatus.AwaitingHumanInput)])
    renderHeartbeat()
    expect(await screen.findByText("Needs you · 1")).toBeInTheDocument()
  })

  it("prefers a live run over a standing blocked count", async () => {
    vi.mocked(fetchCases).mockResolvedValue([makeCase(CaseStatus.ManualReviewRequired)])
    renderHeartbeat()
    await screen.findByText("Blocked · 1")
    act(() => setAgentActivity({ kind: "tool", name: "odata_read" }))
    expect(screen.getByText("Calling odata_read")).toBeInTheDocument()
  })

  it("keeps the state in the live region, not only in the tooltip", async () => {
    // A live region announces on content change, not on an aria-label change, and the
    // tooltip is aria-hidden. Dropping the sr-only label would make every state change
    // silent to a screen reader, and leave dot hue as the only signal to a colour-blind
    // operator who has not hovered.
    renderHeartbeat()
    const region = await screen.findByRole("status")
    expect(region).toContainElement(await screen.findByText("Idle"))
    expect(screen.getByText("Idle")).toHaveClass("sr-only")
  })

  it("says the status is unknown rather than claiming idle when the poll fails", async () => {
    vi.mocked(fetchCases).mockRejectedValue(new Error("500"))
    renderHeartbeat()
    expect(await screen.findByText("Status unknown")).toBeInTheDocument()
    expect(screen.queryByText("Idle")).not.toBeInTheDocument()
  })

  it("does not claim idle before the first poll has settled", async () => {
    // The gap this closes: in production `retry` is 3 with backoff, so a query that
    // will end in an error spends seconds pending first. Reporting idle there asserts
    // "nothing needs you" on no evidence at all.
    vi.mocked(fetchCases).mockReturnValue(new Promise(() => {}))
    renderHeartbeat()
    expect(await screen.findByText("Status unknown")).toBeInTheDocument()
    expect(screen.queryByText("Idle")).not.toBeInTheDocument()
  })

  it("polls faster while a background run is in flight than while quiet", async () => {
    vi.mocked(fetchCases).mockResolvedValue([makeCase(CaseStatus.Processing)])
    // Installed before render: react-query schedules the interval when the first fetch
    // settles, so a later swap would leave that timer on the real clock.
    vi.useFakeTimers()
    try {
      renderHeartbeat()
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0)
      })
      const afterFirst = vi.mocked(fetchCases).mock.calls.length
      expect(afterFirst).toBe(1)

      // POLL_ACTIVE_MS is 5s and POLL_QUIET_MS is 30s, so a 6s advance refetches only
      // under the active interval.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(6_000)
      })
      expect(vi.mocked(fetchCases).mock.calls.length).toBeGreaterThan(afterFirst)
    } finally {
      vi.useRealTimers()
    }
  })
})

/**
 * An enqueue is the one state change the rail cannot observe: `agent_invoker` stamps
 * `processing` only when it dequeues, so the poll that follows an enqueue still reads
 * `pending` and the status-driven interval alone would drop straight back to quiet.
 */
describe("pollIntervalMs", () => {
  it("stays fast inside the window after an enqueue, before any case is processing", () => {
    expect(pollIntervalMs([makeCase(CaseStatus.Detected)], 1_000)).toBe(5_000)
  })

  it("returns to quiet once the window closes and nothing is processing", () => {
    expect(pollIntervalMs([makeCase(CaseStatus.Detected)], 25_000)).toBe(30_000)
  })

  it("stays fast past the window while a case is still processing", () => {
    expect(pollIntervalMs([makeCase(CaseStatus.Processing)], 25_000)).toBe(5_000)
  })

  it("treats an unsettled query as quiet outside the window", () => {
    expect(pollIntervalMs(undefined, 25_000)).toBe(30_000)
  })
})

describe("notifyWorkEnqueued", () => {
  it("invalidates the pulse key so the rail refetches instead of waiting", () => {
    const client = new QueryClient()
    const invalidate = vi.spyOn(client, "invalidateQueries")
    notifyWorkEnqueued(client)
    expect(invalidate).toHaveBeenCalledWith({ queryKey: AGENT_PULSE_KEY })
  })

  it("opens the fast-poll window, which is closed until it is called", () => {
    const client = new QueryClient()
    vi.spyOn(client, "invalidateQueries").mockResolvedValue(undefined)
    const pending = [makeCase(CaseStatus.Detected)]

    // The marker is module state, so this drives it to a known-closed point of its own
    // rather than assuming one — another test in this file opens the window on the real
    // clock. It also ends stale, leaving the window closed for whatever runs next.
    vi.useFakeTimers()
    try {
      vi.setSystemTime(new Date("2020-01-01T00:00:00Z"))
      notifyWorkEnqueued(client)
      vi.setSystemTime(new Date("2020-01-01T00:00:25Z"))

      // Read through the same accessor the query uses, so this fails if the call stops
      // moving the marker. The case statuses are identical across all three reads.
      expect(pollIntervalMs(pending, msSinceEnqueue())).toBe(30_000)
      notifyWorkEnqueued(client)
      expect(pollIntervalMs(pending, msSinceEnqueue())).toBe(5_000)

      vi.setSystemTime(new Date("2020-01-01T00:00:50Z"))
      expect(pollIntervalMs(pending, msSinceEnqueue())).toBe(30_000)
    } finally {
      vi.useRealTimers()
    }
  })
})
