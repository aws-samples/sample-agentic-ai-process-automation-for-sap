<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Evaluations Quick Start

The entry point for evaluating this ERP-exception agent. Pick a path below.

## Where do I go?

| I want to… | Go to |
|------------|-------|
| Run the regression suite before deploying a model/SOP change | [Run Regression Tests](#run-regression-tests) (`agentcore/evals/run_regression.py`) |
| Set up online (live) production evals | [`scripts/data/setup_evaluations.py`](#one-time-setup-online-evals) |
| Understand the custom `SAPActionAccuracy` evaluator, online-config internals, or deep API reference | [AGENTCORE_EVALUATIONS_GUIDE.md](AGENTCORE_EVALUATIONS_GUIDE.md) |
| See what it costs per case | [COST_BENCHMARK.md](COST_BENCHMARK.md) (~$0.26/case) |
| Lower that cost | [INFERENCE_COST_OPTIMIZATION.md](INFERENCE_COST_OPTIMIZATION.md) |

## Three evaluation layers

| Layer | When | What it checks |
|-------|------|----------------|
| **Regression** (on-demand) | Pre-deploy, CI | Agent produces correct workflow + tool calls for known ground-truth cases |
| **Online sampling** (live) | Production | LLM-as-judge scores a sample of live sessions, written to CloudWatch Logs |
| **`SAPActionAccuracy`** (custom) | Both | LLM-as-judge that checks workflow selection against materiality thresholds and accrual math |

## Run Regression Tests

Run this **before** deploying model changes or SOP updates.

```bash
# If the ground-truth cases already exist in SAP + DynamoDB:
python agentcore/evals/run_regression.py --stack-name <your-stack-name> --region <your-region>

# Create the cases first, then run (requires demo.test_data.enabled):
python agentcore/evals/run_regression.py --stack-name <your-stack-name> --region <your-region> --seed
```

It loads `agentcore/evals/ground_truth.json`, invokes the agent via AgentCore Runtime for each
case, runs five evaluators on each session (`Builtin.Correctness`, `Builtin.GoalSuccessRate`,
`Builtin.ToolSelectionAccuracy`, `Builtin.ToolParameterAccuracy`, `Builtin.Faithfulness`), and
prints a pass/fail summary. Default pass threshold is avg score `0.7` (`--threshold` to change).

With `--seed`, each case's `seed.sap_params` are POSTed to the demo `/test-data/ap-cases` endpoint
to create the PO + (optional) goods receipt + blocked invoice in SAP, a matching case record is
written to DynamoDB, and the invoke payload is rewritten to the real SAP keys (`document_number` =
supplier invoice number, `item_id` = fiscal year). Cases without a `seed` block are assumed to
already exist and are invoked as-is.

### Ground truth cases

Each case in `ground_truth.json` specifies the expected outcome and required tool calls for the
wired **finance_ap** domain (supplier-invoice three-way-match exceptions):

```json
{
  "test_id": "ap_price_variance_above_tolerance",
  "process_type": "price_variance",
  "payload": { "document_number": "5105600102", "item_id": "2026", "process_type": "price_variance" },
  "seed": {
    "sap_params": {
      "po_amount": 50000, "invoice_amount": 54000,
      "po_quantity": 10, "invoice_quantity": 10, "gr_quantity": 10,
      "payment_block": "R", "skip_gr": false
    }
  },
  "expected": {
    "outcome": "approval_required",
    "reason": "Price variance exceeds ±2% tolerance — requires procurement approval per SOP",
    "required_tool_calls": [
      "get_case_state",
      "odata_read",
      "search_sap_sops",
      "send_notification",
      "update_case_state"
    ]
  }
}
```

The runner consumes `payload` (it invokes the agent and scores the session with the five Builtin
evaluators); the `seed` block is used only by `--seed` to create the SAP data (`sap_params` matches
the `/test-data/ap-cases` request body).

**`expected` is asserted, not just documentation.** `check_expectations` reads the persisted case
record and fails the case if a `required_tool_calls` entry never appears in the trace, or if the
final status is outside the set `expected.outcome` maps to (`OUTCOME_TO_STATUS` — an unrecognized
outcome string is itself a failure, so a typo cannot pass silently). A case with no `expected`
block fails with "the case asserts nothing." A case passes only when **both** the deterministic
assertions and the judge threshold pass: the judges score how well the agent explained itself,
the assertions decide whether it did the right thing.

The `payload` key fields follow the case schema: `document_number` = supplier invoice number,
`item_id` = fiscal year (both rewritten to the real SAP keys when seeding).

> SAP OData reads/writes go through the external AWS for SAP MCP server, surfaced as MCP tools
> (`odata_read`, `odata_count`, `odata_create`, `odata_update`, …). Case state, SOP search, and
> notifications are AgentCore Gateway tools (`get_case_state`, `update_case_state`,
> `search_sap_sops`, `send_notification`). There are no homegrown `sap_read`/`sap_write` tools.

## One-Time Setup (online evals)

```bash
python scripts/data/setup_evaluations.py --stack-name <your-stack-name> --region <your-region> [--sampling-rate 25]
```

This creates the custom `SAPActionAccuracy` evaluator (Sonnet LLM-as-judge) and an online
evaluation config named `sap_agent_eval` that continuously samples live sessions. Results land in
CloudWatch Logs at `/aws/bedrock-agentcore/evaluations/results/{config-id}`. See the
[full guide](AGENTCORE_EVALUATIONS_GUIDE.md) for the evaluator definition and how to tune it.

## Key files

| File | Purpose |
|------|---------|
| `agentcore/evals/run_regression.py` | Regression test runner |
| `agentcore/evals/ground_truth.json` | Ground-truth cases (expected workflow + tool calls) |
| `scripts/data/setup_evaluations.py` | One-time online-eval + custom evaluator setup |
| `agentcore/evals/ap_cost_benchmark/run_benchmark.py` | Cost benchmark runner (see [COST_BENCHMARK.md](COST_BENCHMARK.md)) |
| [AGENTCORE_EVALUATIONS_GUIDE.md](AGENTCORE_EVALUATIONS_GUIDE.md) | Deep reference for this stack |
</content>
</invoke>
