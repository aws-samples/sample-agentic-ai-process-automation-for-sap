<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# SAP Basic Setup

Quick start for connecting the agent to your SAP system. SAP machine identity is
**service-account only** (Basic Auth from Secrets Manager); for the full identity model see
[Connectivity & Auth](CONNECTIVITY_AND_AUTH.md).

## 1. Configure the SAP Endpoint

Edit `cdk/config.yaml`:

```yaml
sap:
  base_url: https://your-sap-host:port
```

For private SAP endpoints (RISE, on-prem, same-VPC EC2), also set:

```yaml
backend:
  network_mode: VPC
  vpc:
    vpc_id: vpc-0abc1234
    subnet_ids: [subnet-aaa, subnet-bbb]
    security_group_ids: [sg-0abc1234]  # optional
```

This places the AgentCore Runtime and the OData poller into your VPC so they can reach SAP. You
manage the networking (VPC peering, VPN, Direct Connect, security groups). See
[Connectivity & Auth](CONNECTIVITY_AND_AUTH.md#deployment-scenarios) for the scenario matrix.

## 2. Deploy the Stack

```bash
cd cdk && cdk deploy --all && cd ..
```

This creates a Secrets Manager secret (`{stack_name_base}/sap-credentials`) with placeholder
values and stores its ARN in SSM at `/{stack_name_base}/secrets/sap-credentials-arn`.

## 3. Sync Service-Account Credentials

```bash
python3 launch.py sync-sap
```

Reads `sap.base_url` from `config.yaml` and prompts for username/password. The secret stores three
keys: `base_url`, `username`, `password`. Re-run any time credentials change (e.g. password
rotation). These same credentials are what you configure on the external AWS for SAP MCP server
(BASIC auth) for the agent's interactive SAP access.

## 4. Test the Connection

After deploying and syncing credentials:

1. Open the frontend UI and navigate to the Chat page.
2. Ask the agent to read a known SAP entity: "Read the first 5 purchase orders from SAP".
3. If it works, you'll see OData results. If not, check:
   - The OData poller's CloudWatch logs — look for 401 (bad credentials) or connection errors.
   - The secret has real values:
     `aws secretsmanager get-secret-value --secret-id "{stack_name_base}/sap-credentials"`.
   - The SAP service user has the required OData service authorizations (see
     [SAP System Configuration](SAP_SYSTEM_CONFIGURATION.md)).

## OData Discovery

There is no homegrown metadata scanner. OData service discovery and metadata are handled at
runtime by the external SAP MCP server's `find_sap_services` / `get_metadata` tools — see
[SAP MCP Integration](SAP_MCP_INTEGRATION.md).

## Related Docs

- [Connectivity & Auth](CONNECTIVITY_AND_AUTH.md) — identity model, networking, auth providers.
- [SAP System Configuration](SAP_SYSTEM_CONFIGURATION.md) — SAP-side service account + OData activation.
- [SAP MCP Integration](SAP_MCP_INTEGRATION.md) — the external AWS for SAP MCP server.
