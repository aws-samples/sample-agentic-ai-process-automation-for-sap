<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Choosing an Auth Profile

One knob selects the identity topology for the entire deployment: **`auth_profile`**.

## Where to set it

| Backend | Where | Default |
|---------|-------|---------|
| **CDK** | `cdk/config.yaml` key `auth_profile:` | `cognito-basic` |
| **Terraform** | `terraform.tfvars` var `auth_profile` | `"cognito-basic"` |

Default works out of the box with no external IdP.

## The profile catalog

Profiles are defined in [`auth-profiles.yaml`](../../auth-profiles.yaml) (single source of truth).
Each profile selects a value on four axes: **frontend** (SPA login IdP), **inbound** (JWT
authorizer), **mode** (processing model), and **outbound** (expected SAP-facing auth flow).

> **External ownership of the outbound flow:** this CDK does not create or configure the
> SAP-facing OAuth flow. The separately deployed AWS for SAP MCP server owns its runtime,
> SAP OAuth provider, credentials, scopes, and `MCP_SERVER_SAP_OAUTH_FLOW`. With real AWS
> credentials, CDK reads that external CloudFormation stack at synth time, verifies that
> its declared flow is coherent with the selected profile, and provisions only this
> repository's Gateway/direct-MCP adapter. Thus `outbound: m2m-sap` is both an adapter
> selection and an expectation about the external stack—not ownership of SAP auth by
> this repository.

### Supported by this repository's CDK deployment path

| Profile | Frontend | Inbound | Mode | Outbound | SAP flow | Verified E2E |
|---------|----------|---------|------|----------|----------|--------------|
| `cognito-basic` (default) | Cognito | Cognito | autonomous, live | basic | BASIC (service account) | ✅ S/4HANA, both modes |
| `cognito-m2m` | Cognito | Cognito | autonomous, live | m2m-sap | M2M (client credentials) | — |
| `cognito-m2m-batch` | Cognito | Cognito | autonomous, live, batch | m2m-sap | M2M (client credentials) | — |
| `entra-obo` | Direct-Entra | Entra | live | obo | ON_BEHALF_OF_TOKEN_EXCHANGE | ✅ S/4HANA 2023 |
| `okta-basic` | Direct-Okta | Okta | live | basic | BASIC (service account) | — |

This repository's CDK deployment path implements the required adapter wiring for these profiles.
It can synthesize and deploy them when their documented, operator-owned external prerequisites are
supplied; that is separate from the live-SAP verification shown in the last column.

