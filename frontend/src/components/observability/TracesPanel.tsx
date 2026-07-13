// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

"use client"

import { useState, useMemo } from "react"
import {
  ChevronDown,
  ChevronRight,
  Clock,
  Bot,
  User,
  Webhook,
  Timer,
  AlertTriangle,
  Loader2,
} from "lucide-react"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import type { TraceRecord } from "@/services/observabilityService"
import { getOutcomeColor, filterErrorTraces, sortAndLimitTraces } from "./utils/traceUtils"
import TraceStats from "./TraceStats"
import SpanTimeline from "./SpanTimeline"
import SessionView from "./SessionView"
import { useStaggeredEntrance } from "./hooks/useStaggeredEntrance"
import "./observability-animations.css"
// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------

const DESKTOP_LIMIT = 25
const MOBILE_LIMIT = 10

/** Map trigger strings to icons and labels for badges. */
const TRIGGER_STYLE: Record<string, { icon: typeof Bot; label: string; className: string }> = {
  poller: { icon: Timer, label: "Poller", className: "bg-amber-100 text-amber-700" },
  manual: { icon: User, label: "Manual", className: "bg-blue-100 text-blue-700" },
  "webhook-ses": { icon: Webhook, label: "Email", className: "bg-purple-100 text-purple-700" },
  webhook: { icon: Webhook, label: "Webhook", className: "bg-purple-100 text-purple-700" },
}

/** Map outcome to Tailwind border-left color class. */
function getOutcomeBorderClass(outcome: string): string {
  switch (outcome) {
    case "complete":
      return "border-l-green-500"
    case "error":
      return "border-l-red-500"
    case "cancelled":
      return "border-l-yellow-500"
    default:
      return "border-l-gray-400"
  }
}

/** Map outcome to a human-readable label. */
function getOutcomeLabel(outcome: string): string {
  switch (outcome) {
    case "complete":
      return "Complete"
    case "error":
      return "Error"
    case "cancelled":
      return "Cancelled"
    case "disconnected":
      return "Disconnected"
    default:
      return outcome || "Unknown"
  }
}

