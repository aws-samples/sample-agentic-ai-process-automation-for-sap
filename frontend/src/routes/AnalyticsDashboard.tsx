// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useState, useRef, useMemo } from "react"
import { useQuery } from "@tanstack/react-query"
import { useAuth } from "react-oidc-context"
import { useFreshToken } from "@/hooks/useFreshToken"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { StatusBadge, StatusDot } from "@/components/ui/status-badge"
import {
  Banner,
  EmptyState,
  PageBody,
  PageHeader,
  PageLoader,
  StatMetric,
} from "@/components/ui/page-chrome"
import { TONE_TEXT, type StatusTone } from "@/lib/statusTone"
import {
  fetchMetrics,
  fetchHealth,
  fetchTraces,
  type MetricPoint,
  type ByModelMetrics,
} from "@/services/observabilityService"
import {
  findNearestPoint,
  computeTokenPercentages,
} from "@/components/observability/utils/traceUtils"
import { useStaggeredEntrance } from "@/components/observability/hooks/useStaggeredEntrance"
import TracesPanel from "@/components/observability/TracesPanel"
import ToolUsageChart from "@/components/observability/ToolUsageChart"
import { PeriodBriefing } from "@/components/PeriodBriefing"
import { AGENT_PULSE_KEY } from "@/components/AgentHeartbeat"
import { fetchCases } from "@/services/casesService"
import { WINDOWS } from "@/lib/digest"
import "@/components/observability/observability-animations.css"

function Sparkline({
  data,
  color = "#3b82f6",
  height = 40,
  width = 160,
}: {
  data: MetricPoint[]
  color?: string
  height?: number
  width?: number
}) {
  const [tooltip, setTooltip] = useState<{
    x: number
    y: number
    value: number
    time: string
  } | null>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const pathRef = useRef<SVGPolylineElement>(null)
  const [pathLength, setPathLength] = useState(1000)

  // Compute path length after mount for accurate stroke-dasharray animation
  useEffect(() => {
    if (pathRef.current) {
      const len = pathRef.current.getTotalLength()
      setPathLength(len)
    }
  }, [data, width, height])

  if (data.length < 2) {
    return (
      <div
        style={{ width, height }}
        className="flex items-center justify-center text-xs text-muted-foreground/60"
      >
        No data
      </div>
    )
  }

  const values = data.map(d => d.v)
  const max = Math.max(...values, 1)
  const min = Math.min(...values, 0)
  const range = max - min || 1

  const points = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * width
      const y = height - ((v - min) / range) * (height - 4) - 2
      return `${x},${y}`
    })
    .join(" ")

  const areaPoints = `0,${height} ${points} ${width},${height}`
  const gradId = `grad-${color.replace("#", "")}-${width}-${height}`
  const lastY = height - ((values[values.length - 1] - min) / range) * (height - 4) - 2

  const handleMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!svgRef.current || data.length === 0) return
    const rect = svgRef.current.getBoundingClientRect()
    const queryX = ((e.clientX - rect.left) / rect.width) * width
    const nearest = findNearestPoint(data, queryX, width)
    if (!nearest) return
    const idx = data.indexOf(nearest)
    const x = idx >= 0 ? (idx / (data.length - 1)) * width : queryX
    const y = height - ((nearest.v - min) / range) * (height - 4) - 2
    setTooltip({
      x,
      y,
      value: nearest.v,
      time: new Date(nearest.t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    })
  }

  const handleMouseLeave = () => setTooltip(null)

  return (
    <svg
      ref={svgRef}
      width={width}
      height={height}
      className="overflow-visible"
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
    >
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.3" />
          <stop offset="100%" stopColor={color} stopOpacity="0.02" />
        </linearGradient>
      </defs>
      {/* Gradient fill area — fades in after line drawing completes */}
      <polygon
        points={areaPoints}
        fill={`url(#${gradId})`}
        opacity="0"
        style={{
          animation: `fadeIn 400ms ease-out 900ms forwards`,
        }}
      />
      <polyline
        ref={pathRef}
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeDasharray={pathLength}
        strokeDashoffset={pathLength}
        style={{
          animation: `drawLine 900ms ease-out forwards`,
        }}
      />
      <circle cx={width} cy={lastY} r="3" fill={color}>
        <animate attributeName="r" values="2;3;4;3;2" dur="2s" repeatCount="indefinite" />
        <animate attributeName="opacity" values="1;1;0.6;1;1" dur="2s" repeatCount="indefinite" />
      </circle>
      {tooltip && (
        <g>
          <circle cx={tooltip.x} cy={tooltip.y} r="4" fill={color} opacity="0.8" />
          <rect
            x={tooltip.x - 30}
            y={tooltip.y - 28}
            width="60"
            height="20"
            rx="4"
            className="fill-foreground"
            opacity="0.9"
          />
          <text
            x={tooltip.x}
            y={tooltip.y - 15}
            textAnchor="middle"
            className="fill-background"
            fontSize="9"
            fontFamily="ui-monospace, monospace"
          >
            {tooltip.value.toFixed(1)} · {tooltip.time}
          </text>
        </g>
      )}
    </svg>
  )
}

