// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { getConfig } from "@/lib/config"
import type { TraceSegment } from "@/types/generated-cases"

export interface MetricPoint {
  t: string
  v: number
}

export interface MetricsSummary {
  totalCases: number
  successRate: number
  avgCostUSD: number
  avgLatencyMs: number
  source?: "traces" | "cloudwatch" // "traces" = derived from DynamoDB when CW is empty
}

export interface MetricsData {
  timeRange: { hours: number; period: number }
  summary: MetricsSummary
  casesProcessed: MetricPoint[]
  successRate: MetricPoint[]
  avgTurns: MetricPoint[]
  avgLatencyMs: MetricPoint[]
  p90LatencyMs: MetricPoint[]
  avgCostUSD: MetricPoint[]
  totalCostUSD: MetricPoint[]
  inputTokens: MetricPoint[]
  outputTokens: MetricPoint[]
  cacheReadTokens: MetricPoint[]
  cacheWriteTokens: MetricPoint[]
  byModel?: ByModelMetrics
}

/** Per-model breakdown: each key is a metric name, value is { [modelTier]: series } */
export interface ByModelMetrics {
  inputTokens: Record<string, MetricPoint[]>
  outputTokens: Record<string, MetricPoint[]>
  cacheReadTokens: Record<string, MetricPoint[]>
  cacheWriteTokens: Record<string, MetricPoint[]>
  avgLatencyMs: Record<string, MetricPoint[]>
  totalCostUSD: Record<string, MetricPoint[]>
  casesProcessed: Record<string, MetricPoint[]>
  avgTurns: Record<string, MetricPoint[]>
}

export interface LambdaHealth {
  name: string
  invocations: number
  errors: number
  status: "healthy" | "degraded" | "error" | "unknown"
}

export interface AlarmInfo {
  name: string
  state: "OK" | "ALARM" | "INSUFFICIENT_DATA"
  reason: string
}

export interface HealthData {
  lambdas: LambdaHealth[]
  queues: Record<string, { visible: number; inFlight: number }>
  alarms: AlarmInfo[]
  recentErrors?: RecentError[]
}

export interface RecentError {
  lambda: string
  timestamp: string
  message: string
}

export async function fetchMetrics(token: string, hours = 24, period = 3600): Promise<MetricsData> {
  const { apiUrl } = await getConfig()
  const res = await fetch(
    `${apiUrl}/observability/metrics?hours=${hours}&period=${period}&by_model=true`,
    { headers: { Authorization: `Bearer ${token}` } }
  )
  if (!res.ok) throw new Error(`Metrics fetch failed: ${res.status}`)
  return res.json()
}

export async function fetchHealth(token: string): Promise<HealthData> {
  const { apiUrl } = await getConfig()
  const res = await fetch(`${apiUrl}/observability/health`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error(`Health fetch failed: ${res.status}`)
  return res.json()
}

export interface TraceRecord {
  case_id: string
  document_number: string
  item_id: string
  process_type: string
  trace_id: string
  timestamp: string
  trigger: string
  outcome: string
  segment_count: number
  segments: TraceSegment[]
}

export interface TracesData {
  traces: TraceRecord[]
  total_cases_scanned: number
}

export async function fetchTraces(token: string, hours?: number): Promise<TracesData> {
  const { apiUrl } = await getConfig()
  const params = hours !== undefined ? `?hours=${hours}` : ""
  const res = await fetch(`${apiUrl}/observability/traces${params}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error(`Traces fetch failed: ${res.status}`)
  return res.json()
}
