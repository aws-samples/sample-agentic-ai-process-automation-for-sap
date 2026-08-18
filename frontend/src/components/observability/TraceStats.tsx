// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useMemo } from "react"
import { Card } from "@/components/ui/card"
import { StatMetric } from "@/components/ui/page-chrome"
import type { TraceRecord } from "@/services/observabilityService"
import { computeTraceStats } from "./utils/traceUtils"

// These figures land at their value rather than counting up to it: a ramp on a number
// someone is reconciling against SAP shows a wrong figure for most of its duration, and
// every ramp here ran past the 250 ms motion ceiling.

export interface TraceStatsProps {
  traces: TraceRecord[]
}

export default function TraceStats({ traces }: TraceStatsProps) {
  const stats = useMemo(() => computeTraceStats(traces), [traces])

  const topToolName = stats.topTools.length > 0 ? stats.topTools[0].name : "—"

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <Card className="p-4">
        <StatMetric label="Total Traces" value={stats.totalTraces} />
      </Card>

      <Card className="p-4">
        <StatMetric label="Success Rate" value={`${(stats.successRate * 100).toFixed(1)}%`} />
      </Card>

      <Card className="p-4">
        <StatMetric label="Avg Segments" value={stats.avgSegments.toFixed(1)} />
      </Card>

      <Card className="p-4">
        <p className="text-xs text-muted-foreground uppercase tracking-wider">Top Tool</p>
        {/* A tool name, not a number — mono, because it is matched against config. */}
        <p className="text-lg font-semibold mt-2 font-mono truncate" title={topToolName}>
          {topToolName}
        </p>
      </Card>
    </div>
  )
}
