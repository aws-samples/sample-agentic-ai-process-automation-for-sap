---
inclusion: always
---

<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->
# Project Overview

Agentic ERP Automation Quick Start — production-ready starter code for autonomous AI agents that automate ERP exception handling, built on FAST (Fullstack AgentCore Solution Template).

## What It Does

An autonomous agent processes SAP finance exceptions across two domains:
- PO Accruals — month-end accrual exceptions, delivery date validation, time-proportional calculations
- AP Invoice Matching — invoice exceptions, PO/GR matching, approval routing

The agent is event-driven: EventBridge scheduler → OData poller → SQS FIFO → agent invoker → Strands agent → Gateway tools (case/KB/notification + SAP OData via the external MCP target).

## Key Concepts

**Skills** — Domain expertise loaded dynamically based on `process_type`. Each skill has a `config.json` (process types, tools, model tier) and `base_prompt.txt` with `{SOP_CONTENT}` placeholder. Located in `skills/<domain>/`. Auto-discovered by `agent/utils/skill_router.py`.

**SOPs** — Standard Operating Procedures stored in S3, injected into the system prompt at runtime. Located in `knowledge-base/sops/<domain>/`. Synced via `make sync-kb`.

**Gateway Tools** — Lambda-backed MCP tools the agent calls via AgentCore Gateway. Each tool is a directory under `gateway/tools/<name>/` with a Lambda handler and `tool_spec.json`. Auto-discovered by CDK.

**Autonomy Controls** — Two SSM-backed toggles flippable without redeployment:
- `trigger-mode`: `auto` (poller auto-enqueues) / `manual` (human trigger)
- `action-mode`: `full-auto` / `supervised` / `read-only`

Enforced at the Lambda level, not just in the prompt. Flip via UI, `make autonomy`, or SSM console.

**SAP Machine Identity** — SAP access uses service-account credentials only. The `odata_poller` Lambda is the sole direct SAP caller (service-account Basic Auth from Secrets Manager). All agent-driven SAP OData (read/write/discovery) goes through the external AWS for SAP MCP server, registered as a Gateway target. Interactive per-user SAP auth is handled by that MCP server's USER_FEDERATION flow, not by this stack.

**Audit Context** — Agent SAP requests carry audit baggage (`x-correlationid`, `x-sap-ext-initiator`, `x-sap-ext-trigger`). Headers propagate from agent → Gateway → tool Lambda via `context.client_context.custom.bedrockAgentCorePropagatedHeaders`.

## Architecture at a Glance

```
EventBridge → odata_poller ──(service-account Basic Auth)──→ SAP OData
                  │
                  └→ SQS FIFO → agent_invoker → Strands Agent
                                                     ↓
                                           AgentCore Gateway
                                           ├── case_management (DynamoDB): get_case_state / update_case_state
                                           ├── knowledge_base (Bedrock KB): search_sap_sops / search_sap_api_docs
                                           ├── notification (SES/Slack/Jira/ServiceNow): send_notification
                                           ├── demo_ticket_management (DynamoDB, demo.enabled only)
                                           └── SAP OData (MCP target → external AWS for SAP MCP server):
                                                 find_sap_services / get_metadata / odata_read /
                                                 odata_create / odata_update / ...
```

## Key Directories

| Directory | What |
|-----------|------|
| `agent/` | Strands agent entry point, skill router, specialist |
| `gateway/tools/` | Gateway Lambda tools (one dir per tool) |
| `lambdas/` | Non-gateway Lambdas (poller, invoker, write consumer, etc.) |
| `skills/` | Domain skill definitions (config.json + base_prompt.txt) |
| `knowledge-base/` | SOPs and SAP API docs (synced to S3) |
| `cdk/` | CDK infrastructure (config.yaml drives everything) |
| `frontend/` | React app (Amplify Hosting) |
| `scripts/` | Deployment, ops, dev, and data scripts |

## Configuration

Everything flows from `cdk/config.yaml`:
- `stack_name_base` — names all resources, SSM paths, secrets
- `sap.*` — base URL (poller service-account target), auth provider
- `notification.channel` — SES/Slack/Jira/ServiceNow
- `cedar_enforcement_mode` — LOG_ONLY or ENFORCE
- `demo.enabled` — opt-in test infrastructure
