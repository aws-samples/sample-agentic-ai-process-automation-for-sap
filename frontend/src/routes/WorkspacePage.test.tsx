// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen, cleanup, act, fireEvent, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter, Route, Routes } from "react-router"
import { CaseStatus, Domain } from "@/types/cases"
import type { WorkItem } from "@/types/cases"
import { fetchCases, fetchCase, enqueueCases } from "@/services/casesService"
import { invokeInteractiveRun } from "@/services/agentRuntimeService"
import type { AguiEvent } from "@/lib/aguiReducer"
import { getAgentActivity, setAgentActivity } from "@/lib/agentActivity"
import { clearTranscript } from "@/lib/transcript"
import { AGENT_PULSE_KEY } from "@/components/AgentHeartbeat"

/**
 * Processing a case from the workspace, and what the rail is told while it streams.
 *
 * The stream lives in the shell's `useAgentChat`, not in the page, so these mount the
 * real layout route: the run is started by a click in the workspace and rendered by the
 * docked assistant, which is the seam that would break if either end changed alone.
 *
 * `agentActivity` is module state published from inside the stream loop and reset by
 * one wrapper's `finally`. Every publish and reset path was previously verified only by
 * reading the code — which is how a caller that never reset the heartbeat shipped and
 * had to be caught in review. These pin the reset on each terminal branch, and the
 * enqueue notification that a background run depends on.
 */

vi.mock("@/services/casesService", () => ({
  fetchCases: vi.fn(async () => []),
  fetchCase: vi.fn(async () => null),
  enqueueCases: vi.fn(async () => undefined),
}))
vi.mock("@/services/agentRuntimeService", async () => {
  // The real error class is part of the contract under test: Workspace branches on
  // `instanceof`, so a plain stub would silently take the wrong branch.
  const actual = await vi.importActual<typeof import("@/services/agentRuntimeService")>(
    "@/services/agentRuntimeService"
  )
  return {
    ...actual,
    invokeInteractiveRun: vi.fn(),
    stopInteractiveSession: vi.fn(async () => undefined),
  }
})
vi.mock("@/hooks/useFreshToken", () => ({
  useFreshToken: () => async () => ({ idToken: "id", accessToken: "access" }),
}))
vi.mock("react-oidc-context", () => ({ useAuth: () => ({ isAuthenticated: true }) }))
vi.mock("@/hooks/useDemoEnabled", () => ({
  useDemoFeatures: () => ({ ticketing: false, testData: false }),
}))
// The rail runs its own polling query and is covered by its own test.
vi.mock("@/components/SideRail", () => ({ SideRail: () => <div>rail-stub</div> }))
// Allotment measures the DOM; jsdom reports zero and it renders nothing.
vi.mock("allotment", () => ({
  Allotment: Object.assign(({ children }: { children: React.ReactNode }) => <div>{children}</div>, {
    Pane: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  }),
}))

import WorkspacePage from "@/routes/WorkspacePage"
import { AppShell } from "@/routes/AppShell"

function makeCase(caseId: string, status = CaseStatus.Detected): WorkItem {
  const [document_number, item_id] = caseId.split("-")
  return {
    case_id: caseId,
    document_number,
    item_id,
    domain: Domain.FinanceAp,
    process_type: "price_variance",
    status,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
  }
}

const CASE_A = "5100001976-2026"
const CASE_B = "5100001977-2026"

/**
 * Mount the workspace under the real shell. The shell owns the conversation, so a
 * bare `<WorkspacePage />` has no assistant to hand its runs to.
 */
function renderWorkspace() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const invalidate = vi.spyOn(client, "invalidateQueries")
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<WorkspacePage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
  return { ...view, client, invalidate }
}

/** Wait for the config fetch and first case query to settle, so buttons are live. */
async function settle() {
  await act(async () => {
    await Promise.resolve()
  })
}

