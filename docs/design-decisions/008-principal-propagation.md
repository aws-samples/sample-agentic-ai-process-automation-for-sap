# ADR-008: SAP Identity Modes

> ⚠️ **HISTORICAL — superseded by ADR-012.** The four-mode SAP identity taxonomy and the identity interceptor described here were removed; SAP identity is now handled by the external AWS for SAP MCP server. Retained for historical context. See [ADR-012](012-sap-mcp-server-integration.md).

## Status
Accepted (revised) — superseded by ADR-012

## Context

The agent authenticated to SAP OData on behalf of two principals: a **machine** (pollers, scheduled jobs — SAP sees a service account) and a **human** (user clicks "Process" — SAP should see the actual user for audit and authorization). Different SAP topologies (S/4HANA Cloud, BTP ABAP, on-prem ECC/S4, RISE on AWS) support different propagation mechanisms — some OIDC (JWT), some X.509 cert mapping, some neither without extra config.

## Decision

Four identity modes selected via `sap.identity_mode` in `config.yaml`:

| Mode | SAP sees | Mechanism |
|---|---|---|
| `service-account` | Machine user | Basic Auth from Secrets Manager (default) |
| `mtls` | Machine user | Client cert from ACM + Basic Auth |
| `oidc-passthrough` | Actual human | Forward user's JWT; SAP validates via JWKS |
| `principal-propagation` | Actual human | Ephemeral X.509 cert (CN=user); SAP maps via CERTRULE |

A single deployment used multiple modes at once: event-driven Lambdas always used a machine mode (no user context exists); user-initiated Gateway calls used the configured user-identity mode when a token was present, falling back to service-account otherwise. Mode was resolved per-request in the shared `sap_auth` layer, and user-identity propagation was infrastructure-enforced by a Gateway interceptor Lambda the agent could not bypass.

## Why superseded

ADR-012 consolidated all SAP access onto the external AWS for SAP MCP server. The interceptor, the two user-identity modes, and the per-request mode resolution were removed; the `odata_poller` retains service-account basic auth as its only direct-to-SAP path. The alternatives rejected at the time (single service account, SAP-side impersonation, SAML assertion forwarding) are recorded here for completeness.
