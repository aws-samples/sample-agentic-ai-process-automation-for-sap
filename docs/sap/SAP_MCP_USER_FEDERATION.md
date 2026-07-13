<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# SAP MCP — USER_FEDERATION (3-Legged Interactive) Setup

> **NAMING.** This is `USER_FEDERATION` — a **3-legged interactive** login. It is **NOT** the
> literal `ON_BEHALF_OF_TOKEN_EXCHANGE` flow (OBO / ON_BEHALF_OF_TOKEN_EXCHANGE, direct-to-MCP),
> even though older text called this "interactive OBO." The two are different token mechanisms —
> see [TOKEN_MECHANICS.md](./TOKEN_MECHANICS.md).
>
> **STATUS.** USER_FEDERATION is implemented for external mode (Gateway user target). The
> interactive auth URL surfaces through the Gateway as tool-result JSON. What remains is the
> SAP-side trust + a real-user audit proof in your own SAP system — see the same-sub federation
> runbook. Treat as a reference design, not yet run end-to-end; validate against your own SAP
> system.

This guide covers interactive per-user federated access to SAP via the AWS for SAP MCP
Server's `AuthFlow=USER_FEDERATION`. (It is *not* the `ON_BEHALF_OF_TOKEN_EXCHANGE` flow —
[TOKEN_MECHANICS.md](./TOKEN_MECHANICS.md) explains the difference.) For the deploy-model and env-var contract, see
[SAP_MCP_INTEGRATION.md](./SAP_MCP_INTEGRATION.md). For the decision record, see
[ADR-012](../design-decisions/012-sap-mcp-server-integration.md).

## What USER_FEDERATION is (and is not)

`USER_FEDERATION` is the SAP MCP Server's **interactive, 3-legged (authorization-code)** flow.
The container references a pre-created AgentCore Identity OAuth provider **by name**
(`MCP_SERVER_SAP_OAUTH_PROVIDER`) and drives a browser-based login so a **per-user** SAP token is
obtained and used for OData calls. SAP then enforces that user's own authorizations.

