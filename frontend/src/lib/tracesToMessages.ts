// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { Type as TraceSegmentType } from "@/types/cases"
import type { AgentTrace, TraceSegment } from "@/types/cases"
import type { Message, MessageSegment } from "@/components/chat/types"

function mapSegment(segment: TraceSegment, index: number, traceId: string): MessageSegment | null {
  if (segment.type === TraceSegmentType.Text) {
    if (!segment.content) return null
    return { type: "text", content: segment.content }
  }
  if (segment.type === TraceSegmentType.Tool) {
    if (!segment.tool_name) return null
    return {
      type: "tool",
      toolCall: {
        toolUseId: `${traceId}-${index}`,
        name: segment.tool_name,
        input: segment.tool_input ?? "",
        result: segment.tool_result,
        status: "complete",
      },
    }
  }
  return null
}

/** Replays a case's agent_traces as chat messages, oldest first (storage order). */
export function tracesToMessages(traces: AgentTrace[]): Message[] {
  const messages: Message[] = []

  for (const trace of traces) {
    if (!Array.isArray(trace.segments) || trace.segments.length === 0) continue

    if (trace.prompt) {
      messages.push({ role: "user", content: trace.prompt, timestamp: trace.timestamp })
    }

    const segments = trace.segments
      .map((segment, index) => mapSegment(segment, index, trace.trace_id))
      .filter((s): s is MessageSegment => s !== null)

    const content = segments
      .filter((s): s is { type: "text"; content: string } => s.type === "text")
      .map(s => s.content)
      .join(" ")

    messages.push({
      id: trace.trace_id,
      role: "assistant",
      content,
      timestamp: trace.timestamp,
      segments,
    })
  }

  return messages
}
