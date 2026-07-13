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
authorizer), **mode** (processing model), and **outbound** (SAP-facing auth flow).

### Deploys today

| Profile | Frontend | Inbound | Mode | Outbound | SAP flow | Verified E2E |
|---------|----------|---------|------|----------|----------|--------------|
| `cognito-basic` (default) | Cognito | Cognito | autonomous, live | basic | BASIC (service account) | — |
| `cognito-m2m` | Cognito | Cognito | autonomous, live | m2m-sap | M2M (client credentials) | — |
| `entra-obo` | Direct-Entra | Entra | live | obo | ON_BEHALF_OF_TOKEN_EXCHANGE | ✅ S/4HANA 2023 |

These have built IaC and deploy end-to-end on CDK. On **Terraform**, only `cognito-basic` deploys
today (Terraform has no SAP MCP module, so the outbound axis is not wired — see [Terraform scope](#terraform-scope) below).

`cognito-basic` and `cognito-m2m` work with no external IdP. **`entra-obo` is not zero-config**: it
requires `frontend_overrides` + `inbound_overrides` with your Entra tenant values (see
[Companion knobs](#companion-knobs-non-cognito-profiles) below) and is Entra/OBO only — it was verified
end-to-end against a live SAP system (S/4HANA 2023, SAP_BASIS 7.58); see
[`runbooks/soidc-entra-obo.md`](./runbooks/soidc-entra-obo.md).

### Preview (not yet deployable)

| Profile | Frontend | Inbound | Mode | Outbound | SAP flow | Notes |
|---------|----------|---------|------|----------|----------|-------|
| `cognito-userfed-ias` | Cognito | Cognito | live | user-federation | USER_FEDERATION | IAS trust chain |
| `entra-userfed` | Cognito+Federated | Cognito | live, batch | user-federation | USER_FEDERATION | Email-join federation |
| `okta-userfed` | Direct-Okta | Okta | live | user-federation | USER_FEDERATION | Okta inbound + outbound |

Preview profiles resolve and validate but cannot deploy — at least one axis value is `status: stub`
(IaC module not built). They document the roadmap. Promotion criteria and the two-gate model
(`status` = built, `verified` = run against live SAP) live in
[`PROFILE_PROMOTION.md`](./PROFILE_PROMOTION.md).

## Decision tree

```
Do you need interactive per-user SAP identity?
├── No  → Do you need SAP OData via the MCP server?
│         ├── No  → cognito-basic (default)
│         └── Yes → cognito-m2m (M2M client credentials to SAP)
└── Yes → Seamless (no second login, server-side token exchange)?
          ├── Yes → entra-obo (direct-to-MCP OBO, Entra inbound) — deploys today;
          │         needs Entra frontend_overrides + inbound_overrides (not zero-config)
          └── No, 3-legged interactive login → (preview — not deployable yet)
                ├── Cognito users + IAS federation → cognito-userfed-ias
                ├── Cognito federated + Entra → entra-userfed
                └── Okta inbound + outbound → okta-userfed
          See TOKEN_MECHANICS.md for the distinctions between these flows.
```

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
| `auth_profile` | Selects identity topology across all four axes (deploy-time) | This doc |
| `sap.auth_provider` / `auth_provider` | Frontend **login** IdP (Cognito / Okta / custom-OIDC) — independent of SAP identity | [CONNECTIVITY_AND_AUTH.md](./CONNECTIVITY_AND_AUTH.md) |
| `autonomy.trigger_mode` / `trigger_mode` | Runtime behaviour (auto / manual) — flippable at runtime via SSM | [DEPLOYMENT.md](../getting-started/DEPLOYMENT.md) |
| Mode axis (`autonomous` / `live` / `batch`) | Deploy-time constraint; provisions nothing except `batch` (which is unimplemented and fails at synth) | [DEPLOYMENT.md](../getting-started/DEPLOYMENT.md) |

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
