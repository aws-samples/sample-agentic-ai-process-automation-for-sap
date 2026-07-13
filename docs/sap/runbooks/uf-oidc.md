<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# USER_FEDERATION (OIDC) — Operator Runbook (User Federation, external OIDC IdP; Entra or Okta)

> **PREVIEW — not yet deployable.** The USER_FEDERATION outbound flow is a preview design: the
> topology is modeled and validated, but its IaC module is not built yet. Reference design for the
> roadmap, not a ready-to-run procedure.

> **STATUS.** USER_FEDERATION (OIDC) with Entra or Okta is the **base interactive per-user**
> USER_FEDERATION case, and the one UF variant **unambiguously supported** by the AWS-for-SAP MCP
> scenario table: *"External IdP with OIDC | User Federation | OIDC | Entra ID | SAP OIDC trust"*
> ([identity-and-authentication](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/identity-and-authentication.html)).
> The human does a 3-legged OIDC login at Entra/Okta; SAP validates the resulting OIDC token via a
> **SOIDC** trust and runs OData as that human. But this flow is **preview / not built** and has **not
> been run end-to-end here** — reference design pending your own validation. SAP-side facts that could
> not be re-confirmed against a rendered primary SAP doc (help.sap.com is client-side-rendered) are
> marked **UNVERIFIED**.

**This is the base UF case; the siblings are deltas from it.** USER_FEDERATION (SAML)
([uf-saml.md](./uf-saml.md)) swaps the OIDC IdP for a **SAML** IdP with SAP as the SAML SP (OAuth
bridge); USER_FEDERATION with SAP as its own OAuth authorization server
([uf-oauth2-sap.md](./uf-oauth2-sap.md)) makes **SAP itself** the OAuth authorization server; OBO /
ON_BEHALF_OF_TOKEN_EXCHANGE ([soidc-entra-obo.md](./soidc-entra-obo.md)) uses the **same SOIDC trust**
but a non-interactive server-side exchange (no second login). If you can, prefer **Okta** — Okta puts
email in `sub`, so the SAP mapping is trivial (see S3); Entra's opaque `sub` needs extra work.

**Audience:** an SAP admin **+** an Entra admin (Entra path) or Okta admin (Okta path) **+** an AWS
operator. Each side owns a lane below; the checklist maps every step to its operator.

This runbook is a **variant-delta on the base USER_FEDERATION case** — understand the shipped
USER_FEDERATION contract first (the User Gateway target and the two callback URLs). The SAP-side
**SOIDC trust + STRUST + the `sub`→SU01 mapping** are identical to the OBO flow
([soidc-entra-obo.md](./soidc-entra-obo.md)) S2/S3/S4 — this doc **cross-links, not duplicates** them;
the only delta from OBO is that the login is **interactive 3-legged** (User Gateway target) rather
than a server-side OBO exchange.

## When to pick USER_FEDERATION (OIDC) (vs the other UF variants and OBO)

| | **USER_FEDERATION (OIDC), this doc** | **USER_FEDERATION (SAML)** | **USER_FEDERATION (SAP as authz server)** | **OBO / ON_BEHALF_OF_TOKEN_EXCHANGE** |
|---|---|---|---|---|
| Who is the OAuth authz server | the **external OIDC IdP** (Entra/Okta) | SAP (redirects to a SAML IdP) | **SAP itself** | the Entra outbound app |
| What SAP trusts | **SOIDC** (OIDC provider) | **SAML2** trusted provider | SAP-native + (a SAML/OIDC IdP) | **SOIDC**, direct |
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

The SOIDC trust, STRUST chain, and `sub`→SU01 mapping are **identical to the OBO flow** — this lane
cross-links [soidc-entra-obo.md](./soidc-entra-obo.md) rather than repeating them. Base OData
connectivity and the human's SU01 user are covered by your SAP system configuration (SU01 user +
PFCG + SICF base).

> **SAP-side trust facts below reflect a working Okta→SAP integration, but the AWS topology differs.**
> The **SAP-side** trust facts below (SOIDC tcode + fields, STRUST CA import, the `/oauth2/default`
> issuer trap, the `cmRc=20` reachability error, the SOIDC token trace) come from a real Okta
> S/4HANA integration run end-to-end. **Caveat — different AWS topology:** that integration used a
> *bespoke* MCP server on AgentCore Runtime with the Okta token passed **as a tool parameter** and
> **no Gateway** — so it validates the *SAP trust* (SOIDC/STRUST/mapping, which is topology-agnostic)
> but does **not** validate the Gateway User-target path. Items still specific to this topology, and
> Entra's opaque-`sub` requirement (that integration used Okta), remain **UNVERIFIED** as noted.

