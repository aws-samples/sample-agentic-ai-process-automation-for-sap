---
inclusion: always
---

<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->
# Extending the Agent System

This project is a multi-skill autonomous agent for ERP exception handling. When adding new capabilities, files go in specific places and follow existing conventions. Always read an existing example in each directory before creating new ones.

## Adding a New Domain Skill

A "skill" = a domain the agent can handle (e.g. example_finance_accruals, finance_ap).

1. **Skill definition** → `skills/<domain>/`
   - `config.json` — skill_id, display_name, model_tier, gateway_tools list, process_type_to_sop mapping. Copy an existing one (e.g. `skills/example_finance_accruals/config.json`).
   - `base_prompt.txt` — domain-specific system prompt. Must contain `{PLATFORM_MECHANICS}` (where the shared `skills/_platform_prompt.txt` is injected) and `{SOP_CONTENT}` (where the routed SOP is injected). Do not restate the shared mechanics — `make test` fails on a copy.

2. **SOP document** → `knowledge-base/sops/<domain>/<sop_name>.txt`
   - One SOP per process_type. The `config.json` → `process_type_to_sop` maps process types to these files.
   - Use `@author-sop` power (in `.kiro/powers/author-sop-power/`) to draft SOPs with correct RFC 2119 structure.

3. **SAP API docs** (if new SAP APIs are involved) → `knowledge-base/sap-api-docs/`
   - YAML specs or markdown guides for the SAP OData endpoints the skill will call.

No agent code changes needed — `agent/utils/skill_router.py` auto-discovers skills by scanning `skills/*/config.json`.

## Adding a New Gateway Tool

Gateway tools are Lambda-backed MCP tools the agent calls via AgentCore Gateway.

1. **Tool Lambda** → `gateway/tools/<tool_name>/`
   - `<tool_name>_lambda.py` — handler function. Uses `context.client_context.custom['bedrockAgentCoreToolName']` to route by tool name.
   - `tool_spec.json` — MCP tool schema (name, description, inputSchema with JSON Schema properties/required).
   - Optional: `requirements.txt` if the Lambda needs extra dependencies.
   - Copy `gateway/tools/notification/` as a minimal template.

2. **CDK registration** — The backend stack (`cdk/lib/backend-stack.ts`) auto-discovers tools in `gateway/tools/`, so just adding the directory is usually enough. Check the CDK stack if the tool needs special IAM permissions or environment variables.

3. **Propagated headers** — To access user identity or audit context, read from the Lambda context:
   ```python
   headers = context.client_context.custom.get("bedrockAgentCorePropagatedHeaders", {})
   ```
   Available headers: `x-user-token`, `x-audit-correlation-id`, `x-audit-initiator`, `x-audit-trigger`.

4. **Wire to skill** — Add the tool's name to the `gateway_tools` array in the relevant `skills/<domain>/config.json`.

## Adding a Standalone Lambda

Lambdas that aren't gateway tools (pollers, processors, APIs) go in `lambdas/<lambda_name>/`:
- `<lambda_name>_lambda.py` (or `index.py`) — handler
- `requirements.txt` if needed
- CDK construct in `cdk/lib/` wires it up (EventBridge, SQS, API Gateway, etc.)

## Naming Conventions

- Directories: `snake_case` (e.g. `example_finance_accruals`, `case_management`, `notification`)
- skill_id in config.json matches the directory name under `skills/`
- SOP paths in config.json are relative to `knowledge-base/sops/`
- Tool names in tool_spec.json use `snake_case` (e.g. `send_notification`, `update_case_state`)

## Key Files for Reference

| What | Where | Read first |
|------|-------|------------|
| Skill config example | `skills/example_finance_accruals/config.json` | |
| Base prompt example (domain-only) | `skills/example_finance_accruals/base_prompt.txt` | |
| Shared platform mechanics | `skills/_platform_prompt.txt` | |
| SOP example | `knowledge-base/sops/example_finance_accruals/po_accrual.txt` | |
| Gateway tool example | `gateway/tools/notification/` | |
| Tool spec example | `gateway/tools/notification/tool_spec.json` | |
| Skill router (auto-discovery) | `agent/utils/skill_router.py` | |
| CDK backend stack | `cdk/lib/backend-stack.ts` | |
| SOP authoring power | `.kiro/powers/author-sop-power/author-sop.md` | |
