# ADR-010: Identity and Audit Context Architecture

> ⚠️ **HISTORICAL — partly superseded by ADR-012.** The SQS `sap_write` consumer and the identity interceptor code paths described here were removed; the four-mode SAP identity taxonomy is gone and SAP is reached exclusively through the external AWS for SAP MCP server. The audit-context concept is now partly historical. Retained for historical context. See [ADR-012](012-sap-mcp-server-integration.md).

**Status:** Accepted — partly superseded by ADR-012
**Date:** 2025-04-27
**Related:** [ADR-008: SAP Identity Modes](008-principal-propagation.md)

## Context

With four identity modes ([ADR-008](008-principal-propagation.md)) and multiple code paths calling SAP (frontend, agent_invoker, odata_poller, sap_write_consumer), two problems arose:

1. **Identity loss at the SQS boundary.** A user-initiated write enqueued to SQS FIFO; the consumer Lambda had no user context — the JWT wasn't in the message, and would likely have expired anyway.
2. **No audit trail for machine-initiated actions.** Poller/invoker paths used service-account creds, so SAP's log showed the machine user with no record of what triggered the action.

## Decision

Separate **authentication** (who makes the HTTP call) from **audit baggage** (who initiated the business action). Every SAP-bound request carried both, via an audit context (`correlation_id`, `initiator`, `trigger`) mapped onto SAP headers:

| Header | Purpose |
|--------|---------|
| `x-correlationid` | SAP-standard distributed trace ID (captured by Cloud ALM, SM20) |
| `x-sap-ext-initiator` | Custom: who initiated the action |
| `x-sap-ext-trigger` | Custom: what triggered it |

Audit context was orthogonal to identity mode — essential for `service-account`/`mtls` (the only way to trace a machine-executed action back to its human/system initiator), redundant-but-useful for the user-identity modes.

### Write Identity Gap (Accepted)

Writes always used machine authentication regardless of identity mode: a user's Bearer token can't reliably cross the SQS boundary (JWTs expire, no refresh token, storing tokens in SQS is a security surface). The audit baggage recorded the human initiator — the standard enterprise pattern of a technical communication user performing writes. Enterprises needing user-level auth on writes had two documented customization paths: synchronous writes (skip SQS) or a token-exchange service.

## Why partly superseded

ADR-012 moved SAP access to the external MCP server, removing the `sap_write` SQS consumer, the identity interceptor, and the four-mode taxonomy. The audit-context idea (attributing machine-executed SAP actions to their initiator) remains conceptually relevant but its implementation here is historical.
