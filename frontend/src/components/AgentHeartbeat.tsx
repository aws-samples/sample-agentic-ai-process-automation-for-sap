// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useQuery, type QueryClient } from "@tanstack/react-query"
import { useAuth } from "react-oidc-context"
import {
  Activity,
  Circle,
  CircleAlert,
  Hand,
  HelpCircle,
  Loader2,
  type LucideIcon,
} from "lucide-react"
import { CaseStatus } from "@/types/cases"
import type { WorkItem } from "@/types/cases"
import { fetchCases } from "@/services/casesService"
import { useFreshToken } from "@/hooks/useFreshToken"
import { useAgentActivity, type AgentActivity } from "@/lib/agentActivity"
import { TONE_TEXT, type StatusTone } from "@/lib/statusTone"
import { itemClass, RailTooltip } from "@/components/SideRail"
import { cn, ICON_CHROME } from "@/lib/utils"

/**
 * One persistent statement of what the agent is doing, legible from any route.
 *
 * Six states, in precedence order: a live interactive run, an unknown case status, a
 * live background run, cases blocked, cases waiting on a human, idle. A live run wins
 * over a standing count because "it is working right now" is the thing a standing
 * count cannot say.
 *
 * Colour: agent activity uses the reserved `--agent` violet, the hue that means
 * "the agent is working". Everything else is a state and takes its colour from the
 * tone vocabulary. Neither is decided here.
 */

// While work is in flight, the view is stale in seconds rather than minutes.
const POLL_ACTIVE_MS = 5_000
const POLL_QUIET_MS = 30_000

/**
 * Query key for the rail's case counts. Exported so the page that enqueues work can
 * invalidate it: an enqueue changes what the rail should say, and nothing else tells it.
 */
export const AGENT_PULSE_KEY = ["agent-pulse"] as const

/**
 * How long after an enqueue the rail stays on the fast poll.
 *
 * An invalidation alone does not close the gap. `agent_invoker` stamps `processing`
 * only when it picks the SQS message up, so the refetch that follows an enqueue
 * usually still reads `pending`, no case is `processing`, and the interval recomputes
 * straight back to quiet — leaving the operator on a 30 s wait for the state they
 * just caused. This window keeps the fast poll running until the queue is picked up.
 */
const HANDOFF_WINDOW_MS = 20_000

type Pulse = {
  label: string
  detail: string
  /** Live agent work, so violet rather than a tone. */
  live: boolean
  /** The interactive run this operator started, which is the only state that spins. */
  interactive: boolean
  tone: StatusTone
  /**
   * Collapsed, the label is `sr-only`, so a dot would leave hue as the only signal a
   * sighted operator gets — and blocked/needs-you/unknown are red, orange, orange.
   * Each state therefore carries a distinct shape too.
   */
  icon: LucideIcon
}

/**
 * When work was last handed to the queue from this tab. `-Infinity` rather than 0 so
 * the elapsed time is never inside the window before an enqueue has happened.
 */
let enqueuedAt = -Infinity

/**
 * Tell the rail that work was just queued. The caller owns the enqueue; the rail owns
 * what it says about it, and without this it says nothing until its next quiet poll.
 */
export function notifyWorkEnqueued(queryClient: QueryClient): void {
  enqueuedAt = Date.now()
  void queryClient.invalidateQueries({ queryKey: AGENT_PULSE_KEY })
}

/** Elapsed time since the last local enqueue; `Infinity` if there has not been one. */
export function msSinceEnqueue(): number {
  return Date.now() - enqueuedAt
}

/**
 * Fast while anything is running, and through the window after a local enqueue.
 * Split out from the query so the two reasons to poll fast are testable without
 * driving timers through a mounted component.
 */
export function pollIntervalMs(cases: WorkItem[] | undefined, sinceEnqueueMs: number): number {
  if (sinceEnqueueMs < HANDOFF_WINDOW_MS) return POLL_ACTIVE_MS
  return cases?.some(c => c.status === CaseStatus.Processing) ? POLL_ACTIVE_MS : POLL_QUIET_MS
}

/**
 * `unknown` is a state, not the absence of one: until the first poll settles there is
 * no basis for claiming idle, and after a failure there is no basis for the counts.
 */
