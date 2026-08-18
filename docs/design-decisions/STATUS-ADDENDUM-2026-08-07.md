# ADR Catalog Status Addendum — 2026-08-07

## Purpose

This dated addendum records the current applicability of historical ADRs without changing their original text, dates, or prior addenda. Where a record named below conflicts with this addendum, this addendum is authoritative **only for the stated current-status mapping**. The original ADR remains the historical account of its decision.

Future catalog corrections MUST add a new dated status addendum rather than revise an existing ADR or status addendum.

## Status terminology

Auth-profile status has independent dimensions:

- **Deployable:** every selected axis has repository wiring and is in `profiles`.
- **Verified:** the exact profile has `verified: true` after a live SAP end-to-end run.
- **Maturity:** hardening breadth, independent of deployability and verification.
- **Stub / blocked by:** an unresolved axis and its owner (`repo`, `operator`, or `upstream`).

`auth-profiles.yaml` is the current source of truth for those signals. This addendum does not treat an implemented adapter, a configured IdP, or a passing unit test as proof that every profile has completed a live SAP run.

## Current status mapping

| Historical ADR | Current status | Current interpretation |
|---|---|---|
| [ADR-002](002-two-layer-sap-api-knowledge.md) | Accepted — partly superseded | The Layer 1 purpose/process documentation KB remains applicable. ADR-013 supersedes the OpenSearch Serverless vector-store choice. ADR-012 supersedes the Layer 2 homegrown metadata scanner, generated per-entity specs, CloudFront path, and related lookup tools: runtime SAP service and metadata discovery now use the external AWS for SAP MCP server's discovery and metadata tools. |
| [ADR-012](012-sap-mcp-server-integration.md) | Accepted/implemented — external-only adapter and sole SAP tool path; verification is profile-specific | The external AWS for SAP MCP server remains the sole agent-driven SAP path. Current auth-profile evidence is profile-specific: `cognito-basic` and `entra-obo` are verified; `cognito-m2m` and `cognito-m2m-batch` are deployable but not marked verified; `okta-basic` is deployable with proven frontend/inbound axes but has no verified live-SAP run and uses a technical Basic SAP identity; user-federation profiles remain preview because their outbound axis is stubbed. |

## Related decisions

- [ADR-013](013-s3-vectors-over-aoss.md) supersedes ADR-002's vector-store choice.
- [ADR-015](015-batch-recovery-sweeper.md) records the batch recovery path used by `cognito-m2m-batch`.
- [ADR-016](016-sop-quotation-evidence.md) records the runtime evidence contract for SOP citations.
- [ADR-017](017-server-owned-case-audit-fields.md) records case-record audit-field ownership.

## Evidence

- Current auth profile catalog: `auth-profiles.yaml`
- SAP MCP integration: [ADR-012](012-sap-mcp-server-integration.md)
- SAP knowledge-base history: [ADR-002](002-two-layer-sap-api-knowledge.md)
- S3 Vectors replacement: [ADR-013](013-s3-vectors-over-aoss.md)