beforeEach(() => {
  localStorage.clear()
  setAgentActivity({ kind: "idle" })
  // Both are module stores that outlive unmount, so a leftover transcript would seed
  // the next test's assistant with the previous test's turn.
  clearTranscript()
  // jsdom implements no layout, so this is absent rather than a no-op; the assistant
  // scrolls to the newest message on every append.
  Element.prototype.scrollIntoView = vi.fn()
  vi.mocked(fetchCases)
    .mockReset()
    .mockResolvedValue([makeCase(CASE_A), makeCase(CASE_B)])
  vi.mocked(fetchCase).mockReset().mockResolvedValue(makeCase(CASE_A))
  vi.mocked(enqueueCases).mockReset().mockResolvedValue(undefined)
  vi.mocked(invokeInteractiveRun).mockReset()
  // The page gates every run on this: an unconfigured runtime returns early and no
  // stream, no publish and no reset would happen at all.
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({ agentRuntimeArn: "arn:aws:test" })))
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

/**
 * Select case rows, then click Process. Rows carry no test id and render the case by its
 * canonical id, which the handover renders too — so the row is the match that sits inside
 * the list's clickable div.
 */
async function processCase(ids: string[]) {
  for (const id of ids) {
    const labels = await screen.findAllByText(id)
    const row = labels.map(l => l.closest("div.cursor-pointer")).find(Boolean)
    const checkbox = row?.querySelector('input[type="checkbox"]') as HTMLInputElement | null
    if (!checkbox) throw new Error(`no checkbox for ${id}`)
    fireEvent.click(checkbox)
  }
  const button = await screen.findByRole("button", { name: /Process/ })
  await act(async () => {
    fireEvent.click(button)
  })
}

describe("WorkspacePage heartbeat publishing", () => {
  it("resets the heartbeat when a run completes normally", async () => {
    vi.mocked(invokeInteractiveRun).mockImplementation(async (_req, _token, onEvent) => {
      onEvent({ type: "TOOL_CALL_START", toolCallId: "t1", toolCallName: "odata_read" })
      // The rail must be able to see the run while it is in flight, not only after.
      expect(getAgentActivity()).toEqual({ kind: "tool", name: "odata_read" })
      return { terminalEvent: "RUN_FINISHED" as const }
    })

    renderWorkspace()
    await settle()
    await processCase([CASE_A])

    await waitFor(() => expect(getAgentActivity()).toEqual({ kind: "idle" }))
    expect(vi.mocked(invokeInteractiveRun)).toHaveBeenCalled()
  })

  it("resets the heartbeat when the run cannot be started", async () => {
    const { AgentRuntimeStartError } = await vi.importActual<
      typeof import("@/services/agentRuntimeService")
    >("@/services/agentRuntimeService")
    vi.mocked(invokeInteractiveRun).mockImplementation(async (_req, _token, onEvent) => {
      onEvent({ type: "TEXT_MESSAGE_CONTENT", delta: "thinking" })
      throw new AgentRuntimeStartError("runtime refused")
    })

    renderWorkspace()
    await settle()
    await processCase([CASE_A])

    // The failure branch appends its own notice, which re-renders the turn and
    // republishes activity — the reset has to outlive that.
    await waitFor(() => expect(getAgentActivity()).toEqual({ kind: "idle" }))
    expect(await screen.findByText(/could not be started/)).toBeInTheDocument()
  })

  it("resets the heartbeat when the stream throws mid-run", async () => {
    vi.mocked(invokeInteractiveRun).mockImplementation(async (_req, _token, onEvent) => {
      onEvent({ type: "TOOL_CALL_START", toolCallId: "t1", toolCallName: "odata_update" })
      throw new Error("socket closed")
    })

    renderWorkspace()
    await settle()
    await processCase([CASE_A])

    await waitFor(() => expect(getAgentActivity()).toEqual({ kind: "idle" }))
  })

  it("clears the heartbeat on unmount so an interrupted run cannot strand it", async () => {
    let release: (() => void) | undefined
    vi.mocked(invokeInteractiveRun).mockImplementation(async (_req, _token, onEvent) => {
      onEvent({ type: "TOOL_CALL_START", toolCallId: "t1", toolCallName: "odata_read" })
      await new Promise<void>(resolve => {
        release = resolve
      })
      return { terminalEvent: "RUN_FINISHED" as const }
    })

    const { unmount } = renderWorkspace()
    await settle()
    await processCase([CASE_A])
    expect(getAgentActivity()).toEqual({ kind: "tool", name: "odata_read" })

    unmount()
    expect(getAgentActivity()).toEqual({ kind: "idle" })
    release?.()
  })

  it("resets after Stop, which republishes activity on its way out", async () => {
    // Stop takes an early-return branch that settles the projection and appends
    // "⏹ Stopped.". Settling marks the in-flight tool incomplete, so the notice's
    // re-render publishes `reasoning` — still a live state. Anything that reset the
    // rail before that point would leave it claiming work on a stopped run.
    // The stream parks on a gate the test releases, rather than clicking Stop from
    // inside the mock: a nested act() corrupts React's act queue for the whole file and
    // every later test in it stops rendering.
    let release: (() => void) | undefined
    let sawAborted: boolean | undefined
    vi.mocked(invokeInteractiveRun).mockImplementation(async (_req, _token, onEvent, signal) => {
      onEvent({ type: "TOOL_CALL_START", toolCallId: "t1", toolCallName: "odata_read" })
      await new Promise<void>(resolve => {
        release = resolve
      })
      sawAborted = signal?.aborted
      return { terminalEvent: "RUN_FINISHED" as const }
    })

    renderWorkspace()
    await settle()
    await processCase([CASE_A])
    expect(getAgentActivity()).toEqual({ kind: "tool", name: "odata_read" })

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Stop/i }))
    })
    release?.()

    expect(await screen.findByText(/Stopped\./)).toBeInTheDocument()
    // The stop has to reach the run itself, not only the button's own state.
    expect(sawAborted).toBe(true)
    await waitFor(() => expect(getAgentActivity()).toEqual({ kind: "idle" }))
  })
})

