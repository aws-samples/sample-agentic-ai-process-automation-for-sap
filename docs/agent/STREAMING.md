<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Streaming Guide for Agents

## Overview

The agent streams over **AG-UI**, a standard agent-to-UI event protocol. The Runtime is
configured with `ProtocolConfiguration: AGUI` and the agent emits canonical AG-UI events,
so the frontend consumes a stable contract instead of a parser written against a specific
framework's internals.

This replaces the earlier arrangement in which each agent framework needed its own SSE
parser registered in the frontend. Adding a framework now means emitting AG-UI events from
the backend; no frontend parser is required.

## Path of a turn

```
Browser                                    Autonomous
   |                                            |
   | invokeInteractiveRun()                     | agent_invoker (SQS consumer)
   |   POST /invocations                        |   POST /invocations
   |   Accept: text/event-stream                |   drains the stream, logs the
   |                                            |   terminal event
   v                                            v
AgentCore Runtime  (ProtocolConfiguration: AGUI)
   |
   | FastAPI /invocations  <- RunAgentInput
   | ag_ui_strands.StrandsAgent wraps the Strands agent
   | -> StreamingResponse of canonical AG-UI events
   v
Frontend
   aguiReducer.reduceAguiEvent()  -> AguiProjection
   WorkspacePage renders projection.messages
```

Both callers send the same `RunAgentInput` body. ERP-specific fields travel in
`forwardedProps.erpPayload`, which is where the agent reads them; the prompt is also placed
in the AG-UI message history so the turn is well formed.

## Backend

**File:** `agentcore/agent/basic_agent.py`

The FastAPI entry point accepts a `RunAgentInput` and returns a `StreamingResponse`:

```python
@app.post("/invocations")
async def agent_stream(input_data: RunAgentInput, request: Request) -> StreamingResponse:
    encoder = EventEncoder(accept=request.headers.get("accept"))
    ...
```

`ag_ui_strands.StrandsAgent` adapts the Strands agent to AG-UI, so event emission is
handled by the adapter rather than by hand.

The Runtime advertises AGUI through a CDK property override in
`cdk/lib/backend-stack.ts`: the alpha L2 construct exposes HTTP/MCP/A2A but not the
service's AGUI enum, so `ProtocolType.HTTP` satisfies the construct type and the
synthesized L1 is overridden.

## Frontend

| File | Responsibility |
|------|----------------|
| `frontend/src/services/agentRuntimeService.ts` | POSTs `RunAgentInput`, reads the SSE stream, splits events, returns the terminal event |
| `frontend/src/lib/aguiReducer.ts` | Pure reducer folding one event into an `AguiProjection` |
| `frontend/src/routes/WorkspacePage.tsx` | Owns the projection, renders `projection.messages` |

The reducer is a pure function, so rendering is a function of the event sequence rather
than accumulated mutation. That is also what makes it directly testable —
see `frontend/src/test/agui-reducer.test.ts`.

## Events handled

| Event | Effect on the projection |
|-------|--------------------------|
| `RUN_STARTED` | Emitted by the agent; no projection change |
| `TEXT_MESSAGE_START` | Ensures an assistant message exists |
| `TEXT_MESSAGE_CONTENT` | Appends the text delta |
| `TOOL_CALL_START` | Adds a tool call in `streaming` |
| `TOOL_CALL_ARGS` | Appends to the tool call's input |
| `TOOL_CALL_END` | Moves `streaming` to `executing` |
| `TOOL_CALL_RESULT` | Records the result, marks `complete` |
| `MESSAGES_SNAPSHOT` | Replaces message content and tool calls from the snapshot |
| `STATE_SNAPSHOT` | Replaces projection state |
| `RUN_FINISHED` | Settles unresolved tool calls |
| `RUN_ERROR` | Settles unresolved tool calls and appends an error message |

AG-UI defines only these two terminal events — there is no cancelled event. A
deliberate stop, such as the agent reaching its turn limit, is reported as `RUN_ERROR`
carrying a code (`MAX_TURNS_REACHED`), which the reducer renders as a warning rather
than a failure.

### Unconfirmed tool calls

A tool call that never receives a `TOOL_CALL_RESULT` settles as `incomplete`, not as
complete or failed. For a side-effecting tool the call may have succeeded server-side, so
the UI asks for verification rather than inviting a retry that could duplicate the effect.
The same settling applies when the stream ends without any terminal event.

## Known gap: interrupt and resume

The AG-UI adapter has no interrupt/resume mapping, so the SAP sign-in flow does not pause
and resume a tool mid-run. The sign-in affordance still works, because it renders from the
tool *result* rather than from the transport: an `authentication_required` result surfaces
the button, and after sign-in the prompt is replayed. The interrupt-driven banner in
`WorkspacePage.tsx` is currently unreachable and is left in place pending that mapping.

`SAP_AUTH_INTERRUPT` gates the agent-side wrappers and is not set by the CDK, so the
interrupt path is off by default.

## Keepalive

A single SAP OData call can leave the stream idle for minutes, and an intermediate hop
will drop an idle connection — the failure this migration sits on top of. The agent
interleaves an SSE **comment** heartbeat every 15 seconds, plus one immediately when the
stream opens:

```
: keepalive 3 45000
```

The fields are a monotonic sequence number and elapsed milliseconds, so a disconnect can
be correlated with the heartbeat that should have followed it. A comment carries no
`data:` line, so `decodeEvent` returns `null` and nothing reaches the reducer — no AG-UI
event type is involved and no client has to know about it.

`_with_keepalive` in `basic_agent.py` interleaves the ticks from outside the adapter's
event loop, since `ag_ui_strands` owns that loop. A source failure still propagates, and
closing the stream early cancels both the heartbeat and the agent. `add_ping(app, "/ping")`
is unrelated — that is a `GET` health route, not a stream heartbeat.

## Debugging

Log events as they are reduced, in the stream callback in `WorkspacePage.tsx`:

```ts
console.log("[AG-UI]", event.type, event)
```

For the autonomous path, the invoker logs the run id and terminal event:

```
Agent response: 200 (14823 bytes) run=<uuid> terminal=RUN_FINISHED
```

`terminal=none` means the stream ended without a terminal event — the run may still be
in flight server-side. HTTP 200 alone does not distinguish a completed run from a
failed one, which is why the terminal event is logged.