function BarChart({
  data,
  color = "#3b82f6",
  height = 80,
}: {
  data: MetricPoint[]
  color?: string
  height?: number
}) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null)

  if (data.length === 0) {
    return (
      <div
        style={{ height }}
        className="flex items-center justify-center text-xs text-muted-foreground/60"
      >
        No data
      </div>
    )
  }

  const max = Math.max(...data.map(d => d.v), 1)

  return (
    <div className="flex items-end gap-0.5 w-full" style={{ height }}>
      {data.map((d, i) => {
        const barH = (d.v / max) * height
        const isHovered = hoveredIndex === i
        return (
          <div
            key={i}
            className="flex-1 rounded-t group relative"
            style={{
              height: barH,
              backgroundColor: color,
              opacity:
                hoveredIndex === null ? 0.7 + (i / data.length) * 0.3 : isHovered ? 1.0 : 0.4,
              transformOrigin: "bottom",
              animation: `growBar 500ms ease-out ${i * 40}ms both`,
              transition: "opacity 200ms ease",
            }}
            onMouseEnter={() => setHoveredIndex(i)}
            onMouseLeave={() => setHoveredIndex(null)}
          >
            <div className="absolute -top-7 left-1/2 -translate-x-1/2 bg-foreground text-background text-3xs px-1.5 py-0.5 rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none z-10">
              {d.v.toFixed(1)} ·{" "}
              {new Date(d.t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            </div>
          </div>
        )
      })}
    </div>
  )
}

/**
 * Lambda health and CloudWatch alarm states, which are two vocabularies for the
 * same three outcomes, folded onto the shared tone set. Unknown states read as
 * neutral rather than green — absent data is not good news.
 */
const HEALTH_TONE: Record<string, StatusTone> = {
  healthy: "success",
  OK: "success",
  degraded: "progress",
  error: "danger",
  ALARM: "danger",
  unknown: "neutral",
  INSUFFICIENT_DATA: "neutral",
}

export function healthTone(status: string): StatusTone {
  return HEALTH_TONE[status] ?? "neutral"
}

/** Status dot that pings while something is actually wrong. */
function HealthDot({ status }: { status: string }) {
  const tone = healthTone(status)
  return (
    <span className="relative flex h-2.5 w-2.5 items-center justify-center">
      {tone === "danger" && (
        <StatusDot
          tone={tone}
          className="absolute h-full w-full opacity-75 motion-safe:animate-ping"
        />
      )}
      <StatusDot tone={tone} className="relative h-2.5 w-2.5" />
    </span>
  )
}

/** Live indicator: auto-refresh is on and there is traffic to refresh. */
function PulseRing({ active }: { active: boolean }) {
  if (!active) return null
  return (
    <span className="relative flex h-2.5 w-2.5 items-center justify-center" title="Live">
      <StatusDot
        tone="success"
        className="absolute h-full w-full opacity-75 motion-safe:animate-ping"
      />
      <StatusDot tone="success" className="relative h-2.5 w-2.5" />
    </span>
  )
}

function RefreshProgressBar({ active }: { active: boolean }) {
  if (!active) return null
  return (
    <div className="w-full h-0.5 bg-muted overflow-hidden">
      <div
        className="h-full w-1/3 bg-agent rounded"
        style={{ animation: "progressShimmer 1.2s ease-in-out infinite" }}
      />
    </div>
  )
}

/**
 * One colour per model tier, shared by the donut and the breakdown legend — the
 * two used to carry separate ramps, so the same tier was a different colour in
 * each. Values clear 3:1 on both the light and dark card.
 */
const MODEL_COLORS: Record<string, string> = {
  sonnet: "#8b5cf6",
  haiku: "#019eb8",
  unknown: "#6b7280",
}

function TokenDonut({
  input,
  output,
  cacheRead,
  byModel,
}: {
  input: number
  output: number
  cacheRead: number
  byModel?: ByModelMetrics
}) {
  const [hoveredSegment, setHoveredSegment] = useState<string | null>(null)

  // Build segments: per-model if available, otherwise aggregate
  const tiers = byModel ? Object.keys(byModel.inputTokens ?? {}).sort() : []
  const hasModelData = tiers.length > 0

  type Seg = {
    key: string
    label: string
    color: string
    count: number
    pct: number
    delay: string
  }

  let segments: Seg[]
  let total: number

  if (hasModelData && byModel) {
    // Per-model segments: each tier gets input+output+cache as one slice
    const tierTotals = tiers.map(tier => {
      const inp = sumSeries(byModel.inputTokens?.[tier] ?? [])
      const out = sumSeries(byModel.outputTokens?.[tier] ?? [])
      const cache = sumSeries(byModel.cacheReadTokens?.[tier] ?? [])
      return { tier, total: inp + out + cache, inp, out, cache }
    })
    total = tierTotals.reduce((a, t) => a + t.total, 0) || 1
    segments = tierTotals.map((t, i) => ({
      key: t.tier,
      label: t.tier,
      color: MODEL_COLORS[t.tier] ?? MODEL_COLORS.unknown,
      count: t.total,
      pct: (t.total / total) * 100,
      delay: `${i * 0.5}s`,
    }))
  } else {
    total = input + output + cacheRead || 1
    const percentages = computeTokenPercentages(input, output, cacheRead)
    segments = [
      {
        key: "input",
        label: "Input",
        color: "#3b82f6",
        count: input,
        pct: percentages.input,
        delay: "0s",
      },
      {
        key: "output",
        label: "Output",
        color: "#c98003",
        count: output,
        pct: percentages.output,
        delay: "0.5s",
      },
      {
        key: "cache",
        label: "Cache",
        color: "#01a471",
        count: cacheRead,
        pct: percentages.cacheRead,
        delay: "1.0s",
      },
    ]
  }

  const circumference = 2 * Math.PI * 30
  let offset = 0

  return (
    <div className="flex items-center gap-4">
      <div className="relative">
        <svg width="80" height="80" viewBox="0 0 80 80">
          <circle cx="40" cy="40" r="30" fill="none" className="stroke-border" strokeWidth="8" />
          {segments.map(seg => {
            const dashLen = (seg.pct / 100) * circumference
            const segOffset = -offset
            offset += dashLen
            const isHovered = hoveredSegment === seg.key
            const hoverOffset = isHovered ? 3 : 0
            return (
              <circle
                key={seg.key}
                cx="40"
                cy="40"
                r={30 + hoverOffset}
                fill="none"
                stroke={seg.color}
                strokeWidth="8"
                strokeDasharray={`${dashLen} ${circumference}`}
                strokeDashoffset={`${segOffset}`}
                transform="rotate(-90 40 40)"
                style={{
                  transition: "r 200ms ease, stroke-width 200ms ease",
                  cursor: "pointer",
                }}
                onMouseEnter={() => setHoveredSegment(seg.key)}
                onMouseLeave={() => setHoveredSegment(null)}
              >
                <animate
                  attributeName="stroke-dasharray"
                  from={`0 ${circumference}`}
                  to={`${dashLen} ${circumference}`}
                  dur="0.5s"
                  begin={seg.delay}
                  fill="freeze"
                />
              </circle>
            )
          })}
          <text
            x="40"
            y="40"
            textAnchor="middle"
            dominantBaseline="central"
            className="text-3xs fill-muted-foreground"
          >
            {(total / 1000).toFixed(0)}K
          </text>
        </svg>
        {hoveredSegment &&
          (() => {
            const seg = segments.find(s => s.key === hoveredSegment)
            if (!seg) return null
            return (
              <div className="absolute -top-8 left-1/2 -translate-x-1/2 bg-foreground text-background text-3xs px-2 py-1 rounded shadow-lg whitespace-nowrap pointer-events-none z-10">
                {seg.label}: {(seg.count / 1000).toFixed(1)}K ({seg.pct.toFixed(1)}%)
              </div>
            )
          })()}
      </div>
      {/* Swatches read from the segment, so a legend dot can never disagree with
          the arc it labels. */}
      <div className="text-xs space-y-1">
        {segments.map(seg => (
          <div key={seg.key} className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: seg.color }} />
            <span className={hasModelData ? "font-mono" : undefined}>{seg.label}</span>:{" "}
            {(seg.count / 1000).toFixed(1)}K
          </div>
        ))}
      </div>
    </div>
  )
}

