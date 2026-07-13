# ADR-012: Offer AWS for SAP MCP Server as a Drop-In Alongside Lambda SAP Tools

**Status:** Accepted/Implemented (external-only, **sole SAP path**). BASIC + M2M + USER_FEDERATION wired for external mode; the inbound-auth design and the auth-URL surfacing behavior are verified against current AWS/SAP docs. Pending end-to-end validation against a production SAP system. (The legacy `self` deploy mode was removed — see the 2026-06-09 addendum. The homegrown `sap_operations` Lambda tools were removed and the SAP MCP server is now the *only* SAP path; our adapter config is reduced to on/off target toggles — see the 2026-06-24 addendum.)
**Date:** 2026-05-07 (original) / 2026-06-05 (hybrid + M2M update) / 2026-06-09 (external-only) / 2026-06-24 (MCP-only, pure adapter) — see addenda at end

## Context

AWS launched the [AWS for SAP MCP Server](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/introduction.html) in May 2026 (GA). It's a container image deployed to AgentCore Runtime that exposes SAP S/4HANA and SAP ECC OData operations as MCP tools — service discovery, `$metadata` inspection, OData read/write, function imports, custom catalog support — with AgentCore Identity-backed auth (Basic, OAuth 2.0 M2M, OAuth 2.0 authorization-code for user federation).

Our quickstart currently exposes SAP via two parameterized Lambda tools (`sap_read`, `sap_write`) routed through the AgentCore Gateway, with an identity interceptor Lambda handling four SAP identity modes (`service-account`, `mtls`, `oidc-passthrough`, `principal-propagation`).

We want to offer the SAP MCP Server as a drop-in option so that:

1. Customers who prefer a managed, AWS-maintained SAP OData layer can opt in with minimal config.
2. We can A/B-test the agent's effectiveness with AWS-provided tool schemas vs. our hand-tuned parameterized tools.
3. Future SAP OData capabilities that AWS ships (pagination, batch, new metadata features) land automatically without code changes here.

There was a concern that the Gateway doesn't support MCP server targets with `$defs`/`$ref` in tool schemas. We verified this is partially true (the Gateway's `SchemaDefinition` doesn't document `$defs`/`$ref`) but does not block MCP server targets in DYNAMIC listing mode, which forwards `tools/list` at invoke time without normalization. This is the escape hatch.

## Decision

Add the AWS for SAP MCP Server as an **opt-in second path** to SAP, deployed in a new CDK stack (`sap-mcp-stack`), connected to the existing Gateway via an MCP server target, and offered alongside the existing `sap_operations` Lambda tools. No existing code paths are removed or modified.

Rollout in two phases:

- **Phase 1 (this ADR, Accepted)** — Service-account-only Runtime with OAuth2 outbound auth from the Gateway (client_credentials grant from Cognito → Bearer token). Covers autonomous/poller flows and the `service-account` identity mode. Scaffolding exists in config for Phase 2 but is disabled by default.
- **Phase 2 (Proposed)** — Optional user-federation Runtime with OAuth 2.0 token exchange (On-Behalf-Of, OBO) outbound auth. Covers `oidc-passthrough`-equivalent user-delegated flows. Disabled by default; customers opt in when they have a compatible IdP topology.

## Rationale

### Why keep both paths side-by-side

The existing `sap_operations` + identity interceptor path covers **four** SAP identity modes (`service-account`, `mtls`, `oidc-passthrough`, `principal-propagation`). The SAP MCP Server only represents OAuth-adjacent identity patterns (Basic, M2M, user-federation). Dropping the existing path would regress two identity modes (`mtls`, `principal-propagation`).

Side-by-side also lets us A/B benchmark the two approaches without a flag-day cutover. Tools can be added or removed from a skill's `gateway_tools` list without deploys, so benchmarking is just a config flip.

### Why a separate stack (`sap-mcp-stack`)