describe("WorkspacePage streams into the docked assistant", () => {
  it("keeps the streamed turn when the case's own record arrives mid-run", async () => {
    // Processing focuses the case in the same click, so its record — and the traces
    // written before this turn — land while the stream is live. Replaying them over a
    // running turn empties the transcript the operator is watching.
    let release: (() => void) | undefined
    vi.mocked(invokeInteractiveRun).mockImplementation(async (_req, _token, onEvent) => {
      onEvent({ type: "TEXT_MESSAGE_CONTENT", delta: "checking the invoice" })
      await new Promise<void>(resolve => {
        release = resolve
      })
      return { terminalEvent: "RUN_FINISHED" as const }
    })

    renderWorkspace()
    await settle()
    await processCase([CASE_A])

    expect(await screen.findByText(/checking the invoice/)).toBeInTheDocument()
    await act(async () => {
      release?.()
    })
    expect(screen.getByText(/checking the invoice/)).toBeInTheDocument()
  })
})

describe("WorkspacePage background enqueue", () => {
  it("tells the rail about the enqueue instead of leaving it on its own interval", async () => {
    const { invalidate } = renderWorkspace()
    await settle()
    await processCase([CASE_A, CASE_B])

    await waitFor(() => expect(vi.mocked(enqueueCases)).toHaveBeenCalled())
    expect(invalidate).toHaveBeenCalledWith({ queryKey: AGENT_PULSE_KEY })
    // Multi-select enqueues rather than streaming: no interactive run is started, so
    // the rail's poll is the only thing that can report this work.
    expect(vi.mocked(invokeInteractiveRun)).not.toHaveBeenCalled()
  })

  it("does not claim the rail is tracking work when the enqueue failed", async () => {
    vi.mocked(enqueueCases).mockRejectedValue(new Error("queue unavailable"))

    const { invalidate } = renderWorkspace()
    await settle()
    await processCase([CASE_A, CASE_B])

    await waitFor(() => expect(screen.getByText(/queue unavailable/)).toBeInTheDocument())
    expect(invalidate).not.toHaveBeenCalledWith({ queryKey: AGENT_PULSE_KEY })
  })
})

