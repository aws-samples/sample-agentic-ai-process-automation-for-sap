<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# M2M via SAP SOAUTH2 client-credentials / M2M via an external IdP — Operator Runbook (Machine Identity → SAP)

> **STATUS.** M2M via SAP SOAUTH2 client-credentials is the **GA / deploys-today** path:
> SAP itself is the OAuth server (SOAUTH2 client-credentials). It is
> **validated by design + current AWS docs; NOT yet run end-to-end against a production SAP
> system** — validate in your own account against your own SAP system before production.
> M2M via an external IdP (external IdP mints the machine token) is **preview**: it shares the
> same outbound provisioning path but has no built provisioning module yet, and
> AgentCore's M2M-OIDC path is documented for Entra and **undocumented for Okta**. Facts that
> could not be confirmed against a primary SAP doc are marked
> **UNVERIFIED**; confirm them on your system.

**Audience:** an SAP admin **+** an AWS operator (M2M-via-SOAUTH2). The external-IdP variant adds an **Entra/Okta admin**. Each
side owns a lane below; the checklist maps every step to the responsible operator.

For the deploy-model / env-var contract see the SAP MCP integration reference.
Base OData connectivity + the SU01 technical user are owned by the SAP system configuration
guide — do **not** redo BASIC/service-account
setup here; M2M reuses that same technical-user concept and adds SOAUTH2 (M2M-via-SOAUTH2) or SOIDC (M2M-via-external-IdP).
The SOIDC OIDC-provider-trust story (STRUST chain, SOIDC registration, claim mapping) is the
**machine-identity analog** of the sibling [soidc-entra-obo.md](./soidc-entra-obo.md) OBO runbook —
cross-linked below, **not** duplicated (M2M has **no human**, so there is no user-mapping story).

## M2M-via-SOAUTH2 vs M2M-via-external-IdP — who mints the token (the load-bearing distinction)

Grounded in the AWS SAP-MCP outbound-auth table
([identity-and-authentication](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/identity-and-authentication.html)):

| | **M2M via SAP SOAUTH2 client-credentials** (GA) | **M2M via an external IdP (Entra/Okta)** (preview) |
|---|---|---|
| Who is the OAuth server | **SAP itself** (SOAUTH2) | an **external IdP** (Entra / Okta) |
| Who mints the outbound token | SAP mints it (client-credentials) | the external IdP mints it (client-credentials) |
| SAP-side config | **SOAUTH2** OAuth 2.0 client | **SOIDC** OIDC-provider trust |
| AgentCore provider points at | **SAP's token endpoint** | the IdP discovery URL |
| Provider `oauthDiscovery` field | `authorizationServerMetadata` (see below) | `discoveryUrl` (real `.well-known`) |
| AWS-doc coverage | documented | Entra documented; **Okta undocumented** |

Both are **Mode-1 autonomous** flows: **no user, no user JWT, no identity propagation**. The
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

The SU01 technical user + its PFCG OData authorizations are owned by the SAP system configuration
guide. M2M does **not** federate a human;
the outbound token resolves to a **fixed technical user**. How that binding happens differs by variant:
- **M2M via SOAUTH2:** the SOAUTH2 OAuth 2.0 client is bound to a SAP user (the client's resource owner /
  service user) — SAP mints the token for that user. See S2.
- **M2M via external IdP:** SAP must map the **externally-minted** machine token to a fixed technical user. The
  mechanism (client_id → fixed SU01, vs requiring SAP-as-authorization-server) is **UNVERIFIED** —
  see S5 and the Open items.

### S2. Create the SOAUTH2 OAuth 2.0 client (client-credentials) — **M2M via SOAUTH2** — field labels **UNVERIFIED**

SAP GUI transaction **SOAUTH2**. Register an OAuth 2.0 client for the **client-credentials** grant
so SAP acts as its own authorization server and mints the outbound token. Record the **client id +
client secret** — these become the `{clientId, clientSecret}` Secrets Manager secret the external
stack reads (see A1). Bind the client to the technical SU01 user from S1 so the minted
token carries that user's SAP authorizations. Exact SOAUTH2 field labels and the scope-model
mapping are **UNVERIFIED** — confirm in the live transaction. (SOAUTH2 auth-code clients for
interactive user login are a **different** setup owned by the USER_FEDERATION path — not this
runbook.)

