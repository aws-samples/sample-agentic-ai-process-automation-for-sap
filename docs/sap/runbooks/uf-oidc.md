<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# USER_FEDERATION (OIDC) — Operator Runbook (User Federation, external OIDC IdP; Entra or Okta)

> **Status.** The USER_FEDERATION outbound is `status: stub` in `auth-profiles.yaml`
> (`user-federation: { ..., status: stub, blocked_by: upstream }`). The wiring exists in this
> repository, but this sample has not yet run it end to end, and the deploy prints a notice
> saying so. AWS documents this pattern in the scenario table as *"External IdP with OIDC | User
> Federation | OIDC | Entra ID | SAP OIDC trust"*
> ([identity-and-authentication](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/identity-and-authentication.html)).
> SAP-side details that vary by release say *confirm on your system*.

**Before you start.** Programmatic or agent access to SAP can have licensing implications (for
example, SAP Digital Access). Review with your SAP account team.

The person signs in interactively (3-legged) at Microsoft Entra ID or Okta, which is the
authorization server. SAP validates the resulting token through a **SOIDC** trust to that IdP and
runs OData as that person.

**This is the base UF case; the siblings are deltas from it.** USER_FEDERATION (SAML)
([uf-saml.md](./uf-saml.md)) makes SAP a SAML 2.0 service provider with its own OAuth server;
USER_FEDERATION with SAP as its own OAuth authorization server
([uf-oauth2-sap.md](./uf-oauth2-sap.md)) uses no IdP at all; OBO /
ON_BEHALF_OF_TOKEN_EXCHANGE ([soidc-entra-obo.md](./soidc-entra-obo.md)) uses the **same SOIDC
trust** but a non-interactive server-side exchange (no second sign-in). Okta's default
authorization server sets `sub` to the Okta username, which is commonly the email address, so the
SAP mapping can be simpler (see S3); Entra's opaque `sub` needs a custom claim mapping.

**Audience:** an SAP admin **+** an Entra admin (Entra path) or Okta admin (Okta path) **+** an AWS
operator. Each side owns a lane below; the checklist maps every step to its operator.

Understand the shared USER_FEDERATION contract first — the User Gateway target and the two
callback URLs, in [SAP_MCP_USER_FEDERATION.md](../SAP_MCP_USER_FEDERATION.md). The SAP-side
**SOIDC trust + STRUST + the `sub`→SU01 mapping** are the same as the OBO flow
([soidc-entra-obo.md](./soidc-entra-obo.md)) S2/S3/S4, which this runbook links rather than
repeats; the difference from OBO is that the sign-in is **interactive 3-legged** (User Gateway
target) rather than a server-side exchange.

## When to pick USER_FEDERATION (OIDC) (vs the other UF variants and OBO)

| | **USER_FEDERATION (OIDC), this doc** | **USER_FEDERATION (SAML)** | **USER_FEDERATION (SAP as authz server)** | **OBO / ON_BEHALF_OF_TOKEN_EXCHANGE** |
|---|---|---|---|---|
| Who is the OAuth authz server | the **external OIDC IdP** (Entra/Okta) | SAP (redirects to a SAML IdP) | **SAP itself** | the Entra outbound app |
| What SAP trusts | **SOIDC** (OIDC provider) | **SAML2** trusted provider | SAP-native (no IdP) | **SOIDC**, direct |
| Human interaction | interactive 3-legged OIDC | interactive 3-legged + SAML redirect | interactive 3-legged | **none** — server-side |
| Needs a SAP SOAUTH2 client | **No** — the IdP is the authz server | Yes (auth-code + SAML link) | Yes (auth-code) | No |
| AgentCore provider points at | the **IdP** `.well-known` (`discoveryUrl`) | SAP OAuth (`authorizationServerMetadata`) | SAP OAuth (`authorizationServerMetadata`) | the IdP (`discoveryUrl`) |
| Topology in this repo | **Gateway User target** | Gateway User target | Gateway User target | Direct-to-MCP (OBO-only) |

Pick **USER_FEDERATION (OIDC)** when SAP already trusts your OIDC IdP (Entra/Okta) and an interactive
login is acceptable. All UF variants map to the **same** USER_FEDERATION outbound flow and the
**same** User Gateway target.

