// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

export type MessageRole = "user" | "assistant"

// "incomplete" means the run ended without a result — outcome unknown. "error" means
// the tool reported failure. Rendering the second as the first says "unknown" about
// something we were told.
export type ToolCallStatus = "streaming" | "executing" | "complete" | "incomplete" | "error"

export interface ToolCall {
  toolUseId: string
  name: string
  input: string
  result?: string
  status: ToolCallStatus
}

export type MessageSegment =
  { type: "text"; content: string } | { type: "tool"; toolCall: ToolCall }

export interface Message {
  id?: string
  role: MessageRole
  content: string
  timestamp: string
  segments?: MessageSegment[]
}

export interface ToolRenderProps {
  name: string
  args: string
  status: ToolCallStatus
  result?: string
}
