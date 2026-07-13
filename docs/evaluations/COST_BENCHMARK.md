<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# AP Cost-Per-Exception Benchmark

Measures the real Bedrock cost of processing AP exceptions end-to-end — from SAP document creation through agent analysis, ticket-based human approval, and post-approval SAP execution. Every token is tracked per-case across all agent invocations.

This doc is the **benchmark result**. For static per-service infrastructure pricing and the cost-at-volume model, see [INFERENCE_COST_OPTIMIZATION.md](INFERENCE_COST_OPTIMIZATION.md). To reduce the per-case number, see the optimization levers there too.

## Results Summary

**50 AP cases** across 9 exception types and 3 complexity tiers, processed through the full production pipeline with real SAP documents and simulated ticket approvals.

| Metric | Value |
|--------|-------|
| Cases with cost data | 41 / 50 |
| Total Bedrock cost | $10.53 |
| Average cost per case | **$0.26** |
| Median cost per case | $0.21 |
| p90 cost per case | $0.40 |
| Std deviation | $0.12 |
| Min / Max | $0.16 / $0.73 |
| Total invocations | 46 |
| Total tokens | 11.6M |
| Total runtime | 34 minutes |

At $0.26/case, processing 10,000 AP exceptions per month costs approximately **$2,600 in Bedrock inference** — compared to $15–50 per exception for manual processing by an AP analyst.

