# ADR-016: Verify SOP evidence by quoted text supplied to the run

## Status

Accepted (2026-08-07). Extends ADR-006 (evaluation strategy), ADR-009 (SOP integrity), and ADR-014 (SOP corpus granularity).

## Context

An earlier evidence check treated a referenced SOP clause number as proof that the agent had followed the rule. A real clause number can accompany an invented rule, and many customer SOPs are not numbered, so clause-number membership is neither a reliable nor general-purpose provenance signal.

The authoritative text for an invocation is also not always the raw SOP file. The skill router injects a post-substitution SOP into the system prompt, while subsequent SOP lookups may return a rendering that retains symbolic constants. Audit evidence must be evaluated against the text the agent actually received during that invocation.

## Decision

For case updates and notifications that cite an SOP, the agent MUST quote the operative sentence in double quotation marks. The platform verifies that quote against an invocation-scoped baseline consisting of:

1. the post-substitution SOP extracted from the assembled system prompt; and
2. each SOP lookup result returned during the same invocation.

Verification normalizes Unicode, typographic quotation marks and dashes, case, and whitespace. A quote is gradeable only when it has at least six words, no more than two sentences, and no more than 320 characters. The platform records the best gradeable quote and whether it occurs in the baseline.

A `verified: false` result means only that the quote was absent from text supplied to the agent. It is not proof of an SOP violation: a compliant paraphrase, malformed quotation, or quote outside the supported bounds can also be unverified. Clause numbers remain optional human-readable locators and are not the verification key.

The baseline is reset for every invocation so a warm runtime cannot use one case's SOP text to verify another case's citation. Retrieved SOP results retain their source URI for human traceability.

## Consequences

- An invented sentence labeled with a real section number is recorded as unverified instead of receiving a false-positive verification result.
- Unnumbered customer SOPs receive the same evidence treatment as numbered sample SOPs.
- Either the substituted injected rendering or a retrieved rendering of the same rule can verify.
- Evidence verification remains deterministic and explainable; it does not depend on a semantic-similarity model.
- A bounded quote prevents pasting a full SOP from trivially satisfying the evidence check.
- The deprecated `clauses_available` trace field remains only for compatibility with persisted traces; new evidence uses `citation.quote` and `citation.verified`.

## Alternatives considered

1. **Verify only `per §N.N` clause membership.** Rejected because a real clause label can accompany fabricated content and it overfits numbered SOPs.
2. **Accept any model-supplied citation.** Rejected because it provides no auditable provenance signal.
3. **Hash only raw source documents.** Rejected because runtime substitutions and retrieved fragments can legitimately render the same rule differently.
4. **Use semantic similarity.** Rejected for this evidence field because the result would be less deterministic and less explainable to an auditor.

## References

- Evidence implementation: `agentcore/agent/utils/evidence.py`
- Invocation hook: `agentcore/agent/basic_agent.py`
- Trace schema: `types/cases.schema.json`
- SOP corpus decision: [ADR-014](014-sop-corpus-chunking.md)
- Implementation commits: `f327f8285ab7d0b5a2593a468bf8415433ab3646`, `46f9d7cb3d3f288afd969f97f75f5c16e87e6954`
