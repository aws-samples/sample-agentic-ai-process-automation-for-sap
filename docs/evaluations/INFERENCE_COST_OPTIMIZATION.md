<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Inference Cost Optimization

The [Cost Benchmark](COST_BENCHMARK.md) established a baseline of **$0.26/case** in Bedrock inference across 50 AP exceptions. This guide covers six optimization levers to reduce that — potentially to under $0.10/case — without sacrificing accuracy. It also holds the **infrastructure cost context** (per-service rates, fixed monthly costs, and the cost-at-volume model) for the whole orchestration architecture.

For Knowledge Base infrastructure cost (now S3 Vectors pay-per-use), see [KB Cost Optimization](../getting-started/KNOWLEDGE_BASE_COST_OPTIMIZATION.md).

> Validate any lever below with the regression suite before shipping — see [EVALUATIONS_QUICKSTART.md](EVALUATIONS_QUICKSTART.md). A cost win that drops accuracy is not a win.

## Current Baseline

| Metric | Value |
|--------|-------|
| Model | Claude Sonnet 4 (single-agent, all turns) |
| Avg cost per case | $0.26 |
| Avg cache read tokens | 221K/invocation — summed over its 5–7 turns, not the prompt size |
| Assembled system prompt | 4.2K–5.0K tokens (persona + platform mechanics + routed SOP) |
| Avg turns per invocation | ~5–7 |
| Multi-agent mode | Built but disabled (`multi_agent: false`) |
| Exemplars | Infrastructure exists, content not generated |

The key insight from the benchmark: **60–70% of agent turns are mechanical** — calling tools, following SOP formulas, writing to DynamoDB. Only 2–3 turns per case require genuine reasoning (ambiguous date parsing, conflicting data resolution, escalation judgment). We're paying Sonnet prices ($3/$15 per M tokens) for Haiku-level work on most turns.

## Optimization 1: Enable Multi-Agent Mode (Haiku Orchestrator)

**Savings: 50–70% of inference cost | Effort: Config change + benchmark validation**

The Haiku orchestrator + Sonnet specialist architecture ([ADR-007](../design-decisions/007-multi-agent-orchestrator-specialist.md)) is fully implemented but feature-flagged off. Enabling it routes the orchestrator to Haiku ($0.80/$4 per M tokens) and only invokes Sonnet for ambiguous interpretation tasks.

### How It Works

```
Orchestrator (Haiku) — owns the event loop
  ├── Reads SOP, follows steps sequentially
  ├── Calls Gateway tools (gateway_sap_read, case_management, etc.)
  ├── Calls calculator for financial math
  └── Delegates to Specialist (Sonnet) when SOP says "if ambiguous"
```

The specialist is a stateless, tool-less Sonnet agent exposed as a tool to the orchestrator. It receives a focused task description and returns a reasoned answer. See `agentcore/agent/utils/specialist.py`.

### Config Change

In the relevant skill config (e.g., `skills/finance_ap/config.json`):

```json
{
  "multi_agent": true,
  "orchestrator_tier": "haiku",
  "specialist_tier": "sonnet"
}
```

The fields already exist in the configs — `multi_agent` just needs to flip from `false` to `true`. The agent entrypoint (`agentcore/agent/basic_agent.py`) already handles model selection, tool wiring, and per-tier cost tracking via `MetricsHook`.

### Cost Estimate

If 80% of tokens route through Haiku and 20% through Sonnet specialist:

| | Sonnet-only (current) | Haiku + Sonnet specialist |
|---|---|---|
| Blended input rate | $3.00/M | ~$1.24/M |
| Blended output rate | $15.00/M | ~$6.20/M |
| Blended cache read rate | $0.30/M | ~$0.12/M |
| **Estimated per-case cost** | **$0.26** | **~$0.10–0.15** |

### Validation

Run the AP cost benchmark with `multi_agent: true` and compare accuracy scores against the single-agent baseline before committing to production. The evaluation suite ([Full Guide](AGENTCORE_EVALUATIONS_GUIDE.md)) can detect quality regressions.

## Optimization 2: Generate Exemplars

**Savings: 20–30% fewer tokens per case | Effort: 1–2 days**