## End-to-end flow (short)

```
Agent ─▶ AgentCore Gateway (User target, credentialProviderType:OAUTH)
      ─▶ external AWS-for-SAP MCP Runtime (inbound: token from the EXTERNAL stack's pool — see the inbound-pool risk in A3)
      ─▶ AgentCore Identity USER_FEDERATION (3-legged OIDC to the external IdP): returns an auth URL
      ─▶ (auth URL surfaces back through the Gateway as tool-result JSON — agent relays to frontend)
      ─▶ human logs in at Entra/Okta ─▶ IdP issues a per-user OIDC token
      ─▶ AgentCore callback ─▶ /auth/callback (signals completion)
      ─▶ MCP server calls SAP OData with the per-user OIDC token
      ─▶ SAP validates it via SOIDC trust + maps a claim (email/sub) → SU01 user; enforces that user's authz
```

Unlike the SAP-as-authz-server and SAML variants, **SAP is not the OAuth authorization server here** —
the external OIDC IdP is, so there is **no SAP SOAUTH2 client** to create; SAP only needs the
**SOIDC trust** to validate the IdP's token. Unlike OBO (same SOIDC trust), the login is
**interactive** — the auth-URL / tool-result / two-callback-URL mechanics are the base USER_FEDERATION
story (see the two-callback-URL treatment in A2 below).

---

## SAP-side steps (SAP admin)

The SOIDC trust, STRUST chain, and `sub`→SU01 mapping are the same as the OBO flow — this lane
links [soidc-entra-obo.md](./soidc-entra-obo.md) rather than repeating them. Base OData
connectivity and each person's SU01 user are covered by
[SAP_SYSTEM_CONFIGURATION.md](../SAP_SYSTEM_CONFIGURATION.md) (SU01 user + PFCG + SICF base).

> **Okta details.** The Okta-specific SAP details below (SOIDC fields, the `/oauth2/default`
> issuer, the `cmRc=20` reachability error, the SOIDC token trace) were observed on one SAP
> S/4HANA test system with Okta, through an MCP topology without a Gateway. They cover the SAP
> trust, which does not depend on the AWS topology; the Gateway User-target path has not yet been
> run end to end in this sample.

### S1. STRUST — import the IdP's TLS chain