### S1. STRUST — import the IdP's TLS chain — **confirmed**

Import the OIDC IdP's full token-endpoint TLS chain (leaf + intermediates + root) into the SAP
**STRUST** **SSL Client (Standard) PSE** and restart ICM — the exact discipline in
[soidc-entra-obo.md S2](./soidc-entra-obo.md#s2-import-the-entra-token-endpoint-tls-chain-into-strust)
(root-only imports are the classic silent TLS failure). For Okta the host is your Okta org /
custom-auth-server domain instead of `login.microsoftonline.com`.

Confirmed prerequisites (Okta): **SAP ICM must have HTTPS enabled**; the IdP's **root CA** must
be imported into the SSL Client PSE; and SAP must reach the IdP endpoints **outbound** to download
JWKS keys (S2). Confirmed failure mode: if SAP cannot reach the IdP, JWKS download fails with the RFC
error **`ThSAPOCMINIT, CM_PRODUCT_SPECIFIC_ERROR cmRc=20`** — treat `cmRc=20` as "SAP→IdP network/
proxy/TLS blocked," not a token problem.

### S2. SOIDC — create the OIDC provider trust for the IdP — tcode **confirmed**

SAP GUI transaction **SOIDC** — **confirmed** as the correct transaction by the Okta integration.
Register Entra / Okta as an OIDC provider. Fields used (Okta):
- **Issuer** = the IdP issuer, e.g. `https://<okta-domain>/oauth2/default` (see the `/oauth2/default`
  trap in S2a below — the issuer **must** match what the token actually carries and what AgentCore's
  authorizer validates).
- **JWKS download URL** = `https://<okta-domain>/oauth2/default/v1/keys` — SAP downloads the signing
  keys from here (requires outbound reachability + the TLS chain in STRUST S1).

This is the **same** SOIDC registration as [soidc-entra-obo.md S3](./soidc-entra-obo.md#s3-create-the-oidc-provider-trust-for-entra-in-soidc--field-labels-unverified)
— the only difference here is the audience is the **interactive** OIDC client (S-IdP), not an OBO
outbound app. Exact remaining field labels beyond issuer/JWKS are still worth confirming in your live
transaction, but the transaction + the issuer/JWKS/mapping fields are **field-confirmed**.

#### S2a. The `/oauth2/default` issuer trap — **confirmed failure mode**

Okta exposes two authorization servers with **different issuers**, and picking the wrong one 401s:
- **Org server** `/oauth2/v1/` → issuer `https://<okta-domain>` — does **NOT** match SAP/AgentCore config.
- **Custom (default) server** `/oauth2/default/v1/` → issuer `https://<okta-domain>/oauth2/default` — the one that matches.

Use the **`/oauth2/default`** endpoints everywhere (Okta app authorize/token URLs, SAP SOIDC issuer,
AgentCore `discoveryUrl`) so all three agree. Decode the `access_token` and check its `iss` claim if
in doubt. (This is the concrete realization of the general Okta org-vs-custom-authserver risk.)

### S3. Map the OIDC `sub`/claim → SU01 business user — Okta path **confirmed**, Entra trap UNVERIFIED

SAP GUI transaction **SOIDC** (claim mapping) + **SU01**. The join key differs by IdP — this is the
one place the Entra and Okta paths diverge. **Confirmed detail:** SOIDC's **User Mapping Claim** =
`sub` and its **User Mapping Mechanism** = **E-Mail** — i.e. SOIDC reads the `sub` claim and resolves
the SAP user by matching **email**. (More precise than "map on sub/email": the *claim* is `sub`, the
*resolution mechanism* is E-Mail.)

- **Okta (simpler, confirmed):** Okta puts the user's **email in `sub`**, so the `sub` claim +
  E-Mail mapping mechanism resolves the SU01 user directly when the SU01 email matches — **confirmed
  working** in the Okta integration.
- **Entra (the trap, still UNVERIFIED):** Entra emits an **opaque, app-pairwise `sub`** that
  will **not** carry email — so the `sub`+E-Mail mechanism above won't resolve. Configure a **custom
  claim mapping** on `preferred_username`/UPN or `email`, which requires **SOIDC Feature Pack 2+**
  (**UNVERIFIED** — the confirmed integration used Okta, not Entra). This is the identical trap
  documented in
  [soidc-entra-obo.md S4](./soidc-entra-obo.md#s4-map-the-entra-sub--su01-business-user-via-a-custom-claim-mapping--unverified)
  (the OBO flow hits it too). Ensure the IdP emits that stable claim (set IdP-side, S-IdP).

Each target SU01 user must exist with the matching identifier and hold the PFCG OData
authorizations for the services the agent calls, or SAP returns **403**. Email-join principle:
unmapped users fail closed — never a silent service-account fallback.

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
- **Audit proof (the acceptance test):** SM20 / RSAU_* must show the action under the **mapped human
  SU01 user**, not a service account. **UNVERIFIED end-to-end** (this flow not run against the
  Gateway topology here; the Okta integration proved the SAP trust on a bespoke-MCP topology).
- **SOIDC token trace (confirmed debug tool):** in transaction **SOIDC** you can **trace/analyze a
  token** — paste a captured `access_token` and SOIDC validates it, showing a green result or an
  error with a description. Use this to localize a 401 to the SAP side (issuer/audience/`sub` mapping
  vs. JWKS reachability) before blaming AgentCore.

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
(`preferred_username`/`email`/`upn`) the SAP **S3** mapping binds to (Entra's default `sub` is opaque
— the trap). Grant the delegated OIDC scopes (`openid`/`profile`/`email`) admin consent.

### E-Okta. Okta OIDC app + custom authorization server

Okta admin → **Applications → Create App Integration → OIDC → Web Application**; set the **Sign-in
redirect URI** = the AgentCore provider callback (A2, after deploy). Use a **Custom Authorization
Server** (Security → API) if you need custom scopes/claims. Okta natively puts **email** in `sub`
(why Okta's SAP mapping is trivial — S3). Record the `{clientId, clientSecret}` for the external
stack's secret. The IdP `.well-known` discovery URL (org or custom-auth-server) is what the AgentCore
provider (A2) and SAP SOIDC (S2) both point at.

> **Okta and Entra are the same mechanism** — only the `sub` shape and claim-mapping effort
> differ (S3). AWS documents Entra explicitly; the OIDC pattern is IdP-agnostic, so Okta is
> well-supported here (unlike the SAML case, where AWS names only Entra).

---

## AWS / AgentCore-side steps (AWS operator)

> The deployment does **not** provision the external AWS-for-SAP MCP stack, its inbound pool, or its
> OAuth provider — those are owned externally. Your IaC mints the **Gateway User target + a Gateway
> OAuth2 credential provider** (the UF path is the **Gateway** path — **never** direct-to-MCP; that is
> OBO-only, [OBO / ON_BEHALF_OF_TOKEN_EXCHANGE](./soidc-entra-obo.md)).

### A1. Set the USER_FEDERATION flow + SAP knobs on the external stack — **all**

External stack env vars (CFN params; editable via Bedrock AgentCore console → Runtime → Update
Hosting → Advanced Configurations). **Your IaC does NOT set these; the SAP OAuth knobs live on the
external stack:**

- `MCP_SERVER_SAP_OAUTH_FLOW=USER_FEDERATION`
- `MCP_SERVER_SAP_BASE_URL=https://<sap-host>/sap/opu/odata/sap/`
- `MCP_SERVER_SAP_OAUTH_SCOPES=<sap-service-name(s)>` e.g. `ZAPI_SALES_ORDER_SRV_0001` — **SAP OData
  service names, NOT OAuth scope URIs**; a wrong/foreign scope → **HTTP 403** (each service must be
  SICF-activated S4 and PFCG-authorized S3).
- `MCP_SERVER_APP_CALLBACK_URL=https://<frontend-domain>/auth/callback` — required for
  USER_FEDERATION; the path **must end in `/callback` or `/oauthcallback`**.
- Secret `{clientId, clientSecret}` = the **IdP OIDC client** (S-IdP) — the IdP is the authz server,
  so these are the IdP's client credentials, **not** a SAP SOAUTH2 client.
- Start read-only (`MCP_SERVER_WRITE_ENABLED=false`); enable writes there when ready — Gateway Cedar
  is defense-in-depth on top.

> **Env-var name:** use `MCP_SERVER_SAP_OAUTH_PROVIDER` (with the `SAP_` infix) — confirm against the
> AWS-for-SAP MCP container's env-var contract for your build.

### A2. Create the AgentCore Identity OAuth2 provider for the IdP — real `discoveryUrl` (the OIDC delta)

`aws bedrock-agentcore-control create-oauth2-credential-provider` (or Console → custom provider),
`clientId`/`clientSecret` = the IdP OIDC client (A1's secret). Because the **external OIDC IdP** is
the authorization server, use a **real `oauthDiscovery.discoveryUrl`** = the IdP's
`.well-known/openid-configuration` — an OIDC IdP **does** publish one. This is the key contrast with
[the M2M SAP-facing provider](./m2m-oauth2-sap.md#a2-create-the-agentcore-identity-outbound-oauth2-credential-provider--all),
which must use `authorizationServerMetadata` because a SAP token URL is not a `.well-known` document.
For the built-in providers, Entra → **MicrosoftOauth2**, Okta → a Custom OIDC provider. After deploy,
register the provider's returned **callbackUrl** as a redirect URI on the **IdP's OIDC client**
(E-Entra/E-Okta) — **not** on SAP.

> **The two callback URLs — do NOT conflate.** The **AgentCore callback URL** (auto-generated) →
> the **IdP OIDC client**'s redirect-URI allowlist; `MCP_SERVER_APP_CALLBACK_URL` (`/auth/callback`)
> → the frontend completion route. These are two distinct URLs serving two distinct purposes; wiring
> one where the other belongs is the most common USER_FEDERATION setup error.

### A3. Gateway User target — NOT direct-to-MCP — **all**

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
| **SAP** | S2 SOIDC OIDC provider trust for the IdP (**UNVERIFIED** labels) | OIDC provider (Entra) SOIDC / (Okta) |
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
| **IdP rejects the redirect** | AgentCore callback not registered on the **IdP's OIDC client** (registered on SAP by mistake) | Register the AgentCore callback on the IdP OIDC client — A2/E-IdP |
| **SAP 401** issuer/`aud` mismatch | SOIDC issuer/audience wrong for the IdP token | Fix the SOIDC trust — S2 |
| **SAP: token valid but "no matching user"** (Entra) | Mapping on Entra's opaque `sub` | Map on `preferred_username`/`email` (FP2+) + emit that claim IdP-side — S3/E-Entra |
| **SAP 403** on OData | Wrong scope (not a service name), or mapped SU01 user lacks PFCG | Set scopes to OData service names; grant PFCG — A1/S3 |
| **`discoveryUrl` regex rejection** creating the provider | You passed a SAP URL — but this flow's provider points at the **IdP**, which has a real `.well-known` | Use the IdP `discoveryUrl` (A2); `authorizationServerMetadata` is only for the SAP-as-authz-server flows (SAP-as-authz-server UF and M2M) |

## Open items (carried, not blocking — reference design)

- **Not built / not run end-to-end.** This flow is preview and not built; no live OIDC SSO or
  real-user SAP audit proof exists here (S5 acceptance test). The whole SAP-MCP integration is
  reference design.
- **UNVERIFIED against primary SAP docs:** SOIDC Basis 7.56 SP1+ floor; Feature Pack 2+ for the Entra
  opaque-`sub` custom claim mapping (S3); exact SOIDC field labels (S2). All inherited from
  [soidc-entra-obo.md](./soidc-entra-obo.md) (same SOIDC trust) — confirm on your release.
- **UNVERIFIED against AWS/deployed stack:** the `SAP_` infix the deployed container reads (A1); the
  AgentCore callbackUrl format; whether `x-audit-*` survives the container to SAP.

## References

- The base USER_FEDERATION contract — User target and the two callback URLs (understand first)
- [soidc-entra-obo.md](./soidc-entra-obo.md) — OBO / ON_BEHALF_OF_TOKEN_EXCHANGE; the **identical** SOIDC trust + STRUST + `sub`→SU01 mapping (S2/S3/S4) this doc reuses, minus the interactive login
- [uf-saml.md](./uf-saml.md) — sibling USER_FEDERATION (SAML): SAML IdP instead of OIDC (SAP as SAML SP, OAuth bridge)
- [uf-oauth2-sap.md](./uf-oauth2-sap.md) — sibling USER_FEDERATION with SAP as its own OAuth authz server ("SAP-direct no-IdP" is refuted)
- [m2m-oauth2-sap.md](./m2m-oauth2-sap.md) — sibling M2M; the `authorizationServerMetadata` vs `discoveryUrl` contrast (A2)
- The email-join user mapping principle — same-sub trust is not transitive
- Your SAP system configuration — SU01 user + PFCG + SICF base
- [AWS SAP-MCP — Identity and Authentication](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/identity-and-authentication.html) — scenario table row *"External IdP with OIDC | User Federation | OIDC | Entra ID | SAP OIDC trust"*
- [AWS SAP-MCP — Configuration Reference](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/configuration-reference.html) — env vars, cross-validation rule #3
