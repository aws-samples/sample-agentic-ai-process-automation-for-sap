// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useSyncExternalStore } from "react"
import type { Message } from "@/components/chat/types"

/**
 * What the agent is doing in the *interactive* run, published by whoever owns the
 * stream and read by the rail's heartbeat.
 *
 * A module-level store rather than a context provider: the rail and the streaming
 * page share no ancestor that owns this state today. Once chat state is hoisted into
 * a hook in `AppShell`, that hook publishes here instead and the heartbeat is
 * unchanged.
 *
 * Background runs are not published here. They are visible as cases in `processing`,
 * which the heartbeat polls for directly.
 */
/**
 * `tool` carries the name of the tool in flight, because the console must not claim
 * SAP work for a case-state write or an SOP lookup. The name comes from the stream,
 * so it needs no tool-name pattern matching and cannot go stale as tools are added.
 */
export type AgentActivity =
  { kind: "idle" } | { kind: "reasoning" } | { kind: "tool"; name: string }

const IDLE: AgentActivity = { kind: "idle" }

let activity: AgentActivity = IDLE
const listeners = new Set<() => void>()

export function getAgentActivity(): AgentActivity {
  return activity
}

export function setAgentActivity(next: AgentActivity): void {
  if (next.kind === activity.kind && toolName(next) === toolName(activity)) return
  activity = next
  for (const listener of listeners) listener()
}

function toolName(a: AgentActivity): string | undefined {
  return a.kind === "tool" ? a.name : undefined
}

export function subscribeAgentActivity(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function useAgentActivity(): AgentActivity {
  return useSyncExternalStore(subscribeAgentActivity, getAgentActivity)
}

/**
 * Activity implied by a live turn's projected messages. Called only while a run is
 * in flight, so it never returns idle — a turn with nothing but text is the model
 * thinking, which is what "reasoning" means.
 *
 * The last in-flight call wins: a turn that has already returned one tool result and
 * started another should name the one still running.
 */
export function deriveActivity(messages: Message[]): AgentActivity {
  let inFlight: string | undefined
  for (const message of messages) {
    for (const segment of message.segments ?? []) {
      if (segment?.type !== "tool") continue
      const { status, name } = segment.toolCall
      if (status === "streaming" || status === "executing") inFlight = name
    }
  }
  return inFlight === undefined
    ? { kind: "reasoning" }
    : { kind: "tool", name: toolLabel(inFlight) }
}

/**
 * A tool arrives from the Gateway renamed `target___tool`, and a direct-MCP (OBO)
 * call can still carry the prefix. The backend strips it the same way
 * (`evidence.py:_tool_key`); an operator should never read the plumbing.
 */
function toolLabel(name: string): string {
  return (name || "").split("___").pop() || "a tool"
}
