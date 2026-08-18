// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { getConfig } from "@/lib/config"
import type { AguiEvent } from "@/lib/aguiReducer"
import { Trigger } from "@/types/cases"

export interface InteractiveRunRequest {
  /** The user prompt for this turn. */
  message: string
  /** AG-UI thread identifier; also the Runtime session id for this conversation. */
  threadId: string
  /** Runtime session id, kept distinct so a turn can be replayed on the same session. */
  runtimeSessionId: string
  /** AG-UI run identifier, unique per turn. */
  runId: string
  /** Focused case, forwarded to the agent for skill routing and audit. */
  caseId?: string
  /** What initiated the run — a `Trigger` value; interactive chat is "manual". */
  trigger?: Trigger
  /** Case's process type, so the agent can skill-route without a DynamoDB lookup. */
  processType?: string
}

export interface InteractiveRunResult {
  terminalEvent: "RUN_FINISHED" | "RUN_ERROR"
}

/**
 * Thrown when the invocation is rejected before any streaming begins.
 *
 * Distinguishes "no run was ever started" from "a run started and the stream
 * broke". The two need opposite messages: one is an error to show, the other
 * means work may still be in flight server-side.
 */
export class AgentRuntimeStartError extends Error {
  constructor(message: string) {
    super(message)
    this.name = "AgentRuntimeStartError"
  }
}

function runtimeUrl(runtimeArn: string, region: string, action = "invocations"): string {
  const encodedArn = encodeURIComponent(runtimeArn)
  return `https://bedrock-agentcore.${region}.amazonaws.com/runtimes/${encodedArn}/${action}?qualifier=DEFAULT`
}

function aguiInput(request: InteractiveRunRequest): Record<string, unknown> {
  const erpPayload = {
    prompt: request.message,
    case_id: request.caseId ?? "",
    trigger: request.trigger ?? Trigger.Manual,
    process_type: request.processType,
    run_id: request.runId,
    thread_id: request.threadId,
  }
  return {
    threadId: request.threadId,
    runId: request.runId,
    // RunAgentInput requires the key; nothing reads it back, so it carries no
    // duplicate of the caseId/trigger already in forwardedProps.erpPayload.
    state: null,
    messages: [
      {
        id: `input-${request.runId}`,
        role: "user",
        content: request.message,
      },
    ],
    tools: [],
    context: [],
    forwardedProps: { erpPayload },
  }
}

function decodeEvent(block: string): AguiEvent | null {
  const data = block
    .split("\n")
    .filter(line => line.startsWith("data:"))
    .map(line => line.slice(5).replace(/^ /, ""))
    .join("\n")
  // No data lines means an SSE comment — the agent's keepalive heartbeat, which
  // exists to keep an idle connection warm and carries nothing to project.
  if (!data) return null
  const parsed: unknown = JSON.parse(data)
  if (
    typeof parsed !== "object" ||
    parsed === null ||
    typeof (parsed as AguiEvent).type !== "string"
  ) {
    throw new Error("Agent Runtime returned an invalid AG-UI event.")
  }
  return parsed as AguiEvent
}

async function readAguiStream(
  response: Response,
  onEvent: (event: AguiEvent) => void,
  signal?: AbortSignal
): Promise<InteractiveRunResult> {
  if (!response.body) {
    throw new AgentRuntimeStartError("Agent Runtime response did not include a stream.")
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  let terminalEvent: InteractiveRunResult["terminalEvent"] | undefined

  const consume = (block: string) => {
    const event = decodeEvent(block)
    if (!event) return
    onEvent(event)
    // AG-UI defines exactly two terminal outcomes. A deliberate stop, such as the
    // agent's turn limit, arrives as RUN_ERROR carrying a code.
    if (event.type === "RUN_FINISHED" || event.type === "RUN_ERROR") {
      terminalEvent = event.type
    }
  }

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      // Preserve a trailing CR until the next chunk so a split CRLF is not
      // mistaken for the blank line that terminates an SSE event.
      buffer = buffer.replace(/\r\n/g, "\n").replace(/\r(?!$)/g, "\n")
      const blocks = buffer.split("\n\n")
      buffer = blocks.pop() ?? ""
      for (const block of blocks) consume(block)
    }
    buffer += decoder.decode()
    buffer = buffer.replace(/\r\n/g, "\n").replace(/\r/g, "\n")
    if (buffer.trim()) consume(buffer)
  } finally {
    reader.releaseLock()
  }

  if (signal?.aborted) throw new DOMException("The operation was aborted.", "AbortError")
  if (!terminalEvent) throw new Error("Agent Runtime stream ended without a terminal AG-UI event.")
  return { terminalEvent }
}

export async function invokeInteractiveRun(
  request: InteractiveRunRequest,
  token: string,
  onEvent: (event: AguiEvent) => void,
  signal?: AbortSignal
): Promise<InteractiveRunResult> {
  const { agentRuntimeArn, awsRegion } = await getConfig()
  if (!agentRuntimeArn) throw new AgentRuntimeStartError("Agent Runtime ARN is not configured.")

  const response = await fetch(runtimeUrl(agentRuntimeArn, awsRegion || "us-east-1"), {
    method: "POST",
    signal,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "text/event-stream",
      "Content-Type": "application/json",
      "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": request.runtimeSessionId,
    },
    body: JSON.stringify(aguiInput(request)),
  })

  if (!response.ok) {
    throw new AgentRuntimeStartError(
      `Agent Runtime invocation failed with HTTP ${response.status}.`
    )
  }
  return readAguiStream(response, onEvent, signal)
}

export async function stopInteractiveSession(
  runtimeSessionId: string,
  token: string
): Promise<void> {
  const { agentRuntimeArn, awsRegion } = await getConfig()
  if (!agentRuntimeArn) return
  const response = await fetch(
    runtimeUrl(agentRuntimeArn, awsRegion || "us-east-1", "stopruntimesession"),
    {
      method: "POST",
      keepalive: true,
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": runtimeSessionId,
      },
    }
  )
  if (!response.ok) {
    throw new Error(`Stopping the Agent Runtime session failed with HTTP ${response.status}.`)
  }
}
