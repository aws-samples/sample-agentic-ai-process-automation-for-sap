// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useRef, useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useAuth } from "react-oidc-context"
import { useFreshToken } from "@/hooks/useFreshToken"
import { Allotment, type AllotmentHandle } from "allotment"
import "allotment/dist/style.css"
import { Link } from "react-router"
import { RefreshCw, X, PanelLeftClose, PanelLeftOpen } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import type { WorkItem, CaseStatus } from "@/types/cases"
import { CASE_STATUSES, DOMAINS, STATUS_META, Domain, caseStatusMeta } from "@/types/cases"
import { StatusBadge, StatusDot } from "@/components/ui/status-badge"
import { Banner, DomainTabs } from "@/components/ui/page-chrome"
import { fetchCases, fetchCase, enqueueCases } from "@/services/casesService"
import { fetchTickets } from "@/services/ticketsService"
import { formatCaseId, isCaseId, parseCaseId, tryFormatCaseId } from "@/lib/caseKey"
import { AGENT_PULSE_KEY, notifyWorkEnqueued } from "@/components/AgentHeartbeat"
import { useDemoFeatures } from "@/hooks/useDemoEnabled"
import { InlineCaseTicket } from "@/components/tickets/TicketResponseControls"
import { CaseTimeline } from "@/components/case/CaseTimeline"
import { HandoverPanel } from "@/components/HandoverPanel"
import { DOMAIN_SOURCE, domainFields, formatAmount } from "@/lib/domainFields"
import { shortAge } from "@/lib/timeAgo"
import { useWorkspacePrefs, usePanelSizes } from "@/hooks/useWorkspacePrefs"
import { usePanelCollapsed } from "@/hooks/usePanelCollapsed"
import { useAssistant } from "@/hooks/useAgentChat"

/** Auto-refresh interval for the focused case detail (ms). */
const CASE_POLL_MS = 10_000

/**
 * The canonical case identity, which is also the workspace's `?case=` URL key and
 * the selection-set key. One representation for the list, the URL, and the API.
 *
 * Records written before the poller stored `case_id` derive it from their key. A
 * value the codec cannot build is kept only so the row still renders and stays
 * selectable — the API boundary rejects it rather than mis-routing it.
 */
function caseKey(c: WorkItem): string {
  return (
    c.case_id ??
    tryFormatCaseId(c.document_number, c.item_id) ??
    `${c.document_number}-${c.item_id}`
  )
}

/** The list's case-count pill — one spelling for the header and the collapsed strip. */
function CountPill({ n }: { n: number }) {
  return (
    <span className="rounded-full bg-muted px-1.5 py-0.5 text-2xs font-medium tabular-nums text-muted-foreground">
      {n}
    </span>
  )
}

interface CasesPanelProps {
  cases: WorkItem[]
  loading: boolean
  error: string | null
  filter: CaseStatus | "all"
  setFilter: (f: CaseStatus | "all") => void
  domainFilter: Domain
  setDomainFilter: (d: Domain) => void
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
  error,
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
        <CountPill n={cases.length} />
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
            <CountPill n={cases.length} />
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
        {DOMAINS.length > 1 && <DomainTabs value={domainFilter} onChange={setDomainFilter} dense />}
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
                    <StatusDot tone={STATUS_META[s].tone} />
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
      {/* The list's own failure surface: without it a failed fetch reads as "No cases." */}
      {error && (
        <Banner tone="danger" className="p-2 text-xs">
          {error}
        </Banner>
      )}
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
                  <div className="flex min-w-0 flex-1 items-center gap-2">
                    <span className="min-w-0 flex-1 truncate text-xs font-medium">
                      {c.title ?? caseKey(c)}
                    </span>
                    <span className="flex-none text-2xs font-medium tabular-nums text-foreground">
                      {formatAmount(c.amount, c.currency)}
                    </span>
                    <StatusBadge {...caseStatusMeta(c.status)} />
                    <span
                      className="flex-none text-2xs tabular-nums text-muted-foreground"
                      title={c.updated_at ?? undefined}
                    >
                      {shortAge(c.updated_at)}
                    </span>
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
  token: string
}

