<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# USER_FEDERATION with SAP as its own OAuth Authorization Server — Operator Runbook

> **PREVIEW — not yet deployable.** The USER_FEDERATION outbound is a preview topology:
> it is modeled and validated, but its IaC module is not built yet. Reference design for the
> roadmap, not a ready-to-run procedure.

> **STATUS — READ THIS FIRST.** The headline claim for this flow ("SAP mints its own per-user token
> via a 3-legged USER_FEDERATION login with **no** external IdP and **no** SAML — the lowest-risk
> interactive variant") is **NOT supported by the current AWS for SAP MCP docs.** The AWS
> outbound-auth scenario table has **exactly two** USER_FEDERATION rows and **both require an
> external IdP** (see the table below). "SAP as Authorization Server with OAuth2" with **no**
> external IdP maps to **M2M** — a non-interactive 2-legged flow — **not** USER_FEDERATION. So
> the interactive, per-user "SAP-direct, no IdP" topology this flow was named for **is not a row
> in the table**. Ship one of the two documented USER_FEDERATION realizations instead
> (USER_FEDERATION (SAML), or USER_FEDERATION (OIDC)). Treat this flow as an **alias that
> resolves to the same single USER_FEDERATION profile + User Gateway target** as the other
> USER_FEDERATION realizations — the runtime wiring is identical; only the SAP-side trust differs,
> and the SAP-side trust the name implies **does not exist** as documented.
>
> This topology is a PREVIEW, not-yet-built variant. Facts that
> could not be re-confirmed against a rendered primary SAP doc are marked **UNVERIFIED**.

**Audience:** an SAP admin **+** an AWS operator (+ a SAML/OIDC IdP admin if you take the
documented path). Each side owns a lane below; the checklist maps every step to the responsible
operator.

For the deploy-model / env-var contract see the SAP MCP integration doc.
This runbook is a **variant-delta on** the base interactive-OBO doc — the two callback URLs, the
auth-URL-through-the-Gateway story, and the SAP OAuth authorize/token config live in the base
USER_FEDERATION doc and are **not** repeated here (the
SAP OAuth knobs are set on the external stack). The
SAML-redirect realization (documented path A) is fully covered by the sibling
[uf-saml.md](./uf-saml.md) (SAML2 trusted provider + SOAUTH2 auth-code linkage); STRUST chain
mechanics are in [soidc-entra-obo.md](./soidc-entra-obo.md) S2 — cross-link, don't duplicate.

## What this flow was supposed to be — and what the docs actually support

This flow was intended as *"USER_FEDERATION with SAP as its own OAuth authorization server …
possible via SOAUTH2 auth-code."* SAP **is** an OAuth 2.0 authorization server and **does** support
the Authorization Code grant (RFC 6749) — so an *SAP-hosted, interactive, per-user*
authorization-code client is real **on the SAP side**. The break is on the **AWS side**: driving that
login through `AuthFlow=USER_FEDERATION` **with no external IdP** is not a topology the AWS for SAP
MCP Server documents.

Grounded in the AWS SAP-MCP outbound-auth scenario table
([identity-and-authentication](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/identity-and-authentication.html),
fetched 2026-07-01):

| Scenario (verbatim) | Auth Flow | Protocol | Identity Provider | SAP Configuration |
|---|---|---|---|---|
| SAP as Authorization Server with OAuth2 | **M2M** | OAuth2 | **SAP** | SAP OAuth2 Client |
| SAP as Authorization Server with OAuth2 **and SAML IdP redirect** | **User Federation** | OAuth2 + SAML | **Entra ID or other SAML IdP** | SAP OAuth2 client + **SAML trusted provider** |
| External IdP with OIDC | **User Federation** | OIDC | Entra ID | SAP OIDC trust |

Read the columns carefully:

- **The only "SAP-direct, no external IdP" OAuth2 row is `M2M`** — and M2M is explicitly *"No user
  interaction required — fully automated token exchange."* It **cannot** be the interactive,
  per-user, signed-in-human flow this one describes. That row is the
  [M2M via SAP SOAUTH2 client-credentials runbook](./m2m-oauth2-sap.md), not this one.
- **The only USER_FEDERATION row where SAP is the authorization server** is the SAML-redirect row:
  Protocol = **OAuth2 + SAML**, IdP = **Entra ID or other SAML IdP**, SAP config = **SAP OAuth2
  client + SAML trusted provider**. It **requires** an external SAML IdP and a SAML trust in SAP —
  the exact opposite of "no external IdP, no SAML."
- The AWS narrative is explicit that a **choice of IdP is inherent** to the flow: *"This flow uses
  either OAuth2, OIDC, or SAML2 depending on your choice of IdP."* There is no IdP-less
  USER_FEDERATION variant.

> **Net.** The lowest-risk "SAP-direct, no IdP, no SAML" 3-legged variant this flow was named for is
> **not** offered by the current AWS doc. Your two documented interactive choices are:
> **(A)** SAP-as-authorization-server **+ a SAML IdP redirect** — the SAML-redirect row (this is
> the [USER_FEDERATION (SAML)](./uf-saml.md) shape); or
> **(B)** an **OIDC external IdP** — the USER_FEDERATION (OIDC)
> shape. Pick (A) if you specifically want SAP to be the OAuth authorization server; pick (B) for
> the simplest interactive path. Either way it is the **same** USER_FEDERATION profile + User
> Gateway target.

### The one thing you could technically wire (undocumented — do not ship as "supported")

It is *conceivable* to set `MCP_SERVER_SAP_OAUTH_FLOW=USER_FEDERATION` and point the AgentCore
Identity OAuth provider's authorize/token endpoints at SAP's **own** SOAUTH2 authorization-code
endpoints with no SAML in between — startup validation only checks that the named provider **exists**
in AgentCore Identity (cross-validation rule #3), not that an IdP is wired. But the AWS docs neither
document nor bless this combination, and it is **UNVERIFIED** whether the container honors it. This
is "technically wireable but undocumented/unsupported" — it is **not** the "lowest-risk supported
variant" the name claims. **Do not present it as generally available.** If you need SAP to be the
OAuth authorization server today, take documented path (A).

## End-to-end flow (short — documented path (A), SAML-redirect realization)

```
Agent ─▶ AgentCore Gateway (User target, credentialProviderType:OAUTH — via the Gateway)
      ─▶ external AWS-for-SAP MCP Runtime (inbound: token from the EXTERNAL stack's pool)
      ─▶ AgentCore Identity USER_FEDERATION (3-legged): returns an authorization URL
      ─▶ (auth URL surfaces back through the Gateway as tool-result JSON; agent relays to frontend)
      ─▶ human's browser hits SAP's OAuth /authorize ─▶ SAP REDIRECTS to the SAML IdP
      ─▶ human authenticates at the SAML IdP ─▶ back to SAP ─▶ SAP issues its OWN per-user token
      ─▶ AgentCore callback ─▶ /auth/callback (signals completion) ─▶ OData as the signed-in human
```

The auth-URL-through-the-Gateway path and the **two callback URLs** are the base
USER_FEDERATION story (see the base USER_FEDERATION doc, "the two callback URLs").
The delta for this flow is only that **SAP is the OAuth authorization server** (its own `/authorize` +
`/token`) and it **redirects the login to a SAML IdP** — vs. USER_FEDERATION (OIDC) where the
external OIDC IdP is itself the authorization server.

---

## SAP-side steps (SAP admin)

Base OData connectivity + the human's SU01 business user (+ PFCG OData authorizations) are owned by
the SAP system configuration doc and the email-join mapping story is covered by the SAP MCP
same-sub federation doc — do **not** redo them here.

### S1. Decide the realization — this is the load-bearing SAP decision

- **Path (A) — SAP as authorization server + SAML IdP redirect** (the documented USER_FEDERATION
  SAP-as-authz-server row): create the SAP OAuth2 **authorization-code** client (S2) **and** register
  a **SAML trusted provider** in SAP (S3), so SAP's `/authorize` delegates the human login to your
  SAML IdP. This is the USER_FEDERATION (SAML) shape.
- **Path (B) — external OIDC IdP** (the other USER_FEDERATION row): SAP trusts the OIDC IdP directly;
  follow [soidc-entra-obo.md S2/S3](./soidc-entra-obo.md) (STRUST chain + SOIDC OIDC-provider trust)
  and the email-join mapping — this is the USER_FEDERATION (OIDC) shape. Skip S2/S3 below.

There is **no path (C)** ("SAP alone, no IdP, interactive"). If you have no external IdP at all, the
only SAP-direct OAuth2 flow the docs offer is **M2M** (non-interactive, shared technical user) —
[m2m-oauth2-sap.md](./m2m-oauth2-sap.md).

### S2. (Path A) Create the SAP OAuth 2.0 **authorization-code** client — **UNVERIFIED** labels

SAP GUI transaction **SOAUTH2**. Register an OAuth 2.0 client for the **authorization-code** grant
(interactive user login) — **not** the client-credentials grant (that is the M2M client, a
different SOAUTH2 setup — [m2m-oauth2-sap.md S2](./m2m-oauth2-sap.md)). Record the **client id +
client secret** → they become the `{clientId, clientSecret}` Secrets Manager secret the external
stack reads. The client's `/authorize` + `/token` endpoints become SAP's OAuth authorize/token
endpoints (base USER_FEDERATION doc). The OData service names you expose
go into `MCP_SERVER_SAP_OAUTH_SCOPES` (S5). Exact SOAUTH2 field labels and the scope→service mapping
are **UNVERIFIED** against a rendered help.sap.com page — confirm in the live transaction.

> **SAP-side fact (independently true, but UNVERIFIED against a rendered SAP doc):** SAP NetWeaver/
> ABAP is an OAuth 2.0 authorization server and supports the Authorization Code grant (RFC 6749) as
> well as the SAML 2.0 Bearer Assertion grant. help.sap.com is client-side-rendered and returned
> **title-only** on fetch (2026-07-01), so the exact SOAUTH2 grant-type field labels and the
> "runs as the logged-in human" wording are **UNVERIFIED** here — confirm on your own system.

### S3. (Path A) Register the SAML trusted provider + import its TLS chain — **UNVERIFIED** labels

The documented SAP-as-authz-server USER_FEDERATION row is *"SAP OAuth2 client **+ SAML trusted
provider**."* So SAP must trust your SAML IdP (Entra ID or other SAML IdP) and redirect the
interactive login to it:

- **TLS:** import the SAML IdP's full certificate chain (leaf + intermediates + root) into the SAP
  **STRUST** SSL client PSE and restart ICM — the same full-chain discipline as
  [soidc-entra-obo.md S2](./soidc-entra-obo.md#s2-import-the-entra-token-endpoint-tls-chain-into-strust)
  (root-only imports are the classic silent TLS failure).
- **SAML trust:** register the SAML IdP as a trusted provider in SAP (SAML 2.0 configuration:
  metadata exchange, entity id `saml-idp-entityid`, signing cert, name-id/assertion attribute
  mapping to the SU01 user). The **exact SAP SAML transaction/field labels are UNVERIFIED** — do not
  invent them; confirm in the live system. Whether this OAuth-authorization-code + SAML-redirect
  mechanism actually carries the human identity end-to-end is the same open question flagged for
  USER_FEDERATION (SAML) — validate before relying on it.

### S4. Map the human → SU01 business user — email join

Interactive USER_FEDERATION reaches SAP **as the signed-in human**, so a human claim must map to the
SU01 business user. On the SAML-redirect path the SAML assertion's name-id/attribute is the join key
(SAP-side); the email-join principle and the "unmapped users fail closed, never a service-account
fallback" rule are covered by the SAP MCP same-sub federation doc. Ensure each
target SU01 user exists with the matching identifier and holds the PFCG OData authorizations for the
services the agent calls, or SAP returns **403**.

### S5. SAP OAuth "scopes" are OData **service names**, not scope URIs — same as every tier

`MCP_SERVER_SAP_OAUTH_SCOPES` takes **SAP OData service names** (e.g. `ZAPI_SALES_ORDER_SRV_0001`),
**not** OAuth scope URIs — the AWS config-reference labels the field "OAuth scopes" but its own
example is a service name. A wrong/foreign scope → **HTTP 403**. Same rule the siblings document
([m2m-oauth2-sap.md S3](./m2m-oauth2-sap.md#s3-sap-oauth-scopes-are-odata-service-names-not-scope-uris--all)) —
not re-derived.

### S6. SICF: activate the OData service nodes — same node set as the siblings

SAP GUI transaction **SICF** → activate `/sap/opu/odata/sap/` (+ each exposed service subnode), plus
(if `MCP_SERVER_USE_SAP_CATALOG=true`) `/sap/opu/odata/iwfnd/catalogservice;v=2`. Same set the
sibling runbooks activate — [soidc-entra-obo.md S6](./soidc-entra-obo.md); do not re-derive. Whether
a dedicated OAuth token-endpoint SICF node must also be active for your release is **UNVERIFIED**.

### S7. Smoke-test the SAP OAuth server in isolation (before full E2E)

- Drive SAP's `/authorize` in a browser directly (path A): you should be **redirected to the SAML
  IdP**, authenticate, land back at SAP, and receive a code → token. No redirect to the SAML IdP →
  the S3 SAML trusted-provider registration is wrong.
- Present the SAP-issued per-user token to **one** activated OData service. **401** → the SOAUTH2
  auth-code client / token endpoint is wrong (S2). **403** → the mapped SU01 user lacks PFCG (S4) or
  the scope isn't a real service name (S5).
- **Audit proof (the acceptance test):** SM20 / RSAU_* must show the action under the **mapped human
  SU01 user**, not a service account — the same real-user audit proof carried open across the sibling
  runbooks (**UNVERIFIED** end-to-end).

---

## SAML / OIDC IdP-side steps (IdP admin) — **path A only**

Path A needs a SAML IdP because SAP redirects the interactive login to it. Register SAP as a SAML
service provider / relying party at your SAML IdP (Entra ID or other), exchange metadata, and emit
the human identifier (name-id / `email` / UPN) that the S4 mapping binds to. This is the SAML analog
of the OIDC registration in [soidc-entra-obo.md](./soidc-entra-obo.md) E-lane; **exact IdP blade
names and SAML binding names are UNVERIFIED** — do not invent them. (Path B uses an OIDC IdP instead;
follow the sibling runbook's OIDC registration directly.)

---

## AWS / AgentCore-side steps (AWS operator)

> The deployment does **not** deploy the external AWS-for-SAP MCP stack, its inbound pool, or its
> outbound SAP OAuth provider — those are owned externally. Your IaC is a pure adapter that mints the
> **User Gateway target + a Gateway OAuth2 credential provider** (USER_FEDERATION is the **Gateway**
> path — **never** direct-to-MCP; direct-to-MCP is OBO-only,
> [OBO / ON_BEHALF_OF_TOKEN_EXCHANGE](./soidc-entra-obo.md)).

### A1. Deploy the external stack with USER_FEDERATION + SAP knobs — external stack owns these

AgentCore Runtime env vars (external stack; CFN params, editable via Bedrock AgentCore console →
Runtime → Update Hosting → Advanced Configurations). **The deployment's IaC does NOT set these:**

- `MCP_SERVER_SAP_OAUTH_FLOW=USER_FEDERATION`
- `MCP_SERVER_SAP_BASE_URL=https://<sap-host>/sap/opu/odata/sap/`
- `MCP_SERVER_SAP_OAUTH_SCOPES=<sap-service-name(s)>` e.g. `ZAPI_SALES_ORDER_SRV_0001` — **SAP OData
  service names, NOT OAuth scope URIs** (S5).
- `MCP_SERVER_APP_CALLBACK_URL=https://<frontend-domain>/auth/callback` — **required for
  USER_FEDERATION** (cross-validation: `MCP_SERVER_APP_CALLBACK_URL` is required when the flow is
  `USER_FEDERATION`). The path **must end in `/callback` or `/oauthcallback`** or the AgentCore
  validator rejects it (see the SAP MCP integration doc troubleshooting).
- Secret: `{clientId, clientSecret}` = the **SOAUTH2 authorization-code client** (path A, S2) — same
  secret shape as the M2M flow.
- Start read-only (`MCP_SERVER_WRITE_ENABLED=false`); enable writes there when ready — Gateway Cedar
  is defense-in-depth on top.

> **Env-var name:** use `MCP_SERVER_SAP_OAUTH_PROVIDER` (with the `SAP_` infix) — see the SAP MCP
> integration doc env-var contract.

### A2. Create the AgentCore Identity OAuth2 provider for the SAP-facing token — `authorizationServerMetadata`

`aws bedrock-agentcore-control create-oauth2-credential-provider` (or Console → custom provider),
`clientId`/`clientSecret` = the SOAUTH2 auth-code client from A1's secret. Because SAP is the
authorization server, use **`oauthDiscovery.authorizationServerMetadata`** — explicit
`authorizationEndpoint` + `tokenEndpoint` + `issuer` (issuer derived from the SAP token URL origin) —
**NOT** `discoveryUrl`. A SAP token/authorize URL is **not** a `.well-known` document, and AgentCore's
`discoveryUrl` enforces a `.+/\.well-known/(openid-configuration|oauth-authorization-server)` regex
that a SAP URL fails; the OAuth2-provider setup uses `authorizationServerMetadata` when an
authorization endpoint + token endpoint are supplied. See the SAP MCP integration doc's
`discoveryUrl` regex rejection note
and the M2M crux in [m2m-oauth2-sap.md A2](./m2m-oauth2-sap.md#a2-create-the-agentcore-identity-outbound-oauth2-credential-provider--all).
The runtime references this provider **by name** (`MCP_SERVER_SAP_OAUTH_PROVIDER`) and validates it
exists at startup or fails to start — the container never takes SAP endpoints directly. Then register
the AgentCore callback URL per the base doc's "two callback URLs."

> **The two callback URLs — do NOT conflate.** The **AgentCore callback URL** (auto-generated by the
> provider) must be registered as an allowed redirect URI on **SAP's OAuth2 client** (and on the SAML
> IdP for path A); `MCP_SERVER_APP_CALLBACK_URL` (`/auth/callback`) is the **frontend** completion
> route. Full treatment is in the base USER_FEDERATION doc ("the two callback URLs").
> Don't repeat it — just don't swap them.

### A3. Deployment output — User Gateway target (via the Gateway), NOT direct-to-MCP

For a User outbound profile, the deployment mints a **"User" Gateway target** pointing at the
external runtime's invocation URL, `credentialProviderType: "OAUTH"`, flow `USER_FEDERATION`. Calls
keep flowing through the Gateway (Cedar + `x-audit-*` interception intact). It is **not** the
direct-to-MCP path (that is OBO-only,
[OBO / ON_BEHALF_OF_TOKEN_EXCHANGE](./soidc-entra-obo.md)). Same
behavior as the other USER_FEDERATION realizations.

> **Inbound-pool risk.** The Gateway OAuth2 provider **must point at the EXTERNAL stack's inbound
> pool**, not the deployment's own — else the runtime **401s** (`iss` mismatch). Distinct from the
> outbound provider in A2. See the SAP MCP integration doc, "401 in external mode."

---

## Checklist (mapped to the flow's rows)

| Side | Step | Flow |
|---|---|---|
| **SAP** | S1 pick realization: (A) SAP-authz + SAML redirect, or (B) OIDC IdP — **no path (C)** | USER_FEDERATION (SAP-as-authz) / USER_FEDERATION (SAML) / USER_FEDERATION (OIDC) |
| **SAP** | S2 (A) SOAUTH2 **auth-code** client (**UNVERIFIED** labels) | OAuth2 client (auth code) SOAUTH2 (SAML / SAP-as-authz) |
| **SAP** | S3 (A) SAML trusted provider + STRUST chain (**UNVERIFIED** labels) | SAML trusted provider (USER_FEDERATION (SAML)) |
| **SAP** | S4 human → SU01 (email/SAML name-id join) | identity mapping (same-sub federation) |
| **SAP** | S5 scopes = OData service names | SAP OAuth scopes |
| **SAP** | S6 SICF `/sap/opu/odata/sap/` + `iwfnd/catalogservice;v=2` | SICF (All) |
| **SAP** | S7 isolation smoke-test + real-user audit proof | acceptance |
| **IdP** | (A) register SAP as SAML SP + emit human claim (**UNVERIFIED** blade names) | IdP (SAML) (USER_FEDERATION (SAML)) |
| **AWS** | A1 external stack USER_FEDERATION + SAP knobs + `/auth/callback` | (external stack) |
| **AWS** | A2 AgentCore outbound provider (`authorizationServerMetadata`, SAP endpoints) + AgentCore callback | OAuth provider (SAP) |
| **AWS** | A3 User Gateway target (via the Gateway) + Gateway OAuth2 provider (inbound-pool guard) | (deployment-side) |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| **You cannot find an "SAP-only, no IdP, interactive" USER_FEDERATION option** | It does not exist — that row is **M2M** (non-interactive) | Take documented path (A) SAML-redirect or (B) OIDC; or use [M2M via SAP SOAUTH2 client-credentials](./m2m-oauth2-sap.md) if a shared technical user is acceptable |
| **`discoveryUrl` regex rejection** creating the SAP provider | SAP authorize/token URL passed where a `.well-known` URL is expected | Use `authorizationServerMetadata` (authEndpoint+tokenEndpoint+issuer) — A2 |
| **401 from the external runtime** (`iss mismatch`) | Gateway OAuth2 provider points at the deployment's own Cognito, not the external stack's pool | Point the Gateway provider at the external stack's inbound pool — A3 |
| **Callback URL rejected** ("must match the allowed pattern") | `MCP_SERVER_APP_CALLBACK_URL` path doesn't end in `/callback` or `/oauthcallback` | Use `/auth/callback` — A1 / base USER_FEDERATION doc |
| **Auth URL surfaces but SAP/IdP rejects the redirect** | The **AgentCore** callback URL isn't registered on SAP's OAuth client (and the SAML IdP for path A) | Register it — A2 / base doc "two callback URLs" |
| **No redirect to the SAML IdP at SAP `/authorize`** (path A) | SAML trusted provider not registered in SAP | Fix S3 |
| **SAP 403** | Mapped SU01 user lacks PFCG, or scope isn't a real service name | Grant PFCG (S4); set scopes to OData service names (S5) |
| **No interactive auth URL surfaces to the agent** | Gateway auth-URL handoff not being read | The URL surfaces as tool-result JSON — the agent must relay it, not treat it as an error (base doc troubleshooting) |

## Open items (carried; the "SAP-direct" variant is REFUTED, not merely open)

- **The headline "SAP-direct, no IdP, no SAML" interactive variant is REFUTED** against the current
  AWS scenario table — it is not a documented USER_FEDERATION topology. Ship documented path (A)
  (SAML-redirect) or (B) (OIDC) instead. The "wire SAP's own SOAUTH2 auth-code endpoints under
  USER_FEDERATION with no SAML" combination is **UNVERIFIED / undocumented** — do not ship as
  supported.
- **Not run end-to-end** against a production SAP system (whole SAP-MCP integration is
  reference-design — see the SAP MCP integration doc status banner).
- **UNVERIFIED against primary/rendered SAP docs:** that SAP supports the OAuth authorization-code
  grant + SAML 2.0 Bearer Assertion grant (help.sap.com returned title-only — fact is
  standard/inferred, not quoted from a rendered SAP page); SOAUTH2 auth-code field labels (S2); the
  SAP SAML trusted-provider transaction + field labels (S3); whether the OAuth-code+SAML-redirect
  mechanism carries the human identity end-to-end (shared open question with USER_FEDERATION (SAML));
  whether a dedicated OAuth token-endpoint SICF node is required (S6).
- **UNVERIFIED against AWS/deployed stack:** the `SAP_` infix the deployed container reads (A1); the
  AgentCore callbackUrl format (base doc); whether `x-audit-*` baggage survives the container to SAP.

## References

- Base USER_FEDERATION doc — the two callback URLs, the auth-URL-through-the-Gateway path, SAP OAuth authorize/token config, config validation
- SAP MCP integration doc — deploy model, env-var contract, the external-pool 401, `discoveryUrl` regex, `authorizationServerMetadata`
- SAP MCP same-sub federation doc — email/name-id join, unmapped-user fail-closed
- [runbooks/soidc-entra-obo.md](./soidc-entra-obo.md) — sibling: STRUST chain + SOIDC trust mechanics path B reuses (SAML delta noted in S3) and the OBO / ON_BEHALF_OF_TOKEN_EXCHANGE contrast
- [runbooks/m2m-oauth2-sap.md](./m2m-oauth2-sap.md) — sibling: the "SAP as Authorization Server with OAuth2" row is **M2M**, not USER_FEDERATION
- SAP system configuration doc — SU01 user + PFCG + SICF base
- [AWS SAP-MCP — Identity and Authentication](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/identity-and-authentication.html) — the outbound-auth scenario table (the REFUTATION source)
- [AWS SAP-MCP — Configuration Reference](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/configuration-reference.html) — env vars, cross-validation rule #3