> This is the **Bedrock inference** cost only. Infrastructure (AgentCore Runtime, Lambda, DynamoDB, Amazon S3 Vectors for the KBs, etc.) adds an all-in figure of ~$0.26–$0.27/case. KB vector storage now runs on S3 Vectors — usage-based with no fixed compute-unit floor — so KB infrastructure cost is negligible and inference dominates at every volume tier. See [INFERENCE_COST_OPTIMIZATION.md → Infrastructure cost context](INFERENCE_COST_OPTIMIZATION.md#infrastructure-cost-context).

### Cost by Complexity Tier

| Tier | Cases (w/cost) | Avg Cost | Avg Invocations | Avg Input Tokens | Avg Output Tokens | Avg Cache Read |
|------|----------------|----------|-----------------|------------------|-------------------|----------------|
| Simple | 10 / 15 | $0.39 | 1.5 | 32,381 | 4,142 | 393,529 |
| Medium | 16 / 19 | $0.22 | 1.0 | 23,416 | 3,197 | 222,021 |
| Escalation | 15 / 16 | $0.21 | 1.0 | 22,419 | 3,243 | 196,391 |

Simple cases averaged higher cost because 5 of them completed the full approval cycle (2 invocations: initial analysis + post-approval SAP execution), while medium and escalation cases mostly completed their first invocation within the benchmark window. The per-invocation cost is consistent at ~$0.20 regardless of complexity.

### Cost by Exception Type

| Process Type | Cases (w/cost) | Avg Cost | Notes |
|-------------|----------------|----------|-------|
| UOM mismatch | 3 / 3 | $0.21 | Unit conversion analysis |
| Three-way match | 4 / 7 | $0.21 | PO + GR + invoice reconciliation |
| AP exception (generic) | 4 / 4 | $0.21 | Simplest routing |
| Invoice matching | 7 / 8 | $0.22 | Full 2-way match |
| Missing goods receipt | 6 / 6 | $0.23 | GR status check, warehouse notification |
| Missing purchase order | 4 / 4 | $0.23 | PO search and matching |
| Duplicate invoice | 1 / 5 | $0.26 | Extra SAP reads to compare documents |
| Quantity variance | 6 / 6 | $0.32 | GR vs invoice qty reconciliation |
| Price variance | 6 / 7 | $0.37 | Highest — includes fully-resolved 2-invocation cases |

The cost spread across exception types is narrow ($0.21–$0.37) for single-invocation cases. Price variance appears highest because it had the most fully-resolved cases (2 invocations each).

### Fully-Resolved Cases (Complete Lifecycle)

Six cases completed the full cycle: analyze → create ticket → approve → execute SAP writes → resolved.

| Case | Type | Cost | Invocations | Status |
|------|------|------|-------------|--------|
| AP-B01 | price_variance | $0.46 | 2 | resolved |
| AP-B02 | price_variance | $0.40 | 2 | resolved |
| AP-B03 | price_variance | $0.50 | 2 | resolved |
| AP-B04 | price_variance | $0.52 | 2 | resolved |
| AP-B05 | quantity_variance | $0.73 | 2 | resolved |
| AP-B06 | quantity_variance | $0.73 | 2 | resolved |

**Average cost for a fully-resolved case: $0.56** (2 invocations). This is the true end-to-end cost when the agent analyzes the exception, gets human approval, and executes the corrective SAP transaction.

### Token Distribution

| Metric | Per Invocation (avg) | Total (41 cases) |
|--------|---------------------|-------------------|
| Input tokens | 25,000 | 1,025,000 |
| Output tokens | 3,500 | 143,500 |
| Cache read tokens | 250,000 | 10,250,000 |

**Prompt caching is the dominant cost factor.** The system prompt + SOP content (~200K tokens) is cached and reused across turns within each invocation. At $0.30/M tokens (Sonnet cache read rate), this is 10x cheaper than re-sending the full prompt each turn. Without caching, the average cost per case would be approximately $0.70.

### Agent Outcomes

| Status | Count | Description |
|--------|-------|-------------|
| `awaiting_human_input` | 24 | Completed first invocation, awaiting next approval round |
| `processing` | 10 | Still running or stuck at benchmark end |
| `complete` | 7 | Fully resolved autonomously (no SAP write needed) |
| `resolved` | 6 | Full lifecycle: analyze → approve → execute → resolved |
| `manual_review_required` | 1 | Agent determined case needs human expertise |
| `investigating` | 1 | Agent still gathering information |
| `analyzing` | 1 | Agent mid-analysis at benchmark end |

### Ticket Approval Flow

| Metric | Value |
|--------|-------|
| Cases reaching `awaiting_human_input` | 33 |
| Cases with `ticket_id` linked | 31 (94%) |
| Tickets approved | 31 |
| Cases re-processed after approval | 31 |
| Cases fully resolved after approval | 6 |

The 24 cases still in `awaiting_human_input` after re-processing are cases where the agent created a second ticket for the SAP write action — supervised mode requires approval for each write operation. A second approval round would resolve these.

## How It Works

### Architecture

```
cases.json (50 fixtures)
    │
    ▼
Demo API (POST /demo/test-data/ap-cases)
    │  Creates PO + GR + Invoice in SAP (~8s each)
    ▼
DynamoDB cases table (seed with benchmark metadata)
    │
    ▼
SQS FIFO queue → Agent Invoker Lambda → AgentCore Runtime
    │                                         │
    │                                    Strands Agent
    │                                    ├── gateway_sap_read (OData GET, via SAP MCP)
    │                                    ├── case_management (DDB)
    │                                    ├── demo_create_ticket ──→ writes ticket_id
    │                                    ├── notification          back to cases table
    │                                    └── knowledge_base
    │
    ▼
MetricsHook captures cumulative token usage per invocation
    │  Reads event_loop_metrics from both orchestrator (Haiku)
    │  and specialist (Sonnet) agents
    ▼
_save_trace_to_ddb() atomically increments cost_summary on the case item
    │  Uses DynamoDB ADD to accumulate across multiple invocations
    ▼
Benchmark runner approves tickets via Lambda invocation
    │  Bypasses Cognito auth on the feedback API
    ▼
Agent re-processes approved cases (second invocation)
    │  Executes SAP writes, updates case status
    ▼
Final report with per-case cost breakdown
```

SAP OData reads/writes are served by the external AWS for SAP MCP server, surfaced to the agent as gateway tools (e.g. `gateway_sap_read`, `odata_read`, `odata_create`).

### Per-Case Cost Accumulator

Each agent invocation writes a cost accumulator to the DynamoDB case item using two atomic operations:

1. **Initialize** — `SET cost_summary = if_not_exists(cost_summary, :init)` creates the map with zero counters on first invocation
2. **Increment** — `ADD cost_summary.total_cost_usd :cost, ...` atomically adds the delta from the current invocation

This handles multi-invocation cases (initial analysis → ticket approval → resumed processing) by summing costs across all invocations on the same case item.

Tracked counters: `total_cost_usd` (Decimal), `total_input_tokens`, `total_output_tokens`, `total_cache_read_tokens`, `invocation_count`.

### Multi-Agent Token Tracking

The system supports a Haiku orchestrator + Sonnet specialist architecture ([ADR-007](../design-decisions/007-multi-agent-orchestrator-specialist.md)). `MetricsHook` reads accumulated usage from both agents' `event_loop_metrics` and applies the correct per-model pricing:

| Model | Input | Output | Cache Read | Cache Write |
|-------|-------|--------|------------|-------------|
| Claude Sonnet 4 | $3.00/M | $15.00/M | $0.30/M | $3.75/M |
| Claude Haiku 3.5 | $0.80/M | $4.00/M | $0.08/M | $1.00/M |

Pricing source: [Amazon Bedrock pricing](https://aws.amazon.com/bedrock/pricing/)

### Ticket Linkage

The `demo_create_ticket` Gateway tool writes `ticket_id` back to the cases table when a `case_id` is provided. This lets the benchmark runner find and approve tickets programmatically. Without this linkage, ticket approval depends on the agent explicitly calling `update_case_state` with the ticket ID — which is non-deterministic.

### Benchmark Fixtures

`agentcore/evals/ap_cost_benchmark/cases.json` contains 50 AP cases across:

- **9 process types**: price_variance, quantity_variance, duplicate_invoice, three_way_match, uom_mismatch, missing_goods_receipt, invoice_matching, missing_purchase_order, ap_exception
- **3 complexity tiers**: simple (15), medium (19), escalation (16)

Each case includes `sap_params` that drive the Demo API to create realistic SAP documents with specific variance amounts, quantities, and pricing that trigger the target exception type.

## Running the Benchmark

### Prerequisites

- Deployed stack (`make deploy-all`)
- Test-data infrastructure enabled (`demo.test_data.enabled: true`, or `demo.enabled: true` for both, in `cdk/config.yaml`)
- SAP credentials configured (`make sync-sap-secret`)

### Single-Case Validation

```bash
python agentcore/evals/ap_cost_benchmark/run_benchmark.py \
  --stack-name erp-accrual-agent --region us-east-1 --limit 5
```

### Full 50-Case Run

```bash
python agentcore/evals/ap_cost_benchmark/run_benchmark.py \
  --stack-name erp-accrual-agent --region us-east-1 --max-wait 1500
```

`--max-wait` controls how long to wait for agent processing (default 600s). With 50 cases and `maxConcurrency: 5` on the SQS queue, expect ~25 minutes for initial processing plus ~2 minutes for the approval cycle. Total runtime ~35 minutes including SAP document creation.

### Re-reading Results (Skip SAP Creation)

```bash
python agentcore/evals/ap_cost_benchmark/run_benchmark.py \
  --stack-name erp-accrual-agent --region us-east-1 --skip-sap --max-wait 1200
```

Loads PO numbers from DynamoDB and re-enqueues cases that are still pending.

### Output

The runner logs each phase with timestamps, per-case transitions, status breakdowns during polling, and ticket approval results. A detailed `report.json` is saved to `agentcore/evals/ap_cost_benchmark/`.

### Actual Deployed Cost (Cost Explorer)

For real billed costs rather than estimates, `scripts/ops/infra_cost_report.py` queries AWS Cost Explorer filtered by the `project` cost-allocation tag, grouped by `architecture-component`:

```bash
python scripts/ops/infra_cost_report.py --stack-name erp-accrual-agent --days 30
```

## Key Files

| File | Purpose |
|------|---------|
| `agentcore/evals/ap_cost_benchmark/cases.json` | 50 AP test case fixtures |
| `agentcore/evals/ap_cost_benchmark/run_benchmark.py` | Benchmark runner (6-phase pipeline) |
| `agentcore/evals/ap_cost_benchmark/report.json` | Latest benchmark results |
| `agentcore/agent/basic_agent.py` | Cost accumulator in `_save_trace_to_ddb()`, `MetricsHook` |
| `agentcore/agent/utils/agent_metrics.py` | Pricing table and `_estimate_cost()` |
| `agentcore/gateway/tools/demo_ticket_management/` | Ticket tool with `ticket_id` writeback |
| `scripts/ops/infra_cost_report.py` | AWS Cost Explorer infrastructure report |

## Technical Notes

**Why Decimal?** DynamoDB rejects Python `float`. All cost values are converted to `Decimal` before writing. The `ADD` operation on nested map attributes requires consistent numeric types — mixing `float` and `Decimal` fails silently with "Float types are not supported. Use Decimal types instead."

**Trace save timing.** The cost accumulator writes after the agent stream completes, which is after the case status changes. The runner adds a 15-second delay before the final read so traces are persisted.

**Prompt caching impact.** The ~250K cache read tokens per invocation are the system prompt + SOP content cached across turns. Without caching, each invocation would consume ~250K additional input tokens at $3.00/M instead of $0.30/M, roughly tripling per-case cost.

**Stuck cases.** ~10–15% of cases remain in `processing` at benchmark end (long SAP read chains or runtime timeout without a status update). They typically have partial cost data. Increasing `--max-wait` captures more; some need manual investigation.

**Supervised mode and multi-approval.** In `supervised` action mode the agent creates an approval ticket for every SAP write. A case may need multiple rounds: (1) analyze + create ticket, (2) on approval, execute the write and possibly create another ticket, repeat. The benchmark runs one approval round, so cases needing more end in `awaiting_human_input`. Running `full-auto` skips the approval cycle entirely.
</content>