**"Verified E2E" means the profile completed a live-SAP run — not that SAP saw the end user.**
Only `entra-obo` propagates human identity to SAP (Entra user → SU01 user, confirmed in `STAD`).
`cognito-basic` reached SAP as the configured Basic *technical* user, so its audit rows carry the
service account, whoever was signed in. Pick on that distinction, not on the checkmark. On
**Terraform**, only `cognito-basic` deploys today (Terraform has no SAP MCP module, so the outbound
axis is not wired — see [Terraform scope](#terraform-scope) below).

`cognito-basic` and `cognito-m2m` work with no external IdP. **`entra-obo` is not zero-config**: it
requires `frontend_overrides` + `inbound_overrides` with your Entra tenant values (see
[Companion knobs](#companion-knobs-non-cognito-profiles) below) and is Entra/OBO only — it was verified
end-to-end against a live SAP system (S/4HANA 2023, SAP_BASIS 7.58); see
[`runbooks/soidc-entra-obo.md`](./runbooks/soidc-entra-obo.md).

**`okta-basic` is likewise not zero-config** and needs both override blocks with your Okta org values
(see [`OKTA_SETUP.md`](./OKTA_SETUP.md)). Its Verified column stays `—` on purpose: its two Okta axes
were proven by a real login on 2026-07-31 — the deployed SPA's PKCE flow issued an `id_token` that the
deployed authorizer accepted, and the request reached the backend — but its outbound is a Basic
technical user, so nothing per-user reaches SAP and the `verified` bar (a live-SAP E2E run) is not met.
Its frontend axis is still `experimental`, so the deployment emits a maturity caveat.

### Preview (not yet supported by this repository's CDK deployment path)

| Profile | Frontend | Inbound | Mode | Outbound | SAP flow | Notes |
|---------|----------|---------|------|----------|----------|-------|
| `cognito-userfed-ias` | Cognito | Cognito | live | user-federation | USER_FEDERATION | IAS trust chain |
| `entra-userfed` | Cognito+Federated | Cognito | live, batch | user-federation | USER_FEDERATION | Email-join federation. Its `batch` is the *user-identity* flavour (acting as a named absent human), which needs a refresh-capable outbound — distinct from `cognito-m2m-batch` above. It also omits `autonomous`, so it fails the batch synth gate as written. |
| `okta-userfed` | Direct-Okta | Okta | live | user-federation | USER_FEDERATION | Okta inbound + outbound. **Its outbound is blocked upstream**, not merely unimplemented here: AgentCore Identity's managed 3LO callback takes the Okta auth code and never redeems it, so no token vaults. It is therefore the wrong profile to pick when you want to exercise a SAP-side Okta SOIDC trust — nothing deployable forwards an Okta user token today. Use `okta-basic` for the Okta axes, and `test-scripts/test-okta-sap-local.py` for the SOIDC trust — noting that the test reports pass/fail, not *where* a failure is: on a system whose 401 challenge scheme varies with header length, localising it needs SOIDC's paste-a-token validator or the SAP audit log. |

Preview profiles resolve and validate, but this repository's CDK deployment path cannot stand them
up end to end — at least one selected axis is `status: stub`. They document the roadmap. Promotion
criteria and the two-gate model (`status` = supported by the repository's CDK deployment path,
`verified` = run against live SAP) live in [`PROFILE_PROMOTION.md`](./PROFILE_PROMOTION.md).

**Stub does not always mean unbuilt.** Each stub axis declares `blocked_by` in
`auth-profiles.yaml`: `repo` (wiring missing here), `operator` (wiring built, awaiting external
config such as an IdP tenant), or `upstream` (wiring built, blocked in an AWS service). This changes
what the emitted banner reports, not whether the profile can deploy — a stub axis is undeployable
regardless of who owns the blocker.

Both Okta axes used to be `operator`, and clearing them shows what that classification was worth: the
wiring really was built (the authorizer and direct-IdP frontend are issuer-parameterized, proven on
Entra over the same code), so supplying the external config was the whole remaining task. Note what
did **not** happen when they cleared — `okta-userfed` shares both of those axes and stayed in preview,
because its `user-federation` outbound is `upstream`-blocked in AgentCore Identity's 3LO vault. Axis
status is shared; profile promotion is not.

## Decision tree

```
Do you need interactive per-user SAP identity?
├── No  → Do you need SAP OData via the MCP server?
│         ├── No  → cognito-basic (default)
│         └── Yes → Sweep cases the poller never enqueued (unattended backlog)?
│                   ├── No  → cognito-m2m (M2M client credentials to SAP)
│                   └── Yes → cognito-m2m-batch (adds the batch sweeper; same
│                             technical-user identity, re-minted per run)
└── Yes → Seamless (no second login, server-side token exchange)?
          ├── Yes → entra-obo (direct-to-MCP OBO, Entra inbound) — CDK-supported;
          │         needs Entra frontend_overrides + inbound_overrides (not zero-config)
          └── No, 3-legged interactive login → (preview — all three share the
                user-federation outbound, blocked upstream in AgentCore's 3LO vault)
                ├── Cognito users + IAS federation → cognito-userfed-ias
                ├── Cognito federated + Entra → entra-userfed
                └── Okta inbound + outbound → okta-userfed
          See TOKEN_MECHANICS.md for the distinctions between these flows.
```

`okta-basic` is off this tree on purpose, even though it is now CDK-supported: it answers "no" to
per-user SAP identity, so nothing here routes to it. It exists to prove the Okta frontend and inbound
axes while `user-federation` is blocked, not to be chosen for what it does at SAP. If you want Okta
login *and* Okta identity at SAP, no profile delivers that today.

## Companion knobs (non-cognito profiles)

When selecting a non-cognito **inbound** profile, supply the external IdP values that are known
pre-deploy:

| Backend | What to set |
|---------|-------------|
| CDK | `inbound_overrides:` block — `discovery_url` + `allowed_clients` |
| Terraform | `auth_inbound_discovery_url` + `auth_inbound_allowed_clients` vars |

When selecting a **direct-entra / direct-okta frontend** (CDK only):

```yaml
frontend_overrides:
  discovery_url: https://login.microsoftonline.com/<tenant>/v2.0/.well-known/openid-configuration
  client_id: <spa-app-client-id>
  # scope: email openid profile offline_access   # optional
```

## Disambiguation

| Knob | What it does | Where documented |
|------|--------------|-----------------|
| `auth_profile` | Selects identity topology across all four axes (deploy-time), including the frontend login IdP | This doc |
| `autonomy.trigger_mode` / `trigger_mode` | Runtime behaviour (auto / manual) — flippable at runtime via SSM | [DEPLOYMENT.md](../getting-started/DEPLOYMENT.md) |
| Mode axis (`autonomous` / `live` / `batch`) | Deploy-time constraint; only `batch` provisions anything (a sweeper Lambda + schedule), and it requires `autonomous` in the same profile | [DEPLOYMENT.md](../getting-started/DEPLOYMENT.md) |

## Terraform scope

Terraform consumes **only the inbound axis** today. The outbound (SAP MCP target / OBO), mode
(batch runner), and frontend (direct-IdP SPA) axes are wired by CDK only — no Terraform module
exists for those. If you select a profile that requires any of those axes, the Terraform
`external` data source will **fail at plan time** with a clear message naming the CDK-only axes.

For the default `cognito-basic` profile and a Cognito-only deployment, Terraform is feature-complete.

## See also

- [`auth-profiles.yaml`](../../auth-profiles.yaml) — source of truth (axis definitions + profile catalog)
- [SAP MCP Integration](./SAP_MCP_INTEGRATION.md) — the external SAP MCP adapter deploy model
- [Token Mechanics](./TOKEN_MECHANICS.md) — passthrough vs OBO vs USER_FEDERATION vs M2M
- [Runbooks index](./runbooks/README.md) — SAP-side operator steps per flow
