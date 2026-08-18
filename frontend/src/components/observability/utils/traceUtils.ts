// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import type { TraceRecord, MetricPoint } from "@/services/observabilityService"
import type { TraceSegment } from "@/types/generated-cases"
// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

// Chart data-series palette. These are hex, not tokens, on purpose: they feed SVG
// `fill`/`stroke` (not className), each hue is a stated meaning (which tool ran),
// and the weights read on both grounds — the same rationale the token file gives
// for keeping `--chart-*` as raw values. Status colour still comes from statusTone.
export const TOOL_COLORS: Record<string, string> = {
  sap_read: "#3b82f6", // blue
  sap_write: "#c98003", // amber
  update_case_state: "#01a471", // green
  send_notification: "#8b5cf6", // purple
  query_knowledge_base: "#ec4899", // pink
  get_odata_spec: "#019eb8", // cyan
}

const DEFAULT_TOOL_COLOR = "#6b7280" // gray

// ---------------------------------------------------------------------------
// sortAndLimitTraces
// ---------------------------------------------------------------------------

/** Sort traces by timestamp descending and limit to N results. */
export function sortAndLimitTraces(traces: TraceRecord[], limit: number): TraceRecord[] {
  return [...traces]
    .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
    .slice(0, limit)
}

// ---------------------------------------------------------------------------
// getOutcomeColor
// ---------------------------------------------------------------------------

/** Map an outcome string to a display color. */
export function getOutcomeColor(outcome: string | undefined): string {
  switch (outcome) {
    case "complete":
      return "#01a471" // green
    case "error":
      return "#ef4444" // red
    case "cancelled":
      return "#c98003" // yellow
    default:
      return "#6b7280" // gray
  }
}
// ---------------------------------------------------------------------------
// getSegmentLabelAndColor
// ---------------------------------------------------------------------------

/**
 * Derive a human-readable label and color for a trace segment.
 *  - tool segments → tool_name label + mapped color (or gray default)
 *  - text segments → "Reasoning" label + slate color
 */
export function getSegmentLabelAndColor(segment: TraceSegment): { label: string; color: string } {
  if (segment.type === "tool") {
    const toolName = segment.tool_name ?? "unknown"
    const color = TOOL_COLORS[toolName] ?? DEFAULT_TOOL_COLOR
    return { label: toolName, color }
  }
  return { label: "Reasoning", color: "#64748b" } // slate
}

// ---------------------------------------------------------------------------
// truncateTooltipContent
// ---------------------------------------------------------------------------

/**
 * Truncate content to `maxLength` characters (default 200).
 * Appends "…" when truncated. Returns empty string for nullish input.
 */
export function truncateTooltipContent(content: unknown, maxLength = 200): string {
  if (!content) return ""
  const str = typeof content === "string" ? content : JSON.stringify(content)
  if (str.length <= maxLength) return str
  return str.slice(0, maxLength) + "…"
}

// ---------------------------------------------------------------------------
// filterTracesByCase
// ---------------------------------------------------------------------------

/**
 * Filter traces to those matching `caseId`, sorted ascending by timestamp
 * (chronological order).
 */
export function filterTracesByCase(traces: TraceRecord[], caseId: string): TraceRecord[] {
  return traces
    .filter(t => t.case_id === caseId)
    .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())
}
// ---------------------------------------------------------------------------
// computeSessionAggregates
// ---------------------------------------------------------------------------

export interface SessionAggregates {
  totalInvocations: number
  totalSegments: number
  overallOutcome: string
}

/**
 * Compute aggregate stats for a set of traces belonging to a single case.
 * `overallOutcome` is the outcome of the last trace by timestamp.
 */
