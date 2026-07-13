// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useState, useMemo } from "react"
import { Card } from "@/components/ui/card"
import type { TraceRecord } from "@/services/observabilityService"
import { computeTraceStats } from "./utils/traceUtils"

// Mirrors the AnimatedNumber pattern used in ObservabilityPage, for visual consistency.
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
    let cancelled = false

    function tick(now: number) {
      if (cancelled) return
      const elapsed = now - startTime
      const progress = Math.min(elapsed / duration, 1)
      const eased = 1 - Math.pow(1 - progress, 3) // ease-out cubic
      setDisplay(start + diff * eased)
      if (progress < 1) requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)

    return () => {
      cancelled = true
    }
  }, [value])

  return (
    <span className="tabular-nums">
      {prefix}
      {display.toFixed(decimals)}
      {suffix}
    </span>
  )
}

export interface TraceStatsProps {
  traces: TraceRecord[]
}

export default function TraceStats({ traces }: TraceStatsProps) {
  const stats = useMemo(() => computeTraceStats(traces), [traces])

  const topToolName = stats.topTools.length > 0 ? stats.topTools[0].name : "—"

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <Card className="p-4">
        <p className="text-xs text-gray-500 uppercase tracking-wider">Total Traces</p>
        <p className="text-3xl font-bold mt-1">
          <AnimatedNumber value={stats.totalTraces} />
        </p>
      </Card>

      <Card className="p-4">
        <p className="text-xs text-gray-500 uppercase tracking-wider">Success Rate</p>
        <p className="text-3xl font-bold mt-1">
          <AnimatedNumber value={stats.successRate * 100} decimals={1} suffix="%" />
        </p>
      </Card>

      <Card className="p-4">
        <p className="text-xs text-gray-500 uppercase tracking-wider">Avg Segments</p>
        <p className="text-3xl font-bold mt-1">
          <AnimatedNumber value={stats.avgSegments} decimals={1} />
        </p>
      </Card>

      <Card className="p-4">
        <p className="text-xs text-gray-500 uppercase tracking-wider">Top Tool</p>
        <p className="text-lg font-semibold mt-2 font-mono truncate" title={topToolName}>
          {topToolName}
        </p>
      </Card>
    </div>
  )
}
