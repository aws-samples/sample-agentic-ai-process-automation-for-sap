// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useState, useMemo } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { TraceRecord } from "@/services/observabilityService"
import { computeToolUsage, TOOL_COLORS } from "./utils/traceUtils"
import { useStaggeredEntrance } from "./hooks/useStaggeredEntrance"
import "./observability-animations.css"

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
const BAR_HEIGHT = 24
const BAR_GAP = 8
const LABEL_WIDTH = 140
const COUNT_WIDTH = 48
const BAR_AREA_LEFT = LABEL_WIDTH + 8
const BAR_RADIUS = 4
const DEFAULT_COLOR = "#6b7280" // gray

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
export interface ToolUsageChartProps {
  traces: TraceRecord[]
}
// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------

export default function ToolUsageChart({ traces }: ToolUsageChartProps) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null)

  const toolData = useMemo(() => computeToolUsage(traces, 10), [traces])
  const maxCount = useMemo(() => {
    if (toolData.length === 0) return 0
    return toolData[0].count
  }, [toolData])

  const { getDelay } = useStaggeredEntrance(toolData.length, 0, 50)

  if (toolData.length === 0) {
    return (
      <Card className="p-4">
        <CardHeader className="p-0 pb-3">
          <CardTitle className="text-sm">Tool Usage</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <p className="text-xs text-muted-foreground/70 text-center py-6">
            No tool usage data available.
          </p>
        </CardContent>
      </Card>
    )
  }

  const svgHeight = toolData.length * (BAR_HEIGHT + BAR_GAP) - BAR_GAP + 8
  const svgWidth = 500

  const barAreaWidth = svgWidth - BAR_AREA_LEFT - COUNT_WIDTH - 8

  return (
    <Card className="p-4">
      <CardHeader className="p-0 pb-3">
        <CardTitle className="text-sm">Tool Usage</CardTitle>
      </CardHeader>
      <CardContent className="p-0 overflow-x-auto">
        <div className="relative">
          <svg
            width="100%"
            height={svgHeight}
            viewBox={`0 0 ${svgWidth} ${svgHeight}`}
            className="block"
            role="img"
            aria-label={`Tool usage chart showing ${toolData.length} tools`}
          >
            {toolData.map((tool, index) => {
              const y = index * (BAR_HEIGHT + BAR_GAP) + 4
              const barWidth = maxCount > 0 ? (tool.count / maxCount) * barAreaWidth : 0
              const color = TOOL_COLORS[tool.name] ?? DEFAULT_COLOR
              const isHovered = hoveredIndex === index
              const delay = getDelay(index)

              return (
                <g
                  key={tool.name}
                  className="opacity-0"
                  style={{
                    animation: `fadeSlideUp 300ms ease-out ${delay}ms forwards`,
                  }}
                  onMouseEnter={() => setHoveredIndex(index)}
                  onMouseLeave={() => setHoveredIndex(null)}
                  data-testid={`tool-bar-${index}`}
                >
                  <text
                    x={LABEL_WIDTH}
                    y={y + BAR_HEIGHT / 2 + 1}
                    textAnchor="end"
                    dominantBaseline="middle"
                    fontSize={11}
                    fontFamily="ui-monospace, monospace"
                    fontWeight={isHovered ? 600 : 400}
                    className={`transition-all duration-150 ${isHovered ? "fill-foreground" : "fill-muted-foreground"}`}
                  >
                    {tool.name.length > 18 ? tool.name.slice(0, 17) + "…" : tool.name}
                  </text>

                  <rect
                    x={BAR_AREA_LEFT}
                    y={y}
                    width={barAreaWidth}
                    height={BAR_HEIGHT}
                    rx={BAR_RADIUS}
                    ry={BAR_RADIUS}
                    className="fill-muted"
                  />

                  <rect
                    x={BAR_AREA_LEFT}
                    y={y}
                    width={barWidth}
                    height={BAR_HEIGHT}
                    rx={BAR_RADIUS}
                    ry={BAR_RADIUS}
                    fill={color}
                    opacity={isHovered ? 1 : 0.85}
                    className="transition-opacity duration-150"
                    style={{
                      transformOrigin: `${BAR_AREA_LEFT}px ${y + BAR_HEIGHT / 2}px`,
                      animation: `growBarHorizontal 400ms ease-out ${delay}ms both`,
                    }}
                    data-testid={`tool-bar-rect-${index}`}
                  />

                  <text
                    x={BAR_AREA_LEFT + barAreaWidth + 8}
                    y={y + BAR_HEIGHT / 2 + 1}
                    textAnchor="start"
                    dominantBaseline="middle"
                    fontSize={11}
                    fontFamily="ui-monospace, monospace"
                    fontWeight={isHovered ? 600 : 400}
                    className={`transition-all duration-150 ${isHovered ? "fill-foreground" : "fill-muted-foreground/70"}`}
                  >
                    {tool.count}
                  </text>

                  <title>{`${tool.name}: ${tool.count} invocation${tool.count !== 1 ? "s" : ""}`}</title>
                </g>
              )
            })}
          </svg>

          {hoveredIndex !== null && toolData[hoveredIndex] && (
            <div
              className="absolute z-50 bg-foreground text-background text-2xs rounded-md shadow-lg px-3 py-2 pointer-events-none whitespace-nowrap"
              style={{
                left: BAR_AREA_LEFT,
                top: hoveredIndex * (BAR_HEIGHT + BAR_GAP) + BAR_HEIGHT + 8,
              }}
              data-testid="tool-usage-tooltip"
            >
              <span className="font-mono font-semibold">{toolData[hoveredIndex].name}</span>
              <span className="text-muted-foreground/60 mx-1.5">—</span>
              <span className="tabular-nums">
                {toolData[hoveredIndex].count} invocation
                {toolData[hoveredIndex].count !== 1 ? "s" : ""}
              </span>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
