<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# SAP System Configuration

What to configure inside your SAP system so the agent can authenticate and call OData APIs. SAP
machine identity is **service-account only** — a single system user authenticating via Basic Auth.

> This guide assumes SAP S/4HANA (on-prem or Cloud). ECC steps are similar but transaction names
> may differ. Adjust for your SAP version.

## 1. Service Account Setup

The OData poller (and the external SAP MCP server in BASIC mode) authenticate to SAP as one
machine user.

### Create the service user

| Step | Transaction | Details |
|------|-------------|---------|
| Create user | `SU01` | Type: **System** (non-dialog). Username: e.g. `SVC_ERP_AGENT` |
| Assign roles | `SU01` → Roles tab | Assign roles that grant access to the OData services below |
| Set password | `SU01` → Logon Data tab | Set initial password. Sync to AWS with `./scripts/sync-sap-secret.sh` |

### Required OData service authorizations

Activate the OData services the agent will call and grant the service user access:

| Step | Transaction | Details |
|------|-------------|---------|
| Activate OData services | `/IWFND/MAINT_SERVICE` | Add services: `API_PURCHASEORDER_PROCESS_SRV`, `API_SUPPLIERINVOICE_PROCESS_SRV`, `FAP_VENDOR_LINE_ITEMS_SRV`, plus any custom services |
| Check ICF nodes | `SICF` | Verify `/sap/opu/odata/sap/` node is active |
| Test service | Browser or Postman | `GET https://<sap-host>/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/$metadata` with Basic Auth |

### Authorization objects

The service user's roles must include these authorization objects:

| Object | Field | Value | Purpose |
|--------|-------|-------|---------|
| `S_SERVICE` | `SRV_NAME` | `*` or specific service names | OData service access |
| `S_SERVICE` | `SRV_TYPE` | `HT` | HTTP service type |
| `M_BEST_EKO` | `EKORG` | Your purchasing orgs | PO read/write |
| `F_BKPF_BUK` | `BUKRS` | Your company codes | FI document access |
| `F_LFA1_BUK` | `BUKRS` | Your company codes | Vendor master access |

> Tip: Use `SU53` after a failed API call to see exactly which authorization check failed.

## 2. CSRF Protection

SAP requires CSRF tokens for write operations (POST/PUT/PATCH/DELETE). CSRF token fetch and retry
are handled by the **external AWS for SAP MCP server**, not by this project's `sap_auth` layer
(which is read-only service-account session handling). No SAP-side configuration is needed — CSRF
is enabled by default on all OData services.

## 3. OData Service Activation Checklist

For each OData service the agent will call:

- [ ] Service activated in `/IWFND/MAINT_SERVICE`
- [ ] ICF node active in `SICF` (`/sap/opu/odata/sap/<service_name>`)
- [ ] Service user has `S_SERVICE` authorization for the service
- [ ] `$metadata` returns valid EDMX (test in browser with Basic Auth)
- [ ] Entity-level authorizations granted (e.g. `M_BEST_EKO` for POs, `F_BKPF_BUK` for FI docs)

## 4. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| 401 Unauthorized | Bad credentials or user locked | Check password in Secrets Manager, check user status in `SU01` |
| 403 Forbidden | Missing authorization | Run `SU53` as the service user to see which auth object failed |
| 404 Not Found | Service not activated | Activate in `/IWFND/MAINT_SERVICE` |
| 500 Internal Server Error | SAP backend error | Check SAP transaction `ST22` for ABAP dumps, `/IWFND/ERROR_LOG` for OData errors |
| Connection timeout / refused | Network path to SAP not reachable | For private endpoints verify `backend.network_mode: VPC` + VPC peering/VPN/SG rules ([Connectivity & Auth](CONNECTIVITY_AND_AUTH.md#deployment-scenarios)) |

## Related Docs

- [SAP Basic Setup](SAP_SETUP.md) — AWS-side setup (config.yaml, deploy, sync credentials)
- [Connectivity & Auth](CONNECTIVITY_AND_AUTH.md) — identity model, networking, auth providers
