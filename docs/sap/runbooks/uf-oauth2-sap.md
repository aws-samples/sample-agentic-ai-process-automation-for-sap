<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# USER_FEDERATION with SAP as the OAuth Authorization Server — Operator Runbook

Each person signs in to SAP itself, and the agent calls SAP as that
person — no Entra, Okta or other IdP in between.

> AWS documents this as [User Federation Pattern 1](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/getting-started.html#user-federation-outbound-prereqs).
> **Status.** The USER_FEDERATION outbound is `status: stub` in `auth-profiles.yaml`
> (`user-federation: { ..., status: stub, blocked_by: upstream }`). The wiring exists in this
> repository, but this sample has not yet run it end to end, and the deploy prints a notice
> saying so.

**Before you start.** Programmatic or agent access to SAP can have licensing implications (for
example, SAP Digital Access). Review with your SAP account team.

**Audience:** an SAP admin **+** an AWS operator. There is no IdP admin on this flow. SAP labels
that could not be checked against a rendered SAP page say *confirm on your system*.

## What you get

- **Per-user SAP identity.** The human signs in on SAP's own OAuth authorize page, and SAP issues a
  token for that human's SU01 user. OData calls run with that user's PFCG authorizations.
- **No external IdP.** SAP is the authorization server. There is no SOIDC trust, no SAML trusted
  provider and no claim-to-SU01 mapping to maintain.
- **Not SSO.** With Cognito inbound the human signs in twice: once to the app, once to SAP.

The interactive mechanics — the auth URL returned through the Gateway and the two callback URLs —
are shared with every USER_FEDERATION flow and live in
[SAP_MCP_USER_FEDERATION.md](../SAP_MCP_USER_FEDERATION.md).

---

## SAP-side steps (SAP admin)

AWS lists this pattern's prerequisites as *"Same as M2M Pattern 1 prerequisites, plus"* one
redirect URI. S1–S3 are that list.

### S1. Create the SOAUTH2 OAuth 2.0 client (authorization code)

SAP GUI transaction **SOAUTH2**, per SAP's
[OAuth client configuration](https://help.sap.com/docs/ABAP_PLATFORM_NEW/fd0fc52fd22b45f29d274a7f8236e768/cdb122d5b0784c77bf1bcce17f730e74.html).
It is the same kind of client as [m2m-oauth2-sap.md](./m2m-oauth2-sap.md) S2, with the
**authorization-code** grant instead of client-credentials. SAP issues each token for the person
who signed in, not for the client's own user. Field labels vary by release — confirm on your
system.

- **The client is an SU01 user.** The OAuth client ID is an SU01 user of type **System**, and its
  password is the client secret. Record both; they become the `{clientId, clientSecret}` secret
  (A1). Rotate the secret as you would any technical-user password, and update the secret when you
  do.
- **Enable OAuth per service first.** Each OData service must have OAuth enabled in transaction
  **/IWFND/MAINT_SERVICE** before its scope ID (`<SERVICE>_0001`) exists.
- **Scopes** are those scope IDs, derived from the service name, for example
  `API_SALES_ORDER_SRV_0001` — see [m2m-oauth2-sap.md](./m2m-oauth2-sap.md) S3.
- The endpoints the AWS side needs are SAP's `/sap/bc/sec/oauth2/authorize` and
  `/sap/bc/sec/oauth2/token` on the same host — confirm on your system that those SICF nodes are
  active.

### S2. Register the AgentCore callback URL as the client's redirect URI

AWS: *"The AgentCore callback URL must be registered with SAP as a redirect URI in the OAuth2 client
configuration. This URL is auto-generated during deployment."* Take it from the outbound credential
provider after A2 and add it to the S1 client. Do not register `MCP_SERVER_APP_CALLBACK_URL` here —
see [the two callback URLs](../SAP_MCP_USER_FEDERATION.md#the-two-callback-urls-do-not-conflate-them).

### S3. Private SAP only: reach it over a private endpoint

If SAP is inside your VPC with no public exposure, AgentCore Identity cannot reach its authorize and
token endpoints. Configure a private endpoint on the outbound OAuth credential provider using
Amazon VPC Lattice (managed or self-managed) — see AWS
[Connect to private identity providers](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/identity-private-idp.html).

### S4. One SU01 user + PFCG roles per human

Every person who signs in needs their own SU01 dialog user with the PFCG roles for the OData
services in S1's scopes. Base OData connectivity is [SAP_SETUP.md](../SAP_SETUP.md).

### S5. SAP's HTTPS server certificate

In this pattern SAP calls no IdP, so there is no outbound trust to import on the SAP side. What
matters is that AgentCore Identity trusts SAP's HTTPS server certificate when it calls the
authorize and token endpoints: serve them with a certificate from a publicly trusted CA, or reach
SAP through the private endpoint in S3. The server certificate is managed in transaction
**STRUST** (SSL server PSE); restarting ICM after a change drops the system's open HTTP
connections, so schedule it.

### S6. Smoke-test SAP's OAuth server in isolation

Open SAP's `/authorize` in a browser with the S1 client id, sign in as a test SU01 user, and expect
a code back at the redirect URI; exchange it at `/token`. Then call one OData service with the
token, as in [m2m-oauth2-sap.md](./m2m-oauth2-sap.md) S6. A 401 from OData is most likely the
client, its secret or its scopes — there is no trust to misconfigure.

---

## AWS / AgentCore-side steps (AWS operator)

The external AWS-for-SAP MCP stack owns the runtime env vars and the outbound provider; this sample
mints the User Gateway target. See [SAP_MCP_USER_FEDERATION.md](../SAP_MCP_USER_FEDERATION.md).

### A1. Deploy the external stack with USER_FEDERATION

- `MCP_SERVER_SAP_OAUTH_FLOW=USER_FEDERATION`
- `MCP_SERVER_SAP_BASE_URL=https://<sap-host>/sap/opu/odata/sap/`
- `MCP_SERVER_SAP_OAUTH_SCOPES=<service-name(s)>` — the S1 scopes
- `MCP_SERVER_SAP_OAUTH_PROVIDER=<provider-name>` — the A2 provider (note the `SAP_` infix)
- `MCP_SERVER_APP_CALLBACK_URL=https://<frontend-domain>/auth/callback` — must end in `/callback`
  or `/oauthcallback`
- Secret: `{clientId, clientSecret}` of the S1 client
- Keep `MCP_SERVER_WRITE_ENABLED=false` until you have reviewed the SAP API Policy (see the
  [README](../../../README.md)). This sample has no per-write approval step. On
  this Gateway path, the Cedar policies permit `odata_create`, `odata_update` and
  `odata_function_import` only for the finance, procurement and admin role tags and forbid
  `odata_delete`; the default `cedar_enforcement_mode: LOG_ONLY` only logs those decisions, so set
  `ENFORCE` for them to block.

### A2. Create the AgentCore Identity OAuth2 credential provider

`aws bedrock-agentcore-control create-oauth2-credential-provider` with the S1 client id and secret,
and `oauthDiscovery.authorizationServerMetadata` (S1's paths — confirm on your system):

| Field | Value |
|---|---|
| `authorizationEndpoint` | `https://<sap-host>/sap/bc/sec/oauth2/authorize` |
| `tokenEndpoint` | `https://<sap-host>/sap/bc/sec/oauth2/token` |
| `issuer` | the SAP token URL origin |

Not `discoveryUrl` — a SAP token URL is not a `.well-known` document
([SAP_MCP_INTEGRATION.md troubleshooting](../SAP_MCP_INTEGRATION.md#troubleshooting)). The
provider's callback URL is the one S2 registers.

### A3. Set the auth profile and the external stack

In `cdk/config.yaml` set `auth_profile: cognito-userfed-ias`, and turn on the SAP MCP integration
with `sap_mcp.enabled: true` and its `external_stack` block (the external stack's name, Region and
inbound settings — see the commented `sap_mcp:` block in `cdk/config.yaml.example`). Then run
`python3 launch.py deploy`. `cognito-userfed-ias` is
this release's Cognito-inbound USER_FEDERATION profile; the `-ias` suffix names one SAP-side trust,
but nothing in its wiring depends on IAS. The deploy mints a User Gateway target with
`credentialProviderType: OAUTH`; point its Gateway OAuth2 provider at the **external** stack's
inbound pool, or the runtime 401s
([SAP_MCP_USER_FEDERATION.md troubleshooting](../SAP_MCP_USER_FEDERATION.md#troubleshooting)).

---

## Checklist

| Side | Step |
|---|---|
| **SAP** | S1 SOAUTH2 authorization-code client, scopes = service scope IDs |
| **SAP** | S2 AgentCore callback URL registered as the client's redirect URI |
| **SAP / AWS** | S3 VPC Lattice private endpoint, if SAP is private |
| **SAP** | S4 SU01 user + PFCG roles per human |
| **SAP** | S5 SAP's HTTPS server certificate trusted by AgentCore Identity |
| **SAP** | S6 authorize → code → token in isolation |
| **AWS** | A1 external stack with `USER_FEDERATION` and the SAP knobs |
| **AWS** | A2 credential provider with `authorizationServerMetadata` |
| **AWS** | A3 `cognito-userfed-ias`, `sap_mcp.enabled` + `external_stack`, external inbound pool |

---

## Limits

- **Interactive consent per user.** Not for unattended runs.
- **Scope is the client's OData services.** A token reaches only the services named in S1's scopes.
- **Nothing ties the consenting SAP user to the signed-in app user.** Whoever signs in at SAP's
  authorize page is who the agent acts as. Decide whether your audit needs that link.

## Troubleshooting

Shared symptoms — the `discoveryUrl` rejection, a refused redirect, a 401 from the runtime — are in
[SAP_MCP_USER_FEDERATION.md troubleshooting](../SAP_MCP_USER_FEDERATION.md#troubleshooting).

| Symptom | Likely cause | Fix |
|---|---|---|
| **`redirect_uri` mismatch at SAP** | The AgentCore callback URL is not registered on the SOAUTH2 client | Register it — S2 |

## References

- [AWS SAP-MCP — Getting Started, User Federation Pattern 1](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/getting-started.html#user-federation-outbound-prereqs) — this pattern's prerequisites
- [AWS SAP-MCP — Identity and Authentication](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/identity-and-authentication.html#auth-user-federation) — how User Federation works, the two callback URLs
- [m2m-oauth2-sap.md](./m2m-oauth2-sap.md) — M2M Pattern 1, whose prerequisites this reuses
- [uf-saml.md](./uf-saml.md) — User Federation Pattern 2: SAP as authorization server + a SAML IdP
- [uf-oidc.md](./uf-oidc.md) — User Federation Pattern 3: an external OIDC IdP
- [SAP_MCP_USER_FEDERATION.md](../SAP_MCP_USER_FEDERATION.md) — the shared USER_FEDERATION mechanics
