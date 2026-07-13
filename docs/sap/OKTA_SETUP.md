<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Okta Setup — `okta-userfed` / direct-Okta (Okta inbound, USER_FEDERATION outbound)

Okta is **Entra's sibling** on the same generic auth machinery — the inbound JWT authorizer and the
direct-IdP frontend are issuer-*parameterized*, not per-IdP. There is **no Okta-specific code**; this
doc is the config reference for wiring a real Okta org into the `okta-userfed` profile.

> **STATUS.** Okta→SOIDC→SAP token round-trip **live-verified** against an S/4HANA 2023 system
> (standalone-MCP variant): Okta custom authorization server, SOIDC email mapping on `sub`,
> `Authorization: Bearer <access_token>` → OData **HTTP 200** as the mapped user. The AWS-side
> (`okta-userfed` emit/resolve) is built + unit-tested; the *repo-topology* path (Gateway/external
> MCP) is Phase 2 and not yet live.
>
> **Two non-obvious SAP-side gotchas that gated the round-trip (both cost hours):**
> 1. **ICF logon-procedure ORDER on the OData node.** SAP has two independent OIDC modes —
>    `OIDC Bearer Token` (Bearer passthrough, what we use) and `OIDC Logon` (interactive redirect).
>    ICF tries the node's procedures *in list order*; if `OIDC Logon` precedes `OIDC Bearer Token`,
>    a headless Bearer call matches the interactive procedure first and 401s with HTML
>    `Anmeldung fehlgeschlagen`. Fix: remove `OIDC Logon` from the node (or order Bearer first).
> 2. **Audience must equal SAP's own client ID.** SAP rejects any token whose `aud` doesn't contain
>    the SOIDC-configured client ID, regardless of eval mode. `aud` is written by Okta — set
>    **Okta AS → Settings → Audience = `<your-okta-app-client-id>`** (Okta's default `api://default`
>    will NOT match). Fix is on the IdP, not SAP.

## The profile

`okta-userfed` = `frontend: direct-okta` · `inbound: okta` · `outbound: user-federation`
(`auth-profiles.yaml`). The frontend signs the user in against Okta directly; the backend authorizer
validates the Okta-issued JWT; the outbound leg is the shared USER_FEDERATION flow (same as the OIDC
UF case — see [`SAP_MCP_USER_FEDERATION.md`](SAP_MCP_USER_FEDERATION.md)).

## What you must supply

Both blocks are supplied via env vars (which win in CodeBuild) or `cdk/config.yaml`. Values are your
Okta org's — placeholders shown.

### Inbound (backend authorizer)

| Input | Env var | Example |
|---|---|---|
| Discovery URL | `AUTH_INBOUND_DISCOVERY_URL` | `https://<okta-domain>/oauth2/default/.well-known/openid-configuration` |
| Allowed clients | `AUTH_INBOUND_ALLOWED_CLIENTS` (CSV) | `okta-app-id` (or `okta-1,okta-2`) |

### Frontend (SPA OIDC)

| Input | Field | Example |
|---|---|---|
| Discovery URL | `discovery_url` | `https://<okta-domain>/oauth2/default/.well-known/openid-configuration` |
| SPA client id | `client_id` | `spa-client-id` |
| Authority | `authority` | `https://<okta-domain>/oauth2/default` |
| Scope (optional) | `scope` | `email openid profile offline_access` |

## The one caveat that bites: authorization-server URL shape

Okta has **two** discovery-URL shapes and you must supply the right one for your org:

- **Org authorization server:** `https://<okta-domain>/.well-known/openid-configuration`
- **Custom authorization server:** `https://<okta-domain>/oauth2/<authserver-id>/.well-known/openid-configuration`
  (the `default` server is `.../oauth2/default/...`)

The authorizer and frontend pass `discovery_url` through **verbatim** (as `metadata_url`), so a
custom-auth-server URL round-trips unchanged — but a wrong one silently fails at sign-in. This is a
config choice, not something the code can guess.

> **Failure mode (per Okta's authorization-server docs).** The two servers emit
> **different `iss` claims**, and SAP + AgentCore both validate `iss`:
> - Org server `/oauth2/v1/` → `iss = https://<okta-domain>` — does **NOT** match SAP/AgentCore config.
> - Custom (default) server `/oauth2/default/v1/` → `iss = https://<okta-domain>/oauth2/default` — matches.
>
> Use the **`/oauth2/default`** endpoints consistently across the Okta app (authorize/token URLs),
> the SAP SOIDC issuer, and AgentCore's `discoveryUrl`, so all three agree. A mismatch surfaces as a
> **401 from AgentCore** (issuer ≠ configured discovery URL) or a **401 from SAP** (issuer ≠ SOIDC
> config). Decode the `access_token` and check `iss` to confirm. Also use the **access_token**, not
> the `id_token`, for the SAP call.

## Identity join key — email in `sub` (simpler than Entra)

Okta puts the user's email in the `sub` claim, so the email join key used for IAS / user-federation
mapping works out of the box. This is *simpler* than Entra, whose `sub` is an opaque app-pairwise id
requiring a Feature-Pack-2+ custom claim mapping to surface email/UPN. No code difference — the agent's
`get_inbound_identity` reads `email` / `sub` / `iss` generically — just less SAP-side setup for Okta.

## Out of scope

`obo-okta` (Okta on-behalf-of token exchange) is a **separate, experimental** outbound value — AWS
documents OBO out-of-the-box only for Entra (`MicrosoftOauth2`); Okta OBO needs a hand-rolled
`CustomOauth2` provider. It is not part of the `okta-userfed` path.