The exemplar infrastructure is fully wired:
- `exemplar_s3_key()` / `_fetch_exemplars()` in `agentcore/agent/utils/skill_router.py` load `{skill_id}/{process_type}_exemplars.md` from the exemplars bucket (`EXEMPLAR_BUCKET`) and append them to the system prompt
- `lambdas/exemplar_builder/` generates exemplars from successful case traces
- [ADR-005](../design-decisions/005-cost-optimization-model-routing.md) describes the design

But exemplar content hasn't been generated for most process types yet.

The writer and reader disagreed on that key once — the builder wrote one prefix, the router read another, and `_fetch_exemplars` swallowed the resulting 404 as "no exemplars yet," so a generated file looked identical to a missing one. Both sides now derive the key from the same format and `tests/unit/test_exemplar_key_parity.py` pins them byte-for-byte. If exemplars appear to have no effect, check that test before assuming the content is at fault.

### Why Exemplars Reduce Cost

Without exemplars, the agent explores: it tries different OData entities, makes speculative `odata_read` calls, and takes 5–7 turns to converge on the right tool sequence. With exemplars showing the exact tool call sequence for each exception type, the agent follows the demonstrated pattern and converges in 3–4 turns.

Fewer turns = fewer input/output tokens = lower cost.

### How to Generate

1. Run 5–10 successful cases per process type through the benchmark
2. Extract tool call sequences from the `agent_traces` in DynamoDB
3. Format as condensed exemplars showing: exception type → tool calls → outcome
4. Upload to the exemplars bucket at `{skill_id}/{process_type}_exemplars.md` — or better, let `exemplar_s3_key()` build the key, since a hand-typed one is what broke this before. Never the SOP bucket: the SOPs knowledge base ingests all of it, and a `search_sap_sops` hit on an LLM-condensed trace is indistinguishable from an authored SOP.
5. The skill router picks them up automatically on next invocation

The `exemplar_builder` Lambda can automate steps 2–4. Run it via EventBridge or manually:

```bash
aws lambda invoke --function-name {stack}-exemplar-builder \
  --payload '{"process_types": ["price_variance", "quantity_variance"]}' \
  /dev/stdout
```

### Combined Impact

Exemplars + Haiku orchestration compound: Haiku follows demonstrated patterns even more reliably than Sonnet follows exploratory reasoning. The combination could push per-case cost under $0.10.

## Optimization 3: Scope the Tool Results, Not the SOP

**Savings: the bulk of the ~221K cache reads | Effort: prompt guidance (shipped) + SOP audit**

The benchmark shows ~221K cache read tokens per invocation. It is tempting to read that as a 221K prompt and go compress SOPs — that is the wrong target. The assembled system prompt (persona + shared platform mechanics + routed SOP) measures **4.5K–5.2K tokens**:

```python
# PYTHONPATH=agentcore/agent
from utils import skill_router as sr
len(sr.resolve_skill("quantity_variance")["system_prompt"])  # ~18K chars ≈ 4.5K tokens
```

221K is the **sum over the invocation's 5–7 turns** of the whole cached prefix. The prompt is a small, fixed part of it; the growth is the conversation, and the conversation is mostly **tool results**. A single `odata_read` of `A_SupplierInvoice` without `select` returns 100+ fields, stays in context, and is re-read on every subsequent turn — so one unscoped read is billed five to seven times.

### What to Do

- **Scope every read.** `select` naming only the needed fields, `top` whenever not reading by key, `odata_count` instead of reading rows to count them, `expand` only when the related rows are needed this turn. This guidance now ships in `skills/_platform_prompt.txt` (SAP READS) so it reaches every skill.
- **Name all the fields a comparison needs in one call.** Two narrow reads cost more than one correctly-scoped read.
- **Then** audit SOPs — but for correctness and redundant inline examples, not for byte count. At ~1–3K tokens of SOP per case, a 30% prose cut saves under $0.0005 per invocation on Sonnet. It is not a cost lever.

| Model | Cache read cost per invocation (221K tokens) |
|-------|----------------------------------------------|
| Sonnet | $0.066 |
| Haiku | $0.018 |

Halving accumulated tool-result size roughly halves that line — two orders of magnitude more than SOP compression can reach.

## Optimization 4: Remove Redundant KB Searches

**Savings: 1–2 fewer tool calls per case | Effort: Config change**