It is **not** the original "Gateway-mediated OBO" design (where the Gateway would exchange a user
JWT for a SAP bearer and forward it). That design appears infeasible because the container has no
"accept arbitrary pre-exchanged bearer" mode — see
[ADR-012 — Update (2026-06-05)](../design-decisions/012-sap-mcp-server-integration.md#update-2026-06-05-hybrid-deploy-model--m2m-implemented-phase-2-mechanism-revised).
The related `AuthFlow=ON_BEHALF_OF_TOKEN_EXCHANGE` (non-interactive, server-to-server) is out of
scope **for this interactive USER_FEDERATION flow** — it is the separate **OBO /
ON_BEHALF_OF_TOKEN_EXCHANGE flagship** (seamless, no second login) via the direct-to-MCP path: see
[runbooks/soidc-entra-obo.md](./runbooks/soidc-entra-obo.md).

## Which Cognito? Two gates, not a relay

The single most common confusion: people assume the human's identity is *carried through* the
MCP's Cognito pool on its way to SAP — i.e. `your-pool → mcp-pool → IAS`. **There is no such
relay.** There are two **separate** Cognito-touching gates that never chain together:

| | Gate 1 — Inbound (invoke the Runtime) | Gate 2 — Outbound OBO (reach SAP as the human) |
|---|---|---|
| **What** | Gateway presents a Bearer the Runtime's authorizer trusts | `USER_FEDERATION` 3-legged login to SAP's OAuth server (IAS on RISE) |
| **Which Cognito** | The **external SAP MCP stack's inbound pool** | **Our user-facing (frontend) pool** |
| **Who owns it** | AWS-published SAP MCP CFN stack | This project / CDK |
| **What's in it** | Machine/M2M tokens only — no humans | The actual humans, with verified `email` |
| **Is IAS involved?** | No — pure machine-to-machine, stops at the Runtime door | Yes — IAS trusts our user-facing pool **directly** as a corporate IdP |

Key facts that kill the misconception:

- **`USER_FEDERATION` does not spin up a user pool.** The MCP inbound pool exists for *every*
  flow (BASIC, M2M, USER_FEDERATION) as the Runtime's front-door authorizer; it is created by
  the external CFN stack, not by `USER_FEDERATION`, and never by us. `USER_FEDERATION` itself
  references an AgentCore Identity OAuth provider **by name** pointed at SAP's OAuth server
  (`authorize_url`/`token_url`) — not at any Cognito.
- **The MCP inbound pool is never in the identity chain.** IAS never sees it. The only thing
  that crosses the SAP boundary is the human's **`email`** claim, federated from our
  **user-facing** pool to IAS directly. Same-sub trust is **not transitive** — neither the MCP
  pool, the Gateway, nor Federate relays the human identity (see
  [SAP_MCP_SAME_SUB_FEDERATION.md](./SAP_MCP_SAME_SUB_FEDERATION.md)).
- **The container's role in OBO is to *start* the login, not to be a link in the chain.** It
  emits the interactive auth URL (which surfaces back through the Gateway as tool-result JSON);
  the human then authenticates at IAS, which delegates to our user-facing pool.

> **In one sentence:** we use **our user-facing Cognito as the user pool, federated directly to
> SAP's IAS**; the MCP's own Cognito is a separate machine-auth gate and nothing is carried
> through it to IAS.

## The two callback URLs (do not conflate them)

USER_FEDERATION involves **two distinct callback URLs**. Conflating them silently breaks the flow:

1. **The AgentCore callback URL** — auto-generated by the AWS SAP MCP stack (AgentCore Identity
   owns it). This is the redirect URI that completes the OAuth authorization-code exchange with the
   IdP/SAP. **It must be registered as an allowed redirect URI with your IdP (XSUAA/IAS/Entra) and
   the SAP OAuth client.** You obtain it from the deployed AWS stack (its outputs / AgentCore
   Identity provider config), not from this repo's config.
2. **`MCP_SERVER_APP_CALLBACK_URL`** — **our frontend route** (`/auth/callback`). This is where
   AgentCore redirects the browser **after** the IdP exchange completes, to signal completion back
   to our application. Set as `MCP_SERVER_APP_CALLBACK_URL` on the **external** AWS-for-SAP MCP
   stack (post-refactor — no longer a `cdk/config.yaml` `sap_mcp.user` field; see the Configuration
   note below).

| URL | Owner | Registered where | Purpose |
|---|---|---|---|
| AgentCore callback URL | AWS stack / AgentCore Identity | IdP + SAP OAuth client (redirect URI allowlist) | Completes the OAuth code exchange |
| `MCP_SERVER_APP_CALLBACK_URL` (`/auth/callback`) | Our frontend | Our config (`app_callback_url`) | Signals completion to our app |

## IdP redirect-URI registration

Register the **AgentCore callback URL** (item 1 above) as an allowed redirect URI on your IdP's
SAP/OAuth client, then ensure the SAP OAuth client allows it too.

- **SAP XSUAA / IAS (BTP):** add the AgentCore callback URL to the OAuth client's
  `redirect-uris` (xs-security.json `oauth2-configuration.redirect-uris`, or the IAS application's
  configured redirect URIs). The client's `authorize_url`/`token_url` go into
  `sap_oauth.authorize_url`/`token_url`. The SAP service names you intend to call go into
  `sap_oauth_scopes` (→ `MCP_SERVER_SAP_OAUTH_SCOPES`).
- **Microsoft Entra ID:** register the AgentCore callback URL as a Web redirect URI on the app
  registration; expose the SAP API scopes and grant the app consent. (Entra inbound is functional-
  parity scaffolding — Cognito is the tested-first default.)

The SAP credentials secret must hold `{clientId, clientSecret}` (same as M2M). The SAP-facing
OAuth provider is registered with `authorizationServerMetadata` (explicit endpoints), not
`discoveryUrl` — see the integration doc's M2M/troubleshooting notes.

## Configuration

> **STALE (pre-refactor) config surface — the `sap_mcp.user:` block below is no longer read.** The
> adapter refactor removed the manual `service`/`user` runtime blocks: the target variant is now
> **derived from `auth_profile`'s outbound axis** (`user-federation` → User target), and the SAP
> OAuth knobs (`MCP_SERVER_SAP_OAUTH_FLOW`, the SAP `authorize`/`token` endpoints, scopes,
> `MCP_SERVER_APP_CALLBACK_URL`, read/write enablement) all live on the **external** AWS-for-SAP MCP
> stack (its CFN params / runtime env vars), not in this repo's `config.yaml`. Our
> `config-manager.ts` validates only `sap_mcp.external_stack.stack_name` (+ the OBO coherence guard).
> The block below is retained only to show the field *names* → their `MCP_SERVER_*` env-var
> equivalents on the external stack. Operator steps:
> [runbooks/uf-oauth2-sap.md](./runbooks/uf-oauth2-sap.md) (SAP-direct) and
> [runbooks/uf-saml.md](./runbooks/uf-saml.md) (SAML).

```yaml
# Field-name → external-stack env-var reference (NOT a live config.yaml block anymore):
sap_mcp:
  enabled: true
  external_stack:
    stack_name: sap-mcp-server-prod        # AWS CFN stack to read outputs from
    inbound_auth_provider: Cognito         # Cognito (default) | EntraId
    inbound_cognito:
      client_secret_arn: "arn:aws:secretsmanager:us-east-1:ACCT:secret:ext-cognito-XXXX"

  # --- pre-refactor `user:` block, shown for the field→env-var mapping only; NOT read: ---
  user:
    auth_flow: USER_FEDERATION             # → MCP_SERVER_SAP_OAUTH_FLOW (set on the external stack)
    sap_oauth:                             # → the external stack's SAP OAuth provider endpoints
      authorize_url: "https://<tenant>.authentication.<region>.hana.ondemand.com/oauth/authorize"
      token_url: "https://<tenant>.authentication.<region>.hana.ondemand.com/oauth/token"
    sap_oauth_scopes: "ZAPI_SALES_ORDER_SRV_0001"   # → MCP_SERVER_SAP_OAUTH_SCOPES (SAP service name(s))
    app_callback_url: "https://<frontend-domain>/auth/callback"   # → MCP_SERVER_APP_CALLBACK_URL
```

## Gateway vs. direct-invoke — resolved

USER_FEDERATION's interactive flow assumes the **MCP client** receives the AgentCore-issued auth
URL and drives the browser login. With the Gateway terminating MCP, the Gateway is the client, so
there was an open question of whether the auth-URL handoff would surface to our agent/frontend.
This is resolved: the auth URL surfaces through the Gateway as tool-result JSON.

- **Auth URL surfaces through the Gateway.** We use the frontend-callback model: the agent relays
  the auth URL to the frontend, the user logs in, the IdP redirects to the AgentCore callback, and
  AgentCore then redirects to `/auth/callback` to signal completion. OBO calls keep flowing through
  the Gateway (Cedar + audit interception intact).
- **The alternative that did not materialize.** Had the URL not surfaced, the USER_FEDERATION
  target would have had to be invoked **directly** (agent → AgentCore Runtime, bypassing the
  Gateway for that one target), losing Gateway-level Cedar authorization and `x-audit-*`
  interception for OBO calls. That is not the case.

The external-mode USER_FEDERATION Gateway target is wired, and the auth-URL handoff surfaces
correctly. **End-to-end is currently blocked upstream in AgentCore Identity**, not in this repo
or SAP — see the status note below.

> **STATUS — 3LO auto-vault blocked in AgentCore Identity.** Testing against an Okta custom
> authorization server proved every layer this project owns is correct, but the token never
> vaults. The Okta System Log shows every `authorize.code` SUCCEEDS against AgentCore's callback
> (`…/identities/oauth2/callback/<guid>`), yet **no `app.oauth2.as.token.grant` is ever issued
> for that callback** — AgentCore's managed callback receives the authorization code but never
> redeems it at the IdP's `/token` endpoint, so the MCP poller times out (600s) and the agent
> re-prompts. A direct-SDK repro that bypasses the MCP server reproduces the same behavior, so
> the defect is in AgentCore Identity's USER_FEDERATION 3LO with a custom-OIDC provider — not
> the vendor server, not this project's code. The **SAP trust chain itself is proven** (a real
> Okta user token returns SAP OData 200 as the mapped user via pass-through test). Escalation
> is with the AgentCore Identity team.

