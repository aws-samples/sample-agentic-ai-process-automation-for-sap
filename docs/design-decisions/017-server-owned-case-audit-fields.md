# ADR-017: Make case audit fields server-owned

## Status

Accepted (2026-08-07). Relates to ADR-010 (identity and audit context).

## Context

The case-management Gateway Lambda is the write chokepoint for case state. Allowing a model to supply timestamps and audit history makes operator-visible claims, such as how long a case has awaited human input, dependent on model cooperation. It also allows a model-supplied audit field to overlap with a server-written DynamoDB document path, which rejects the entire update and can discard the intended state transition.

A handover timer has specific state semantics: it begins when a case first enters `awaiting_human_input`, persists while the case remains there, and ends when the case leaves that state. An ordinary field edit is not a new human inquiry.

## Decision

The case-management Gateway Lambda owns `updated_at`, `action_log`, and `inquiry_sent_at`. It discards these fields when supplied in model-authored updates and writes them itself:

- every successful update receives a server-generated `updated_at` timestamp;
- the service appends an action-log entry with the server timestamp;
- entering `awaiting_human_input` sets `inquiry_sent_at` with `if_not_exists`, preserving the first inquiry time during repeated updates in that state;
- leaving `awaiting_human_input` removes `inquiry_sent_at`; and
- an update that omits `status` changes neither handover timestamp state nor status.

The tool contract and platform prompt must describe these fields as automatic. This decision applies to these case-record audit fields only; it does not replace SAP-side identity or audit propagation.

## Consequences

- Handover age is derived from a deterministic server-side state transition rather than model-authored prose or timestamp values.
- A reinvocation while awaiting a human response does not reset the wait clock; a later, separate escalation starts a new interval.
- Invalid or fabricated audit values cannot falsify the case audit signal or cause overlapping DynamoDB update paths.
- The action log remains an application audit trail owned by the case-management service.
- Extending server ownership to additional fields requires an explicit contract decision, rather than silently dropping arbitrary model-supplied values.

## Alternatives considered

1. **Require each SOP or model action to submit the timestamps.** Rejected because it repeats policy and makes audit truth model-dependent.
2. **Accept and validate client-provided audit fields.** Rejected because validation cannot establish the truth of a client-supplied transition time when the server owns the write.
3. **Stamp every update as a new inquiry.** Rejected because a non-status edit is not a new request for human input.
4. **Write audit history asynchronously.** Rejected because the handover-age signal must be atomically coupled to the case state transition.

## References

- Case-management implementation: `agentcore/gateway/tools/case_management/case_management_lambda.py`
- Case schema: `types/cases.schema.json`
- Related identity/audit record: [ADR-010](010-identity-audit-context.md)
- Implementation commit: `ef8eae04a6b2e6625bc3e697a6a734287ced20db`