function CaseDetailPanel({
  caseData,
  onClose,
  refreshing,
  onRefresh,
  onProcess,
  processing,
  token,
}: CaseDetailPanelProps) {
  const { ticketing } = useDemoFeatures()
  if (!caseData) return null

  const meta = caseStatusMeta(caseData.status)
  const source = DOMAIN_SOURCE[caseData.domain]

  return (
    <div className="flex flex-col h-full border-r overflow-auto">
      <div className="flex-none border-b px-3 py-2 space-y-2">
        <div className="flex min-h-7 items-center justify-between">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-sm font-semibold truncate">
              {caseData.title || caseKey(caseData)}
            </span>
            <StatusBadge {...meta} className="text-xs" />
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
            <Link to={`/tickets?case_id=${caseKey(caseData)}`}>
              <Button size="sm" variant="outline" className="h-7 text-xs px-3">
                Tickets →
              </Button>
            </Link>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-auto px-3 py-4 space-y-4">
        {ticketing && caseData.ticket_id && token && (
          <InlineCaseTicket ticketId={caseData.ticket_id} token={token} onSubmitted={onRefresh} />
        )}

        {/* Case fields — each SAP-sourced figure names the field it was read from */}
        <div>
          <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
            Info
          </h3>
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
            {domainFields(caseData, formatAmount).map(({ label, value, exact, sapField }) => (
              <div key={label} className="contents">
                <dt className="text-muted-foreground">
                  {label}
                  {/* The attribution belongs on the label, not the value: an operator
                      comparing against SAP needs the field name, and putting it beside
                      the figure would compete with the figure itself. */}
                  {sapField && (
                    <span className="block font-mono text-3xs opacity-70">{sapField}</span>
                  )}
                </dt>
                <dd className="font-medium text-right" title={exact}>
                  {value}
                </dd>
              </div>
            ))}
          </dl>
          {source && (
            <p className="mt-1.5 font-mono text-3xs text-muted-foreground">
              {source.service} · {source.entity} · {caseKey(caseData)}
            </p>
          )}
        </div>

        {/* Decision chain — the latest run is visible, earlier runs collapse */}
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Decision Chain
          </h3>
          <CaseTimeline traces={caseData.agent_traces ?? []} />
        </div>
      </div>
    </div>
  )
}

