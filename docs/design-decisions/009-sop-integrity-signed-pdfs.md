# ADR-009: SOP Integrity — Signed PDFs and Contact Templating

## Status
Proposed

## Context

SOPs (Standard Operating Procedures) are the authoritative instructions that govern how the agent processes ERP exceptions. They contain domain logic, workflow steps, escalation paths, and contact information. Today SOPs are plain text files committed to the repo and uploaded to S3, where they're consumed two ways:

1. **Skill router** — fetches the SOP from S3, injects it verbatim into the agent's system prompt
2. **Bedrock Knowledge Base** — indexes SOPs for RAG retrieval when the agent needs cross-domain context

This creates two governance problems:

1. **Integrity** — Anyone with S3 write access can modify an SOP. There's no cryptographic proof that the SOP the agent is executing matches what was reviewed and approved. In regulated ERP environments (SOX, GxP), this is a compliance gap.
2. **Maintainability** — Contact email addresses were hardcoded across all SOPs. Changing a single email required editing multiple files and resyncing the KB.

The maintainability problem has been solved (see Decision §1 below). The integrity problem motivates the signed PDF design.

## Decision

### 1. Contact directory with runtime substitution (implemented)

A centralized `contacts` map in `cdk/config.yaml` is the single source of truth for all email addresses:

```yaml
contacts:
  po_owner: po-owner@example.com
  finance_team: finance@example.com
  technical_support: support@example.com
```

SOPs reference contacts via `{{CONTACT_<KEY>}}` placeholders (e.g. `{{CONTACT_FINANCE_TEAM}}`). Substitution happens at two points:

- **Skill router** (`agent/utils/skill_router.py`) — resolves placeholders after loading the SOP, before building the system prompt
- **KB Lambda** (`gateway/tools/knowledge_base/knowledge_base_lambda.py`) — resolves placeholders in RAG results before returning to the agent

The agent never sees raw placeholders. Contacts are passed to the runtime and Lambda via `CONTACTS_JSON` environment variable, with a local dev fallback that reads `cdk/config.yaml` directly.

This design is forward-compatible with signed PDFs: the signature covers the template (with placeholders), and substitution happens after text extraction.

### 2. Signed PDF SOPs (proposed, not yet implemented)

The target architecture for SOP integrity:

```
Author → Sign PDF (digital signature) → Upload to S3
                                              │
                    ┌─────────────────────────┤
                    ▼                         ▼
            Ingestion Lambda           Skill Router
            1. Verify signature        1. Fetch from S3
            2. Extract text            2. Extract text (PyPDF2/Textract)
            3. Write to KB bucket      3. Inject into prompt
            4. Trigger KB sync         4. Substitute contacts
                    │
                    ▼
            Bedrock KB indexes
            extracted text
```

Key design principles:

- **Signature verification at ingestion, not query time.** The KB and skill router consume extracted text. Verification happens once when the PDF enters S3, not on every agent invocation.
- **Reject unsigned/tampered PDFs.** The ingestion Lambda (or S3 event trigger) validates the digital signature before allowing the SOP into the pipeline. Invalid signatures → reject upload, alert SOP admin.
- **SOP bucket write policy is the first gate.** The existing `sopAdminRole` restricts who can write to the SOP bucket. Signed PDFs add a second gate: even if you can write, the content must be validly signed.
- **Placeholders survive signing.** The signed PDF contains `{{CONTACT_*}}` placeholders as literal text. The signature covers the template. Runtime substitution happens downstream and doesn't modify the signed artifact.
- **PDF text extraction.** The skill router already has a basic PyPDF2 path. Production should use Amazon Textract for reliable extraction from complex PDF layouts.

### Implementation phases

| Phase | Scope | Status |
|-------|-------|--------|
| 1 | Contact directory + `{{CONTACT_*}}` substitution in skill router and KB Lambda | ✅ Implemented |
| 2 | SOP ingestion Lambda with signature verification (S3 event trigger) | Not started |
| 3 | Migrate existing SOPs to signed PDF format | Not started |
| 4 | Enforce signed-only policy (reject unsigned uploads) | Not started |

## Consequences

**Positive:**
- Contact changes are a single config edit + redeploy — no SOP file modifications needed
- Signed PDFs provide cryptographic proof of SOP provenance and integrity
- Compatible with SOX/GxP audit requirements for change control
- Signature verification is decoupled from agent execution — no runtime performance impact
- Existing SOP bucket admin-only policy provides defense in depth alongside signatures

**Negative:**
- PDF signing requires a certificate authority (ACM Private CA or external CA) and a signing workflow
- SOP authors need tooling to sign PDFs (Adobe Acrobat, CLI tools, or a custom signing Lambda)
- Text extraction from PDFs is less reliable than plain text — complex formatting, tables, and multi-column layouts may need Textract
- Two-phase rollout needed: can't enforce signed-only until all existing SOPs are migrated

## Alternatives Considered

1. **S3 Object Lock (WORM)** — prevents modification but doesn't prove authorship or detect tampering before upload. Complements but doesn't replace signatures.
2. **Git-signed commits as integrity proof** — works for the repo copy but not for the S3 copy the agent actually reads. S3 is the runtime source of truth.
3. **Pre-resolve contacts before upload (Option B)** — rejected: bakes emails into S3/KB, loses single-source-of-truth for contacts, and would break PDF signatures since the resolved content differs from the signed content.
