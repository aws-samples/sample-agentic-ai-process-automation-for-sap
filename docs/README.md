<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Documentation

Start here. For one consolidated architectural and implementation reference, use [Technical Context and Decision Reference](TECHNICAL_CONTEXT.md). For task-specific guidance, most people need only the first two sections below.

## New here? Read in this order

1. [Architecture](getting-started/ARCHITECTURE.md) — what the system is and how the pieces fit (10 min)
2. [Deployment](getting-started/DEPLOYMENT.md) — deploy a working agent to your AWS account (~15 min hands-on)
3. [SAP Integration overview](sap/README.md) — connect the agent to your SAP system
4. [Adding a use case](extending/ADDING_USE_CASES.md) — make it do your work

Everything below is reference — reach for it when you have a specific question.

## Getting Started

| Document | When you need it |
|----------|------------------|
| [Architecture](getting-started/ARCHITECTURE.md) | Understand the components and data flow |
| [Deployment Guide](getting-started/DEPLOYMENT.md) | Deploy with CDK (the default path) |
| [Terraform Deployment](getting-started/TERRAFORM_DEPLOYMENT.md) | Deploy with Terraform instead of CDK |
| [Local Development](getting-started/LOCAL_DEVELOPMENT.md) | Run the agent + frontend locally against a deployed stack |
| [Contributing](getting-started/CONTRIBUTING.md) | Conventions, pre-commit, PR workflow |
| [KB Cost Optimization](getting-started/KNOWLEDGE_BASE_COST_OPTIMIZATION.md) | Understand S3 Vectors pay-per-use costs, or drop the knowledge base entirely |

## SAP Integration

Start with the [SAP overview](sap/README.md), which routes you to the right doc. In short:

| Document | When you need it |
|----------|------------------|
| [SAP Overview](sap/README.md) | Index + recommended reading order |
| [Auth Profile Selection](sap/AUTH_PROFILE_SELECTION.md) | Which profile to pick and the single knob to set |
| [Connectivity & Auth](sap/CONNECTIVITY_AND_AUTH.md) | How SAP connectivity and identity work (read first) |
| [Token Mechanics](sap/TOKEN_MECHANICS.md) | Passthrough vs OBO exchange vs USER_FEDERATION vs M2M, untangled |
| [SAP Setup](sap/SAP_SETUP.md) | Configure the connection and sync the service account |
| [SAP System Configuration](sap/SAP_SYSTEM_CONFIGURATION.md) | SAP-side setup: service-account user + OData activation |
| [SAP MCP Integration](sap/SAP_MCP_INTEGRATION.md) | Wire up the external AWS for SAP MCP server (all OData) |
| [User Federation](sap/SAP_MCP_USER_FEDERATION.md) · [Same-Sub Federation](sap/SAP_MCP_SAME_SUB_FEDERATION.md) | Only if you need interactive per-user SAP access |
| [Okta Setup](sap/OKTA_SETUP.md) | Okta as the direct-IdP frontend/inbound provider |
| [BTP Hosting](sap/BTP_HOSTING.md) | Deploying when SAP runs on BTP |
| [Operator Runbooks](sap/runbooks/README.md) | Per-flow SAP-side operator steps (OBO, M2M, UF-OIDC, UF-SAML, UF-OAuth2) |

## Extending the System

Not sure which to use? Each doc opens with a "which guide do I need?" block.

| Document | When you need it |
|----------|------------------|
| [Adding Skills](extending/ADDING_SKILLS.md) | Add a skill to an existing data pipeline (config + SOP only) |
| [Adding Use Cases](extending/ADDING_USE_CASES.md) | Add a brand-new domain with its own OData poller config |
| [Adding Gateway Tools](extending/ADDING_GATEWAY_TOOLS.md) | Add a homegrown Lambda tool to the Gateway |
| [A2A & Joule Integration](extending/A2A_JOULE_INTEGRATION.md) | Expose the agent via A2A for Joule / cross-org interop |

## Agent Internals (reference)

| Document | Topic |
|----------|-------|
| [Agent Configuration](agent/AGENT_CONFIGURATION.md) | Skill routing, multi-agent pattern, autonomy controls |
| [Gateway](agent/GATEWAY.md) | Gateway tool development and the Lambda-target pattern |
| [Runtime & Gateway Auth](agent/RUNTIME_GATEWAY_AUTH.md) | OAuth2 M2M auth between Runtime and Gateway |
| [Memory Integration](agent/MEMORY_INTEGRATION.md) | AgentCore Memory setup |
| [Streaming](agent/STREAMING.md) | Streaming response handling |

## Evaluations & Cost

| Document | Topic |
|----------|-------|
| [Quick Start](evaluations/EVALUATIONS_QUICKSTART.md) | Run the regression suite; set up online evals (start here) |
| [Cost Benchmark](evaluations/COST_BENCHMARK.md) | Historical ~$0.26/case baseline and methodology |
| [August 2026 Benchmark Analysis](evaluations/AP_COST_BENCHMARK_2026_08.md) | Why the lifecycle-complete rerun reached ~$0.52/case and what changed |
| [Inference Cost Optimization](evaluations/INFERENCE_COST_OPTIMIZATION.md) | Six levers to drive per-case cost down to ~$0.08 |
| [Full Guide](evaluations/AGENTCORE_EVALUATIONS_GUIDE.md) | Deep reference: custom evaluators for this agent |

## Security

| Document | Topic |
|----------|-------|
| [Input Sanitization](security/INPUT_SANITIZATION.md) | Prompt-injection defense: content filtering and fencing |
| [Autonomy Controls](security/AUTONOMY_CONTROLS.md) | SSM write restriction, CloudTrail audit, change alarms |
| [Webhook Verification](security/WEBHOOK_VERIFICATION.md) | Inbound webhook signature verification and rate limiting |

## Design Decisions (ADRs)

Architecture Decision Records capture *why* the system is built the way it is. Newcomers can skip these; reach for one when a design choice is unclear. [ADR-012](design-decisions/012-sap-mcp-server-integration.md) is the current ground truth for SAP integration; [ADR-003](design-decisions/003-domain-skills-s3-sops.md) explains the skill system.

See [design-decisions/](design-decisions/) for all ADRs (001–014). ADRs 008, 010, and 011 are historical or partly superseded by ADR-012; ADR-013 supersedes ADR-002's OpenSearch Serverless storage choice; ADR-014 covers SOP corpus granularity and chunking strategy.

## Comparison Docs

| Document | Topic |
|----------|-------|
| [Lambda vs MCP](comparison-docs/lambda-vs-mcp.md) | Direct Lambda vs Gateway vs self-hosted MCP, with a token-overhead benchmark |
