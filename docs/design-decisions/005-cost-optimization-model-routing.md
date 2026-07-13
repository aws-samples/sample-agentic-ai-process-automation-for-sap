# ADR-005: Cost Optimization Strategy — Model Routing & Future Orchestrator Pattern

## Status
Accepted

## Context

Our agent uses a single powerful model (Sonnet) for the entire case lifecycle. A typical PO accrual case involves ~8 steps, but only 2-3 require genuine reasoning (NLP parsing of email responses, edge case judgment). The rest are mechanical: calling tools, following SOP formulas, writing summaries to DynamoDB.

This means we're paying Sonnet prices for Haiku-level work on ~60-70% of turns.

## Decision

### Phase 1 (implemented): Config-driven cost controls

Four techniques deployed now, all config-driven:

1. **Static model tier per skill** — Each skill config declares `"model_tier": "sonnet"` or `"haiku"`. The agent entrypoint maps tiers to model IDs. Simple cases (e.g., `DELIVERY_DATE` workflow) can use Haiku for the entire case.

2. **Prompt caching** — `CacheConfig(strategy="auto")` on BedrockModel. System prompts (SOP + base prompt + exemplars) are large and identical across invocations of the same process_type. Bedrock caches the prefix — 90% input token cost reduction on subsequent turns within a session.

3. **Max turns per skill** — Each skill config declares `"max_turns": 20`. A hook cancels the agent if it exceeds the limit, preventing runaway loops. Accruals get 25 (more complex workflow), AP/AR get 20.

4. **Exemplar injection** — Daily Lambda generates condensed resolution examples from successful cases. Agent sees efficient tool-call sequences and follows them instead of exploring, reducing wasted turns.

### Phase 1.5 (available, not yet configured): Bedrock Intelligent Prompt Routing

Bedrock IPR routes each request within a model family (e.g., Anthropic) to Haiku or Sonnet based on prompt complexity. Available as `"model_tier": "ipr-anthropic"` in skill configs.

**Why not default:** IPR evaluates the *prompt text* to decide complexity. Our system prompts always include a large SOP document, so IPR will likely classify most requests as complex and pick Sonnet anyway. IPR is better suited for chatbot workloads with varying prompt sizes, not agentic loops with constant large system prompts.

**When to use:** If we add a lightweight "chat about a case" mode without SOP injection, IPR would be a good fit there.

### Phase 2 (future): Orchestrator + Specialist decomposition

The real cost win comes from splitting the agent into two tiers:

```
Orchestrator (Haiku) — manages workflow, calls tools, tracks state
  │
  ├─ Mechanical steps: tool calls, SOP formula execution, DDB updates
  │   → Haiku handles these directly (cheap, fast)
  │
  └─ Complex steps: NLP parsing, edge case judgment, ambiguous decisions
      → Delegates to Sonnet specialist sub-agent (expensive, smart)
```

**Step complexity breakdown for a typical PO accrual case:**

| Step | Task | Model needed |
|------|------|-------------|
| Read case state | Tool call | Haiku |
| Query SAP for PO details | Tool call | Haiku |
| Decide workflow (materiality threshold) | Simple SOP lookup | Haiku |
| Parse email response for delivery date | NLP — "mid-December" → Dec 15 | **Sonnet** |
| Calculate accrual (straight-line) | Follow formula | Haiku |
| Compose approval email | Structured writing | Haiku |
| Summarize steps → update DDB | Condense actions | Haiku |
| Handle edge case / escalation | Judgment call | **Sonnet** |

**Estimated savings:** ~60-70% of turns shift from Sonnet to Haiku pricing. Combined with prompt caching and exemplar injection, total cost reduction could be 50-70%.

**Implementation path (Strands patterns):**
- Orchestrator: Haiku agent with SOP + tools + a `reasoning_specialist` tool
- Specialist: Sonnet agent exposed as a Strands `agents-as-tools` tool
- Orchestrator decides when to delegate based on SOP instructions ("if ambiguous, consult specialist")
- Strands also supports `swarm` and `graph` patterns for more complex multi-agent topologies

**Prerequisites before building:**
1. Real traffic data — need traces showing which turns fail on Haiku vs. succeed on Sonnet
2. Evaluation framework (roadmap 4.6) — need to measure quality regression when switching models
3. Clear boundary definition — which SOP steps are "mechanical" vs. "reasoning"

## Consequences

**Phase 1 (now):**
- Prompt caching: ~90% input token savings on turns 2+ within a session (free win)
- Max turns: prevents runaway costs from confused agents (safety net)
- Exemplar injection: fewer wasted tool calls (measured after deployment)
- Static model tier: enables per-skill model selection when ready

**Phase 2 (future):**
- Significant cost reduction but adds architectural complexity
- Two agents to maintain instead of one
- Need evaluation framework to ensure quality doesn't regress
- Orchestrator prompt engineering is its own challenge

## Alternatives Considered

1. **Bedrock IPR only** — rejected as default: doesn't help when system prompt is always large
2. **Fine-tuned small model** — rejected: SOPs change frequently, fine-tuning is brittle and expensive to maintain
3. **Deterministic workflow (no LLM for mechanical steps)** — viable long-term (roadmap 7.x: agentic→deterministic graduation), but premature now
4. **Single model, just use Haiku everywhere** — rejected: quality regression on complex reasoning steps is unacceptable for financial accuracy