function sumSeries(points: MetricPoint[]): number {
  return points.reduce((a, p) => a + p.v, 0)
}

function ModelBreakdown({ byModel }: { byModel: ByModelMetrics }) {
  const tiers = useMemo(() => {
    const all = new Set<string>()
    for (const metric of Object.values(byModel)) {
      for (const tier of Object.keys(metric)) all.add(tier)
    }
    return Array.from(all).sort()
  }, [byModel])

  if (tiers.length === 0) {
    return (
      <Card className="p-4">
        <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
          Model Breakdown
        </h3>
        <EmptyState message="No per-model data available" className="px-0 py-4" />
      </Card>
    )
  }

  const tierStats = tiers.map(tier => ({
    tier,
    color: MODEL_COLORS[tier] ?? MODEL_COLORS.unknown,
    inputTokens: sumSeries(byModel.inputTokens?.[tier] ?? []),
    outputTokens: sumSeries(byModel.outputTokens?.[tier] ?? []),
    cacheReadTokens: sumSeries(byModel.cacheReadTokens?.[tier] ?? []),
    cost: sumSeries(byModel.totalCostUSD?.[tier] ?? []),
    cases: sumSeries(byModel.casesProcessed?.[tier] ?? []),
    avgLatency: (() => {
      const pts = byModel.avgLatencyMs?.[tier] ?? []
      return pts.length > 0 ? pts.reduce((a, p) => a + p.v, 0) / pts.length : 0
    })(),
    avgTurns: (() => {
      const pts = byModel.avgTurns?.[tier] ?? []
      return pts.length > 0 ? pts.reduce((a, p) => a + p.v, 0) / pts.length : 0
    })(),
  }))

  const totalTokens = tierStats.reduce(
    (a, t) => a + t.inputTokens + t.outputTokens + t.cacheReadTokens,
    0
  )
  const totalCost = tierStats.reduce((a, t) => a + t.cost, 0)
  const totalCases = tierStats.reduce((a, t) => a + t.cases, 0)

  const rows = [
    {
      label: "Tokens",
      values: tierStats.map(t => t.inputTokens + t.outputTokens + t.cacheReadTokens),
      total: totalTokens,
      fmt: (v: number) => `${(v / 1000).toFixed(1)}K`,
    },
    {
      label: "Cost",
      values: tierStats.map(t => t.cost),
      total: totalCost,
      fmt: (v: number) => `$${v.toFixed(4)}`,
    },
    {
      label: "Cases",
      values: tierStats.map(t => t.cases),
      total: totalCases,
      fmt: (v: number) => `${v}`,
    },
  ]

  return (
    <Card className="p-4">
      <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
        Model Breakdown
      </h3>

      <div className="flex items-center gap-4 mb-4">
        {tierStats.map(t => (
          <div key={t.tier} className="flex items-center gap-1.5 text-xs">
            <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: t.color }} />
            <span className="font-mono font-medium">{t.tier}</span>
            <span className="text-muted-foreground/70">({t.cases} cases)</span>
          </div>
        ))}
      </div>

      <div className="space-y-3">
        {rows.map(row => (
          <div key={row.label}>
            <div className="flex items-center justify-between mb-1">
              <span className="text-3xs text-muted-foreground uppercase tracking-wider">
                {row.label}
              </span>
              <span className="text-3xs text-muted-foreground/70 font-mono">
                {row.fmt(row.total)}
              </span>
            </div>
            <div className="flex h-5 rounded overflow-hidden bg-muted">
              {tierStats.map((t, i) => {
                const pct = row.total > 0 ? (row.values[i] / row.total) * 100 : 0
                if (pct === 0) return null
                return (
                  <div
                    key={t.tier}
                    className="h-full relative group"
                    style={{
                      width: `${pct}%`,
                      backgroundColor: t.color,
                      opacity: 0.85,
                    }}
                  >
                    <div className="absolute -top-7 left-1/2 -translate-x-1/2 bg-foreground text-background text-3xs px-2 py-0.5 rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none z-10">
                      {t.tier}: {row.fmt(row.values[i])} ({pct.toFixed(1)}%)
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-4 border-t pt-3">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-3xs text-muted-foreground/70 uppercase tracking-wider">
              <th className="text-left font-medium pb-1">Model</th>
              <th className="text-right font-medium pb-1">Input</th>
              <th className="text-right font-medium pb-1">Output</th>
              <th className="text-right font-medium pb-1">Cache</th>
              <th className="text-right font-medium pb-1">Avg Latency</th>
              <th className="text-right font-medium pb-1">Avg Turns</th>
              <th className="text-right font-medium pb-1">Cost</th>
            </tr>
          </thead>
          <tbody>
            {tierStats.map(t => (
              <tr key={t.tier} className="border-t border-border">
                <td className="py-1.5 font-mono font-medium flex items-center gap-1.5">
                  <span
                    className="w-2 h-2 rounded-full inline-block"
                    style={{ backgroundColor: t.color }}
                  />
                  {t.tier}
                </td>
                <td className="text-right text-muted-foreground tabular-nums">
                  {(t.inputTokens / 1000).toFixed(1)}K
                </td>
                <td className="text-right text-muted-foreground tabular-nums">
                  {(t.outputTokens / 1000).toFixed(1)}K
                </td>
                <td className="text-right text-muted-foreground tabular-nums">
                  {(t.cacheReadTokens / 1000).toFixed(1)}K
                </td>
                <td className="text-right text-muted-foreground tabular-nums">
                  {(t.avgLatency / 1000).toFixed(1)}s
                </td>
                <td className="text-right text-muted-foreground tabular-nums">
                  {t.avgTurns.toFixed(1)}
                </td>
                <td className="text-right text-muted-foreground tabular-nums">
                  ${t.cost.toFixed(4)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

/** Auto-refresh interval for metrics, health, and traces (ms). */
const AUTO_REFRESH_MS = 30_000

export default function AnalyticsDashboard() {
  const auth = useAuth()
  const getFreshTokens = useFreshToken()

  const [hours, setHours] = useState("24")
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null)
  const [timestampFlash, setTimestampFlash] = useState(false)

  const hasAnimated = useRef(false)

  const [isMobile, setIsMobile] = useState(false)
  useEffect(() => {
    const checkMobile = () => setIsMobile(window.innerWidth < 768)
    checkMobile()
    window.addEventListener("resize", checkMobile)
    return () => window.removeEventListener("resize", checkMobile)
  }, [])

  const refetchInterval = autoRefresh ? AUTO_REFRESH_MS : false

  const metricsQuery = useQuery({
    queryKey: ["metrics", hours],
    queryFn: async () => {
      const { idToken } = await getFreshTokens()
      if (!idToken) throw new Error("Not authenticated")
      return fetchMetrics(idToken, parseInt(hours))
    },
    enabled: auth.isAuthenticated,
    refetchInterval,
  })
  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: async () => {
      const { idToken } = await getFreshTokens()
      if (!idToken) throw new Error("Not authenticated")
      return fetchHealth(idToken)
    },
    enabled: auth.isAuthenticated,
    refetchInterval,
  })
  // Loads independently — must not block metrics/health rendering
  const tracesQuery = useQuery({
    queryKey: ["traces", hours],
    queryFn: async () => {
      const { idToken } = await getFreshTokens()
      if (!idToken) throw new Error("Not authenticated")
      return fetchTraces(idToken, parseInt(hours))
    },
    enabled: auth.isAuthenticated,
    refetchInterval,
  })
  // The briefing is over cases, which metrics do not carry. Reads the rail's cache entry
  // rather than starting a second scan of the same table, and takes no `hours` in the key:
  // the window is applied by the digest, so widening it re-derives instead of refetching.
  const casesQuery = useQuery({
    queryKey: AGENT_PULSE_KEY,
    queryFn: async () => {
      const { idToken } = await getFreshTokens()
      if (!idToken) throw new Error("Not authenticated")
      return fetchCases({}, idToken)
    },
    enabled: auth.isAuthenticated,
  })

  const metrics = metricsQuery.data ?? null
  const health = healthQuery.data ?? null
  const traces = tracesQuery.data ?? null
  const loading = metricsQuery.isLoading || healthQuery.isLoading
  const error =
    metricsQuery.error instanceof Error
      ? metricsQuery.error.message
      : healthQuery.error instanceof Error
        ? healthQuery.error.message
        : null
  const tracesLoading = tracesQuery.isLoading
  const tracesError = tracesQuery.error instanceof Error ? tracesQuery.error.message : null
  const isRefreshing = metricsQuery.isFetching || healthQuery.isFetching

  const lambdaCount = health?.lambdas?.length ?? 0
  const { getDelay: getLambdaDelay } = useStaggeredEntrance(lambdaCount, 0, 50)

  const { getDelay: getSummaryDelay } = useStaggeredEntrance(4, 0, 100)

  // Previous queue depths for flash detection
  const prevQueues = useRef<Record<string, number>>({})

  const dataUpdatedAt = metricsQuery.dataUpdatedAt
  useEffect(() => {
    if (!dataUpdatedAt) return
    setLastRefresh(new Date(dataUpdatedAt))
    setTimestampFlash(true)
    const timer = setTimeout(() => setTimestampFlash(false), 600)
    return () => clearTimeout(timer)
  }, [dataUpdatedAt])

  // Mark entrance animations as complete after first data load
  useEffect(() => {
    if (metrics && !hasAnimated.current) {
      const timer = setTimeout(() => {
        hasAnimated.current = true
      }, 1200)
      return () => clearTimeout(timer)
    }
  }, [metrics])

  const s = metrics?.summary
  const hasActivity = (s?.totalCases ?? 0) > 0

  // Sum latest token values for donut
  const latestInput = metrics?.inputTokens?.reduce((a, p) => a + p.v, 0) ?? 0
  const latestOutput = metrics?.outputTokens?.reduce((a, p) => a + p.v, 0) ?? 0
  const latestCache = metrics?.cacheReadTokens?.reduce((a, p) => a + p.v, 0) ?? 0

  // Detect queue depth increases for flash effect
  const queueEntries = useMemo(() => Object.entries(health?.queues ?? {}), [health?.queues])
  const queueFlashKeys = useMemo(() => {
    const flashing = new Set<string>()
    for (const [label, q] of queueEntries) {
      const prev = prevQueues.current[label] ?? 0
      if (q.visible > 0 && q.visible > prev) {
        flashing.add(label)
      }
      prevQueues.current[label] = q.visible
    }
    return flashing
  }, [queueEntries])

  const getEntranceStyle = (baseDelay: number) => {
    if (hasAnimated.current) return {}
    return {
      opacity: 0,
      animation: `fadeSlideUp 400ms ease-out ${baseDelay}ms forwards`,
    }
  }

  // Entrance delay tiers:
  // Summary tiles: 0–400ms
  // Chart row: starts at 300ms
  // Health grid + traces + cost: starts at 600ms
  const CHART_ROW_BASE = 300
  const BOTTOM_ROW_BASE = 600

  const handleManualRefresh = () => {
    metricsQuery.refetch()
    healthQuery.refetch()
    tracesQuery.refetch()
  }

  return (
    <>
      <PageHeader
        title="Analytics"
        actions={
          <>
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={e => setAutoRefresh(e.target.checked)}
                className="rounded border-input"
              />
              Auto-refresh
            </label>
            <Select value={hours} onValueChange={setHours}>
              <SelectTrigger className="w-28 h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {WINDOWS.map(w => (
                  <SelectItem key={w.value} value={w.value}>
                    {w.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button variant="outline" size="sm" className="h-8" onClick={handleManualRefresh}>
              Refresh
            </Button>
          </>
        }
      >
        <PulseRing active={autoRefresh && hasActivity} />
        <span
          className="rounded px-1 text-xs text-muted-foreground transition-colors"
          style={timestampFlash ? { animation: "flashHighlight 600ms ease-out" } : undefined}
        >
          {lastRefresh ? `Updated ${lastRefresh.toLocaleTimeString()}` : "Loading..."}
        </span>
      </PageHeader>

      {/* Thin progress bar during refresh */}
      <RefreshProgressBar active={isRefreshing} />

      {error && (
        <Banner tone="danger" className="mx-6 mt-3">
          {error}
        </Banner>
      )}

      <PageBody className="grow space-y-6">
        {/* Outside the metrics loading branch on purpose: the period's outcome is the
            first thing the page owes the reader, and it comes from cases, which load
            independently of the chart data. */}
        <PeriodBriefing cases={casesQuery.data ?? []} hours={hours} known={casesQuery.isSuccess} />

        {loading && !metrics ? (
          <PageLoader label="Loading metrics…" />
        ) : (
          <>
            {/* Row 1: Summary tiles + staggered entrance */}
            {s?.source === "traces" && (
              <Banner tone="progress" className="rounded-md border-l-4 text-xs">
                Metrics derived from trace data — CloudWatch agent metrics not available for this
                period
              </Banner>
            )}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {[
                {
                  label: "Cases (24h)",
                  value: s?.totalCases ?? 0,
                  decimals: 0,
                  prefix: "",
                  suffix: "",
                  data: metrics?.casesProcessed ?? [],
                  color: "#3b82f6",
                },
                {
                  label: "Success Rate",
                  value: s?.successRate ?? 0,
                  decimals: 1,
                  prefix: "",
                  suffix: "%",
                  data: metrics?.successRate ?? [],
                  color: "#01a471",
                },
                {
                  label: "Avg Cost",
                  value: s?.avgCostUSD ?? 0,
                  decimals: 3,
                  prefix: "$",
                  suffix: "",
                  data: metrics?.avgCostUSD ?? [],
                  color: "#c98003",
                },
                {
                  label: "Avg Latency",
                  value: (s?.avgLatencyMs ?? 0) / 1000,
                  decimals: 1,
                  prefix: "",
                  suffix: "s",
                  data: metrics?.avgLatencyMs ?? [],
                  color: "#8b5cf6",
                },
              ].map((tile, i) => (
                <Card key={tile.label} className="p-4">
                  <StatMetric
                    label={tile.label}
                    // Landed, not ramped: a count-up shows a number that is not the
                    // figure for most of its run, and these are read against SAP.
                    value={`${tile.prefix}${tile.value.toFixed(tile.decimals)}${tile.suffix}`}
                    chart={
                      <Sparkline data={tile.data} color={tile.color} width={120} height={30} />
                    }
                    style={
                      !hasAnimated.current
                        ? {
                            opacity: 0,
                            animation: `fadeSlideUp 400ms ease-out ${getSummaryDelay(i)}ms forwards`,
                          }
                        : undefined
                    }
                  />
                </Card>
              ))}
            </div>

            {/* Row 2: Charts — entrance starts after summary tiles */}
            <div
              className="grid grid-cols-1 md:grid-cols-3 gap-4"
              style={getEntranceStyle(CHART_ROW_BASE)}
            >
              <Card className="p-4">
                <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
                  Cases Over Time
                </h3>
                <BarChart data={metrics?.casesProcessed ?? []} color="#3b82f6" height={100} />
              </Card>
              <Card className="p-4">
                <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
                  Latency (avg vs p90)
                </h3>
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="text-3xs text-muted-foreground/70 w-8">avg</span>
                    <Sparkline
                      data={metrics?.avgLatencyMs ?? []}
                      color="#8b5cf6"
                      width={200}
                      height={35}
                    />
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-3xs text-muted-foreground/70 w-8">p90</span>
                    <Sparkline
                      data={metrics?.p90LatencyMs ?? []}
                      color="#ec4899"
                      width={200}
                      height={35}
                    />
                  </div>
                </div>
              </Card>
              <Card className="p-4">
                <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
                  Token Usage
                </h3>
                <TokenDonut
                  input={latestInput}
                  output={latestOutput}
                  cacheRead={latestCache}
                  byModel={metrics?.byModel}
                />
              </Card>
            </div>

            {/* Row 2.5: Model Breakdown — per-model token/cost/latency split */}
            <div style={getEntranceStyle(CHART_ROW_BASE + 150)}>
              {metrics?.byModel && Object.keys(metrics.byModel.inputTokens ?? {}).length > 0 ? (
                <ModelBreakdown byModel={metrics.byModel} />
              ) : (
                <Card className="p-4">
                  <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
                    Model Breakdown
                  </h3>
                  <EmptyState
                    message="No per-model metrics yet."
                    hint="Tokens, cost, and latency by model tier appear here once agent cases are processed."
                    className="px-0 py-4"
                  />
                </Card>
              )}
            </div>

            {/* Row 3: Infrastructure health — entrance starts after chart row */}
            <div
              className="grid grid-cols-1 md:grid-cols-2 gap-4"
              style={getEntranceStyle(BOTTOM_ROW_BASE)}
            >
              {/* Lambda health with staggered row entrance */}
              <Card className="p-4">
                <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
                  Lambda Functions
                </h3>
                <div className="space-y-2">
                  {(health?.lambdas ?? []).map((fn, idx) => (
                    <div
                      key={fn.name}
                      className="flex items-center justify-between py-1.5 border-b border-border last:border-0"
                      style={
                        !hasAnimated.current
                          ? {
                              opacity: 0,
                              animation: `fadeSlideUp 300ms ease-out ${BOTTOM_ROW_BASE + getLambdaDelay(idx)}ms forwards`,
                            }
                          : undefined
                      }
                    >
                      <div className="flex items-center gap-2">
                        <HealthDot status={fn.status} />
                        <span className="text-sm font-mono">{fn.name}</span>
                      </div>
                      <div className="flex items-center gap-3 text-xs text-muted-foreground">
                        <span>{fn.invocations} invocations</span>
                        {fn.errors > 0 && (
                          <span className={`font-medium ${TONE_TEXT.danger}`}>
                            {fn.errors} errors
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                  {(health?.lambdas ?? []).length === 0 && (
                    <EmptyState message="No Lambda data available" className="px-0 py-4" />
                  )}
                </div>
              </Card>

              {/* Queues + Alarms with queue flash */}
              <Card className="p-4">
                <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
                  Queues & Alarms
                </h3>

                <div className="space-y-3 mb-4">
                  {queueEntries.map(([label, q]) => (
                    <div
                      key={label}
                      className="flex items-center justify-between rounded px-1 -mx-1"
                      style={
                        queueFlashKeys.has(label)
                          ? { animation: "queueFlash 800ms ease-out" }
                          : undefined
                      }
                    >
                      <div className="flex items-center gap-2">
                        <HealthDot
                          status={label === "dlq" && q.visible > 0 ? "error" : "healthy"}
                        />
                        <span className="text-sm font-mono">
                          {label === "dlq" ? "Dead Letter Queue" : "Agent Queue"}
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-muted-foreground">{q.visible} pending</span>
                        {q.inFlight > 0 && (
                          <span className="text-xs text-agent">{q.inFlight} in-flight</span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>

                <h4 className="text-3xs font-medium text-muted-foreground/70 uppercase tracking-wider mb-2">
                  CloudWatch Alarms
                </h4>
                <div className="space-y-2">
                  {(health?.alarms ?? []).map(alarm => (
                    <div
                      key={alarm.name}
                      className="flex items-center justify-between py-1 border-b border-border last:border-0"
                    >
                      <div className="flex items-center gap-2">
                        <HealthDot status={alarm.state} />
                        <span className="text-xs">{alarm.name}</span>
                      </div>
                      <StatusBadge label={alarm.state} tone={healthTone(alarm.state)} />
                    </div>
                  ))}
                  {(health?.alarms ?? []).length === 0 && (
                    <EmptyState message="No alarms configured" className="px-0 py-4" />
                  )}
                </div>
              </Card>
            </div>

            {/* Recent Errors — surfaces Lambda errors directly on the dashboard */}
            {(health?.recentErrors ?? []).length > 0 && (
              <Card
                className="p-4 border-l-4 border-l-red-500"
                style={getEntranceStyle(BOTTOM_ROW_BASE + 50)}
              >
                <h3 className="text-xs font-medium text-red-700 dark:text-red-400 uppercase tracking-wider mb-3 flex items-center gap-1.5">
                  <span className="relative flex h-2 w-2">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75" />
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-red-500" />
                  </span>
                  Recent Errors ({health?.recentErrors?.length ?? 0})
                </h3>
                <div className="space-y-2 max-h-48 overflow-auto">
                  {(health?.recentErrors ?? []).map((err, i) => (
                    <div
                      key={i}
                      className="text-xs border rounded-md p-2 bg-red-50/50 dark:bg-red-400/10"
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-mono font-medium text-red-700 dark:text-red-300">
                          {err.lambda}
                        </span>
                        <span className="text-muted-foreground/70">
                          {new Date(err.timestamp).toLocaleTimeString([], {
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </span>
                      </div>
                      <p className="text-muted-foreground font-mono text-2xs break-all">
                        {err.message}
                      </p>
                    </div>
                  ))}
                </div>
              </Card>
            )}

            {/* Row 4: Traces Panel + Tool Usage — entrance after health grid */}
            <div
              className="grid grid-cols-1 md:grid-cols-3 gap-4"
              style={getEntranceStyle(BOTTOM_ROW_BASE + 100)}
            >
              <div className="md:col-span-2">
                {tracesError ? (
                  <Card className="p-4">
                    <Banner tone="danger">{tracesError}</Banner>
                  </Card>
                ) : (
                  <TracesPanel
                    traces={traces?.traces ?? []}
                    loading={tracesLoading}
                    isMobile={isMobile}
                  />
                )}
              </div>
              <div>
                <ToolUsageChart traces={traces?.traces ?? []} />
              </div>
            </div>

            {/* Row 5: Cost breakdown — entrance after traces */}
            <Card className="p-4" style={getEntranceStyle(BOTTOM_ROW_BASE + 200)}>
              <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
                Cost Over Time (USD)
              </h3>
              <BarChart data={metrics?.totalCostUSD ?? []} color="#c98003" height={80} />
            </Card>
          </>
        )}
      </PageBody>
    </>
  )
}
