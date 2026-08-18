---
inclusion: always
---

<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->
# SAP Integration

## Connectivity

Set `sap.base_url` in `cdk/config.yaml` to the SAP OData endpoint URL. No networking resources are created by CDK — you manage your own VPC/peering/VPN.

For private SAP endpoints, set `backend.network_mode: VPC` and provide your VPC config in `backend.vpc`.

| Scenario | `sap.base_url` | `backend.network_mode` | You manage |
|----------|---------------|----------------------|------------|
| SAP BTP / Cloud | Public URL | `PUBLIC` | Nothing extra |
| SAP RISE on AWS | Private DNS | `VPC` | VPC peering |
| SAP on-prem | Private DNS | `VPC` | VPN or Direct Connect |
| SAP on EC2 | Private IP | `VPC` | Security group rules |

## Identity

SAP access uses service-account credentials only.

- **`odata_poller` Lambda** — the only component in this stack that calls SAP directly, using service-account Basic Auth read from Secrets Manager. It polls for exceptions and enqueues cases.
- **Agent SAP OData** — all read/write/discovery the agent performs goes through the external AWS for SAP MCP server (registered as a Gateway target), not through any Lambda in this repo.
- **Interactive per-user SAP auth** — handled by the external MCP server's USER_FEDERATION flow. See `docs/sap/` for setup; this stack does not implement per-user SAP identity propagation.

## Credential Flow

1. CDK creates a Secrets Manager secret: `{stack_name_base}/sap-credentials` with keys `base_url`, `username`, `password`
2. CDK stores the secret ARN in SSM: `/{stack_name_base}/secrets/sap-credentials-arn`
3. Lambdas read the ARN from SSM, then fetch the secret from Secrets Manager
4. `make sync-sap-secret` updates the secret values (reads `sap.base_url` from config.yaml, prompts for username/password)

## OData Access

SAP OData is a Gateway MCP *target* pointing at the external AWS for SAP MCP server — not a homegrown Gateway tool. The MCP server exposes the OData tools the agent calls, e.g. `find_sap_services`, `get_metadata`, `get_service_hints`, `odata_read`, `odata_count`, `odata_create`, `odata_update`, `odata_function_import`. Service/entity discovery (metadata) happens at runtime via `find_sap_services` / `get_metadata` — there is no pre-built spec cache in this repo.

Skills opt into these tools by listing them in their `gateway_tools` array (see `skills/*/config.json`).

## Key Files

| File | What |
|------|------|
| `cdk/config.yaml` | `sap.*` settings drive everything |
| `cdk/lib/backend-stack.ts` → `createSapSecrets()` | Creates the secret + SSM param |
| `lambdas/odata_poller/` | Service-account poller — the only direct SAP caller |
| `lambdas/odata_poller/domains/*.json` | Per-domain poll configs (e.g. `example_finance_accruals.json`, `finance_ap.json`) |
| `python3 launch.py sync-sap` | Sync credentials to Secrets Manager (also `make sync-sap-secret`) |
| `docs/sap/` | External MCP server setup + USER_FEDERATION for interactive auth |
