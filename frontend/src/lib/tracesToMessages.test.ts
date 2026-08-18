// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest"
import { tracesToMessages } from "@/lib/tracesToMessages"
import { Type as TraceSegmentType } from "@/types/cases"
import type { AgentTrace } from "@/types/cases"

function makeTrace(overrides: Partial<AgentTrace> = {}): AgentTrace {
  return {
    trace_id: "trace-1",
    timestamp: "2026-07-01T00:00:00Z",
    segments: [{ type: TraceSegmentType.Text, content: "Hello from the agent" }],
    ...overrides,
  }
}

describe("tracesToMessages", () => {
  it("maps a text-only trace to a single assistant message", () => {
    const messages = tracesToMessages([makeTrace()])
    expect(messages).toEqual([
      {
        id: "trace-1",
        role: "assistant",
        content: "Hello from the agent",
        timestamp: "2026-07-01T00:00:00Z",
        segments: [{ type: "text", content: "Hello from the agent" }],
      },
    ])
  })

  it("emits a preceding user message when prompt is present", () => {
    const messages = tracesToMessages([makeTrace({ prompt: "Process case DOC-1" })])
    expect(messages[0]).toEqual({
      role: "user",
      content: "Process case DOC-1",
      timestamp: "2026-07-01T00:00:00Z",
    })
    expect(messages[1].role).toBe("assistant")
  })

  it("maps tool segments into a toolCall with status complete", () => {
    const messages = tracesToMessages([
      makeTrace({
        segments: [
          {
            type: TraceSegmentType.Tool,
            tool_name: "get_po",
            tool_input: '{"po":"123"}',
            tool_result: '{"status":"ok"}',
          },
        ],
      }),
    ])
    expect(messages[0].segments).toEqual([
      {
        type: "tool",
        toolCall: {
          toolUseId: "trace-1-0",
          name: "get_po",
          input: '{"po":"123"}',
          result: '{"status":"ok"}',
          status: "complete",
        },
      },
    ])
    expect(messages[0].content).toBe("")
  })

  it("concatenates multiple text segments space-joined into content", () => {
    const messages = tracesToMessages([
      makeTrace({
        segments: [
          { type: TraceSegmentType.Text, content: "First." },
          { type: TraceSegmentType.Tool, tool_name: "get_po" },
          { type: TraceSegmentType.Text, content: "Second." },
        ],
      }),
    ])
    expect(messages[0].content).toBe("First. Second.")
    expect(messages[0].segments).toHaveLength(3)
  })

  it("preserves trace order (oldest first, matching storage order)", () => {
    const messages = tracesToMessages([
      makeTrace({ trace_id: "t1", timestamp: "2026-07-01T00:00:00Z" }),
      makeTrace({ trace_id: "t2", timestamp: "2026-07-02T00:00:00Z" }),
    ])
    expect(messages.map(m => m.id)).toEqual(["t1", "t2"])
  })

  it("skips a trace with missing segments", () => {
    const messages = tracesToMessages([
      { trace_id: "bad", timestamp: "2026-07-01T00:00:00Z" } as unknown as AgentTrace,
    ])
    expect(messages).toEqual([])
  })

  it("skips a trace with empty segments array", () => {
    const messages = tracesToMessages([makeTrace({ segments: [] })])
    expect(messages).toEqual([])
  })

  it("skips a tool segment with no tool_name", () => {
    const messages = tracesToMessages([
      makeTrace({
        segments: [
          { type: TraceSegmentType.Text, content: "Before" },
          { type: TraceSegmentType.Tool },
          { type: TraceSegmentType.Text, content: "After" },
        ],
      }),
    ])
    expect(messages[0].segments).toEqual([
      { type: "text", content: "Before" },
      { type: "text", content: "After" },
    ])
  })

  it("skips a text segment with empty content", () => {
    const messages = tracesToMessages([
      makeTrace({
        segments: [
          { type: TraceSegmentType.Text, content: "" },
          { type: TraceSegmentType.Text, content: "Kept" },
        ],
      }),
    ])
    expect(messages[0].segments).toEqual([{ type: "text", content: "Kept" }])
  })

  it("returns an empty array for an empty traces list", () => {
    expect(tracesToMessages([])).toEqual([])
  })
})