/** Map outcome to Tailwind text color class. */
function getOutcomeTextClass(outcome: string): string {
  switch (outcome) {
    case "complete":
      return "text-green-600"
    case "error":
      return "text-red-600"
    case "cancelled":
      return "text-yellow-600"
    default:
      return "text-gray-500"
  }
}

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
function TriggerBadge({ trigger }: { trigger: string }) {
  const style = TRIGGER_STYLE[trigger] ?? {
    icon: Bot,
    label: trigger || "agent",
    className: "bg-gray-100 text-gray-600",
  }
  const Icon = style.icon
  return (
    <span
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium ${style.className}`}
    >
      <Icon size={10} />
      {style.label}
    </span>
  )
}

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
export interface TracesPanelProps {
  traces: TraceRecord[]
  loading: boolean
  isMobile: boolean
}

export default function TracesPanel({ traces, loading, isMobile }: TracesPanelProps) {
  const [expandedTraceId, setExpandedTraceId] = useState<string | null>(null)
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null)
  const [showErrorsOnly, setShowErrorsOnly] = useState(false)

  const errorTraces = useMemo(() => filterErrorTraces(traces), [traces])
  const errorCount = errorTraces.length

  const filteredTraces = useMemo(
    () => (showErrorsOnly ? errorTraces : traces),
    [showErrorsOnly, errorTraces, traces]
  )

  const limit = isMobile ? MOBILE_LIMIT : DESKTOP_LIMIT
  const displayTraces = useMemo(
    () => sortAndLimitTraces(filteredTraces, limit),
    [filteredTraces, limit]
  )

  const { getDelay } = useStaggeredEntrance(displayTraces.length, 0, 40)

  const handleRowClick = (traceId: string) => {
    setExpandedTraceId(prev => (prev === traceId ? null : traceId))
  }

  const handleCaseClick = (e: React.MouseEvent, caseId: string) => {
    e.stopPropagation()
    setSelectedCaseId(caseId)
  }

  const handleCloseSession = () => {
    setSelectedCaseId(null)
  }

  return (
    <Card className="py-0">
      <CardHeader className="py-4 border-b">
        <div className="flex items-center justify-between w-full">
          <CardTitle className="text-base">
            {selectedCaseId ? `Session: ${selectedCaseId}` : "Recent Agent Traces"}
          </CardTitle>
          <div className="flex items-center gap-2">
            {!selectedCaseId && (
              <button
                onClick={() => setShowErrorsOnly(prev => !prev)}
                className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
                  showErrorsOnly
                    ? "bg-red-100 text-red-700 border border-red-300"
                    : "bg-gray-100 text-gray-600 hover:bg-gray-200 border border-transparent"
                }`}
                aria-pressed={showErrorsOnly}
                aria-label={`Filter error traces. ${errorCount} errors.`}
              >
                <AlertTriangle size={12} />
                Errors
                {errorCount > 0 && (
                  <span
                    className={`inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full text-[10px] font-bold ${
                      showErrorsOnly ? "bg-red-600 text-white" : "bg-gray-300 text-gray-700"
                    }`}
                  >
                    {errorCount}
                  </span>
                )}
              </button>
            )}
            {selectedCaseId && (
              <button
                onClick={handleCloseSession}
                className="text-xs text-blue-600 hover:text-blue-800 underline"
              >
                ← Back to traces
              </button>
            )}
          </div>
        </div>
      </CardHeader>

      <CardContent className="p-4 space-y-4">
        {selectedCaseId ? (
          <SessionView caseId={selectedCaseId} traces={traces} onClose={handleCloseSession} />
        ) : (
          <>
            <TraceStats traces={traces} />

            {loading && (
              <div className="flex items-center justify-center py-8 text-gray-400 text-sm gap-2">
                <Loader2 size={16} className="animate-spin" />
                Loading traces…
              </div>
            )}

            {!loading && displayTraces.length === 0 && (
              <p className="text-gray-400 text-xs text-center py-6">
                {showErrorsOnly
                  ? "No error or cancelled traces in this time range."
                  : "No agent traces in this time range."}
              </p>
            )}

            {!loading && displayTraces.length > 0 && (
              <div className="space-y-1.5">
                {displayTraces.map((trace, index) => {
                  const isExpanded = expandedTraceId === trace.trace_id
                  const delay = getDelay(index)
                  const time = new Date(trace.timestamp).toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                  })
                  const date = new Date(trace.timestamp).toLocaleDateString([], {
                    month: "short",
                    day: "numeric",
                  })

                  return (
                    <div
                      key={trace.trace_id}
                      className="opacity-0"
                      style={{
                        animation: `fadeSlideUp 300ms ease-out ${delay}ms forwards`,
                      }}
                    >
                      <div
                        className={`border rounded-md overflow-hidden border-l-4 ${getOutcomeBorderClass(trace.outcome)} transition-colors`}
                      >
                        <button
                          onClick={() => handleRowClick(trace.trace_id)}
                          className={`flex items-center gap-2 px-3 py-2 text-xs w-full text-left transition-colors ${
                            isExpanded ? "bg-gray-50" : "hover:bg-gray-50"
                          }`}
                          aria-expanded={isExpanded}
                        >
                          {isExpanded ? (
                            <ChevronDown size={12} className="flex-none text-gray-400" />
                          ) : (
                            <ChevronRight size={12} className="flex-none text-gray-400" />
                          )}

                          <span
                            onClick={e => handleCaseClick(e, trace.case_id)}
                            className="text-blue-600 hover:text-blue-800 hover:underline cursor-pointer font-mono text-[11px] flex-none"
                            role="link"
                            tabIndex={0}
                            onKeyDown={e => {
                              if (e.key === "Enter" || e.key === " ") {
                                e.preventDefault()
                                handleCaseClick(e as unknown as React.MouseEvent, trace.case_id)
                              }
                            }}
                          >
                            {trace.case_id}
                          </span>

                          <span className="flex items-center gap-1 text-gray-500 flex-none">
                            <Clock size={10} className="text-gray-400" />
                            {date} {time}
                          </span>

                          <TriggerBadge trigger={trace.trigger} />

                          <span
                            className={`text-[10px] font-medium flex-none ${getOutcomeTextClass(trace.outcome)}`}
                            style={{ color: getOutcomeColor(trace.outcome) }}
                          >
                            {getOutcomeLabel(trace.outcome)}
                          </span>

                          <span className="flex-none text-gray-400 text-[10px] ml-auto">
                            {trace.segment_count} segment{trace.segment_count !== 1 ? "s" : ""}
                          </span>
                        </button>

                        {isExpanded && (
                          <div className="border-t px-3 py-3 bg-white">
                            <SpanTimeline
                              segments={trace.segments}
                              isError={trace.outcome === "error" || trace.outcome === "cancelled"}
                            />
                          </div>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
