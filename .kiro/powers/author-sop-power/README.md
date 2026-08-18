<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Kiro Powers

Reusable prompt templates for common tasks in this project. Use them with `@prompt-name` in Kiro CLI or copy them into `.kiro/prompts/`.

## Available Powers

### `author-sop.md` — SOP Author (RFC 2119)

Guides Kiro to write Standard Operating Procedures using RFC 2119 requirement-level language (MUST, SHOULD, MAY, etc.) in the exact format consumed by the agent's skill router.

**Usage:**

```
@author-sop 'Write an SOP for handling SAP intercompany invoice reconciliation exceptions'
```

Or paste the prompt content into a Kiro conversation and describe the ERP exception you need an SOP for.

**Output:** A `.txt` file ready to drop into `knowledge-base/sops/<domain>/` and map in the skill's `config.json` → `process_type_to_sop`.

### `sample-sop-gr-reversal.txt` — Example Output

A complete sample SOP for goods receipt reversal exceptions, demonstrating correct RFC 2119 keyword usage and the required SOP structure.

## Companion: `author-skill` Power

SOPs belong to a **skill**. The `author-skill` power (`.kiro/powers/author-skill-power/`) authors the skill's `config.json` + `base_prompt.txt`, including the tunable **`constants`** block that SOPs reference.

**Division of responsibility:**

| Concern | Owned by | Lives in | SOP references it as |
|---------|----------|----------|----------------------|
| The procedure (RFC 2119 steps) | `author-sop` | `knowledge-base/sops/<domain>/*.txt` | — (this file) |
| Thresholds / weights / SLAs | `author-skill` | `config.json → constants` | `{{SYMBOL}}` |
| Contact emails | (config) | `config.yaml → contacts` | `{{CONTACT_*}}` |
| SAP service/entities, tools, model tier | `author-skill` | `config.json` | — |

Constants and contacts are substituted into the SOP at runtime by `skill_router.py` (`_substitute_constants` / `_substitute_contacts`) — so tunable values change in config without rewriting the SOP.

## Adding a Use Case (chaining the powers)

To add a brand-new domain end-to-end:

1. **`author-skill`** — create `skills/<domain>/config.json` (declare `constants`) + `base_prompt.txt`.
2. **`author-sop`** — write one SOP per `process_type`, referencing the `{{SYMBOL}}` constants declared in step 1.
3. **Poller / schema / frontend** — wire the data source per [`docs/extending/ADDING_USE_CASES.md`](../../../docs/extending/ADDING_USE_CASES.md).
4. **Deploy** — `make sync-kb` then `cd cdk && cdk deploy --all`.

For a skill on top of an existing data pipeline, steps 1–2 + deploy are enough (see [`ADDING_SKILLS.md`](../../../docs/extending/ADDING_SKILLS.md)).
