<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# SOIDC / Entra-OBO — Operator Runbook (OBO / ON_BEHALF_OF_TOKEN_EXCHANGE, Direct-Entra → OBO → SAP)

> **VERIFIED END-TO-END.** This flow was exercised in a full end-to-end run against a
> live S/4HANA 2023 system (SAP_BASIS 7.58): browser Entra SPA login → Entra inbound →
> server-side `ON_BEHALF_OF_TOKEN_EXCHANGE` OBO → SAP OData returned real data as the mapped
> SU01 user. The direct-IdP frontend, JWT inbound authorizer, and OBO outbound wiring are all
> built and deployed.

> **STATUS.** Flagship OBO path: Direct-Entra SPA login → Entra inbound → server-side
> `ON_BEHALF_OF_TOKEN_EXCHANGE` OBO → SAP OData as the signed-in human, **no second login**.
> **Verified against one S/4HANA 2023 system (SAP_BASIS 7.58)** — the SAP version floors (S1)
> and SOIDC Feature-Pack claim-mapping (S4) are confirmed for that release. Field labels marked
> **UNVERIFIED** below were confirmed during initial testing; re-confirm on your own release
> before production, and validate in your own account/SAP system.

**Audience:** an SAP admin **+** an Entra admin **+** an AWS operator, executing together.
Each side owns a lane below; the checklist maps every step to the responsible operator.

For the deploy-model / env-var contract see your base SAP MCP integration documentation.
For the **interactive** per-user flow (USER_FEDERATION, 3-legged, browser redirect) see the
sibling [uf-oidc.md](uf-oidc.md) and the email-federation variant [uf-saml.md](uf-saml.md).

## When to pick OBO (vs USER_FEDERATION)

