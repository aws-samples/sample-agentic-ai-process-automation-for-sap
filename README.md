<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Agentic ERP Automation Quickstart

![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue) ![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue) ![Node 20+](https://img.shields.io/badge/node-20%2B-blue) ![Built with AWS CDK](https://img.shields.io/badge/IaC-AWS%20CDK-orange)




> [!WARNING]
> This is a reference implementation intended for demonstration purposes. Review and adapt it — especially auth, autonomy controls, and SAP write paths — before deploying to a production environment. See [NOTICE](NOTICE) for details.
>
> This is sample code, for non-production usage. You should work with your security and legal teams to meet your organizational security, regulatory and compliance requirements before deployment.

![Agent chat UI](frontend/readme-imgs/fast-chat-screenshot.png)

**Jump to:** [Quick Start](#quick-start) · [Architecture](#architecture) · [Key Features](#key-features) · [Extending](#extending) · [Docs](#documentation)

## Included Use Case: SAP Finance Exception Processing

A multi-skill autonomous agent that processes SAP finance exceptions across domains:

- **PO Accruals** — Detects month-end accrual exceptions, validates delivery dates, calculates time-proportional accruals, updates SAP schedule lines, creates parked journal entries
- **AP Invoice Matching** — Processes invoice exceptions, validates PO/GR matching, routes for approval

The agent is driven by Standard Operating Procedures (SOPs) stored in S3 and dynamically loaded at runtime based on the exception type. New domains are added by dropping in a skill config + SOP — no agent code changes (see [Adding Use Cases](docs/extending/ADDING_USE_CASES.md)).

## Architecture

![Agentic ERP Automation Quickstart Architecture Diagram](docs/getting-started/QUICKSTART_ARCHITECTURE_DIAGRAM.png)

## Quick Start

Deploys all AWS infrastructure, a Cognito login, and a working agent you can chat with. SAP is optional — the agent deploys and runs without it.

Plan for ~20–30 minutes end-to-end (CDK deploy alone is 10–20 min), plus any wait for Bedrock model access approval. Running cost: ~$0.26/case processed ([benchmark](docs/evaluations/COST_BENCHMARK.md)); idle infrastructure cost is low (serverless, pay-per-use).

### Prerequisites

- Node.js 20+, npm
- Python 3.12+
- AWS CLI (configured with appropriate permissions)
- No global CDK install needed — the pinned version comes from `cdk/package.json`
- **Bedrock model access enabled** for Claude in your target region — [request access](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html) before you start.

> [!IMPORTANT]
> Missing Bedrock model access is the most common first-deploy failure. Request it before you start — approval can take a few minutes to a few hours. `python3 launch.py doctor` will tell you whether the Bedrock API is reachable, but only the console can confirm the model grants.

### First-Time Setup

The guided launcher walks you through everything — prerequisites, config, deploy, frontend, and the optional SAP and knowledge-base steps:

```bash
python3 launch.py
```

That's the whole happy path. It needs nothing installed beyond the prerequisites above, and nothing is written to AWS until it shows you the target account and Region and you confirm. Only two config values are required to start: `stack_name_base` and `admin_user_email`. Everything else has safe defaults.

Useful on their own:

```bash
python3 launch.py doctor      # check prerequisites and AWS access; changes nothing
python3 launch.py configure   # generate cdk/config.yaml
python3 launch.py status      # what is deployed, with endpoints
python3 launch.py resume      # continue an interrupted launch
python3 launch.py --help      # every command
```

Prefer to run each step yourself:

```bash
cp cdk/config.yaml.example cdk/config.yaml   # edit: stack_name_base, admin_user_email
cd cdk && npm ci && npx cdk deploy --all     # deploy the stacks
python3 scripts/deploy/deploy-frontend.py    # build and deploy the frontend
python3 launch.py sync-sap                   # (optional) sync SAP service-account creds
python3 launch.py sync-kb                    # sync SOPs + API docs to S3
```

Full walkthrough, including auth-profile options and troubleshooting: [Deployment Guide](docs/getting-started/DEPLOYMENT.md).

### Redeploy After Code Changes

```bash
python3 launch.py deploy
```

This deploys the CDK stacks, refreshes all Lambdas (so they pick up new SSM values), and redeploys the frontend. It confirms the target account and Region first; add `--yes` for unattended runs.

### Make targets

`make` is the contributor entry point — linting, tests, type generation, and packaging. Run `make` to see everything, grouped by category. Its deploy and operate targets delegate to the launcher, so `make deploy-all` and `python3 launch.py deploy` do the same thing.

See [Deployment Guide](docs/getting-started/DEPLOYMENT.md) for full instructions, [scripts/README.md](scripts/README.md) for all available scripts.

## Key Features

- **Multi-Skill Agent** — Dynamically loads domain expertise based on exception type. Each skill has a `config.json`, `base_prompt.txt`, and SOPs injected at runtime. Auto-discovered, no code changes to add new domains.
- **Managed SAP OData via MCP** — the agent reaches SAP (reads, writes, discovery) through the external [AWS for SAP MCP Server](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/introduction.html): service discovery, metadata inspection, and OData read/write/function-import tools. Our CDK is a thin adapter (Gateway target + OAuth2 provider) pointed at a customer-deployed SAP MCP stack; write enablement lives on that stack. See [ADR-012](docs/design-decisions/012-sap-mcp-server-integration.md).
- **Autonomy Controls** — `trigger-mode` (`auto` / `manual`) is an SSM-backed toggle, flippable without redeployment from Settings or the CLI, governing whether the poller auto-enqueues detected cases. Settings states what the mode has actually been doing and requires typing `AUTO` to arm. It gates *initiation*, not SAP writes — write gating lives in the Cedar policies at the Gateway and in the MCP server's write-enable flags. See [Autonomy controls](docs/security/AUTONOMY_CONTROLS.md).
- **Pluggable Notifications** — SES, Jira, or ServiceNow — one config value swap in `config.yaml`.
- **Ticket Management** — Built-in escalation and approval workflows correlated to ERP cases.
- **SAP Connectivity & Identity** — Reference-only networking (you manage VPC/peering/VPN). The agent reaches SAP through the external AWS for SAP MCP server (reads + writes + discovery); the autonomous poller uses a service-account. See [SAP docs](docs/sap/CONNECTIVITY_AND_AUTH.md).
- **Pluggable Enterprise Auth** — one config value (`auth_profile`) selects a full frontend/inbound/outbound identity path: Cognito + service-account for POC, or Entra/Okta-backed per-user identity (M2M, user federation, or seamless OBO token exchange) for production SAP access. See [Auth Profile Selection](docs/sap/AUTH_PROFILE_SELECTION.md).
- **Cedar Policy Engine** — Gateway authorization via deterministic Cedar policies. See [ADR-004](docs/design-decisions/004-cedar-policy-engine.md).
- **OData Discovery via MCP** — the SAP MCP server's `find_sap_services` / `get_metadata` / `get_service_hints` tools handle service discovery and `$metadata` inspection at runtime; no homegrown spec cache.

## Extending

Add a new exception type: create `skills/<domain>/config.json` + `base_prompt.txt`, upload SOPs, `cdk deploy`. No agent code changes.

Add a new Gateway tool: create `gateway/tools/<name>/` with handler + `tool_spec.json`, `cdk deploy`. Auto-discovered by CDK.

See [Adding Use Cases](docs/extending/ADDING_USE_CASES.md) for the full end-to-end guide.

## Project Structure

See [Contributing Guide](docs/getting-started/CONTRIBUTING.md#project-layout) for the full directory tree. Key directories:

| Directory | What lives there |
|-----------|-----------------|
| `agentcore/` | Agent code (Strands SDK), Gateway tools, Cedar policies, evals |
| `lambdas/` | All Lambda functions: pollers, APIs, webhooks, custom resources |
| `skills/` | Domain skill configs + base prompts (auto-discovered), plus `_platform_prompt.txt` — the platform mechanics injected into every skill |
| `knowledge-base/` | SOPs + SAP API docs (synced to S3) |
| `cdk/` | CDK infrastructure (primary IaC path) |
| `frontend/` | React app (Amplify Hosting) |
| `docs/` | All documentation ([start here](docs/README.md)) |

## Built With

- [Amazon Bedrock AgentCore](https://aws.amazon.com/bedrock/agentcore/) — Runtime, Gateway, Memory, Identity
- [AWS for SAP MCP Server](https://docs.aws.amazon.com/mcp-sap/latest/awsforsapmcp/introduction.html) — Managed SAP OData MCP tools (optional)
- [Strands Agents SDK](https://github.com/awslabs/strands-agents) — Agent framework
- [FAST](https://github.com/awslabs/fullstack-solution-template-for-agentcore) — Fullstack template
- [AWS CDK](https://aws.amazon.com/cdk/) / [Terraform](https://www.terraform.io/) — Infrastructure as Code
- [Cedar](https://www.cedarpolicy.com/) — Policy-based authorization for Gateway tools

## Documentation

Full documentation index: [docs/README.md](docs/README.md)

| Category | Key Documents |
|----------|---------------|
| Getting Started | [Architecture](docs/getting-started/ARCHITECTURE.md) · [Deployment](docs/getting-started/DEPLOYMENT.md) · [Terraform](docs/getting-started/TERRAFORM_DEPLOYMENT.md) · [Local Dev](docs/getting-started/LOCAL_DEVELOPMENT.md) · [Contributing](docs/getting-started/CONTRIBUTING.md) |
| SAP Integration | [Overview](docs/sap/README.md) · [Auth Profile Selection](docs/sap/AUTH_PROFILE_SELECTION.md) · [Connectivity & Auth](docs/sap/CONNECTIVITY_AND_AUTH.md) · [SAP Setup](docs/sap/SAP_SETUP.md) · [SAP MCP Integration](docs/sap/SAP_MCP_INTEGRATION.md) |
| Agent Internals | [Configuration](docs/agent/AGENT_CONFIGURATION.md) · [Gateway](docs/agent/GATEWAY.md) · [Auth](docs/agent/RUNTIME_GATEWAY_AUTH.md) · [Memory](docs/agent/MEMORY_INTEGRATION.md) · [Streaming](docs/agent/STREAMING.md) |
| Extending | [Adding Use Cases](docs/extending/ADDING_USE_CASES.md) · [Adding Skills](docs/extending/ADDING_SKILLS.md) · [Adding Tools](docs/extending/ADDING_GATEWAY_TOOLS.md) |
| Evaluations | [Quick Start](docs/evaluations/EVALUATIONS_QUICKSTART.md) · [Cost Benchmark](docs/evaluations/COST_BENCHMARK.md) · [Full Guide](docs/evaluations/AGENTCORE_EVALUATIONS_GUIDE.md) |
| Security | [Input Sanitization](docs/security/INPUT_SANITIZATION.md) · [Autonomy Controls](docs/security/AUTONOMY_CONTROLS.md) · [Webhook Verification](docs/security/WEBHOOK_VERIFICATION.md) |
| Design Decisions | [ADR-001](docs/design-decisions/001-gateway-over-self-hosted-mcp.md)–[014](docs/design-decisions/014-sop-corpus-chunking.md) |

## Contributing

New to the project? See [CONTRIBUTING.md](docs/getting-started/CONTRIBUTING.md) for setup instructions, project structure, and contribution guidelines.

## License

Apache-2.0