Import the OIDC IdP's full token-endpoint TLS chain (leaf + intermediates + root) into the SAP
**STRUST** **SSL Client (Standard) PSE** and restart ICM, as in
[soidc-entra-obo.md S2](./soidc-entra-obo.md#s2-import-the-entra-token-endpoint-tls-chain-into-strust)
(a root-only import is a common cause of silent TLS failures). Restarting ICM drops the system's
open HTTP connections; schedule it. For Okta the host is your Okta org /
custom-auth-server domain instead of `login.microsoftonline.com`.

Prerequisites: **SAP ICM must have HTTPS enabled**; the IdP's **root CA** must be imported into
the SSL Client PSE; and SAP must reach the IdP endpoints **outbound** to download JWKS keys (S2).
If SAP cannot reach the IdP, JWKS download fails with the RFC
error **`ThSAPOCMINIT, CM_PRODUCT_SPECIFIC_ERROR cmRc=20`** — treat `cmRc=20` as "SAP→IdP network/
proxy/TLS blocked," not a token problem.

### S2. SOIDC — create the OIDC provider trust for the IdP

SAP GUI transaction **SOIDC**. Register Entra ID or Okta as an OIDC provider. Fields (Okta):
- **Issuer** = the IdP issuer, e.g. `https://<okta-domain>/oauth2/default` (see the `/oauth2/default`
  trap in S2a below — the issuer **must** match what the token actually carries and what AgentCore's
  authorizer validates).
- **JWKS download URL** = `https://<okta-domain>/oauth2/default/v1/keys` — SAP downloads the signing
  keys from here (requires outbound reachability + the TLS chain in STRUST S1).

This is the **same** SOIDC registration as [soidc-entra-obo.md S3](./soidc-entra-obo.md#s3-create-the-oidc-provider-trust-for-entra-in-soidc)
— the difference is that the audience is the **interactive** OIDC client (E-Entra/E-Okta), not
an OBO outbound app. For Entra, set the audience to the app registration whose API the token is
requested for (E-Entra). Field labels beyond issuer and JWKS vary by release — confirm on your
system.

#### S2a. The `/oauth2/default` issuer

Okta exposes two authorization servers with **different issuers**, and picking the wrong one 401s:
- **Org server** `/oauth2/v1/` → issuer `https://<okta-domain>` — does not match the SAP/AgentCore configuration.
- **Custom (default) server** `/oauth2/default/v1/` → issuer `https://<okta-domain>/oauth2/default` — the one that matches.

Use the **`/oauth2/default`** endpoints everywhere (Okta app authorize/token URLs, SAP SOIDC issuer,
AgentCore `discoveryUrl`) so all three agree. Decode the `access_token` and check its `iss` claim if
in doubt.

### S3. Map the OIDC `sub`/claim → SU01 business user

SAP GUI transaction **SOIDC** (claim mapping) + **SU01**. The join key differs by IdP — this is the
one place the Entra and Okta paths diverge. SOIDC has a **User Mapping Claim** (which claim to
read) and a **User Mapping Mechanism** (how to resolve the SAP user from it); with claim `sub` and
mechanism **E-Mail**, SOIDC reads `sub` and resolves the SAP user by matching email.

- **Okta:** Okta's default authorization server sets `sub` to the Okta username, which is commonly
  the email address. When it is, the `sub` claim + E-Mail mechanism resolves the SU01 user whose
  email matches. Observed on one SAP S/4HANA test system.
- **Entra:** Entra emits an **opaque, app-pairwise `sub`** that
  will **not** carry email — so the `sub`+E-Mail mechanism above won't resolve. Configure a **custom
  claim mapping** on `preferred_username`/UPN or `email`, which requires **SOIDC Feature Pack 2+**
  (confirm on your system). This is the same mapping documented in
  [soidc-entra-obo.md S4](./soidc-entra-obo.md#s4-map-the-entra-sub--su01-business-user-via-a-custom-claim-mapping)
  (the OBO flow needs it too). Ensure the IdP emits that stable claim (E-Entra).

Each target SU01 user must exist with the matching identifier and hold the PFCG OData
authorizations for the services the agent calls, or SAP returns **403**. Unmapped users fail
closed; there is no service-account fallback.

A token that maps is a full SAP logon for that user: its scopes do not confine it to particular
OData services, and the PFCG roles on the mapped user are the authorization boundary.

### S4. SICF — activate the OData service nodes — same set as the siblings

SAP GUI transaction **SICF** → activate `/sap/opu/odata/sap/` (+ each exposed service subnode) and,
if `MCP_SERVER_USE_SAP_CATALOG=true`, `/sap/opu/odata/iwfnd/catalogservice;v=2`. Same node set as
[soidc-entra-obo.md S6](./soidc-entra-obo.md) / [m2m-oauth2-sap.md S4](./m2m-oauth2-sap.md) — not
re-derived. **No** SAP OAuth/SOAUTH2 SICF node is needed (the IdP, not SAP, is the OAuth server).


### S5. Smoke-test the SAP trust in isolation (before full E2E)

- **SOIDC/STRUST:** confirm SAP reaches + trusts the IdP `.well-known` + JWKS over TLS (no handshake
  error in `dev_icm` / SMICM); SOIDC shows the provider active.
- **One OData service** with a real per-user OIDC token (from a manual IdP login): **401** with
  issuer/`aud` mismatch → SOIDC issuer/audience wrong (S2). **401** with `sub`/claim not resolving →
  the S3 mapping (the Entra opaque-`sub` trap). **403** → the mapped SU01 user lacks PFCG.
- **Audit proof (the acceptance test):** STAD (transaction STAD), or SM20 if the security audit
  log's logon classes were enabled beforehand, must show the action under the **mapped human SU01
  user**, not a service account. See
  [Proving user attribution in SAP](./soidc-entra-obo.md#proving-user-attribution-in-sap).
- **SOIDC token trace:** in transaction **SOIDC** you can **trace/analyze a
  token** — paste a captured `access_token` and SOIDC validates it, showing a green result or an
  error with a description. Use this to localize a 401 to the SAP side (issuer/audience/`sub` mapping
  vs. JWKS reachability) before looking at the AWS side.

---

## IdP-side steps — register an interactive **OIDC** client whose redirect is the AgentCore callback

Unlike UF-SAML (where the IdP app's reply URL is SAP's ACS), here the IdP is the OAuth authorization
server, so the **AgentCore provider callback URL** (from A2, after deploy) is the redirect URI on the
IdP's OIDC client.

### E-Entra. Entra OIDC app registration

Entra admin center → **App registrations** → New registration. Add a **Web** platform with redirect
URI = the **AgentCore provider callback** (`.../identities/oauth2/callback/<provider-guid>`, from
A2 — register it **after** deploy). Create a client secret → the `{clientId, clientSecret}` the
external stack reads. Under **Token configuration**, add the stable optional claim
(`preferred_username`/`email`/`upn`) the SAP **S3** mapping binds to (Entra's default `sub` is
opaque). Under **Expose an API**, set an Application ID URI (`api://<app-id>`) and add a delegated
scope, then grant admin consent. The provider requests `api://<app-id>/<scope>` (A1), so the
token's `aud` is this app — set the SOIDC audience (S2) to it. A request for only
`openid`/`profile`/`email` returns a token for Microsoft Graph, which SAP cannot validate.

### E-Okta. Okta OIDC app + custom authorization server

Okta admin → **Applications → Create App Integration → OIDC → Web Application**; set the **Sign-in
redirect URI** = the AgentCore provider callback (A2, after deploy). Use a **Custom Authorization
Server** (Security → API) if you need custom scopes/claims. Okta's default authorization server
sets `sub` to the Okta username, which is commonly the email address (S3). Record the
`{clientId, clientSecret}` for the external stack's secret. The IdP `.well-known` discovery URL
(org or custom-auth-server) is what the AgentCore provider (A2) and SAP SOIDC (S2) both point at.

> **Okta and Entra are the same mechanism** — only the `sub` shape and claim-mapping effort
> differ (S3). AWS documents Entra ID explicitly; Okta uses the same OIDC pattern and has not yet
> been run end to end in this sample.

---

## AWS / AgentCore-side steps (AWS operator)

> The deployment does **not** provision the external AWS-for-SAP MCP stack, its inbound pool, or its
> OAuth provider — those are owned externally. Your IaC mints the **Gateway User target + a Gateway
> OAuth2 credential provider** (the UF path is the **Gateway** path — **never** direct-to-MCP; that is
> OBO-only, [OBO / ON_BEHALF_OF_TOKEN_EXCHANGE](./soidc-entra-obo.md)).

### A1. Set the USER_FEDERATION flow + SAP knobs on the external stack — **all**

External stack env vars (AWS CloudFormation parameters; editable in the Amazon Bedrock AgentCore
console → Runtime → Update Hosting → Advanced Configurations). This sample does not set these; the
SAP OAuth settings live on the external stack:

- `MCP_SERVER_SAP_OAUTH_FLOW=USER_FEDERATION`
- `MCP_SERVER_SAP_BASE_URL=https://<sap-host>/sap/opu/odata/sap/`
- `MCP_SERVER_SAP_OAUTH_PROVIDER=<provider-name>` — the A2 provider (note the `SAP_` infix)
- `MCP_SERVER_SAP_OAUTH_SCOPES=api://<app-id>/<scope>` — the scope the IdP issues the token for
  (E-Entra); for Okta, the custom authorization server's scope. Each OData service the agent calls
  must be SICF-activated (S4) and PFCG-authorized (S3), or SAP returns **403**.
- `MCP_SERVER_APP_CALLBACK_URL=https://<frontend-domain>/auth/callback` — required for
  USER_FEDERATION; the path **must end in `/callback` or `/oauthcallback`**.
- Secret `{clientId, clientSecret}` = the **IdP OIDC client** (E-Entra/E-Okta). The IdP is the
  authorization server, so these are the IdP's client credentials, **not** a SAP SOAUTH2 client.
- Keep `MCP_SERVER_WRITE_ENABLED=false` until you have reviewed the SAP API Policy (see the
  [README](../../../README.md)). This sample has no per-write approval step. On
  this Gateway path, the Cedar policies permit `odata_create`, `odata_update` and
  `odata_function_import` only for the finance, procurement and admin role tags and forbid
  `odata_delete`; the default `cedar_enforcement_mode: LOG_ONLY` only logs those decisions, so set
  `ENFORCE` for them to block.

> **Env-var name:** use `MCP_SERVER_SAP_OAUTH_PROVIDER` (with the `SAP_` infix). The env var name
> is what the AWS
> [configuration reference](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/configuration-reference.html)
> documents.

### A2. Create the AgentCore Identity OAuth2 provider for the IdP — real `discoveryUrl` (the OIDC delta)

`aws bedrock-agentcore-control create-oauth2-credential-provider` (or Console → custom provider),
`clientId`/`clientSecret` = the IdP OIDC client (A1's secret). Because the **external OIDC IdP** is
the authorization server, use a **real `oauthDiscovery.discoveryUrl`** = the IdP's
`.well-known/openid-configuration` — an OIDC IdP **does** publish one. This is the key contrast with
[the M2M SAP-facing provider](./m2m-oauth2-sap.md#a2-create-the-agentcore-identity-outbound-oauth2-credential-provider--all),
which must use `authorizationServerMetadata` because a SAP token URL is not a `.well-known` document.
Use a custom OAuth2 provider with that `discoveryUrl` for both Entra ID and Okta, so the issuer
the provider uses is the one SOIDC trusts (S2). After deploy,
register the provider's returned **callbackUrl** as a redirect URI on the **IdP's OIDC client**
(E-Entra/E-Okta) — **not** on SAP.

> **The two callback URLs — do not conflate.** The **AgentCore callback URL** (auto-generated) →
> the **IdP OIDC client**'s redirect-URI allowlist; `MCP_SERVER_APP_CALLBACK_URL` (`/auth/callback`)
> → the frontend completion route. These are two distinct URLs serving two distinct purposes; wiring
> one where the other belongs is the most common USER_FEDERATION setup error.

### A3. Gateway User target — not direct-to-MCP — **all**

The USER_FEDERATION path mints a **"User" Gateway target** (`credentialProviderType: "OAUTH"`)
pointing at the external runtime; calls keep flowing through the Gateway (Cedar + `x-audit-*`
interception intact). It is **not** the direct-to-MCP path (OBO-only,
[OBO / ON_BEHALF_OF_TOKEN_EXCHANGE](./soidc-entra-obo.md)). Same behavior as the SAML and
SAP-as-authz-server UF variants.

> **Inbound-pool risk.** The Gateway OAuth2 provider is the **inbound** credential to the external
> runtime and **must point at the EXTERNAL stack's inbound pool**, not yours — else the runtime
> **401s** (`iss` mismatch). Distinct from the **outbound** IdP-facing provider in A2.

---

## Checklist (mapped to the scenario-table rows)

| Side | Step | Scenario-table row |
|---|---|---|
| **SAP** | S1 STRUST full IdP TLS chain + ICM restart | SSL certs (Entra/Okta) STRUST |
| **SAP** | S2 SOIDC OIDC provider trust for the IdP | OIDC provider (Entra) SOIDC / (Okta) |
| **SAP** | S3 `sub`/claim→SU01 mapping (Entra opaque-`sub` FP2+ trap; Okta email-`sub` simple) | sub-claim mapping |
| **SAP** | S4 SICF `/sap/opu/odata/sap/` + `iwfnd/catalogservice;v=2` (no SOAUTH2 node) | SICF (All) |
| **SAP** | S5 isolation smoke-test + real-user audit proof | acceptance |
| **Entra** | E-Entra OIDC app-reg + AgentCore callback + stable optional claim | OIDC provider (Entra) / Redirect URI (AgentCore) |
| **Okta** | E-Okta OIDC app + Custom Auth Server + AgentCore callback | OIDC app (outbound User Fed) / Custom Auth Server / Redirect URI (AgentCore) |
| **AWS** | A1 external stack USER_FEDERATION + SAP knobs + `/auth/callback` | External IdP discovery / Client callback URL |
| **AWS** | A2 AgentCore outbound provider — real `discoveryUrl` (IdP `.well-known`) | AgentCore — OIDC provider (Entra/Okta) |
| **AWS** | A3 Gateway User target + Gateway OAuth2 provider (inbound-pool risk) | (deployment-side) |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| **401 from the external runtime** (`iss mismatch`) | Gateway OAuth2 (inbound) provider points at your own pool, not the external stack's (inbound-pool risk) | Point it at the external stack's inbound pool — A3 |
| **No interactive auth URL surfaces** | Agent not reading the tool-result JSON | Relay the auth URL from tool-result JSON to the frontend — A3 |
| **IdP rejects the redirect** | AgentCore callback not registered on the **IdP's OIDC client** (registered on SAP by mistake) | Register the AgentCore callback on the IdP OIDC client — A2, E-Entra/E-Okta |
| **SAP 401** issuer/`aud` mismatch | SOIDC issuer/audience wrong for the IdP token | Fix the SOIDC trust — S2 |
| **SAP: token valid but "no matching user"** (Entra) | Mapping on Entra's opaque `sub` | Map on `preferred_username`/`email` (FP2+) + emit that claim IdP-side — S3/E-Entra |
| **SAP 403** on OData | Mapped SU01 user lacks PFCG for the service, or the service is not SICF-activated | Grant PFCG; activate the SICF node — S3/S4 |
| **`discoveryUrl` regex rejection** creating the provider | You passed a SAP URL — but this flow's provider points at the **IdP**, which has a real `.well-known` | Use the IdP `discoveryUrl` (A2); `authorizationServerMetadata` is only for the SAP-as-authz-server flows (SAP-as-authz-server UF and M2M) |

## Limits

- **Not yet run end to end in this sample.** The S5 acceptance test (STAD attribution to the
  signed-in user) has not been run on the Gateway User-target path.
- **Confirm on your system:** the SOIDC Basis floor; Feature Pack 2+ for the Entra custom claim
  mapping (S3); SOIDC field labels (S2). These are the same as in
  [soidc-entra-obo.md](./soidc-entra-obo.md), which uses the same SOIDC trust.

## References

- [SAP_MCP_USER_FEDERATION.md](../SAP_MCP_USER_FEDERATION.md) — the shared USER_FEDERATION contract: User target and the two callback URLs (understand first)
- [soidc-entra-obo.md](./soidc-entra-obo.md) — OBO / ON_BEHALF_OF_TOKEN_EXCHANGE; the same SOIDC trust + STRUST + `sub`→SU01 mapping (S2/S3/S4) this doc reuses, minus the interactive login
- [uf-saml.md](./uf-saml.md) — sibling USER_FEDERATION (SAML): SAP as a SAML 2.0 service provider with its own OAuth server
- [uf-oauth2-sap.md](./uf-oauth2-sap.md) — sibling USER_FEDERATION with SAP as its own OAuth authorization server (AWS Pattern 1: no IdP, SAP issues the per-user token)
- [m2m-oauth2-sap.md](./m2m-oauth2-sap.md) — sibling M2M; the `authorizationServerMetadata` vs `discoveryUrl` contrast (A2)
- [SAP_MCP_SAME_SUB_FEDERATION.md](../SAP_MCP_SAME_SUB_FEDERATION.md) — email federation through SAP Cloud Identity Services (IAS); same-sub trust is not transitive
- [SAP_SYSTEM_CONFIGURATION.md](../SAP_SYSTEM_CONFIGURATION.md) — SU01 user + PFCG + SICF base
- [AWS SAP-MCP — Identity and Authentication](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/identity-and-authentication.html) — scenario table row *"External IdP with OIDC | User Federation | OIDC | Entra ID | SAP OIDC trust"*
- [AWS SAP-MCP — Configuration Reference](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/configuration-reference.html) — env vars, cross-validation rule #3
