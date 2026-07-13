# ADR-007: Multi-Agent Architecture — Orchestrator + Specialist Pattern

## Status
Accepted — implemented in `specialist.py` + `basic_agent.py`. Feature-flagged via `multi_agent: true` in skill configs. All skills default to `false` (single-agent) for safe rollout.

## Context

ADR-005 identified that ~60-70% of agent turns are mechanical (tool calls, SOP formula execution, DDB updates) and don't need Sonnet. Now that we have:
- OTEL traces showing per-turn token usage and latency (4.5)
- Evaluations to detect quality regression (4.6)
- A deterministic calculator tool for financial math

...we can design the split with confidence.

## Proposed Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Orchestrator Agent (Haiku)                             │
│  - Owns the event loop and workflow state               │
│  - Reads SOP, follows steps sequentially                │
│  - Calls Gateway tools (SAP, DDB, notifications)       │
│  - Calls calculator for all financial math              │
│  - Delegates to Specialist when SOP says "if ambiguous" │
│  - Writes processing_history to DDB                     │
│                                                         │
│  Tools:                                                 │
│    [gateway_client]  — SAP, DDB, notifications, KB      │
│    [calculator]      — deterministic SymPy math          │
│    [specialist]      — Sonnet agent-as-tool              │
└──────────────────────────┬──────────────────────────────┘
                           │ delegates complex tasks
                           ▼
┌─────────────────────────────────────────────────────────┐
│  Specialist Agent (Sonnet)                              │
│  - Stateless — receives a focused task, returns answer  │
│  - No tools — pure reasoning                            │
│  - Tasks:                                               │
│    • Parse ambiguous email: "mid-December" → Dec 15     │
│    • Resolve conflicting data between SAP and Excel     │
│    • Decide escalation when SOP doesn't cover the case  │
│    • Interpret vague PO owner responses                 │
└─────────────────────────────────────────────────────────┘
```

### Implementation with Strands

Strands supports this via `agents-as-tools`:

```python
from strands import Agent
from strands.models import BedrockModel

# Specialist: Sonnet, no tools, pure reasoning
specialist = Agent(
    name="ReasoningSpecialist",
    model=BedrockModel(model_id=MODEL_TIERS["sonnet"]),
    system_prompt="You are an expert at interpreting ambiguous data...",
    tools=[],  # No tools — reasoning only
)

# Orchestrator: Haiku, all tools + specialist as a tool
orchestrator = Agent(
    name="SAPOrchestrator",
    model=BedrockModel(model_id=MODEL_TIERS["haiku"]),
    system_prompt=skill["system_prompt"],  # Full SOP
    tools=[gateway_client, calculator, specialist.as_tool()],
)
```

The orchestrator's SOP would include instructions like:
```
When parsing email responses for delivery dates:
  - If the date is explicit (e.g., "March 15, 2026"), extract it directly
  - If the date is ambiguous (e.g., "mid-December", "Q2 next year"),
    use the reasoning_specialist tool to interpret it
```

### What changes from current architecture

| Component | Current (single agent) | Multi-agent |
|-----------|----------------------|-------------|
| Model | Sonnet for everything | Haiku orchestrator + Sonnet specialist |
| Calculator | Sonnet does math (risky) | calculator tool (deterministic) |
| SOP | Loaded into single agent | Loaded into orchestrator only |
| Specialist | N/A | Stateless, no SOP, focused task |
| Traces | One agent span | Nested: orchestrator span → specialist span |
| Cost | ~$0.08/case | ~$0.03/case (estimated) |

### How to validate before committing

1. **Analyze existing traces** — Query X-Ray for completed cases. For each turn, check:
   - Did the model just call a tool and pass through the result? → Haiku candidate
   - Did the model reason about ambiguous data? → Sonnet candidate
   - Tag each turn as "mechanical" or "reasoning"

2. **Run Haiku on historical prompts** — Replay the mechanical turns through Haiku.
   If Haiku produces the same tool calls with the same parameters → safe to route.

3. **A/B eval** — Run the same ground truth test cases (evals/ground_truth.json) with:
   - Current: single Sonnet agent
   - Proposed: Haiku orchestrator + Sonnet specialist
   Compare GoalSuccessRate, ToolSelectionAccuracy, SAPActionAccuracy scores.

4. **Cost comparison** — Use the AgentEstimatedCostUSD metric from 4.5 to compare.

### Risk: Haiku can't follow complex SOPs

The biggest risk is that Haiku can't reliably follow multi-step SOPs with conditional logic. Mitigation:
- SOPs are already structured with clear IF/THEN/ELSE blocks
- Exemplar injection shows Haiku exactly what tool calls to make
- Calculator handles all math — Haiku just needs to call it with the right inputs
- If Haiku fails on a step, the MaxTurnsHook catches runaway loops
- Evals catch quality regression before deployment

### Strands multi-agent patterns available

| Pattern | Use case | Fit for us |
|---------|----------|-----------|
| `agent.as_tool()` | Agent as a callable tool | ✅ Best fit — specialist is a tool |
| `Swarm` | Dynamic agent handoff | ❌ Overkill — we have fixed roles |
| `Graph` | DAG of agent steps | 🟡 Maybe later for Step Functions replacement |

## Implementation Steps

1. Create `specialist_agent.py` — Sonnet agent with reasoning-focused system prompt
2. Modify `basic_agent.py` — Haiku orchestrator with specialist as tool
3. Update skill configs — `"orchestrator_tier": "haiku"`, `"specialist_tier": "sonnet"`
4. Run A/B evals against ground truth
5. Deploy behind feature flag in config.yaml
6. Monitor traces + cost metrics for 1 week
7. If quality holds, make it default

## Consequences

- ~60% cost reduction per case (estimated)
- Two agents to maintain instead of one
- Specialist prompt needs careful engineering (what context to pass)
- Traces become nested (orchestrator → specialist) — dashboard may need update
- Rollback is easy: set `"orchestrator_tier": "sonnet"` to revert to single-agent
