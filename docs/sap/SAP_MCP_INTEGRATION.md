<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# AWS for SAP MCP Server Integration

> **Reference design.** This integration has been verified against current AWS/SAP docs and
> the AWS for SAP MCP Server, but has NOT been run end-to-end against a production SAP system
> in your environment. Treat it as a reference architecture: validate in your own AWS account
> against your own SAP system before production use.

The agent reaches SAP exclusively through the [AWS for SAP MCP Server](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/introduction.html) — reads, writes, and discovery all go through it. There is no homegrown SAP tool path; this integration **is** the agent's SAP access layer. See [ADR-012](../design-decisions/012-sap-mcp-server-integration.md) for the decision record.

## Choose your path

| You need… | SAP auth flow | Go to |
|---|---|---|
| Machine identity only (autonomous + shared service account) | `BASIC` or `M2M` | **This doc** (deploy model); SAP-side M2M operator steps → [runbooks/m2m-oauth2-sap.md](./runbooks/m2m-oauth2-sap.md) |
| Interactive per-user, **3-legged** login (reach SAP as the signed-in human) | `USER_FEDERATION` | [SAP_MCP_USER_FEDERATION.md](./SAP_MCP_USER_FEDERATION.md) (mechanics); operator runbooks: [uf-saml.md](./runbooks/uf-saml.md) (USER_FEDERATION with a SAML IdP), [uf-oauth2-sap.md](./runbooks/uf-oauth2-sap.md) (USER_FEDERATION with SAP as its own OAuth authorization server) |
| Email-based Cognito→IAS corporate-IdP federation | `USER_FEDERATION` + IAS trust | [SAP_MCP_SAME_SUB_FEDERATION.md](./SAP_MCP_SAME_SUB_FEDERATION.md) |
| Seamless per-user, no second login — server-side **token exchange** (Direct-Entra) | `ON_BEHALF_OF_TOKEN_EXCHANGE` (direct-to-MCP) | [runbooks/soidc-entra-obo.md](./runbooks/soidc-entra-obo.md) |

> **"OBO" is ambiguous — see [TOKEN_MECHANICS.md](./TOKEN_MECHANICS.md).** `USER_FEDERATION`
> (3-legged interactive) and `ON_BEHALF_OF_TOKEN_EXCHANGE` (server-side token exchange) are
> **different** token mechanisms; older text calls both "OBO." Reserve "OBO" for the exchange flow.

> **STATUS.** BASIC, M2M, and USER_FEDERATION are **implemented for external mode**. The
> inbound-auth requirement (the Gateway OAuth2 provider must point at the external stack's
> pool) and the auth-URL surfacing (USER_FEDERATION's interactive auth URL surfaces through
> the Gateway as tool-result JSON) are **verified against current AWS/SAP docs**. The
> remaining gap is SAP-side end-to-end validation — see [SAP_MCP_USER_FEDERATION.md](./SAP_MCP_USER_FEDERATION.md).
> **Nothing has been run end-to-end against a production SAP system yet.**

## Quick facts

