<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# SAP Auth Operator Runbooks

Per-flow SAP-side operator runbooks for the auth matrix's outbound flows. Each documents the
SAP-side trust delta plus the AWS/AgentCore and identity-provider steps for one flow. All carry a
status banner; the whole SAP-MCP integration is **reference design, not yet run end-to-end**
against a production SAP system except where a runbook states otherwise.

Each runbook was verified against current AWS/Microsoft/SAP docs; the
verdict is noted below because it changes how you should read the doc.

| Runbook | Flow | Transport | Verify gate | One-line |
|---|---|---|---|---|
| [soidc-entra-obo.md](./soidc-entra-obo.md) | **OBO / `ON_BEHALF_OF_TOKEN_EXCHANGE`** (direct-to-MCP) | Direct-to-MCP | **SUPPORTED** | Seamless per-user OBO: Direct-Entra → server-side exchange → SAP, no second login. The flagship OBO path. |
| [m2m-oauth2-sap.md](./m2m-oauth2-sap.md) | **M2M via SAP SOAUTH2 client-credentials** / M2M via an external IdP | `M2M` (Gateway) | SAP SOAUTH2 solid / external-IdP **UNCLEAR** | Machine identity. M2M via SAP SOAUTH2 client-credentials (SAP-as-OAuth-server) is GA/deploys-today; M2M via an external IdP (preview) behind a risk callout. |
| [uf-oidc.md](./uf-oidc.md) | **USER_FEDERATION (OIDC)** | `USER_FEDERATION` (OIDC) | SUPPORTED (base UF case) | Interactive per-user via an external **OIDC** IdP (Entra/Okta); SAP validates via SOIDC. Prefer Okta (email `sub`). |
| [uf-saml.md](./uf-saml.md) | **USER_FEDERATION (SAML)** | `USER_FEDERATION` (SAML) | **UNCLEAR** (mechanism-corrected) | Interactive per-user via a **SAML** IdP (Entra/Okta); SAP is the SAML SP behind an **OAuth bridge** — AgentCore never sees SAML. |
| [uf-oauth2-sap.md](./uf-oauth2-sap.md) | **USER_FEDERATION with SAP as its own OAuth authorization server** | `USER_FEDERATION` (SAP-direct) | **REFUTED** | "SAP-direct, no IdP" is **not** a documented UF topology — documents why, and the two real realizations (SAML-redirect / OIDC). |

**Not (yet) runbooks:** BASIC (service-account) auth is your base SAP system configuration;
Okta inbound reuses the OIDC USER_FEDERATION (Okta) outbound; the batch / autonomous flows need no
SAP-side steps of their own — they reach SAP as the technical user, so the BASIC/M2M configuration
already covers them; frontend SAML/OIDC federation is a **frontend** concern (planned / not yet
built) whose SAP-side reuses the OIDC and SAML USER_FEDERATION runbooks.

**Shared background (read first):** your base SAP OData connectivity and service-user setup (the
SU01 user + PFCG authorizations + SICF activation), the deploy model / env-var contract for the
AWS-for-SAP MCP container, and the interactive USER_FEDERATION mechanics (auth-URL handoff, the two
callback URLs). Each runbook cross-links the sibling runbooks it builds on.
