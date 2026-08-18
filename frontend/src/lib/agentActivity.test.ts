// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, afterEach } from "vitest"
import {
  deriveActivity,
  getAgentActivity,
  setAgentActivity,
  subscribeAgentActivity,
} from "@/lib/agentActivity"
import type { Message, MessageSegment, ToolCallStatus } from "@/components/chat/types"

function assistant(segments: MessageSegment[]): Message[] {
  return [{ role: "assistant", content: "", timestamp: "2026-07-01T00:00:00Z", segments }]
}

// Typed rather than widened to `string`: a typo'd status would otherwise compile and
// the test would silently assert the fallback instead of the branch it names.
function tool(name: string, status: ToolCallStatus): MessageSegment {
  return { type: "tool", toolCall: { toolUseId: name, name, input: "", status } }
}

afterEach(() => setAgentActivity({ kind: "idle" }))

describe("deriveActivity", () => {
  it("names the tool that is streaming", () => {
    const messages = assistant([tool("odata_read", "streaming")])
    expect(deriveActivity(messages)).toEqual({ kind: "tool", name: "odata_read" })
  })

  it("names the tool that is executing", () => {
    const messages = assistant([tool("odata_read", "executing")])
    expect(deriveActivity(messages)).toEqual({ kind: "tool", name: "odata_read" })
  })

  it("names the tool still running, not one that already returned", () => {
    const messages = assistant([
      tool("odata_read", "complete"),
      tool("update_case_state", "executing"),
    ])
    expect(deriveActivity(messages)).toEqual({ kind: "tool", name: "update_case_state" })
  })

  it("strips the Gateway prefix so the plumbing never reaches an operator", () => {
    const messages = assistant([tool("target___odata_update", "executing")])
    expect(deriveActivity(messages)).toEqual({ kind: "tool", name: "odata_update" })
  })

  it("reports reasoning once every tool call has returned", () => {
    const messages = assistant([
      tool("odata_read", "complete"),
      { type: "text", content: "The variance is 2%." },
    ])
    expect(deriveActivity(messages)).toEqual({ kind: "reasoning" })
  })

  it("reports reasoning for a turn with no tool calls yet", () => {
    expect(deriveActivity(assistant([]))).toEqual({ kind: "reasoning" })
  })
})

describe("the activity store", () => {
  it("notifies subscribers on a change and not on a repeat", () => {
    const listener = vi.fn()
    const unsubscribe = subscribeAgentActivity(listener)

    setAgentActivity({ kind: "reasoning" })
    expect(listener).toHaveBeenCalledTimes(1)
    expect(getAgentActivity()).toEqual({ kind: "reasoning" })

    setAgentActivity({ kind: "reasoning" })
    expect(listener).toHaveBeenCalledTimes(1)

    unsubscribe()
    setAgentActivity({ kind: "idle" })
    expect(listener).toHaveBeenCalledTimes(1)
    expect(getAgentActivity()).toEqual({ kind: "idle" })
  })

  it("notifies when only the tool name changes", () => {
    // Same kind, different tool: the label has to follow the run from one call to the
    // next, so identity cannot be decided on `kind` alone.
    const listener = vi.fn()
    const unsubscribe = subscribeAgentActivity(listener)

    setAgentActivity({ kind: "tool", name: "odata_read" })
    setAgentActivity({ kind: "tool", name: "update_case_state" })
    expect(listener).toHaveBeenCalledTimes(2)

    setAgentActivity({ kind: "tool", name: "update_case_state" })
    expect(listener).toHaveBeenCalledTimes(2)
    unsubscribe()
  })
})
