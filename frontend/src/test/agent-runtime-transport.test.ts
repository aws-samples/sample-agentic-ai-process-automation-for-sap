// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import {
  AgentRuntimeStartError,
  invokeInteractiveRun,
  type InteractiveRunRequest,
} from "@/services/agentRuntimeService"
import type { AguiEvent } from "@/lib/aguiReducer"

vi.mock("@/lib/config", () => ({
  getConfig: () =>
    Promise.resolve({
      agentRuntimeArn: "arn:aws:bedrock-agentcore:us-east-1:1:runtime/test",
      awsRegion: "us-east-1",
    }),
}))

const encoder = new TextEncoder()

function streamOf(chunks: string[], status = 200): Response {
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        chunks.forEach(chunk => controller.enqueue(encoder.encode(chunk)))
        controller.close()
      },
    }),
    { status }
  )
}

const REQUEST: InteractiveRunRequest = {
  message: "process the accrual",
  threadId: "thread-1",
  runtimeSessionId: "thread-1",
  runId: "run-1",
}

async function run(response: Response): Promise<AguiEvent[]> {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response))
  const seen: AguiEvent[] = []
  await invokeInteractiveRun(REQUEST, "token", event => seen.push(event))
  return seen
}

describe("AG-UI transport — keepalive handling", () => {
  beforeEach(() => vi.restoreAllMocks())
  afterEach(() => vi.unstubAllGlobals())

  it("ignores heartbeat comments and still projects real events", async () => {
    // The agent interleaves `: keepalive <seq> <ms>` comments to keep an idle
    // connection warm. They must never reach the reducer.
    const seen = await run(
      streamOf([
        ": keepalive 0 0\n\n",
        'data: {"type":"RUN_STARTED","threadId":"thread-1","runId":"run-1"}\n\n',
        ": keepalive 1 15000\n\n",
        ": keepalive 2 30000\n\n",
        'data: {"type":"TEXT_MESSAGE_CONTENT","messageId":"m1","delta":"hello"}\n\n',
        'data: {"type":"RUN_FINISHED","threadId":"thread-1","runId":"run-1"}\n\n',
      ])
    )

    expect(seen.map(event => event.type)).toEqual([
      "RUN_STARTED",
      "TEXT_MESSAGE_CONTENT",
      "RUN_FINISHED",
    ])
  })

  it("tolerates a heartbeat split across chunk boundaries", async () => {
    const seen = await run(
      streamOf([
        ": keepa",
        "live 1 15000\n",
        "\n",
        'data: {"type":"RUN_FINISHED","threadId":"t","runId":"r"}\n\n',
      ])
    )

    expect(seen.map(event => event.type)).toEqual(["RUN_FINISHED"])
  })

  it("a heartbeat alone does not satisfy the terminal-event requirement", async () => {
    // Otherwise a stream that only ever heartbeats would look like a completed run.
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(streamOf([": keepalive 1 15000\n\n"])))

    await expect(invokeInteractiveRun(REQUEST, "token", () => {})).rejects.toThrow(
      /without a terminal AG-UI event/i
    )
  })
})

describe("AG-UI transport — start failures are distinguishable", () => {
  beforeEach(() => vi.restoreAllMocks())
  afterEach(() => vi.unstubAllGlobals())

  it("throws AgentRuntimeStartError when the invocation is rejected", async () => {
    // The caller reports a rejected request differently from a broken stream, so the
    // two must be distinguishable by type rather than by whether events arrived.
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(streamOf([], 403)))

    await expect(invokeInteractiveRun(REQUEST, "token", () => {})).rejects.toBeInstanceOf(
      AgentRuntimeStartError
    )
  })

  it("a mid-stream failure is not a start error", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          streamOf(['data: {"type":"RUN_STARTED","threadId":"t","runId":"r"}\n\n'])
        )
    )

    const failure = await invokeInteractiveRun(REQUEST, "token", () => {}).catch(err => err)

    expect(failure).toBeInstanceOf(Error)
    expect(failure).not.toBeInstanceOf(AgentRuntimeStartError)
  })
})
