# ADR-011: Retain Lambda-in-VPC and Identity Interceptor After Gateway VPC Egress Launch

> ⚠️ **STATUS UPDATE — partly superseded by ADR-012.** The identity interceptor Lambda this ADR recommended retaining has since been **removed**; SAP identity is now handled by the external AWS for SAP MCP server. The Lambda-in-VPC pattern is retained, but only for the `odata_poller` (service-account, basic auth). Retained for historical context. See [ADR-012](012-sap-mcp-server-integration.md).

**Status:** Accepted — partly superseded by ADR-012
**Date:** 2026-04-28

## Context

April 2026's AgentCore Gateway/Identity VPC egress launch (Gateway routing to private MCP/OpenAPI targets; JWT authorizer validating against a private IdP) prompted two questions: should we replace Lambda-in-VPC with Gateway VPC egress for private SAP endpoints, and does the launch eliminate our custom identity interceptor Lambda?

## Decision

**No architectural changes.** Retain Lambda-in-VPC for SAP connectivity and the identity interceptor for token propagation.

## Rationale

- **Gateway VPC egress didn't apply to our targets.** It supports MCP-server and OpenAPI target types; our Gateway targets were Lambda functions. Lambda targets already reach the VPC out-of-the-box (Gateway → Lambda-in-VPC → SAP OData), so VPC egress added nothing for us.
- **The interceptor was still required.** The built-in JWT authorizer only gates *inbound* access; it doesn't forward the token downstream. Gateway's outbound auth options (IAM/SigV4, OAuth client-credentials, API key) had no "forward the inbound user's JWT to the target" mode — exactly what the interceptor did for `oidc-passthrough` and `principal-propagation`.
- **Identity VPC egress was additive** — it helps customers with private IdPs use the built-in authorizer for inbound auth, but doesn't change outbound identity propagation.

Conditions that *would* have changed this: Gateway adding a token-passthrough outbound mode, native OpenAPI/MCP SAP OData targets with VPC egress, or refactoring SAP tools into a standalone MCP server.

## Why partly superseded

ADR-012 took the third path — SAP access moved to the external AWS for SAP MCP server — so the interceptor was removed. Lambda-in-VPC survives only for the `odata_poller` (service-account, basic auth).

## References

- [Gateway VPC Egress for Targets](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-vpc-egress.html)
- [Gateway Interceptors](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-interceptors.html)
- [ADR-001](001-gateway-over-self-hosted-mcp.md) · [ADR-008](008-principal-propagation.md) · [ADR-010](010-identity-audit-context.md)