Keeping the SAP MCP wiring out of `backend-stack.ts` keeps that stack's blast radius small. The SAP MCP stack depends on (but does not modify) `BackendStack`: it reads its Gateway, Gateway role, VPC, Cognito pool, and SAP credentials secret, and adds new resources (Runtime, execution role, Gateway target). This also lets customers deploy or tear down the SAP MCP path independently.

### Why OAuth2 outbound auth for Phase 1

The SAP MCP Runtime requires a `customJwtAuthorizer` and rejects SigV4 (`GATEWAY_IAM_ROLE`) for inbound auth. This means the Gateway must present a Bearer token, not an IAM signature. We use an OAuth2 credential provider configured with a Cognito machine-to-machine (M2M) app client using the `client_credentials` grant. The Gateway obtains a JWT from Cognito's token endpoint and forwards it as a Bearer token to the Runtime.

This reuses the existing Cognito user pool (no new IdP) and requires only two new resources: a Cognito app client with a secret (for `client_credentials` grant) and an OAuth2 credential provider registered in AgentCore's token vault via a Custom Resource Lambda.

### Why DYNAMIC listing mode for Phase 1

The Gateway control-plane `SchemaDefinition` type officially supports only `type`/`description`/`items`/`properties`/`required`. MCP tool schemas that contain `$defs`/`$ref`/`oneOf`/`anyOf`/`allOf` may fail the Gateway's `tools/list` normalization during `SynchronizeGatewayTargets` (DEFAULT mode). DYNAMIC mode forwards `tools/list` at invoke time without normalization.

Tradeoff: DYNAMIC disables semantic tool search for the SAP MCP target. Acceptable — the SAP MCP target surfaces a small, well-named tool set and our agent has explicit skill→tool mappings in `skills/*/config.json`.

We'll promote to DEFAULT mode after verifying the specific SAP MCP tool schemas are SchemaDefinition-compliant.

### Why not replace the existing Lambda tools

- **Identity model parity** — existing path covers all 4 modes; SAP MCP covers 2–3 depending on phase.
- **Audit context propagation** — existing path propagates `x-audit-correlation-id`/`x-audit-initiator`/`x-audit-trigger` through the identity interceptor Lambda, which injects them as SAP headers. SAP MCP handles audit differently and we haven't verified parity.
- **SQS FIFO-backed writes** — `sap_write` queues writes for reliability and retry. SAP MCP does synchronous writes. Our write volume and failure isolation needs are different.
- **Cedar enforcement** — existing path is the reference for Cedar policy authoring. Adding SAP MCP tools means adding Cedar actions for them too.

### Why Phase 2 is separate

User-federation requires a specific IdP topology:
- Either users and SAP use the same IdP (Entra/Okta/Auth0 — OBO works out of the box).
- Or there's a trust relationship between Cognito (agent inbound) and SAP BTP's IdP (XSUAA/IAS) enabling token exchange.

Neither is a quickstart-level default. Phase 2 requires customer-specific config (SAP IdP discovery URL, OBO grant mode, actor token content). Scaffolding the config shape now lets Phase 2 land cleanly later without another ADR.

## What gets created

### Phase 1 (in scope now)

New CDK stack (`cdk/lib/sap-mcp-stack.ts`) with:
- `AWS::BedrockAgentCore::Runtime` — SAP MCP container from `<aws-account>.dkr.ecr.<region>.amazonaws.com/aws-sap-mcp:<tag>`
- `AWS::IAM::Role` + `AWS::IAM::Policy` — Runtime execution role (ECR, CW Logs, X-Ray, workload identity, SAP secret scoped to ARN)
- **OAuth2 credential provider** — Custom Resource Lambda that registers a `client_credentials` provider in AgentCore's token vault, pointing at the Cognito token endpoint with the machine client's credentials
- `AWS::BedrockAgentCore::GatewayTarget` — MCP server target on the existing Gateway, `credentialProviderType: OAUTH` with `OauthCredentialProvider` referencing the provider ARN, `listingMode: DYNAMIC`
- SSM parameters for Runtime ARN and MCP tool names