### S3. SAP OAuth "scopes" are OData **service names**, not scope URIs — **all**

`MCP_SERVER_SAP_OAUTH_SCOPES` takes **SAP OData service names** (e.g.
`ZAPI_SALES_ORDER_SRV_0001`), **NOT** standard OAuth/OIDC scope URIs. The AWS config-reference
labels the field "OAuth scopes" but its own example value is a service name
([configuration-reference](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/configuration-reference.html)).
A wrong/foreign scope → **HTTP 403** from SAP. Each named service must be SICF-activated (S6) and
PFCG-authorized (S1) for the bound technical user.

### S4. SICF: activate the OData service nodes — **all**

SAP GUI transaction **SICF** (right-click → Activate). Activate the OData runtime tree
`/sap/opu/odata/sap/` and each service subnode you exposed via S3 scopes, plus (if
`MCP_SERVER_USE_SAP_CATALOG=true`) the IWFND catalog service
`/sap/opu/odata/iwfnd/catalogservice;v=2`. Same node set the sibling runbooks activate — cross-link
[soidc-entra-obo.md S6](./soidc-entra-obo.md); do not re-derive.

### S5. (M2M via external IdP only) SOIDC trust + STRUST chain for the external IdP — **UNVERIFIED**

The external-IdP variant makes SAP **validate an externally-minted machine token**, so SAP needs the same SOIDC
OIDC-provider trust + STRUST TLS chain as the OBO path — **register those exactly per
[soidc-entra-obo.md S2/S3](./soidc-entra-obo.md)** (STRUST full chain + ICM restart; SOIDC issuer =
the IdP, audience = the app whose id the machine token's `aud` carries). **Do not duplicate** those
steps here.

> **The external-IdP machine-identity gap (the crux — UNVERIFIED).** A machine token carries **no human
> claim** (no email/UPN) — only a client/app id (`appid`/`azp`) as subject. The OBO SOIDC claim
> mapping (soidc-entra-obo.md S4) keys on a **human** claim and **explicitly forbids** mapping on an
> opaque `sub`, so it **cannot** map a machine token as written. Whether SOIDC supports a
> **client_id → fixed technical user** mapping for an externally-minted token is **UNVERIFIED**
> against any primary SAP doc reachable here. The two plausible-but-unconfirmed resolutions: (a) use
> **M2M via SAP SOAUTH2 client-credentials** instead (SAP-as-authorization-server via SOAUTH2, where the client is already bound to a
> technical user — no external-token mapping needed); or (b) a SOIDC/SOAUTH2 config that binds a
> client_id/app-role claim to a fixed technical user — **confirm on your own SAP system before
> relying on the external-IdP variant.** This is exactly why the external-IdP variant remains preview / not-yet-built.

### S6. Smoke-test in isolation (before full E2E) — **all**

- **M2M via SOAUTH2:** obtain a token from SAP's SOAUTH2 token endpoint with the client credentials, present it
  to one activated OData service. **401** → SOAUTH2 client/secret or token-endpoint wrong. **403** →
  the bound technical user lacks PFCG authorization for that service (S1/S3).
- **M2M via external IdP:** present an IdP-minted machine token to one service. **401** with issuer/`aud` mismatch →
  SOIDC issuer/audience wrong (S5). **403** → the client_id→technical-user binding is missing/wrong
  (the S5 gap) **or** the technical user lacks PFCG.
- **Audit:** SM20 / RSAU_* shows the action under the **bound technical user** (expected — there is
  no human to attribute; M2M is a service identity, unlike the OBO path's human-audit acceptance test).

---

## Entra / Okta-side steps (external-IdP admin) — **external-IdP variant only, preview**

> Only needed for the external-IdP variant. The GA M2M-via-SOAUTH2 path needs **no external IdP** — skip this
> lane entirely for the SOAUTH2 path.

### E1. Register the outbound M2M app + client-credentials — **external-IdP variant**

Entra: App registrations → New registration; under Certificates & secrets create a client secret.
Okta: Applications → an OIDC app + a Custom Authorization Server (Security → API). The app's
**client id + secret** become the `{clientId, clientSecret}` secret the external stack reads. This
app is the machine identity — AgentCore Identity uses it for the **client-credentials** grant to
mint the outbound token. Record the app/client id (the machine token's subject/`appid`).

> **Okta is a stretch.** AWS documents the M2M-OIDC path for Entra; Okta client-creds is
> "SAP yes / AgentCore undocumented". Treat the Okta variant as experimental.

### E2. Expose the SAP scope / app-role the SAP SOIDC trust validates — **external-IdP variant** — **UNVERIFIED**

The machine token must carry an `aud`/scope (Entra: Expose an API / app role; Okta: custom
auth-server scope) that SAP's S5 SOIDC trust accepts, and a **claim SAP can bind to a fixed
technical user** (see the S5 crux). Which claim (client_id/`appid`/an app-role) SAP keys on is
**UNVERIFIED** — coordinate with the SAP admin (S5).

---

## AWS / AgentCore-side steps (AWS operator)

> The external AWS-for-SAP MCP stack, its inbound pool, and its
> outbound OAuth provider are owned externally — not deployed here. The infrastructure on this side
> mints the **Gateway Service target + a Gateway OAuth2 credential provider** (the M2M path is the Gateway
> path, never direct-to-MCP).

### A1. Deploy the external stack with the M2M flow + SAP knobs — **all**

On the external stack set the container env vars (CFN params; editable via Bedrock AgentCore console
→ Runtime → Update Hosting → Advanced Configurations). These are **not** set on this side — the external
stack owns them:
- `MCP_SERVER_SAP_OAUTH_FLOW=M2M`
- `MCP_SERVER_SAP_BASE_URL=https://<sap-host>/sap/opu/odata/sap/`
- `MCP_SERVER_SAP_OAUTH_PROVIDER=<m2m-provider-name>` (the AgentCore Identity provider **name**)
- `MCP_SERVER_SAP_OAUTH_SCOPES=<sap-service-name(s)>` — **SAP OData service names, not scope URIs** (S3)
- Start read-only (`MCP_SERVER_WRITE_ENABLED=false`); enable writes there when ready — the Gateway's
  Cedar policy is defense-in-depth on top.
- Secret: `{clientId, clientSecret}` in Secrets Manager (M2M via SOAUTH2 = the SOAUTH2 client;
  M2M via external IdP = the Entra/Okta app).

> **Env-var name:** use `MCP_SERVER_SAP_OAUTH_PROVIDER` (with the `SAP_` infix) — see the
> SAP MCP integration reference's env-var contract.

### A2. Create the AgentCore Identity outbound OAuth2 credential provider — **all**

`aws bedrock-agentcore-control create-oauth2-credential-provider` (or Console → custom provider),
`clientId`/`clientSecret` = the values from the secret (A1). The `oauthDiscovery` field differs by
variant — **this is the M2M-via-SOAUTH2 crux**:
- **M2M via SOAUTH2 (SAP-facing):** use `oauthDiscovery.authorizationServerMetadata` — explicit
  `authorizationEndpoint` + `tokenEndpoint` + `issuer` (issuer derived from the SAP token URL
  origin). **NOT** `discoveryUrl`: a SAP token URL is **not** a `.well-known` document, and
  AgentCore's `discoveryUrl` enforces a
  `.+/\.well-known/(openid-configuration|oauth-authorization-server)` regex that a SAP token URL
  fails. Supply `authorizationEndpoint` + `tokenEndpoint` explicitly instead. (See the SAP MCP
  integration reference's "`discoveryUrl` regex rejection" note.)
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
> outbound provider in A2. See the SAP MCP integration reference's "401 in external mode" note.

> **Inbound coherence (external-IdP variant).** If you point the external stack at an **EntraId**
> inbound authorizer while running an M2M flow, the machine token your Gateway mints against your own
> Cognito pool is rejected on `iss`. Pick a Cognito inbound for the external stack. This is the
> *inbound* axis alone — `InboundAuthProvider` and `AuthFlow` are independent CFN parameters, so an
> `EntraId`-inbound stack can carry any outbound flow. The AWS-side mirror of the SAP-side
> issuer/audience trap.

---

## Checklist

| Side | Step | Flow row |
|---|---|---|
| **SAP** | S1 reuse technical SU01 + PFCG | SU01 (SAP system configuration guide) |
| **SAP** | S2 SOAUTH2 client-credentials client (**M2M via SOAUTH2**, **UNVERIFIED** labels) | OAuth2 client (client creds) SOAUTH2 (M2M via SOAUTH2) |
| **SAP** | S3 scopes = OData service names | SAP OAuth scopes (wrong scope → 403) |
| **SAP** | S4 SICF `/sap/opu/odata/sap/` + `iwfnd/catalogservice;v=2` | SICF (All) |
| **SAP** | S5 (**M2M via external IdP**) SOIDC trust + STRUST + client_id→user (**UNVERIFIED**) | OIDC provider (Entra/Okta) SOIDC (M2M via external IdP) |
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
| **SAP 403** | Wrong scope (not a service name), or bound technical user lacks PFCG | Set scopes to OData service names (S3); grant PFCG (S1) |
| **SAP 401** (M2M via SOAUTH2) | SOAUTH2 client/secret or token endpoint wrong | Re-check the SOAUTH2 client + `{clientId,clientSecret}` secret — S2/A1 |
| **SAP 401** issuer/`aud` mismatch (M2M via external IdP) | SOIDC issuer/audience wrong for the IdP-minted token | Fix SOIDC trust — S5 |
| **M2M-via-external-IdP token maps to no user** | client_id→technical-user binding missing (the S5 gap) | **UNVERIFIED** — use M2M via SAP SOAUTH2 client-credentials (SAP-as-authz-server) or confirm SOIDC client-id binding on your system |
| **M2M flow vs EntraId external inbound** | Inbound-authorizer mismatch (A3) | Point external stack at a Cognito inbound |
| **Target `READY` but zero tools** | Wrong external inbound scope, or `listing_mode: DYNAMIC` | Use the external pool's own resource-server scope; prefer `DEFAULT` — see the SAP MCP integration reference |

## Open items (carried, not blocking the M2M-via-SOAUTH2 GA-ness)

- **Not run end-to-end** against a production SAP system (whole SAP-MCP integration is
  reference-design — see the SAP MCP integration reference's status banner).
- **THE EXTERNAL-IdP CRUX (UNVERIFIED against primary SAP docs):** how SAP maps a **no-human, app-only**
  machine token (subject = client/app id, no email/UPN) to a **fixed technical SU01 user**. The AWS
  M2M flow documents **no** user-mapping step and never names a technical user; the only documented
  SOIDC mapping (soidc-entra-obo.md S4) keys on a **human** claim and forbids mapping on an opaque
  subject — so it cannot map an app-only token as written. Whether SOIDC supports a
  **client_id → fixed-technical-user** binding (vs requiring **M2M via SAP SOAUTH2 client-credentials / SAP-as-authorization-server via
  SOAUTH2**, where the client is already bound to a technical user, vs BASIC service-account) is
  **UNVERIFIED** — confirm on your own SAP system before relying on the external-IdP variant. (This is why the
  external-IdP variant stays preview / not-yet-built.)
- **UNVERIFIED against primary SAP docs:** SOAUTH2 client-credentials field labels + scope model
  (S2); SOIDC Basis 7.56 SP1+ floor for the external-IdP variant (inherited from soidc-entra-obo.md S1); whether a
  dedicated OAuth/OIDC token-endpoint SICF node is required.
- **UNVERIFIED against AWS/deployed stack:** the `SAP_` infix the deployed container reads (A1);
  whether AgentCore's M2M-OIDC path works for **Okta** (Entra documented, Okta undocumented).

## References

- SAP MCP integration reference — deploy model, env-var contract, external-runtime 401 on inbound-credential mismatch, `discoveryUrl` regex, M2M `authorizationServerMetadata`
- SAP system configuration guide — the technical/service SU01 user (reused, not redone)
- [soidc-entra-obo.md](./soidc-entra-obo.md) — sibling OBO runbook; SOIDC/STRUST steps the M2M external-IdP variant reuses (user-mapping story is human-only, does NOT apply to M2M)
- [AWS SAP-MCP — Identity and Authentication](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/identity-and-authentication.html) — the outbound-auth table (SAP OAuth2 client vs SAP OIDC trust)
- [AWS SAP-MCP — Configuration Reference](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/configuration-reference.html) — env vars, cross-validation rule #3 (`MCP_SERVER_SAP_OAUTH_PROVIDER`)
