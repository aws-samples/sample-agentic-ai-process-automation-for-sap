// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useState, useMemo } from "react"
import {
  ArrowLeft,
  Timer,
  User,
  Webhook,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Layers,
  Activity,
  Hash,
} from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import type { TraceRecord } from "@/services/observabilityService"
import { filterTracesByCase, computeSessionAggregates, getOutcomeColor } from "./utils/traceUtils"
import { TONE_TEXT } from "@/lib/statusTone"
import SpanTimeline from "./SpanTimeline"
import { useStaggeredEntrance } from "./hooks/useStaggeredEntrance"
import "./observability-animations.css"

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
export interface SessionViewProps {
  caseId: string
  traces: TraceRecord[]
  onClose: () => void
}

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// Trigger is categorical (which source fired the run), not a state, so these keep
// distinct hues with dark variants rather than mapping onto the tone set.
function TriggerIcon({ trigger }: { trigger: string }) {
  switch (trigger) {
    case "poller":
      return <Timer size={14} className="text-amber-600 dark:text-amber-400" />
    case "manual":
      return <User size={14} className="text-blue-600 dark:text-blue-400" />
    case "webhook-ses":
    case "webhook":
      return <Webhook size={14} className="text-purple-600 dark:text-purple-400" />
    default:
      return <Activity size={14} className="text-muted-foreground" />
  }
}

function getTriggerLabel(trigger: string): string {
  switch (trigger) {
    case "poller":
      return "Poller"
    case "manual":
      return "Manual"
    case "webhook-ses":
      return "Email"
    case "webhook":
      return "Webhook"
    default:
      return trigger || "Unknown"
  }
}

