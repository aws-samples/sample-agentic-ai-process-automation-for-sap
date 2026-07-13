# ADR-001: AgentCore Gateway Lambda Targets over Self-Hosted MCP Server

> **Note:** This decision (use Gateway over self-hosting) remains valid. [ADR-012](012-sap-mcp-server-integration.md) finalizes the SAP path — the Gateway now routes to the external AWS for SAP MCP server target rather than homegrown Lambda SAP tools.

**Status:** Accepted  
**Date:** 2026-03-19

## Context

The original PoC used a single FastMCP server process hosting all agent tools (SAP OData, case management, email, knowledge base). For the production migration, we needed to decide between:

1. **Self-hosted MCP server** on AgentCore Runtime (containerized FastMCP)
2. **AgentCore Gateway** with individual Lambda function targets per tool domain

## Decision

Use AgentCore Gateway with Lambda targets.

## Rationale

**What Gateway provides that we'd otherwise build ourselves:**
- MCP protocol layer (initialize, tools/list, tools/call) — zero implementation
- OAuth2 inbound auth (Cognito, Okta, etc.) with JWT validation
- Serverless scaling per tool, not per container
- Built-in observability and audit logging
- Semantic tool search for agent tool discovery
- Cedar policy integration for fine-grained authorization

**Why it fits this use case:**
- Our tools are cleanly separated by domain (SAP API, DynamoDB state, SES email, Bedrock KB)
- Each tool call is a discrete, stateless operation
- Tool count is moderate (~15-20), not requiring semantic search but benefiting from it
- Production auth is a hard requirement — Gateway provides it out of the box
- The FAST template (our project foundation) has Gateway CDK wiring built in

## Tradeoffs

| Aspect | Gateway + Lambda | Self-Hosted MCP Server |
|---|---|---|
| MCP spec coverage | tools/list, tools/call only | Full spec (resources, prompts, sampling) |
| Cross-tool state | Each Lambda is isolated | Shared in-process state possible |
| Local development | Deploy or mock each Lambda | Single process to run/debug |
| Auth | Managed (Cognito/OAuth2) | You implement it |
| Scaling | Per-tool (Lambda concurrency) | Per-container |
| Protocol boilerplate | None | You implement JSON-RPC layer |
| Hosting | Fully managed | You manage Runtime containers |

**Key tradeoff acknowledged:** The original MCP server could share state across SAP API calls (e.g., CSRF tokens). With Gateway, each Lambda manages its own token lifecycle. This added ~20 lines per Lambda but eliminated the shared-state coupling.

## Reversibility

This is not a one-way door. Gateway supports MCP servers hosted on AgentCore Runtime as targets. If we later need full MCP capabilities (resources, prompts, shared process state), we can add a self-hosted MCP server behind the same Gateway endpoint without changing the agent's connection.

## References

- [AgentCore Gateway Developer Guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html)
- [FAST Template — Gateway Documentation](../agent/GATEWAY.md)
