# ADR-015: Recover detected cases with an autonomous-pipeline batch sweeper

## Status

Accepted (2026-08-07).

## Context

The OData poller enqueues a case only when it creates the case. A case can therefore remain in `detected` without an unattended caller when it was created while `trigger-mode` was `manual` or when its initial queue handoff failed.

Recovery must not create a second agent-processing plane, re-run work that has already been handed to an agent, or require a stored credential for an absent human. The existing autonomous pipeline already provides a FIFO invocation queue, an agent invoker, and a machine identity that obtains fresh client-credentials tokens for each run.

## Decision

Provision a scheduled batch sweeper only when the selected auth profile includes both `batch` and `autonomous` modes. The sweeper MUST:

- reuse the existing FIFO agent-invocation queue and agent invoker rather than deploy a separate queue or agent runtime;
- use the existing technical service identity, not a named user's stored refresh token;
- obey `/{stack}/autonomy/trigger-mode` at runtime and perform no enqueue for any value other than `auto`, including an SSM read failure;
- query only cases whose status remains `detected`, require an age floor above the poller cadence, and bound each sweep to a configured maximum backlog; and
- enqueue one FIFO message group per canonical case identity with `trigger: batch`.

The sweeper is a bounded, at-least-once recovery mechanism. Downstream state transitions and idempotency remain responsible for safely tolerating duplicate deliveries.

## Consequences

- Missed poller handoffs can recover automatically without changing the normal invocation topology.
- The age floor, rather than FIFO content-based deduplication, prevents a fresh poller enqueue from racing the batch sweep because their message bodies differ by trigger.
- A large backlog drains across scheduled sweeps instead of overwhelming the queue in one run.
- An invalid case identity or one failed enqueue does not prevent the remaining eligible cases from being considered.
- A case that remains `detected` may be retried by a later sweep. This is intentional recovery behavior, not exactly-once processing.
- Batch execution as an absent human remains unsupported until a refresh-capable user-identity flow is designed and operated.

## Alternatives considered

1. **Retry only from the poller.** Rejected because it cannot recover existing cases created in manual mode or cases whose initial enqueue was already missed.
2. **Create a dedicated batch queue and agent runtime.** Rejected because it would duplicate routing, authorization, observability, and operational behavior.
3. **Sweep all nonterminal statuses.** Rejected because it could re-run work that was already handed to an agent or human.
4. **Use stored refresh tokens for a named user.** Deferred because unattended user-identity execution is a distinct security and lifecycle design.

## References

- Implementation: `lambdas/batch_runner/index.py`
- Infrastructure wiring: `cdk/lib/backend-stack.ts`
- Auth-profile contract: `auth-profiles.yaml`
- Implementation commit: `1f3e8b746b04bfe3445c843ba02baeefa50b0ad9`
