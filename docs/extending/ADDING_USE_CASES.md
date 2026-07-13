<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Adding a New SAP Use Case — End-to-End Guide

> **Which guide do I need?**
> - **This guide (`ADDING_USE_CASES.md`)** — you're adding a brand-new domain that needs its own OData poller config (no data source exists yet), plus schema enum and frontend wiring. End-to-end: SAP discovery → skill → poller → types → deploy.
> - **[`ADDING_SKILLS.md`](ADDING_SKILLS.md)** — you only need the agent to handle a new `process_type` on top of a data pipeline that already exists. No poller/schema/frontend work.
>
> The skill-creation mechanics (`config.json` + `base_prompt.txt` + SOPs) live in `ADDING_SKILLS.md`; Phase 2 below references it rather than repeating the steps.

How to add a new domain (e.g. procurement, inventory, plant maintenance) to the agent system.

## Architecture: What's Generic vs. What's Not

Before diving in, understand where the work actually lives:

| Component | Generic? | What happens when you add a domain |
|-----------|----------|-------------------------------------|
| OData discovery (`find_sap_services`, `get_metadata`) | ✅ Fully | Runtime service/entity discovery via the external AWS for SAP MCP server — nothing to pre-build |
| SAP OData tools (`odata_read`, `odata_create`, …) | ✅ Fully | Served by the external AWS for SAP MCP server — parameterized, works with any service/entity/field. No homegrown SAP Lambda. See [`../design-decisions/012-sap-mcp-server-integration.md`](../design-decisions/012-sap-mcp-server-integration.md) |
| `skill_router` | ✅ Fully | Glob-discovers `skills/*/config.json` — no code changes |
| `odata_poller` | ✅ Config-driven | Add a JSON file to `lambdas/odata_poller/domains/` — no Python code changes |
| CDK gateway tools | ⚠️ Semi-manual | Existing homegrown tools (case/notification/knowledge-base/ticket) work; adding a *new* homegrown tool requires a tool dir + deploy (see [`ADDING_GATEWAY_TOOLS.md`](ADDING_GATEWAY_TOOLS.md)) |
| Frontend | ⚠️ Mostly auto | Schema enum + `DOMAIN_META` + `domainFields` mapping, then `make generate-types` |


## Recommended Approach: Config-Driven Poller

Work through the **Step-by-Step Checklist** below directly — every step is a file edit or shell command, no IDE-specific tooling required.

If you're using Kiro, `@add-use-case` (`.kiro/powers/add-use-case-power/`) automates Phases 2–4 of the checklist (skill scaffold, poller config, schema/frontend updates) by discovering SAP entities at runtime and generating the files for you. It's an accelerator, not a prerequisite — everything it does, you can do by hand with this guide.

### The Poller is Already Config-Driven

The `odata_poller` reads domain definitions from `lambdas/odata_poller/domains/*.json`. Each JSON file declares:

- OData service, entity, `$filter`, `$expand`, `$select`
- Iteration pattern (flat entity or nested parent/child via nav property)
- Skip conditions (blank, empty, lte, present, compound `and`)
- Process type rules (conditional + default)
- Field mapping with path resolution, type casting, and fallbacks
- Title template with `{parent.Field}`, `{child.Field}` interpolation

The generic engine (`polling_engine.py`) handles the pipeline: fetch → iterate → skip → dedupe → map → create case → enqueue. Adding a new polling domain is just adding a JSON file — no Python changes.

#### Domain Config Reference

