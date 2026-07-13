// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { useAuth } from "react-oidc-context"
import { Allotment } from "allotment"
import "allotment/dist/style.css"
import { Link } from "react-router-dom"
import { RefreshCw, X, Sparkles, PanelLeftClose, PanelLeftOpen } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { ChatInput } from "@/components/chat/ChatInput"
import { ChatMessages } from "@/components/chat/ChatMessages"
import { useGlobal } from "@/app/context/GlobalContext"
import { AgentCoreClient } from "@/lib/agentcore-client"
import type { AgentPattern, StreamEvent } from "@/lib/agentcore-client"
import { buildPromptWithHistory } from "@/lib/buildPromptWithHistory"
import type { Message, MessageSegment, ToolCall } from "@/components/chat/types"
import type { WorkItem, CaseStatus } from "@/types/cases"
import { CASE_STATUSES, STATUS_META, DOMAINS, DOMAIN_META, Domain } from "@/types/cases"
import { fetchCases, fetchCase, enqueueCases } from "@/services/casesService"
import { submitFeedback } from "@/services/feedbackService"
import { useDefaultTool } from "@/hooks/useToolRenderer"
import { useDemoFeatures } from "@/hooks/useDemoEnabled"
import { ToolCallDisplay, parseAuthRequired } from "@/components/chat/ToolCallDisplay"
import { TraceViewer } from "@/components/chat/TraceViewer"
import { domainFields } from "@/lib/domainFields"
import { useWorkspacePrefs, usePanelSizes } from "@/hooks/useWorkspacePrefs"

/** Auto-refresh interval for the focused case detail (ms). */
const CASE_POLL_MS = 10_000

function caseKey(c: WorkItem): string {
  return `${c.document_number}-${c.item_id}`
}

function fmt(n?: number | null): string {
  if (n == null) return "—"
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

/**
 * Format a date string as relative time (e.g. "2h ago", "3d ago").
 *
 * @param iso - ISO date string.
 * @returns Relative time string or empty string.
 */
function timeAgo(iso?: string | null): string {
  if (!iso) return ""
  const diff = Math.max(0, Date.now() - new Date(iso).getTime())
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return "just now"
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

function StatusBadge({ status }: { status: CaseStatus }) {
  const meta = STATUS_META[status] ?? STATUS_META.detected
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap px-2 py-0.5 rounded-full text-[11px] font-medium ${meta.color}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} />
      {meta.label}
    </span>
  )
}

interface CasesPanelProps {
  cases: WorkItem[]
  loading: boolean
  filter: CaseStatus | "all"
  setFilter: (f: CaseStatus | "all") => void
  domainFilter: Domain | "all"
  setDomainFilter: (d: Domain | "all") => void
  selected: Set<string>
  toggleSelect: (key: string) => void
  toggleAll: () => void
  focusedKey: string | null
  onFocus: (key: string) => void
  onProcess: () => void
  processing: boolean
  onRefresh: () => void
  collapsed: boolean
  onToggleCollapse: () => void
}

