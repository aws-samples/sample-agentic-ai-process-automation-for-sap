// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useRef, useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useOutletContext, useSearchParams } from "react-router"
import { useAuth } from "react-oidc-context"
import { useFreshToken } from "@/hooks/useFreshToken"
import {
  AgentRuntimeStartError,
  invokeInteractiveRun,
  stopInteractiveSession,
} from "@/services/agentRuntimeService"
import {
  reduceAguiEvent,
  settleAguiProjection,
  spliceTurnIntoHistory,
  type AguiEvent,
  type AguiProjection,
} from "@/lib/aguiReducer"
import { buildPromptWithHistory } from "@/lib/buildPromptWithHistory"
import { tracesToMessages } from "@/lib/tracesToMessages"
import { deriveActivity, setAgentActivity } from "@/lib/agentActivity"
import { clearTranscript, getTranscript, setTranscript } from "@/lib/transcript"
import { parseAuthRequired } from "@/components/chat/ToolCallDisplay"
import { fetchCase } from "@/services/casesService"
import { submitFeedback } from "@/services/feedbackService"
import { formatAmount } from "@/lib/domainFields"
import { formatCaseId, isCaseId, toRuntimeSessionId, tryNormalizeCaseId } from "@/lib/caseKey"
import type { Message } from "@/components/chat/types"
import type { WorkItem } from "@/types/cases"

/**
 * The interactive agent conversation, owned once by the layout route.
 *
 * It lives above the router's outlet rather than inside a page because the assistant
 * is ambient: the same run has to survive a move from the workspace to analytics, and
 * a page that owned it would tear the stream down on navigation.
 *
 * There is no context provider. The layout route already has one channel to its
 * children — `<Outlet context>` — so `useAssistant()` below reads it from there.
 *
 * The transcript is deliberately *not* part of that channel. State on a layout route
 * re-renders the outlet context, so holding messages here would re-render the routed
 * page and its case list on every streamed token. It lives in `lib/transcript`
 * instead, which the assistant subscribes to directly.
 */

/**
 * The case the assistant is talking about, taken from the URL on whatever route is
 * mounted: `?case=` in the workspace, `?case_id=` on the tickets dashboard.
 *
 * Reading the URL rather than accepting a prop is what makes the panel ambient. Every
 * route that has a case already puts it in the address bar — so the assistant knows
 * which case without the page telling it, and a shared link carries the context too.
 */
function useCaseInContext(): string | null {
  const [params] = useSearchParams()
  return tryNormalizeCaseId(params.get("case") ?? params.get("case_id"))
}

export interface AgentChat {
  /** The case in context, or null on a route that is not looking at one. */
  caseId: string | null
  input: string
  setInput: (value: string) => void
  isLoading: boolean
  error: string | null
  setError: (value: string | null) => void
  /** AgentCore Memory session — the case's own when there is one. */
  sessionId: string
  /** False until the runtime ARN is confirmed; every run is gated on it. */
  ready: boolean
  /** How many cases a route has put in context beyond the focused one. */
  contextCaseCount: number
  setContextCases: (items: WorkItem[]) => void
  send: (text: string) => Promise<void>
  processCase: (doc: string, item: string, processType?: string) => Promise<void>
  stop: () => Promise<void>
  clear: () => void
  /** Append a system statement to the transcript — an enqueue confirmation, say. */
  postNotice: (content: string) => void
  submitMessageFeedback: (
    content: string,
    feedbackType: "positive" | "negative",
    comment: string
  ) => Promise<void>
}

