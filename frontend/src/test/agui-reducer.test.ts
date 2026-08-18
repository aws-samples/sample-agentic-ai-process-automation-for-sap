// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from "vitest"
import {
  reduceAguiEvent,
  settleAguiProjection,
  spliceTurnIntoHistory,
  type AguiProjection,
} from "@/lib/aguiReducer"
import type { Message, ToolCall } from "@/components/chat/types"
import type { AguiEvent } from "@/lib/aguiReducer"

const JOURNAL_TIME = "2026-07-24T12:00:00.000Z"
const RUN_ID = "run-1"

function apply(projection: AguiProjection, event: AguiEvent): AguiProjection {
  return reduceAguiEvent(projection, event, JOURNAL_TIME, RUN_ID)
}

function onlyTool(projection: AguiProjection): ToolCall {
  const segment = projection.messages
    .flatMap(message => message.segments ?? [])
    .find(candidate => candidate.type === "tool")
  if (!segment || segment.type !== "tool") throw new Error("expected one tool segment")
  return segment.toolCall
}

describe("AG-UI projection", () => {
  it("projects interleaved text and tool events deterministically", () => {
    let projection: AguiProjection = { messages: [] }
    projection = apply(projection, {
      type: "TEXT_MESSAGE_START",
      messageId: "message-1",
      role: "assistant",
    })
    projection = apply(projection, {
      type: "TEXT_MESSAGE_CONTENT",
      messageId: "message-1",
      delta: "Checking ",
    })
    projection = apply(projection, {
      type: "TOOL_CALL_START",
      toolCallId: "tool-1",
      toolCallName: "get_case_state",
      parentMessageId: "message-1",
    })
    projection = apply(projection, {
      type: "TOOL_CALL_ARGS",
      toolCallId: "tool-1",
      delta: '{"caseId":"100#10"}',
    })
    projection = apply(projection, {
      type: "TOOL_CALL_END",
      toolCallId: "tool-1",
    })
    projection = apply(projection, {
      type: "TEXT_MESSAGE_CONTENT",
      messageId: "message-1",
      delta: "the case.",
    })
    projection = apply(projection, {
      type: "TOOL_CALL_RESULT",
      toolCallId: "tool-1",
      content: { status: "open" },
    })

    expect(projection.messages).toHaveLength(1)
    expect(projection.messages[0].content).toBe("Checking the case.")
    expect(projection.messages[0].segments?.map(segment => segment.type)).toEqual([
      "text",
      "tool",
      "text",
    ])
    expect(onlyTool(projection)).toMatchObject({
      toolUseId: "tool-1",
      name: "get_case_state",
      input: '{"caseId":"100#10"}',
      result: '{"status":"open"}',
      status: "complete",
    })
  })

  it("renders a failed tool as failed while streaming, and the snapshot does not undo it", () => {
    // AG-UI defines no failure field on TOOL_CALL_RESULT, so the agent attaches the
    // SDK's ToolResult.status as an extra. Without this the call showed a green check
    // mid-run and a red X only after a reload read the persisted segment.
    let projection: AguiProjection = { messages: [] }
    projection = apply(projection, {
      type: "TOOL_CALL_START",
      toolCallId: "tool-1",
      toolCallName: "odata_update",
    })
    projection = apply(projection, {
      type: "TOOL_CALL_RESULT",
      toolCallId: "tool-1",
      content: "Error: 403 Forbidden",
      status: "error",
    })

    expect(onlyTool(projection).status).toBe("error")

    // The adapter splices a ToolMessage snapshot in right behind the result event.
    projection = apply(projection, {
      type: "MESSAGES_SNAPSHOT",
      messages: [{ role: "tool", toolCallId: "tool-1", content: "Error: 403 Forbidden" }],
    })

    expect(onlyTool(projection).status).toBe("error")
  })

  it("marks a tool without a canonical result incomplete instead of failed", () => {
    let projection: AguiProjection = { messages: [] }
    projection = apply(projection, {
      type: "TOOL_CALL_START",
      toolCallId: "tool-unknown",
      toolCallName: "send_notification",
    })
    projection = apply(projection, {
      type: "TOOL_CALL_END",
      toolCallId: "tool-unknown",
    })

    const settled = settleAguiProjection(projection)

    expect(onlyTool(settled).status).toBe("incomplete")
    expect(onlyTool(settled).result).toBeUndefined()
  })

  it("applies snapshots and does not duplicate a replayed run error", () => {
    let projection: AguiProjection = { messages: [] }
    projection = apply(projection, {
      type: "MESSAGES_SNAPSHOT",
      messages: [
        {
          id: "message-1",
          role: "assistant",
          content: "Snapshot text",
          toolCalls: [
            {
              id: "tool-1",
              function: { name: "odata_read", arguments: '{"entity":"Invoice"}' },
            },
          ],
        },
        { role: "tool", toolCallId: "tool-1", content: "Invoice found" },
      ],
    })
    const error: AguiEvent = {
      type: "RUN_ERROR",
      message: "Runtime outcome unknown",
      code: "OUTCOME_UNKNOWN",
    }
    projection = apply(projection, error)
    projection = apply(projection, error)

    expect(onlyTool(projection)).toMatchObject({
      status: "complete",
      result: "Invoice found",
    })
    expect(
      projection.messages.filter(message => message.id === `run-error-${RUN_ID}`)
    ).toHaveLength(1)
  })
})

