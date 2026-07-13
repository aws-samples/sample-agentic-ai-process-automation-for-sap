<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Deployment Guide

This guide walks you through deploying the Agentic ERP Automation Quickstart platform to AWS using CDK.

> **Terraform alternative:** See the [Terraform Deployment Guide](TERRAFORM_DEPLOYMENT.md). We recommend choosing one IaC tool and deleting the other directory (`cdk/` or `terraform/`).

> **Auth profiles require the CDK backend.** `make setup` and every non-default auth profile
> (Entra/Okta inbound, M2M/OBO/user-federation outbound, direct-IdP frontend) are CDK-only.
> Terraform deploys `cognito-basic` only and loud-fails any other profile at `terraform plan`.
> Testing an auth-matrix permutation? Use CDK. See [Auth Profile Selection](../sap/AUTH_PROFILE_SELECTION.md#terraform-scope).

## Prerequisites

- **Node.js 20+** ([install guide](https://docs.aws.amazon.com/sdk-for-javascript/v2/developer-guide/setting-up-node-on-ec2-instance.html))
- **Python 3.12+** with **pip**
- **AWS CLI** configured (`aws configure`) — [setup guide](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-quickstart.html)
- **AWS CDK CLI**: `npm install -g aws-cdk` — [getting started](https://docs.aws.amazon.com/cdk/v2/guide/getting-started.html)
- An AWS account with permissions to create: S3, CloudFront, Cognito, Amplify Hosting, Bedrock AgentCore, DynamoDB, SQS, EventBridge, Lambda, IAM, SSM, Secrets Manager, and S3 Vectors resources
- **Bedrock model access enabled** for the Claude models used by the agent, in your target region — [request model access](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html). This is the most common first-deploy failure; requests can take a few minutes to a few hours to approve.

Docker/Finch is **not** required unless you set `deployment_type: docker`.

## Quick Start

The guided setup walks you through everything interactively:

```bash
make setup
```

This runs bootstrap (prerequisites → config → CDK deploy → frontend), then prompts for SAP credentials and knowledge base sync. Allow ~20–30 minutes end-to-end on a first run (CDK deploy alone is 10–20 min) — plus any wait time for Bedrock model access approval if you haven't requested it yet.

Or run the setup wizard directly:

```bash
python scripts/setup.py
```

This checks prerequisites → generates `cdk/config.yaml` → installs CDK deps → `cdk bootstrap` → `cdk deploy --all` → deploys frontend → prints next steps.

After code changes, redeploy with:

```bash
make deploy-all
```

This runs CDK deploy, refreshes all Lambdas (so they pick up new SSM values), and redeploys the frontend. Run `make` to see all available targets.

Or deploy manually — see the step-by-step sections below.

## Configuration

### Minimal config to deploy

Two values are required. Everything else has safe defaults (deployment is `zip`, SAP/MCP off, notifications off, autonomy `manual`/`supervised`). Start here:

```bash
cp cdk/config.yaml.example cdk/config.yaml
```

```yaml
stack_name_base: my-erp-agent        # Names all AWS resources (max 35 chars, hyphens only)
admin_user_email: admin@example.com  # Auto-creates Cognito user and emails credentials
```

With just these set, the platform deploys and runs end-to-end — it just can't process real SAP exceptions until you connect SAP. The sections below are all optional; come back to them as needed.

`stack_name_base` is used as a prefix for every resource, SSM parameter path, and Secrets Manager secret. No underscores — use hyphens (S3 and Cognito reject underscores).

### Full configuration reference

#### 1. Configure SAP connectivity (optional at deploy time)

SAP settings can be configured later. The agent deploys and runs without SAP — it just can't process real exceptions until connected.

```yaml
sap:
  base_url: https://my-sap-host.example.com:443   # SAP OData endpoint (poller)
  poller_schedule: rate(5 minutes)                  # EventBridge schedule for OData polling
```

**How SAP is reached:**
- The `odata_poller` Lambda is the only component that calls SAP directly. It uses service-account Basic Auth, with credentials read from Secrets Manager (set via `./scripts/sync-sap-secret.sh` after deploy).
- All other SAP OData — reads, writes, and discovery — flows through the external **AWS for SAP MCP server**, configured under `sap_mcp:` in `config.yaml.example`.
- Interactive per-user SAP access is handled by that server's USER_FEDERATION (OBO) flow — not by this project.

See [Connectivity & Auth](../sap/CONNECTIVITY_AND_AUTH.md) for networking details and [SAP MCP Integration](../sap/SAP_MCP_INTEGRATION.md) for the external-server setup.

#### 2. Configure notifications (optional)

```yaml
notification:
  channel: ses                              # ses | slack | jira | servicenow
  ses_sender_email: accrual-agent@example.com
```

For Slack/Jira/ServiceNow, store credentials in Secrets Manager and reference via `secret_arn`.

#### 3. Set autonomy controls

```yaml
autonomy:
  trigger_mode: manual      # auto (poller auto-enqueues) | manual (human trigger)
```

These are SSM-backed — changeable at runtime without redeployment via `./scripts/ops/autonomy.sh` or the frontend toggle.

> **Not to be confused with the auth-profile `mode` axis.** The selected `auth_profile`
> also carries a processing-model `mode` axis (`autonomous` / `live` / `batch`). That is a
> deploy-time **constraint**, unrelated to the runtime `trigger_mode` knob above: it
> provisions nothing except `batch`, which requires a token-refresh-capable outbound
> (enforced before deploy) and a **batch runner that is not implemented in this sample** —
> selecting a `batch` profile fails at synth with a clear message. `autonomous` and `live`
> provision nothing and are the default paths.

#### 4. Configure Cedar policy enforcement

```yaml
cedar_enforcement_mode: LOG_ONLY   # LOG_ONLY | ENFORCE
```

Start with `LOG_ONLY` to audit policy decisions in CloudWatch, then switch to `ENFORCE` when ready.

#### 5. Other options

See `cdk/config.yaml.example` for the rest: VPC mode, the `sap_mcp:` external-server integration, demo infrastructure, alarm email, and contact directory.

## Deployment Types

Set `backend.deployment_type` in config.yaml:

| Type | Description |
|------|-------------|
| `zip` (default) | Packages agent code as ZIP via Lambda, uploads to S3. No container runtime needed. |
| `docker` | Builds container image, pushes to ECR. Requires Docker or Finch. |

**Use ZIP** for simplest setup, faster iteration, and higher session throughput. **Use Docker** if you need native C/C++ libraries without ARM64 wheels, packages exceeding 250 MB, or custom OS-level dependencies.

## Step-by-Step Deployment

### 1. Install CDK dependencies

```bash
cd cdk && npm install
```

### 2. Bootstrap CDK (first time only)

```bash
cdk bootstrap
```

### 3. Deploy infrastructure

```bash
cdk deploy --all
```

This creates:
- Cognito User Pool + app client
- AgentCore Runtime (agent container or ZIP)
- AgentCore Gateway with the homegrown tool Lambdas (case_management, notification, knowledge_base, and demo_ticket_management when `demo.ticketing.enabled`), plus a SAP OData MCP target pointing at the external AWS for SAP MCP server (when `sap_mcp.enabled`)
- SQS FIFO queue (agent invocation)
- EventBridge scheduler + OData poller Lambda
- DynamoDB tables (cases, tickets)
- S3 buckets (SOPs, API docs, email)
- Bedrock Knowledge Base + S3 Vectors
- Cedar policy engine Lambda
- SSM parameters for autonomy controls and secret ARNs
- CloudWatch dashboard and alarms

Deployment takes 10–20 minutes.

> **Tip:** If CDK appears silent, add `--progress events` to see CloudFormation events as they happen.

### 4. Deploy frontend

```bash
cd ..  # back to project root
python scripts/deploy/deploy-frontend.py
```

This generates `aws-exports.json` from stack outputs, builds the React app, and deploys to Amplify Hosting. The output prints the app URL.

### 5. Deploy without local tooling (alternative)

If you don't have Node.js or CDK locally:

```bash
python scripts/deploy/deploy-with-codebuild.py
```

This creates a temporary CodeBuild project that runs the full deployment in the cloud. Requires only Python 3.8+ and AWS CLI.

## Post-Deployment Setup

### Create a Cognito user

If you set `admin_user_email` in config, check your email for the temporary password. Otherwise, create a user manually:

1. Open the [Cognito Console](https://console.aws.amazon.com/cognito/)
2. Find `{stack_name_base}-user-pool`
3. Users → Create user → set email + temporary password → mark email as verified

### Sync SAP credentials

```bash
./scripts/sync-sap-secret.sh
```

This reads `sap.base_url` from config.yaml, prompts for username/password, and writes them to Secrets Manager.

### Sync knowledge base

Upload SOPs and SAP API docs to S3 and trigger Bedrock KB re-ingestion:

```bash
./scripts/sync-knowledge-base.sh
```

### Verify the deployment

```bash
cd test-scripts
python3 test-gateway.py    # Verify Gateway tools are reachable
python3 test-agent.py      # Invoke the agent with a test case
python3 test-memory.py     # Verify session memory works
```

Check CloudWatch logs at: `/aws/bedrock-agentcore/runtimes/<agent-name>-DEFAULT`

## Updating

**Infrastructure changes:**

```bash
cd cdk && cdk deploy --all
```

**Frontend changes:**

```bash
python scripts/deploy/deploy-frontend.py
```

**Local frontend dev:**

```bash
./scripts/dev/local-dev.sh config   # pull Cognito/backend values from deployed stacks
cd frontend && npm install && npm run dev
```

Re-run `local-dev.sh config` after any infrastructure redeployment.

**SOPs or API docs:**

```bash
./scripts/sync-knowledge-base.sh
```

**SAP credential rotation:**

```bash
./scripts/sync-sap-secret.sh
```

**Autonomy controls (no redeploy):**

```bash
./scripts/ops/autonomy.sh set trigger-mode auto
```

## VPC Deployment

By default the AgentCore Runtime runs in PUBLIC network mode. To deploy into an existing VPC for private network isolation:

```yaml
backend:
  network_mode: VPC
  vpc:
    vpc_id: vpc-0abc1234def56789a
    subnet_ids:
      - subnet-aaaa1111bbbb2222c
      - subnet-cccc3333dddd4444e
    security_group_ids:       # Optional — default SG created if omitted
      - sg-0abc1234def56789a
```

### What runs inside vs outside the VPC

**Inside the VPC** (your private subnets): the AgentCore Runtime (agent code) and the OData poller Lambda (so it can reach a private/on-prem SAP endpoint). Both reach AWS services through VPC endpoints or a NAT Gateway — see below.

**Outside the VPC** (AWS-managed infrastructure): Gateway tool Lambdas, Bedrock model invocations, frontend (Amplify/CloudFront). The agent reaches these via VPC endpoints, so the network path stays private.

### Required VPC endpoints

| Endpoint | Service | Type |
|----------|---------|------|
| `com.amazonaws.{region}.bedrock-runtime` | Bedrock model invocation | Interface |
| `com.amazonaws.{region}.bedrock-agent-runtime` | AgentCore Runtime | Interface |
| `com.amazonaws.{region}.bedrock-agentcore` | AgentCore Identity (Token Vault) | Interface |
| `com.amazonaws.{region}.bedrock-agentcore.gateway` | AgentCore Gateway | Interface |
| `com.amazonaws.{region}.ssm` | SSM Parameter Store | Interface |
| `com.amazonaws.{region}.secretsmanager` | Secrets Manager | Interface |
| `com.amazonaws.{region}.sqs` | SQS — poller enqueues cases when `trigger_mode: auto` | Interface |
| `com.amazonaws.{region}.logs` | CloudWatch Logs | Interface |
| `com.amazonaws.{region}.ecr.api` | ECR API (docker only) | Interface |
| `com.amazonaws.{region}.ecr.dkr` | ECR Docker (docker only) | Interface |
| `com.amazonaws.{region}.s3` | S3 | Gateway |
| `com.amazonaws.{region}.dynamodb` | DynamoDB | Gateway |
| `com.amazonaws.{region}.xray` | X-Ray (OTel traces) | Interface |

All interface endpoints need private DNS enabled and must be in the same subnets/security groups as the runtime. Add a self-referencing inbound rule (TCP 443, source = same SG) to allow the runtime and the in-VPC poller to reach the endpoints. (The default security group both IaC backends create when you omit `security_group_ids` already includes this rule; if you supply your own SG, add it yourself.)

### VPC egress: endpoints or NAT

The VPC-placed components (runtime + OData poller) need a network path to the AWS services above. Choose **one**:

- **Interface/gateway VPC endpoints (fully private, recommended).** Provision every endpoint in the table — **including SQS**, or the poller's `send_message` hangs whenever `trigger_mode: auto` and cases are never enqueued. No NAT Gateway required, and no traffic leaves the AWS backbone.
- **NAT Gateway.** If you'd rather not manage the full endpoint set, a NAT Gateway in a public subnet lets the in-VPC components reach the AWS APIs over the AWS backbone. Simpler to stand up; you pay hourly + per-GB NAT charges.

Add a NAT Gateway regardless if you introduce custom tools that make outbound **internet** calls (VPC endpoints only cover AWS services), or if your SAP endpoint is reachable only over the public internet while you run in VPC mode.

## Cleanup

```bash
cd cdk && cdk destroy --force
```

This deletes all resources including S3 buckets and DynamoDB tables.

## Troubleshooting

### CDK deploy fails with bundling errors

Ensure `pip` is on your PATH (`pip --version`). If local bundling fails, install Docker or Finch as a fallback — CDK uses it automatically.

### CDK deploy shows no progress

Add `--progress events` for CloudFormation event-by-event output.

### "Architecture incompatible" or "exec format error"

Only applies to `deployment_type: docker`. AgentCore Runtime requires ARM64. On x86 machines:

```bash
docker run --privileged --rm tonistiigi/binfmt --install all
docker buildx create --use --name multiarch --driver docker-container
```

### Authentication errors

Verify the Cognito user exists and email is verified. Redeploy frontend to regenerate `aws-exports.json`:

```bash
python scripts/deploy/deploy-frontend.py
```

### SAP connectivity issues

Check the Lambda's `STACK_NAME_BASE` env var matches `stack_name_base` in config.yaml. Verify SSM parameter `/{stack_name_base}/secrets/sap-credentials-arn` points to the correct secret. Redeploy with `cd cdk && cdk deploy --all`.

## Security Considerations

- Cognito User Pool enforces strong password policies
- All traffic uses HTTPS via CloudFront
- AgentCore Runtime uses JWT authentication
- IAM roles follow least-privilege principles
- Cedar policy engine enforces tool-level authorization independently of the prompt
- SAP access is brokered by the external AWS for SAP MCP server; write enablement and per-user identity (USER_FEDERATION) are governed there. Write gating is enforced by Cedar policy at the Gateway and the external MCP server's write-enablement knobs as defense in depth

For production, consider: MFA on Cognito users, custom domains with your own certificates, `cedar_enforcement_mode: ENFORCE`, and VPC deployment for network isolation.
