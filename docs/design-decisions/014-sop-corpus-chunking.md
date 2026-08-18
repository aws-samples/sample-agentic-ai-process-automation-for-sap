# ADR-014: SOP corpus granularity and chunking strategy

## Status

Accepted (2026-07-21). Extends ADR-003 (domain skills + S3 SOPs) and relates to ADR-013 (S3 Vectors) and ADR-009 (SOP integrity).

## Context

SOPs reach the agent through two independent paths:

1. **Deterministic injection (primary).** The skill router maps `process_type` → one SOP file, fetches the **whole file** from S3, and injects it into the `{SOP_CONTENT}` placeholder. No vectors, no chunking — the agent always receives the complete, ordered procedure it is executing.
2. **Vector search (secondary).** The `search_sap_sops` Gateway tool queries the SOPs Bedrock KB (S3 Vectors) for supplementary lookup across SOPs.

Only path 2 is affected by chunking. Bedrock's **default** chunking (~300 tokens/chunk) means a `search_sap_sops` query can return fragments stitched across multiple SOPs — undesirable when the intent is "operate by SOP." Two forces pull in opposite directions:

- **Whole-SOP integrity / auditability.** Regulated enterprises must be able to say which SOP + version drove a decision; fragment-soup across documents is hard to defend.
- **Real-world corpora vary.** Enterprises hold two archetypes at once: (A) short, atomic work instructions that map 1:1 to a `process_type`, and (B) long, multi-branch, often multimodal SOPs (flowcharts, screenshots, scanned pages) stored in DMS platforms, which exceed any single-embedding limit and cannot be re-authored cheaply.

Titan Text Embeddings v2 (the default) accepts ~8k tokens / 50k characters per input; Cohere Embed v4 raises this to 128k tokens and is multimodal.

## Decision

**Default to whole-SOP integrity via `NONE` chunking on the SOPs KB, and make the strategy configurable** rather than hardcoded.

- The SOPs data source chunking strategy is driven by `config.yaml` → `knowledge_base.sops_chunking_strategy` (default `NONE`). `NONE` = one vector per SOP file → a retrieval hit returns the whole SOP, never fragments across SOPs.
- `FIXED_SIZE` and `SEMANTIC` are supported for corpora whose individual SOPs exceed the embedding input limit (`sops_chunk_max_tokens`, `sops_chunk_overlap_percentage`).
- The **API-docs** KB keeps Bedrock default chunking — large OData specs where passage-level retrieval is desirable.
- SOP tolerances/thresholds are externalized to the skill's `config.json` → `constants` and referenced as `{{SYMBOL}}` placeholders, so tuning a value never requires re-authoring (and re-syncing) an SOP.

## Consequences

- **Demo / Archetype A:** `NONE` + focused per-`process_type` SOPs gives clean, auditable, whole-SOP retrieval with zero cross-contamination. This is the shipped default.
- **Archetype B (long / monolithic):** flip `sops_chunking_strategy` to `SEMANTIC`/`FIXED_SIZE`. To preserve "one SOP at a time" under chunking, tag each SOP with `sop_id`/`version` metadata (a `<file>.metadata.json` sidecar) and filter retrieval to a single SOP — deferred, not yet implemented; `search_sap_sops` currently issues an unfiltered semantic query.
- **Multimodal:** the current ingest extracts PDF **text only** (PyPDF2) and drops diagrams/tables. SOPs whose procedure lives in a flowchart need an ingest-time parsing step (Bedrock Data Automation / Textract) and, for image-native retrieval, a multimodal embedding model (Cohere Embed v4). Documented as future work, not implemented.
- **Embedding limit:** whole-SOP (`NONE`) requires each SOP to fit ~50k chars on Titan v2. For larger single SOPs, switch `sap.embedding_model` to Cohere Embed v4 (128k) — note the S3 Vectors index `dimension` must match the model's output dimension and a re-ingest is required.
- **Interface stability:** SSM KB-ID params and the KB-search Lambda are unchanged; the strategy change is a data-source property + re-ingest.

## Guidance summary

| Corpus | Strategy | Notes |
|--------|----------|-------|
| Short / atomic work instructions | `NONE` (default) | Whole-SOP, cleanest audit story |
| Long, well-sectioned SOPs | `SEMANTIC` | Add SOP-scoped metadata filtering for integrity |
| Very large / fixed-format | `FIXED_SIZE` | Tune `sops_chunk_max_tokens` / overlap |
| Multimodal (diagrams/scans) | parse first | BDA/Textract + Cohere Embed v4 |
