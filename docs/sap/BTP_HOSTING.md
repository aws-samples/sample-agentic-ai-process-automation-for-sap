<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# SAP BTP Hosting Options

How to deploy and connect the quickstart when SAP runs on BTP.

## Option A: AWS-Hosted Agent, BTP as SAP Endpoint (this release)

This is the default and only supported path for this release. The agent, Gateway, and all Lambdas
stay on AWS. BTP is just the SAP OData target.

```yaml
# cdk/config.yaml
sap:
  base_url: https://my-api.s4hana.ondemand.com

backend:
  network_mode: PUBLIC             # BTP endpoints are public
```

**What you get:**
- Zero BTP deployment — just point `sap.base_url` at your BTP OData endpoint.
- Service-account machine identity (Basic Auth from Secrets Manager). The autonomous poller calls
  SAP directly; interactive SAP access goes through the external AWS for SAP MCP server. See
  [Connectivity & Auth](CONNECTIVITY_AND_AUTH.md) for the identity model.
- Full AgentCore feature set (Gateway, Memory, Identity, Cedar policies).

**When to use:** All deployments in this release. Per-user SAP identity is handled by the external
MCP server's `USER_FEDERATION` flow ([SAP_MCP_USER_FEDERATION.md](SAP_MCP_USER_FEDERATION.md)), not
by hosting the agent on BTP.

## Option B: BTP Sidecar for Joule Integration

> **Out of scope for this release.** This is a sketch of a possible future path, not implemented or
> validated here. The agent stays on AWS (Option A); a thin Cloud Foundry proxy on BTP could serve
> an A2A agent card so Joule can discover and invoke the AWS-hosted agent. See
> [A2A & Joule Integration](../extending/A2A_JOULE_INTEGRATION.md) for the A2A protocol details.

## Option C: Full BTP-Native Deployment

> **Out of scope for this release.** Moving the agent itself to BTP Kyma or Cloud Foundry (replacing
> AgentCore Gateway/Memory/Identity, Cognito, DynamoDB, etc. with SAP equivalents) is a significant
> rewrite and is not covered by this quickstart. The agent code is portable (Strands SDK runs
> anywhere Python runs), but the infrastructure layer would have to be rebuilt.

## Related

- [Connectivity & Auth](CONNECTIVITY_AND_AUTH.md) — identity model and networking
- [A2A & Joule Integration](../extending/A2A_JOULE_INTEGRATION.md) — A2A protocol implementation guide
- [SAP Basic Setup](SAP_SETUP.md) — end-to-end SAP connection quick start
