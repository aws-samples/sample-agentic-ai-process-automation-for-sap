// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import type { AgentCoreConfig, ChunkParser, StreamCallback } from "./types"
import { parseStrandsChunk } from "./parsers/strands"
import { readSSEStream, type SSEStreamResult } from "./utils/sse"

/** The sample ships a single Strands agent, so the Strands SSE parser is used. */
function getParser(): ChunkParser {
  return parseStrandsChunk
}

export class AgentCoreClient {
  private runtimeArn: string
  private region: string
  private parser: ChunkParser

  constructor(config: AgentCoreConfig) {
    this.runtimeArn = config.runtimeArn
    this.region = config.region ?? "us-east-1"
    this.parser = getParser()
  }

  generateSessionId(): string {
    return crypto.randomUUID()
  }

  async invoke(
    query: string,
    sessionId: string,
    accessToken: string,
    onEvent: StreamCallback,
    signal?: AbortSignal,
    extras?: Record<string, unknown>
  ): Promise<SSEStreamResult> {
    return this.invokeCloud(query, sessionId, accessToken, onEvent, signal, extras)
  }

  /** Fire-and-forget — errors are logged but not thrown. */
  async stopSession(sessionId: string, accessToken: string): Promise<void> {
    const endpoint = `https://bedrock-agentcore.${this.region}.amazonaws.com`
    const escapedArn = encodeURIComponent(this.runtimeArn)
    const url = `${endpoint}/runtimes/${escapedArn}/stopruntimesession?qualifier=DEFAULT`

    try {
      await fetch(url, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${accessToken}`,
          "Content-Type": "application/json",
          "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": sessionId,
        },
      })
    } catch (err) {
      console.warn("Failed to stop runtime session:", err)
    }
  }

  private async invokeCloud(
    query: string,
    sessionId: string,
    accessToken: string,
    onEvent: StreamCallback,
    signal?: AbortSignal,
    extras?: Record<string, unknown>
  ): Promise<SSEStreamResult> {
    if (!accessToken) throw new Error("No valid access token found.")
    if (!this.runtimeArn) throw new Error("Agent Runtime ARN not configured.")

    const endpoint = `https://bedrock-agentcore.${this.region}.amazonaws.com`
    const escapedArn = encodeURIComponent(this.runtimeArn)
    const url = `${endpoint}/runtimes/${escapedArn}/invocations?qualifier=DEFAULT`

    const traceId = `1-${Math.floor(Date.now() / 1000).toString(16)}-${crypto.randomUUID()}`

    const response = await fetch(url, {
      method: "POST",
      signal,
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "X-Amzn-Trace-Id": traceId,
        "Content-Type": "application/json",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": sessionId,
      },
      body: JSON.stringify({
        prompt: query,
        runtimeSessionId: sessionId,
        ...extras,
      }),
    })

    if (!response.ok) {
      const errorText = await response.text()
      throw new Error(`HTTP ${response.status}: ${errorText}`)
    }

    return readSSEStream(response, this.parser, onEvent, signal)
  }
}
