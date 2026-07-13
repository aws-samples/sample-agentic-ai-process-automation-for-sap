# ADR-003: Domain Skills + S3 SOPs (Two-Layer Agent Architecture)

## Status
Accepted

## Context

We have three SAP exception demos (PO Accrual, AP Three-Way Matching, AR Lockbox) that need to be consolidated into a single multi-use-case platform. The initial approach of one skill per SOP (1:1) would create 60+ skills as the platform scales across SAP domains (AP, AR, Accruals, Procurement, Inventory, Quality, HR, etc.).

We also need SOPs to be manageable by business users without code deployments — versioned, PDF-only, digitally signed, with Glacier backup for compliance.

## Decision

Use a two-layer architecture:

**Layer 1: Domain Skills (few, code-deployed)**
- A skill represents a SAP domain capability (e.g., Finance/AP, Finance/AR, Finance/Accruals)
- Contains a `base_prompt.txt` with domain expertise, authorization boundaries, workflow patterns, and tool usage guidance
- Contains a `config.json` mapping `process_type` values to SOP S3 keys
- Declares which Gateway tools the domain needs (some domains have extra tools beyond the shared SAP/case set)
- ~8-12 skills cover all of SAP

**Layer 2: SOPs (many, S3-managed)**
- Each SOP is a standalone procedure document in S3 (PDF in production, .txt for dev)
- Organized by domain: `s3://sops-bucket/finance_ap/price_variance.pdf`
- Versioned, with noncurrent versions transitioning to Glacier after 30 days
- Write access restricted to `sop-admin` IAM role only
- Adding a new exception type = upload PDF + add one mapping line to config.json

**At invocation time:**
1. Skill Router reads `process_type` from case payload
2. Finds which skill handles it (scans `config.json` mappings)
3. Loads the skill's `base_prompt.txt` (domain expertise)
4. Fetches the matching SOP from S3
5. Injects SOP content into base prompt at `{SOP_CONTENT}` placeholder
6. Creates Agent with assembled system prompt + scoped tools

## Consequences

**Positive:**
- Adding a new exception type requires zero code changes — upload PDF, add mapping
- Skills are transferable across customers — only SOPs are customer-specific
- SOPs are auditable (S3 versioning + Glacier) and access-controlled (IAM)
- Domain expertise (base prompt) is maintained separately from procedures (SOP)
- Context window is used efficiently — full SOP in prompt for determinism

**Negative:**
- SOPs must fit in context window (~50 pages max). Larger SOPs fall back to RAG.
- PDF text extraction needed at runtime (PyPDF2 or Textract)
- Two places to update when adding a new domain (skill directory + S3 prefix)

## Alternatives Considered

1. **1:1 Skill per SOP** — rejected: doesn't scale (60+ skills), massive duplication
2. **RAG-only (no skills)** — rejected: non-deterministic for known procedures, retrieval misses mid-workflow
3. **Single monolithic agent** — rejected: context window bloat, no domain scoping