## Per-user token flow

The implemented mechanism is AgentCore's interactive `USER_FEDERATION` (3-legged authorization
code), not Gateway-mediated token exchange. The original Gateway-mediated OBO design is
preserved in [ADR-012 Change 4](../design-decisions/012-sap-mcp-server-integration.md#change-4--phase-2--obo-mechanism-revised-and-honestly-de-scoped-pending-further-investigation).
The auth URL surfaces through the Gateway as tool-result JSON; the agent relays it to the frontend,
the user completes the IdP login, and AgentCore redirects to `/auth/callback` to signal completion.
The exact per-user sequence will be finalized against your own SAP system during end-to-end
validation.

## Troubleshooting

**401 from the runtime** — inbound auth mismatch. In `external` mode the Gateway OAuth2 provider
must point at the **external stack's** inbound IdP (its client id + discovery URL), not our pool;
see [SAP_MCP_INTEGRATION.md troubleshooting](./SAP_MCP_INTEGRATION.md#troubleshooting).

**No interactive auth URL surfaces to the agent/frontend** — the auth URL *does* surface through
the Gateway as tool-result JSON. If it does not surface in your deploy, check that the agent is
reading the tool-result JSON for the auth URL and relaying it to the frontend, rather than treating
it as an error.

**Auth URL surfaces but the IdP rejects the redirect** — the **AgentCore callback URL** (not
`MCP_SERVER_APP_CALLBACK_URL`) is not registered as an allowed redirect URI on the IdP/SAP OAuth
client. These are two different URLs — see "The two callback URLs" above.

**`discoveryUrl` regex rejection creating the SAP OAuth provider** — a SAP token URL was passed
where a `.well-known` discovery URL is expected; the SAP-facing provider must use
`authorizationServerMetadata`. See the integration doc's troubleshooting.

## References

- [ADR-012: SAP MCP Server Integration](../design-decisions/012-sap-mcp-server-integration.md)
- [SAP_MCP_INTEGRATION.md](./SAP_MCP_INTEGRATION.md) — deploy model, env-var contract, M2M, troubleshooting
- [On-Behalf-Of Token Exchange (AWS)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/on-behalf-of-token-exchange.html)
