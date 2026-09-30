<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# SOIDC / Entra-OBO — Operator Runbook (OBO / ON_BEHALF_OF_TOKEN_EXCHANGE, Direct-Entra → OBO → SAP)

> **Status.** Run end to end in this sample against one SAP S/4HANA 2023 test system
> (SAP_BASIS 7.58): a browser sign-in to Microsoft Entra ID, Entra inbound, a server-side
> `ON_BEHALF_OF_TOKEN_EXCHANGE` exchange in Amazon Bedrock AgentCore Identity, then OData reads
> and one update as the signed-in user's SU01 user, with no second sign-in. Steps that say
> *confirm on your system* vary by SAP release; confirm them on yours, and validate in your own
> account and SAP system before production.

**Before you start.** Programmatic or agent access to SAP can have licensing implications (for
example, SAP Digital Access). Review with your SAP account team.

**Audience:** an SAP admin **+** an Entra admin **+** an AWS operator, executing together.
Each side owns a lane below; the checklist maps every step to the responsible operator.

For the deploy model and env-var contract see
[SAP_MCP_INTEGRATION.md](../SAP_MCP_INTEGRATION.md#env-var-contract-external-sap-mcp-container--reference).
For the **interactive** per-user flows (USER_FEDERATION, 3-legged, browser redirect) see
[uf-oidc.md](uf-oidc.md) (external OIDC IdP), [uf-saml.md](uf-saml.md) (SAP as a SAML 2.0 service
provider) and [uf-oauth2-sap.md](uf-oauth2-sap.md) (SAP as its own OAuth authorization server).
For email federation from Amazon Cognito into SAP Cloud Identity Services (IAS), see
[SAP_MCP_SAME_SUB_FEDERATION.md](../SAP_MCP_SAME_SUB_FEDERATION.md).

## When to pick OBO (vs USER_FEDERATION)

| | **OBO (this doc)** | **USER_FEDERATION (OIDC)** |
|---|---|---|
| User interaction after SPA login | **None** — server-side exchange | Interactive 3-legged sign-in at the external IdP (Entra ID or Okta), which is the authorization server |
| Grant | RFC 7523 JWT-bearer (Entra `jwt-bearer`, `requested_token_use=on_behalf_of`) | Authorization-code (3-legged) |
| Topology | **Direct-to-MCP** (the runtime dials the external MCP server directly, user's Entra JWT is the primary bearer) | Gateway User target |
| SAP trust | **SOIDC** OIDC-provider trust to Entra, direct | **SOIDC** OIDC-provider trust to the same IdP |
| Frontend | `direct-entra`: SPA logs into Entra directly | Cognito/IdP + `/auth/callback` |
| SAP-side redirect/callback | **None** (server-to-server) | Two callback URLs (see below) |

Pick **OBO** when the SPA already signs in to Entra ID and a second SAP sign-in prompt is not
acceptable. Pick USER_FEDERATION when an interactive per-user sign-in is acceptable.

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
owned by [SAP_SYSTEM_CONFIGURATION.md](../SAP_SYSTEM_CONFIGURATION.md) — don't redo the
BASIC/service-account setup here.

### S1. Verify the Basis floor that gates SOIDC

SAP GUI: **System → Status** (component `SAP_BASIS`); SPAM/SAINT for the SP level. SOIDC
(OIDC-provider trust for token-based inbound) is commonly cited as needing **SAP_BASIS 7.56 SP1
or later** — confirm on your system. This sample ran it on SAP_BASIS 7.58. Below the floor OBO is
not available; use a flow that does not need SOIDC — [uf-saml.md](uf-saml.md) or
[uf-oauth2-sap.md](uf-oauth2-sap.md).

### S2. Import the Entra token-endpoint TLS chain into STRUST

SAP GUI transaction **STRUST** → SSL client PSE. SAP fetches Entra's JWKS/discovery over TLS
(`login.microsoftonline.com/<tenant>/v2.0/.well-known/openid-configuration`). Import the **full
chain** (leaf + intermediates + Microsoft's public root CA) into the SSL client PSE, then restart
ICM / the PSE-consuming work processes. A root-only import is a common cause of silent TLS
failures, so import the whole chain. Restarting ICM drops the system's open HTTP connections;
schedule it.

### S3. Create the OIDC provider trust for Entra in SOIDC

SAP GUI transaction **SOIDC**. Register Microsoft Entra as an OIDC provider:
- **Issuer:** `https://login.microsoftonline.com/<tenant>/v2.0`
- **Discovery/well-known:** `https://login.microsoftonline.com/<tenant>/v2.0/.well-known/openid-configuration`
- **Audience/client:** must match the audience of the token the OBO exchange **mints** — i.e. the
  **OUTBOUND** Entra app (`obo-app-client-id`) or the SAP OAuth client, **not** the inbound SPA
  client. Trusting the SPA client id yields an `iss`/`aud`-mismatch 401 (the SAP-side mirror of
  the AWS audience-mismatch 401).

SOIDC field labels (issuer / audience / subject-claim / discovery-URL) vary by release —
confirm in the live transaction.

### S4. Map the Entra `sub` → SU01 business user via a custom claim mapping

SAP GUI transaction **SOIDC** (claim mapping) + **SU01** (target users). Entra emits an
**opaque, app-pairwise `sub`** — it is **not** the email and will **not** match an SU01 user.
**Do not map on `sub`.** Configure a **custom claim mapping** on a stable human claim
(`preferred_username`/UPN or `email`) → the SU01 user whose email/alias matches. This custom
mapping requires **SOIDC Feature Pack 2+** — confirm on your system. (Contrast: Okta's default
authorization server sets `sub` to the Okta username, which is commonly the email address, so a
`sub` mapping can work there without a custom claim.) Ensure each target SU01 user exists with the
matching email/UPN and holds the PFCG OData authorizations for the services the agent calls.

A token that maps is a full SAP logon for that user: its scopes do not confine it to particular
OData services, and the PFCG roles on the mapped user are the authorization boundary.

> **Machine tokens map differently.** An app-only token (M2M via Entra) has no human claim, so
> this mapping cannot bind it. Map on `oid` to the technical user's Alias instead —
> [m2m-oauth2-sap.md S5](./m2m-oauth2-sap.md).

> **Entra's `sub` is not a join key.** Mapping on Entra's opaque `sub` never matches; it is the
> most common failure specific to this flow. Here SAP trusts Entra ID **directly**. For the SAML
> equivalent (SAP as SAML 2.0 service provider) see [uf-saml.md](uf-saml.md) S4; for email
> federation through SAP Cloud Identity Services (IAS) see
> [SAP_MCP_SAME_SUB_FEDERATION.md](../SAP_MCP_SAME_SUB_FEDERATION.md). Same-sub trust is not
> transitive.

### S5. Confirm the Entra token carries the mapping claim (coordinate with the Entra lane)

The SAP-scoped token AgentCore mints must **carry** the stable claim your S4 mapping binds to
(`preferred_username`/`email`/`upn`). That is set **Entra-side** on the OUTBOUND app (Token
configuration / optional claims) — flag it to the Entra admin (step E3). SAP only chooses **which**
incoming claim to map; you cannot conjure a claim SAP never receives.

### S6. Activate the required SICF service nodes

SAP GUI transaction **SICF** (right-click → Activate). Activate the OData runtime tree
`/sap/opu/odata/sap/` (and each service subnode you exposed via scopes), plus the IWFND catalog
service `/sap/opu/odata/iwfnd/catalogservice;v=2` (used by `find_sap_services` / catalog fetch when
`MCP_SERVER_USE_SAP_CATALOG=true`). Whether a dedicated OAuth/OIDC token-endpoint SICF node (e.g.
under `/sap/bc/sec/oauth2`) must **also** be active depends on your release — confirm on your system.

### S7. Smoke-test the SAP trust in isolation (before full E2E)

- **STRUST:** confirm SAP reaches + trusts the Entra JWKS host over TLS (no handshake error in
  `dev_icm` / SMICM).
- **One OData service:** present a real SAP-scoped token (from a manual OBO exchange in the AWS
  lane) to one activated service. A **401** with issuer/`sub`-mismatch → SOIDC issuer/audience or
  the S4 claim mapping is wrong. A **403** → the mapped SU01 user lacks PFCG authorization.
- **Audit proof (the acceptance test):** STAD (transaction STAD), or SM20 if the security audit
  log's logon classes were enabled beforehand, must show the action under the **mapped human SU01
  user**, not a service account. A service-account attribution means the user identity did not
  survive the exchange. See [Proving user attribution in SAP](#proving-user-attribution-in-sap).

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
credentials for the server-side exchange. Store `obo-app-client-id` and this secret in AWS Secrets
Manager as the `{clientId, clientSecret}` secret the **external** AWS for SAP MCP stack's outbound
OAuth provider reads (that stack's client-secret parameter). It is not this sample's
`sap_mcp.external_stack.entra_client_secret_arn`, which is the Gateway's inbound credential to an
`EntraId`-inbound external runtime and plays no part on the OBO direct path. Don't put a
SPA/frontend redirect here.

> **Custom-signing-key apps (including SSO-configured enterprise apps) cannot be OBO middle-tier
> apps** — keep the outbound exchange app a plain app registration.

### E3. Expose the SAP API scope + optional claims on the outbound app

**Expose an API** → set an Application ID URI (e.g. `api://obo-app-client-id`) and add a delegated
scope (e.g. `SAP.Access` / `user_impersonation`). This scope is what the OBO exchange requests and
what SAP's SOIDC trust validates. **Token version trap:** for v2.0 access tokens set
`requestedAccessTokenVersion: 2` (Microsoft Graph app manifest format) or
`accessTokenAcceptedVersion: 2` (older Azure AD Graph format) in the manifest **and** expose an API scope included in the SPA's
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
tenant-wide and OBO runs with no second prompt. Alternatively wire combined consent via
the outbound app manifest (`knownClientApplications` / `preAuthorizedApplications`). **Do not
combine `.default` with other dynamic delegated scopes in one authorize request** → `AADSTS70011`.

### E6. Register the AgentCore callback URL on the OUTBOUND app — **after deploy**

**Ordering.** The callback URL is **unique per credential provider** and unknown until
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
**before** the OBO exchange. Inbound CloudFormation parameter names:

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
- `MCP_SERVER_SAP_OAUTH_SCOPES=api://<outbound-app-id>/<scope>` — the Entra scope the OBO exchange
  requests, the same value as `OauthScopes` in A1. It is not a list of SAP service names: which
  OData services the mapped user reaches is set by that user's PFCG roles and the SICF nodes
  activated in S6, and a service outside them returns **403**.
- Keep `MCP_SERVER_WRITE_ENABLED=false` until you have reviewed the SAP API Policy (see the
  [README](../../../README.md)). This sample has no per-write approval step. The write flags are CloudFormation parameters on the external stack,
  so changing them is a stack update; disabled operations do not appear in `tools/list`. This
  sample's `cdk/lib/sap-mcp-stack.ts` never creates a runtime, so its deploy cannot change them.

### A3. Point the runtime at the OBO provider by name

`MCP_SERVER_SAP_OAUTH_PROVIDER=<obo-provider-name>`. The runtime validates this provider exists in
AgentCore Identity at startup or fails to start.

> **Env-var name:** use the `SAP_`-infixed form (`MCP_SERVER_SAP_OAUTH_PROVIDER`) that the server
> reads — see the AWS [configuration reference](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/configuration-reference.html).

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
| SPA login redirect | This sample's frontend (inbound app) | INBOUND Entra app (SPA platform) | SPA Auth-Code + PKCE (E1) |
| AgentCore provider `callbackUrl` (`.../identities/oauth2/callback/<guid>`) | AWS / AgentCore Identity | **OUTBOUND** Entra app (Web platform) | The OBO credential provider (E6/A4) |
| `MCP_SERVER_APP_CALLBACK_URL` (`/auth/callback`) | This sample's frontend | The external stack's configuration | **USER_FEDERATION only, not OBO** |

**OBO is server-side and non-interactive:** `MCP_SERVER_APP_CALLBACK_URL` is required only for
USER_FEDERATION per the config-reference — the sibling runbook [uf-oidc.md](uf-oidc.md) covers that
"two callback URLs" model. Don't go hunting for a SAP redirect URI OBO never uses; the
**only** redirect that matters for OBO is the AgentCore provider callback on the OUTBOUND app.

---

## Checklist

| Side | Step | Area |
|---|---|---|
| **SAP** | S1 SOIDC Basis floor (confirm on your system) | SOIDC prerequisite |
| **SAP** | S2 STRUST full Entra TLS chain + ICM restart | SSL certs (Entra) / STRUST |
| **SAP** | S3 SOIDC OIDC provider for Entra (issuer/audience = **outbound** app) | OIDC provider (Entra) |
| **SAP** | S4 `sub`→SU01 custom claim mapping (Feature Pack 2+) | sub-claim mapping |
| **SAP** | S5 confirm the Entra token carries the mapping claim | token claims |
| **SAP** | S6 SICF: `/sap/opu/odata/sap/` + `iwfnd/catalogservice;v=2` | SICF |
| **SAP** | S7 isolation smoke-test + real-user audit proof | acceptance |
| **Entra** | E1 inbound SPA app-reg | App registration (inbound) |
| **Entra** | E2 outbound OIDC app-reg + secret | App registration (outbound OIDC) |
| **Entra** | E3–E5 expose scope, API perms, admin consent | App registration (OBO + API perms) |
| **Entra** | E6 AgentCore callback on outbound app (after deploy) | Redirect URI (AgentCore callback) |
| **AWS** | A1 external stack Entra inbound + discovery | External IdP discovery (Entra) |
| **AWS** | A2 outbound flow, SAP base URL, Entra scope, writes disabled | External stack runtime env |
| **AWS** | A3 `MCP_SERVER_SAP_OAUTH_PROVIDER` names the OBO provider | External stack runtime env |
| **AWS** | A4 AgentCore OBO provider (RFC 7523) | AgentCore — OBO (Entra) / OIDC provider (Entra) |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| **Inbound 401** at the runtime | No `Authorization` header, or a *claim* check failed: wrong `iss` (token from another IdP/tenant), or expired | Send an **access token** for the right tenant, unexpired; align the discovery URL (A1) |
| **Inbound 403** at the runtime | Header present but unparseable (empty value, missing `Bearer ` prefix, `alg=none`), **or** `iss`+`aud` matched and signature verification then failed. Also a raw id_token / Graph-scoped token whose `aud` is not the outbound app | SPA must acquire an access token scoped to the outbound app's exposed scope (E3/E4); align allowed audiences (A1) |
| **Exchange fails** | Entra configured as TOKEN_EXCHANGE/`subject_token` | Use `JWT_AUTHORIZATION_GRANT` (RFC 7523) — A4 |
| **`AADSTS70011`** | `.default` combined with dynamic delegated scopes in one authorize request | Use `.default` alone, or split requests — E5 |
| **SAP 401**, issuer/`sub` mismatch | SOIDC issuer/audience trusts the **inbound SPA** client, or maps on Entra's opaque `sub` | Trust the **outbound** app audience (S3); map on `preferred_username`/`email` (S4) |
| **SAP 403** | Mapped SU01 user lacks PFCG authorization, or service not SICF-activated | Grant PFCG on the service; activate SICF node (S4/S6) |
| **`interaction_required` (401 + claims challenge)** | Conditional Access / MFA step-up on the downstream resource | Client must resolve the claims challenge; happy path needs no second login |
| **App-only / autonomous token** rejected for OBO | Entra OBO "only works for user principals" | Autonomous/poller path cannot use OBO — keep it on the service-account flow |
| **Deploy/validation fails** on OBO/external mismatch | OBO selected but the external stack's inbound is not Entra (a machine/M2M token would be 401'd by the Entra inbound authorizer, and vice-versa) | Redeploy the external stack with Entra inbound, or pick a non-OBO profile |

## Results and limits

- **Run end to end in this sample** against one SAP S/4HANA 2023 test system (SAP_BASIS 7.58):
  OData reads and one update as the signed-in user. Create, delete and function-import have not
  been run end to end in this sample.
- **Write flags are deploy-time CloudFormation parameters** on the external stack, not runtime
  toggles. Enabling writes means a stack update or a second stack, and a second runtime is not an
  isolated blast radius: it shares the VPC, security group, SAP secret, Entra ID app and SAP system.
- **Cedar does not gate writes on this path.** The OBO direct path deploys no Gateway target, so
  the Gateway's Cedar policies never see these calls. Writes are gated by the external stack's
  write flags and the mapped user's PFCG roles.
- **A token's `scp` does not limit which OData services it reaches;** the mapped user's PFCG
  roles do.
- **Confirm on your system:** the SOIDC Basis floor (S1), Feature Pack 2+ for the custom claim
  mapping (S4), SOIDC field labels (S3), and whether a dedicated token-endpoint SICF node is
  required (S6).

### Proving user attribution in SAP

No AWS-side log records the effective SU01 user, so prove it on the SAP system with STAD
(transaction STAD), which records each HTTP request with its authenticated ABAP user.

1. Open STAD with the start time set to the call time (check the app server's display time zone
   against a request you made yourself) and a window of a few minutes.
2. Leave the user field blank. Filtering on the expected user hides the failure case, where a
   token mapped to a technical user returns no rows.
3. Look for `SAPMHTTP` rows whose program carries the OData path
   (`SAPMHTTP /sap/opu/odata/sap/<SERVICE>`).
4. The `User` column is the SU01 user the OData call ran as.

## References

- [uf-oidc.md](uf-oidc.md) — interactive USER_FEDERATION (OIDC), the two callback URLs
- [uf-saml.md](uf-saml.md) — interactive USER_FEDERATION with SAP as a SAML 2.0 service provider
- [SAP_MCP_SAME_SUB_FEDERATION.md](../SAP_MCP_SAME_SUB_FEDERATION.md) — email federation through SAP Cloud Identity Services (IAS)
- [AWS SAP-MCP — Identity and Authentication](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/identity-and-authentication.html)
- [AWS SAP-MCP — Configuration Reference](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/configuration-reference.html)
- [AgentCore — On-Behalf-Of Token Exchange](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/on-behalf-of-token-exchange.html)
- [Microsoft Entra — OAuth 2.0 On-Behalf-Of flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-on-behalf-of-flow)