export default function WorkspacePage() {
  const { focusedKey, setFocusedKey, filter, setFilter, domainFilter, setDomainFilter } =
    useWorkspacePrefs()
  const { ticketing, testData } = useDemoFeatures()

  // The conversation belongs to the shell, not to this page — the assistant is docked
  // beside every route. This page only puts cases in its context and asks it to run.
  const chat = useAssistant()

  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [processing, setProcessing] = useState(false)
  const {
    collapsed: casesCollapsed,
    setCollapsed: setCasesCollapsed,
    toggle: toggleCasesCollapsed,
  } = usePanelCollapsed("workspace.casesCollapsed")

  const auth = useAuth()
  const getFreshTokens = useFreshToken()
  const queryClient = useQueryClient()

  const casesQuery = useQuery({
    queryKey: ["cases", filter, domainFilter],
    queryFn: async () => {
      const { idToken } = await getFreshTokens()
      if (!idToken) throw new Error("Not authenticated")
      return fetchCases({ status: filter, domain: domainFilter }, idToken)
    },
    enabled: auth.isAuthenticated,
  })
  const cases = casesQuery.data ?? []
  const casesLoading = casesQuery.isLoading
  const casesError = casesQuery.error instanceof Error ? casesQuery.error.message : null
  const loadCases = casesQuery.refetch

  // Focused case for center panel — now managed via dedicated state + auto-refresh
  const showDetail = focusedKey !== null

  // The handover has to be over every case, not the filtered list the operator is
  // looking at — so it reads the rail's cache entry rather than starting a second scan
  // of the same table. The rail owns the poll cadence; this only observes.
  const allCasesQuery = useQuery({
    queryKey: AGENT_PULSE_KEY,
    queryFn: async () => {
      const { idToken } = await getFreshTokens()
      if (!idToken) throw new Error("Not authenticated")
      return fetchCases({}, idToken)
    },
    enabled: auth.isAuthenticated && !showDetail,
  })

  // Owner grouping's only source. `undefined` when ticketing is off is load-bearing:
  // the digest groups by process_type and states that it did, rather than inventing a
  // recipient for a case nobody was assigned.
  const ticketsQuery = useQuery({
    queryKey: ["tickets", "all"],
    queryFn: async () => {
      const { idToken } = await getFreshTokens()
      if (!idToken) throw new Error("Not authenticated")
      return fetchTickets({}, idToken)
    },
    enabled: auth.isAuthenticated && ticketing && !showDetail,
  })

  // `focusedKey` is the canonical case_id, which is also the table key — no split.
  const focusedCaseQuery = useQuery({
    queryKey: ["case", focusedKey],
    queryFn: async () => {
      const { idToken } = await getFreshTokens()
      if (!idToken) throw new Error("Not authenticated")
      return fetchCase(focusedKey!, idToken)
    },
    enabled: auth.isAuthenticated && !!focusedKey && isCaseId(focusedKey),
    // Only shows from-list data instantly on the first render for a given key;
    // once the fresh fetch lands it's cached and this is never consulted again.
    placeholderData: () => cases.find(c => caseKey(c) === focusedKey),
    // Refetch while processing so the detail panel tracks the agent's progress.
    refetchInterval: processing ? CASE_POLL_MS : false,
  })
  const focusedCase = focusedCaseQuery.data ?? null
  const focusedRefreshing = focusedCaseQuery.isFetching
  const refreshFocusedCase = useCallback(async () => {
    await focusedCaseQuery.refetch()
  }, [focusedCaseQuery.refetch])

  // Publish the multi-selection so the docked assistant can name those cases in its
  // prompt preamble. The focused case reaches it through the URL, not through here.
  // `selectedCases` is a fresh array every render, which is safe: setContextCases
  // compares element identity and returns the previous state unchanged, so this
  // re-runs without re-rendering.
  const selectedCases = cases.filter(c => selected.has(caseKey(c)))
  useEffect(() => {
    chat.setContextCases(selectedCases)
  }, [selectedCases, chat.setContextCases])

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

  // Sizes are tracked per mode (list vs detail) so toggling the detail pane can
  // restore the right layout via resize() below, without remounting Allotment —
  // a remount would reset the list's scroll position.
  const { initialSizes: listSizes, onPanelChange: onListPanelChange } = usePanelSizes(false)
  const { initialSizes: detailSizes, onPanelChange: onDetailPanelChange } = usePanelSizes(true)
  const initialSizes = showDetail ? detailSizes : listSizes
  const onPanelChange = showDetail ? onDetailPanelChange : onListPanelChange
  const allotmentRef = useRef<AllotmentHandle>(null)
  const prevShowDetailRef = useRef(showDetail)
  useEffect(() => {
    if (prevShowDetailRef.current === showDetail) return
    prevShowDetailRef.current = showDetail
    allotmentRef.current?.resize(showDetail ? detailSizes : listSizes)
  }, [showDetail, detailSizes, listSizes])

  /**
   * Process a single case: focus it, then hand the run to the docked assistant.
   *
   * Focusing first is what points the assistant at this case — it reads the case from
   * the URL — but state written in this tick is not visible to `processCase`, which is
   * why that derives the session id from the case itself rather than from state.
   *
   * @param doc - Document number (an attribute of the case, not its key).
   * @param item - Item identifier (likewise). Together they form the case_id.
   */
  async function processSingleCase(doc: string, item: string): Promise<void> {
    const key = formatCaseId(doc, item)
    setFocusedKey(key)
    setProcessing(true)
    const c = cases.find(x => caseKey(x) === key)
    try {
      await chat.processCase(doc, item, c?.process_type)
    } finally {
      // The assistant invalidates the case and list queries itself, twice, to cover
      // the lag before the trace reaches DynamoDB — so nothing is refetched here.
      setProcessing(false)
    }
  }

  /**
   * Process the selection.
   * One case: hand it to the docked assistant and watch it stream.
   * Several: enqueue for background processing — the rail reports on those.
   */
  async function processSelected() {
    if (selected.size === 0 || !chat.ready) return

    if (selected.size === 1) {
      const key = [...selected][0]
      const c = cases.find(x => caseKey(x) === key)
      const fallback = parseCaseId(key)
      const doc = c?.document_number ?? fallback.document_number
      const item = c?.item_id ?? fallback.item_id
      return processSingleCase(doc, item)
    }

    // Multiple cases: enqueue to SQS for background processing.
    // Each case gets its own SQS message → isolated agent session with user identity.
    setProcessing(true)
    chat.setError(null)
    // The selection key is already the canonical case_id the API expects.
    const caseIds = [...selected]
    chat.postNotice(`⏳ Enqueuing ${caseIds.length} cases for background processing…`)

    try {
      const { idToken } = await getFreshTokens()
      if (!idToken) throw new Error("Not authenticated")

      await enqueueCases(caseIds, idToken)
      // The rail polls on its own interval and has no other way to learn about this.
      notifyWorkEnqueued(queryClient)

      chat.postNotice(
        `✅ ${caseIds.length} case(s) enqueued. Processing in background — the rail tracks ` +
          `progress; refresh the list to see each case's new status.`
      )
    } catch (e) {
      chat.setError(e instanceof Error ? e.message : "Failed to enqueue cases")
    } finally {
      setProcessing(false)
    }
  }

  /** Process the currently focused case from the detail panel. */
  const processFocused = () => {
    if (!focusedCase) return
    processSingleCase(focusedCase.document_number, focusedCase.item_id)
  }

  /** Close the detail panel. */
  const closeDetail = () => {
    setFocusedKey(null)
  }

  const casesPane = (
    <CasesPanel
      cases={cases}
      loading={casesLoading}
      error={casesError}
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
      {/* Collapsed rail lives outside the split so the freed width flows to the detail */}
      {casesCollapsed && <div className="flex-none w-[var(--gutter-w)]">{casesPane}</div>}
      <Allotment
        ref={allotmentRef}
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

        {/* Case detail, or the shift handover when nothing is focused — the landing
            surface is a supervisor's queue, not an empty pane. */}
        <Allotment.Pane minSize={300}>
          {showDetail ? (
            <CaseDetailPanel
              caseData={focusedCase}
              onClose={closeDetail}
              refreshing={focusedRefreshing}
              onRefresh={refreshFocusedCase}
              onProcess={processFocused}
              processing={processing}
              token={auth.user?.id_token ?? ""}
            />
          ) : (
            <HandoverPanel
              cases={allCasesQuery.data ?? []}
              tickets={ticketing ? (ticketsQuery.data ?? []) : undefined}
              loading={allCasesQuery.isFetching}
              onRefresh={() => {
                void allCasesQuery.refetch()
                void ticketsQuery.refetch()
              }}
              onOpenCase={setFocusedKey}
              testDataEnabled={testData}
            />
          )}
        </Allotment.Pane>
      </Allotment>
    </div>
  )
}