Modifications to `backend-stack.ts`:
- Expose `gateway`, `gatewayRole`, `machineClientId`, `machineClientSecretArn` as public for cross-stack consumption

Config schema extension (`cdk/config.yaml.example` + `cdk/lib/config.ts`):
- `sap_mcp.enabled`, `sap_mcp.container_uri`, `sap_mcp.listing_mode`, `sap_mcp.allowed_service_prefixes`, `sap_mcp.use_sap_catalog`
- `sap_mcp.service.*` block for the Phase 1 service-account Runtime
- `sap_mcp.user.*` block pre-scaffolded but defaults disabled

Skill wiring: existing skills gain SAP MCP tools (`find_sap_services`, `get_metadata`, `get_service_hints`, `odata_read`, `odata_count`) in `gateway_tools`, replacing `sap_read` and the OData spec tools. `sap_write` is retained for SQS-FIFO-backed writes.

### Phase 2 (Proposed, deferred)

Additions to `cdk/lib/sap-mcp-stack.ts` gated on `sap_mcp.user.enabled`:
- Second `AWS::BedrockAgentCore::Runtime` with `AuthFlow=USER_FEDERATION`
- `AwsCustomResource` calling `bedrock-agentcore:CreateOauth2CredentialProvider` with the SAP IdP's discovery URL + OBO config (`onBehalfOfTokenExchangeConfig.grantType` = `TOKEN_EXCHANGE` or `JWT_AUTHORIZATION_GRANT`)
- Second `GatewayTarget` with `credentialProviderType: OAUTH`, `grantType: TOKEN_EXCHANGE`, pointing at the credential provider ARN
- Runtime's `CustomJWTAuthorizer` configured for the SAP IdP's issuer (not Cognito — the MCP server receives SAP IdP tokens after Gateway's OBO exchange)
- Additional IAM grants on `gatewayRole`: `bedrock-agentcore:GetResourceOauth2Token` on the new provider ARN, `bedrock-agentcore:GetWorkloadAccessTokenForJWT` on the Gateway's workload identity

Additional skill tools: `sap_mcp_user_odata_read`, `sap_mcp_user_odata_write` (OBO path).

Additional Cedar policies: actions for the user-federation variants, with stricter defaults (e.g., `delete` disallowed even if Runtime env var permits).

Docs:
- `docs/sap/SAP_MCP_USER_FEDERATION.md` — how to configure the SAP IdP (XSUAA, Entra, Okta) for OBO, trust relationships between Cognito (agent inbound) and SAP IdP (OAuth outbound), rotation runbooks.

## Open questions (for Phase 2)

1. **IdP trust topology** — quickstart ships Cognito inbound. Real customers often have Entra/Okta. Do we ship per-IdP setup guides or document a generic pattern and point at IdP docs?
2. **OBO grant type selection** — RFC 8693 (`TOKEN_EXCHANGE`) vs. RFC 7523 (`JWT_AUTHORIZATION_GRANT`). Need a decision tree in the guide based on target IdP.
3. **Actor token content** — `M2M` is the safe default (AgentCore Identity fetches a machine token via client_credentials and sends it as actor). `AWS_IAM_ID_TOKEN_JWT` is available when `iam:EnableOutboundWebIdentityFederation` is on the account. `NONE` works for some IdPs. Document per-IdP.
4. **Audit context propagation through OBO** — SAP MCP Server passes the Bearer token to SAP. Whether our audit baggage (`x-audit-*`) survives the chain depends on how the MCP server handles headers. Needs verification.
5. **Cedar policy scope for user-federation tools** — should they inherit all actions from the service-account variants, or start with a minimal set (read-only, no function imports)?
6. **Token caching / revocation latency** — AgentCore Identity caches OBO exchange results. Document the TTL and how to test role-change propagation to SAP.

## What would change this decision

- **AWS adds native SAP OData support to AgentCore Gateway** (OpenAPI target or similar) that matches SAP MCP capabilities with lower operational overhead. Then both our Lambda path and the SAP MCP path become redundant.
- **SAP MCP Server adds mTLS and principal-propagation identity support.** Then it covers our full 4-mode matrix and replacement becomes viable (still subject to write queuing and audit parity).
- **Gateway adds `$defs`/`$ref` support to `SchemaDefinition`.** ~~Lets us promote SAP MCP targets from DYNAMIC to DEFAULT mode and regain semantic search.~~ **Update (2026-05-05):** This was fixed. SAP MCP targets can now use DEFAULT listing mode. We still default to DYNAMIC for safety but promotion is viable after verifying schemas.

## References

- [AWS for SAP MCP Server documentation](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/introduction.html)
- [AgentCore Gateway MCP server targets](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-MCPservers.html)
- [AgentCore Gateway outbound authorization matrix](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-outbound-auth.html)
- [On-behalf-of token exchange](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/on-behalf-of-token-exchange.html)
- [Classmethod writeup on IAM outbound to Runtime MCP](https://dev.classmethod.jp/en/articles/amazon-bedrock-agentcore-gateway-mcp-server-target-iam-outbound-auth/)
- [ADR-001: Gateway over Self-Hosted MCP](001-gateway-over-self-hosted-mcp.md)
- [ADR-010: Identity and Audit Context](010-identity-audit-context.md)
- [ADR-011: Retain Lambda-in-VPC and Identity Interceptor](011-vpc-egress-identity-interceptor-retention.md)

---

## Update (2026-06-05): Hybrid deploy model + M2M implemented; Phase 2 mechanism revised

> **Update (2026-06-09):** the `self` deploy mode was removed; the SAP MCP integration is now external-only.

This addendum supersedes parts of the original record. The historical body above is
preserved for context; where it conflicts with this section, **this section is
authoritative.**

> **Honesty note on status (updated 2026-06-09).** BASIC, M2M, and USER_FEDERATION are
> implemented for external mode. USER_FEDERATION's interactive-flow-behind-a-Gateway behavior
> is **verified against current AWS/SAP docs — the auth URL surfaces through the Gateway as
> tool-result JSON** and the external-mode USER_FEDERATION Gateway target is wired. **Nothing has been
> run end-to-end against a production SAP system yet** — the remaining work is SAP-side (IAS
> trust + a real-user audit proof). Treat as a reference design pending your own end-to-end
> validation.

### Change 1 — two deploy models: `external` (hybrid, recommended) vs `self` (legacy)

The original ADR assumed our CDK builds the SAP MCP Runtime (the path now called
`self`). We have since added a **hybrid** model and made it the recommended default
posture, selected by `sap_mcp.deploy_mode`:

- **`external` (hybrid, recommended)** — the AWS-published SAP MCP CloudFormation stack
  owns the AgentCore Runtime (the container), its **inbound Cognito pool/client/domain**,
  and the **outbound OAuth provider registration**. Our CDK becomes an *adapter*: it
  attaches a **Gateway MCP target** pointing at the external stack's invocation URL, plus
  a **Gateway OAuth2 credential provider** pointed at *that* stack's inbound IdP (so the
  Bearer token our Gateway presents is accepted by the external runtime's authorizer).
- **`self` (legacy, retained)** — our CDK creates the Runtime, both OAuth providers, the
  inbound authorizer (reusing our own Cognito pool), and the container env vars, as in the
  original Phase 1.

Default is `self` for backward compatibility (`config-manager.ts` `_normalizeSapMcpConfig`),
but hybrid is recommended for new deployments: AWS owns the container lifecycle, the
inbound pool, and the OAuth provider, so there is less for us to recreate, drift, or get
wrong. In `external` mode we must **not** recreate the runtime/pool/provider — only the
Gateway target + Gateway OAuth2 provider.

### Change 2 — M2M is implemented for both modes

The original Phase 1 shipped service-account **BASIC** only, with M2M scaffolded. **M2M is
now implemented** for both `self` and `external` modes (the old "M2M scaffolded but throws"
guard in `sap-mcp-stack.ts` is gone). M2M uses OAuth 2.0 client-credentials to the SAP IdP.

For M2M (and USER_FEDERATION) the SAP-facing OAuth2 credential provider is registered in
AgentCore Identity via `lambdas/oauth2_provider_cr/index.py`, configured with AgentCore's
`oauthDiscovery.authorizationServerMetadata` (explicit `authorizationEndpoint` +
`tokenEndpoint` + `issuer`) — **not** `discoveryUrl`. A SAP token URL is not a
`.well-known` discovery document, and the `discoveryUrl` field enforces a
`.+/\.well-known/(openid-configuration|oauth-authorization-server)` regex that a SAP token
URL fails. The issuer is derived from the token URL origin. The Cognito/Gateway-side
providers continue to use `discoveryUrl` (a genuine `.well-known/openid-configuration` URL).

The SAP credentials secret must be JSON `{clientId, clientSecret}` for M2M/USER_FEDERATION
(BASIC continues to use `{username, password}`).

### Change 3 — config-selectable inbound IdP (Cognito or EntraId)

In `external` mode, `external_stack.inbound_auth_provider` selects which IdP the external
stack was deployed with: `Cognito` (default) or `EntraId`. For EntraId, the Gateway OAuth2
provider uses `entra_discovery_url` / `entra_client_id` / `entra_client_secret_arn`
overrides instead of the Cognito pool-derived discovery URL, because the external runtime's
inbound authorizer validates Entra-issued tokens. Cognito remains the tested-first default;
EntraId is functional-parity scaffolding.

### Change 4 — Phase 2 / OBO mechanism revised (and honestly de-scoped pending further investigation)

The original Phase 2 design (above) assumed **Gateway-mediated OBO**: the Gateway would
exchange a user JWT for a SAP-scoped bearer (`oauth2Flow: ON_BEHALF_OF_TOKEN_EXCHANGE`,
`grantType: TOKEN_EXCHANGE`) and forward that bearer to the runtime. On closer reading of
the AWS for SAP MCP Server contract, the container references a **pre-created AgentCore
Identity provider by name** (`MCP_SERVER_SAP_OAUTH_PROVIDER`) and — per current
understanding of the docs and CFN template — has **no "accept an arbitrary pre-exchanged
bearer" mode**. The container drives its own auth using the named provider.

Consequently, interactive per-user identity to SAP uses **`AuthFlow=USER_FEDERATION`**,
which relies on AgentCore's own 3-legged (authorization-code) callback machinery rather
than a Gateway-side token exchange. The `AuthFlow` values accepted by the AWS template are
`BASIC`, `M2M`, `USER_FEDERATION`, and `ON_BEHALF_OF_TOKEN_EXCHANGE`; we use
**`USER_FEDERATION`** for interactive OBO. **`ON_BEHALF_OF_TOKEN_EXCHANGE` was out of scope**
for this design (it appears to be a non-interactive server-to-server token-exchange variant;
flag for follow-up investigation if a no-browser OBO is ever needed).

> **Update (2026-07-01): `ON_BEHALF_OF_TOKEN_EXCHANGE` is now in scope as the flagship OBO path.**
> The follow-up investigation this line flagged was completed. The June "out of scope" reasoning was scoped to
> a **Gateway-mediated** pre-exchange (the Gateway mints a bearer and forwards it) — which the
> container genuinely does not support. The OBO / ON_BEHALF_OF_TOKEN_EXCHANGE design instead calls the external MCP **directly**
> (bypassing our Gateway) with the user's Entra JWT as the inbound bearer, and lets the **runtime**
> drive the server-side OBO exchange via the named provider — a topology current AWS docs document
> as a first-class `ON_BEHALF_OF_TOKEN_EXCHANGE` AuthFlow. Design-validated and verified against current AWS/SAP docs; not
> yet run end-to-end. See `docs/sap/runbooks/soidc-entra-obo.md`.

> **The Gateway-mediated-OBO design appears infeasible by doc analysis — but this is NOT
> yet confirmed.** USER_FEDERATION's interactive flow assumes the MCP *client* receives the
> AgentCore-issued auth URL and drives a browser callback. With the Gateway terminating MCP,
> the Gateway is the client, and the auth-URL handoff may not surface to our agent/frontend.
> Investigation determined which of two designs applies:
> - The auth URL *does* surface through the Gateway: use the frontend-callback
>   model (`MCP_SERVER_APP_CALLBACK_URL` → our `/auth/callback` route).
> - It does *not* surface: the USER_FEDERATION target must be invoked
>   **directly** (agent → runtime, bypassing the Gateway for that one target), which loses
>   Gateway-level Cedar/audit interception for OBO calls.
>
> **Outcome (2026-06-09):** the auth URL surfaces through the Gateway as
> tool-result JSON. We use the frontend-callback model and OBO calls keep flowing through the
> Gateway (Cedar/audit interception intact); the external-mode USER_FEDERATION target is wired.

### Change 5 — Risks carried into deploy

- **Primary correctness risk (validated by design, not yet by deploy):** in
  `external` mode the Gateway's OAuth2 provider must point at the **external stack's**
  inbound IdP (client id + discovery URL), NOT our own Cognito pool — otherwise the external
  runtime's inbound authorizer returns **401**. The adapter is coded to do this
  (`cfn-outputs-resolver.ts` resolves the external pool's discovery URL/client id), but it is
  unverified until a real deploy.
- **Interactive USER_FEDERATION behind a Gateway (resolved):** see
  Change 4. The auth URL surfaces through the Gateway as tool-result JSON,
  so the external-mode USER_FEDERATION target is wired via the frontend-callback model
  (`MCP_SERVER_APP_CALLBACK_URL` → `/auth/callback`); Gateway-level Cedar/audit interception
  stays intact. Not yet run end-to-end against a production SAP system.

### Status summary

| Capability | Deploy mode | Status |
|---|---|---|
| BASIC (service account) | self, external | Accepted / Implemented (covered by the repo's tests; not yet deployed) |
| M2M (external + self) | self, external | Accepted / Implemented (covered by the repo's tests; not yet deployed) |
| Inbound IdP Cognito | external | Implemented (default) |
| Inbound IdP EntraId | external | Implemented (functional-parity scaffolding) |
| USER_FEDERATION (interactive OBO) | external | Implemented (external-mode Gateway target wired; auth-URL surfacing verified against current AWS/SAP docs; not yet run end-to-end against a production SAP system) |
| `ON_BEHALF_OF_TOKEN_EXCHANGE` (direct-to-MCP) | external | In scope (design-validated and verified against current AWS/SAP docs; direct-to-MCP, not Gateway-mediated; not yet run end-to-end — see `docs/sap/runbooks/soidc-entra-obo.md`) |

See `docs/sap/SAP_MCP_INTEGRATION.md` (deploy model, env-var contract, troubleshooting) and
`docs/sap/SAP_MCP_USER_FEDERATION.md` (interactive OBO setup).

---

## Update (2026-06-24): MCP-only — homegrown SAP path removed; config reduced to a pure adapter

> This addendum supersedes the original "drop-in **alongside** the Lambda SAP tools / keep both
> paths side-by-side / A/B benchmark" framing (title, Context, Decision, and the "Why keep both
> paths" / "Why not replace the existing Lambda tools" rationale). Where the body above conflicts
> with this section, **this section is authoritative.** The historical body is retained for
> context.

> **Supersedes:** [ADR-008](008-principal-propagation.md) (SAP Identity Modes — the four-mode
> taxonomy and identity interceptor), [ADR-010](010-identity-audit-context.md) (Identity and
> Audit Context — the SQS `sap_write` consumer and interceptor code paths), and (partially)
> [ADR-011](011-vpc-egress-identity-interceptor-retention.md) (the identity interceptor it
> recommended retaining is removed; the Lambda-in-VPC pattern is retained for the `odata_poller`).

For the external sample release we collapsed the over-broad SAP optionality onto a single
opinionated path. The change has two parts:

### 1. The SAP MCP server is now the *only* SAP path

The homegrown `sap_operations` (`sap_read`/`sap_write`), `odata_spec`, `metadata_scanner`, and
the SQS-FIFO `sap_write_consumer` were **removed entirely**, along with the four-mode SAP
identity taxonomy and the JWT-verifying identity interceptor. The agent reaches SAP for reads,
writes, and discovery **exclusively** through the external AWS for SAP MCP server. The only
component that still calls SAP directly is the autonomous OData poller (service-account, basic
auth — it cannot use Gateway/MCP tools). This moots the original "identity-model parity" and
"keep both paths" rationale: there is no second path to keep.

Write governance did not regress — it moved to the Gateway, on top of the MCP target:
- **Cedar** role-gates `odata_create`/`odata_update`/`odata_function_import` (finance/
  procurement/admin) and **forbids `odata_delete`** outright.
- The **external AWS-for-SAP MCP server's write-enablement** (`MCP_SERVER_WRITE_ENABLED` +
  the per-op `MCP_SERVER_CREATE/UPDATE/DELETE/FUNCTION_IMPORT_ENABLED` flags, all default-off)
  governs whether the runtime performs writes at all.

(An earlier `action-mode` interceptor that hard-blocked writes at the Gateway was removed in a
later simplification — see threat T6. Prod guidance is to
re-add a deterministic Gateway request interceptor for write gating.)

### 2. Our adapter config is reduced to on/off target toggles

> **Superseded (2026-06-30).** The manual `sap_mcp.service.enabled` / `sap_mcp.user.enabled`
> toggles described below were **removed**. The active target variant (Service / User) is now
> **derived from `auth_profile`'s outbound axis** (`m2m-*` → Service, `user-federation` → User,
> `basic` → neither), so the profile decides which target is minted — see
> `docs/sap/SAP_MCP_INTEGRATION.md`.

`sap_mcp.service` and `sap_mcp.user` are now **bare `{ enabled }` toggles** that decide which
Gateway targets to mint. The per-runtime permission knobs that used to live in our config
(`auth_flow`, `sap_oauth`, `sap_oauth_scopes`, `app_callback_url`, `read_enabled`,
`write_enabled`, `create_enabled`, `update_enabled`, `delete_enabled`,
`function_import_enabled`) were **removed** — every one of them is owned by the **external AWS
CFN stack** (its CFN parameters / runtime `MCP_SERVER_*` env vars). In particular, read vs write
enablement is set on the external runtime via `MCP_SERVER_WRITE_ENABLED` + the per-op
`MCP_SERVER_CREATE/UPDATE/DELETE/FUNCTION_IMPORT_ENABLED` flags (all default-off), per the
[AWS configuration reference](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/configuration-reference.html).
Writes are fully supported — you enable them there.

This keeps our CDK a true adapter: it never deploys the runtime, owns the SAP OAuth provider,
or sets a SAP permission. Terraform never implemented the SAP MCP adapter (it remains CDK-only;
the TF backend module documents that SAP OData is served externally), so there was nothing to
mirror.

### Status (unchanged capabilities, narrower config)

| Capability | Status |
|---|---|
| BASIC / M2M / USER_FEDERATION | Implemented for external mode (flow set on the external stack) |
| SAP writes (create/update/function_import) | Supported — enabled on the external stack; Gateway Cedar policy + the external MCP server's write-enablement govern them |
| `odata_delete` | Forbidden at the Gateway by Cedar |
| Homegrown `sap_operations` / write queue / odata_spec / metadata_scanner | Removed |
| Our config per-op permission knobs | Removed (owned by the external stack) |
