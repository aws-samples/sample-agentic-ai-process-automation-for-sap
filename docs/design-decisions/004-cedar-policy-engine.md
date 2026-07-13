# ADR-004: Cedar Policies via AgentCore Policy Engine

## Status
Accepted

## Context

Our SAP agent has broad tool access through the AgentCore Gateway — it can read/write SAP data, update case state, send notifications, and search knowledge bases. The agent's behavior is guided by SOPs in the system prompt, but prompt-based guardrails are probabilistic. A prompt injection, hallucination, or SOP misinterpretation could cause the agent to:

- DELETE SAP data (never intended)
- Write to SAP without proper role authorization
- Send high-priority notifications without finance approval
- Access tools outside its authorized scope

We need deterministic enforcement that operates independently of the agent's reasoning.

## Decision

Use AgentCore Policy (Cedar) to enforce fine-grained, identity-aware guardrails at the Gateway boundary. Cedar policies are evaluated BEFORE tool execution — the agent cannot bypass them regardless of prompt manipulation.

### Policy Architecture

```
Agent → Gateway → Cedar Policy Engine → Tool Lambda
                       ↓
              ALLOW / DENY (deterministic)
```

### Policy Categories

1. **Read operations** — broadly permitted for all authenticated users (KB search, case reads, SAP GETs)
2. **SAP writes** — require `finance` or `procurement` role in JWT claims
3. **SAP deletes** — hard-blocked via `forbid` (no exceptions)
4. **Case state updates** — permitted for all (agents need this for workflow tracking)
5. **Notifications** — standard priority open to all; high/critical require `finance` or `admin` role

### Deployment Strategy

Policies deploy in `LOG_ONLY` mode first — all requests are evaluated but never blocked. CloudWatch logs show what WOULD have been denied. After validation, flip to `ENFORCE` mode via `config.yaml` (single line change + redeploy).

### Infrastructure

- No `CfnPolicyEngine` L1 construct exists yet in CDK
- Custom Resource Lambda creates the policy engine, adds policies, and associates with Gateway via the `bedrock-agentcore` API
- Cedar policies stored in `agentcore/policies/sap_agent_policies.cedar` — version-controlled, auditable
- Policy engine ID stored as CDK output

## Consequences

**Positive:**
- Deterministic enforcement independent of agent reasoning
- Auditable — Cedar policies are human-readable and version-controlled
- Forbid-wins-over-permit model prevents accidental over-permissioning
- LOG_ONLY mode enables safe rollout without breaking production
- Identity-aware — policies reference JWT claims (role, department, scope)

**Negative:**
- Custom Resource needed until CDK L1 support ships
- Policy changes require redeployment (but Cedar is declarative, so changes are safe)
- Tool action names must match Gateway target names exactly

## Alternatives Considered

1. **Prompt-only guardrails** — rejected: probabilistic, bypassable via injection
2. **Lambda interceptors** — viable but more code to maintain; Cedar is declarative
3. **Amazon Verified Permissions** — Cedar-based but not integrated with AgentCore Gateway natively
