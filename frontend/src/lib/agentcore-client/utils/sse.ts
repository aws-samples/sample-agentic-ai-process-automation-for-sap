// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import type { ChunkParser, StreamCallback, StreamEvent } from "../types"

/** Result of reading an SSE stream — includes the stop reason if one was received. */
export interface SSEStreamResult {
  /** The stop reason from a `result` event, or undefined if the stream ended without one. */
  stopReason?: string
  /** True if the stream was aborted by the caller. */
  aborted?: boolean
  /** Error message from the agent, if the stream ended with an error. */
  errorMessage?: string
  /** True if the stream was interrupted by a network error (agent may still be running). */
  disconnected?: boolean
}

/** Reads an SSE response stream, passing each line to the parser. */
export async function readSSEStream(
  response: Response,
  parser: ChunkParser,
  callback: StreamCallback,
  signal?: AbortSignal
): Promise<SSEStreamResult> {
  let buffer = ""
  let stopReason: string | undefined
  let errorMessage: string | undefined
  let aborted = false
  let disconnected = false

  // Tracks recent reads (timing, size, keepalive cadence) so an intermittent
  // disconnect can be diagnosed from console output after the fact.
  const startedAtMs = performance.now()
  let lastReadMs = startedAtMs
  let readCount = 0
  let keepaliveCount = 0
  let lastEventKind: string | undefined
  const readHistory: Array<{ elapsedMs: number; gapMs: number; bytes: number; preview: string }> =
    []
  const HISTORY_CAP = 20

  if (!response.body) {
    return {}
  }

  const wrappedCallback: StreamCallback = (event: StreamEvent) => {
    lastEventKind = event.type
    if (event.type === "result") {
      stopReason = event.stopReason
    }
    if (event.type === "error") {
      errorMessage = event.message
    }
    callback(event)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()

  const onAbort = () => {
    aborted = true
    reader.cancel().catch(() => {})
  }
  signal?.addEventListener("abort", onAbort, { once: true })

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      const now = performance.now()
      const chunk = decoder.decode(value, { stream: true })
      readCount += 1
      const gap = now - lastReadMs
      lastReadMs = now
      // Cheap substring check avoids re-parsing JSON just to count keepalives.
      if (chunk.includes('"keepalive"')) keepaliveCount += 1
      readHistory.push({
        elapsedMs: Math.round(now - startedAtMs),
        gapMs: Math.round(gap),
        bytes: value.byteLength,
        preview: chunk.slice(0, 80).replace(/\n/g, "\\n"),
      })
      if (readHistory.length > HISTORY_CAP) readHistory.shift()

      buffer += chunk

      const lines = buffer.split("\n")
      buffer = lines.pop() || ""

      for (const line of lines) {
        if (line.trim()) {
          parser(line, wrappedCallback)
        }
      }
    }

    if (buffer.trim()) {
      parser(buffer, wrappedCallback)
    }
  } catch (e) {
    if (!aborted) {
      // A network error here means the connection was severed, but the agent may
      // still be running server-side — treat as partial rather than fatal so the
      // UI can show what was received.
      const totalMs = Math.round(performance.now() - startedAtMs)
      const gapAtDropMs = Math.round(performance.now() - lastReadMs)
      console.warn("[SSE] Stream disconnected:", e)
      // ~60s total duration or a large gap-at-drop suggests an intermediate hop
      // dropped an idle connection; near-zero keepaliveCount means the backend
      // heartbeat isn't arriving.
      console.warn("[SSE] Disconnect diagnostics:", {
        totalMs,
        gapAtDropMs,
        readCount,
        keepaliveCount,
        lastEventKind,
        recentReads: readHistory,
      })
      disconnected = true
    }
  } finally {
    signal?.removeEventListener("abort", onAbort)
    reader.releaseLock()
    // Log a single summary on success so the happy path stays quiet.
    if (!aborted && !disconnected) {
      const totalMs = Math.round(performance.now() - startedAtMs)
      console.debug("[SSE] Stream complete:", {
        totalMs,
        readCount,
        keepaliveCount,
        stopReason,
      })
    }
  }

  return { stopReason, aborted, errorMessage, disconnected }
}
