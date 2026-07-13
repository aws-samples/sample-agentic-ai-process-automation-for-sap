<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# USER_FEDERATION (SAML) — Operator Runbook (User Federation, SAP-as-SAML-SP; Entra or Okta)

> **PREVIEW — not yet deployable.** The User Federation outbound flow (with Entra, Okta, or
> Cognito-fronted IAS as the IdP) is not built yet: the topology is modeled and validated, but its
> deployment module does not exist. Reference design for the roadmap, not a ready-to-run procedure.

> **STATUS.** USER_FEDERATION (SAML) with Entra or Okta is a **documented USER_FEDERATION
> variant, NOT aspirational** — the AWS-for-SAP MCP identity doc carries the row *"SAP as
> Authorization Server with OAuth2 and SAML IdP redirect | User Federation | OAuth2 + SAML |
> Entra ID or other SAML IdP | SAP OAuth2 client + SAML trusted provider"* and states the UF
> flow *"uses either OAuth2, OIDC, or SAML2 depending on your choice of IdP"*
> ([identity-and-authentication](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/identity-and-authentication.html)).
> The **AWS-side is built**, not aspirational: because AgentCore's leg is plain
> OAuth2 to SAP (the bridge below), USER_FEDERATION (SAML) uses the **same generic User Gateway target** as
> USER_FEDERATION (OIDC) — the Gateway target has no SAML/OIDC branch, so all
> USER_FEDERATION variants produce the identical AWS-side output. The preview status means
> **not E2E-verified against a live SAP + SAML IdP**, *not* "uncoded" — the remaining work is
> SAP-side (SAML2 trust + SOAUTH2↔SAML2 linkage + `NameID`→SU01) plus a real-user audit proof, not
> AWS-side code. (Verified against current AWS/SAP docs.)
> SAP-side facts that could not be re-confirmed against a primary SAP doc (help.sap.com is
> client-side-rendered and returned title-only on fetch) are marked **UNVERIFIED**.
>
> **MECHANISM CORRECTION — read this first.** AgentCore does **NOT** drive, receive, parse, or
> validate a SAML assertion. This is an **OAuth-2.0 bridge**: AgentCore runs the interactive
> 3-legged **authorization-code** flow against **SAP's own OAuth authorization server**
> (SAP's authorize/token endpoints); SAP — acting as a **SAML 2.0 Service
> Provider** (transaction SAML2) — redirects the user's browser to the external SAML IdP
> (Entra/Okta). The SAML assertion is exchanged **only** between the browser, the IdP, and SAP;
> it is one layer upstream and **invisible to AgentCore**. The AWS row label **"OAuth2 + SAML"**
> denotes exactly this bridge. Any wording that reads as *"AgentCore propagates / drives / validates
> a SAML assertion"* is wrong — SAP does that, as SP.

**Audience:** an SAP admin **+** an Entra admin (Entra variant) or Okta admin (Okta variant) **+** an AWS operator,
executing together. Each side owns a lane below; the checklist maps every step to its operator.

This runbook is a **variant-delta on the base USER_FEDERATION documentation** — read the base
User Federation documentation **first**. It owns the shipped contract (the User Gateway target,
the two callback URLs, SAP's authorize / token endpoints, config validation). This doc does
**not** repeat that mechanics; it adds only the **SAP-as-SAML-SP trust delta** (SAML2 trust + the
SOAUTH2 auth-code OAuth client) and the IdP SAML app. For the deploy-model / env-var contract see
the base SAP MCP integration documentation. For the sibling flows: OBO /
ON_BEHALF_OF_TOKEN_EXCHANGE (server-side, direct-to-MCP, RFC 7523) is
[soidc-entra-obo.md](./soidc-entra-obo.md); M2M (machine identity, SOAUTH2/SOIDC) is
[m2m-oauth2-sap.md](./m2m-oauth2-sap.md); the email-join OIDC federation variant is described in the
same-sub federation documentation. SOIDC/STRUST mechanics live in
[soidc-entra-obo.md S2/S3](./soidc-entra-obo.md) — cross-linked, not duplicated.

## When to pick UF-SAML (vs the other flows)

| | **USER_FEDERATION (SAML), this doc** | **USER_FEDERATION (OIDC)** | **OBO / ON_BEHALF_OF_TOKEN_EXCHANGE** |
|---|---|---|---|
| Human interaction | Interactive 3-legged login; SAP redirects to the SAML IdP | Interactive 3-legged; SAP trusts the IdP via OIDC | **None** — server-side exchange |
| What SAP trusts | **SAML2** trusted provider (Entra/Okta as SAML IdP) | **SOIDC** OIDC-provider trust | **SOIDC** trust to Entra, direct |
| Grant AgentCore drives | OAuth2 authorization-code (to SAP's OAuth server) | OAuth2 authorization-code (to SAP's OAuth server) | RFC 7523 jwt-bearer |
| Topology in this repo | **Gateway User target** | Gateway User target | Direct-to-MCP (OBO-only) |
| SAML assertion seen by AgentCore | **Never** — browser↔IdP↔SAP only | n/a | n/a |

Pick **USER_FEDERATION (SAML)** when SAP already trusts an external **SAML** IdP (Entra/Okta SAML) and you want
the interactive per-user path. If SAP trusts the IdP by **OIDC**, use USER_FEDERATION (OIDC). If no second
login is acceptable and SAP trusts Entra directly, use OBO / ON_BEHALF_OF_TOKEN_EXCHANGE. All USER_FEDERATION
variants use the **same** User Gateway target — see A3.

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

**KEY POINT (grounds every step below).** AgentCore speaks **only** OAuth2 (authorize/token,
clientId/secret, scopes) end-to-end and stores the resulting SAP token in its vault. It never
registers a SAML IdP, never receives or validates a SAML assertion. The SAML leg is entirely
SAP-side. (A separate, **non-UF** path is RFC 7522 SAML-bearer — an assertion POSTed to SAP's token
endpoint for M2M-style exchange. That is a different grant and **not** this interactive flow — do
not conflate.)

---

## SAP-side steps (SAP admin)

This lane is **only the SAML-SP + SOAUTH2 trust delta**. Base OData connectivity + the SU01 user
are owned by the SAP system configuration documentation — do **not** redo
BASIC/service-account setup here.

### S1. Verify the Basis floor for the SAML2-trusted-provider + SOAUTH2 combination — **UNVERIFIED**

SAP GUI: **System → Status** (component `SAP_BASIS`); SPAM/SAINT for the SP level. SAML 2.0
Service-Provider support is long-standing in NetWeaver / ABAP Platform, but the release that
supports **linking a SAML2 trusted provider to a SOAUTH2 OAuth authorization-code client** (so the
OAuth authorize endpoint delegates human logon to the SAML IdP) is **UNVERIFIED** against a primary
SAP doc — confirm on your release before relying on this flow.

### S2. Configure SAP as a SAML 2.0 Service Provider trusting the external IdP — field labels **UNVERIFIED**

SAP GUI transaction **SAML2**. Create/confirm SAP's **Local Provider** (SAP as SP), then add
Entra / Okta as a **Trusted Provider** by importing the IdP's SAML metadata (IdP
EntityID/Issuer, SSO endpoints, X.509 signing cert). This is the AWS row's *"SAML trusted provider"*.
Exact SAML2 screen labels (Local Provider / Trusted Provider / NameID format / assertion consumer
service URL) are **UNVERIFIED** — confirm in the live transaction. Corroboration that SAP-as-SP is
set up via SAML2 (*"Create SAML 2.0 Local Provider"*):
[AWS-for-SAP SSO-with-Fiori blog](https://aws.amazon.com/blogs/awsforsap/aws-single-sign-on-integration-with-sap-fiori-in-s-4hana/).

### S3. Import the IdP's SAML signing + endpoint TLS chain into STRUST

SAP GUI transaction **STRUST**. SAP validates the assertion signature and fetches IdP endpoints over
TLS, so import the **full** IdP SAML assertion-signing chain **and** endpoint TLS chain (leaf +
intermediates + public root CA), then restart ICM / the PSE-consuming work processes. **Root-only
imports are the classic silent failure.** STRUST mechanics are identical to
[soidc-entra-obo.md S2](./soidc-entra-obo.md#s2-import-the-entra-token-endpoint-tls-chain-into-strust)
— cross-linked, not repeated.

### S4. Map the SAML NameID (email) → SU01 business user — **UNVERIFIED labels**

SAP GUI transaction **SAML2** (assertion → user mapping) + **SU01** (target users). SAP maps the
assertion **NameID/attribute** to an SU01 user. **Join on email**, not on an opaque identifier:
- **Okta** commonly emits **email** as the NameID subject (easy join).
- **Entra** must be configured to send a stable human attribute (**email/UPN**) as NameID — do
  **NOT** join on Entra's default persistent/pairwise identifier (opaque; will not match an SU01
  user). This is the SAML analog of the OIDC opaque-`sub` trap in
  [soidc-entra-obo.md S4](./soidc-entra-obo.md#s4-map-the-entra-sub--su01-business-user-via-a-custom-claim-mapping--unverified).

Each target SU01 user must exist with the matching email/UPN and hold the PFCG OData authorizations
for the services the agent calls. Same email-join principle as the same-sub federation
documentation, but via SAP's **own** SAML2 SP,
**not** IAS (same-sub trust is not transitive). Exact mapping labels are **UNVERIFIED**.

### S5. Create the SOAUTH2 auth-code OAuth client, LINKED to the SAML2 trusted provider — the load-bearing SAP fact, **UNVERIFIED**

SAP GUI transaction **SOAUTH2**. Register an **authorization-code (3-legged)** OAuth 2.0 client so
SAP acts as its own authorization server for the interactive flow:
- The client's **authorize / token** endpoints are SAP's own OAuth authorize/token endpoints,
  configured on the external stack (A1).
- Register the **AgentCore callback URL** (from A4, after deploy) as an allowed **redirect URI** on
  **this SOAUTH2 client** — **not** on the SAML IdP app.
- Its logon must **delegate to the SAML2 trusted provider** (S2), so an unauthenticated hit on the
  authorize endpoint triggers the SAML redirect to Entra/Okta.
- Record `{clientId, clientSecret}` for the external stack's Secrets Manager secret (A1).

The **SOAUTH2↔SAML2 linkage** (that the OAuth authorize endpoint delegates human logon to the SAML2
trusted provider) is the load-bearing SAP-side fact and is **UNVERIFIED** against a primary SAP doc —
grounded only in the AWS row *"SAP OAuth2 client + SAML trusted provider"*. SAP
Help search corroborates the pairing (*"Start the transaction SAML2 … Start transaction SOAUTH2 …
choose the OAuth 2.0 client"*, help.sap.com "Configuring a Trusted Identity Provider for OAuth 2.0",
title-only fetch) but the exact runtime `authorize → SAML redirect → token` sequence was **not read
verbatim** — confirm on your system. (Contrast: a SOAUTH2 **client-credentials** client is the M2M
path — no human, no SAML — see [m2m-oauth2-sap.md S2](./m2m-oauth2-sap.md).)

### S6. Activate the required SICF service nodes — SAML2/token nodes **UNVERIFIED**

SAP GUI transaction **SICF** (right-click → Activate). Activate the OData runtime tree
`/sap/opu/odata/sap/` (and each service subnode exposed via scopes) plus the IWFND catalog service
`/sap/opu/odata/iwfnd/catalogservice;v=2` (same node set as the siblings — cross-link
[m2m-oauth2-sap.md S4](./m2m-oauth2-sap.md)). **Additionally** the SAML2 SP service
`/sap/public/bc/sec/saml2` + its assertion-consumer node, and any OAuth authorize/token SICF node,
must be active. The exact SAML2/OAuth node paths for your release are **UNVERIFIED** — confirm.

### S7. Smoke-test the SAP trust in isolation (before full E2E)

- **STRUST/SAML2:** confirm SAP reaches + trusts the IdP SAML signing cert and endpoints (no
  handshake/signature error in `dev_icm` / SMICM); SAML2 shows the trusted provider active.
- **Interactive login:** hit SAP's SOAUTH2 authorize endpoint in a browser → expect a redirect to
  Entra/Okta → after IdP login, a SAML assertion POSTs back to SAP's ACS and SAP issues an
  authorization code. A failure to redirect → the SOAUTH2↔SAML2 linkage (S5) is wrong. A SAML
  signature error → STRUST chain (S3). A "no matching user" → the NameID→SU01 mapping (S4).
- **One OData service** with the resulting SAP OAuth token: **401** → SOAUTH2 client / token
  endpoint wrong. **403** → the mapped SU01 user lacks PFCG authorization.
- **Audit proof (the acceptance test):** SM20 / RSAU_* must show the action under the **mapped human
  SU01 user**, not a service account — a silent service-account fallback means the human identity did
  not survive. **UNVERIFIED end-to-end** (this flow not run here).

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
   **Reply URL (Assertion Consumer Service URL)** = SAP's ACS. (Lazy path: upload SAP's SP metadata
   XML instead of typing.)
2. **Attributes & Claims** → Edit: set **Unique User Identifier (Name ID)** = `user.mail` with
   NameID format `urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress`
   ([Entra SAML protocol](https://learn.microsoft.com/en-us/entra/identity-platform/single-sign-on-saml-protocol)).
   **Do NOT leave NameID at Entra's default persistent/pairwise identifier** (the S4 opaque trap).
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
   natively puts email in the subject — why the Okta variant is simpler than the Entra opaque case).
3. **Attribute Statements** — only for extra claims beyond the NameID subject.
4. After the wizard, the **Sign On** tab exposes Okta's IdP metadata: hand SAP the **Identity
   Provider Issuer** (IdP EntityID), **Single Sign-On URL**, and **X.509 signing certificate** (or
   the metadata URL for SAML2 to ingest). The exact Sign-On-tab label for retrieving metadata/cert
   is **UNVERIFIED** against a primary Okta doc.

> **The Okta variant is less-validated.** AWS docs say *"Entra ID or other SAML IdP"* generically and do
> **not** name Okta for this pattern (**UNVERIFIED** for Okta specifically). The mechanism
> is identical to Entra — only the IdP differs. Treat the Okta variant as plausible-but-unproven-in-AWS-docs.

---

## AWS / AgentCore-side steps (AWS operator)

> The external AWS-for-SAP MCP stack, its inbound pool, and its OAuth provider are owned
> externally — not deployed here. The AWS-side deployment mints the **Gateway
> User target + a Gateway OAuth2 credential provider** (the UF path is the Gateway path, never
> direct-to-MCP). From AgentCore's side this is a plain OAuth2 authorization-code provider pointed
> at SAP's OAuth server — **AgentCore is unaware of SAML**.

### A1. Set the USER_FEDERATION flow + SAP SOAUTH2 endpoints on the external stack — **all**

External stack env vars (CFN params; editable via Bedrock AgentCore console → Runtime → Update
Hosting → Advanced Configurations). These are set on the external stack, not by the AWS-side deploy here:
- `MCP_SERVER_SAP_OAUTH_FLOW=USER_FEDERATION`
- SAP's **SOAUTH2 auth-code** `authorize` + `token` endpoints — configured on the external stack's
  SAP OAuth provider (the `authorizationServerMetadata` in A2).
- `MCP_SERVER_SAP_OAUTH_SCOPES=<sap-service-name(s)>` e.g. `ZAPI_SALES_ORDER_SRV_0001` — **SAP OData
  service names, NOT OAuth scope URIs**; a wrong/foreign scope → **HTTP 403** (each service must be
  SICF-activated S6 and PFCG-authorized S4)
- `MCP_SERVER_APP_CALLBACK_URL` = the frontend `/auth/callback` route (must end in `/callback` or
  `/oauthcallback`)
- Secret `{clientId, clientSecret}` = the **SOAUTH2 auth-code client** from S5
- Start read-only (`MCP_SERVER_WRITE_ENABLED=false`); enable writes there when ready.

### A2. Create the AgentCore Identity outbound OAuth2 provider (SAP-facing) — **all**

`aws bedrock-agentcore-control create-oauth2-credential-provider` (or Console → custom provider),
`clientId`/`clientSecret` = the S5 SOAUTH2 client. Use
`oauthDiscovery.authorizationServerMetadata` (explicit `authorizationEndpoint` + `tokenEndpoint` +
`issuer`), **NOT** `discoveryUrl`: a SAP OAuth URL is not a `.well-known` document and fails
AgentCore's `discoveryUrl` regex — same as the M2M SAP-facing provider
([m2m-oauth2-sap.md A2](./m2m-oauth2-sap.md); see also the `discoveryUrl` regex rejection note in
the base SAP MCP integration documentation). This is an ordinary **OAuth2 authorization-code** provider from AgentCore's side; the
SAML redirect happens later, inside SAP, invisibly.

### A3. The Gateway User target — Gateway path, NOT direct-to-MCP — **all**

For a User outbound profile, the deploy mints a **"User" Gateway target**
(`credentialProviderType: "OAUTH"`) pointing at the external runtime; interactive calls keep flowing
through the Gateway (Cedar + `x-audit-*` interception intact). The interactive auth URL surfaces
through the Gateway as tool-result JSON. It is **NOT** direct-to-MCP (that is OBO-only).

**USER_FEDERATION (OIDC), USER_FEDERATION (SAML), and USER_FEDERATION with SAP as its own OAuth
authorization server all use the SAME User Gateway target** — the only difference is what SAP
trusts (SOIDC vs SAML2 vs SAP-native) and where the human authenticates; invisible to AgentCore.
There is no SAML-specific variant on the AWS side. The SAP OAuth knobs
(`MCP_SERVER_SAP_OAUTH_FLOW` / scopes / `MCP_SERVER_APP_CALLBACK_URL`) live on the **external** stack.

### A4. The Gateway OAuth2 (inbound) provider must point at the EXTERNAL stack's pool — **all**

The Gateway OAuth2 provider **must point at the EXTERNAL stack's inbound pool**, not the local one — else the
runtime **401s** (`iss` mismatch); see the "401 in external mode" troubleshooting note in the base SAP MCP integration documentation.
After deploy, AgentCore Identity's outbound provider returns a **callback URL** — register that exact
URL as a redirect URI on **SAP's SOAUTH2 client** (S5), **not** on the SAML IdP app.

---

## The callback / redirect URLs (three, do not conflate)

Base UF mechanics for the first two live in the "The two callback URLs" section of the base User
Federation documentation — not repeated here. UF-SAML adds a **third**, SAP-owned, IdP-registered
SAML endpoint:

| URL | Owner | Registered where | Used by |
|---|---|---|---|
| AgentCore provider callback | AWS / AgentCore Identity | **SAP's SOAUTH2 OAuth client** (redirect-URI allowlist) — **NOT the SAML IdP** | Completes the OAuth code exchange (A4/S5) |
| `MCP_SERVER_APP_CALLBACK_URL` (`/auth/callback`) | Frontend | App config | Signals completion to the app |
| **SAP SAML ACS** (assertion consumer service) | **SAP** (as SAML SP) | **The SAML IdP app** (Entra Reply URL / Okta Single sign-on URL) | The SAML leg (browser↔IdP↔SAP) — AgentCore never sees it |

**The single fact proving AgentCore's leg is OAuth2, not SAML:** the AgentCore callback registers on
SAP's **SOAUTH2** client; the IdP app's only reply URL is SAP's **ACS**. Conflating these silently
breaks the flow.

---

## Checklist (mapped to the AWS outbound-auth table rows)

| Side | Step | Outbound-auth row |
|---|---|---|
| **SAP** | S1 Basis floor for SAML2↔SOAUTH2 combo (**UNVERIFIED**) | UF-SAML prerequisite |
| **SAP** | S2 SAML2 trusted provider (Entra) | SAML trust (Entra) SAML2 |
| **SAP** | S2 SAML2 trusted provider (Okta) | SAML trust (Okta) SAML2 |
| **SAP** | S3 STRUST full IdP SAML+TLS chain + ICM restart | SSL certs STRUST (Entra, Okta) |
| **SAP** | S4 NameID (email)→SU01 mapping (**UNVERIFIED** labels) | user mapping |
| **SAP** | S5 SOAUTH2 auth-code client linked to SAML2 (**UNVERIFIED**) | OAuth2 client (auth code) SOAUTH2 |
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
| **Auth URL opens but SAP does not redirect to the IdP** | SOAUTH2 client not linked to the SAML2 trusted provider (S5 gap) | Wire SOAUTH2 logon to delegate to the SAML2 provider — S5 (**UNVERIFIED** — confirm on-system) |
| **IdP rejects the redirect** | AgentCore callback registered on the **SAML IdP** instead of SAP's **SOAUTH2** client | Register the AgentCore callback on the SOAUTH2 client; the IdP app carries only SAP's ACS — S5/A4 |
| **SAML signature / trust error at SAP** | IdP signing chain not fully imported (root-only) | Import the full IdP SAML signing chain into STRUST — S3 |
| **SAP: "no matching user" after SAML login** | NameID is Entra's opaque/pairwise id, or SU01 email mismatch | Set Entra NameID = `user.mail` (emailAddress); ensure SU01 email matches — S4/E-Entra |
| **SAP 403** on OData | Wrong scope (not a service name), or mapped SU01 user lacks PFCG | Set scopes to OData service names; grant PFCG — A1/S4 |
| **`discoveryUrl` regex rejection** creating the SAP provider | SAP OAuth URL passed where a `.well-known` URL is expected | Use `authorizationServerMetadata` (auth+token+issuer) — A2 |

## Open items (carried, not blocking — reference design)

- **Not built / not run end-to-end.** This flow is in preview — the User Federation deployment
  module is unbuilt; no live SAML SSO or real-user SAP audit proof exists here. The whole SAP-MCP
  integration is reference design (see the status banner in the base SAP MCP integration documentation).
- **THE load-bearing UNVERIFIED fact:** the **SOAUTH2↔SAML2 linkage** (S5) — that SAP's OAuth
  authorize endpoint delegates human logon to the SAML2 trusted provider — is grounded only in the
  AWS row *"SAP OAuth2 client + SAML trusted provider"* + a title-only help.sap.com
  search snippet; the exact `authorize → SAML redirect → token` sequence was not read verbatim.
  **Confirm on a live SAP system before sign-off.**
- **UNVERIFIED against primary SAP docs:** Basis floor for the SAML2-trusted-provider-for-OAuth combo
  (S1); exact SAML2 transaction screen labels — Local Provider / Trusted Provider / NameID format /
  ACS URL (S2); exact SAML2→SU01 mapping labels (S4); which SICF nodes the SAML2 SP + OAuth
  authorize/token endpoints require, incl. the exact ACS path under `/sap/public/bc/sec/saml2` (S6).
- **UNVERIFIED against AWS docs:** the **Okta variant** specifically — AWS docs say *"Entra ID or other SAML
  IdP"* and do not name Okta. Mechanism identical to Entra.
- **UNVERIFIED against a primary Okta doc:** the Sign-On-tab label for retrieving IdP metadata / X.509
  signing cert after the wizard (E-Okta step 4).
- **Mechanism claim resting on secondary sources:** the "AgentCore Identity is OAuth2/OIDC-only, no
  native SAML provider" conclusion rests on the fully-rendered AWS SAP-MCP identity doc + the AgentCore
  provider list ([identity-idps.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/identity-idps.html),
  no SAML entry); the AgentCore devguide auth-patterns page body was not read verbatim (client-side
  rendered).
- **Mechanism guardrail for future edits:** if the base User Federation documentation is later
  reworded to describe the SAML sub-case, keep it to the OAuth-bridge mechanism (AgentCore→SAP
  OAuth2, SAP→IdP SAML2) — never "AgentCore drives SAML."

## References

- Base User Federation documentation — User target, the two callback URLs, SAP's authorize/token endpoints, config validation (read first)
- Base SAP MCP integration documentation — deploy model, env-var contract, inbound-pool 401, `discoveryUrl` regex, `authorizationServerMetadata`
- [soidc-entra-obo.md](./soidc-entra-obo.md) — sibling OBO / ON_BEHALF_OF_TOKEN_EXCHANGE; STRUST + opaque-subject-mapping trap (S2/S4)
- [m2m-oauth2-sap.md](./m2m-oauth2-sap.md) — sibling M2M; SOAUTH2 client-credentials contrast + `authorizationServerMetadata`
- Same-sub federation documentation — email-join federation (IAS/OIDC variant); same-sub trust not transitive
- SAP system configuration documentation — SU01 user + PFCG + SICF base (reused, not redone)
- [AWS SAP-MCP — Identity and Authentication](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/identity-and-authentication.html) — outbound-auth table row *"OAuth2 + SAML | SAP OAuth2 client + SAML trusted provider"*; UF *"either OAuth2, OIDC, or SAML2 depending on your choice of IdP"*
- [AWS SAP-MCP — Getting Started](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/getting-started.html) — Pattern 2: SAP as Authorization Server with OAuth2 + SAML IdP; AgentCore callback registered on SAP's OAuth2 client
- [AgentCore — Supported identity providers](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/identity-idps.html) — OAuth2/OIDC provider list (no SAML entry)
- [Entra: set up SAML SSO](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/add-application-portal-setup-sso) / [Entra SAML protocol](https://learn.microsoft.com/en-us/entra/identity-platform/single-sign-on-saml-protocol)
- [Okta SAML app field reference](https://help.okta.com/en-us/content/topics/apps/aiw-saml-reference.htm)
- [AWS-for-SAP — SSO with Fiori in S/4HANA](https://aws.amazon.com/blogs/awsforsap/aws-single-sign-on-integration-with-sap-fiori-in-s-4hana/) — SAP-as-SP via SAML2 local provider