function CasesPanel({
  cases,
  loading,
  filter,
  setFilter,
  domainFilter,
  setDomainFilter,
  selected,
  toggleSelect,
  toggleAll,
  focusedKey,
  onFocus,
  onProcess,
  processing,
  onRefresh,
  collapsed,
  onToggleCollapse,
}: CasesPanelProps) {
  if (collapsed) {
    // Drag the rail's right edge rightward past a threshold to reopen (mirrors the sash).
    const onHandleDown = (e: React.PointerEvent) => {
      const startX = e.clientX
      const move = (ev: PointerEvent) => {
        if (ev.clientX - startX > 40) {
          onToggleCollapse()
          cleanup()
        }
      }
      const cleanup = () => {
        window.removeEventListener("pointermove", move)
        window.removeEventListener("pointerup", cleanup)
      }
      window.addEventListener("pointermove", move)
      window.addEventListener("pointerup", cleanup)
    }
    return (
      <div className="relative flex flex-col items-center h-full border-r py-2 gap-3">
        <button
          onClick={onToggleCollapse}
          className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent"
          title="Expand cases"
          aria-label="Expand cases panel"
        >
          <PanelLeftOpen size={16} />
        </button>
        <span className="rounded-full bg-muted px-1.5 py-0.5 text-[11px] font-medium tabular-nums text-muted-foreground">
          {cases.length}
        </span>
        <button
          onClick={onToggleCollapse}
          className="flex-1 text-xs font-medium tracking-wide text-muted-foreground hover:text-foreground [writing-mode:vertical-rl]"
          title="Expand cases"
        >
          Cases
        </button>
        {/* Drag-to-reopen strip on the right edge */}
        <div
          onPointerDown={onHandleDown}
          className="absolute inset-y-0 right-0 w-1.5 cursor-ew-resize hover:bg-accent"
          title="Drag to expand cases"
          aria-hidden
        />
      </div>
    )
  }
  return (
    <div className="flex flex-col h-full border-r">
      <div className="flex-none border-b px-3 py-2 space-y-2">
        <div className="flex min-h-7 items-center justify-between">
          <h2 className="font-semibold text-sm">Cases</h2>
          <div className="flex items-center gap-1.5">
            <span className="rounded-full bg-muted px-1.5 py-0.5 text-[11px] font-medium tabular-nums text-muted-foreground">
              {cases.length}
            </span>
            <button
              onClick={onRefresh}
              disabled={loading}
              className="p-0.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent disabled:opacity-50"
              title="Refresh"
            >
              <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
            </button>
            <button
              onClick={onToggleCollapse}
              className="p-0.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent"
              title="Collapse cases"
              aria-label="Collapse cases panel"
            >
              <PanelLeftClose size={13} />
            </button>
          </div>
        </div>
        <div className="flex border-b -mx-3 px-1">
          <button
            onClick={() => setDomainFilter("all")}
            className={`flex-1 px-2 py-1 text-[11px] font-medium border-b-2 transition-colors ${
              domainFilter === "all"
                ? "border-foreground text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            All
          </button>
          {DOMAINS.map(d => (
            <button
              key={d}
              onClick={() => setDomainFilter(d)}
              className={`flex-1 px-2 py-1 text-[11px] font-medium border-b-2 transition-colors ${
                domainFilter === d
                  ? "border-foreground text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {DOMAIN_META[d].short}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1">
          <Select value={filter} onValueChange={v => setFilter(v as CaseStatus | "all")}>
            <SelectTrigger className="h-7 text-xs flex-1">
              <SelectValue placeholder="Filter" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All</SelectItem>
              {CASE_STATUSES.map(s => (
                <SelectItem key={s} value={s}>
                  <span className="inline-flex items-center gap-1.5">
                    <span className={`h-1.5 w-1.5 rounded-full ${STATUS_META[s].dot}`} />
                    {STATUS_META[s].label}
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button size="sm" variant="outline" className="h-7 text-xs px-2" onClick={toggleAll}>
            {selected.size === cases.length && cases.length > 0 ? "None" : "All"}
          </Button>
        </div>
        {selected.size > 0 && (
          <Button
            size="sm"
            className="w-full h-7 text-xs"
            onClick={onProcess}
            disabled={processing}
          >
            {processing
              ? "Processing…"
              : selected.size === 1
                ? "Process in Chat ▶"
                : `Process ${selected.size} in Background ▶`}
          </Button>
        )}
      </div>
      <div className="flex-1 overflow-auto">
        {loading ? (
          <p className="text-muted-foreground text-xs text-center mt-8">Loading…</p>
        ) : cases.length === 0 ? (
          <p className="text-muted-foreground text-xs text-center mt-8">No cases.</p>
        ) : (
          <div className="divide-y">
            {cases.map(c => {
              const key = caseKey(c)
              const isSelected = selected.has(key)
              const isFocused = focusedKey === key
              return (
                <div
                  key={key}
                  className={`flex items-center gap-2 px-3 py-2 cursor-pointer transition-colors ${
                    isFocused
                      ? "bg-accent border-l-2 border-foreground"
                      : isSelected
                        ? "bg-muted/60"
                        : "hover:bg-accent/60"
                  }`}
                  onClick={() => onFocus(key)}
                >
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={e => {
                      e.stopPropagation()
                      toggleSelect(key)
                    }}
                    onClick={e => e.stopPropagation()}
                    className="h-3.5 w-3.5 rounded-sm border-border"
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-1">
                      <span className="text-xs font-medium truncate">
                        {c.title ?? `${c.document_number} / ${c.item_id}`}
                      </span>
                      <StatusBadge status={c.status} />
                    </div>
                    <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground mt-0.5">
                      <span className="bg-muted text-muted-foreground px-1 rounded-sm">
                        {DOMAIN_META[c.domain]?.short ?? c.domain}
                      </span>
                      <span className="font-medium text-foreground">{fmt(c.amount)}</span>
                      {c.exception_type && (
                        <span className="bg-red-50 text-red-600 px-1 rounded-sm">
                          {c.exception_type}
                        </span>
                      )}
                      <span className="ml-auto">{timeAgo(c.updated_at)}</span>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

interface CaseDetailPanelProps {
  caseData: WorkItem | null
  onClose: () => void
  refreshing: boolean
  onRefresh: () => void
  onProcess: () => void
  processing: boolean
}

function CaseDetailPanel({
  caseData,
  onClose,
  refreshing,
  onRefresh,
  onProcess,
  processing,
}: CaseDetailPanelProps) {
  const { ticketing } = useDemoFeatures()
  if (!caseData) return null

  const meta = STATUS_META[caseData.status] ?? STATUS_META.detected

  return (
    <div className="flex flex-col h-full border-r overflow-auto">
      <div className="flex-none border-b px-3 py-2 space-y-2">
        <div className="flex min-h-7 items-center justify-between">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-sm font-semibold truncate">
              {caseData.title || `${caseData.document_number}-${caseData.item_id}`}
            </span>
            <span
              className={`inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap px-2 py-0.5 rounded-full text-xs font-medium ${meta.color}`}
            >
              <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} />
              {meta.label}
            </span>
          </div>
          <div className="flex items-center gap-1 shrink-0">
            <button
              onClick={onRefresh}
              disabled={refreshing}
              className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent disabled:opacity-50"
              title="Refresh case"
            >
              <RefreshCw size={13} className={refreshing ? "animate-spin" : ""} />
            </button>
            <button
              onClick={onClose}
              className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent"
              title="Close detail"
            >
              <X size={14} />
            </button>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" className="h-7 text-xs px-3" onClick={onProcess} disabled={processing}>
            {processing ? "Processing…" : "Process ▶"}
          </Button>
          {ticketing && (
            <Link to={`/tickets?case_id=${caseData.document_number}%23${caseData.item_id}`}>
              <Button size="sm" variant="outline" className="h-7 text-xs px-3">
                Tickets →
              </Button>
            </Link>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-auto px-3 py-4 space-y-4">
        {/* Case fields */}
        <div>
          <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
            Info
          </h3>
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
            {domainFields(caseData, fmt).map(([label, value]) => (
              <div key={label} className="contents">
                <dt className="text-muted-foreground">{label}</dt>
                <dd className="font-medium text-right">{value}</dd>
              </div>
            ))}
          </dl>
        </div>

        {/* Processing history — each agent invocation is a collapsible entry */}
        <div>
          <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
            Processing History
          </h3>
          {caseData.agent_traces && caseData.agent_traces.length > 0 ? (
            <TraceViewer traces={caseData.agent_traces} />
          ) : (
            <p className="text-muted-foreground text-xs">No processing history yet.</p>
          )}
        </div>
      </div>
    </div>
  )
}

export default function WorkspacePage() {
  const { focusedKey, setFocusedKey, filter, setFilter, domainFilter, setDomainFilter } =
    useWorkspacePrefs()

  // Cases state
  const [cases, setCases] = useState<WorkItem[]>([])
  const [casesLoading, setCasesLoading] = useState(true)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const focusedKeyRef = useRef<string | null>(focusedKey)
  const [focusedCase, setFocusedCase] = useState<WorkItem | null>(null)
  const [focusedRefreshing, setFocusedRefreshing] = useState(false)
  const [casesError, setCasesError] = useState<string | null>(null)

  // Messages are not persisted: they carry SAP tool results (PO numbers, amounts,
  // vendor data), and localStorage would leak them across logout on a shared machine.
  // The sign-in flow uses a popup, so the tab never unloads and state survives it.
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [chatError, setChatError] = useState<string | null>(null)
  const [client, setClient] = useState<AgentCoreClient | null>(null)
  const [sessionId, setSessionId] = useState(() => crypto.randomUUID())
  const [processing, setProcessing] = useState(false)
  const [casesCollapsed, setCasesCollapsedState] = useState(
    () => localStorage.getItem("workspace.casesCollapsed") === "1"
  )
  const setCasesCollapsed = useCallback((next: boolean) => {
    localStorage.setItem("workspace.casesCollapsed", next ? "1" : "0")
    setCasesCollapsedState(next)
  }, [])
  const toggleCasesCollapsed = () => setCasesCollapsed(!casesCollapsed)

  const { isLoading, setIsLoading } = useGlobal()
  const auth = useAuth()
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  // Stash the triggering request so the popup's postMessage can replay it on the
  // same session. Refs, not state, so the long-lived listener never reads stale values.
  const pendingAuthResumeRef = useRef<{ prompt: string; extras?: Record<string, unknown> } | null>(
    null
  )
  // Surfaced when the agent pauses for SAP sign-in. Button click is a real user
  // gesture, so popup blockers allow the login popup it opens.
  const [authPending, setAuthPending] = useState<{ authUrl: string } | null>(null)
  const sessionIdRef = useRef(sessionId)
  sessionIdRef.current = sessionId
  const isLoadingRef = useRef(isLoading)
  isLoadingRef.current = isLoading

  /** Return a fresh id_token, silently refreshing if the current one is expired or about to expire. */
  const getFreshIdToken = useCallback(async (): Promise<string | undefined> => {
    const user = auth.user
    if (!user) return undefined
    // Refresh if token expires within 60 seconds
    if (user.expired || (user.expires_in !== undefined && user.expires_in < 60)) {
      try {
        const refreshed = await auth.signinSilent()
        return refreshed?.id_token
      } catch {
        return user.id_token // fall back to current token
      }
    }
    return user.id_token
  }, [auth])

  // Clears pending SAP-auth resume + banner. Must run at the start of every new
  // turn/session — otherwise a stale banner can replay an interruptId against the wrong session.
  const resetPendingAuth = useCallback(() => {
    pendingAuthResumeRef.current = null
    setAuthPending(null)
  }, [])

  useDefaultTool(({ name, args, status, result }) => (
    <ToolCallDisplay name={name} args={args} status={status} result={result} />
  ))

  // Keep focusedKeyRef in sync with state
  useEffect(() => {
    focusedKeyRef.current = focusedKey
  }, [focusedKey])

  // Load AgentCore client
  useEffect(() => {
    fetch("/aws-exports.json")
      .then(r => r.json())
      .then(config => {
        if (config.agentRuntimeArn) {
          setClient(
            new AgentCoreClient({
              runtimeArn: config.agentRuntimeArn,
              region: config.awsRegion || "us-east-1",
              pattern: (config.agentPattern || "strands-single-agent") as AgentPattern,
            })
          )
        }
      })
      .catch(e => setChatError(`Config error: ${e}`))
  }, [])

  // Load cases list
  const loadCases = useCallback(async () => {
    setCasesLoading(true)
    setCasesError(null)
    try {
      const token = auth.user?.id_token
      if (!token) throw new Error("Not authenticated")
      const freshCases = await fetchCases({ status: filter, domain: domainFilter }, token)
      setCases(freshCases)
    } catch (e) {
      setCasesError(e instanceof Error ? e.message : "Unknown error")
    } finally {
      setCasesLoading(false)
    }
  }, [filter, domainFilter, auth.user?.id_token])

  useEffect(() => {
    loadCases()
  }, [loadCases])

  /**
   * Refresh the focused case detail from the API using a consistent read.
   * Uses functional setState to avoid overwriting with stale data.
   */
  const refreshFocusedCase = useCallback(async () => {
    const currentKey = focusedKeyRef.current
    if (!currentKey) return
    const token = auth.user?.id_token
    if (!token) return
    const [doc, item] = currentKey.split("-")
    try {
      setFocusedRefreshing(true)
      const fresh = await fetchCase(doc, item, token)
      setFocusedCase(prev => {
        const key = `${fresh.document_number}-${fresh.item_id}`
        if (key !== focusedKeyRef.current) return prev
        return fresh
      })
    } catch {
      // Silent fail on background refresh
    } finally {
      setFocusedRefreshing(false)
    }
  }, [auth.user?.id_token])

  // When focusedKey changes, show from list immediately then fetch fresh
  useEffect(() => {
    if (focusedKey) {
      const fromList = cases.find(c => caseKey(c) === focusedKey) ?? null
      setFocusedCase(fromList)
      refreshFocusedCase()
    } else {
      setFocusedCase(null)
    }
  }, [focusedKey])

  // Auto-refresh focused case on interval — only while processing
  useEffect(() => {
    if (!focusedKey || !processing) return
    const id = setInterval(refreshFocusedCase, CASE_POLL_MS)
    return () => clearInterval(id)
  }, [focusedKey, processing, refreshFocusedCase])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  // Selection helpers
  const toggleSelect = (key: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(key) ? next.delete(key) : next.add(key)
      return next
    })
  }

  const toggleAll = () => {
    setSelected(
      selected.size === cases.length && cases.length > 0 ? new Set() : new Set(cases.map(caseKey))
    )
  }

  // Focused case for center panel — now managed via dedicated state + auto-refresh
  const showDetail = focusedKey !== null
  const { initialSizes, onPanelChange } = usePanelSizes(showDetail)

  // Build context prefix from selected cases
  function buildContextPrefix(): string {
    if (selected.size === 0) return ""
    const items = [...selected].map(k => {
      const c = cases.find(x => caseKey(x) === k)
      if (!c) return k
      return `- ${k}: status=${c.status}, supplier=${c.supplier_number ?? "none"}, amount=${fmt(c.amount)}, exception=${c.exception_type ?? "none"}`
    })
    return `[Context: The user has selected ${selected.size} case(s) for processing:\n${items.join("\n")}\n]\n\n`
  }

  /**
   * Stream a single agent invocation into the chat panel.
   * Returns the captured segments for trace persistence.
   *
   * @param prompt - The prompt to send to the agent.
   * @param overrideSessionId - Optional session ID override (defaults to current state).
   * @returns The message segments captured during streaming.
   */
  interface InvocationResult {
    segments: MessageSegment[]
    stopReason?: string
  }

  async function streamAgentInvocation(
    prompt: string,
    overrideSessionId?: string,
    extras?: Record<string, unknown>
  ): Promise<InvocationResult> {
    if (!client) return { segments: [] }

    const assistantMsg: Message = {
      role: "assistant",
      content: "",
      timestamp: new Date().toISOString(),
    }
    setMessages(prev => [...prev, assistantMsg])

    const segments: MessageSegment[] = []
    const toolCallMap = new Map<string, ToolCall>()

    const updateMessage = () => {
      const content = segments
        .filter((s): s is Extract<MessageSegment, { type: "text" }> => s.type === "text")
        .map(s => s.content)
        .join("")
      setMessages(prev => {
        const updated = [...prev]
        updated[updated.length - 1] = {
          ...updated[updated.length - 1],
          content,
          segments: [...segments],
        }
        return updated
      })
    }

    const accessToken = auth.user?.access_token
    if (!accessToken) throw new Error("Authentication required.")

    const abort = new AbortController()
    abortRef.current = abort
    const { stopReason, aborted, errorMessage, disconnected } = await client.invoke(
      prompt,
      overrideSessionId ?? sessionId,
      accessToken,
      (event: StreamEvent) => {
        switch (event.type) {
          case "text": {
            // Mark any in-progress tools as complete when new text arrives
            for (const tc of toolCallMap.values()) {
              if (tc.status === "streaming" || tc.status === "executing") tc.status = "complete"
            }
            const last = segments[segments.length - 1]
            if (last && last.type === "text") last.content += event.content
            else segments.push({ type: "text", content: event.content })
            updateMessage()
            break
          }
          case "tool_use_start": {
            const tc: ToolCall = {
              toolUseId: event.toolUseId,
              name: event.name,
              input: "",
              status: "streaming",
            }
            toolCallMap.set(event.toolUseId, tc)
            segments.push({ type: "tool", toolCall: tc })
            updateMessage()
            break
          }
          case "tool_use_delta": {
            const tc = toolCallMap.get(event.toolUseId)
            if (tc) tc.input += event.input
            updateMessage()
            break
          }
          case "tool_result": {
            const tc = toolCallMap.get(event.toolUseId)
            if (tc) {
              tc.result = event.result
              tc.status = "complete"
            }
            // Plain tool-result path (no interrupt): remember this request so the auth
            // popup can replay it. The interrupt event fires instead when SAP_AUTH_INTERRUPT is on.
            if (parseAuthRequired(event.result)) {
              pendingAuthResumeRef.current = { prompt, extras }
            }
            updateMessage()
            break
          }
          case "interrupt": {
            // Resume by replaying the interrupt id (not a fresh prompt) so the paused tool
            // re-runs. Can't auto-open the popup here — this callback isn't a user-gesture
            // stack, so a blocker would kill it. Show a banner button instead; its click is the gesture.
            pendingAuthResumeRef.current = {
              prompt,
              extras: { ...extras, interrupt_response: { interruptId: event.interruptId } },
            }
            if (event.authUrl) setAuthPending({ authUrl: event.authUrl })
            break
          }
          case "message": {
            if (event.role === "assistant") {
              for (const tc of toolCallMap.values()) {
                if (tc.status === "streaming") tc.status = "executing"
              }
              updateMessage()
            }
            break
          }
        }
      },
      abort.signal,
      extras
    )

    abortRef.current = null

    // User stopped the agent
    if (aborted) {
      segments.push({ type: "text", content: "\n\n⏹ Stopped." })
      updateMessage()
      return { segments, stopReason: "stopped" }
    }

    // Stream was interrupted by a network disconnect — agent may still be running
    if (disconnected) {
      segments.push({
        type: "text",
        content:
          "\n\n⚠️ Streaming connection lost. The agent is likely still running server-side — " +
          "check the case state in a few moments for the final result.",
      })
      updateMessage()
      return { segments, stopReason: "disconnected" }
    }

    // Append a warning if the agent was cancelled or the stream ended without a completion signal
    if (stopReason?.startsWith("cancelled:")) {
      const reason = stopReason.replace("cancelled:", "")
      const warning =
        reason === "max_turns"
          ? "⚠️ Agent reached the maximum number of processing steps and stopped early. The case may be partially processed."
          : `⚠️ Agent was cancelled: ${reason}`
      segments.push({ type: "text", content: `\n\n${warning}` })
      updateMessage()
    } else if (stopReason === "error") {
      segments.push({
        type: "text",
        content: `\n\n❌ Agent error: ${errorMessage || "Unknown error. Check agent logs for details."}`,
      })
      updateMessage()
    } else if (!stopReason && !pendingAuthResumeRef.current) {
      // Suppress this warning when paused for SAP sign-in — the turn stopped deliberately.
      segments.push({
        type: "text",
        content:
          "\n\n⚠️ Agent stream ended unexpectedly without a completion signal. The case may be partially processed.",
      })
      updateMessage()
    }

    return { segments, stopReason }
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
      setAuthPending(null)
      setIsLoading(true)
      streamRef
        .current(pending.prompt, sessionIdRef.current, pending.extras)
        .catch(err => setChatError(err instanceof Error ? err.message : "Resume failed"))
        .finally(() => setIsLoading(false))
    }
    window.addEventListener("message", onMessage)
    return () => window.removeEventListener("message", onMessage)
  }, [setIsLoading])

  /**
   * Process a single case: focus it in the detail panel and stream into chat.
   *
   * @param doc - Document number (partition key).
   * @param item - Item identifier (sort key).
   */
  async function processSingleCase(doc: string, item: string): Promise<void> {
    const key = `${doc}-${item}`
    setFocusedKey(key)
    setProcessing(true)
    setIsLoading(true)
    setChatError(null)
    // Fresh session + clear chat for each case processing
    setSessionId(crypto.randomUUID())
    setMessages([])
    resetPendingAuth() // new session — drop any pending auth from a prior turn

    setMessages(prev => [
      ...prev,
      {
        role: "user" as const,
        content: `Process case ${key}`,
        timestamp: new Date().toISOString(),
      },
    ])

    const c = cases.find(x => caseKey(x) === key)

    // Include previous processing history so the agent knows what was tried before
    let historyContext = ""
    if (c?.agent_traces && c.agent_traces.length > 0) {
      const summaries = c.agent_traces.slice(-3).map((t, i) => {
        const text = t.segments
          .filter(s => s.type === "text" && s.content)
          .map(s => s.content!.trim())
          .join(" ")
        const truncated = text.length > 300 ? text.slice(0, 300) + "…" : text
        return `Attempt ${i + 1} (${t.timestamp}, outcome: ${t.outcome || "unknown"}): ${truncated}`
      })
      historyContext = `\n\n<previous_processing_history>\nThis case has been processed ${c.agent_traces.length} time(s) before. Recent attempts:\n${summaries.join("\n")}\n</previous_processing_history>`
    }

    const prompt = `Process ERP exception case: document_number=${doc}, item_id=${item}${historyContext}`
    try {
      const extras = c?.process_type
        ? { process_type: c.process_type, case_id: `${doc}#${item}` }
        : { case_id: `${doc}#${item}` }
      await streamAgentInvocation(prompt, undefined, extras)
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return
      const msg = err instanceof Error ? err.message : "Unknown error"
      setMessages(prev => [
        ...prev,
        {
          role: "assistant" as const,
          content: `❌ Error processing ${key}: ${msg}`,
          timestamp: new Date().toISOString(),
        },
      ])
    }
    // Trace is saved server-side by the agent runtime
    // Cleanup and refresh regardless of outcome
    setProcessing(false)
    setIsLoading(false)
    // Refresh twice: once immediately, once after 3s to catch DynamoDB trace propagation
    await loadCases()
    await refreshFocusedCase()
    setTimeout(async () => {
      await loadCases()
      await refreshFocusedCase()
    }, 3000)
  }

  /**
   * Process selected cases sequentially via direct SSE streaming.
   * Single selection: focus the case and stream into chat.
   * Multiple selection: process all sequentially in the background.
   */
  async function processSelected() {
    if (selected.size === 0 || !client) return

    // Single case: focus it and stream live
    if (selected.size === 1) {
      const key = [...selected][0]
      const c = cases.find(x => caseKey(x) === key)
      const doc = c?.document_number ?? key.split("-")[0]
      const item = c?.item_id ?? key.split("-")[1]
      return processSingleCase(doc, item)
    }

    // Multiple cases: enqueue to SQS for background processing.
    // Each case gets its own SQS message → isolated agent session with user identity.
    setProcessing(true)
    setChatError(null)
    resetPendingAuth()
    setMessages([
      {
        role: "assistant" as const,
        content: `⏳ Enqueuing ${selected.size} cases for background processing…`,
        timestamp: new Date().toISOString(),
      },
    ])

    const caseList = [...selected].map(key => {
      const c = cases.find(x => caseKey(x) === key)
      return {
        key,
        doc: c?.document_number ?? key.split("-")[0],
        item: c?.item_id ?? key.split("-")[1],
      }
    })

    try {
      const token = await getFreshIdToken()
      if (!token) throw new Error("Not authenticated")

      const caseIds = caseList.map(({ doc, item }) => `${doc}#${item}`)
      await enqueueCases(caseIds, token)

      setMessages(prev => [
        ...prev,
        {
          role: "assistant" as const,
          content: `✅ ${caseList.length} case(s) enqueued. Processing in background — refresh to see updates.`,
          timestamp: new Date().toISOString(),
        },
      ])
    } catch (e) {
      setChatError(e instanceof Error ? e.message : "Failed to enqueue cases")
    } finally {
      setProcessing(false)
    }
  }

  /**
   * Send a free-form chat message to the agent with selected cases as context.
   */
  async function sendMessage(userMessage: string): Promise<void> {
    if (!userMessage.trim() || !client) return
    setChatError(null)
    // A pending SAP-auth interrupt means the AgentCore session still has the interrupt
    // active server-side; reusing it makes Strands reject the prompt. Rotate to a fresh
    // session so the turn starts clean — resetPendingAuth() only clears the client banner.
    const hadPendingAuth = pendingAuthResumeRef.current !== null
    resetPendingAuth() // new user turn supersedes any pending SAP-auth resume
    let turnSessionId = sessionId
    if (hadPendingAuth) {
      turnSessionId = crypto.randomUUID()
      setSessionId(turnSessionId)
    }

    const fullPrompt = buildContextPrefix() + buildPromptWithHistory(userMessage, messages)
    setMessages(prev => [
      ...prev,
      { role: "user" as const, content: userMessage, timestamp: new Date().toISOString() },
    ])
    setInput("")
    setIsLoading(true)

    try {
      await streamAgentInvocation(
        fullPrompt,
        turnSessionId,
        focusedCase
          ? { case_id: `${focusedCase.document_number}#${focusedCase.item_id}` }
          : undefined
      )
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return
      const msg = err instanceof Error ? err.message : "Unknown error"
      setChatError(`Failed: ${msg}`)
      setMessages(prev => {
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
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    sendMessage(input)
  }

  const handleStop = () => {
    abortRef.current?.abort()
    abortRef.current = null
    resetPendingAuth() // stopping abandons the paused turn — don't leave a live banner
    const accessToken = auth.user?.access_token
    if (client && accessToken) {
      client.stopSession(sessionId, accessToken)
    }
  }

  const handleFeedbackSubmit = async (
    messageContent: string,
    feedbackType: "positive" | "negative",
    comment: string
  ) => {
    const idToken = auth.user?.id_token
    if (!idToken) return
    await submitFeedback(
      { sessionId, message: messageContent, feedbackType, comment: comment || undefined },
      idToken
    )
  }

  const hasMessages = messages.length > 0

  /** Process the currently focused case from the detail panel. */
  const processFocused = () => {
    if (!focusedCase) return
    processSingleCase(focusedCase.document_number, focusedCase.item_id)
  }

  /** Close the detail panel. */
  const closeDetail = () => {
    setFocusedKey(null)
    setFocusedCase(null)
  }

  const chatPane = (
    <div className="flex flex-col h-full">
      <div className="flex-none border-b px-3 py-2">
        <div className="flex min-h-7 items-center justify-between">
          <h2 className="font-semibold text-sm">
            Agent Chat
            {selected.size > 0 && (
              <span className="ml-1 text-xs font-normal text-muted-foreground">
                ({selected.size} case{selected.size > 1 ? "s" : ""})
              </span>
            )}
          </h2>
          {hasMessages && (
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              onClick={() => {
                setMessages([])
                setChatError(null)
                setSessionId(crypto.randomUUID())
                resetPendingAuth() // clearing chat drops the stale sign-in banner too
              }}
            >
              Clear
            </Button>
          )}
        </div>
      </div>

      {(chatError || casesError) && (
        <div className="bg-red-50 border-l-4 border-red-500 p-2 mx-2 mt-1">
          <p className="text-xs text-red-700">{chatError || casesError}</p>
        </div>
      )}

      {authPending && (
        <div className="bg-amber-50 border-l-4 border-amber-500 p-2 mx-2 mt-1 flex items-center justify-between gap-2">
          <p className="text-xs text-amber-800">
            SAP sign-in needed to continue. This conversation resumes automatically after you sign
            in.
          </p>
          <Button
            size="sm"
            className="h-7 text-xs shrink-0 bg-amber-600 hover:bg-amber-700"
            onClick={() =>
              // Click = user gesture, so the popup isn't blocked. SapAuthCallback posts
              // back to the listener above, which replays the paused turn.
              window.open(
                authPending.authUrl,
                "sapAuth",
                "width=480,height=700,menubar=no,toolbar=no"
              )
            }
          >
            Sign in to SAP
          </Button>
        </div>
      )}

      {!hasMessages ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-3 px-3">
          <div className="animate-rise-in flex flex-col items-center gap-4 max-w-sm text-center">
            <span className="flex h-11 w-11 items-center justify-center rounded-lg bg-muted text-muted-foreground">
              <Sparkles size={20} />
            </span>
            <div>
              <h3 className="text-lg font-semibold tracking-tight text-foreground">
                Ready when you are
              </h3>
              <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                Select cases and click <span className="font-medium text-foreground">Process</span>,
                or just ask the agent a question below.
              </p>
            </div>
          </div>
          <div className="w-full">
            <ChatInput
              input={input}
              setInput={setInput}
              handleSubmit={handleSubmit}
              isLoading={isLoading}
              onStop={handleStop}
              selectedCaseCount={selected.size}
            />
          </div>
        </div>
      ) : (
        <>
          <div className="flex-1 overflow-hidden">
            <ChatMessages
              messages={messages}
              messagesEndRef={messagesEndRef}
              sessionId={sessionId}
              onFeedbackSubmit={handleFeedbackSubmit}
            />
          </div>
          <div className="flex-none">
            <ChatInput
              input={input}
              setInput={setInput}
              handleSubmit={handleSubmit}
              isLoading={isLoading}
              onStop={handleStop}
              selectedCaseCount={selected.size}
            />
          </div>
        </>
      )}
    </div>
  )

  const casesPane = (
    <CasesPanel
      cases={cases}
      loading={casesLoading}
      filter={filter}
      setFilter={setFilter}
      domainFilter={domainFilter}
      setDomainFilter={setDomainFilter}
      selected={selected}
      toggleSelect={toggleSelect}
      toggleAll={toggleAll}
      focusedKey={focusedKey}
      onFocus={setFocusedKey}
      onProcess={processSelected}
      processing={processing}
      onRefresh={loadCases}
      collapsed={casesCollapsed}
      onToggleCollapse={toggleCasesCollapsed}
    />
  )

  return (
    <div className="h-full flex">
      {/* Collapsed rail lives outside the split so the freed width flows to detail/chat */}
      {casesCollapsed && <div className="flex-none w-11">{casesPane}</div>}
      <Allotment
        key={`${showDetail ? "detail" : "list"}-${casesCollapsed ? "railed" : "full"}`}
        className="flex-1"
        proportionalLayout={false}
        defaultSizes={initialSizes}
        onChange={casesCollapsed ? undefined : onPanelChange}
        onVisibleChange={(index, visible) => {
          // Dragging the cases sash past its snap point collapses it to the rail.
          if (index === 0 && !visible && !casesCollapsed) setCasesCollapsed(true)
        }}
      >
        {/* Cases list — snaps shut on drag; hidden (width→0) when collapsed, rail stands in */}
        <Allotment.Pane minSize={200} snap visible={!casesCollapsed}>
          {casesCollapsed ? null : casesPane}
        </Allotment.Pane>

        {/* Case detail — always rendered, collapses to 0 when no case focused */}
        <Allotment.Pane minSize={showDetail ? 300 : 0} maxSize={showDetail ? undefined : 0}>
          {showDetail ? (
            <CaseDetailPanel
              caseData={focusedCase}
              onClose={closeDetail}
              refreshing={focusedRefreshing}
              onRefresh={refreshFocusedCase}
              onProcess={processFocused}
              processing={processing}
            />
          ) : null}
        </Allotment.Pane>

        {/* Chat */}
        <Allotment.Pane minSize={280}>{chatPane}</Allotment.Pane>
      </Allotment>
    </div>
  )
}