```jsonc
{
  "domain": "example_finance_accruals",   // Must match Domain enum in types/cases.schema.json
  "label": "PO Accruals",                 // Human-readable label for logs
  "service": "API_PURCHASEORDER_PROCESS_SRV",  // SAP OData service name
  "entity": "A_PurchaseOrder",            // Entity set to query
  "filter": "CompanyCode eq '1710'",      // $filter (optional)
  "expand": "to_Items",                   // $expand (optional)
  "select": "Field1,Field2",              // $select (optional)

  "iterate": {
    "path": "to_Items",                   // Nav property to iterate (null = flat entity)
    "allow_empty_children": false,         // Create synthetic child if nav prop is empty
    "document_number": { "source": "parent", "field": "DocNumber" },
    "item_id": { "source": "child", "field": "ItemNumber", "fallback_index": true }
  },

  "skip_when": [                          // Skip record if ANY condition is true
    { "field": "Amount", "op": "lte", "value": 0, "cast": "float" },
    { "field": "Name", "op": "blank" },
    { "op": "and", "conditions": [...] }  // Compound condition
  ],

  "process_type": {
    "rules": [                            // First match wins
      { "when": { "field": "WBS", "op": "present" }, "then": "wbs_accrual" }
    ],
    "default": "po_accrual"
  },

  "title": "PO {parent.DocNumber} / Line {child.ItemNumber}",

  "field_map": {
    "case_field": {
      "path": "child.SapField",           // parent./child./self. prefix
      "cast": "sap_date",                 // sap_date, float, decimal2, abs_decimal
      "fallback": "parent.AltField",      // Try this path if primary is null
      "strip": true,                      // .strip() string values
      "omit_blank": true                  // Don't include field if value is blank
    },
    "computed_field": {
      "expr": "float(child.Qty) * float(child.Price)",
      "cast": "decimal2"
    }
  }
}
```

## Single Source of Truth: Schema Validation

`types/cases.schema.json` is the single source of truth for domains, statuses, and case fields. The poller configs are validated against it at two levels:

**Build time** (`make generate-types`, pre-commit hook, CI):
- `scripts/dev/validate_domain_configs.py` reads the schema and every `domains/*.json`, fails the build if:
  - A `domain` value isn't in the `Domain` enum
  - A `field_map` key isn't a valid schema property
  - Unknown top-level config keys exist (catches typos)

**Runtime** (Lambda cold start):
- `polling_engine.py` loads the schema and logs warnings for the same checks — doesn't crash the Lambda, but makes drift visible in CloudWatch.

This means: if you add a field to a poller config that doesn't exist in the schema, `make generate-types` breaks. If you add a new domain to the schema but forget to update the poller config's `domain` value, it breaks. The old poller could silently write arbitrary fields to DynamoDB — now it can't.

```
types/cases.schema.json          ← single source of truth
        │
        ├──→ make generate-types
        │       ├──→ generated_cases.py        (Python enums + pydantic models)
        │       ├──→ generated-cases.ts        (TypeScript enums + interfaces)
        │       └──→ validate_domain_configs.py (poller configs vs schema)
        │
        └──→ polling_engine.py (runtime)
                └── warns on domain/field_map/status drift
```

## Step-by-Step Checklist

### Phase 1: SAP API Discovery

Discovery is done at runtime via the external AWS for SAP MCP server — no metadata scanner or S3 spec cache to set up.

- [ ] **1.1** Ensure SAP connectivity is working (service-account credentials synced via `make sync-sap-secret`)
- [ ] **1.2** Use `find_sap_services` (via the agent chat or MCP client) to locate the OData service(s) for your domain
- [ ] **1.3** Use `get_metadata` / `get_service_hints` to inspect entities, fields, nav properties, and annotations
- [ ] **1.4** Note: service name, entity set, key fields, nav properties, and filter criteria you'll use in the poller config

### Phase 2: Skill + SOP

Follow the skill-creation mechanics in **[`ADDING_SKILLS.md`](ADDING_SKILLS.md)** (create `config.json` + `base_prompt.txt` + SOPs from the `skills/example_finance_accruals/` template). The only use-case-specific notes:

- [ ] **2.1** Create the skill (`config.json`, `base_prompt.txt`, SOPs) per `ADDING_SKILLS.md`
  - Use the entity/field names from Phase 1 in `base_prompt.txt`
  - One SOP per process_type (or share SOPs across related types)
- [ ] **2.2** Sync SOPs to S3: `./scripts/sync-knowledge-base.sh --sops-only`

