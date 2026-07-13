// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

"use client"

import { useEffect, useState, useCallback, useRef, useMemo } from "react"
import { useAuth } from "react-oidc-context"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  fetchMetrics,
  fetchHealth,
  fetchTraces,
  type MetricsData,
  type HealthData,
  type MetricPoint,
  type TracesData,
  type ByModelMetrics,
} from "@/services/observabilityService"
import {
  findNearestPoint,
  computeTokenPercentages,
} from "@/components/observability/utils/traceUtils"
import { useStaggeredEntrance } from "@/components/observability/hooks/useStaggeredEntrance"
import TracesPanel from "@/components/observability/TracesPanel"
import ToolUsageChart from "@/components/observability/ToolUsageChart"
import "@/components/observability/observability-animations.css"

function AnimatedNumber({
  value,
  decimals = 0,
  prefix = "",
  suffix = "",
}: {
  value: number
  decimals?: number
  prefix?: string
  suffix?: string
}) {
  const [display, setDisplay] = useState(0)

  useEffect(() => {
    const duration = 800
    const start = display
    const diff = value - start
    const startTime = performance.now()

    function tick(now: number) {
      const elapsed = now - startTime
      const progress = Math.min(elapsed / duration, 1)
      const eased = 1 - Math.pow(1 - progress, 3) // ease-out cubic
      setDisplay(start + diff * eased)
      if (progress < 1) requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  }, [value])

  return (
    <span className="tabular-nums">
      {prefix}
      {display.toFixed(decimals)}
      {suffix}
    </span>
  )
}

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
        className="flex items-center justify-center text-xs text-gray-300"
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
            fill="#1f2937"
            opacity="0.9"
          />
          <text
            x={tooltip.x}
            y={tooltip.y - 15}
            textAnchor="middle"
            fill="white"
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
      <div style={{ height }} className="flex items-center justify-center text-xs text-gray-300">
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
            <div className="absolute -top-7 left-1/2 -translate-x-1/2 bg-gray-800 text-white text-[10px] px-1.5 py-0.5 rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none z-10">
              {d.v.toFixed(1)} ·{" "}
              {new Date(d.t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function StatusDot({ status }: { status: string }) {
  const colors: Record<string, string> = {
    healthy: "bg-green-500",
    degraded: "bg-yellow-500",
    error: "bg-red-500",
    unknown: "bg-gray-400",
    OK: "bg-green-500",
    ALARM: "bg-red-500",
    INSUFFICIENT_DATA: "bg-gray-400",
  }
  const c = colors[status] ?? "bg-gray-400"
  const isAlarm = status === "ALARM" || status === "error"

  return (
    <span className="relative flex h-2.5 w-2.5">
      {isAlarm && (
        <span
          className={`animate-ping absolute inline-flex h-full w-full rounded-full ${c} opacity-75`}
        />
      )}
      <span
        className={`relative inline-flex rounded-full h-2.5 w-2.5 ${c}`}
        style={{ transition: "background-color 300ms ease" }}
      />
    </span>
  )
}

function PulseRing({ active }: { active: boolean }) {
  if (!active) return null
  return (
    <span className="absolute -top-1 -right-1 flex h-3 w-3">
      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
      <span className="relative inline-flex rounded-full h-3 w-3 bg-green-500" />
    </span>
  )
}

function RefreshProgressBar({ active }: { active: boolean }) {
  if (!active) return null
  return (
    <div className="w-full h-0.5 bg-gray-100 overflow-hidden">
      <div
        className="h-full w-1/3 bg-blue-500 rounded"
        style={{ animation: "progressShimmer 1.2s ease-in-out infinite" }}
      />
    </div>
  )
}

const MODEL_DONUT_COLORS: Record<string, { input: string; output: string; cache: string }> = {
  sonnet: { input: "#7c3aed", output: "#a78bfa", cache: "#c4b5fd" },
  haiku: { input: "#0891b2", output: "#22d3ee", cache: "#67e8f9" },
  unknown: { input: "#4b5563", output: "#9ca3af", cache: "#d1d5db" },
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
      color: (MODEL_DONUT_COLORS[t.tier] ?? MODEL_DONUT_COLORS.unknown).input,
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
        color: "#f59e0b",
        count: output,
        pct: percentages.output,
        delay: "0.5s",
      },
      {
        key: "cache",
        label: "Cache",
        color: "#10b981",
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
          <circle cx="40" cy="40" r="30" fill="none" stroke="#e5e7eb" strokeWidth="8" />
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
            className="text-[10px] fill-gray-500"
          >
            {(total / 1000).toFixed(0)}K
          </text>
        </svg>
        {hoveredSegment &&
          (() => {
            const seg = segments.find(s => s.key === hoveredSegment)
            if (!seg) return null
            return (
              <div className="absolute -top-8 left-1/2 -translate-x-1/2 bg-gray-900 text-white text-[10px] px-2 py-1 rounded shadow-lg whitespace-nowrap pointer-events-none z-10">
                {seg.label}: {(seg.count / 1000).toFixed(1)}K ({seg.pct.toFixed(1)}%)
              </div>
            )
          })()}
      </div>
      <div className="text-xs space-y-1">
        {hasModelData ? (
          segments.map(seg => (
            <div key={seg.key} className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full" style={{ backgroundColor: seg.color }} />
              <span className="font-mono">{seg.label}</span>: {(seg.count / 1000).toFixed(1)}K
            </div>
          ))
        ) : (
          <>
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-blue-500" /> Input:{" "}
              {(input / 1000).toFixed(1)}K
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-amber-500" /> Output:{" "}
              {(output / 1000).toFixed(1)}K
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-emerald-500" /> Cache:{" "}
              {(cacheRead / 1000).toFixed(1)}K
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function sumSeries(points: MetricPoint[]): number {
  return points.reduce((a, p) => a + p.v, 0)
}

const MODEL_COLORS: Record<string, string> = {
  sonnet: "#8b5cf6",
  haiku: "#06b6d4",
  unknown: "#6b7280",
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
        <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">
          Model Breakdown
        </h3>
        <p className="text-xs text-gray-400 text-center py-4">No per-model data available</p>
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
      <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">
        Model Breakdown
      </h3>

      <div className="flex items-center gap-4 mb-4">
        {tierStats.map(t => (
          <div key={t.tier} className="flex items-center gap-1.5 text-xs">
            <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: t.color }} />
            <span className="font-mono font-medium">{t.tier}</span>
            <span className="text-gray-400">({t.cases} cases)</span>
          </div>
        ))}
      </div>

      <div className="space-y-3">
        {rows.map(row => (
          <div key={row.label}>
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] text-gray-500 uppercase tracking-wider">
                {row.label}
              </span>
              <span className="text-[10px] text-gray-400 font-mono">{row.fmt(row.total)}</span>
            </div>
            <div className="flex h-5 rounded overflow-hidden bg-gray-100">
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
                    <div className="absolute -top-7 left-1/2 -translate-x-1/2 bg-gray-900 text-white text-[10px] px-2 py-0.5 rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none z-10">
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
            <tr className="text-[10px] text-gray-400 uppercase tracking-wider">
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
              <tr key={t.tier} className="border-t border-gray-50">
                <td className="py-1.5 font-mono font-medium flex items-center gap-1.5">
                  <span
                    className="w-2 h-2 rounded-full inline-block"
                    style={{ backgroundColor: t.color }}
                  />
                  {t.tier}
                </td>
                <td className="text-right text-gray-600 tabular-nums">
                  {(t.inputTokens / 1000).toFixed(1)}K
                </td>
                <td className="text-right text-gray-600 tabular-nums">
                  {(t.outputTokens / 1000).toFixed(1)}K
                </td>
                <td className="text-right text-gray-600 tabular-nums">
                  {(t.cacheReadTokens / 1000).toFixed(1)}K
                </td>
                <td className="text-right text-gray-600 tabular-nums">
                  {(t.avgLatency / 1000).toFixed(1)}s
                </td>
                <td className="text-right text-gray-600 tabular-nums">{t.avgTurns.toFixed(1)}</td>
                <td className="text-right text-gray-600 tabular-nums">${t.cost.toFixed(4)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

export default function AnalyticsDashboard() {
  const auth = useAuth()
  const token = auth.user?.id_token ?? ""

  const [metrics, setMetrics] = useState<MetricsData | null>(null)
  const [health, setHealth] = useState<HealthData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [hours, setHours] = useState("24")
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null)

  const [traces, setTraces] = useState<TracesData | null>(null)
  const [tracesLoading, setTracesLoading] = useState(true)
  const [tracesError, setTracesError] = useState<string | null>(null)

  const [isRefreshing, setIsRefreshing] = useState(false)
  const [timestampFlash, setTimestampFlash] = useState(false)

  const hasAnimated = useRef(false)

  const [isMobile, setIsMobile] = useState(false)
  useEffect(() => {
    const checkMobile = () => setIsMobile(window.innerWidth < 768)
    checkMobile()
    window.addEventListener("resize", checkMobile)
    return () => window.removeEventListener("resize", checkMobile)
  }, [])

  const lambdaCount = health?.lambdas?.length ?? 0
  const { getDelay: getLambdaDelay } = useStaggeredEntrance(lambdaCount, 0, 50)

  const { getDelay: getSummaryDelay } = useStaggeredEntrance(4, 0, 100)

  // Previous queue depths for flash detection
  const prevQueues = useRef<Record<string, number>>({})

  const load = useCallback(async () => {
    if (!token) return
    setError(null)
    setIsRefreshing(true)
    try {
      const [m, h] = await Promise.all([fetchMetrics(token, parseInt(hours)), fetchHealth(token)])
      setMetrics(m)
      setHealth(h)
      setLastRefresh(new Date())

      setTimestampFlash(true)
      setTimeout(() => setTimestampFlash(false), 600)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load")
    } finally {
      setLoading(false)
      setIsRefreshing(false)
    }
  }, [token, hours])

  // Loads independently — must not block metrics/health rendering
  const loadTraces = useCallback(async () => {
    if (!token) return
    setTracesError(null)
    setTracesLoading(true)
    try {
      const t = await fetchTraces(token, parseInt(hours))
      setTraces(t)
    } catch (e) {
      setTracesError(e instanceof Error ? e.message : "Failed to load traces")
    } finally {
      setTracesLoading(false)
    }
  }, [token, hours])

  useEffect(() => {
    load()
    loadTraces()
  }, [load, loadTraces])

  // Auto-refresh every 30s
  useEffect(() => {
    if (!autoRefresh) return
    const id = setInterval(() => {
      load()
      loadTraces()
    }, 30000)
    return () => clearInterval(id)
  }, [autoRefresh, load, loadTraces])

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
    load()
    loadTraces()
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex-none border-b px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="relative">
            <h1 className="text-xl font-semibold">Analytics</h1>
            {/* Pulsing ring while auto-refresh is enabled */}
            <PulseRing active={autoRefresh && hasActivity} />
          </div>
          <span
            className="text-xs text-gray-400 px-1 rounded transition-colors"
            style={timestampFlash ? { animation: "flashHighlight 600ms ease-out" } : undefined}
          >
            {lastRefresh ? `Updated ${lastRefresh.toLocaleTimeString()}` : "Loading..."}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-xs text-gray-500">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={e => setAutoRefresh(e.target.checked)}
              className="rounded border-gray-300"
            />
            Auto-refresh
          </label>
          <Select value={hours} onValueChange={setHours}>
            <SelectTrigger className="w-28 h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="1">Last 1h</SelectItem>
              <SelectItem value="6">Last 6h</SelectItem>
              <SelectItem value="24">Last 24h</SelectItem>
              <SelectItem value="72">Last 3d</SelectItem>
            </SelectContent>
          </Select>
          <Button variant="outline" size="sm" className="h-8" onClick={handleManualRefresh}>
            Refresh
          </Button>
        </div>
      </div>

      {/* Thin progress bar during refresh */}
      <RefreshProgressBar active={isRefreshing} />

      {error && (
        <div className="bg-red-50 border-l-4 border-red-500 p-3 mx-6 mt-3">
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      <div className="grow overflow-auto p-6 space-y-6">
        {loading && !metrics ? (
          <div className="flex items-center justify-center h-64">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
          </div>
        ) : (
          <>
            {/* Row 1: Summary tiles with animated counters + staggered entrance */}
            {s?.source === "traces" && (
              <div className="flex items-center gap-2 px-1 text-[10px] text-amber-600 bg-amber-50 rounded-md py-1.5 px-3">
                <span>📊</span>
                <span>
                  Metrics derived from trace data — CloudWatch agent metrics not available for this
                  period
                </span>
              </div>
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
                  color: "#10b981",
                },
                {
                  label: "Avg Cost",
                  value: s?.avgCostUSD ?? 0,
                  decimals: 3,
                  prefix: "$",
                  suffix: "",
                  data: metrics?.avgCostUSD ?? [],
                  color: "#f59e0b",
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
                <Card
                  key={tile.label}
                  className="p-4 relative overflow-hidden"
                  style={
                    !hasAnimated.current
                      ? {
                          opacity: 0,
                          animation: `fadeSlideUp 400ms ease-out ${getSummaryDelay(i)}ms forwards`,
                        }
                      : undefined
                  }
                >
                  <p className="text-xs text-gray-500 uppercase tracking-wider">{tile.label}</p>
                  <p className="text-3xl font-bold mt-1">
                    <AnimatedNumber
                      value={tile.value}
                      decimals={tile.decimals}
                      prefix={tile.prefix}
                      suffix={tile.suffix}
                    />
                  </p>
                  <Sparkline data={tile.data} color={tile.color} width={120} height={30} />
                </Card>
              ))}
            </div>

            {/* Row 2: Charts — entrance starts after summary tiles */}
            <div
              className="grid grid-cols-1 md:grid-cols-3 gap-4"
              style={getEntranceStyle(CHART_ROW_BASE)}
            >
              <Card className="p-4">
                <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">
                  Cases Over Time
                </h3>
                <BarChart data={metrics?.casesProcessed ?? []} color="#3b82f6" height={100} />
              </Card>
              <Card className="p-4">
                <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">
                  Latency (avg vs p90)
                </h3>
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] text-gray-400 w-8">avg</span>
                    <Sparkline
                      data={metrics?.avgLatencyMs ?? []}
                      color="#8b5cf6"
                      width={200}
                      height={35}
                    />
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] text-gray-400 w-8">p90</span>
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
                <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">
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
                  <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">
                    Model Breakdown
                  </h3>
                  <p className="text-xs text-gray-400 text-center py-4">
                    Per-model metrics (tokens, cost, latency by model tier) will appear here after
                    agent cases are processed.
                  </p>
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
                <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">
                  Lambda Functions
                </h3>
                <div className="space-y-2">
                  {(health?.lambdas ?? []).map((fn, idx) => (
                    <div
                      key={fn.name}
                      className="flex items-center justify-between py-1.5 border-b border-gray-50 last:border-0"
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
                        <StatusDot status={fn.status} />
                        <span className="text-sm font-mono">{fn.name}</span>
                      </div>
                      <div className="flex items-center gap-3 text-xs text-gray-500">
                        <span>{fn.invocations} invocations</span>
                        {fn.errors > 0 && (
                          <span className="text-red-500 font-medium">{fn.errors} errors</span>
                        )}
                      </div>
                    </div>
                  ))}
                  {(health?.lambdas ?? []).length === 0 && (
                    <p className="text-xs text-gray-400">No Lambda data available</p>
                  )}
                </div>
              </Card>

              {/* Queues + Alarms with queue flash */}
              <Card className="p-4">
                <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">
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
                        <StatusDot
                          status={label === "dlq" && q.visible > 0 ? "error" : "healthy"}
                        />
                        <span className="text-sm font-mono">
                          {label === "dlq" ? "Dead Letter Queue" : "Agent Queue"}
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-gray-500">{q.visible} pending</span>
                        {q.inFlight > 0 && (
                          <span className="text-xs text-blue-500">{q.inFlight} in-flight</span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>

                <h4 className="text-[10px] font-medium text-gray-400 uppercase tracking-wider mb-2">
                  CloudWatch Alarms
                </h4>
                <div className="space-y-2">
                  {(health?.alarms ?? []).map(alarm => (
                    <div
                      key={alarm.name}
                      className="flex items-center justify-between py-1 border-b border-gray-50 last:border-0"
                    >
                      <div className="flex items-center gap-2">
                        <StatusDot status={alarm.state} />
                        <span className="text-xs">{alarm.name}</span>
                      </div>
                      <span
                        className={`text-[10px] px-1.5 py-0.5 rounded-full ${
                          alarm.state === "OK"
                            ? "bg-green-50 text-green-700"
                            : alarm.state === "ALARM"
                              ? "bg-red-50 text-red-700"
                              : "bg-gray-50 text-gray-500"
                        }`}
                      >
                        {alarm.state}
                      </span>
                    </div>
                  ))}
                  {(health?.alarms ?? []).length === 0 && (
                    <p className="text-xs text-gray-400">No alarms configured</p>
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
                <h3 className="text-xs font-medium text-red-600 uppercase tracking-wider mb-3 flex items-center gap-1.5">
                  <span className="relative flex h-2 w-2">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75" />
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-red-500" />
                  </span>
                  Recent Errors ({health?.recentErrors?.length ?? 0})
                </h3>
                <div className="space-y-2 max-h-48 overflow-auto">
                  {(health?.recentErrors ?? []).map((err, i) => (
                    <div key={i} className="text-xs border rounded-md p-2 bg-red-50/50">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-mono font-medium text-red-700">{err.lambda}</span>
                        <span className="text-gray-400">
                          {new Date(err.timestamp).toLocaleTimeString([], {
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </span>
                      </div>
                      <p className="text-gray-600 font-mono text-[11px] break-all">{err.message}</p>
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
                    <div className="bg-red-50 border-l-4 border-red-500 p-3">
                      <p className="text-sm text-red-700">{tracesError}</p>
                    </div>
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
              <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">
                Cost Over Time (USD)
              </h3>
              <BarChart data={metrics?.totalCostUSD ?? []} color="#f59e0b" height={80} />
            </Card>
          </>
        )}
      </div>
    </div>
  )
}
