<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Agent Configuration Guide

This project supports any agent framework that can run in a container. This guide covers how to use existing patterns, configure the multi-skill system, and extend the agent with new domains.

---

## Multi-Skill Architecture

The primary agent (`agent/`) uses a **Skill Router** to dynamically load domain expertise at runtime based on the `process_type` field in the incoming case payload.

### How It Works

1. A case arrives with a `process_type` (e.g. `po_accrual`, `invoice_matching`)
2. `skill_router.py` scans `skills/*/config.json` to find the matching skill
3. The skill's `base_prompt.txt` is loaded (domain expertise)
4. The matching SOP is fetched from S3 and injected into the prompt at `{SOP_CONTENT}`
5. The assembled system prompt + skill config is returned to the agent

This means **adding a new ERP domain requires no agent code changes** — only a new skill directory and SOP.

### Skill Directory Structure

```
skills/
├── _platform_prompt.txt      # Shared platform mechanics, injected into every skill
├── example_finance_accruals/
│   ├── config.json           # Skill metadata, process_type mappings, model tier
│   └── base_prompt.txt       # Domain persona only, with {PLATFORM_MECHANICS} + {SOP_CONTENT}
└── finance_ap/
    ├── config.json
    └── base_prompt.txt
```

`_platform_prompt.txt` holds everything that is a property of the deployment rather than a
domain: tool names, OData query scoping, write semantics, the escalation/ticket protocol, the
SOP-citation convention, and how to weigh what the optional precedent and vendor-risk tools
return. The router substitutes it at `{PLATFORM_MECHANICS}`, so it is edited in one place and
reaches every skill. It is not a skill directory, so skill discovery (`skills/*/config.json`)
ignores it.

A Gateway tool listed in a skill's `gateway_tools` but described in no prompt is reachable and
ungoverned — the tool's own description is then the only thing the model sees, and a description
cannot say when *not* to call something. `tests/unit/test_agent_knowledge_wiring.py` enforces
this for the agent-knowledge tools.

### Skill config.json Fields

```json
{
  "skill_id": "example_finance_accruals",
  "display_name": "Finance — Accruals & Month-End",
  "description": "...",
  "model_tier": "sonnet",        // "haiku" | "sonnet" | "opus"
  "max_turns": 15,          // turn ceiling; measured need is 5-7 (ADR-005)
  "multi_agent": false,          // true = use orchestrator+specialist pattern (ADR-007)
  "orchestrator_tier": "haiku",  // used when multi_agent: true
  "specialist_tier": "sonnet",   // used when multi_agent: true
  "sap_service": {               // optional: pin SAP service + entities to skip runtime discovery
    "service": "API_SUPPLIERINVOICE_PROCESS_SRV",
    "entities": { "supplier_invoice": "A_SupplierInvoice" }
  },
  "constants": {                 // tunable thresholds, referenced as {{SYMBOL}} in the SOP
    "PRICE_VARIANCE_PCT": 2,     // resolved at runtime from here, NOT baked into SOP text
    "SLA_ROUTING_RESPONSE": 3
  },
  "gateway_tools": [             // Gateway Lambda tools the agent is allowed to call
    "search_sap_api_docs",
    "search_sap_sops",
    "get_case_state",
    "update_case_state",
    "send_notification"
  ],
  // SAP OData read/write is via the external AWS for SAP MCP server target, not a Gateway tool (see ADR-012).
  "process_type_to_sop": {       // maps process_type → S3 SOP key; every target must exist
    "po_accrual": "example_finance_accruals/po_accrual.pdf",
    "tooling_accrual": "example_finance_accruals/po_accrual.pdf"
  }
}
```

### Adding a New Skill

1. Create `skills/<domain>/config.json` with the fields above
2. Create `skills/<domain>/base_prompt.txt` with the domain persona and the `{PLATFORM_MECHANICS}` + `{SOP_CONTENT}` placeholders — do not restate anything from `_platform_prompt.txt`
3. Upload the SOP PDF to `knowledge-base/sops/<domain>/` and run `make sync-kb` to sync
4. `cdk deploy` is not required — the skill is discovered at runtime

> **Turn cap:** `max_turns` is 15 for every skill, enforced as a ceiling by `scripts/dev/validate_domain_configs.py`. [ADR-005](../design-decisions/005-cost-optimization-model-routing.md) proposed 20 for AP/AR and 25 for accruals; the benchmark then measured 5–7 turns per invocation ([INFERENCE_COST_OPTIMIZATION.md](../evaluations/INFERENCE_COST_OPTIMIZATION.md)), so the shipped cap is lower than the ADR's. The cap is a runaway-cost brake, not a budget — a case that needs more turns than this is looping.

> **Tunable values:** thresholds, SLAs, and weights go in `constants` and are referenced as `{{SYMBOL}}` in the SOP — resolved at runtime, so tuning a value never requires editing/re-syncing the SOP. `config.json` holds the deploy-time default; an operator can override it without a deploy through the Settings page, which writes the config table that `agentcore/agent/utils/config_overrides.py` reads. Both substitution paths — the agent's `skill_router` and the `load_sop` Gateway tool — read the same overrides, so an edit cannot change the injected prompt while leaving a mid-case `load_sop` on the old value. An absent, empty, or unreadable table resolves the deployed default rather than blanking a threshold. How SOPs are chunked in the vector KB is configurable via `knowledge_base.sops_chunking_strategy` (default `NONE` = whole-SOP). See [ADR-014](../design-decisions/014-sop-corpus-chunking.md).