export function useAgentChat(): AgentChat {
  const caseId = useCaseInContext()
  const auth = useAuth()
  const getFreshTokens = useFreshToken()
  const queryClient = useQueryClient()

  const [input, setInput] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [ready, setReady] = useState(false)
  const [contextCases, setContextCasesState] = useState<WorkItem[]>([])

  // Only consulted when no case is in context. With a case, the session *is* the
  // case's, derived below — so no state can drift out of step with the URL, which is
  // what let a "Process" click stream into the previously focused case's session.
  const [ephemeralSessionId, setEphemeralSessionId] = useState(() => crypto.randomUUID())
  const sessionId = caseId ? toRuntimeSessionId(caseId) : ephemeralSessionId

  const abortRef = useRef<AbortController | null>(null)
  // Which caseId `messages` has already been seeded from, so a later render of the
  // same case cannot re-seed and clobber a live-streaming turn.
  const seededForRef = useRef<string | null>(null)
  // Stash the triggering request so the auth popup's postMessage can replay it on the
  // same session. Refs, not state, so the long-lived listener never reads stale values.
  const pendingAuthResumeRef = useRef<{ prompt: string; extras?: Record<string, unknown> } | null>(
    null
  )
  const sessionIdRef = useRef(sessionId)
  sessionIdRef.current = sessionId
  const isLoadingRef = useRef(isLoading)
  isLoadingRef.current = isLoading

  // Confirm the Runtime is configured. agentRuntimeService reads the ARN and region
  // from the same config at call time, so no client object is constructed here.
  useEffect(() => {
    fetch("/aws-exports.json")
      .then(r => r.json())
      .then(config => setReady(Boolean(config.agentRuntimeArn)))
      .catch(e => setError(`Config error: ${e}`))
  }, [])

  // The case's prior turns, for replay. Same query key the workspace's detail pane
  // uses, so React Query serves both observers from one request rather than two.
  const caseQuery = useQuery({
    queryKey: ["case", caseId],
    queryFn: async () => {
      const { idToken } = await getFreshTokens()
      if (!idToken) throw new Error("Not authenticated")
      return fetchCase(caseId!, idToken)
    },
    enabled: auth.isAuthenticated && !!caseId && isCaseId(caseId),
  })

  // Replay the case's decision chain as the conversation's history, so opening a case
  // continues its thread instead of presenting a blank assistant that has to be told
  // what has already happened. Keyed by case, so the data can never belong to another.
  useEffect(() => {
    if (!caseId) {
      seededForRef.current = null
      return
    }
    if (seededForRef.current === caseId) return
    const record = caseQuery.data
    if (!record) return
    setTranscript(tracesToMessages(record.agent_traces ?? []))
    seededForRef.current = caseId
  }, [caseId, caseQuery.data])

  // A run interrupted by unmount would otherwise leave the rail reading "working".
  useEffect(() => () => setAgentActivity({ kind: "idle" }), [])

  /**
   * Cases a route has put in context beyond the focused one — the workspace's
   * multi-select. Returning `prev` bails out of the re-render, so a route may push
   * this from an effect on every render without looping.
   */
  const setContextCases = useCallback((next: WorkItem[]) => {
    setContextCasesState(prev =>
      prev.length === next.length && prev.every((c, i) => c === next[i]) ? prev : next
    )
  }, [])

  /** Clears any pending SAP-auth replay. Must run at the start of every new turn —
   *  otherwise a stale resume can replay against the wrong session. */
  const resetPendingAuth = useCallback(() => {
    pendingAuthResumeRef.current = null
  }, [])

  /**
   * Clears the rail's heartbeat on every exit — normal return, abort, thrown error.
   * Every caller routes through this wrapper rather than resetting for itself, which
   * is what a caller that forgot the reset cost us once. `finally` rather than a line
   * after the await because the inner function publishes activity as it streams: any
   * throw from it after that point would otherwise strand the rail claiming live work.
   */
  async function streamAgentInvocation(
    prompt: string,
    runtimeSessionId: string,
    extras?: Record<string, unknown>
  ): Promise<void> {
    try {
      await runAgentStream(prompt, runtimeSessionId, extras)
    } finally {
      setAgentActivity({ kind: "idle" })
    }
  }

  /**
   * Stream a single agent invocation into the transcript.
   *
   * Canonical AG-UI events are folded into a projection by `reduceAguiEvent`; the
   * projection's messages replace this turn's slice of the history on each event.
   */
  async function runAgentStream(
    prompt: string,
    runtimeSessionId: string,
    extras?: Record<string, unknown>
  ): Promise<void> {
    if (!ready) return

    const { accessToken } = await getFreshTokens()
    if (!accessToken) throw new Error("Authentication required.")

    const runId = crypto.randomUUID()
    const startedAt = new Date().toISOString()
    let projection: AguiProjection = { messages: [] }
    // Every id this turn has rendered. The turn is spliced against live state rather
    // than a prefix captured up front, because the caller may still have an
    // uncommitted append in flight — its own user message.
    const ownedIds = new Set<string>()

    // Shown until the first canonical event arrives so the turn is visibly in flight.
    const placeholder: Message = {
      id: `assistant-${runId}`,
      role: "assistant",
      content: "",
      timestamp: startedAt,
      segments: [],
    }

    const render = () => {
      const turn = projection.messages.length > 0 ? projection.messages : [placeholder]
      for (const message of turn) {
        if (message.id) ownedIds.add(message.id)
      }
      setAgentActivity(deriveActivity(turn))
      setTranscript(prev => spliceTurnIntoHistory(prev, turn, ownedIds))
    }

    /** Append a client-side notice to the turn without going through the reducer. */
    const appendNotice = (content: string) => {
      const projected = [...projection.messages]
      const last = projected[projected.length - 1]
      if (last && last.role === "assistant") {
        projected[projected.length - 1] = {
          ...last,
          content: last.content + content,
          segments: [...(last.segments ?? []), { type: "text", content }],
        }
      } else {
        projected.push({
          id: `notice-${runId}`,
          role: "assistant",
          content,
          timestamp: new Date().toISOString(),
          segments: [{ type: "text", content }],
        })
      }
      projection = { ...projection, messages: projected }
      render()
    }

    /** TOOL_CALL_RESULT carries the payload as `content`; `result` is tolerated. */
    const toolResultText = (event: AguiEvent): string | undefined => {
      const value = event.content ?? event.result
      if (typeof value === "string") return value
      if (value === undefined || value === null) return undefined
      try {
        return JSON.stringify(value)
      } catch {
        return String(value)
      }
    }

    render()

    const abort = new AbortController()
    abortRef.current = abort

    let failure: unknown

    try {
      await invokeInteractiveRun(
        {
          message: prompt,
          threadId: runtimeSessionId,
          runtimeSessionId,
          runId,
          caseId: typeof extras?.case_id === "string" ? extras.case_id : undefined,
          processType: typeof extras?.process_type === "string" ? extras.process_type : undefined,
        },
        accessToken,
        (event: AguiEvent) => {
          projection = reduceAguiEvent(projection, event, new Date().toISOString(), runId)
          // Plain tool-result path: remember this request so the auth popup can replay it.
          // The agent's AG-UI adapter has no interrupt/resume mapping, so replaying the
          // prompt after sign-in is the only resume path.
          if (event.type === "TOOL_CALL_RESULT" && parseAuthRequired(toolResultText(event))) {
            pendingAuthResumeRef.current = { prompt, extras }
          }
          render()
        },
        abort.signal
      )
    } catch (err) {
      failure = err
    }

    abortRef.current = null

    // User stopped the agent
    if (abort.signal.aborted) {
      projection = settleAguiProjection(projection)
      appendNotice("\n\n⏹ Stopped.")
      return
    }

    if (failure) {
      projection = settleAguiProjection(projection)
      // The request was rejected before streaming, so no run is in flight. Saying the
      // agent is still working would send the user to wait on a run that never began.
      // Keyed on the error type rather than an event count: a heartbeat-only stream
      // that then breaks did start a run, even though no event was projected.
      if (failure instanceof AgentRuntimeStartError) {
        const detail = failure instanceof Error ? failure.message : String(failure)
        appendNotice(`\n\n❌ The agent run could not be started: ${detail}`)
        return
      }
      // The stream began and then broke, so the agent may still be running server-side.
      // Tools without a canonical result settle as unconfirmed rather than failed.
      appendNotice(
        "\n\n⚠️ Streaming connection lost after the run started. The agent is likely still " +
          "running server-side — check the case state in a few moments for the final result."
      )
    }
    // A clean finish needs no notice: RUN_ERROR already appended its own message
    // through the reducer, and RUN_FINISHED's content is the answer itself.
  }

  // Keep the message listener's invocation fn current without re-registering it.
  const streamRef = useRef(streamAgentInvocation)
  streamRef.current = streamAgentInvocation

  // The auth popup posts back here on success. Origin check is the security
  // boundary — do not widen it. Clear the pending request before replaying so it can't loop.
  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      if (e.origin !== window.location.origin) return
      if (e.data?.type !== "sap-auth-complete") return
      const pending = pendingAuthResumeRef.current
      if (!pending || isLoadingRef.current) return
      pendingAuthResumeRef.current = null
      setIsLoading(true)
      streamRef
        .current(pending.prompt, sessionIdRef.current, pending.extras)
        .catch(err => setError(err instanceof Error ? err.message : "Resume failed"))
        .finally(() => setIsLoading(false))
    }
    window.addEventListener("message", onMessage)
    return () => window.removeEventListener("message", onMessage)
  }, [])

  /** Cases a route has put in context, as a prompt preamble. */
  const contextPrefix = useCallback((): string => {
    if (contextCases.length === 0) return ""
    const items = contextCases.map(
      c =>
        `- ${c.case_id ?? formatCaseId(c.document_number, c.item_id)}: status=${c.status}, ` +
        `supplier=${c.supplier_number ?? "none"}, amount=${formatAmount(c.amount)}, ` +
        `exception=${c.exception_type ?? "none"}`
    )
    return `[Context: The user has selected ${contextCases.length} case(s) for processing:\n${items.join("\n")}\n]\n\n`
  }, [contextCases])

  const postNotice = useCallback((content: string) => {
    setTranscript(prev => [
      ...prev,
      { role: "assistant" as const, content, timestamp: new Date().toISOString() },
    ])
  }, [])

  /** Send a free-form message, with the case in context and any selection attached. */
  const send = useCallback(
    async (userMessage: string): Promise<void> => {
      if (!userMessage.trim() || !ready) return
      setError(null)
      // Only the plain tool-result path sets a pending resume now, and that raises no
      // server-side interrupt — so there is no stale session to escape. Rotating here
      // would hand the user a new AgentCore Memory thread, discarding the conversation
      // at exactly the moment they finish signing in and expect it to continue.
      resetPendingAuth()

      // Read at send time rather than closing over the transcript: the store is not
      // React state, so a closure captured on the last render could be a turn behind.
      const fullPrompt = contextPrefix() + buildPromptWithHistory(userMessage, getTranscript())
      setTranscript(prev => [
        ...prev,
        { role: "user" as const, content: userMessage, timestamp: new Date().toISOString() },
      ])
      setInput("")
      setIsLoading(true)

      try {
        await streamRef.current(fullPrompt, sessionId, caseId ? { case_id: caseId } : undefined)
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return
        const msg = err instanceof Error ? err.message : "Unknown error"
        setError(`Failed: ${msg}`)
        setTranscript(prev => {
          const updated = [...prev]
          updated[updated.length - 1] = {
            ...updated[updated.length - 1],
            content: "Error processing request. Please try again.",
          }
          return updated
        })
      } finally {
        abortRef.current = null
        setIsLoading(false)
      }
    },
    [ready, resetPendingAuth, contextPrefix, sessionId, caseId]
  )

  /**
   * Process one case end to end, streaming into the transcript.
   *
   * The session id is computed from the case rather than read off state: the caller
   * has usually just pointed the URL at this case, and state written in the same tick
   * is not visible here — which used to send the run to the previous case's session.
   */
  const processCase = useCallback(
    async (doc: string, item: string, processType?: string): Promise<void> => {
      const key = formatCaseId(doc, item)
      const runtimeSessionId = toRuntimeSessionId(key)
      setIsLoading(true)
      setError(null)
      resetPendingAuth() // new turn on this case — drop any pending auth from a prior turn

      // Claim the replay slot before streaming. The caller usually focuses the case in
      // the same click, so its record lands mid-run — and the replay effect would seed
      // traces that predate this turn straight over it, emptying the transcript.
      seededForRef.current = key

      // Snapshot before the append below, so the summary is the conversation up to this
      // turn and not this turn's own "Process case" line restated back to the agent.
      const history = getTranscript()

      setTranscript(prev => [
        ...prev,
        {
          role: "user" as const,
          content: `Process case ${key}`,
          timestamp: new Date().toISOString(),
        },
      ])

      // History reaches the agent by one client-side route, not two. The transcript is
      // already seeded from this case's agent_traces by the effect above, so the same
      // summarizer the free-text path uses covers replay here too. (Server-side Memory
      // also restores the case's session; this stays as the belt-and-braces for restore
      // lag, which is why buildPromptWithHistory exists at all.)
      const prompt = buildPromptWithHistory(
        `Process ERP exception case: ${key} (document_number=${doc}, item_id=${item})`,
        history
      )
      try {
        await streamRef.current(prompt, runtimeSessionId, {
          case_id: key,
          ...(processType ? { process_type: processType } : {}),
        })
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return
        const msg = err instanceof Error ? err.message : "Unknown error"
        postNotice(`❌ Error processing ${key}: ${msg}`)
      } finally {
        setIsLoading(false)
      }

      // The trace is written server-side, so the case is refetched rather than patched.
      // Twice: once now, once after a beat, because the trace reaches DynamoDB after
      // the stream closes and the first read can still miss it.
      const refresh = () => {
        void queryClient.invalidateQueries({ queryKey: ["cases"] })
        void queryClient.invalidateQueries({ queryKey: ["case", key] })
      }
      refresh()
      setTimeout(refresh, 3000)
    },
    [postNotice, queryClient, resetPendingAuth]
  )

  const stop = useCallback(async (): Promise<void> => {
    abortRef.current?.abort()
    abortRef.current = null
    resetPendingAuth() // stopping abandons the paused turn
    if (!ready) return
    const { accessToken } = await getFreshTokens()
    if (accessToken) {
      stopInteractiveSession(sessionId, accessToken).catch(err =>
        console.warn("Failed to stop runtime session:", err)
      )
    }
  }, [ready, getFreshTokens, sessionId, resetPendingAuth])

  const clear = useCallback(() => {
    clearTranscript()
    setError(null)
    resetPendingAuth()
    // Only meaningful off a case. On a case the session belongs to the case, and
    // rotating it would strand the conversation the operator is auditing.
    if (!caseId) setEphemeralSessionId(crypto.randomUUID())
  }, [caseId, resetPendingAuth])

  const submitMessageFeedback = useCallback(
    async (
      content: string,
      feedbackType: "positive" | "negative",
      comment: string
    ): Promise<void> => {
      const { idToken } = await getFreshTokens()
      if (!idToken) return
      await submitFeedback(
        { sessionId, message: content, feedbackType, comment: comment || undefined },
        idToken
      )
    },
    [getFreshTokens, sessionId]
  )

  return {
    caseId,
    input,
    setInput,
    isLoading,
    error,
    setError,
    sessionId,
    ready,
    contextCaseCount: contextCases.length,
    setContextCases,
    send,
    processCase,
    stop,
    clear,
    postNotice,
    submitMessageFeedback,
  }
}

/**
 * The shell's chat, from inside a routed page. Throws rather than returning a stub:
 * a page that reads this outside the layout route is a routing mistake, and a silent
 * no-op assistant is harder to notice than a failure.
 */
export function useAssistant(): AgentChat {
  const chat = useOutletContext<AgentChat | null>()
  if (!chat) throw new Error("useAssistant must be used inside the AppShell layout route")
  return chat
}
