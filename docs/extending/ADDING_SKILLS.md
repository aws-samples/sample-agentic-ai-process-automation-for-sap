<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Adding a New Skill

> **Which guide do I need?**
> - **This guide (`ADDING_SKILLS.md`)** — you're adding a skill on top of an existing data pipeline. Case data already arrives (via an existing OData poller, webhook, or manual creation) and you just need the agent to handle a new `process_type`. You write `config.json` + `base_prompt.txt` + SOPs. No poller config, no schema/frontend changes.
> - **[`ADDING_USE_CASES.md`](ADDING_USE_CASES.md)** — you're adding a brand-new domain that has no data source yet and needs its own OData poller config, schema enum entry, and frontend wiring. That guide reuses the skill-creation steps below for its skill phase.

A "skill" is a domain the agent can handle (e.g. `example_finance_accruals`, `finance_ap`). The skill router auto-discovers skills — no agent code changes needed.

## Step-by-Step

### 1. Create the Skill Directory

```bash
mkdir skills/<your_domain>
```

Use `snake_case` for the directory name. This becomes the `skill_id`.

### 2. Create `config.json`

Copy an existing one as a template:

```bash
cp skills/example_finance_accruals/config.json skills/<your_domain>/config.json
```

Edit the fields:

```json
{
  "skill_id": "<your_domain>",
  "display_name": "Human-Readable Name",
  "description": "What this skill handles.",
  "model_tier": "sonnet",
  "max_turns": 45,
  "gateway_tools": [
    "get_case_state",
    "update_case_state",
    "odata_read",
    "odata_create",
    "send_notification"
  ],
  "process_type_to_sop": {
    "your_process_type": "<your_domain>/your_sop.pdf"
  }
}
```

Key fields:
- `gateway_tools` — which tools this skill can use. Homegrown tool names must match `agentcore/gateway/tools/*/tool_spec.json` (e.g. `get_case_state`, `send_notification`, `search_sap_sops`). SAP OData tools (`odata_read`, `odata_create`, `odata_update`, `odata_function_import`, etc.) are served by the external AWS for SAP MCP server target, not a homegrown Lambda — see [`../design-decisions/012-sap-mcp-server-integration.md`](../design-decisions/012-sap-mcp-server-integration.md).
- `process_type_to_sop` — maps each `process_type` value to an SOP file path relative to `knowledge-base/sops/`
- `model_tier` — `haiku` (cheap/fast) or `sonnet` (expensive/smart)

### 3. Create `base_prompt.txt`

```bash
cp skills/example_finance_accruals/base_prompt.txt skills/<your_domain>/base_prompt.txt
```

Edit to describe the domain expertise. Must contain the `{SOP_CONTENT}` placeholder — the skill router injects the SOP here at runtime.

### 4. Add SOPs

Place SOP documents in `knowledge-base/sops/<your_domain>/`:

```bash
mkdir -p knowledge-base/sops/<your_domain>
# Add your SOP files (.txt or .pdf)
```

Then sync to S3:

```bash
./scripts/sync-knowledge-base.sh --sops-only
```

### 5. Deploy

```bash
cd cdk && cdk deploy --all
```

The skill router (`agentcore/agent/utils/skill_router.py`) scans `skills/*/config.json` at startup and registers the new skill automatically.

### 6. Test

Create a case with a `process_type` that matches your `process_type_to_sop` mapping. The agent should route to your new skill and use the SOP you provided.

## Reference

| File | Purpose |
|------|---------|
| `skills/example_finance_accruals/config.json` | Example skill config |
| `skills/example_finance_accruals/base_prompt.txt` | Example base prompt |
| `agentcore/agent/utils/skill_router.py` | Auto-discovery logic |
| `knowledge-base/sops/` | SOP storage (synced to S3) |
