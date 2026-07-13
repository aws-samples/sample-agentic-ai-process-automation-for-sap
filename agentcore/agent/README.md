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

- **Agent**: `us.anthropic.claude-sonnet-4-5-20250929-v1:0` (Sonnet via Bedrock)

## Streaming Events

The agent yields SSE `data: {json}` lines via `agent.stream_async()`. The frontend parser at `frontend/src/lib/agentcore-client/parsers/strands.ts` handles these event types:

| Event | Format | Description |
|-------|--------|-------------|
| Text | `{"data": "text"}` | Token-level text content |
| Tool use start | `{"current_tool_use": {...}, "delta": {"toolUse": {"input": ""}}}` | Tool invocation begins |
| Tool use delta | `{"current_tool_use": {...}, "delta": {"toolUse": {"input": "..."}}}` | Streaming tool input |
| Tool result | `{"message": {"role": "user", "content": [{"toolResult": {...}}]}}` | Tool execution result |
| Result | `{"result": {"stop_reason": "end_turn"}}` | Agent finished |
| Lifecycle | `{"init_event_loop": true}` / `{"start_event_loop": true}` | Agent lifecycle events |

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

```
strands-agents==1.24.0
mcp==1.26.0
bedrock-agentcore[strands-agents]==1.2.0
PyJWT[crypto]>=2.10.1
```
