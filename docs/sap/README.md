<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# SAP Documentation

How the agent connects to SAP. SAP machine identity is **service-account only** (Basic Auth);
all OData read/write/discovery goes through the external **AWS for SAP MCP server**, and the
autonomous OData poller is the only component that calls SAP directly.

## Reading order

0. [**Choosing an Auth Profile**](AUTH_PROFILE_SELECTION.md) — which profile, the single knob to set,
   deploys-today vs preview, and the Terraform scope boundary.
1. [Connectivity & Auth](CONNECTIVITY_AND_AUTH.md) — identity model, networking
   scenarios, frontend auth providers, Gateway write enforcement.
2. [SAP Basic Setup](SAP_SETUP.md) — configure `base_url`, deploy, sync service-account
   credentials, test the connection.
3. [SAP System Configuration](SAP_SYSTEM_CONFIGURATION.md) — SAP-side: service-account user +
   OData service activation.
4. [SAP MCP Integration](SAP_MCP_INTEGRATION.md) — the external AWS for SAP MCP server (Gateway
   target + OAuth2 provider adapter); machine-identity `BASIC`/`M2M` flows.

> **Deploys today vs preview.** Only the `cognito-basic` (default) and `cognito-m2m` auth profiles
> have built IaC and deploy end-to-end — items 1–4 above cover them. The interactive per-user paths
> below (items 5–10, the `preview_profiles` in `auth-profiles.yaml`) are **preview**: the topology is
> modeled and validated, but the provisioning modules are not built yet. Treat those runbooks as
> reference designs for the roadmap, not ready-to-run procedures.

If you need interactive per-user SAP auth:

> New to the flows? Read [Token Mechanics](TOKEN_MECHANICS.md) first — it distinguishes
> passthrough vs OBO exchange vs USER_FEDERATION vs M2M, and untangles the "OBO" naming overload.

5. [SAP MCP User Federation](SAP_MCP_USER_FEDERATION.md) — interactive per-user **3-legged** login via
   the MCP server's `USER_FEDERATION` flow (distinct from the `ON_BEHALF_OF_TOKEN_EXCHANGE` OBO flow —
   see [Token Mechanics](TOKEN_MECHANICS.md)).
6. [SAP MCP Same-Sub Federation](SAP_MCP_SAME_SUB_FEDERATION.md) — email-based Cognito→IAS
   corporate-IdP federation so the federated user is the real human.
Per-test SAP-side operator runbooks live under [runbooks/](runbooks/README.md) — start at that
index. In brief:

7. [SOIDC / Entra-OBO runbook](runbooks/soidc-entra-obo.md) — the flagship OBO path: seamless
   per-user OBO (Direct-Entra → `ON_BEHALF_OF_TOKEN_EXCHANGE` → SAP, no second login).
8. [UF-OIDC runbook](runbooks/uf-oidc.md) — the base interactive USER_FEDERATION (OIDC) case: external **OIDC**
   IdP (Entra/Okta), SAP validates via SOIDC. Prefer Okta (email `sub`).
9. [UF-SAML runbook](runbooks/uf-saml.md) — USER_FEDERATION (SAML) interactive per-user via an external **SAML**
   IdP, SAP as SAML SP behind an OAuth bridge (AgentCore speaks OAuth, not SAML).
10. [UF-OAuth2-SAP runbook](runbooks/uf-oauth2-sap.md) — USER_FEDERATION with SAP as its own OAuth authorization
    server. Documents why the "SAP-direct, no IdP" idea is **REFUTED** and the two documented
    realizations (SAML-redirect / OIDC) instead.

## Also here

- [M2M-OAuth2-SAP runbook](runbooks/m2m-oauth2-sap.md) — SAP-side operator steps for the
  machine-identity `M2M` flow (M2M via SAP SOAUTH2 client-credentials, GA/deploys-today; M2M via an
  external IdP, preview). The SAP-side companion to item 4's deploy model.
- [BTP Hosting Options](BTP_HOSTING.md) — deploying when SAP runs on BTP (Option A supported;
  B/C out of scope for this release).
- [Okta Setup](OKTA_SETUP.md) — Okta (Entra's sibling) inbound + direct-IdP frontend customer
  setup for the `okta-userfed` path (Okta inbound, reusing the Okta OIDC outbound); same generic
  machinery, config-only.