// Outcome is state, so colour comes from the tone vocabulary.
function OutcomeIcon({ outcome }: { outcome: string }) {
  switch (outcome) {
    case "complete":
      return <CheckCircle2 size={14} className={TONE_TEXT.success} />
    case "error":
      return <XCircle size={14} className={TONE_TEXT.danger} />
    case "cancelled":
      return <AlertTriangle size={14} className={TONE_TEXT.progress} />
    default:
      return <AlertTriangle size={14} className="text-muted-foreground/70" />
  }
}

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

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
export default function SessionView({ caseId, traces, onClose }: SessionViewProps) {
  const [expandedTraceId, setExpandedTraceId] = useState<string | null>(null)

  const caseTraces = useMemo(() => filterTracesByCase(traces, caseId), [traces, caseId])
  const aggregates = useMemo(() => computeSessionAggregates(caseTraces), [caseTraces])
  const { getDelay } = useStaggeredEntrance(caseTraces.length, 0, 60)

  const handleToggleTrace = (traceId: string) => {
    setExpandedTraceId(prev => (prev === traceId ? null : traceId))
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <button
          onClick={onClose}
          className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
          aria-label="Back to traces"
        >
          <ArrowLeft size={14} />
          Back
        </button>
        <div>
          <h3 className="text-sm font-semibold text-foreground">
            Session: <span className="font-mono">{caseId}</span>
          </h3>
          <p className="text-2xs text-muted-foreground">
            All agent invocations for this case in chronological order
          </p>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <Card className="p-3 py-3">
          <CardContent className="p-0 flex items-center gap-2">
            <div className="p-1.5 rounded-md bg-blue-50 dark:bg-blue-400/15">
              <Hash size={14} className="text-blue-600 dark:text-blue-400" />
            </div>
            <div>
              <p className="text-3xs text-muted-foreground uppercase tracking-wider">Invocations</p>
              <p className="font-display text-lg font-bold tabular-nums">
                {aggregates.totalInvocations}
              </p>
            </div>
          </CardContent>
        </Card>

        <Card className="p-3 py-3">
          <CardContent className="p-0 flex items-center gap-2">
            <div className="p-1.5 rounded-md bg-purple-50 dark:bg-purple-400/15">
              <Layers size={14} className="text-purple-600 dark:text-purple-400" />
            </div>
            <div>
              <p className="text-3xs text-muted-foreground uppercase tracking-wider">
                Total Segments
              </p>
              <p className="font-display text-lg font-bold tabular-nums">
                {aggregates.totalSegments}
              </p>
            </div>
          </CardContent>
        </Card>

        <Card className="p-3 py-3">
          <CardContent className="p-0 flex items-center gap-2">
            <div
              className="p-1.5 rounded-md"
              style={{ backgroundColor: `${getOutcomeColor(aggregates.overallOutcome)}15` }}
            >
              <OutcomeIcon outcome={aggregates.overallOutcome} />
            </div>
            <div>
              <p className="text-3xs text-muted-foreground uppercase tracking-wider">Outcome</p>
              <p
                className="text-sm font-semibold"
                style={{ color: getOutcomeColor(aggregates.overallOutcome) }}
              >
                {getOutcomeLabel(aggregates.overallOutcome)}
              </p>
            </div>
          </CardContent>
        </Card>
      </div>

      {caseTraces.length === 0 && (
        <p className="text-muted-foreground/70 text-xs text-center py-6">
          No traces found for this case.
        </p>
      )}

      {caseTraces.length > 0 && (
        <div className="relative pl-6">
          <div className="absolute left-[11px] top-3 bottom-3 w-px bg-border" aria-hidden="true" />

          <div className="space-y-3">
            {caseTraces.map((trace, index) => {
              const isExpanded = expandedTraceId === trace.trace_id
              const delay = getDelay(index)
              const time = new Date(trace.timestamp).toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit",
              })
              const date = new Date(trace.timestamp).toLocaleDateString([], {
                month: "short",
                day: "numeric",
              })

              return (
                <div
                  key={trace.trace_id}
                  className="relative opacity-0"
                  style={{
                    animation: `fadeSlideUp 300ms ease-out ${delay}ms forwards`,
                  }}
                >
                  <div
                    className="absolute -left-6 top-3 w-[10px] h-[10px] rounded-full border-2 border-background"
                    style={{ backgroundColor: getOutcomeColor(trace.outcome) }}
                    aria-hidden="true"
                  />

                  <div className="border rounded-md overflow-hidden transition-colors">
                    <button
                      onClick={() => handleToggleTrace(trace.trace_id)}
                      className={`flex items-center gap-2 px-3 py-2.5 text-xs w-full text-left transition-colors ${
                        isExpanded ? "bg-muted" : "hover:bg-muted"
                      }`}
                      aria-expanded={isExpanded}
                    >
                      {isExpanded ? (
                        <ChevronDown size={12} className="flex-none text-muted-foreground/70" />
                      ) : (
                        <ChevronRight size={12} className="flex-none text-muted-foreground/70" />
                      )}

                      <span className="text-muted-foreground flex-none font-mono text-2xs">
                        {date} {time}
                      </span>

                      <span className="inline-flex items-center gap-1 flex-none">
                        <TriggerIcon trigger={trace.trigger} />
                        <span className="text-2xs text-muted-foreground">
                          {getTriggerLabel(trace.trigger)}
                        </span>
                      </span>

                      <span className="inline-flex items-center gap-1 flex-none">
                        <OutcomeIcon outcome={trace.outcome} />
                        <span
                          className="text-2xs font-medium"
                          style={{ color: getOutcomeColor(trace.outcome) }}
                        >
                          {getOutcomeLabel(trace.outcome)}
                        </span>
                      </span>

                      <span className="flex-none text-muted-foreground/70 text-3xs ml-auto">
                        {trace.segment_count} segment{trace.segment_count !== 1 ? "s" : ""}
                      </span>
                    </button>

                    {isExpanded && (
                      <div className="border-t px-3 py-3 bg-card">
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
        </div>
      )}
    </div>
  )
}
