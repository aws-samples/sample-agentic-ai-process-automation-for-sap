<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# USER_FEDERATION (SAML) — Operator Runbook (User Federation, SAP-as-SAML-SP; Entra or Okta)

> **Status.** The USER_FEDERATION outbound is `status: stub` in `auth-profiles.yaml`
> (`user-federation: { ..., status: stub, blocked_by: upstream }`). The wiring exists in this
> repository (this flow uses the same User Gateway target as the other USER_FEDERATION variants),
> but this sample has not yet run it end to end, and the deploy prints a notice saying so. AWS
> documents this pattern in the scenario table as *"SAP as Authorization Server with OAuth2 and
> SAML IdP redirect | User Federation | OAuth2 + SAML | Entra ID or other SAML IdP | SAP OAuth2
> client + SAML trusted provider"*
> ([identity-and-authentication](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/identity-and-authentication.html)).
> SAP-side details that vary by release say *confirm on your system*.

**Before you start.** Programmatic or agent access to SAP can have licensing implications (for
example, SAP Digital Access). Review with your SAP account team.

**How the flow works.** Amazon Bedrock AgentCore does not send, receive or validate a SAML
assertion. AgentCore Identity runs an OAuth 2.0 **authorization-code** flow against **SAP's own
OAuth authorization server** (SAP's authorize and token endpoints). SAP, acting as a **SAML 2.0
service provider** (transaction SAML2), redirects the person's browser to the external SAML
identity provider (Microsoft Entra ID or Okta). The SAML assertion passes only between the browser,
the IdP and SAP. The AWS row label "OAuth2 + SAML" describes this combination.

**Audience:** an SAP admin **+** an Entra admin (Entra variant) or Okta admin (Okta variant) **+** an
AWS operator, working together. Each side owns a lane below; the checklist maps every step to its
operator.

This runbook covers only what differs from the shared USER_FEDERATION mechanics in
[SAP_MCP_USER_FEDERATION.md](../SAP_MCP_USER_FEDERATION.md) — the User Gateway target, the two
callback URLs, SAP's authorize and token endpoints — so read that first. It adds the
SAP-as-SAML-service-provider trust (SAML2 trust plus the SOAUTH2 authorization-code client) and the
IdP SAML app. For the deploy model and env-var contract see
[SAP_MCP_INTEGRATION.md](../SAP_MCP_INTEGRATION.md#env-var-contract-external-sap-mcp-container--reference).
For the sibling flows: OBO / ON_BEHALF_OF_TOKEN_EXCHANGE (server-side, direct-to-MCP, RFC 7523) is
[soidc-entra-obo.md](./soidc-entra-obo.md); M2M (machine identity) is
[m2m-oauth2-sap.md](./m2m-oauth2-sap.md); the email-join OIDC federation variant is
[SAP_MCP_SAME_SUB_FEDERATION.md](../SAP_MCP_SAME_SUB_FEDERATION.md). STRUST mechanics are in
[soidc-entra-obo.md S2](./soidc-entra-obo.md#s2-import-the-entra-token-endpoint-tls-chain-into-strust).

## When to pick UF-SAML (vs the other flows)

| | **USER_FEDERATION (SAML), this doc** | **USER_FEDERATION (OIDC)** | **OBO / ON_BEHALF_OF_TOKEN_EXCHANGE** |
|---|---|---|---|
| Human interaction | Interactive 3-legged login; SAP redirects to the SAML IdP | Interactive 3-legged; SAP trusts the IdP via OIDC | **None** — server-side exchange |
| What SAP trusts | **SAML2** trusted provider (Entra/Okta as SAML IdP) | **SOIDC** OIDC-provider trust | **SOIDC** trust to Entra, direct |
| Grant AgentCore drives | OAuth2 authorization-code (to SAP's OAuth server) | OAuth2 authorization-code (to the external IdP, which is the authorization server) | RFC 7523 jwt-bearer |
| Topology in this repo | **Gateway User target** | Gateway User target | Direct-to-MCP (OBO-only) |
| SAML assertion seen by AgentCore | **Never** — browser↔IdP↔SAP only | n/a | n/a |

Pick **USER_FEDERATION (SAML)** when SAP already trusts an external **SAML** IdP (Entra/Okta SAML)
and you want the interactive per-user path. If SAP trusts the IdP by **OIDC**, use USER_FEDERATION
(OIDC). If no second login is acceptable and SAP trusts Entra directly, use OBO /
ON_BEHALF_OF_TOKEN_EXCHANGE. All USER_FEDERATION variants use the **same** User Gateway target —
see A3.

## End-to-end flow (short)

```
Agent ─▶ AgentCore Gateway (User target, credentialProviderType:OAUTH)
      ─▶ external AWS-for-SAP MCP Runtime (inbound: token from the EXTERNAL stack's pool)
      ─▶ AgentCore Identity: 3-legged OAuth2 authorization-code to SAP's OWN OAuth server;
         auth URL surfaces back through the Gateway as tool-result JSON
      ─▶ human's browser opens SAP's authorize endpoint
      ─▶ SAP (SAML 2.0 SP, transaction SAML2) redirects the browser to Entra/Okta (SAML IdP)
      ─▶ human logs in; IdP POSTs a SAML assertion to SAP's assertion consumer service; SAP
         validates the assertion + maps NameID (email) → SU01 user, then completes ITS OAuth flow
      ─▶ AgentCore exchanges the code at SAP's token endpoint for a per-user SAP OAuth token
      ─▶ MCP server calls OData with that token; SAP enforces the mapped human's authorizations
```

AgentCore uses only OAuth 2.0 (authorize and token endpoints, client ID and secret, scopes) and
stores the resulting SAP token in its token vault. It never registers a SAML IdP. The SAML leg is
entirely on the SAP side. RFC 7522 SAML-bearer — an assertion posted to SAP's token endpoint — is a
different, non-interactive grant and is not part of this flow.

---

## SAP-side steps (SAP admin)

This lane covers only the SAML service provider and SOAUTH2 trust. Base OData connectivity and the
SU01 user are in [SAP_SYSTEM_CONFIGURATION.md](../SAP_SYSTEM_CONFIGURATION.md#1-service-account-setup)
and [SAP_SETUP.md](../SAP_SETUP.md); do not repeat that setup here.

### S1. Verify the Basis floor for the SAML2-trusted-provider + SOAUTH2 combination

SAP GUI: **System → Status** (component `SAP_BASIS`); SPAM/SAINT for the SP level. SAML 2.0
Service-Provider support is long-standing in NetWeaver / ABAP Platform, but the release that
supports **linking a SAML2 trusted provider to a SOAUTH2 OAuth authorization-code client** (so the
OAuth authorize endpoint delegates human logon to the SAML IdP) varies — confirm on your system
before relying on this flow.

### S2. Configure SAP as a SAML 2.0 Service Provider trusting the external IdP

SAP GUI transaction **SAML2**. Create/confirm SAP's **Local Provider** (SAP as SP), then add
Entra / Okta as a **Trusted Provider** by importing the IdP's SAML metadata (IdP
EntityID/Issuer, SSO endpoints, X.509 signing cert). This is the AWS row's *"SAML trusted provider"*.
Exact SAML2 screen labels (Local Provider / Trusted Provider / NameID format / assertion consumer
service URL) vary by release — confirm in the live transaction. Corroboration that SAP-as-SP is
set up via SAML2 (*"Create SAML 2.0 Local Provider"*):
[AWS-for-SAP SSO-with-Fiori blog](https://aws.amazon.com/blogs/awsforsap/aws-single-sign-on-integration-with-sap-fiori-in-s-4hana/).

### S3. Import the IdP's SAML signing + endpoint TLS chain into STRUST

SAP GUI transaction **STRUST**. SAP validates the assertion signature and fetches IdP endpoints over
TLS, so import the **full** IdP SAML assertion-signing chain **and** endpoint TLS chain (leaf +
intermediates + public root CA), then restart ICM. Restarting ICM drops the system's open HTTP
connections, so schedule it. Importing only the root CA is a common cause of silent failure. The
STRUST steps are the same as
[soidc-entra-obo.md S2](./soidc-entra-obo.md#s2-import-the-entra-token-endpoint-tls-chain-into-strust).

### S4. Map the SAML NameID (email) → SU01 business user

SAP GUI transaction **SAML2** (assertion → user mapping) + **SU01** (target users). SAP maps the
assertion **NameID/attribute** to an SU01 user. **Join on email**, not on an opaque identifier:
- **Okta** commonly emits **email** as the NameID subject (easy join).
- **Entra** must be configured to send a stable human attribute (**email/UPN**) as NameID. Do not
  join on Entra's default persistent/pairwise identifier: it is opaque and will not match an SU01
  user. This is the SAML counterpart of the OIDC opaque-`sub` issue in
  [soidc-entra-obo.md S4](./soidc-entra-obo.md#s4-map-the-entra-sub--su01-business-user-via-a-custom-claim-mapping).

Each target SU01 user must exist with the matching email/UPN and hold the PFCG OData authorizations
for the services the agent calls. The email join is the same principle as
[SAP_MCP_SAME_SUB_FEDERATION.md](../SAP_MCP_SAME_SUB_FEDERATION.md), but through SAP's **own** SAML2
service provider, **not** SAP Cloud Identity Services (trust is not transitive). Mapping labels vary
by release — confirm on your system.

### S5. Create the SOAUTH2 auth-code OAuth client, linked to the SAML2 trusted provider

SAP GUI transaction **SOAUTH2**, per SAP's
[OAuth client configuration](https://help.sap.com/docs/ABAP_PLATFORM_NEW/fd0fc52fd22b45f29d274a7f8236e768/cdb122d5b0784c77bf1bcce17f730e74.html).
Register an **authorization-code (3-legged)** OAuth 2.0 client so SAP acts as its own authorization
server for the interactive flow:
- **The client is an SU01 user.** The OAuth client ID is an SU01 user of type **System**, and its
  password is the client secret. Record both for the external stack's AWS Secrets Manager secret
  (A1). Rotate the secret as you would any technical-user password, and update the secret when you
  do.
- **Enable OAuth per service first.** Each OData service must have OAuth enabled in transaction
  **/IWFND/MAINT_SERVICE** before its scope ID (`<SERVICE>_0001`) exists; the client's scopes are
  those IDs — see [m2m-oauth2-sap.md S3](./m2m-oauth2-sap.md).
- The client's **authorize / token** endpoints are SAP's own OAuth authorize and token endpoints,
  configured on the external stack (A1).
- Register the **AgentCore callback URL** (from A4, after deploy) as an allowed **redirect URI** on
  **this SOAUTH2 client** — **not** on the SAML IdP app.
- Its logon must **delegate to the SAML2 trusted provider** (S2), so an unauthenticated request to
  the authorize endpoint triggers the SAML redirect to Entra or Okta.

Linking the SOAUTH2 client to the SAML2 trusted provider is the step the rest of the flow depends
on. AWS documents the pairing in the row *"SAP OAuth2 client + SAML trusted provider"*, and SAP
describes it in *Configuring a Trusted Identity Provider for OAuth 2.0* in the SAP Help Portal.
Confirm the `authorize → SAML redirect → token` sequence on your system. A SOAUTH2
**client-credentials** client is the M2M path instead — no person, no SAML — see
[m2m-oauth2-sap.md S2](./m2m-oauth2-sap.md).

### S6. Activate the required SICF service nodes

SAP GUI transaction **SICF** (right-click → Activate). Activate the OData runtime tree
`/sap/opu/odata/sap/` (and each service subnode exposed via scopes) plus the IWFND catalog service
`/sap/opu/odata/iwfnd/catalogservice;v=2` (same node set as the siblings — cross-link
[m2m-oauth2-sap.md S4](./m2m-oauth2-sap.md)). **Additionally** the SAML2 SP service
`/sap/public/bc/sec/saml2` + its assertion-consumer node, and any OAuth authorize/token SICF node,
must be active. The exact SAML2/OAuth node paths vary by release — confirm on your system.

### S7. Smoke-test the SAP trust in isolation (before the full flow)

- **STRUST/SAML2:** confirm SAP reaches + trusts the IdP SAML signing cert and endpoints (no
  handshake/signature error in `dev_icm` / SMICM); SAML2 shows the trusted provider active.
- **Interactive login:** hit SAP's SOAUTH2 authorize endpoint in a browser → expect a redirect to
  Entra/Okta → after IdP login, a SAML assertion POSTs back to SAP's ACS and SAP issues an
  authorization code. A failure to redirect → the SOAUTH2↔SAML2 linkage (S5) is wrong. A SAML
  signature error → STRUST chain (S3). A "no matching user" → the NameID→SU01 mapping (S4).
- **One OData service** with the resulting SAP OAuth token: **401** → SOAUTH2 client / token
  endpoint wrong. **403** → the mapped SU01 user lacks PFCG authorization.
- **Audit proof:** after one OData call, STAD (transaction STAD), or SM20 if the security audit
  log's logon classes were enabled beforehand, must show the action under the **mapped person's SU01
  user**, not a service account. A service-account entry means the person's identity was not carried
  through — see
  [soidc-entra-obo.md](./soidc-entra-obo.md#proving-user-attribution-in-sap). This flow has not yet
  been run end to end in this sample.

---

## IdP-side steps — register a SAML app whose **Service Provider is SAP** (not AgentCore)

Create a SAML 2.0 app whose SP values are **SAP's** (from S2), emitting a stable human NameID
(email). **No AgentCore callback is registered at the IdP** — the only "reply URL" the IdP app
carries is **SAP's assertion consumer service (ACS)**. Exchange metadata both directions: import the
IdP metadata into SAP (S2) **and** put SAP's SP metadata (entityID + ACS) into the IdP app.

### E-Entra. Entra SAML enterprise application

Entra admin center → **Enterprise applications** → New application → (create) → Manage → **Single
sign-on → SAML**
([Entra: set up SSO](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/add-application-portal-setup-sso)):

1. **Basic SAML Configuration** → Edit: **Identifier (Entity ID)** = SAP's SP entityID;
   **Reply URL (Assertion Consumer Service URL)** = SAP's ACS. You can upload SAP's SP metadata XML
   instead of typing these values.
2. **Attributes & Claims** → Edit: set **Unique User Identifier (Name ID)** = `user.mail` with
   NameID format `urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress`
   ([Entra SAML protocol](https://learn.microsoft.com/en-us/entra/identity-platform/single-sign-on-saml-protocol)).
   Do not leave NameID at Entra's default persistent/pairwise identifier (see S4).
3. **SAML Certificates**: download **Certificate (Raw)** (the signing cert) and copy the
   **App Federation Metadata Url**; the **Microsoft Entra Identifier / Login URL** are the IdP
   EntityID/Issuer + SSO URL. Give SAP the **metadata URL** (preferred — SAML2 ingests EntityID +
   SSO URL + signing cert together) or the raw cert (S2/S3).
4. Assign the users who may sign in.

### E-Okta. Okta SAML app

Okta admin → **Applications → Create App Integration → SAML 2.0 → Configure SAML**
([Okta SAML field reference](https://help.okta.com/en-us/content/topics/apps/aiw-saml-reference.htm)):

1. **Single sign-on URL** = SAP's ACS (this **is** the *"Redirect URI (SAP SAML)"* value — it
   is SAP's ACS, **not** the AgentCore callback); **Audience URI (SP Entity ID)** = SAP's SP
   entityID; **Default RelayState** blank (SP-initiated).
2. **Name ID format** = `EmailAddress` and set **Application username** so the NameID = email (Okta
   natively puts email in the subject, which makes the Okta variant simpler than Entra).
3. **Attribute Statements** — only for extra claims beyond the NameID subject.
4. After the wizard, the **Sign On** tab exposes Okta's IdP metadata: hand SAP the **Identity
   Provider Issuer** (IdP EntityID), **Single Sign-On URL**, and **X.509 signing certificate** (or
   the metadata URL for SAML2 to ingest). The exact Sign-On-tab label for retrieving metadata/cert
   varies with the Okta admin console version — confirm in yours.

> **Okta.** AWS docs say *"Entra ID or other SAML IdP"*; Okta is a standard SAML 2.0 IdP, so the
> mechanism is identical to Entra — only the IdP differs. It has not yet been run end to end in
> this sample.

---

## AWS / AgentCore-side steps (AWS operator)

> The external AWS for SAP MCP stack, its inbound pool, and its OAuth provider are owned
> externally — not deployed here. This sample's deployment mints the **Gateway User target + a
> Gateway OAuth2 credential provider** (the UF path is the Gateway path, never direct-to-MCP). From
> AgentCore's side this is a plain OAuth2 authorization-code provider pointed at SAP's OAuth server;
> AgentCore is not involved in the SAML exchange.

### A1. Set the USER_FEDERATION flow + SAP SOAUTH2 endpoints on the external stack — **all**

External stack env vars (AWS CloudFormation parameters; editable in the Amazon Bedrock AgentCore
console → Runtime → Update Hosting → Advanced Configurations). These are set on the external stack,
not by this sample's deploy:
- `MCP_SERVER_SAP_OAUTH_FLOW=USER_FEDERATION`
- `MCP_SERVER_SAP_BASE_URL=https://<sap-host>/sap/opu/odata/sap/`
- `MCP_SERVER_SAP_OAUTH_SCOPES=<scope-id(s)>`, for example `API_SALES_ORDER_SRV_0001` — SAP
  service scope IDs, not OAuth scope URIs; a wrong or foreign scope returns **HTTP 403** (each
  service must be SICF-activated, S6, and PFCG-authorized, S4)
- `MCP_SERVER_SAP_OAUTH_PROVIDER=<provider-name>` — the A2 provider (note the `SAP_` infix)
- `MCP_SERVER_APP_CALLBACK_URL` = the frontend `/auth/callback` route (must end in `/callback` or
  `/oauthcallback`)
- Secret `{clientId, clientSecret}` = the **SOAUTH2 authorization-code client** from S5
- Keep `MCP_SERVER_WRITE_ENABLED=false` until you have reviewed the SAP API Policy (see the
  [README](../../../README.md)). This sample has no per-write approval step. On
  this Gateway path, the Cedar policies permit `odata_create`, `odata_update` and
  `odata_function_import` only for the finance, procurement and admin role tags and forbid
  `odata_delete`; the default `cedar_enforcement_mode: LOG_ONLY` only logs those decisions, so set
  `ENFORCE` for them to block.

### A2. Create the AgentCore Identity outbound OAuth2 provider (SAP-facing) — **all**

`aws bedrock-agentcore-control create-oauth2-credential-provider` (or Console → custom provider),
`clientId`/`clientSecret` = the S5 SOAUTH2 client. Use
`oauthDiscovery.authorizationServerMetadata` (explicit `authorizationEndpoint` + `tokenEndpoint` +
`issuer`), not `discoveryUrl`: a SAP OAuth URL is not a `.well-known` document and fails
AgentCore's `discoveryUrl` regex — same as the M2M SAP-facing provider
([m2m-oauth2-sap.md A2](./m2m-oauth2-sap.md); see also
[SAP_MCP_INTEGRATION.md troubleshooting](../SAP_MCP_INTEGRATION.md#troubleshooting)). From
AgentCore's side this is an ordinary **OAuth2 authorization-code** provider; the SAML redirect
happens later, inside SAP.

### A3. The Gateway User target — Gateway path, not direct-to-MCP — **all**

For a User outbound profile, the deploy mints a **"User" Gateway target**
(`credentialProviderType: "OAUTH"`) pointing at the external runtime; interactive calls keep flowing
through the Gateway (Cedar + `x-audit-*` interception intact). The interactive auth URL surfaces
through the Gateway as tool-result JSON. It is not direct-to-MCP (that is OBO-only).

**USER_FEDERATION (OIDC), USER_FEDERATION (SAML), and USER_FEDERATION with SAP as its own OAuth
authorization server all use the SAME User Gateway target** — the only difference is what SAP
trusts (SOIDC vs SAML2 vs SAP-native) and where the person authenticates, which AgentCore does
not see.
There is no SAML-specific variant on the AWS side. The SAP OAuth knobs
(`MCP_SERVER_SAP_OAUTH_FLOW` / scopes / `MCP_SERVER_APP_CALLBACK_URL`) live on the **external** stack.

### A4. The Gateway OAuth2 (inbound) provider must point at the external stack's pool — **all**

The Gateway OAuth2 provider **must point at the external stack's inbound pool**, not the local one,
or the runtime returns **401** (`iss` mismatch) — see
[SAP_MCP_USER_FEDERATION.md troubleshooting](../SAP_MCP_USER_FEDERATION.md#troubleshooting).
After deploy, AgentCore Identity's outbound provider returns a **callback URL** — register that exact
URL as a redirect URI on **SAP's SOAUTH2 client** (S5), **not** on the SAML IdP app.

---

## The callback / redirect URLs (three, do not conflate)

The first two are covered in
[the two callback URLs](../SAP_MCP_USER_FEDERATION.md#the-two-callback-urls-do-not-conflate-them).
UF-SAML adds a **third**, SAP-owned, IdP-registered SAML endpoint:

| URL | Owner | Registered where | Used by |
|---|---|---|---|
| AgentCore provider callback | AWS / AgentCore Identity | **SAP's SOAUTH2 OAuth client** (redirect-URI allowlist) — not the SAML IdP | Completes the OAuth code exchange (A4/S5) |
| `MCP_SERVER_APP_CALLBACK_URL` (`/auth/callback`) | Frontend | App config | Signals completion to the app |
| **SAP SAML ACS** (assertion consumer service) | **SAP** (as SAML SP) | **The SAML IdP app** (Entra Reply URL / Okta Single sign-on URL) | The SAML leg (browser↔IdP↔SAP) — AgentCore never sees it |

The AgentCore callback registers on SAP's **SOAUTH2** client; the IdP app's only reply URL is
SAP's **ACS**. Registering either one in the other's place breaks the flow without a clear error.

---

## Checklist (mapped to the AWS outbound-auth table rows)

| Side | Step | Outbound-auth row |
|---|---|---|
| **SAP** | S1 Basis floor for SAML2↔SOAUTH2 combo | UF-SAML prerequisite |
| **SAP** | S2 SAML2 trusted provider (Entra) | SAML trust (Entra) SAML2 |
| **SAP** | S2 SAML2 trusted provider (Okta) | SAML trust (Okta) SAML2 |
| **SAP** | S3 STRUST full IdP SAML+TLS chain + ICM restart | SSL certs STRUST (Entra, Okta) |
| **SAP** | S4 NameID (email)→SU01 mapping | user mapping |
| **SAP** | S5 SOAUTH2 auth-code client linked to SAML2 | OAuth2 client (auth code) SOAUTH2 |
| **SAP** | S6 SICF `/sap/opu/odata/sap/` + `iwfnd/catalogservice;v=2` + SAML2 nodes | SICF |
| **SAP** | S7 isolation smoke-test + real-user audit proof | acceptance |
| **Entra** | E-Entra SAML enterprise app (SP=SAP, NameID=email) | SAML enterprise app (Entra) |
| **Okta** | E-Okta SAML app (SSO URL=SAP ACS, Audience=SAP entityID) | SAML app (outbound) (Okta) |
| **Okta** | E-Okta Single sign-on URL = SAP ACS | Redirect URI (SAP SAML) (Okta) |
| **Okta** | E-Okta attribute statements | Attribute statements (Okta) |
| **AWS** | A2 AgentCore outbound OAuth2 provider (`authorizationServerMetadata`) | SAML+OAuth (Entra) |
| **AWS** | A2 AgentCore outbound OAuth2 provider (Okta variant) | SAML+OAuth (Okta) |
| **AWS** | A3 User Gateway target + app callback URL | Client callback URL (Entra, Okta) |
| **AWS** | A3–A4 User target + Gateway OAuth2 provider (inbound pool) | AgentCore-side wiring |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| **401 from the external runtime** (`iss mismatch`) | Gateway OAuth2 (inbound) provider points at the local pool, not the external stack's | Point it at the external stack's inbound pool — A4 |
| **No interactive auth URL surfaces** | Agent not reading the tool-result JSON | Relay the auth URL from tool-result JSON to the frontend — A3 |
| **Auth URL opens but SAP does not redirect to the IdP** | SOAUTH2 client not linked to the SAML2 trusted provider (S5 gap) | Wire SOAUTH2 logon to delegate to the SAML2 provider — S5 |
| **IdP rejects the redirect** | AgentCore callback registered on the **SAML IdP** instead of SAP's **SOAUTH2** client | Register the AgentCore callback on the SOAUTH2 client; the IdP app carries only SAP's ACS — S5/A4 |
| **SAML signature / trust error at SAP** | IdP signing chain not fully imported (root-only) | Import the full IdP SAML signing chain into STRUST — S3 |
| **SAP: "no matching user" after SAML login** | NameID is Entra's opaque/pairwise id, or SU01 email mismatch | Set Entra NameID = `user.mail` (emailAddress); ensure SU01 email matches — S4/E-Entra |
| **SAP 403** on OData | Wrong scope (not a service scope ID), or mapped SU01 user lacks PFCG | Set scopes to the services' scope IDs; grant PFCG — A1/S4 |
| **`discoveryUrl` regex rejection** creating the SAP provider | SAP OAuth URL passed where a `.well-known` URL is expected | Use `authorizationServerMetadata` (auth+token+issuer) — A2 |

## Limits

- **Interactive consent per user.** Not for unattended runs.
- **Confirm on your system:** the Basis release for linking a SAML2 trusted provider to a SOAUTH2
  client (S1); the SAML2 screen labels — Local Provider / Trusted Provider / NameID format / ACS URL
  (S2); the SAML2→SU01 mapping labels (S4); the SOAUTH2↔SAML2 linkage and its
  `authorize → SAML redirect → token` sequence (S5); and which SICF nodes the SAML2 service
  provider and OAuth endpoints require, including the ACS path under `/sap/public/bc/sec/saml2`
  (S6).
- **Confirm in your Okta console:** the Sign On tab label for retrieving IdP metadata and the X.509
  signing certificate after the wizard (E-Okta step 4).

## References

- [SAP_MCP_USER_FEDERATION.md](../SAP_MCP_USER_FEDERATION.md) — User target, the two callback URLs, SAP's authorize/token endpoints (read first)
- [SAP_MCP_INTEGRATION.md](../SAP_MCP_INTEGRATION.md) — deploy model, env-var contract, `discoveryUrl` vs `authorizationServerMetadata`
- [soidc-entra-obo.md](./soidc-entra-obo.md) — sibling OBO / ON_BEHALF_OF_TOKEN_EXCHANGE; STRUST and subject mapping (S2/S4)
- [m2m-oauth2-sap.md](./m2m-oauth2-sap.md) — sibling M2M; SOAUTH2 client-credentials contrast + `authorizationServerMetadata`
- [SAP_MCP_SAME_SUB_FEDERATION.md](../SAP_MCP_SAME_SUB_FEDERATION.md) — email-join federation (OIDC variant)
- [SAP_SYSTEM_CONFIGURATION.md](../SAP_SYSTEM_CONFIGURATION.md) — SU01 user, PFCG and SICF base setup
- [AWS SAP-MCP — Identity and Authentication](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/identity-and-authentication.html) — outbound-auth table row *"OAuth2 + SAML | SAP OAuth2 client + SAML trusted provider"*; UF *"either OAuth2, OIDC, or SAML2 depending on your choice of IdP"*
- [AWS SAP-MCP — Getting Started](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/getting-started.html) — Pattern 2: SAP as Authorization Server with OAuth2 + SAML IdP; AgentCore callback registered on SAP's OAuth2 client
- [AgentCore — Supported identity providers](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/identity-idps.html) — OAuth2/OIDC provider list (no SAML entry)
- [Entra: set up SAML SSO](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/add-application-portal-setup-sso) / [Entra SAML protocol](https://learn.microsoft.com/en-us/entra/identity-platform/single-sign-on-saml-protocol)
- [Okta SAML app field reference](https://help.okta.com/en-us/content/topics/apps/aiw-saml-reference.htm)
- [AWS-for-SAP — SSO with Fiori in S/4HANA](https://aws.amazon.com/blogs/awsforsap/aws-single-sign-on-integration-with-sap-fiori-in-s-4hana/) — SAP-as-SP via SAML2 local provider
