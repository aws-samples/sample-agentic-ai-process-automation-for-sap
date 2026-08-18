<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Strands Single Agent Pattern

This pattern uses the [Strands Agents](https://github.com/strands-agents/strands-agents) framework to build an agent with Gateway tool access and AgentCore Memory for conversation history.

## Features

- **Token-Level Streaming**: True token-by-token streaming via `agent.stream_async()`
- **AgentCore Memory**: Conversation history persisted across requests via `AgentCoreMemorySessionManager`
- **Gateway Integration**: Access Lambda-based tools through AgentCore Gateway (MCP protocol with OAuth2 auth)
- **Secure Identity**: User identity extracted from validated JWT token (`RequestContext`), not from payload

## Architecture

```
User Request
    |
BedrockAgentCoreApp (basic_agent.py)
    |
Strands Agent (Sonnet model via BedrockModel)
    |
    +-- AgentCore Memory (conversation history)
    |     AgentCoreMemorySessionManager
    |
    +-- Gateway MCP Client (streamable HTTP)
          Lambda-based tools via AgentCore Gateway
```

## File Structure

```
agent/
├── basic_agent.py                # Main entrypoint (BedrockAgentCoreApp)
├── utils/                        # Auth, metrics, skill routing, content filtering
├── requirements.txt              # Pinned dependencies
└── Dockerfile                    # Container build (Python 3.13)
```

## Available Tools

| Tool | Source | Description |
|------|--------|-------------|
| Gateway tools | AgentCore Gateway | Lambda-based tools discovered via MCP |
| `calculator`, `current_time` | Strands built-ins | Deterministic math and clock |

## Model

- **Agent**: `us.anthropic.claude-sonnet-5` (Sonnet via Bedrock)

## Streaming Events

The agent emits canonical **AG-UI** events; the Runtime is configured with
`ProtocolConfiguration: AGUI`. `ag_ui_strands.StrandsAgent` adapts the Strands agent, so
events are produced by the adapter rather than hand-serialized. The frontend folds them
into chat state with the pure reducer at `frontend/src/lib/aguiReducer.ts`.

| Event | Description |
|-------|-------------|
| `RUN_STARTED` | Run accepted and begun |
| `TEXT_MESSAGE_START` / `TEXT_MESSAGE_CONTENT` | Assistant message and token-level deltas |
| `TOOL_CALL_START` / `TOOL_CALL_ARGS` / `TOOL_CALL_END` | Tool invocation and streaming input |
| `TOOL_CALL_RESULT` | Tool execution result |
| `MESSAGES_SNAPSHOT` / `STATE_SNAPSHOT` | Full message or state replacement |
| `RUN_FINISHED` / `RUN_ERROR` | Terminal outcome. A deliberate stop, such as the turn limit, arrives as `RUN_ERROR` with a code |

See `docs/agent/STREAMING.md` for the full contract, the autonomous path, and the
interrupt/resume gap.

## Memory Integration

This pattern uses **AgentCore Memory** for conversation persistence:

1. `MEMORY_ID` environment variable provides the memory resource ID
2. `AgentCoreMemoryConfig` is initialized with `memory_id`, `session_id`, and `actor_id` (user ID)
3. `AgentCoreMemorySessionManager` handles storing/retrieving conversation history
4. Memory is tied to the `runtimeSessionId` from the client

## Security

- **User identity**: Extracted from the validated JWT token via `RequestContext`, not from the payload body
- **STACK_NAME validation**: Validated for alphanumeric format before use in SSM parameter paths
- **Payload validation**: Required fields (`prompt`, `runtimeSessionId`) validated before processing
- **Gateway auth**: OAuth2 client credentials flow via Cognito for machine-to-machine authentication

## Deployment

```bash
cd cdk
# Set pattern in config.yaml:
#   backend:
#     pattern: agent
#     deployment_type: zip  # or docker
cdk deploy
```

Both ZIP (default, no Docker needed) and Docker deployment types are supported.

## Dependencies

`requirements.txt` is authoritative — it is what the Dockerfile installs. The
headline pins:

```
strands-agents==1.50.2
mcp==1.29.0
bedrock-agentcore[strands-agents]==1.19.0
ag-ui-strands==0.2.3
PyJWT[crypto]>=2.10.1
```
