<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# M2M via SAP SOAUTH2 client-credentials / M2M via an external IdP — Operator Runbook (Machine Identity → SAP)

> **Status.** AWS documents both variants on [Getting Started](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/getting-started.html): M2M with SAP as the
> OAuth server (SOAUTH2 client-credentials), and M2M with an external OIDC IdP minting the
> machine token. This release wires the SOAUTH2 variant as the `m2m-sap` outbound; the
> external-IdP variant is `m2m-oidc` in `auth-profiles.yaml` (`status: stub`). Neither has yet been
> run end to end in this sample — validate in your own account against your own SAP system before
> production. SAP field labels that could not be checked against a rendered SAP page say
> *confirm on your system*.

**Before you start.** Programmatic or agent access to SAP can have licensing implications (for
example, SAP Digital Access). Review with your SAP account team.

**Audience:** an SAP admin **+** an AWS operator (M2M-via-SOAUTH2). The external-IdP variant adds
a **Microsoft Entra ID or Okta admin**. Each side owns a lane below; the checklist maps every step
to the responsible operator.

For the deploy model and env-var contract see
[SAP_MCP_INTEGRATION.md](../SAP_MCP_INTEGRATION.md#env-var-contract-external-sap-mcp-container--reference).
Base OData connectivity and the SU01 technical user are owned by
[SAP_SYSTEM_CONFIGURATION.md](../SAP_SYSTEM_CONFIGURATION.md) — don't redo the
BASIC/service-account setup here; M2M reuses that technical user and adds SOAUTH2
(M2M-via-SOAUTH2) or SOIDC (M2M-via-external-IdP).
The SOIDC OIDC-provider-trust story (STRUST chain, SOIDC registration, claim mapping) is the
**machine-identity analog** of the sibling [soidc-entra-obo.md](./soidc-entra-obo.md) OBO runbook —
cross-linked below, **not** duplicated. M2M has **no human**, so its user mapping binds the machine
identity to one technical user (S5) instead.

## M2M-via-SOAUTH2 vs M2M-via-external-IdP — who mints the token (the load-bearing distinction)

Grounded in the AWS SAP-MCP outbound-auth table
([identity-and-authentication](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/identity-and-authentication.html)):

| | **M2M via SAP SOAUTH2 client-credentials** (`m2m-sap`) | **M2M via an external IdP (Entra/Okta)** (`m2m-oidc`) |
|---|---|---|
| Who is the OAuth server | **SAP itself** (SOAUTH2) | an **external IdP** (Entra / Okta) |
| Who mints the outbound token | SAP mints it (client-credentials) | the external IdP mints it (client-credentials) |
| SAP-side config | **SOAUTH2** OAuth 2.0 client | **SOIDC** OIDC-provider trust |
| AgentCore provider points at | **SAP's token endpoint** | the IdP discovery URL |
| Provider `oauthDiscovery` field | `authorizationServerMetadata` (see below) | `discoveryUrl` (real `.well-known`) |
| AWS-doc coverage | documented | documented for Entra ID; Okta is standard OIDC client-credentials, not named by AWS |

Both are unattended machine flows: **no user, no user JWT, no identity propagation**. The
token subject is the machine/client id. Both take the **Gateway path** (Service target), never
the direct-to-MCP path (that is OBO-only).

## End-to-end flow (short, M2M via SAP SOAUTH2 client-credentials)

```
Agent ─▶ AgentCore Gateway (Service target, credentialProviderType:OAUTH)
      ─▶ external AWS-for-SAP MCP Runtime (inbound: token from the EXTERNAL stack's pool — the inbound-credential risk below)
      ─▶ AgentCore Identity M2M exchange (client-credentials, outbound SAP OAuth provider)
      ─▶ SAP-scoped token minted BY SAP (SOAUTH2)
      ─▶ SAP OData: SAP validates its own token; the SOAUTH2 client is bound to a technical user
```

For the external-IdP variant the outbound exchange hits Entra/Okta instead, and SAP validates an **externally-minted**
token via SOIDC trust rather than one it minted itself.

---

## SAP-side steps (SAP admin)

### S1. Reuse the technical/service SU01 user — do not recreate — **all**

Use a technical user of type **System** (B) with least-privilege PFCG roles for only the OData
services the agent calls; the user and its authorizations are set up in
[SAP_SYSTEM_CONFIGURATION.md](../SAP_SYSTEM_CONFIGURATION.md#1-service-account-setup). M2M does
**not** federate a human: the outbound token resolves to this one user, and every agent action is
attributed to it in SAP. How that binding happens differs by variant:
- **M2M via SOAUTH2:** the OAuth client ID is itself this SU01 user (type System). SAP mints the
  token for it, so its PFCG roles and its audit identity apply. See S2.
- **M2M via external IdP:** SAP maps the **externally-minted** machine token to the technical user
  through SOIDC's user-mapping claim — for Entra, the service principal's object id (`oid`) stored
  as that user's alias. See S5.

### S2. Create the SOAUTH2 OAuth 2.0 client (client-credentials) — **M2M via SOAUTH2**

SAP GUI transaction **SOAUTH2**. Register an OAuth 2.0 client for the **client-credentials** grant
so SAP acts as its own authorization server and mints the outbound token. Field labels vary by
release — confirm on your system.

- **The client is an SU01 user.** The OAuth client ID is the type **System** SU01 user from S1,
  and its password is the client secret. Record the client ID and secret; they become the
  `{clientId, clientSecret}` AWS Secrets Manager secret the external stack reads (A1). Rotate the
  secret as you would any technical-user password, and update the secret when you do.
- **Enable OAuth per service first.** Each OData service must have OAuth enabled in transaction
  **/IWFND/MAINT_SERVICE** before its scope ID (`<SERVICE>_0001`, for example
  `API_SALES_ORDER_SRV_0001`) exists to assign to the client.
- **Scopes are scope IDs.** Assign the scope IDs of the services the agent calls (S3).

SOAUTH2 authorization-code clients for interactive sign-in are a different setup, covered in
[uf-oauth2-sap.md](./uf-oauth2-sap.md).

### S3. SAP OAuth "scopes" are service scope IDs, not scope URIs — **all**

`MCP_SERVER_SAP_OAUTH_SCOPES` takes the SOAUTH2 **scope IDs** derived from the OData service names
(for example `API_SALES_ORDER_SRV_0001`, S2), not standard OAuth/OIDC scope URIs. The AWS
configuration reference labels the field "OAuth scopes", and its own example value is in this form
([configuration-reference](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/configuration-reference.html)).
A wrong/foreign scope → **HTTP 403** from SAP. Each named service must be SICF-activated (S4) and
PFCG-authorized (S1) for the bound technical user.

### S4. SICF: activate the OData service nodes — **all**

SAP GUI transaction **SICF** (right-click → Activate). Activate the OData runtime tree
`/sap/opu/odata/sap/` and each service subnode you exposed via S3 scopes, plus (if
`MCP_SERVER_USE_SAP_CATALOG=true`) the IWFND catalog service
`/sap/opu/odata/iwfnd/catalogservice;v=2`. Same node set the sibling runbooks activate — cross-link
[soidc-entra-obo.md S6](./soidc-entra-obo.md); do not re-derive.

### S5. (M2M via external IdP only) SOIDC trust, STRUST chain and the machine-user mapping

The external-IdP variant makes SAP **validate an externally-minted machine token**, so SAP needs the
same SOIDC OIDC-provider trust + STRUST TLS chain as the OBO path — **register those exactly per
[soidc-entra-obo.md S2/S3](./soidc-entra-obo.md)** (STRUST full chain + ICM restart; SOIDC issuer =
the IdP, audience = the app whose id the machine token's `aud` carries). **Do not duplicate** those
steps here.

A machine token carries **no human claim** (no email/UPN), so the OBO mapping in
soidc-entra-obo.md S4 does not apply. Map the machine identity instead:

- **Mapping claim.** In SOIDC, set the provider's user-mapping claim to `oid` (Entra's object id for
  the client app's service principal — stable, and unique to that app in the tenant). SOIDC's
  configuration is stored in `SECOIDC_CONFIG` (`USERMAPPING_CLAIM`).
- **Target user.** On the technical SU01 user from S1, set **Alias** (Logon Data tab, up to 40
  characters) to that `oid` value. Take the `oid` from the service principal in Entra
  (Enterprise applications → Object ID), not the app registration's object id — they differ.
- **Issuer version.** The token's `iss` follows the resource app's access-token version in its
  manifest — `requestedAccessTokenVersion` (Microsoft Graph app manifest format) or
  `accessTokenAcceptedVersion` (older Azure AD Graph format) — not the endpoint you called: a v2.0
  token endpoint can still issue a token with the v1 issuer `https://sts.windows.net/<tenant>/`.
  Register the issuer the token actually carries (decode one), or set the version to `2` for
  `https://login.microsoftonline.com/<tenant>/v2.0`.
- **What the token is.** A token that maps is a full SAP logon for that user: its scopes do not
  confine it to particular OData services, and the PFCG roles on the mapped user are the
  authorization boundary. Keep that user's roles least-privilege. `GET /sap/bc/ui2/start_up` with the
  token returns the mapped user's id, which proves the mapping without calling a business service.

### S6. Smoke-test in isolation (before full E2E) — **all**

- **M2M via SOAUTH2:** obtain a token from SAP's SOAUTH2 token endpoint with the client credentials, present it
  to one activated OData service. **401** → SOAUTH2 client/secret or token-endpoint wrong. **403** →
  the bound technical user lacks PFCG authorization for that service (S1/S3).
- **M2M via external IdP:** call `/sap/bc/ui2/start_up` with an IdP-minted machine token first; it
  names the mapped user. SAP returns the same logon-failure page for every refusal — wrong issuer,
  wrong audience, or no user with that alias — so change one S5 value at a time. Then present the
  token to one service: **403** → the technical user lacks PFCG.
- **Audit:** STAD (transaction STAD), or SM20 if the security audit log's logon classes were
  enabled beforehand, shows the action under the **bound technical user**. That is expected: M2M
  is a service identity, with no human to attribute.

---

## Entra / Okta-side steps (external-IdP admin) — **external-IdP variant only**

> Only needed for the external-IdP variant. The M2M-via-SOAUTH2 path needs **no external IdP** — skip this
> lane entirely for the SOAUTH2 path.

### E1. Register the outbound M2M app + client-credentials — **external-IdP variant**

Entra: App registrations → New registration; under Certificates & secrets create a client secret.
Okta: Applications → an OIDC app + a Custom Authorization Server (Security → API). The app's
**client id + secret** become the `{clientId, clientSecret}` secret the external stack reads. This
app is the machine identity — AgentCore Identity uses it for the **client-credentials** grant to
mint the outbound token. Record the app/client id (the machine token's subject/`appid`).

> **Okta.** AWS names Entra ID for this path. Okta client-credentials is the same standard
> OAuth grant against an OIDC discovery URL; it has not been run end to end in this sample.

### E2. Expose the SAP scope / app-role the SAP SOIDC trust validates — **external-IdP variant**

The machine token must carry an `aud`/scope (Entra: Expose an API / app role; Okta: custom
auth-server scope) that SAP's S5 SOIDC trust accepts, and a **claim SAP can bind to a fixed
technical user**. For Entra that claim is `oid`, which every app-only access token carries — hand
the service principal's object id to the SAP admin for S5. For Okta, pick a claim that is fixed per
client (`cid`/`sub`) and coordinate it the same way.

---

## AWS / AgentCore-side steps (AWS operator)

> The external AWS-for-SAP MCP stack, its inbound pool, and its
> outbound OAuth provider are owned externally — not deployed here. The infrastructure on this side
> mints the **Gateway Service target + a Gateway OAuth2 credential provider** (the M2M path is the Gateway
> path, never direct-to-MCP).

### A1. Deploy the external stack with the M2M flow + SAP knobs — **all**

On the external stack set the container env vars (AWS CloudFormation parameters; editable in the
Amazon Bedrock AgentCore console → Runtime → Update Hosting → Advanced Configurations). They are
set on the external stack, not on this side:
- `MCP_SERVER_SAP_OAUTH_FLOW=M2M`
- `MCP_SERVER_SAP_BASE_URL=https://<sap-host>/sap/opu/odata/sap/`
- `MCP_SERVER_SAP_OAUTH_PROVIDER=<m2m-provider-name>` (the AgentCore Identity provider **name**)
- `MCP_SERVER_SAP_OAUTH_SCOPES=<scope-id(s)>` — SAP service scope IDs, not scope URIs (S3)
- Keep `MCP_SERVER_WRITE_ENABLED=false` until you have reviewed the SAP API Policy (see the
  [README](../../../README.md)). This sample has no per-write approval step. On
  this Gateway path, the Cedar policies permit `odata_create`, `odata_update` and
  `odata_function_import` only for the finance, procurement and admin role tags and forbid
  `odata_delete`; the default `cedar_enforcement_mode: LOG_ONLY` only logs those decisions, so set
  `ENFORCE` for them to block.
- Secret: `{clientId, clientSecret}` in Secrets Manager (M2M via SOAUTH2 = the SOAUTH2 client;
  M2M via external IdP = the Entra/Okta app).

> **Env-var name:** use `MCP_SERVER_SAP_OAUTH_PROVIDER` (with the `SAP_` infix) — see the
> [env-var contract](../SAP_MCP_INTEGRATION.md#env-var-contract-external-sap-mcp-container--reference).

### A2. Create the AgentCore Identity outbound OAuth2 credential provider — **all**

`aws bedrock-agentcore-control create-oauth2-credential-provider` (or Console → custom provider),
`clientId`/`clientSecret` = the values from the secret (A1). The `oauthDiscovery` field differs by
variant — **this is the M2M-via-SOAUTH2 crux**:
- **M2M via SOAUTH2 (SAP-facing):** use `oauthDiscovery.authorizationServerMetadata` — explicit
  `authorizationEndpoint` + `tokenEndpoint` + `issuer` (issuer derived from the SAP token URL
  origin). Not `discoveryUrl`: a SAP token URL is not a `.well-known` document, and
  AgentCore's `discoveryUrl` enforces a
  `.+/\.well-known/(openid-configuration|oauth-authorization-server)` regex that a SAP token URL
  fails. Supply `authorizationEndpoint` + `tokenEndpoint` explicitly instead (see
  [SAP_MCP_INTEGRATION.md troubleshooting](../SAP_MCP_INTEGRATION.md#troubleshooting)).
- **M2M via external IdP (Entra/Okta-facing):** use a real `oauthDiscovery.discoveryUrl` = the IdP's
  `.well-known/openid-configuration` — an external IdP **does** publish one.

At runtime AgentCore Identity performs the **client-credentials** exchange and returns the SAP
access token; the token is never persisted in the MCP server
([identity-and-authentication](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/identity-and-authentication.html)).

### A3. Wire the Gateway Service target + Gateway OAuth2 provider (inbound-credential risk) — **all**

The M2M path is the **Gateway path**: a **"Service" Gateway target** pointing at the external
runtime's invocation URL, with `credentialProviderType: "OAUTH"` referencing a **Gateway OAuth2
credential provider**, `flow="M2M"`. (No direct-to-MCP wiring — that is OBO-only; the agent keeps
using the Gateway unchanged.)

> **Inbound-pool risk.** The Gateway OAuth2 provider **must point at the EXTERNAL stack's inbound
> pool**, not your own — else the runtime **401s** (`iss` mismatch). This is distinct from the
> outbound provider in A2. See [SAP_MCP_INTEGRATION.md troubleshooting](../SAP_MCP_INTEGRATION.md#troubleshooting).

> **Inbound coherence (external-IdP variant).** If you point the external stack at an **EntraId**
> inbound authorizer while running an M2M flow, the machine token your Gateway mints against your own
> Cognito pool is rejected on `iss`. Pick a Cognito inbound for the external stack. This is the
> *inbound* axis alone — `InboundAuthProvider` and `AuthFlow` are independent CloudFormation
> parameters, so an `EntraId`-inbound stack can carry any outbound flow. It is the AWS-side
> counterpart of the SAP-side issuer/audience mismatch.

---

## Checklist

| Side | Step | Flow row |
|---|---|---|
| **SAP** | S1 reuse technical System-type SU01 user + least-privilege PFCG | SU01 |
| **SAP** | S2 SOAUTH2 client-credentials client (**M2M via SOAUTH2**) | OAuth2 client (client creds) SOAUTH2 (M2M via SOAUTH2) |
| **SAP** | S3 scopes = service scope IDs (`<SERVICE>_0001`) | SAP OAuth scopes (wrong scope → 403) |
| **SAP** | S4 SICF `/sap/opu/odata/sap/` + `iwfnd/catalogservice;v=2` | SICF (All) |
| **SAP** | S5 (**M2M via external IdP**) SOIDC trust + STRUST + `oid` → technical-user alias | OIDC provider (Entra/Okta) SOIDC (M2M via external IdP) |
| **SAP** | S6 isolation smoke-test | acceptance |
| **Entra/Okta** | E1–E2 (**M2M via external IdP**) outbound M2M app + client-creds + scope | App registration (outbound OIDC/M2M) (M2M via external IdP) |
| **AWS** | A1 external stack M2M flow + SAP knobs | (external stack) |
| **AWS** | A2 AgentCore outbound provider (authServerMetadata M2M-via-SOAUTH2 / discoveryUrl M2M-via-external-IdP) | OAuth provider (SAP) M2M-via-SOAUTH2 / OIDC provider (Entra/Okta) M2M-via-external-IdP |
| **AWS** | A3 Gateway Service target + Gateway OAuth2 provider (inbound-credential risk + inbound coherence) | Gateway path |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| **401 from the external runtime** (`iss mismatch`) | Gateway OAuth2 provider points at your own Cognito, not the external stack's pool (the inbound-credential risk) | Point the Gateway provider at the external stack's inbound pool — A3 |
| **`discoveryUrl` regex rejection** creating the SAP provider | SAP token URL passed where a `.well-known` URL is expected (M2M via SOAUTH2) | Use `authorizationServerMetadata` (authEndpoint+tokenEndpoint+issuer) — A2 |
| **SAP 403** | Wrong scope (not a service scope ID), or bound technical user lacks PFCG | Set scopes to service scope IDs (S3); grant PFCG (S1) |
| **SAP 401** (M2M via SOAUTH2) | SOAUTH2 client/secret or token endpoint wrong | Re-check the SOAUTH2 client + `{clientId,clientSecret}` secret — S2/A1 |
| **SAP 401** issuer/`aud` mismatch (M2M via external IdP) | SOIDC issuer/audience wrong for the IdP-minted token | Fix SOIDC trust — S5 |
| **M2M-via-external-IdP token maps to no user** (SAP logon-failure page) | SOIDC mapping claim isn't `oid`, the alias holds the app registration's object id instead of the service principal's, or `iss` is the other Entra issuer version | Fix one S5 value at a time; `/sap/bc/ui2/start_up` confirms the mapped user |
| **M2M flow vs EntraId external inbound** | Inbound-authorizer mismatch (A3) | Point external stack at a Cognito inbound |
| **Target `READY` but zero tools** | Wrong external inbound scope, or `listing_mode: DYNAMIC` | Use the external pool's own resource-server scope; prefer `DEFAULT` — see [SAP_MCP_INTEGRATION.md](../SAP_MCP_INTEGRATION.md#troubleshooting) |

## Open items

- **Not yet run end to end in this sample** for either variant — validate against your own SAP
  system before production.
- **Confirm on your system:** SOAUTH2 client-credentials field labels and scope model (S2); the
  SOIDC Basis floor for the external-IdP variant (inherited from soidc-entra-obo.md S1); whether a
  dedicated OAuth/OIDC token-endpoint SICF node is required.
- **External stack:** use the `SAP_`-infixed form (`MCP_SERVER_SAP_OAUTH_PROVIDER`) that the
  server reads (A1).

## References

- [SAP_MCP_INTEGRATION.md](../SAP_MCP_INTEGRATION.md) — deploy model, env-var contract, external-runtime 401 on inbound-credential mismatch, `discoveryUrl` regex, M2M `authorizationServerMetadata`
- [SAP_SYSTEM_CONFIGURATION.md](../SAP_SYSTEM_CONFIGURATION.md) — the technical/service SU01 user (reused, not redone)
- [soidc-entra-obo.md](./soidc-entra-obo.md) — sibling OBO runbook; SOIDC/STRUST steps the M2M external-IdP variant reuses (its S4 human mapping does not apply to M2M — S5 here maps the machine identity)
- [AWS SAP-MCP — Identity and Authentication](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/identity-and-authentication.html) — the outbound-auth table (SAP OAuth2 client vs SAP OIDC trust)
- [AWS SAP-MCP — Configuration Reference](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/configuration-reference.html) — env vars, cross-validation rule #3 (`MCP_SERVER_SAP_OAUTH_PROVIDER`)
