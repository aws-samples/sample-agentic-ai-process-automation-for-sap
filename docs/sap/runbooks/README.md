<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# SAP Auth Operator Runbooks

Per-flow SAP-side operator runbooks for the auth matrix's outbound flows. Each documents the
SAP-side trust plus the AWS/AgentCore and identity-provider steps for one flow, and opens with a
status note. The status column below comes from `auth-profiles.yaml`.

| Runbook | Flow | Transport | Status in this sample | One-line |
|---|---|---|---|---|
| [soidc-entra-obo.md](./soidc-entra-obo.md) | **OBO / `ON_BEHALF_OF_TOKEN_EXCHANGE`** (direct-to-MCP) | Direct-to-MCP | Run end to end (`obo`, `maturity: preview`) | Per-user OBO: Direct-Entra → server-side exchange → SAP, no second sign-in. |
| [m2m-oauth2-sap.md](./m2m-oauth2-sap.md) | **M2M via SAP SOAUTH2 client-credentials** / M2M via an external IdP | `M2M` (Gateway) | SAP SOAUTH2: `m2m-sap`, `maturity: ga`. External IdP: `m2m-oidc`, not yet run end to end | Machine identity. SAP as the OAuth server, or an external IdP with a SOIDC trust. |
| [uf-oidc.md](./uf-oidc.md) | **USER_FEDERATION (OIDC)** | `USER_FEDERATION` (OIDC) | Not yet run end to end (`user-federation`, `status: stub`) | Interactive per-user via an external **OIDC** IdP (Entra/Okta); SAP validates via SOIDC. The base USER_FEDERATION case. |
| [uf-saml.md](./uf-saml.md) | **USER_FEDERATION (SAML)** | `USER_FEDERATION` (SAML) | Not yet run end to end (`user-federation`, `status: stub`) | Interactive per-user via a **SAML** IdP (Entra/Okta); SAP is the SAML service provider and its own OAuth server, so AgentCore handles only OAuth. |
| [uf-oauth2-sap.md](./uf-oauth2-sap.md) | **USER_FEDERATION with SAP as its own OAuth authorization server** | `USER_FEDERATION` (SAP as OAuth server) | Not yet run end to end (`user-federation`, `status: stub`) | AWS User Federation Pattern 1: interactive per-user with no external IdP; SAP's own OAuth client issues each user's token. |

**Not (yet) runbooks:** BASIC (service-account) auth is your base SAP system configuration;
Okta inbound reuses the OIDC USER_FEDERATION (Okta) outbound; the batch / autonomous flows need no
SAP-side steps of their own — they reach SAP as the technical user, so the BASIC/M2M configuration
already covers them; frontend SAML/OIDC federation is a **frontend** concern (not yet built) whose SAP-side reuses the OIDC and SAML USER_FEDERATION runbooks.

**Shared background (read first):** your base SAP OData connectivity and service-user setup (the
SU01 user + PFCG authorizations + SICF activation), the deploy model / env-var contract for the
AWS-for-SAP MCP container, and the interactive USER_FEDERATION mechanics (auth-URL handoff, the two
callback URLs). Each runbook cross-links the sibling runbooks it builds on.
