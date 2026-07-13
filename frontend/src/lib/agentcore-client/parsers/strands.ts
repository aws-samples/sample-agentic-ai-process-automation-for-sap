// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import type { ChunkParser } from "../types"

/** Parses SSE chunks from Strands agents into typed StreamEvents. */
export const parseStrandsChunk: ChunkParser = (line, callback) => {
  if (!line.startsWith("data: ")) return

  const data = line.substring(6).trim()
  if (!data) return

  try {
    const json = JSON.parse(data)

    if (typeof json.data === "string") {
      callback({ type: "text", content: json.data })
      return
    }

    if (json.current_tool_use) {
      const tool = json.current_tool_use
      // First delta for a tool has empty input — treat as start
      if (json.delta?.toolUse?.input === "") {
        callback({
          type: "tool_use_start",
          toolUseId: tool.toolUseId,
          name: tool.name,
        })
      } else if (json.delta?.toolUse?.input) {
        callback({
          type: "tool_use_delta",
          toolUseId: tool.toolUseId,
          input: json.delta.toolUse.input,
        })
      }
      return
    }

    if (json.message) {
      const msg = json.message
      callback({ type: "message", role: msg.role, content: msg.content })

      if (msg.role === "user" && Array.isArray(msg.content)) {
        for (const block of msg.content) {
          if (block.toolResult) {
            const resultText =
              block.toolResult.content
                ?.map((c: { text?: string }) => c.text)
                .filter(Boolean)
                .join("") || JSON.stringify(block.toolResult.content)
            callback({
              type: "tool_result",
              toolUseId: block.toolResult.toolUseId,
              result: resultText,
            })
          }
        }
      }
      return
    }

    // The turn paused awaiting SAP sign-in; emitted before the generic result
    // so it isn't masked as end_turn.
    if (json.interrupt) {
      callback({
        type: "interrupt",
        interruptId: json.interrupt.id,
        authUrl: json.interrupt.auth_url,
        message: json.interrupt.message,
      })
      return
    }

    if (json.result) {
      callback({
        type: "result",
        stopReason: typeof json.result === "object" ? json.result.stop_reason : "end_turn",
      })
      return
    }

    if (json.status) {
      if (json.status === "error") {
        callback({ type: "error", message: json.error || "Unknown agent error" })
      }
      callback({
        type: "result",
        stopReason:
          json.status === "cancelled" ? `cancelled:${json.reason ?? "unknown"}` : json.status,
      })
      return
    }

    if (json.init_event_loop || json.start_event_loop || json.start) {
      const event = json.init_event_loop ? "init" : json.start_event_loop ? "start_loop" : "start"
      callback({ type: "lifecycle", event })
      return
    }
  } catch {
    console.debug("Failed to parse strands event:", data)
  }
}