- Deployed as a separate CDK stack (`sap-mcp-stack`) that depends on `BackendStack`.
- **Pure adapter to an external stack:** the customer deploys AWS's published SAP MCP
  CloudFormation stack themselves; that stack owns the AgentCore Runtime, the inbound Cognito
  (or Entra) pool, the outbound SAP OAuth provider registration, **and every SAP permission
  knob** (read vs write enablement is set there via the runtime's `MCP_SERVER_*` env vars). Our
  CDK is a thin adapter that attaches a **Gateway MCP target** + a **Gateway OAuth2 credential
  provider** pointed at that external stack.
- **Outbound auth flows:** `BASIC`, `M2M`, `USER_FEDERATION` (3-legged interactive), and
  `ON_BEHALF_OF_TOKEN_EXCHANGE` (server-side exchange) — see
  [TOKEN_MECHANICS.md](./TOKEN_MECHANICS.md) for how they differ. The flow is a CFN parameter on the
  external stack, not something our adapter config selects.
- Config-selectable inbound IdP: `Cognito` (default) or `EntraId` (must match the external
  CFN deploy).
- Which Gateway target variant (Service / User) is minted is **derived from `auth_profile`'s
  outbound axis** (see `auth-profiles.yaml`) — there are no manual `service.enabled` /
  `user.enabled` toggles. Everything SAP-side lives on the external stack.

### Outbound axis → SAP MCP variant

| `auth_profile` outbound axis | SAP MCP target variant |
|---|---|
| `basic` | neither variant (poller basic auth; no SAP MCP target) |
| `m2m-sap` / `m2m-oidc` | Service target (M2M) |
| `user-federation` | User target (USER_FEDERATION) |
| `obo` / `obo-okta` | no Gateway target (`mcp_supported: false` → rejected on the **Gateway** MCP path); instead uses the **direct-to-MCP** OBO path (`obo_direct_mcp: true`) — the agent calls the external MCP directly, no Gateway target. See [runbooks/soidc-entra-obo.md](./runbooks/soidc-entra-obo.md) |

## Two Gateway targets

| Target | Derived from (outbound axis) | SAP identity | Typical use |
|---|---|---|---|
| Service | `m2m-sap` / `m2m-oidc` | machine identity (BASIC/M2M, set on the external stack) | autonomous + user-initiated actions under the shared service account |
| User | `user-federation` | interactive per-user OBO (USER_FEDERATION) | actions that must reach SAP as the signed-in human |

The active variant is chosen by `auth_profile`'s outbound axis (see the mapping table above),
not by a manual flag. The agent picks by tool name, and the Gateway Cedar policies govern
writes regardless of which target is used.

## Deploy model — external (adapter)

The SAP MCP integration is **external-only**: the customer deploys AWS's published SAP MCP
CloudFormation stack themselves, and our CDK is a thin adapter on top of it. The
AWS-published SAP MCP CloudFormation stack owns the AgentCore Runtime, its **inbound
Cognito (or Entra) pool/client/domain**, and the **outbound OAuth provider registration**.
Our CDK creates only the adapter resources:

1. A **Gateway MCP target** pointing at the external stack's invocation URL (`listing_mode`,
   `x-audit-*` allowlist).
2. A **Gateway OAuth2 credential provider** registered in AgentCore Identity, pointing at
   *the external stack's* inbound IdP — its client id + discovery URL (Cognito pool-derived
   `.well-known/openid-configuration`, or the Entra discovery URL). This is what lets our
   Gateway present a Bearer token the external runtime's inbound authorizer accepts. **This
   must point at the external stack's pool, not ours — pointing at our own Cognito
   yields a 401 from the external runtime.**

External-stack outputs are auto-resolved at synth via CloudFormation `describe-stacks`
(`cfn-outputs-resolver.ts`), with per-field overrides in `external_stack`.

```yaml
sap_mcp:
  enabled: true
  external_stack:
    stack_name: sap-mcp-server-prod      # AWS CFN stack to read outputs from
    inbound_auth_provider: Cognito       # Cognito (default) | EntraId — must match the CFN deploy
    # Auto-resolved from the stack's Outputs; override any of these if needed:
    # invocation_url: ""
    inbound_cognito:
      # pool_id / client_id / token_endpoint auto-resolved from Outputs; secret ARN required.
      # Must be the COMPLETE ARN, including the 6-char suffix Secrets Manager appends:
      client_secret_arn: "arn:aws:secretsmanager:us-east-1:ACCT:secret:ext-cognito-XXXX-AbCdEf"
    # EntraId inbound instead of Cognito — supply these and set inbound_auth_provider: EntraId:
    # entra_discovery_url: "https://login.microsoftonline.com/<tenant-id>/v2.0/.well-known/openid-configuration"
    # entra_client_id: "<entra-app-client-id>"
    # entra_client_secret_arn: "arn:aws:secretsmanager:...:secret:entra-XXXX-AbCdEf"
```

