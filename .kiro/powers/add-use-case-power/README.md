<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Add Use Case Power

Scaffolds all files needed to add a new SAP domain to the agent system.

## Usage

```
@add-use-case 'Add a procurement domain for purchase requisition approval exceptions using API_PURCHASEREQ_PROCESS_SRV'
```

## What It Does

1. Discovers available entities and fields at runtime via the external SAP MCP server's `find_sap_services` / `get_metadata` tools
2. Asks clarifying questions about the domain, process types, and business rules
3. Generates: skill config, base prompt, SOP draft, poller domain config, types schema update, frontend metadata, frontend field mapping
4. Runs `make generate-types` to regenerate TypeScript/Python types and validate poller configs against the schema

## Schema Validation

`types/cases.schema.json` is the single source of truth. The power ensures:
- The new `domain` value is added to the schema's `Domain` enum before creating the poller config
- Every `field_map` key in the poller config exists as a schema property
- `make generate-types` validates all of this at build time — if something's out of sync, the build fails

## What's Still Manual

- Reviewing and refining the SOP draft
- Integrating the poller function (presented as a code block for review)
- Deploying: `make sync-kb` + `make deploy-all`
- Testing

## See Also

- [Adding Use Cases Guide](../../../docs/extending/ADDING_USE_CASES.md) — full checklist and architecture context
- [Author SOP Power](../author-sop-power/) — RFC 2119 SOP authoring (used by this power for SOP drafts)
