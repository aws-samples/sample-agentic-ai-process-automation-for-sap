// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useState, useMemo } from "react"
import { X, Wrench, Brain } from "lucide-react"
import type { TraceSegment } from "@/types/generated-cases"
import { getSegmentLabelAndColor, truncateTooltipContent } from "./utils/traceUtils"
import "./observability-animations.css"

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
const BLOCK_HEIGHT = 44
const BLOCK_GAP = 3
const BLOCK_RADIUS = 6
const MIN_BLOCK_WIDTH = 90
const LABEL_FONT_SIZE = 10
const ERROR_COLOR = "#ef4444" // red-500
// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------

function SegmentDetail({
  segment,
  index,
  total,
  isError,
  onClose,
}: {
  segment: TraceSegment
  index: number
  total: number
  isError: boolean
  onClose: () => void
}) {
  const { label, color } = getSegmentLabelAndColor(segment)
  const displayColor = isError ? ERROR_COLOR : color

  const formatContent = (content: unknown): string => {
    if (!content) return ""
    if (typeof content === "string") {
      try {
        const parsed = JSON.parse(content)
        return JSON.stringify(parsed, null, 2)
      } catch {
        return content
      }
    }
    return JSON.stringify(content, null, 2)
  }

  return (
    <div
      className="border rounded-lg bg-card shadow-sm overflow-hidden"
      style={{ borderLeftColor: displayColor, borderLeftWidth: 4 }}
    >
      <div className="flex items-center justify-between px-4 py-3 bg-muted border-b">
        <div className="flex items-center gap-2">
          {segment.type === "tool" ? (
            <Wrench size={14} className="text-muted-foreground" />
          ) : (
            <Brain size={14} className="text-muted-foreground" />
          )}
          <span className="font-semibold text-sm">{label}</span>
          <span className="text-3xs text-muted-foreground/70 font-mono">
            Step {index + 1} of {total}
          </span>
          {isError && (
            <span className="text-3xs bg-red-100 text-red-700 dark:bg-red-400/15 dark:text-red-300 px-1.5 py-0.5 rounded font-medium">
              Error
            </span>
          )}
        </div>
        <button
          onClick={onClose}
          className="p-1 hover:bg-muted rounded transition-colors"
          aria-label="Close detail"
        >
          <X size={14} className="text-muted-foreground" />
        </button>
      </div>

      <div className="p-4 space-y-3 max-h-80 overflow-auto">
        {segment.type === "tool" ? (
          <>
            {segment.tool_input && (
              <div>
                <p className="text-3xs font-medium text-muted-foreground/70 uppercase tracking-wider mb-1">
                  Input
                </p>
                <pre className="text-xs bg-muted rounded-md p-3 overflow-auto max-h-32 font-mono text-foreground whitespace-pre-wrap break-all">
                  {formatContent(segment.tool_input)}
                </pre>
              </div>
            )}
            {segment.tool_result && (
              <div>
                <p className="text-3xs font-medium text-muted-foreground/70 uppercase tracking-wider mb-1">
                  Result
                </p>
                <pre className="text-xs bg-muted rounded-md p-3 overflow-auto max-h-32 font-mono text-foreground whitespace-pre-wrap break-all">
                  {formatContent(segment.tool_result)}
                </pre>
              </div>
            )}
            {!segment.tool_input && !segment.tool_result && (
              <p className="text-xs text-muted-foreground/70 italic">
                No input or result data available.
              </p>
            )}
          </>
        ) : (
          <div>
            <p className="text-3xs font-medium text-muted-foreground/70 uppercase tracking-wider mb-1">
              Agent Reasoning
            </p>
            <div className="text-xs bg-muted rounded-md p-3 overflow-auto max-h-48 text-foreground whitespace-pre-wrap">
              {segment.content || "No content available."}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
export interface SpanTimelineProps {
  segments: TraceSegment[]
  isError: boolean
}

export default function SpanTimeline({ segments, isError }: SpanTimelineProps) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null)
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null)

  const blocks = useMemo(() => {
    return segments.map((segment, index) => {
      const { label, color } = getSegmentLabelAndColor(segment)
      const isLastSegment = index === segments.length - 1
      const fillColor = isError && isLastSegment ? ERROR_COLOR : color
      return { segment, label, color: fillColor, index }
    })
  }, [segments, isError])

  if (segments.length === 0) {
    return (
      <div className="text-xs text-muted-foreground/70 text-center py-4">
        No segments to display.
      </div>
    )
  }

  const blockWidth = Math.max(MIN_BLOCK_WIDTH, 100)
  const totalWidth = segments.length * (blockWidth + BLOCK_GAP) - BLOCK_GAP
  const svgHeight = BLOCK_HEIGHT + 8

  const handleBlockClick = (index: number) => {
    setSelectedIndex(prev => (prev === index ? null : index))
  }

  return (
    <div className="space-y-3">
      <div
        className="overflow-x-auto md:overflow-x-visible relative pb-1"
        role="img"
        aria-label={`Span timeline with ${segments.length} segments`}
      >
        <svg
          width={totalWidth}
          height={svgHeight}
          viewBox={`0 0 ${totalWidth} ${svgHeight}`}
          className="block"
          style={{ minWidth: totalWidth }}
        >
          {blocks.map(({ segment, label, color, index }) => {
            const x = index * (blockWidth + BLOCK_GAP)
            const isHovered = hoveredIndex === index
            const isSelected = selectedIndex === index
            const staggerDelay = 50 + index * 25

            return (
              <g
                key={index}
                className="opacity-0 cursor-pointer"
                style={{
                  animation: `fadeSlideUp 250ms ease-out ${staggerDelay}ms forwards`,
                }}
                onMouseEnter={() => setHoveredIndex(index)}
                onMouseLeave={() => setHoveredIndex(null)}
                onClick={() => handleBlockClick(index)}
              >
                {isSelected && (
                  <rect
                    x={x - 2}
                    y={2}
                    width={blockWidth + 4}
                    height={BLOCK_HEIGHT + 4}
                    rx={BLOCK_RADIUS + 2}
                    ry={BLOCK_RADIUS + 2}
                    fill="none"
                    stroke={color}
                    strokeWidth="2"
                    opacity="0.5"
                  />
                )}

                <rect
                  x={x}
                  y={4}
                  width={blockWidth}
                  height={BLOCK_HEIGHT}
                  rx={BLOCK_RADIUS}
                  ry={BLOCK_RADIUS}
                  fill={color}
                  opacity={isHovered || isSelected ? 1 : 0.8}
                  className="transition-opacity duration-150"
                  data-testid={`span-rect-${index}`}
                />

                <text
                  x={x + 8}
                  y={4 + BLOCK_HEIGHT / 2 + 1}
                  dominantBaseline="middle"
                  fill="white"
                  fontSize="10"
                  opacity="0.7"
                  pointerEvents="none"
                >
                  {segment.type === "tool" ? "⚙" : "💭"}
                </text>

                <text
                  x={x + 22}
                  y={4 + BLOCK_HEIGHT / 2 + 1}
                  dominantBaseline="middle"
                  fill="white"
                  fontSize={LABEL_FONT_SIZE}
                  fontFamily="ui-monospace, monospace"
                  fontWeight={600}
                  pointerEvents="none"
                  style={{
                    textShadow: "0 1px 2px rgba(0,0,0,0.3)",
                  }}
                >
                  {label.length > 12 ? label.slice(0, 11) + "…" : label}
                </text>

                <text
                  x={x + blockWidth - 12}
                  y={4 + BLOCK_HEIGHT / 2 + 1}
                  dominantBaseline="middle"
                  fill="white"
                  fontSize="10"
                  opacity={isHovered ? 0.8 : 0.3}
                  pointerEvents="none"
                  className="transition-opacity duration-150"
                >
                  ›
                </text>

                <title>
                  {segment.type === "tool"
                    ? `Tool: ${segment.tool_name ?? "unknown"} — Click to view details`
                    : "Reasoning — Click to view details"}
                </title>
              </g>
            )
          })}
        </svg>

        {hoveredIndex !== null && selectedIndex === null && blocks[hoveredIndex] && (
          <div
            className="absolute z-50 bg-foreground text-background text-xs rounded-lg shadow-xl px-4 py-2.5 pointer-events-none max-w-sm"
            style={{
              left: Math.max(
                0,
                Math.min(hoveredIndex * (blockWidth + BLOCK_GAP), totalWidth - 280)
              ),
              top: svgHeight + 6,
            }}
          >
            <TooltipBody
              segment={blocks[hoveredIndex].segment}
              isError={isError && hoveredIndex === segments.length - 1}
            />
            <p className="text-3xs text-background/70 mt-1.5 border-t border-background/20 pt-1.5">
              Click to expand full details
            </p>
          </div>
        )}
      </div>

      {selectedIndex !== null && blocks[selectedIndex] && (
        <SegmentDetail
          segment={blocks[selectedIndex].segment}
          index={selectedIndex}
          total={segments.length}
          isError={isError && selectedIndex === segments.length - 1}
          onClose={() => setSelectedIndex(null)}
        />
      )}
    </div>
  )
}
// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------

// Renders inside the dark inverting tooltip (bg-foreground), so text uses
// `text-background` weights rather than the neutral tokens — a muted-foreground
// grey would read dark-on-dark once the tooltip flips in dark mode.
function TooltipBody({ segment, isError }: { segment: TraceSegment; isError: boolean }) {
  const errorChip = (
    <span className="rounded bg-red-500/25 px-1 text-3xs font-medium text-red-300">error</span>
  )
  if (segment.type === "tool") {
    return (
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-background">⚙ {segment.tool_name ?? "unknown"}</span>
          {isError && errorChip}
        </div>
        {segment.tool_input && (
          <div className="text-background/60">
            <span className="text-background/80">Input: </span>
            {truncateTooltipContent(segment.tool_input, 150)}
          </div>
        )}
        {segment.tool_result && (
          <div className="text-background/60">
            <span className="text-background/80">Result: </span>
            {truncateTooltipContent(segment.tool_result, 150)}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2">
        <span className="font-semibold text-background">💭 Reasoning</span>
        {isError && errorChip}
      </div>
      {segment.content && (
        <div className="text-background/60">{truncateTooltipContent(segment.content, 200)}</div>
      )}
    </div>
  )
}