### Phase 3: OData Poller (if automated polling needed)

- [ ] **3.1** Create `lambdas/odata_poller/domains/<domain>.json` — copy from an existing config
  - Set `service`, `entity`, `filter`, `expand`/`select`
  - Define `iterate` pattern (flat or nested)
  - Add `skip_when` conditions
  - Set `process_type` rules
  - Map SAP fields → case fields in `field_map`
  - Set `title` template
- [ ] **3.2** No code changes needed — the engine auto-discovers `domains/*.json`

### Phase 4: Types + Frontend

Schema must be updated before or alongside the poller config — `make generate-types` validates both.

- [ ] **4.1** Add the new domain value to `types/cases.schema.json` → `definitions.Domain.enum`
- [ ] **4.2** Add any domain-specific case fields to the schema `properties` (these must match `field_map` keys in the poller config)
- [ ] **4.3** Run `make generate-types` — regenerates TS/Python types AND validates all `domains/*.json` against the schema
- [ ] **4.4** Add `DOMAIN_META` entry in `frontend/src/types/cases.ts` (label + short name)
- [ ] **4.5** Add field mapping in `frontend/src/lib/domainFields.ts`

### Phase 5: Deploy + Test

- [ ] **5.1** `cd cdk && cdk deploy --all`
- [ ] **5.2** Create a test case with a `process_type` matching the new skill's config
- [ ] **5.3** Verify the agent loads the correct skill, SOP, and can call the right SAP APIs

### Phase 6: Optional

- [ ] **6.1** Add test data tab in `frontend/src/routes/TestDataPage.tsx` (if you want UI-based test data creation)
- [ ] **6.2** Add evaluation exemplars via `lambdas/exemplar_builder/`
- [ ] **6.3** Update your project roadmap or backlog to track the new domain

## What the `@add-use-case` Power Does

The power automates Phases 2, 3, and 4 by:

1. Discovering entities/fields at runtime via the SAP MCP server's `find_sap_services` / `get_metadata`
2. Asking you which entities/fields are relevant to the new domain
3. Generating:
   - `skills/<domain>/config.json`
   - `skills/<domain>/base_prompt.txt` (with entity/field references from the specs)
   - Starter SOP draft (delegates to `@author-sop` for RFC 2119 structure)
   - `lambdas/odata_poller/domains/<domain>.json` (polling config)
   - `types/cases.schema.json` update (new enum value + fields)
   - `frontend/src/types/cases.ts` DOMAIN_META entry
   - `frontend/src/lib/domainFields.ts` field mapping
4. Running `make generate-types` to regenerate TS/Python types

**What it doesn't do** (still manual):
- CDK deploy
- SOP content review and refinement
- Testing

## Files Reference

| What | Where |
|------|-------|
| This guide | `docs/extending/ADDING_USE_CASES.md` |
| Kiro power | `.kiro/powers/add-use-case-power/add-use-case.md` |
| SOP authoring power | `.kiro/powers/author-sop-power/author-sop.md` |
| Skill-creation guide | `docs/extending/ADDING_SKILLS.md` |
| Skill config example | `skills/example_finance_accruals/config.json` |
| Base prompt example | `skills/example_finance_accruals/base_prompt.txt` |
| SAP MCP server design | `docs/design-decisions/012-sap-mcp-server-integration.md` |
| Poller domain configs | `lambdas/odata_poller/domains/*.json` |
| Polling engine | `lambdas/odata_poller/polling_engine.py` |
| Poller Lambda (thin handler) | `lambdas/odata_poller/odata_poller.py` |
| Types schema (single source of truth) | `types/cases.schema.json` |
| Domain config validator | `scripts/dev/validate_domain_configs.py` |
| Type generation + validation | `scripts/dev/generate-types.sh` |
| Frontend domain metadata | `frontend/src/types/cases.ts` |
| Frontend field mappings | `frontend/src/lib/domainFields.ts` |
| CDK backend stack | `cdk/lib/backend-stack.ts` |
