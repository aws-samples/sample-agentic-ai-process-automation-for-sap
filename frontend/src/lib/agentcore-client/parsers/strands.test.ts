// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest"
import { parseStrandsChunk } from "@/lib/agentcore-client/parsers/strands"
import type { StreamEvent } from "@/lib/agentcore-client/types"

function collect(line: string): StreamEvent[] {
  const events: StreamEvent[] = []
  parseStrandsChunk(line, e => events.push(e))
  return events
}

function dataLine(obj: unknown): string {
  return `data: ${JSON.stringify(obj)}`
}

describe("parseStrandsChunk", () => {
  it("emits text for a data string", () => {
    expect(collect(dataLine({ data: "hello" }))).toEqual([{ type: "text", content: "hello" }])
  })

  it("emits tool_use_start when tool input delta is empty", () => {
    const line = dataLine({
      current_tool_use: { toolUseId: "t1", name: "sap_read" },
      delta: { toolUse: { input: "" } },
    })
    expect(collect(line)).toEqual([{ type: "tool_use_start", toolUseId: "t1", name: "sap_read" }])
  })

  it("emits tool_use_delta when tool input delta is non-empty", () => {
    const line = dataLine({
      current_tool_use: { toolUseId: "t1", name: "sap_read" },
      delta: { toolUse: { input: '{"po":1}' } },
    })
    expect(collect(line)).toEqual([{ type: "tool_use_delta", toolUseId: "t1", input: '{"po":1}' }])
  })

  it("emits message and tool_result for a user message with a toolResult block", () => {
    const line = dataLine({
      message: {
        role: "user",
        content: [
          { toolResult: { toolUseId: "t1", content: [{ text: "PO " }, { text: "found" }] } },
        ],
      },
    })
    const events = collect(line)
    expect(events[0].type).toBe("message")
    expect(events[1]).toEqual({ type: "tool_result", toolUseId: "t1", result: "PO found" })
  })

  it("emits result with stop_reason from a result object", () => {
    expect(collect(dataLine({ result: { stop_reason: "end_turn" } }))).toEqual([
      { type: "result", stopReason: "end_turn" },
    ])
  })

  it("emits error then result on status error", () => {
    const events = collect(dataLine({ status: "error", error: "boom" }))
    expect(events[0]).toEqual({ type: "error", message: "boom" })
    expect(events[1]).toEqual({ type: "result", stopReason: "error" })
  })

  it("emits cancelled result with reason", () => {
    expect(collect(dataLine({ status: "cancelled", reason: "user" }))).toEqual([
      { type: "result", stopReason: "cancelled:user" },
    ])
  })

  it("emits lifecycle init", () => {
    expect(collect(dataLine({ init_event_loop: true }))).toEqual([
      { type: "lifecycle", event: "init" },
    ])
  })

  it("ignores non-data lines and malformed JSON without throwing", () => {
    expect(collect("event: ping")).toEqual([])
    expect(collect("data: {not json")).toEqual([])
    expect(collect("data: ")).toEqual([])
  })
})
