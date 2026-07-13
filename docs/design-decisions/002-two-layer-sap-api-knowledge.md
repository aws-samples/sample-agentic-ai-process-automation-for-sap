# ADR-002: Two-Layer SAP API Knowledge Architecture

**Status:** Accepted  
**Date:** 2026-03-20

## Context

The original PoC used a single Bedrock Knowledge Base containing hand-curated OpenAPI specs for the SAP OData services the agent needed. This had several problems:

1. **Manual maintenance** — every time a new OData service was needed, someone had to write/convert the API spec and upload it to S3
2. **Stale docs** — specs could drift from the actual SAP system (fields added/removed by Basis team, custom extensions)
3. **Vector search for structured data** — asking a vector DB "what are the fields on A_PurchaseOrder" returns fuzzy chunks, not the precise field list with types
4. **Scalability** — customers may have hundreds of custom Z-services alongside standard APIs; hand-curating specs for all of them doesn't scale

SAP OData services expose `$metadata` — an EDMX XML document describing every entity type, property, navigation property, and function import. SAP also provides annotations in the `sap:` namespace (`sap:label`, `sap:quickinfo`, `sap:heading`) that give human-readable names for even cryptic ABAP field names (e.g., `BUKRS` → "Company Code").

However, `$metadata` alone is insufficient:
- It describes **structure** (what fields exist) but not **purpose** (when to use this API, what business process it supports)
- ECC systems may have German/abbreviated field names that are only meaningful with `sap:label` annotations
- A large S/4HANA system can have 1000+ OData services — dumping all metadata into the agent's context window is impractical

## Decision

Use a two-layer architecture:

**Layer 1 — Knowledge Base (vector search):** Business process documentation, curated API guides, and SOPs. Answers "which API do I need?" and "what's the workflow for parking a journal entry?" Searched via `search_sap_api_docs` tool. Content is authored by humans and updated infrequently.

**Layer 2 — Auto-discovered OData specs (structured JSON):** A `$metadata` scanner Lambda fetches `$metadata?sap-documentation=all` from configured SAP services, parses the EDMX with all SAP annotations, and writes per-entity JSON specs to S3 behind CloudFront. Searched via `search_odata_specs` (keyword search across entity names and `sap:label` text) and read via `get_odata_entity_spec`. Content is machine-generated and refreshed on schedule.

### Agent workflow

1. `search_sap_api_docs("how to create a journal entry")` → KB returns business context mentioning the service name
2. `search_odata_specs("journal entry posting date")` → keyword search returns matching entities with sample labels (max 20 results)
3. `get_odata_entity_spec("API_JOURNALENTRY_PROCESS_SRV", "A_JournalEntry")` → full field spec with labels, types, keys, capabilities
4. `invoke_sap_odata_service(...)` → makes the call with correct fields

### Scanner extracts from `$metadata?sap-documentation=all`

- `sap:label`, `sap:heading`, `sap:quickinfo` — human-readable field names
- `<Documentation><Summary>` / `<LongDescription>` — F1 help from ABAP data dictionary
- `sap:creatable`, `sap:updatable`, `sap:filterable`, `sap:required-in-filter` — capability annotations
- `sap:unit`, `sap:semantics`, `sap:text` — semantic annotations (currency, UoM, text references)
- Entity set capabilities (creatable/updatable/deletable/requires-filter)

## Alternatives Considered

### A. Replace KB entirely with auto-discovered specs

Rejected. `$metadata` has no business process context — it can't tell the agent "use this API for month-end accruals" or "the materiality threshold determines which workflow to follow." The SOP/API docs KB remains essential for decision-making guidance.

### B. Dump all metadata into a single Knowledge Base

Rejected. Vector search over thousands of entity specs returns fuzzy, incomplete results. When the agent needs the exact field list for `A_PurchaseOrderItem`, it needs a precise JSON document, not a chunk of XML that may be truncated mid-property.

### C. Let the agent call `$metadata` directly at runtime

Rejected. `$metadata` responses can be 500KB+ of XML. Parsing XML in the agent's context window wastes tokens and is error-prone. The scanner pre-processes into compact JSON and the CloudFront cache eliminates repeated SAP calls.

### D. Only support pre-configured services (no scanner)

Rejected for the platform, but this is the fallback. The scanner is additive — if a customer's SAP system doesn't support `$metadata` annotations well (rare), they can still hand-curate specs in the API docs KB as the PoC did.

## Consequences

- **Positive:** New OData services are onboarded by adding the service name to `config.yaml` and running the scanner — no manual spec authoring
- **Positive:** Even ECC systems with ABAP field names become agent-friendly via `sap:label` extraction
- **Positive:** CloudFront caching means the agent never hits SAP directly for spec lookups
- **Positive:** `search_odata_specs` caps results at 20, protecting the context window
- **Trade-off:** Two tools to maintain instead of one KB, but the separation of concerns (structure vs. purpose) is cleaner
- **Trade-off:** Scanner requires SAP credentials and network access at scan time, but this is the same access the poller Lambda already has
- **Note:** Customers using RAP (RESTful ABAP Programming) to generate custom OData services get particularly good results — RAP services have rich annotations by default