function pulseFrom(activity: AgentActivity, cases: WorkItem[], known: boolean): Pulse {
  if (activity.kind === "tool") {
    return {
      // The tool's own name rather than a guess at what it talks to: most of these
      // tools never touch SAP, and claiming a SAP write that isn't happening is the
      // one lie this console cannot afford.
      label: `Calling ${activity.name}`,
      detail: `Running ${activity.name} right now`,
      live: true,
      interactive: true,
      tone: "progress",
      icon: Loader2,
    }
  }
  if (activity.kind === "reasoning") {
    return {
      label: "Reasoning",
      detail: "Working through the current request",
      live: true,
      interactive: true,
      tone: "progress",
      icon: Loader2,
    }
  }

  // Only after the live states: an unsettled or failed poll says nothing about the run
  // in front of this operator, but it does mean the counts below are not yet knowable.
  if (!known) {
    return {
      label: "Status unknown",
      // True whether the first poll is still in flight or the last one failed: the
      // interval retries either way, so this state is always "still waiting".
      detail: "Waiting on case status — the counts below are unavailable",
      live: false,
      interactive: false,
      tone: "attention",
      icon: HelpCircle,
    }
  }

  const processing = cases.filter(c => c.status === CaseStatus.Processing).length
  if (processing > 0) {
    return {
      label: `Working · ${processing} case${processing === 1 ? "" : "s"}`,
      detail: "Background runs in flight",
      live: true,
      interactive: false,
      tone: "progress",
      // Not the spinner: a background run outlives the operator's attention, and an
      // indefinite spin in the rail for something they did not start is noise.
      icon: Activity,
    }
  }

  const blocked = cases.filter(c => c.status === CaseStatus.ManualReviewRequired).length
  if (blocked > 0) {
    return {
      label: `Blocked · ${blocked}`,
      detail: "Cases the agent could not clear",
      live: false,
      interactive: false,
      tone: "danger",
      icon: CircleAlert,
    }
  }

  const waiting = cases.filter(c => c.status === CaseStatus.AwaitingHumanInput).length
  if (waiting > 0) {
    return {
      label: `Needs you · ${waiting}`,
      detail: "Cases awaiting a human decision",
      live: false,
      interactive: false,
      tone: "attention",
      icon: Hand,
    }
  }

  return {
    label: "Idle",
    detail: "Nothing in flight",
    live: false,
    interactive: false,
    tone: "neutral",
    icon: Circle,
  }
}

export function AgentHeartbeat() {
  const auth = useAuth()
  const getFreshTokens = useFreshToken()
  const activity = useAgentActivity()

  // ponytail: its own query, not Workspace's — the counts have to be over every case,
  // and Workspace's list is filtered to whatever the operator is looking at. The
  // ceiling: an unfiltered GET /cases is a full table scan returning every case's whole
  // item, agent_traces included, to compute three counts. Three status-filtered queries
  // would hit the index instead — do that when the table is big enough to feel it.
  const pulseQuery = useQuery({
    queryKey: AGENT_PULSE_KEY,
    queryFn: async () => {
      const { idToken } = await getFreshTokens()
      if (!idToken) throw new Error("Not authenticated")
      return fetchCases({}, idToken)
    },
    enabled: auth.isAuthenticated,
    refetchInterval: query => pollIntervalMs(query.state.data, msSinceEnqueue()),
  })

  // A query that has never settled knows nothing, and one that failed knows nothing
  // current. Neither is grounds for reporting idle.
  const known = pulseQuery.isSuccess
  const pulse = pulseFrom(activity, pulseQuery.data ?? [], known)
  const Icon = pulse.icon

  return (
    <div
      role="status"
      // A static name: the state itself lives in the content, which is what a live
      // region announces. A name that restated it would announce twice.
      aria-label="Agent status"
      title={pulse.detail}
      // Shares itemClass() with the nav rows: the heartbeat sits on the same optical
      // axis as every route below it rather than being a fourth band height with its
      // own rule. The rail header's border is the single divider above the nav now.
      // flex-none because the nav <ul> below is flex-1 with a 0% basis and so cannot
      // shrink — this row would be the only compressible child at short heights.
      className={cn(itemClass(), "flex-none")}
    >
      <Icon
        size={ICON_CHROME}
        aria-hidden="true"
        className={cn(
          "flex-none",
          pulse.live ? "text-agent" : TONE_TEXT[pulse.tone],
          pulse.interactive && "motion-safe:animate-spin"
        )}
      />
      {/* sr-only rather than dropped: a live region announces on content change, not on
          an aria-label change, so removing it would make every state change silent. The
          tooltip beside it is aria-hidden and carries the same text for sighted users.
          No aria-live here either: role="status" above is already a polite region, and
          nesting one inside another double-announces. */}
      <span className="sr-only">{pulse.label}</span>
      <RailTooltip label={`${pulse.label} — ${pulse.detail}`} />
    </div>
  )
}
