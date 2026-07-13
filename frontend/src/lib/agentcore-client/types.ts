// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/** Agent pattern identifier. The sample ships a single Strands agent. */
export type AgentPattern = `strands-${string}`

export interface AgentCoreConfig {
  runtimeArn: string
  region?: string
  pattern?: AgentPattern
}

/** Stream event types emitted by parsers */
export type StreamEvent =
  | { type: "text"; content: string }
  | { type: "tool_use_start"; toolUseId: string; name: string }
  | { type: "tool_use_delta"; toolUseId: string; input: string }
  | { type: "tool_result"; toolUseId: string; result: string }
  | { type: "message"; role: string; content: unknown[] }
  | { type: "result"; stopReason: string }
  | { type: "error"; message: string }
  | { type: "lifecycle"; event: string }
  // The turn is paused awaiting SAP sign-in; resume it on the same session via
  // `interrupt_response`.
  | { type: "interrupt"; interruptId: string; authUrl?: string; message?: string }

/** Callback invoked with each stream event */
export type StreamCallback = (event: StreamEvent) => void

/** Parses a single SSE line and emits events via callback */
export type ChunkParser = (line: string, callback: StreamCallback) => void