The skill router already injects the correct SOP into the system prompt at runtime. Yet `finance_ap/config.json` also lists `search_sap_sops` in `gateway_tools`, and the agent often calls it redundantly — searching for the same SOP content it already has in context.

### Fix

Every tool in `gateway_tools` costs its JSON schema on every model request, called or not. Drop the grants nothing reaches for. `get_service_hints` was declared by both skills and named by no prompt or SOP, and `example_finance_accruals` declared `demo_update_ticket`/`demo_list_tickets` while its ticket protocol only creates and reads — all three are now gone from the shipped configs.

Keep `search_sap_sops`: the router injects the routed SOP, `load_sop` handles cross-SOP jumps, and `search_sap_sops` answers questions the loaded SOP does not. Keep `find_sap_services`/`get_metadata` too — they are the deliberate fallback when a pinned service name turns out wrong, and `get_metadata` is required before any `odata_function_import` to retrieve the parameter list. Keep `search_sap_api_docs` ([ADR-002](../design-decisions/002-two-layer-sap-api-knowledge.md) Layer 1).

The check: grep the skill's prompt and SOPs for each granted tool name. A tool no instruction mentions and no failure path needs is schema you pay for on every request.

```json
{
  "gateway_tools": [
    "get_case_state",
    "update_case_state",
    "odata_read",
    "odata_count",
    "odata_create",
    "odata_update",
    "odata_function_import",
    "find_sap_services",
    "get_metadata",
    "search_sap_sops",
    "search_sap_api_docs",
    "send_notification"
  ]
}
```

(SAP OData access is provided by the external AWS for SAP MCP server via the `odata_*` / `*_sap_*` gateway tools above; there are no homegrown `sap_read`/`sap_write` tools.)

Dropping a grant saves its schema on every request; a call the agent no longer makes also saves a Gateway round-trip (~2s) and the tokens of its result on every later turn. Both are small per case, free at the config layer.

## Optimization 5: Per-Process-Type Model Tier

**Savings: cheaper tier on eligible types | Effort: Feature work**

The benchmark shows cases worked with the Sonnet specialist cost more than those a Haiku orchestrator can resolve unaided. Most turns are mechanical and don't need Sonnet-level reasoning (see the baseline insight above).

For low-risk, high-volume exception types — `ap_exception`, `invoice_matching`, simple `price_variance` under a threshold — routing them to the cheaper Haiku orchestrator tier while reserving Sonnet for higher-risk types reduces inference cost on the bulk of volume.

### Current State

Model-tier selection is effectively global: a skill's `model_tier` / `multi_agent` config applies to every case that skill handles. A per-process-type override would allow:

```
price_variance (< $500)  → haiku
price_variance (≥ $500)  → sonnet
duplicate_invoice        → sonnet (always)
invoice_matching         → haiku
```

### Implementation Approach

Extend the skill config to support a per-process-type model-tier override map, with the skill-level setting as the fallback. The `agent_invoker` Lambda already resolves the model tier from the skill config — it would additionally check for a process-type-specific override.

## Optimization 6: Bedrock Intelligent Prompt Routing

**Savings: Variable | Effort: Config change | Risk: May not help**

Bedrock IPR routes each request within a model family to Haiku or Sonnet based on prompt complexity. Available as `"model_tier": "ipr-anthropic"` in skill configs ([ADR-005](../design-decisions/005-cost-optimization-model-routing.md)).

**Why it's listed last:** IPR evaluates the prompt text to decide complexity. Every queued request carries a whole SOP and the platform mechanics, so most will classify as complex and pick Sonnet anyway — not because the prompt is huge (it is 4.2K–5.0K tokens, per Optimization 3) but because procedural multi-step instructions read as complex regardless of length. The explicit multi-agent split (Optimization 1) gives more predictable savings because the routing decision is structural, not heuristic.

IPR may be more effective for chat-mode interactions (no SOP in context) where prompt complexity genuinely varies.

## Infrastructure Cost Context

Beyond Bedrock inference ($0.26/case avg), the orchestration architecture incurs per-request and fixed infrastructure costs. This section estimates them at three volume tiers using published AWS pricing for us-east-1 (April 2025). It complements the measured inference numbers in [COST_BENCHMARK.md](COST_BENCHMARK.md).

### Assumptions Per Case