| | **OBO (this doc)** | **USER_FEDERATION (OIDC)** |
|---|---|---|
| User interaction after SPA login | **None** — server-side exchange | Interactive 3-legged login to SAP's OAuth server |
| Grant | RFC 7523 JWT-bearer (Entra `jwt-bearer`, `requested_token_use=on_behalf_of`) | Authorization-code (3-legged) |
| Topology | **Direct-to-MCP** (the runtime dials the external MCP server directly, user's Entra JWT is the primary bearer) | Gateway User target |
| SAP trust | **SOIDC** OIDC-provider trust to Entra, direct | IAS corporate-IdP federation (email join) |
| Frontend | `direct-entra`: SPA logs into Entra directly | Cognito/IdP + `/auth/callback` |
| SAP-side redirect/callback | **None** (server-to-server) | Two callback URLs (see below) |

Pick **OBO** for the seamless enterprise story where the SPA already logs into Entra and no
second SAP prompt is acceptable. Pick USER_FEDERATION when the SAP OAuth server must drive an
interactive login.

## End-to-end flow (short)

```
SPA (Entra login, direct-entra) ─▶ Runtime (validates the user's Entra JWT: discovery URL + allowed audiences)
                       ─▶ external AWS-for-SAP MCP DIRECTLY (user's Entra JWT = Authorization: Bearer)
                       ─▶ AgentCore Identity OBO exchange (outbound app creds, RFC 7523 jwt-bearer)
                       ─▶ SAP-scoped token carrying the user's identity
                       ─▶ SAP OData: SAP validates the issuer, maps a claim → SU01 user
```

Server-side facts that ground every step below
([AWS SAP-MCP identity doc](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/identity-and-authentication.html)):
the OBO exchange is **entirely server-side** — AgentCore Identity exchanges the user's Entra JWT
for a **new SAP-scoped access token** (using the outbound Entra app's client credentials); the
MCP server forwards **that** token to SAP. SAP therefore only ever validates **one issuer** (the
Entra outbound app / tenant) and maps **one subject claim** to a SAP user. The direct-to-MCP vs
Gateway topology is an AWS/agent-side detail and changes **nothing** on the SAP box.

---

## SAP-side steps (SAP admin)

This lane is **only the OBO trust delta**. Base OData connectivity + the SU01 service user are
owned by your base SAP system configuration — do **not** redo BASIC/service-account setup here.

### S1. Verify the Basis floor that gates SOIDC — **UNVERIFIED**

SAP GUI: **System → Status** (component `SAP_BASIS`); SPAM/SAINT for the SP level. SOIDC
(OIDC-provider trust for token-based inbound) requires **SAP_BASIS 7.56 SP1+**
*(**UNVERIFIED** against help.sap.com — confirm against your release)*. Below that floor OBO is
impossible; fall back to USER_FEDERATION (OIDC), which needs no SOIDC.

### S2. Import the Entra token-endpoint TLS chain into STRUST

SAP GUI transaction **STRUST** → SSL client PSE. SAP fetches Entra's JWKS/discovery over TLS
(`login.microsoftonline.com/<tenant>/v2.0/.well-known/openid-configuration`). Import the **full
chain** (leaf + intermediates + Microsoft's public root CA) into the SSL client PSE, then restart
ICM / the PSE-consuming work processes. **Root-only imports are the classic silent TLS failure** —
import the whole chain.

### S3. Create the OIDC provider trust for Entra in SOIDC — field labels **UNVERIFIED**

SAP GUI transaction **SOIDC**. Register Microsoft Entra as an OIDC provider:
- **Issuer:** `https://login.microsoftonline.com/<tenant>/v2.0`
- **Discovery/well-known:** `https://login.microsoftonline.com/<tenant>/v2.0/.well-known/openid-configuration`
- **Audience/client:** must match the audience of the token the OBO exchange **mints** — i.e. the
  **OUTBOUND** Entra app (`obo-app-client-id`) or the SAP OAuth client, **not** the inbound SPA
  client. Trusting the SPA client id yields an `iss`/`aud`-mismatch 401 (the SAP-side mirror of
  the AWS audience-mismatch 401).

Exact SOIDC field labels (issuer / audience / subject-claim / discovery-URL) are **UNVERIFIED** —
confirm in the live transaction.

### S4. Map the Entra `sub` → SU01 business user via a custom claim mapping — **UNVERIFIED**

SAP GUI transaction **SOIDC** (claim mapping) + **SU01** (target users). Entra emits an
**opaque, app-pairwise `sub`** — it is **not** the email and will **not** match an SU01 user.
**Do not map on `sub`.** Configure a **custom claim mapping** on a stable human claim
(`preferred_username`/UPN or `email`) → the SU01 user whose email/alias matches. This custom
mapping requires **SOIDC Feature Pack 2+** *(**UNVERIFIED**)*. (Contrast: Okta puts
email in `sub` and needs only Basis 7.56 SP1.) Ensure each target SU01 user exists with the
matching email/UPN and holds the PFCG OData authorizations for the services the agent calls.

> **THE ENTRA-OBO TRAP.** Mapping on Entra's opaque `sub` never matches. This is the single most
> common failure specific to this flow. See the email-join principle in the SAML/email-federation
> runbook [uf-saml.md](uf-saml.md) (that runbook covers the IAS/email-federation variant; this flow
> differs — SAP trusts Entra **directly**, not via IAS, and same-sub trust is **not transitive**).

### S5. Confirm the Entra token carries the mapping claim (coordinate with the Entra lane)

The SAP-scoped token AgentCore mints must **carry** the stable claim your S4 mapping binds to
(`preferred_username`/`email`/`upn`). That is set **Entra-side** on the OUTBOUND app (Token
configuration / optional claims) — flag it to the Entra admin (step E3). SAP only chooses **which**
incoming claim to map; you cannot conjure a claim SAP never receives.

### S6. Activate the required SICF service nodes — token-endpoint node **UNVERIFIED**

SAP GUI transaction **SICF** (right-click → Activate). Activate the OData runtime tree
`/sap/opu/odata/sap/` (and each service subnode you exposed via scopes), plus the IWFND catalog
service `/sap/opu/odata/iwfnd/catalogservice;v=2` (used by `find_sap_services` / catalog fetch when
`MCP_SERVER_USE_SAP_CATALOG=true`). Whether a dedicated OAuth/OIDC token-endpoint SICF node (e.g.
under `/sap/bc/sec/oauth2`) must **also** be active for your release is **UNVERIFIED** — confirm.

### S7. Smoke-test the SAP trust in isolation (before full E2E)

- **STRUST:** confirm SAP reaches + trusts the Entra JWKS host over TLS (no handshake error in
  `dev_icm` / SMICM).
- **One OData service:** present a real SAP-scoped token (from a manual OBO exchange in the AWS
  lane) to one activated service. A **401** with issuer/`sub`-mismatch → SOIDC issuer/audience or
  the S4 claim mapping is wrong. A **403** → the mapped SU01 user lacks PFCG authorization.
- **Audit proof (the acceptance test):** the SAP security audit log (SM20 / RSAU_*) must show the
  action under the **mapped human SU01 user**, not a service account. A silent service-account
  fallback means the OBO identity did not survive — the open "real-user audit proof" item carried
  from the sibling runbooks (**UNVERIFIED** end-to-end).

---

## Entra-side steps (Entra admin) — 2-app vs 3-app

**Default = TWO apps:** the inbound SPA client + the outbound exchange (middle-tier) app. A
**third** "Resource app representing AgentCore" is only needed when your MCP-client topology
requires a distinct resource whose `aud` the inbound token targets; in the common
case that is satisfied by `knownClientApplications`/`preAuthorizedApplications` on the outbound
app rather than a separate registration. Ship the 2-app path; add the 3rd only if your token's
`aud` must name AgentCore separately. Grant: Entra OBO is **RFC 7523 jwt-bearer**
(`grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer`, `requested_token_use=on_behalf_of`) —
**NOT** RFC 8693 TOKEN_EXCHANGE
([Microsoft OBO doc](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-on-behalf-of-flow)).

### E1. Register the INBOUND app (the direct-Entra SPA client)

App registrations → New registration. Name e.g. `quickstart-spa`. Add a **Single-page
application (SPA)** platform with redirect URI = the SPA's own login callback (frontend origin,
**not** the AgentCore callback). Record **Application (client) ID = `spa-client-id`** and
**Directory (tenant) ID = `<tenant>`**. This is the client the SPA uses for Auth-Code + PKCE to
obtain the user's Entra JWT. The SPA emits **both** `authority`
(`https://login.microsoftonline.com/<tenant>/v2.0`) **and** `metadata_url`
(`.../v2.0/.well-known/openid-configuration`) — `oidc-client-ts` ^3.5.0 throws at signin if
`authority` is falsy.

### E2. Register the OUTBOUND (middle-tier / confidential) app for the exchange

App registrations → New registration. Name e.g. `quickstart-obo-exchange`. Record **Application
(client) ID = `obo-app-client-id`**. Under **Certificates & secrets** create a client secret
(record once). AgentCore Identity uses `obo-app-client-id` + this secret as the confidential-client
credentials for the server-side exchange. Store the secret in Secrets Manager; pass its ARN as
`entra_client_secret_arn` to the external SAP-MCP stack. **Do not** put a SPA/frontend redirect here.

> **Custom-signing-key apps (including SSO-configured enterprise apps) cannot be OBO middle-tier
> apps** — keep the outbound exchange app a plain app registration.

### E3. Expose the SAP API scope + optional claims on the outbound app

**Expose an API** → set an Application ID URI (e.g. `api://obo-app-client-id`) and add a delegated
scope (e.g. `SAP.Access` / `user_impersonation`). This scope is what the OBO exchange requests and
what SAP's SOIDC trust validates. **Token version trap:** for v2.0 access tokens set
`accessTokenAcceptedVersion=2` in the manifest **and** expose an API scope included in the SPA's
authorize request; for v1.0 include `<app-id>/.default` in the authorize URL — otherwise Entra
issues a Graph-only token AgentCore can't validate. Under **Token configuration**, add the stable
optional claim (`preferred_username`/`email`/`upn`) the SAP S4 mapping binds to.

### E4. Grant the inbound app permission to the outbound app + API permissions

On the **inbound SPA app** → API permissions → Add a permission → My APIs → the outbound app →
add the delegated scope from E3, so the user's Entra JWT carries an `aud`/`scp` usable by the OBO
exchange. **`aud` must equal the app making the OBO request (`obo-app-client-id`)** — a token
minted for a different app (e.g. Graph) cannot be redeemed. Add any downstream permissions the
outbound app itself needs (e.g. Graph `openid`/`profile`).

### E5. Grant admin consent

API permissions → **Grant admin consent for `<tenant>`**, so delegated scopes are pre-consented
tenant-wide and the seamless (no-second-prompt) OBO works. Alternatively wire combined consent via
the outbound app manifest (`knownClientApplications` / `preAuthorizedApplications`). **Do not
combine `.default` with other dynamic delegated scopes in one authorize request** → `AADSTS70011`.

### E6. Register the AgentCore callback URL on the OUTBOUND app — **after deploy**

**CRITICAL ORDERING.** The callback URL is **unique per credential provider** and unknown until
**after** `CreateOauth2CredentialProvider` runs (step A4). Sequence: (1) create the outbound app +
secret (E2), (2) deploy so AgentCore Identity mints the provider — its response returns a
`callbackUrl` of the form
`https://bedrock-agentcore.<region>.amazonaws.com/identities/oauth2/callback/<provider-guid>`,
(3) return here and paste that exact `callbackUrl` as a **Web** redirect URI on the outbound app.
This is a machine/AgentCore redirect — distinct from the SPA's own login redirect (E1) and from
`MCP_SERVER_APP_CALLBACK_URL` (the USER_FEDERATION `/auth/callback` frontend route, which OBO does
**not** use). Read the value off the deployed provider —
`get-oauth2-credential-provider` returns it as a top-level `callbackUrl`.

---

## AWS / AgentCore-side steps (AWS operator)

> The deployment does **not** provision the external AWS-for-SAP MCP stack, its inbound Entra pool,
> or its OAuth provider — those are owned externally. For OBO, the runtime dials the external MCP
> server directly and **skips the Gateway entirely**.

### A1. Deploy the external stack with Entra INBOUND (not Cognito)

On the external AWS-for-SAP MCP CloudFormation stack, select the **External Identity Provider**
inbound option = **Microsoft Entra ID**, so the AgentCore Runtime validates the user's Entra JWT
directly. The runtime validates the inbound JWT against the discovery URL + allowed audiences
**before** the OBO exchange. Inbound CFN parameter names:

| Parameter | Value |
|---|---|
| `InboundAuthProvider` | `EntraId` |
| `DiscoveryUrl` | `https://login.microsoftonline.com/<tenant>/v2.0/.well-known/openid-configuration` |
| `AllowedAudiences` | the **OUTBOUND** exchange app's client id |
| `AuthFlow` | `ON_BEHALF_OF_TOKEN_EXCHANGE` |
| `OauthScopes` | `api://<outbound-app-id>/<scope>` |

`AllowedAudiences` is the **outbound** app, not the SPA: the inbound token must already be minted
*for* the app that performs the exchange, so the SPA requests `api://<outbound-app-id>/<scope>` and
Entra sets `aud` to the outbound app. Setting the SPA's id here rejects every real token.

### A2. Set the outbound flow + SAP targets on the external stack

AgentCore Runtime env vars (external stack; editable via Bedrock AgentCore console → Runtime →
Update Hosting → Advanced Configurations):
- `MCP_SERVER_SAP_OAUTH_FLOW=ON_BEHALF_OF_TOKEN_EXCHANGE`
- `MCP_SERVER_SAP_BASE_URL=https://<sap-host>/sap/opu/odata/sap/`
- `MCP_SERVER_SAP_OAUTH_SCOPES=<sap-service-name(s)>` e.g. `ZAPI_SALES_ORDER_SRV_0001` — these are
  **SAP OData service names, NOT OAuth scope URIs**; each must be SICF-activated (S6) and
  PFCG-authorized (S4) for the mapped user or SAP returns **403**.
- Start read-only (`MCP_SERVER_WRITE_ENABLED=false`). Enabling writes later means a stack update or
  a second stack — the flags are CFN parameters, and disabled operations simply do not appear in
  `tools/list`. Our own `cdk/lib/sap-mcp-stack.ts` never creates a runtime, so `make deploy` cannot
  flip them.

### A3. Point the runtime at the OBO provider by name

`MCP_SERVER_SAP_OAUTH_PROVIDER=<obo-provider-name>`. The runtime validates this provider exists in
AgentCore Identity at startup or fails to start.

> **Env-var name:** use `MCP_SERVER_SAP_OAUTH_PROVIDER` (with the `SAP_` infix). Confirmed live on
> the deployed container alongside `MCP_SERVER_SAP_OAUTH_FLOW` and `MCP_SERVER_SAP_OAUTH_SCOPES`.

### A4. Create the AgentCore Identity OBO credential provider (RFC 7523 for Entra)

`aws bedrock-agentcore-control create-oauth2-credential-provider` (or Console → custom provider).
For Entra choose **`grantType=JWT_AUTHORIZATION_GRANT`** (RFC 7523 §2.1) — Entra's OBO is the
JWT-bearer pattern, **not** RFC 8693 TOKEN_EXCHANGE. Either use the built-in **MicrosoftOauth2**
provider (auto-adds `requested_token_use=on_behalf_of`) or a Custom provider with:
`oauthDiscovery.discoveryUrl` = the Entra `.well-known/openid-configuration`;
`clientId=<obo-app-client-id>`; `clientSecret=<obo-app-secret>`;
`clientAuthenticationMethod=CLIENT_SECRET_BASIC`;
`onBehalfOfTokenExchangeConfig.grantType=JWT_AUTHORIZATION_GRANT` (no actor token for this grant).
At runtime the MCP server calls `GetWorkloadAccessTokenForJWT` (mints the workload token that
seeds the exchange), then `GetResourceOauth2Token` with `oauth2Flow=ON_BEHALF_OF_TOKEN_EXCHANGE`
([AWS OBO doc](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/on-behalf-of-token-exchange.html)).
Grant mode is fixed at provider creation, not at call time. Then complete **E6** (register the
returned callbackUrl on the outbound Entra app).

> RFC 8693 TOKEN_EXCHANGE (inbound JWT as `subject_token`, `actorTokenContent` =
> `M2M`|`AWS_IAM_ID_TOKEN_JWT`|`NONE`) is the mode for IdPs that implement standard token exchange
> — **not** Entra. `AWS_IAM_ID_TOKEN_JWT` additionally needs the account enabled for outbound web
> identity federation; **not needed** on the Entra jwt-bearer path.

---

## The callback / redirect URLs (do not conflate)

Three different URLs get confused across this OBO flow and the USER_FEDERATION sibling flow:

| URL | Owner | Registered where | Used by |
|---|---|---|---|
| SPA login redirect | Our frontend (inbound app) | INBOUND Entra app (SPA platform) | SPA Auth-Code + PKCE (E1) |
| AgentCore provider `callbackUrl` (`.../identities/oauth2/callback/<guid>`) | AWS / AgentCore Identity | **OUTBOUND** Entra app (Web platform) | The OBO credential provider (E6/A4) |
| `MCP_SERVER_APP_CALLBACK_URL` (`/auth/callback`) | Our frontend | Our config | **USER_FEDERATION only — NOT OBO** |

**OBO is server-side and non-interactive:** `MCP_SERVER_APP_CALLBACK_URL` is required only for
USER_FEDERATION per the config-reference — the sibling runbook [uf-oidc.md](uf-oidc.md) covers that
"two callback URLs" model. Don't go hunting for a SAP redirect URI OBO never uses; the
**only** redirect that matters for OBO is the AgentCore provider callback on the OUTBOUND app.

---

## Checklist

| Side | Step | Area |
|---|---|---|
| **SAP** | S1 Basis 7.56 SP1+ floor (**UNVERIFIED**) | SOIDC prerequisite |
| **SAP** | S2 STRUST full Entra TLS chain + ICM restart | SSL certs (Entra) / STRUST |
| **SAP** | S3 SOIDC OIDC provider for Entra (issuer/audience = **outbound** app) | OIDC provider (Entra) |
| **SAP** | S4 `sub`→SU01 custom claim mapping (Feature Pack 2+, **UNVERIFIED**) | sub-claim mapping |
| **SAP** | S6 SICF: `/sap/opu/odata/sap/` + `iwfnd/catalogservice;v=2` | SICF |
| **SAP** | S7 isolation smoke-test + real-user audit proof | acceptance |
| **Entra** | E1 inbound SPA app-reg | App registration (inbound) |
| **Entra** | E2 outbound OIDC app-reg + secret | App registration (outbound OIDC) |
| **Entra** | E3–E5 expose scope, API perms, admin consent | App registration (OBO + API perms) |
| **Entra** | E6 AgentCore callback on outbound app (after deploy) | Redirect URI (AgentCore callback) |
| **AWS** | A1 external stack Entra inbound + discovery | External IdP discovery (Entra) |
| **AWS** | A4 AgentCore OBO provider (RFC 7523) | AgentCore — OBO (Entra) / OIDC provider (Entra) |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| **Inbound 401** at the runtime | No `Authorization` header, or a *claim* check failed: wrong `iss` (token from another IdP/tenant), or expired. The authorizer compares claims **before** verifying the signature, so a 401 means crypto was never reached | Send an **access token** for the right tenant, unexpired; align the discovery URL (A1) |
| **Inbound 403** at the runtime | Header present but unparseable (empty value, missing `Bearer ` prefix, `alg=none`), **or** `iss`+`aud` matched and signature verification then failed. Also a raw id_token / Graph-scoped token whose `aud` is not the outbound app | SPA must acquire an access token scoped to the outbound app's exposed scope (E3/E4); align allowed audiences (A1) |
| **Exchange fails** | Entra configured as TOKEN_EXCHANGE/`subject_token` | Use `JWT_AUTHORIZATION_GRANT` (RFC 7523) — A4 |
| **`AADSTS70011`** | `.default` combined with dynamic delegated scopes in one authorize request | Use `.default` alone, or split requests — E5 |
| **SAP 401**, issuer/`sub` mismatch | SOIDC issuer/audience trusts the **inbound SPA** client, or maps on Entra's opaque `sub` | Trust the **outbound** app audience (S3); map on `preferred_username`/`email` (S4) |
| **SAP 403** | Mapped SU01 user lacks PFCG authorization, or service not SICF-activated | Grant PFCG on the service; activate SICF node (S4/S6) |
| **`interaction_required` (401 + claims challenge)** | Conditional Access / MFA step-up on the downstream resource | Client must resolve the claims challenge; happy path needs no second login |
| **App-only / autonomous token** rejected for OBO | Entra OBO "only works for user principals" | Autonomous/poller path cannot use OBO — keep it on the service-account flow |
| **Deploy/validation fails** on OBO/external mismatch | OBO selected but the external stack's inbound is not Entra (a machine/M2M token would be 401'd by the Entra inbound authorizer, and vice-versa) | Redeploy the external stack with Entra inbound, or pick a non-OBO profile |

## Open items (carried, not blocking supported-ness)

- **Not run against a *production* SAP system.** The full flow — human Entra login → OBO exchange →
  OData read → SAP-side attribution to the mapped SU01 user — is proven end-to-end on the `SB2` demo
  system (2026-07-30). One `odata_update` write has been exercised (see below); create, delete and
  function-import have not. The whole SAP-MCP integration remains reference-design.
- **Write, exercised once on a dedicated write-enabled MCP (2026-07-30).** Write flags are
  **deploy-time CFN parameters**, not runtime toggles, so proving the write path needed a second
  external stack: `aws-for-sap-mcp-server-authverify` (`UniqueId=dzwr01`), Entra-inbound,
  `AuthFlow=ON_BEHALF_OF_TOKEN_EXCHANGE`, `WRITE`/`UPDATE`/`READ` true and
  `CREATE`/`DELETE`/`FUNCTION_IMPORT` false. `odata_update` on one free-text PO header field
  round-tripped `''` → `'GATE4-OBO'` → `''`, each step confirmed by a distinct read-back and by a
  `PATCH … HTTP 204` in the runtime log, under a human Entra token on the direct-MCP path.
  A dedicated runtime is **not** an isolated blast radius: it shares the VPC/SG, the SAP
  credentials secret, the Entra app and the target SAP system with the read-only sibling.
  Four caveats: the *field* reverted but the PO did not — `LastChangeDateTime` is permanent and
  `CDHDR`/`CDPOS` change documents almost certainly remain; `MCP_SERVER_WRITE_ENABLED` is a master
  switch over the per-op flags, not a peer; create/delete disabled is proven at **tool
  registration** (the container logs `Disabling odata_create tool.` at boot) but never observed as
  an invocation-time refusal; and the driver is a standalone MCP client, so this evidences the
  server's flag behaviour, not the agent's write path.
- **Cedar does not gate writes here — and not because of OBO.** `obo_direct_mcp: true` does mean the
  agent dials the MCP directly, so the SAP statements in `agentcore/policies/sap_agent_policies.cedar`
  cannot match: they are keyed on `-sap-mcp-service-target` / `-sap-mcp-user-target`, and the OBO path
  deploys no Gateway target at all. But the operative reason is broader — the policy engine is not
  created unless the runtime SDK exposes `create_policy_engine` (`lambdas/policy_engine_cr/index.py`),
  and `cedar_enforcement_mode` defaults to `LOG_ONLY`, which logs rather than blocks. Check the
  `PolicyEngineId` and `PolicyEnforcementMode` stack outputs before claiming Cedar gates anything.
  On `entra-obo`, write gating is the external MCP's deploy-time flags plus SAP-side authorization,
  with `_assert_direct_topology_bearer` refusing client-credentials tokens in-path.
- **UNVERIFIED against primary SAP docs:** SOIDC Basis 7.56 SP1+ floor (S1); Feature Pack 2+ for
  the opaque-`sub` custom claim mapping (S4); exact SOIDC field labels (S3); whether a dedicated
  OAuth/OIDC token-endpoint SICF node is required (S6); SAP's JWKS-pull vs cached-keys validation
  model.
- **Verified against the deployed stacks (`erp-obo-v1` with `aws-for-sap-mcp-server-uf` read-only,
  then `aws-for-sap-mcp-server-authverify` write-enabled, 2026-07-30):**
  inbound CFN parameter names (A1: `InboundAuthProvider=EntraId`, `DiscoveryUrl`, `AllowedAudiences`
  = the OUTBOUND app, `AuthFlow`, `OauthScopes`); the `SAP_` infix (A3: the container reads
  `MCP_SERVER_SAP_OAUTH_FLOW` / `MCP_SERVER_SAP_OAUTH_PROVIDER` / `MCP_SERVER_SAP_OAUTH_SCOPES`); the
  callbackUrl format (E6: `.../identities/oauth2/callback/<guid>`, read off
  `get-oauth2-credential-provider`). An end-to-end OBO turn read live SAP OData
  (`API_PURCHASEORDER_PROCESS_SRV`, all HTTP 200, zero 401/403) — the exchanged token is
  SAP-authorized. SAP genuinely enforces on that endpoint (unauthenticated GET and bogus
  bearer both return 401 with `www-authenticate: Basic realm="SAP NetWeaver..."`), so the
  200s required a credential SAP actively accepted, and the external runtime holds no
  fallback user/password/secret — `ON_BEHALF_OF_TOKEN_EXCHANGE` is the only configured flow.
- **Do not cite `SAP.Access` scope as an enforced control:** the external MCP logged
  `Identified 0 accessible services based on OAuth scopes` and then read successfully anyway.
  SAP-side authorization gated access, not the token's scope grant.
- **STILL UNVERIFIED against AWS/deployed stack:** whether `x-audit-*` baggage survives the
  container to SAP — note this is now moot for *identity* purposes, since SAP attributes the call to
  the mapped SU01 user on its own without any custom header; whether the OBO provider persists
  `offline_access` for any unattended refresh.
- **Real-user audit proof (the acceptance test) — CLOSED 2026-07-30.** No AWS-side log records the
  effective SU01 user, by design, so this can only be proven on the SAP system. **Use `STAD`, not
  `SM20`.** The Security Audit Log needs the right audit classes armed *before* the call and does not
  reliably record a successful OIDC-bearer HTTP logon, so `SM20` typically looks empty and proves
  nothing. `STAD` records every HTTP/ICF request with its authenticated ABAP user, retrospectively,
  with nothing to enable first.

  How to read it:

  1. `STAD`, start time = the UTC call time, length a few minutes. Check the app server's display
     offset first: compare a timestamp you generated yourself (e.g. your own `SM21` session) against
     its STAD row. On `SB2` the display is effectively UTC.
  2. **Leave the user field blank.** Filtering to the expected user hides the failure case — a token
     that mapped to a technical user would simply return no rows and look like missing data.
  3. Look for `SAPMHTTP` rows whose program carries the OData path
     (`SAPMHTTP /sap/opu/odata/sap/<SERVICE>`). Dialog rows for `SM21`/`RSYSLOG`/`webgui` are your own
     GUI session, not the agent.
  4. The `User` column is the answer: the effective SU01 user the OData call executed as.

  Proven on `SB2`/`vsapsb2ci_SB2_00`: nine `SAPMHTTP /sap/opu/odata/...` requests 18:46:40–18:47:24
  under SU01 user `DANZACH`, matching the AWS-side count and per-second timing, with service users
  (`AGENTIC`, `DIEGOL`) attributed separately in the same window — so the attribution discriminates
  between real principals rather than reporting a single default user.

## References

- [uf-oidc.md](uf-oidc.md) — interactive USER_FEDERATION (OIDC), the two callback URLs
- [uf-saml.md](uf-saml.md) — email join, same-sub trust not transitive
- [AWS SAP-MCP — Identity and Authentication](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/identity-and-authentication.html)
- [AWS SAP-MCP — Configuration Reference](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/configuration-reference.html)
- [AgentCore — On-Behalf-Of Token Exchange](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/on-behalf-of-token-exchange.html)
- [Microsoft Entra — OAuth 2.0 On-Behalf-Of flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-on-behalf-of-flow)
