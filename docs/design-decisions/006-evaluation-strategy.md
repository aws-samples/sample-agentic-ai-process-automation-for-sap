# ADR-006: Evaluation Strategy — Three-Layer Agent Quality Assurance

## Status
Accepted

## Context

Customers deploying AI agents against ERP/SAP systems have near-zero tolerance for errors. While human operators make mistakes too (that's why we're automating), an AI mistake carries different organizational risk — it's harder to explain, harder to audit, and erodes trust faster.

The evaluation challenge for agentic ERP automation is fundamentally different from chatbot evals:
- Chatbot eval: "Was the answer helpful?"
- Agent eval: "Did the agent take the right actions against real financial systems?"

We need to catch three categories of failure:
1. Model regressions (new model version produces worse outputs)
2. Runtime mistakes (agent hallucinated SAP data or miscalculated)
3. Process drift (agent deviated from SOP in ways that aren't justified)

## Decision

Three-layer evaluation strategy using AgentCore's built-in evaluation framework.

### Layer 1: Pre-Deployment Regression Tests (offline)

Ground truth test cases (`evals/ground_truth.json`) with known-correct expected outcomes. Run before deploying model changes or SOP updates.

- `evals/run_regression.py` invokes agent against test cases, then runs on-demand evaluations
- Built-in evaluators: Correctness, GoalSuccessRate, ToolSelectionAccuracy, ToolParameterAccuracy, Faithfulness
- Pass/fail threshold: configurable (default 0.7 average score)
- Blocks deployment if regression detected

### Layer 2: Online Continuous Monitoring (live)

AgentCore online evaluations sample a percentage of live sessions and run LLM-as-judge evaluators automatically.

- `scripts/data/setup_evaluations.py` configures the online eval config
- Sampling rate: 25% (staging), 10% (production)
- Same built-in evaluators as Layer 1, plus custom SAPActionAccuracy evaluator
- Results flow to CloudWatch Logs for dashboarding

### Layer 3: Custom Domain Evaluator (SAP-specific)

`SAPActionAccuracy` — a custom LLM-as-judge evaluator that checks:
1. Workflow selection matches materiality thresholds
2. Correct SAP OData endpoints called with valid parameters
3. Accrual calculation math is correct (accrual ≤ outstanding balance)
4. Agent used actual SAP response data, not hallucinated values
5. All required process steps were completed

This is the evaluator that directly addresses customer concerns about "is the agent doing the right thing against our SAP system?"

### What evals DON'T cover (and what does)

| Concern | Covered by |
|---------|-----------|
| Agent calls wrong SAP API | Layer 2+3 (ToolSelectionAccuracy + SAPActionAccuracy) |
| Agent hallucinates a PO number | Layer 2+3 (Faithfulness + SAPActionAccuracy) |
| Agent miscalculates accrual | Layer 3 (SAPActionAccuracy checks math) |
| Agent follows wrong workflow | Layer 3 (SAPActionAccuracy checks materiality routing) |
| Agent tries to DELETE data | Cedar policies (deterministic block, not eval) |
| Agent exceeds cost budget | CloudWatch alarms (observability, not eval) |
| Agent deviates from SOP intelligently | This is ACCEPTABLE — SOPs aren't perfect. Evals check outcomes, not rigid SOP adherence. |

## Consequences

- Pre-deployment regression tests add ~5 min to release process per test case
- Online evals cost ~$0.001 per evaluated session (LLM-as-judge token cost)
- At 10% sampling with 100 cases/day, that's ~$0.30/day for eval costs
- Custom evaluator prompt may need tuning as SOPs evolve
- Ground truth test cases need maintenance as business rules change

## Alternatives Considered

1. **Deterministic assertion tests only** — rejected: can't catch nuanced reasoning failures
2. **Human review of every case** — rejected: defeats the purpose of automation. Reserved for high-value cases via autonomy controls.
3. **Fine-tuned eval model** — rejected: overkill for current scale, hard to maintain
4. **No evals, just monitoring** — rejected: monitoring catches failures after they happen, evals catch them before deployment
