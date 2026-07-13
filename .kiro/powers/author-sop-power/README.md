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
