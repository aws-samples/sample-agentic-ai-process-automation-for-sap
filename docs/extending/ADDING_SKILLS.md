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
  "max_turns": 15,
  "gateway_tools": [
    "get_case_state",
    "update_case_state",
    "odata_read",
    "odata_create",
    "send_notification"
  ],
  "constants": {
    "YOUR_THRESHOLD_PCT": 5,
    "YOUR_SLA_DAYS": 3
  },
  "process_type_to_sop": {
    "your_process_type": "<your_domain>/your_sop.pdf"
  }
}
```

Key fields:
- `gateway_tools` — which tools this skill can use. Homegrown tool names must match `agentcore/gateway/tools/*/tool_spec.json` (e.g. `get_case_state`, `send_notification`, `search_sap_sops`). SAP OData tools (`odata_read`, `odata_create`, `odata_update`, `odata_function_import`, etc.) are served by the external AWS for SAP MCP server target, not a homegrown Lambda — see [`../design-decisions/012-sap-mcp-server-integration.md`](../design-decisions/012-sap-mcp-server-integration.md).
- `process_type_to_sop` — maps each `process_type` value to an SOP file path relative to `knowledge-base/sops/`
- `model_tier` — `haiku` (cheap/fast) or `sonnet` (expensive/smart)
- `constants` — tunable thresholds/SLAs, referenced as `{{SYMBOL}}` placeholders in the SOP and resolved at runtime from here (so tuning a value never requires editing the SOP). See the SOP Corpus Patterns section below.

### 3. Create `base_prompt.txt`

Write **only** the domain expertise: the persona, the workflow pattern, and rules specific to this domain's documents and calculations. Two placeholders are required, and the skill router substitutes both at assembly time:

| Placeholder | What the router injects |
|-------------|-------------------------|
| `{PLATFORM_MECHANICS}` | `skills/_platform_prompt.txt` — tool names, OData query parameters, write semantics, escalation/ticket protocol, the SOP-citation convention, how to weigh the optional precedent/vendor-risk tools, and the pinned `sap_service` from your `config.json` |
| `{SOP_CONTENT}` | The routed SOP for this case's `process_type` |

Do **not** restate anything from `_platform_prompt.txt`. Those instructions are platform-wide, they reach every skill already, and a per-skill copy is how the previous prompts drifted into telling the agent to rediscover a service that was already pinned. `make test` fails on a `base_prompt.txt` that duplicates them.

`skills/example_finance_accruals/base_prompt.txt` is the shape to follow.

### 4. Add SOPs

Place SOP documents in `knowledge-base/sops/<your_domain>/`:

```bash
mkdir -p knowledge-base/sops/<your_domain>
# Add your SOP files (.txt or .pdf)
```

Open each one with a `Version N.N` line in the header block:

```
QUANTITY VARIANCE — INVOICE EXCEPTION RESOLUTION
STANDARD OPERATING PROCEDURE (SOP)
Version 1.0
```

The router reads that line and records it on every trace, so a case says which
revision it was decided under after the SOP is revised.

Numbering is optional. The agent is told to cite the rule it acted on by quoting
the sentence verbatim, and the platform verifies that quote against the SOP text
the run was given — so an unnumbered document is cited and verified exactly like a
numbered one. Where clauses *are* numbered as `N.N`, two or more spaces, then a
capital letter, the number is recorded alongside the quote as a locator:

```
3.2  IF the variance is ABOVE tolerance AND invoice_qty < gr_qty (under-billing):
```

Write in whole sentences that stand on their own. A rule split across a bulleted
fragment and its parent line has no single sentence to quote.

Then sync to S3:

```bash
python3 launch.py sync-kb --only sops
```

### 5. Deploy

```bash
cd cdk && cdk deploy --all
```

The skill router (`agentcore/agent/utils/skill_router.py`) scans `skills/*/config.json` at startup and registers the new skill automatically.

### 6. Test

Create a case with a `process_type` that matches your `process_type_to_sop` mapping. The agent should route to your new skill and use the SOP you provided.

## SOP Corpus Patterns (chunking & size)

SOPs reach the agent three ways. The skill router injects the **whole** routed SOP into the prompt (primary). The `load_sop` Gateway tool fetches a whole SOP by `process_type` from S3, for the case that turns out to be a different process type mid-run — deterministic, and it resolves the same `{{SYMBOL}}` overrides the injected copy does. `search_sap_sops` does vector lookup across the corpus, for questions the loaded SOP does not answer. Only the vector path is chunked, and it's configurable in `config.yaml`:

```yaml
knowledge_base:
  sops_chunking_strategy: NONE   # NONE (default) | FIXED_SIZE | SEMANTIC
```

Pick by corpus shape:

| Your SOPs | Strategy | Why |
|-----------|----------|-----|
| Short / atomic (one per `process_type`) | `NONE` (default) | One vector per SOP → whole-SOP retrieval, never fragments mixed across SOPs. Cleanest audit story. Requires each SOP to fit ~50k chars (Titan v2). |
| Long, well-sectioned | `SEMANTIC` | Structure-aware chunks for SOPs over the embedding limit. |
| Very large / fixed-format | `FIXED_SIZE` | Tune `sops_chunk_max_tokens` / `sops_chunk_overlap_percentage`. |
| Multimodal (diagrams, scans) | parse first | Text-only ingest drops figures; needs BDA/Textract + a multimodal embedding (Cohere Embed v4). |

Tunable thresholds belong in `config.json → constants` (referenced as `{{SYMBOL}}` in the SOP), not baked into SOP text — so a value change never requires re-authoring the document, and an operator can retune it from the Settings page without a deploy. Full rationale and the large/multimodal path: [ADR-014](../design-decisions/014-sop-corpus-chunking.md).

## Reference

| File | Purpose |
|------|---------|
| `skills/example_finance_accruals/config.json` | Example skill config |
| `skills/example_finance_accruals/base_prompt.txt` | Example base prompt (domain-only) |
| `skills/_platform_prompt.txt` | Shared platform mechanics injected into every skill |
| `agentcore/agent/utils/skill_router.py` | Auto-discovery logic |
| `knowledge-base/sops/` | SOP storage (synced to S3) |