describe("WorkspacePage shift handover", () => {
  /** In-window and awaiting, so it lands in a handover group rather than only the list. */
  function waitingCase(caseId: string): WorkItem {
    return {
      ...makeCase(caseId, CaseStatus.AwaitingHumanInput),
      updated_at: new Date().toISOString(),
    }
  }

  it("fills the second pane when no case is focused", async () => {
    vi.mocked(fetchCases).mockResolvedValue([waitingCase(CASE_A)])

    renderWorkspace()
    await settle()

    // The pane used to collapse to zero width here; the handover is what it holds now.
    expect(await screen.findByText(/waiting on someone/)).toBeInTheDocument()
    // Ticketing is off in this suite, so the digest must say where the grouping came from
    // rather than presenting a process type as a person.
    expect(screen.getByText("Waiting — price_variance")).toBeInTheDocument()
    expect(screen.getByText(/ticketing is disabled/)).toBeInTheDocument()
  })

  it("focuses the case a handover row names, and yields the pane to the detail", async () => {
    vi.mocked(fetchCases).mockResolvedValue([waitingCase(CASE_A)])

    renderWorkspace()
    await settle()

    // Both surfaces render the canonical id now, so the handover row is addressed by its
    // role: the list renders the same string in a div.
    await act(async () => {
      fireEvent.click(await screen.findByRole("button", { name: new RegExp(CASE_A) }))
    })

    await waitFor(() => expect(vi.mocked(fetchCase)).toHaveBeenCalledWith(CASE_A, "id"))
    expect(screen.queryByText(/waiting on someone/)).not.toBeInTheDocument()
  })
})

describe("WorkspacePage case row", () => {
  it("qualifies a non-USD amount with its currency", async () => {
    // A `$` on a EUR invoice is a wrong number, not an unlabelled one — and the row is
    // the surface an operator scans before opening anything. `HandoverPanel` and
    // `PeriodBriefing` already pin this same call; the row was the one that did not.
    vi.mocked(fetchCases).mockResolvedValue([{ ...makeCase(CASE_A), amount: 200, currency: "EUR" }])

    renderWorkspace()
    await settle()

    expect(await screen.findByText("200.00 EUR")).toBeInTheDocument()
  })
})

describe("WorkspacePage domain scope", () => {
  it("renders no domain control when only one domain is deployed", async () => {
    // `AP` is the only domain's short label — with one domain it must appear nowhere,
    // neither as the strip nor as a row pill. A second domain flips this, which is the
    // intended signal rather than a surprise.
    renderWorkspace()
    await settle()

    expect(screen.queryByText("AP")).toBeNull()
  })
})

describe("WorkspacePage tool naming", () => {
  it("publishes the tool's own name with the Gateway prefix stripped", async () => {
    const seen: string[] = []
    vi.mocked(invokeInteractiveRun).mockImplementation(async (_req, _token, onEvent) => {
      onEvent({
        type: "TOOL_CALL_START",
        toolCallId: "t1",
        toolCallName: "sapTarget___odata_read",
      } as AguiEvent)
      const activity = getAgentActivity()
      if (activity.kind === "tool") seen.push(activity.name)
      return { terminalEvent: "RUN_FINISHED" as const }
    })

    renderWorkspace()
    await settle()
    await processCase([CASE_A])

    // An operator reads this label; the Gateway's target prefix is plumbing.
    expect(seen).toEqual(["odata_read"])
  })
})
