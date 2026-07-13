<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Add Use Case — Scaffold a New SAP Domain

You are an expert at extending this ERP automation agent system. When the user describes a new SAP domain they want to add, you scaffold all the files needed to make it work end-to-end.

## Prerequisites

Before running this power, the user should have:
1. A deployed stack with the external AWS for SAP MCP server registered as a Gateway target
2. SAP connectivity working (service-account credentials synced via `make sync-sap-secret`)

If they haven't done this yet, walk them through it first.

## Workflow

### Step 1: Discover Available Entities

Discover entities and fields at runtime via the external SAP MCP server (no S3 spec cache exists):

1. Use `find_sap_services` to locate the relevant OData service(s) for the domain
2. Use `get_metadata` (and `get_service_hints` where helpful) to inspect entities, fields, types, navigation properties, and SAP annotations (sap:label, sap:creatable, sap:updatable)
3. Present a summary to the user: "Here are the entities I found in {service_name}. Which ones are relevant to your use case?"

### Step 2: Gather Domain Requirements

Ask the user:
- **Domain name** (snake_case, e.g. `procurement`, `plant_maintenance`, `inventory`)
- **Display name** (e.g. "Procurement — Purchase Requisitions")
- **Process types** — what exception types will this domain handle? (e.g. `pr_approval`, `pr_budget_exceeded`)
- **Which entities** from Step 1 are involved?
- **Polling criteria** — what `$filter` identifies exceptions? What fields determine the case?
- **Key case fields** — what SAP fields should be stored on the DynamoDB case item?

### Step 3: Generate Files

Generate all of the following files. Read the existing examples first to match conventions exactly.

**Critical ordering**: The schema update (3d) MUST happen before or alongside the poller config (3g), because `make generate-types` validates poller configs against the schema. If the `domain` value or `field_map` keys in the poller config don't exist in the schema, the build will fail.

#### 3a. Skill Config — `skills/{domain}/config.json`

Read `skills/example_finance_accruals/config.json` as the template. Generate with:
- `skill_id` matching the directory name
- `process_type_to_sop` mapping each process type to an SOP path
- `gateway_tools` — start with the homegrown standard set: `get_case_state`, `update_case_state`, `search_sap_sops`, `search_sap_api_docs`, `send_notification`
- Add the SAP OData tools from the external MCP server target: `find_sap_services`, `get_metadata`, `get_service_hints`, `odata_read`, `odata_count`, `odata_create`, `odata_update`, `odata_function_import`
- Add the demo ticket tools (`demo_create_ticket`, `demo_update_ticket`, `demo_get_ticket`, `demo_list_tickets`) only if running with `demo.enabled`

#### 3b. Base Prompt — `skills/{domain}/base_prompt.txt`

Read `skills/example_finance_accruals/base_prompt.txt` as the template. The prompt MUST:
- Contain the `{SOP_CONTENT}` placeholder
- Reference the correct SAP entity names and key fields from the OData specs
- Describe the domain context so the agent understands what it's processing
- List the available tools and when to use each one

#### 3c. SOP Draft — `knowledge-base/sops/{domain}/{sop_name}.txt`

Delegate to `@author-sop` to draft the SOP with correct RFC 2119 structure. Provide the author-sop power with:
- The domain context and exception type
- The SAP entities and fields involved (from the OData specs)
- The business rules the user described

#### 3d. Types Schema Update — `types/cases.schema.json`

This is the single source of truth. The poller config, generated Python/TypeScript types, and frontend all derive from it.

Read the current schema. Add:
- New value to `definitions.Domain.enum` — this MUST match the `"domain"` value in the poller config (3g)
- Any domain-specific fields to `properties` (with type, description) — every key in the poller config's `field_map` MUST exist here

#### 3e. Frontend Domain Metadata — `frontend/src/types/cases.ts`

Read the current file. Add a `DOMAIN_META` entry for the new domain:
```typescript
[Domain.NewDomain]: { label: 'Display Name', short: 'Short' },
```

#### 3f. Frontend Field Mapping — `frontend/src/lib/domainFields.ts`

Read the current file. Add a field mapping array for the new domain:
```typescript
[Domain.NewDomain]: [
  ['Label', 'field_name'],
  // ... one entry per case field to show in the detail view
],
```

#### 3g. Poller Domain Config — `lambdas/odata_poller/domains/{domain}.json`

Read the existing domain configs (e.g. `lambdas/odata_poller/domains/example_finance_accruals.json`) as templates. Generate a config with:

- `domain` — MUST match a value in `types/cases.schema.json` → `definitions.Domain.enum`
- `service` and `entity` from the OData specs discovered in Step 1
- `filter` based on the user's polling criteria
- `expand`/`select` for the fields needed
- `iterate` pattern — `path: null` for flat entities, or the nav property name for nested parent/child
- `skip_when` conditions based on the user's business rules
- `process_type` rules (conditional + default)
- `field_map` — every key MUST be a valid property in `types/cases.schema.json`. Use appropriate casts (`sap_date`, `decimal2`, `abs_decimal`)
- `title` template using `{parent.Field}`, `{child.Field}`, `{self.Field}` interpolation

The polling engine auto-discovers `domains/*.json` — no code changes needed in `odata_poller.py`.

### Step 4: Run Type Generation and Validation

After writing the schema update and poller config, run:
```bash
make generate-types
```

This does three things:
1. Regenerates `types/generated_cases.py` (Python enums + dataclasses)
2. Regenerates `frontend/src/types/generated-cases.ts` (TypeScript enums + interfaces)
3. Validates all `lambdas/odata_poller/domains/*.json` against the schema — fails if `domain` values or `field_map` keys don't match

If validation fails, fix the mismatch before proceeding. Common issues:
- Forgot to add the new domain to `definitions.Domain.enum`
- A `field_map` key doesn't exist in schema `properties` — add it to the schema first

### Step 5: Summary Checklist

Present the user with what was generated and what's still manual:

**Generated:**
- [ ] `skills/{domain}/config.json`
- [ ] `skills/{domain}/base_prompt.txt`
- [ ] `knowledge-base/sops/{domain}/{sop_name}.txt` (draft — review and refine)
- [ ] `lambdas/odata_poller/domains/{domain}.json` (polling config)
- [ ] `types/cases.schema.json` (updated)
- [ ] `frontend/src/types/cases.ts` (updated)
- [ ] `frontend/src/lib/domainFields.ts` (updated)
- [ ] Types regenerated via `make generate-types`

**Still needed (manual):**
- [ ] Review and refine the SOP draft
- [ ] Review the poller config (skip conditions, process_type rules, field mapping)
- [ ] `make sync-kb`
- [ ] `make deploy-all`
- [ ] Test with a real or mock case

## Important Conventions

- Directory names: `snake_case`
- `skill_id` in config.json matches the directory name under `skills/`
- SOP paths in config.json are relative to `knowledge-base/sops/`
- The `{SOP_CONTENT}` placeholder in base_prompt.txt is required — the skill router injects the SOP there
- `{{CONTACT_*}}` placeholders in SOPs are replaced from config.yaml contacts at runtime
- `types/cases.schema.json` is the single source of truth — the `domain` value and every `field_map` key in a poller config MUST exist in the schema
- `make generate-types` validates poller configs against the schema at build time; the polling engine also validates at Lambda cold start (warnings in CloudWatch)