export function computeSessionAggregates(traces: TraceRecord[]): SessionAggregates {
  if (traces.length === 0) {
    return { totalInvocations: 0, totalSegments: 0, overallOutcome: "" }
  }

  const totalInvocations = traces.length
  const totalSegments = traces.reduce((sum, t) => sum + t.segment_count, 0)

  const sorted = [...traces].sort(
    (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
  )
  const overallOutcome = sorted[0].outcome

  return { totalInvocations, totalSegments, overallOutcome }
}
// ---------------------------------------------------------------------------
// computeTraceStats
// ---------------------------------------------------------------------------

export interface TraceStats {
  totalTraces: number
  successRate: number
  avgSegments: number
  topTools: { name: string; count: number }[]
}

/**
 * Compute aggregate statistics across a list of traces.
 *  - successRate: fraction of traces with outcome "complete"
 *  - avgSegments: mean segment_count
 *  - topTools: tool names sorted by frequency descending
 */
export function computeTraceStats(traces: TraceRecord[]): TraceStats {
  if (traces.length === 0) {
    return { totalTraces: 0, successRate: 0, avgSegments: 0, topTools: [] }
  }

  const totalTraces = traces.length
  const completeCount = traces.filter(t => t.outcome === "complete").length
  const successRate = completeCount / totalTraces
  const avgSegments = traces.reduce((sum, t) => sum + t.segment_count, 0) / totalTraces

  const toolCounts = new Map<string, number>()
  for (const trace of traces) {
    for (const seg of trace.segments) {
      if (seg.type === "tool" && seg.tool_name) {
        toolCounts.set(seg.tool_name, (toolCounts.get(seg.tool_name) ?? 0) + 1)
      }
    }
  }

  const topTools = Array.from(toolCounts.entries())
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count)

  return { totalTraces, successRate, avgSegments, topTools }
}
// ---------------------------------------------------------------------------
// computeToolUsage
// ---------------------------------------------------------------------------

/**
 * Count tool-type segments per tool_name across all traces.
 * Returns the top `limit` tools sorted by count descending.
 */
export function computeToolUsage(
  traces: TraceRecord[],
  limit = 10
): { name: string; count: number }[] {
  const toolCounts = new Map<string, number>()
  for (const trace of traces) {
    for (const seg of trace.segments) {
      if (seg.type === "tool" && seg.tool_name) {
        toolCounts.set(seg.tool_name, (toolCounts.get(seg.tool_name) ?? 0) + 1)
      }
    }
  }

  return Array.from(toolCounts.entries())
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, limit)
}

// ---------------------------------------------------------------------------
// filterErrorTraces
// ---------------------------------------------------------------------------

/**
 * Filter traces to only those with "error" or "cancelled" outcomes.
 */
export function filterErrorTraces(traces: TraceRecord[]): TraceRecord[] {
  return traces.filter(t => t.outcome === "error" || t.outcome === "cancelled")
}
// ---------------------------------------------------------------------------
// computeTokenPercentages
// ---------------------------------------------------------------------------

export interface TokenPercentages {
  input: number
  output: number
  cacheRead: number
}

/**
 * Compute percentage breakdown for token categories.
 * Returns 0 for all if total is 0.
 */
export function computeTokenPercentages(
  input: number,
  output: number,
  cacheRead: number
): TokenPercentages {
  const total = input + output + cacheRead
  if (total === 0) {
    return { input: 0, output: 0, cacheRead: 0 }
  }
  return {
    input: (input / total) * 100,
    output: (output / total) * 100,
    cacheRead: (cacheRead / total) * 100,
  }
}

// ---------------------------------------------------------------------------
// findNearestPoint
// ---------------------------------------------------------------------------

/**
 * Find the MetricPoint whose mapped X coordinate is nearest to `queryX`.
 * Points are evenly distributed across `width` (index-based mapping).
 * Returns the first point if `data` has 0 or 1 elements; callers should guard against an empty array.
 */
export function findNearestPoint(data: MetricPoint[], queryX: number, width: number): MetricPoint {
  if (data.length <= 1) {
    return data[0]
  }

  let nearest = data[0]
  let minDist = Infinity

  for (let i = 0; i < data.length; i++) {
    const x = data.length === 1 ? width : (i / (data.length - 1)) * width
    const dist = Math.abs(x - queryX)
    if (dist < minDist) {
      minDist = dist
      nearest = data[i]
    }
  }

  return nearest
}
