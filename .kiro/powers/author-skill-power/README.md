<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Skill Author Power

Guides Kiro to author a domain **skill** — the `config.json` + `base_prompt.txt` pair under `skills/<domain>/` — in the exact shape the skill router expects.

Companion to the **`author-sop`** power: this power owns the skill definition and its tunable `constants`; `author-sop` owns the SOP prose that references those constants as `{{SYMBOL}}` placeholders. Use both to add a use case.

## Files

| File | Purpose |
|------|---------|
| `author-skill.md` | The power prompt — field reference, the `constants` contract, and `base_prompt.txt` rules |
| `sample-config.json` | Worked example `config.json` (AR collections) with a full `constants` block |
| `sample-base-prompt.txt` | Worked example `base_prompt.txt` — domain persona only, with the `{PLATFORM_MECHANICS}` + `{SOP_CONTENT}` placeholders |

## Usage

```
@author-skill 'Create the skill for SAP AR collections handling collections, ar_dispute, and short_payment process types'
```

**Output:** `skills/<domain>/config.json` + `skills/<domain>/base_prompt.txt`, ready for SOPs (via `author-sop`) and `cdk deploy`.

## The constants contract (why this power exists)

Tunable thresholds (tier cutoffs, scoring weights, SLAs) belong in `config.json → constants`, **not** baked into SOP prose. The skill router's `_substitute_constants` replaces `{{SYMBOL}}` placeholders in the assembled prompt with those values at runtime — mirroring how `{{CONTACT_*}}` resolves from `config.yaml`. This lets a finance team retune a threshold by editing config, without rewriting and re-syncing the SOP document.

Symbols MUST match `[A-Z][A-Z0-9_]*` (no `$`, no lowercase) and MUST be declared in `constants` for every `{{SYMBOL}}` the SOP references.
