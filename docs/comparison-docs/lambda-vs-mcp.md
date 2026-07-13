<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Lambda Direct Invocation vs MCP Server for Agent Tools

## Summary

Should the agent call tools via a managed MCP server (AgentCore Gateway wrapping Lambdas), direct Lambda invocation, or a self-hosted MCP server process?

## Comparison

| Dimension | Direct Lambda | Gateway (Lambda targets) | Self-Hosted MCP Server |
|---|---|---|---|
| Token overhead | Lowest — tool def + response only | Low — MCP protocol adds ~5% | Highest — MCP session + protocol + tool discovery |
| Latency | ~50–200ms (cold/warm) | ~100–300ms (Gateway + Lambda) | ~50ms warm, but session setup adds overhead |
| Auth | IAM only (SigV4) | OAuth2/JWT inbound, IAM outbound | You implement (Cognito, mTLS, etc.) |
| Observability | CloudWatch per Lambda | Built-in tracing + CloudWatch | You implement |
| Semantic tool search | No | Yes — `x_amz_bedrock_agentcore_search` | No |
| MCP spec coverage | N/A — not MCP | tools/list, tools/call only | Full spec (resources, prompts, sampling) |
| Cross-tool state | Isolated per Lambda | Isolated per Lambda | Shared in-process |
| Scaling | Per-function concurrency | Per-function concurrency | Per-container |
| Local dev | `sam local invoke` | Deploy or mock | Single process, easy to debug |
| Protocol boilerplate | None | None (Gateway handles it) | You implement JSON-RPC |
| Cedar policy support | No | Yes | No |

## When to use each

**Direct Lambda** — Best for:
- High-volume deterministic operations (month-end batch of 1,000+ POs)
- Cost-sensitive workloads where token overhead matters
- Simple tool sets (<5 tools) with no discovery needs
- Step Functions orchestration (Lambda is a native integration)

**Gateway with Lambda targets** — Best for:
- Production agents that need managed auth, observability, and governance
- Growing tool catalogs where semantic search helps the model pick the right tool
- Teams that want MCP compatibility without implementing the protocol
- Multi-agent architectures where tools are shared across agents

**Self-Hosted MCP Server** — Best for:
- Tools requiring shared in-process state (connection pools, caches)
- Full MCP spec needs (resources, prompts, sampling)
- Design-time exploration of unfamiliar systems
- Rapid prototyping before production architecture is defined

## This project's approach

We use **Gateway with Lambda targets** for the agent's homegrown runtime tools (case management, notifications, knowledge-base search; see [ADR-001](../design-decisions/001-gateway-over-self-hosted-mcp.md)). SAP OData is reached through the external AWS for SAP MCP server, registered as a Gateway MCP target rather than a homegrown Lambda — see [ADR-012](../design-decisions/012-sap-mcp-server-integration.md).

## Token overhead reference

Measured on the PO Accrual workflow (single case, 4 tool calls):

| Approach | Approximate tokens | Relative |
|---|---|---|
| Direct Lambda (tool_use) | ~1,200 | 1x |
| Gateway (MCP over Lambda) | ~1,260 | 1.05x |
| Self-hosted MCP (full session) | ~4,500+ | 3.8x |

The 3.8x overhead for self-hosted MCP comes from: session initialization, tool discovery round-trip, JSON-RPC framing, and auth token exchange in-band.
