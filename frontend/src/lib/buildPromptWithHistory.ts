// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Message } from "@/components/chat/types"

/**
 * Build a context-enriched prompt by prepending recent conversation history.
 * This ensures the agent has conversational context even if server-side memory
 * (AgentCore Memory) fails to load or has eventual-consistency lag.
 */
export function buildPromptWithHistory(userMessage: string, messages: Message[]): string {
  if (messages.length === 0) return userMessage

  const recent = messages
    .slice(-10)
    .map(m => {
      const role = m.role === "user" ? "User" : "Assistant"
      const text = m.content.trim()
      if (!text) return null
      const truncated = role === "Assistant" && text.length > 500 ? text.slice(0, 500) + "…" : text
      return `${role}: ${truncated}`
    })
    .filter(Boolean)
    .join("\n")

  if (!recent) return userMessage

  return `<conversation_history>\n${recent}\n</conversation_history>\n\nUser: ${userMessage}`
}