Each case traverses the full pipeline: EventBridge → OData poller Lambda → SQS FIFO → agent invoker Lambda → AgentCore Runtime → Gateway tools (avg 5 tool calls) → SQS FIFO write queue → SAP write consumer Lambda. Supervised mode adds a ticket approval round (2 agent invocations per resolved case).

| Assumption | Value |
|-----------|-------|
| Agent invocations per case | 1.5 avg (1 initial + 0.5 approval round) |
| Gateway tool calls per invocation | 5 (gateway_sap_read, case_management, knowledge_base, notification/ticket, odata metadata) |
| AgentCore Runtime active CPU per invocation | 18s at 1 vCPU (70% I/O wait on 60s session) |
| AgentCore Runtime peak memory per invocation | 2 GB |
| Lambda duration per tool call | 2s avg at 256 MB |
| DynamoDB operations per case | ~10 writes (1 KB avg), ~20 reads (4 KB avg) |
| S3 reads per case | 2 (SOP + OData spec) |
| API Gateway calls per case | 3 (enqueue + status poll + ticket action) |
| Cedar policy checks per case | 5 (one per tool call) |
| AgentCore Memory events per case | 3 (conversation turns) |

### Per-Service Unit Rates (us-east-1, April 2025)

| Service | Dimension | Rate |
|---------|-----------|------|
| Lambda (ARM) | Requests / Duration | $0.20/1M req · $0.0000133334/GB-s |
| SQS FIFO | Requests | $0.50/1M |
| DynamoDB On-Demand | Write / Read / Storage | $0.625/1M WRU · $0.125/1M RRU · $0.25/GB-mo |
| S3 Standard | Storage / PUT / GET | $0.023/GB-mo · $0.005/1K · $0.0004/1K |
| API Gateway | REST API | $3.50/1M req |
| Secrets Manager | Storage / API | $0.40/secret-mo · $0.05/10K calls |
| AgentCore Runtime | CPU / Memory | $0.0895/vCPU-hr · $0.00945/GB-hr |
| AgentCore Gateway | Invocations | $0.005/1K |
| AgentCore Memory | Short-term events | $0.25/1K |
| AgentCore Policy | Auth requests | $0.000025/request |
| Amazon S3 Vectors | Upload / Storage / Query | Usage-based, pay-per-use (see [S3 pricing](https://aws.amazon.com/s3/pricing/)) |
| CloudWatch | Log ingestion | $0.50/GB |
| EventBridge | Events | $1.00/1M |

Source: published AWS pricing pages. Cognito (< 10K MAU) and SSM standard params are free; CloudTrail first trail is free.

### Fixed Monthly Costs (Volume-Independent)

| Resource | Monthly Cost | Notes |
|----------|-------------|-------|
| Amazon S3 Vectors (KBs) | ~$1–5 | Usage-based (upload + store + query); no compute-unit floor — idle ≈ storage-only |
| Secrets Manager (2 secrets) | $0.80 | SAP creds + machine client |
| CloudWatch dashboard | $3.00 | 1 custom dashboard |
| Amplify hosting | ~$1.00 | Static SPA |
| S3 + DynamoDB storage | ~$0.75 | < 1 GB each at low volume |
| EventBridge / CloudTrail / Cognito / SSM | ~$0.01 | Negligible / free tier |
| **Subtotal** | **~$7–11** | **No fixed vector-store floor — KB storage is now usage-based** |

> **There is no longer a fixed-cost vector-store floor.** Migrating the Knowledge Base vector store from OpenSearch Serverless to Amazon S3 Vectors removed the ~$700/month OCU minimum (two collections × 2-OCU floor). S3 Vectors is pay-per-use — at idle, cost is essentially storage-only — so KB infrastructure is now negligible relative to inference. See [KB Cost Optimization](../getting-started/KNOWLEDGE_BASE_COST_OPTIMIZATION.md) and [ADR-013](../design-decisions/013-s3-vectors-over-aoss.md).

### Variable Cost Per Case

The per-request infrastructure (AgentCore Runtime + Gateway + Memory + Policy, Lambda, SQS, DynamoDB, API Gateway, S3, CloudWatch, Secrets Manager) totals **~$0.003/case** — about 1% of the Bedrock inference cost. AgentCore Runtime dominates that at ~$0.0017/case (you pay only for active CPU, not I/O wait).

### Total Cost at Volume Tiers

| | 1K/month | 10K/month | 100K/month |
|---|---|---|---|
| Bedrock inference | $260 | $2,600 | $26,000 |
| AgentCore + Lambda + SQS + DDB + APIGW + S3 + CW + Secrets | ~$3.70 | ~$28 | ~$277 |
| Amazon S3 Vectors (KBs) | ~$3 | ~$3 | ~$3 |
| Other fixed (dashboard, trail, Cognito, SSM, Amplify) | ~$4 | ~$4 | ~$4 |
| **Total** | **~$271** | **~$2,635** | **~$26,284** |
| **Per case (all-in)** | **$0.27** | **$0.26** | **$0.26** |
| **Per case (excl. KB storage)** | **$0.27** | **$0.26** | **$0.26** |

**Takeaways:** (1) Bedrock inference dominates at every tier — ~96% of cost at 1K/month and ~99% at 100K/month. (2) The former OpenSearch Serverless fixed floor (~$700/month) is **gone** — S3 Vectors makes KB storage usage-based and negligible (~$3/month). (3) The orchestration layer (Lambda/SQS/DynamoDB/Gateway) adds ~1% marginal cost per case. (4) Even at 1K cases ($0.27/case), the system is 55–185× cheaper than manual AP processing ($15–50/exception).

*All prices from published AWS pricing pages as of April 2025, us-east-1. Use the [AWS Pricing Calculator](https://calculator.aws/) for deployment-specific estimates.*

## Summary

| # | Optimization | Effort | Per-Case Savings | Cumulative |
|---|---|---|---|---|
| 1 | Enable multi-agent (Haiku orchestrator) | Config + validation | 50–70% | ~$0.10–0.15 |
| 2 | Generate exemplars | 1–2 days | 20–30% fewer tokens | ~$0.08–0.12 |
| 3 | Scope the tool results | Prompt guidance (shipped) + SOP audit | Most of the cache-read line | ~$0.07–0.11 |
| 4 | Remove redundant KB searches | Config change | 1–2 fewer tool calls | ~$0.07–0.10 |
| 5 | Per-process-type model tier | Feature work | Cheaper tier on eligible types | ~$0.05–0.08 |
| 6 | Bedrock IPR | Config change | Variable (may not help) | — |

### Projected Cost at Volume

| Volume | Current ($0.26/case) | Optimized (~$0.08/case) |
|--------|---------------------|------------------------|
| 1K/month | $260 | ~$80 |
| 10K/month | $2,600 | ~$800 |
| 100K/month | $26,000 | ~$8,000 |

These inference savings stack on top of the infrastructure changes: the move to Amazon S3 Vectors already eliminated the ~$700/month fixed KB floor that previously dominated low-volume cost (see [KB Cost Optimization](../getting-started/KNOWLEDGE_BASE_COST_OPTIMIZATION.md)). With that floor gone and the inference optimizations applied, the all-in cost at 10K cases/month is ~$835 (~$800 inference + ~$35 usage-based infrastructure), down from ~$2,635 today.

## Key Files

| File | Purpose |
|------|---------|
| `skills/finance_ap/config.json` | `multi_agent`, `orchestrator_tier`, `specialist_tier` flags |
| `agentcore/agent/basic_agent.py` | Model tier routing, `MetricsHook` per-tier cost tracking |
| `agentcore/agent/utils/specialist.py` | Sonnet specialist agent-as-tool |
| `agentcore/agent/utils/skill_router.py` | `_fetch_exemplars()`, SOP injection |
| `agentcore/agent/utils/agent_metrics.py` | Per-model pricing table, `_estimate_cost()` |
| `lambdas/exemplar_builder/` | Automated exemplar generation from traces |
| [ADR-005](../design-decisions/005-cost-optimization-model-routing.md) | Cost optimization strategy — model routing |
| [ADR-007](../design-decisions/007-multi-agent-orchestrator-specialist.md) | Multi-agent orchestrator + specialist pattern |
| [Cost Benchmark](COST_BENCHMARK.md) | Baseline measurements this guide optimizes against |

## References

- [Amazon Bedrock pricing](https://aws.amazon.com/bedrock/pricing/)
- [Bedrock Intelligent Prompt Routing](https://docs.aws.amazon.com/bedrock/latest/userguide/cross-region-inference-support.html)
- [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/)