---

## Existing Agent Patterns

### Strands Single Agent (Primary)

**Location**: `agent/`

The production agent for SAP exception processing. Uses the Strands framework with AgentCore Memory, the Skill Router, and AgentCore Gateway tools.

**Key files**:
- `basic_agent.py` — Agent entry point, skill routing, memory integration, streaming
- `requirements.txt` — Python dependencies
- `Dockerfile` — Container definition (used for `deployment_type: docker`)

**Model configuration** (`basic_agent.py`):

The model is determined per-skill via `config.json`'s `model_tier`. The mapping is defined in `basic_agent.py`:

```python
MODEL_TIERS = {
    "haiku":  "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "sonnet": "us.anthropic.claude-sonnet-5",
}
```

**Fallback (chat mode)**: When no `process_type` is provided, the agent uses a general SAP expert prompt and lets the user describe their exception.

### Multi-Agent Pattern (Orchestrator + Specialist)

Enabled per-skill via `"multi_agent": true` in `config.json`. See [ADR-007](../design-decisions/007-multi-agent-orchestrator-specialist.md) for the full design.

- **Orchestrator** (Haiku) — Owns the event loop, follows SOP steps, calls Gateway tools
- **Specialist** (Sonnet) — Stateless reasoning agent invoked as a tool for ambiguous tasks

The specialist is implemented in `agentcore/agent/utils/specialist.py` and exposed as a Strands tool.

---

## Autonomy Controls

One SSM parameter controls agent behavior at runtime without redeployment:

| SSM Parameter | Values | Effect |
|---------------|--------|--------|
| `/<stack>/autonomy/trigger-mode` | `auto` \| `manual` | `auto`: unattended callers (the poller, and the `mode: batch` sweeper if provisioned) enqueue cases. `manual`: cases wait for human to click "Process" in the UI. |

The parameter is seeded on every deployment, but the poller that consumes it is built only when the selected auth profile declares `autonomous`. On any other profile a stored `auto` is inert — `GET /autonomy` returns `autonomous-capable: false` alongside the mode so callers can tell the two apart, and `PUT /autonomy` is not mounted at all.

**Change via CLI:**
```bash
python3 launch.py autonomy set auto
python3 launch.py autonomy  # show current values
```

**Change via UI:** the Autonomy section in Settings. Leaving `auto` is one click; arming it requires typing `AUTO` to confirm.

---

## Gateway Tools

The agent calls SAP and other services through AgentCore Gateway Lambda tools. Tools are auto-discovered from `agentcore/gateway/tools/` at CDK deploy time.

| Tool | Lambda | Description |
|------|--------|-------------|
| `get_case_state` / `update_case_state` | `case_management/case_management_lambda.py` | Read/write case state in DynamoDB |
| `send_notification` | `notification/notification_lambda.py` | Send via SES, Jira, or ServiceNow |
| `search_sap_api_docs` / `search_sap_sops` | `knowledge_base/knowledge_base_lambda.py` | Search Bedrock KB for SAP API docs and SOPs |
| `load_sop` | `knowledge_base/knowledge_base_lambda.py` | Fetch a whole SOP by `process_type` from S3 — the deterministic path for a jump to another process type's SOP, where vector search would return fragments |
| `demo_create_ticket` / `demo_get_ticket` | `demo_ticket_management/ticket_management_lambda.py` | Demo ticketing backend — update/list are human-only, via `lambdas/demo_tickets/index.py` and the Tickets dashboard |

> **SAP OData access (read and write) is not a Gateway Lambda tool.** It is provided exclusively via the external AWS for SAP MCP server target. See [ADR-012](../design-decisions/012-sap-mcp-server-integration.md).

### Adding a New Gateway Tool

1. Create `agentcore/gateway/tools/<tool_name>/` with:
   - `<tool_name>_lambda.py` — Lambda handler
   - `tool_spec.json` — MCP tool specification (name, description, input schema)
2. `cdk deploy` — the backend stack auto-discovers and registers the new tool

---

## Observability

The agent emits custom CloudWatch metrics via `agentcore/agent/utils/agent_metrics.py`:

- `AgentInvocations` — total invocations
- `AgentErrors` — error count
- `AgentLatencyMs` — end-to-end latency
- `AgentTurns` — number of model turns per invocation

A CloudWatch dashboard and alarms are provisioned by `cdk/lib/constructs/observability.ts`. Set `alarm_email` in `config.yaml` to receive SNS alerts.

---

## Creating Your Own Agent Pattern

### Step 1: Create Pattern Directory

```bash
mkdir -p patterns/my-custom-agent
```

### Step 2: Implement Your Agent

```python
from bedrock_agentcore.runtime import BedrockAgentCoreApp, RequestContext
from utils.auth import extract_user_id_from_context

app = BedrockAgentCoreApp()

@app.entrypoint
async def agent_handler(payload, context: RequestContext):
    user_query = payload.get("prompt")
    user_id = extract_user_id_from_context(context)
    # your logic here
    yield response

if __name__ == "__main__":
    app.run()
```

### Step 3: Update config.yaml

```yaml
backend:
  pattern: my-custom-agent
```

### Step 4: Deploy

See the [Deployment Guide](../getting-started/DEPLOYMENT.md) for complete deployment instructions.
t instructions.