> Which target variant is minted (Service vs User) is **derived from `auth_profile`'s outbound
> axis** — `m2m-*` → Service, `user-federation` → User, `basic` → neither — not from a manual
> flag here (see the [Outbound axis → SAP MCP variant](#outbound-axis--sap-mcp-variant) table).

> The SAP auth flow (`BASIC`/`M2M`/`USER_FEDERATION`), the SAP OAuth provider, the OAuth
> scopes (`MCP_SERVER_SAP_OAUTH_SCOPES`), and read/write enablement (`MCP_SERVER_WRITE_ENABLED`
> + the per-op `MCP_SERVER_CREATE/UPDATE/DELETE/FUNCTION_IMPORT_ENABLED` flags) are **all CFN
> parameters / env vars on the external AWS CFN stack** — set them there, not here.

> **`listing_mode`.** `listing_mode` is a CFN parameter on the external stack (`DEFAULT`
> pre-syncs the tool catalog and enables semantic search; `DYNAMIC` forwards `tools/list` at
> invoke time without normalization). Set `DYNAMIC` on the external stack if the SAP MCP tool
> schemas fail the Gateway's `SchemaDefinition` normalization (`$defs`/`$ref` etc.); otherwise
> prefer `DEFAULT` so tools appear in the Gateway's aggregate `tools/list`.

## Env-var contract (external SAP MCP container — reference)

These are the container env vars the **external AWS SAP MCP stack's** container uses (set as
CloudFormation parameters on that stack), per auth flow — provided here as reference. **Our
CDK does NOT set these**; the external stack owns the container. Verified against the live AWS
CFN template (`AwsForSapMcpServerStack.template.json`, fetched 2026-06-04).

| Env var | BASIC | M2M | USER_FEDERATION | Notes |
|---|:---:|:---:|:---:|---|
| `MCP_SERVER_SAP_BASE_URL` | required | required | required | SAP OData base (`.../sap/opu/odata/sap/`) |
| `MCP_SERVER_SAP_OAUTH_FLOW` | `BASIC` | `M2M` | `USER_FEDERATION` | the flow selector |
| `MCP_SERVER_BASIC_AUTH_SECRET_NAME` | required | — | — | Secrets Manager secret name, `{username, password}` |
| `MCP_SERVER_SAP_OAUTH_PROVIDER` | — | required | required | AgentCore Identity provider **name** (the `SAP_` infix is correct — see below) |
| `MCP_SERVER_SAP_OAUTH_SCOPES` | — | required | required | SAP **service names**, e.g. `ZAPI_SALES_ORDER_SRV_0001` |
| `MCP_SERVER_APP_CALLBACK_URL` | — | — | required | client app callback (our frontend `/auth/callback`) |

> **Env-var name — `MCP_SERVER_SAP_OAUTH_PROVIDER` (with the `SAP_` infix).** The AWS docs
> *variable table* says `MCP_SERVER_OAUTH_PROVIDER` (no `SAP_`) — **that is wrong.** The live
> CFN template and the docs' own validation rule use `MCP_SERVER_SAP_OAUTH_PROVIDER`. We use
> the `SAP_` form everywhere.

**Secret formats** (Secrets Manager):

- **BASIC** — `{username, password}` (the existing `{stack_name_base}/sap-credentials` secret).
- **M2M / USER_FEDERATION** — `{clientId, clientSecret}`. The OAuth2 provider Lambda
  (`lambdas/oauth2_provider_cr/index.py`) reads `clientId`/`clientSecret` out of the JSON; a
  plain-string secret is treated as the client secret only (Cognito-style).

## What's deployed (BASIC + M2M)

### Infrastructure

**Owned by the external AWS SAP MCP CloudFormation stack** (the customer deploys this — not our CDK):
- **AgentCore Runtime** (`AWS::BedrockAgentCore::Runtime`) running the SAP MCP container from the AWS-managed ECR (`<aws-account>.dkr.ecr.<region>.amazonaws.com/aws-sap-mcp:<tag>`), its execution role, its inbound Cognito (or Entra) pool, and the outbound SAP OAuth provider registration

**Created by our CDK adapter** (`sap-mcp-stack`):
- **Gateway OAuth2 credential provider** — Custom Resource Lambda that registers a provider in AgentCore's token vault, pointed at the **external stack's** inbound IdP token endpoint + client (so the Bearer token our Gateway presents is accepted by the external runtime's authorizer)
- **Gateway target** on the existing Gateway with `credentialProviderType: OAUTH` + `OauthCredentialProvider` referencing the provider ARN, pointing at the external stack's invocation URL

### Outbound SAP auth

`AuthFlow=BASIC` or `AuthFlow=M2M` — the Service target minted when `auth_profile`'s outbound
axis is `m2m-*`. (USER_FEDERATION → the User target, minted when the outbound axis is
`user-federation` — see the USER_FEDERATION section.)

- **BASIC** — reuses the existing `{stack_name_base}/sap-credentials` Secrets Manager secret
  (`{username, password}`). No OAuth provider needed.
- **M2M** — OAuth 2.0 client credentials to SAP's OAuth server (XSUAA/IAS or equivalent).
  Requires an OAuth2 credential provider registered in AgentCore Identity via the
  `lambdas/oauth2_provider_cr/index.py` Custom Resource. The SAP credentials secret must hold
  `{clientId, clientSecret}`.
  - The SAP-facing provider is configured with AgentCore's
    `oauthDiscovery.authorizationServerMetadata` (explicit `authorizationEndpoint` +
    `tokenEndpoint` + `issuer`), **not** `discoveryUrl`. A SAP token URL is not a
    `.well-known` document, and the `discoveryUrl` field rejects it via a
    `.+/\.well-known/(openid-configuration|oauth-authorization-server)` regex. The `issuer`
    is derived from the token URL origin. The Cognito/Gateway-side providers continue to use
    a real `discoveryUrl`.

### Inbound auth to the Runtime

The AWS CFN stack owns the inbound pool. Our Gateway OAuth2 provider must point at **that**
stack's inbound IdP (its client id + discovery URL), not ours, or the external runtime returns
401. For `inbound_auth_provider: EntraId`, the Gateway provider uses the Entra
discovery URL + client instead. Defense-in-depth: even with the Runtime ARN, you cannot invoke
it without a valid token from the external stack's pool.

### Configuration (cdk/config.yaml)

See the [Deploy model — external (adapter)](#deploy-model--external-adapter) section above for
the full `external_stack` block. A minimal service-account example (the `external_stack` block
is omitted here for brevity — it is required):

```yaml
sap_mcp:
  enabled: true
  external_stack:
    stack_name: sap-mcp-server-prod   # AWS CFN stack to read outputs from
    inbound_auth_provider: Cognito    # Cognito (default) | EntraId
    inbound_cognito:
      client_secret_arn: "arn:aws:secretsmanager:us-east-1:ACCT:secret:ext-cognito-XXXX-AbCdEf"
```

> The Service vs User target variant is derived from `auth_profile`'s outbound axis (`m2m-*` →
> Service, `user-federation` → User), so there are no `service`/`user` enabled flags in this
> block — see the [Outbound axis → SAP MCP variant](#outbound-axis--sap-mcp-variant) table.

> **Where the SAP knobs live.** The auth flow (`MCP_SERVER_SAP_OAUTH_FLOW`), OAuth provider,
> scopes (`MCP_SERVER_SAP_OAUTH_SCOPES`), and read/write enablement
> (`MCP_SERVER_WRITE_ENABLED` + per-op `MCP_SERVER_CREATE/UPDATE/DELETE/FUNCTION_IMPORT_ENABLED`)
> are configured on the **external AWS CFN stack** (its CFN parameters / runtime env vars), per
> the [AWS configuration reference](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/configuration-reference.html).
> Our adapter does not carry them. Start the external runtime read-only and enable writes there
> when ready; the Gateway's Cedar policies are defense-in-depth on top of whatever the external
> stack enables.

### Deployment

```bash
cd cdk
cdk deploy sap-mcp-stack
```

Or deploy everything:

```bash
make deploy-all
```

### Skill wiring

Add the SAP MCP tool names to the relevant skill's `gateway_tools`:

```json
{
  "skill_id": "finance_accruals",
  "gateway_tools": [
    "find_sap_services", "get_metadata",
    "odata_read", "odata_count",
    "odata_create", "odata_update", "odata_function_import",
    "get_case_state", "update_case_state", "send_notification", "search_sap_sops"
  ]
}
```

Grant only what an instruction reaches for. Every name here costs its JSON
schema on every model request, called or not — `get_service_hints` is exposed by
the MCP server but appears in no shipped skill's grants, because no prompt or SOP
names it. See [Optimization 4](../evaluations/INFERENCE_COST_OPTIMIZATION.md#optimization-4-remove-redundant-kb-searches).

The SAP MCP Server exposes reads — `find_sap_services`, `get_metadata`, `get_service_hints`,
`odata_read`, `odata_count` — and writes — `odata_create`, `odata_update`, `odata_delete`,
`odata_function_import` (each surfaced only when the corresponding `MCP_SERVER_*` flag is
enabled on the external stack). These are the agent's only SAP tools; there is no homegrown
SAP tool path. At the Gateway, `odata_delete` is forbidden by Cedar and the role-gated write
permit governs the other writes.

## USER_FEDERATION (3-legged interactive) — implemented for external mode

> **Status.** USER_FEDERATION is implemented for external mode (the Gateway `user` target).
> The interactive auth URL surfaces through the Gateway as tool-result JSON, so the
> frontend-callback model applies (`MCP_SERVER_APP_CALLBACK_URL` → our `/auth/callback`
> route). What remains is SAP-side: IAS trust + a real-user audit proof in your own SAP
> system. Full setup guide: **[SAP_MCP_USER_FEDERATION.md](./SAP_MCP_USER_FEDERATION.md)**.

This supersedes the original Gateway-mediated OBO design. The container references
a pre-created AgentCore Identity provider **by name** and has no "accept arbitrary
pre-exchanged bearer" mode, so interactive per-user identity uses `AuthFlow=USER_FEDERATION`
with AgentCore's own 3-legged callback machinery — not a Gateway-side token exchange. See
[ADR-012 — Update (2026-06-05)](../design-decisions/012-sap-mcp-server-integration.md#update-2026-06-05-hybrid-deploy-model--m2m-implemented-phase-2-mechanism-revised).
`ON_BEHALF_OF_TOKEN_EXCHANGE` is out of scope **for this Gateway-mediated design**. It is,
however, the basis of the **direct-to-MCP** OBO flagship (agent bypasses our Gateway, user's
Entra JWT is the inbound bearer, the runtime drives the server-side exchange) — see
[runbooks/soidc-entra-obo.md](./runbooks/soidc-entra-obo.md).

> **Resolved.** USER_FEDERATION's interactive flow assumes the MCP *client* receives the
> AgentCore-issued auth URL and drives a browser callback. The auth URL surfaces through the
> Gateway as tool-result JSON, so we use the frontend-callback model
> (`MCP_SERVER_APP_CALLBACK_URL` → `/auth/callback`). OBO calls keep flowing through the
> Gateway, so Gateway-level Cedar/audit interception stays intact. The alternative —
> invoking the USER_FEDERATION target directly, bypassing the Gateway and losing Cedar/audit
> — did not materialize.

### Configuration

The User (USER_FEDERATION) Gateway target is minted automatically when `auth_profile`'s
outbound axis is `user-federation` — there is no `sap_mcp.user.enabled` flag to set.

The interactive flow itself is configured on the **external AWS CFN stack**:
`MCP_SERVER_SAP_OAUTH_FLOW=USER_FEDERATION`, the SAP OAuth provider
(`authorize_url`/`token_url`), `MCP_SERVER_SAP_OAUTH_SCOPES` (SAP service name[s]), and
`MCP_SERVER_APP_CALLBACK_URL` (which must point at this project's `/auth/callback` frontend
route — the path must end in `/callback` or `/oauthcallback`). The SAP credentials secret on
that stack must hold `{clientId, clientSecret}` (same as M2M).

### Open questions (still relevant for USER_FEDERATION)

These remain open for the implemented interactive `USER_FEDERATION` flow and are tracked in
[SAP_MCP_USER_FEDERATION.md](./SAP_MCP_USER_FEDERATION.md):

1. **IdP trust topology** — per-IdP setup (XSUAA, Entra) vs. a generic pattern.
2. **Audit context propagation** — whether the SAP MCP Server forwards our audit baggage
   (`x-audit-*`) to SAP (the target allowlists them; survival through the container is unverified).
3. **Cedar policies** — should user-federation tools inherit service-account actions, or start minimal (read-only)?
4. **Token caching / revocation** — TTL and role-change propagation latency.

> The original Gateway-mediated OBO design (where the Gateway would call
> `GetResourceOauth2Token` with `ON_BEHALF_OF_TOKEN_EXCHANGE`) is preserved in
> [ADR-012 Change 4](../design-decisions/012-sap-mcp-server-integration.md#change-4--phase-2--obo-mechanism-revised-and-honestly-de-scoped-pending-further-investigation).
> The implemented per-user mechanism for the Gateway path is interactive `USER_FEDERATION`
> (3-legged callback); the direct-to-MCP path uses `ON_BEHALF_OF_TOKEN_EXCHANGE` with the
> agent bypassing the Gateway — see [runbooks/soidc-entra-obo.md](./runbooks/soidc-entra-obo.md).

## Operational notes

### IAM scoping checklist

Our CDK adapter creates only the Gateway OAuth2 provider Lambda and the Gateway target. The
Runtime exec-role grants below are owned by the **external AWS SAP MCP stack** (listed here as
reference for what that stack's role needs):

- Runtime exec role `ecr:BatchGetImage` → `arn:aws:ecr:<region>:<aws-account>:repository/aws-sap-mcp`
- Runtime exec role `secretsmanager:GetSecretValue` → exact SAP secret ARN
- Runtime exec role `bedrock-agentcore:GetWorkloadAccessToken*` → `workload-identity-directory/default/workload-identity/*`
- Runtime exec role (M2M/USER_FEDERATION only) `bedrock-agentcore:GetResourceOauth2Token`, `GetOauth2CredentialProvider` — to be scoped to the provider ARN

Our adapter's grants:

- OAuth2 provider Lambda: `bedrock-agentcore:{Create,Update,Get,Delete}Oauth2CredentialProvider` (token vault `default`), `bedrock-agentcore:{Create,Get}TokenVault`, `secretsmanager:{Create,Put,Describe,Delete}Secret` (scoped to `bedrock-agentcore-identity!default/oauth2/*`)
- The Gateway OAuth2 provider Lambda also reads the **external stack's** inbound client secret (`external_stack.inbound_cognito.client_secret_arn` or `entra_client_secret_arn`)

### Versioning the container image

The SAP MCP container image is owned by the external AWS SAP MCP CloudFormation stack — pin
its tag there (a CFN parameter on that stack), not in this quickstart's config. Do not use
`:latest` in production; pin to a released tag (e.g., `:v1.0.0`).

### Observability

Separate CloudWatch log group per Runtime (`/aws/bedrock-agentcore/runtimes/<runtime-id>`). Recommended dashboard widgets:
- Invocation count (per target) — service vs. user target
- Error rate (per target)
- p50/p95/p99 latency (per target)
- Token usage per agent invocation (via agent metrics)

### Credential rotation

- **BASIC** — rotate `{stack_name_base}/sap-credentials` via `make sync-sap-secret`. No restart needed; SAP MCP fetches fresh on each call.
- **M2M / USER_FEDERATION** — rotate the SAP BTP OAuth client secret: create new client, update credential provider via AWS CLI or console, validate, delete old client. Document in `docs/sap/SAP_SETUP.md`.

### Troubleshooting

**Callback URL rejected: "Callback URL must match the allowed pattern"** — the
USER_FEDERATION app callback path MUST end in `/callback` or `/oauthcallback`. A path like
`/auth/sap-callback` is rejected by the AgentCore validator. Use `/auth/callback` (the
frontend route this project ships).

**Target stuck in `CREATING`** — Gateway is attempting `tools/list` against the Runtime. Check Runtime logs for startup errors. The SAP MCP container needs `MCP_SERVER_SAP_BASE_URL` + a valid auth config to start.

**Target fails with schema validation in `DEFAULT` mode** — the Gateway normalizes tool schemas
when pre-syncing the catalog and may reject one with `$defs`/`$ref`/`oneOf`/`anyOf`. Per ADR-012
this was fixed upstream and the AWS SAP MCP tool schemas sync cleanly in `DEFAULT` (verified
2026-06-05). If you do hit a normalization failure on a future tool, `DYNAMIC` is the escape
hatch — but note DYNAMIC tools won't appear in the Gateway's aggregate `tools/list` (see below),
so prefer `DEFAULT` and file the schema issue upstream.

**401 from Gateway when calling SAP MCP tools** — check that the OAuth2 credential provider is correctly configured. Verify the Cognito machine client ID and secret match what's in the provider. Check the Runtime's `customJwtAuthorizer` allows the machine client ID in its `allowedClients` list.

**401 in `external` (hybrid) mode** — the most common external-mode failure: the
Gateway's OAuth2 provider is pointed at **our** Cognito pool instead of the **external stack's**
inbound pool. The external runtime's inbound authorizer only trusts its own pool's tokens, so a
token from our pool is rejected. The tell-tale error from the runtime is:
`{"error":{"code":-32001,"message":"Claim 'iss' value mismatch with configuration."}}` — the
JWT issuer doesn't match the pool the runtime trusts. Verify `external_stack.inbound_cognito`
(or the resolved Outputs) reflect the *external* stack's pool/client + `client_secret_arn`, and
for EntraId that `entra_discovery_url`/`entra_client_id` are set. The discovery URL baked into
the Gateway provider must match the external runtime's issuer. (Verified 2026-06-05: a token from
the external pool returns 200; a token from our pool returns this exact 401.)

**`AccessDenied` on `GetSecretValue` when the credential-provider custom resource creates** —
e.g. `User: ...ServiceExtOAuth2Provider... is not authorized to perform: secretsmanager:GetSecretValue`.
Two distinct causes produce this identical error, and only one of them is about IAM:

1. **The configured identifier resolves to no secret** — most often an ARN hand-copied without the
   6-character suffix Secrets Manager appends (`...-Tn5pYW`). Secrets Manager answers
   `AccessDenied`, *not* `ResourceNotFoundException`, so as not to reveal a secret's existence to
   an unauthorized caller. Every signal then points at IAM, where nothing is wrong: the
   `${clientSecretArn}*` grant matches the truncated string, and `simulate-principal-policy`
   reports "allowed" because it string-matches without checking existence. Synth now pre-empts
   this — `assertSecretResolves` (`cdk/lib/utils/cfn-outputs-resolver.ts`) does a real
   `DescribeSecret` from the deployer's credentials and aborts on not-found. Get the exact value
   with `aws secretsmanager describe-secret --secret-id <name> --query ARN`.
2. **A genuine grant mismatch** — granting with a `-??????` partial pattern (the old
   `fromSecretPartialArn` behavior) does not match a complete ARN. The adapter grants on
   `${clientSecretArn}*`, which matches either form.

**Target is `READY` but its tools don't appear in `tools/list` (empty)** — two distinct causes:
1. **Wrong OAuth scope (external mode).** The Gateway provider is requesting a scope the
   *external* pool's resource server doesn't define. The inbound token is minted from the
   external Cognito pool, so `external_stack.inbound_scopes` must be one of ITS scopes —
   `awsforsap-mcp-m2m-resource-server-<UniqueId>/read` — not `<base>-gateway/read`. A foreign
   scope yields a token the runtime won't honor for listing, so the target is `READY` but
   surfaces zero tools. With `inbound_auth_provider: EntraId` the scope *shape* also differs:
   Entra's client-credentials grant takes exactly one `<App ID URI>/.default`, and a
   Cognito-style `<pool>/read` is rejected with a 400 the Gateway reports as
   `Error parsing ClientCredentials response`.
2. **`listing_mode: DYNAMIC`.** DYNAMIC forwards `tools/list` per active MCP session and does
   **not** surface tools in the Gateway's *aggregate* `tools/list`. Use `listing_mode: DEFAULT`
   to pre-sync the catalog so tools appear in the aggregate list (verified 2026-06-05: switching
   the external target DYNAMIC→DEFAULT made its 5 SAP MCP tools appear).

**`discoveryUrl` regex rejection when creating the SAP OAuth provider** — if the provider Lambda
fails validating `discoveryUrl`, a SAP **token URL** was likely passed where a discovery URL is
expected. AgentCore's `discoveryUrl` enforces a `.+/\.well-known/(openid-configuration|oauth-authorization-server)`
regex. SAP token URLs are not `.well-known` documents — the SAP-facing provider must use
`authorizationServerMetadata` (explicit `authorizationEndpoint` + `tokenEndpoint` + `issuer`),
which `lambdas/oauth2_provider_cr/index.py` does automatically when `AuthorizationEndpoint` +
`TokenEndpoint` are supplied. Only the Cognito/Gateway-side providers should use `discoveryUrl`.

**403 from SAP** — SAP-side auth failure. Check `MCP_SERVER_ALLOWED_SERVICE_PREFIXES` covers the service the tool called. Check the SAP BTP OAuth client has the right scopes. Check the SAP user (for BASIC) has the right OData authorizations.

## References

- [ADR-012: SAP MCP Server Integration](../design-decisions/012-sap-mcp-server-integration.md)
- [AWS for SAP MCP Server Documentation](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/introduction.html)
- [AgentCore Gateway MCP Server Targets](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-MCPservers.html)
- [AgentCore Gateway Outbound Authorization](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-outbound-auth.html)
- [On-Behalf-Of Token Exchange](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/on-behalf-of-token-exchange.html)
- [SAP Connectivity and Auth (existing path)](./CONNECTIVITY_AND_AUTH.md)