describe("spliceTurnIntoHistory", () => {
  const userMessage: Message = {
    role: "user",
    content: "Process the accrual exception",
    timestamp: JOURNAL_TIME,
  }

  function assistant(id: string, content: string): Message {
    return { id, role: "assistant", content, timestamp: JOURNAL_TIME, segments: [] }
  }

  it("keeps a user message the caller has not yet committed to state", () => {
    // handleSend queues its user message and calls the stream synchronously, so the
    // first render observes state that already contains it. Splicing must not drop it.
    const placeholder = assistant(`assistant-${RUN_ID}`, "")
    const owned = new Set([placeholder.id!])

    const spliced = spliceTurnIntoHistory([userMessage], [placeholder], owned)

    expect(spliced.map(message => message.role)).toEqual(["user", "assistant"])
    expect(spliced[0]).toBe(userMessage)
  })

  it("replaces the placeholder once the agent supplies its own message id", () => {
    const placeholder = assistant(`assistant-${RUN_ID}`, "")
    const owned = new Set([placeholder.id!])
    const first = spliceTurnIntoHistory([userMessage], [placeholder], owned)

    // The agent's own id differs from the placeholder's, so without accumulating owned
    // ids the empty placeholder would be stranded above the real reply.
    const real = assistant("msg-from-agent", "Reviewing the delivery date.")
    owned.add(real.id!)
    const second = spliceTurnIntoHistory(first, [real], owned)

    expect(second).toHaveLength(2)
    expect(second[1].id).toBe("msg-from-agent")
    expect(second.some(message => message.content === "" && message.role === "assistant")).toBe(
      false
    )
  })

  it("preserves earlier turns and appends the current one", () => {
    const history: Message[] = [
      userMessage,
      assistant("run-1-assistant", "First answer."),
      { role: "user", content: "And the second?", timestamp: JOURNAL_TIME },
    ]
    const turn = [assistant("run-2-assistant", "Second answer.")]
    const owned = new Set(["run-2-assistant"])

    const spliced = spliceTurnIntoHistory(history, turn, owned)

    expect(spliced.map(message => message.content)).toEqual([
      "Process the accrual exception",
      "First answer.",
      "And the second?",
      "Second answer.",
    ])
  })

  it("is idempotent, so repeated renders of one turn do not duplicate it", () => {
    const turn = [assistant(`assistant-${RUN_ID}`, "Streaming...")]
    const owned = new Set([`assistant-${RUN_ID}`])

    let state = spliceTurnIntoHistory([userMessage], turn, owned)
    state = spliceTurnIntoHistory(state, turn, owned)
    state = spliceTurnIntoHistory(state, turn, owned)

    expect(state).toHaveLength(2)
  })
})

describe("terminal RUN_ERROR rendering", () => {
  it("renders a deliberate stop as a warning, not a failure", () => {
    // AG-UI has no cancelled event, so the turn limit arrives as RUN_ERROR. Work done
    // before the limit still stands, so it must not read as something that broke.
    const projection = apply(
      { messages: [] },
      {
        type: "RUN_ERROR",
        message: "The agent reached its configured processing limit.",
        code: "MAX_TURNS_REACHED",
      }
    )

    const content = projection.messages[0].content
    expect(content).toContain("⚠️")
    expect(content).not.toContain("❌")
    expect(content).not.toContain("MAX_TURNS_REACHED")
  })

  it("renders an unexpected failure as an error and keeps the code", () => {
    const projection = apply(
      { messages: [] },
      { type: "RUN_ERROR", message: "Gateway target unreachable.", code: "TOOL_FAILURE" }
    )

    const content = projection.messages[0].content
    expect(content).toContain("❌")
    expect(content).toContain("TOOL_FAILURE")
  })
})
