<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Same-Sub Identity Federation for SAP MCP OBO — Setup Runbook

Lets a user-initiated SAP MCP `USER_FEDERATION` call reach SAP **as the real human
user**, by federating the product's user-facing Cognito pool into SAP Cloud Identity
Services (IAS). The join key is `email`. SAP's native per-user audit + PFCG
authorizations then apply.

> **Not to be confused with ADR-008 `principal-propagation`.** Both mechanisms propagate the
> real user's identity to SAP, but they are different: ADR-008 `principal-propagation` uses
> X.509 client certificates (ACM Private CA) on the existing Lambda tool path. *Same-sub
> federation* here is email-based OIDC (Cognito → IAS), relevant only to the SAP MCP
> `USER_FEDERATION` outbound flow. They are not interchangeable.

It is token/claim-based federation — no CA to operate.

## What our CDK builds vs. what you configure

| Side | Owner | What |
|---|---|---|
| Cognito IAS-facing app client + discovery/client-id outputs | **This CDK** (when `sap.identity.federation.enabled`) | `authorization_code` client, scopes `openid email profile`, IAS redirect URI registered |
| IAS corporate IdP + identity mapping + S/4 OAuth client | **Customer SAP admin** (your tenant) | Register Cognito as OIDC corporate IdP; map `email`; register AgentCore callback |

The **SAP MCP inbound pool** (the external SAP MCP stack's machine pool) is **never
touched** — federation is anchored on the user-facing pool only.

> **Why the user-facing pool and not the MCP pool?** The two pools serve unrelated gates. The
> MCP inbound pool authorizes the Gateway→Runtime call (machine-to-machine; no humans in it, IAS
> never sees it). This federation is about propagating the *human's* identity to SAP, and the
> humans — with verified `email` — live in the user-facing pool. The identity does **not** relay
> `user-facing pool → MCP pool → IAS`; IAS trusts the user-facing pool **directly**, joining on
> `email`. See [SAP_MCP_USER_FEDERATION.md → Which Cognito? Two gates, not a relay](./SAP_MCP_USER_FEDERATION.md#which-cognito-two-gates-not-a-relay).

## Config

```yaml
sap:
  identity:
    federation:
      enabled: true
      ias_redirect_uri: "https://<tenant>.accounts.ondemand.com/oauth2/callback"
      mapping_claim: email   # default: email
```

When `enabled`, `ias_redirect_uri` is required and `mapping_claim` defaults to `email`.

## After `cdk deploy`

Collect from the `*-cognito` stack outputs:
- `FederationDiscoveryUrl` — the Cognito OIDC discovery URL.
- `FederationClientId` — the app client id IAS will consume.

Fetch the client secret out-of-band (Cognito does not store it in Secrets Manager):

```bash
aws cognito-idp describe-user-pool-client \
  --user-pool-id <userPoolId> \
  --client-id <FederationClientId> \
  --query 'UserPoolClient.ClientSecret' --output text
```

## SAP / IAS-side steps (customer SAP admin)

A. **Register Cognito as a corporate IdP in IAS** — IAS admin console → Identity
   Providers → Corporate Identity Providers → Create → OpenID Connect. Point it at the
   `FederationDiscoveryUrl`; use `FederationClientId` + the fetched secret. IAS returns
   its callback/ACS URL — this is the value you put in `ias_redirect_uri`. This URL is
   deterministic per tenant (`https://<tenant>.accounts.ondemand.com/oauth2/callback`)
   and is shown in the IAS registration form before you save, so you can set
   `ias_redirect_uri` and run `cdk deploy` first — no chicken-and-egg.
B. **Conditional authentication** — configure IAS to delegate authentication for the
   application to the Cognito corporate IdP, so users land at Cognito (not the IAS form).
C. **Identity mapping** — map the incoming Cognito `email` claim to the IAS user
   attribute; ensure each IAS user links to the corresponding S/4 business user (SU01
   where `email` matches).
D. **S/4 OAuth client** — the client driving `sap_oauth.authorize_url`/`token_url`.
   List the OData service scopes the agent calls and **register the AgentCore callback
   URL as an allowed redirect URI** (common gotcha). On RISE this client's auth routes
   through IAS by default.
E. **Token lifetime** — tune the OAuth client refresh-token TTL (shorter = smaller
   blast radius).

## Cognito-side steps (product / CDK)

A. **IAS-facing OIDC app client** — created automatically when `federation.enabled`
   (the `*-ias-federation-client`); the `ias_redirect_uri` is registered as an allowed
   callback.
B. **Verified `email` on every user** — the join key. Set `email_verified: true` when
   provisioning via admin/SCIM. `email` is canonical; never change the claim.
C. **Public OIDC endpoints reachable by IAS** — discovery / `/authorize` / `/token` /
   JWKS (already true for the pool domain).

## Security control-point checklist

- [ ] IdP trust pins the expected issuer + audience (both Cognito→IAS and IAS→S/4).
- [ ] The `email` → SAP-user mapping is strictly 1:1.
- [ ] Inbound Gateway `allowedClients` remains pinned (already enforced).
- [ ] Redirect-URI allowlists are explicit in **both** directions (Cognito↔IAS, AgentCore↔S/4).
- [ ] S/4 OAuth client refresh-token TTL is bounded.
- [ ] **Unmapped users fail closed at IAS** — never fall back to a service account.

## Negative path

A user with no matching IAS/S/4 mapping must be **rejected at IAS** and surfaced to the
product as a specific "your SAP user isn't provisioned" message — not a generic failure
and never a silent service-account fallback.

## Out of scope

- ADR-008 `principal-propagation` (X.509) — separate mechanism, legacy Lambda path only.
- On-prem / no-IAS SOIDC federation — same `email` join principle, different SAP-side
  plumbing; tracked for a future spec.
