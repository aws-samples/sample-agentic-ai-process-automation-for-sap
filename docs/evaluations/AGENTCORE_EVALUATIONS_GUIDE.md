<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# AgentCore Evaluations Guide (this stack)

How this ERP-exception agent uses Amazon Bedrock AgentCore evaluations: the regression suite, the
online-eval config, the custom `SAPActionAccuracy` evaluator, on-demand spot-checks, and best
practices. For generic AgentCore eval concepts (IAM setup, SDK install, the full evaluator catalog,
CloudWatch querying, dashboards), see the official
[AgentCore Evaluations docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/evaluations.html).

New here? Start at [EVALUATIONS_QUICKSTART.md](EVALUATIONS_QUICKSTART.md).

## Contents

1. [Setup pointer](#setup-pointer)
2. [Regression suite](#regression-suite)
3. [Online (live) evaluations for this stack](#online-live-evaluations-for-this-stack)
4. [Custom evaluator: SAPActionAccuracy](#custom-evaluator-sapactionaccuracy)
5. [On-demand evaluation](#on-demand-evaluation)
6. [Built-in evaluators we use](#built-in-evaluators-we-use)
7. [Where results land](#where-results-land)
8. [Best practices](#best-practices)
9. [References](#references)

---

## Setup pointer

Prereqs (deployed AgentCore runtime, IAM permissions for `bedrock-agentcore:*` /
`bedrock:InvokeModel` / eval-results log groups, `pip install bedrock-agentcore-starter-toolkit`)
are standard AgentCore eval setup — see the
[official prerequisites](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/evaluations.html).

This repo wires everything through two scripts:

| Script | Creates / does |
|--------|----------------|
| `scripts/data/setup_evaluations.py` | Custom `SAPActionAccuracy` evaluator + online config `sap_agent_eval` |
| `agentcore/evals/run_regression.py` | On-demand regression run against `ground_truth.json` |

```bash
# One-time: create custom evaluator + online sampling config
python scripts/data/setup_evaluations.py --stack-name <stack> --region <region> [--sampling-rate 25]
```

---

## Regression suite

The regression suite is the gate for **model changes and SOP updates**. Run it before deploying.

```bash
python agentcore/evals/run_regression.py --stack-name <stack> --region <region> [--threshold 0.7]
```

Flow (`run_regression.py`):

1. Loads cases from `agentcore/evals/ground_truth.json`.
2. For each case, invokes the agent via `bedrock-agentcore.invoke_agent_runtime` with the case
   `payload` (keyed by `document_number`, `item_id`, `process_type`) and a deterministic
   `runtimeSessionId`.
3. After a short trace-availability wait, runs five evaluators on the session:
   `Builtin.Correctness`, `Builtin.GoalSuccessRate`, `Builtin.ToolSelectionAccuracy`,
   `Builtin.ToolParameterAccuracy`, `Builtin.Faithfulness`.
4. Averages the scores per case; a case **passes** if avg ≥ `--threshold` (default `0.7`).
5. Prints a per-case pass/fail summary with per-evaluator scores.

### Ground-truth case shape

```json
{
  "test_id": "accrual_high_value_email",
  "description": "High-value PO ($500K outstanding) should trigger EMAIL_INQUIRY workflow",
  "process_type": "po_accrual",
  "payload": { "document_number": "4500099001", "item_id": "00010", "process_type": "po_accrual" },
  "expected": {
    "workflow": "EMAIL_INQUIRY",
    "reason": "Outstanding balance > $300K",
    "accrual_must_be_less_than_outstanding": true,
    "required_tool_calls": [
      "gateway_get_case_state",
      "gateway_sap_read",
      "gateway_send_notification",
      "gateway_update_case_state"
    ]
  }
}
```

`required_tool_calls` use the gateway-prefixed tool names. SAP OData access is provided by the
external AWS for SAP MCP server (gateway tools such as `gateway_sap_read`, `odata_read`,
`odata_create`, `odata_update`) — there are no homegrown `sap_read`/`sap_write` tools.

---

## Online (live) evaluations for this stack

`setup_evaluations.py` creates one online config that continuously samples live sessions and runs
LLM-as-judge evaluators, writing results to CloudWatch Logs.

| Setting | Value (this stack) |
|---------|--------------------|
| Config name | `sap_agent_eval` |
| Default sampling rate | `25%` (`--sampling-rate` to override) |
| Built-in evaluators | `Correctness`, `GoalSuccessRate`, `Faithfulness`, `ToolSelectionAccuracy`, `ToolParameterAccuracy` |
| Custom evaluator | `SAPActionAccuracy` (see below) |
| Execution role | Auto-created (`auto_create_execution_role=True`) |
| Enabled on create | Yes |

The script is idempotent — it reuses an existing `sap_agent_eval` config if one is found. To
pause, change sampling, or delete a config, use the starter-toolkit `Evaluation` client
(`update_online_config`, `delete_online_config`); see the official docs for those generic calls.

> Config creation takes ~10–30s; results appear in CloudWatch 2–5 min after the next sampled
> session.

---

## Custom evaluator: SAPActionAccuracy

This is the domain-specific evaluator — built-ins can't judge whether the agent picked the right
*accrual workflow* or did the *accrual math* correctly. Defined in `setup_evaluations.py`
(`create_custom_evaluator`): TRACE-level LLM-as-judge, Sonnet model, numeric scale `0.0–1.0`.

Judge instructions (verbatim intent):

```text
You are an expert SAP financial auditor evaluating an AI agent's actions.
Review the agent's complete session and evaluate whether its actions against SAP and
financial systems were correct and appropriate.

1. WORKFLOW SELECTION (by outstanding balance):
   - >$300K            → EMAIL_INQUIRY
   - >=$150K with WBS  → PROJECT_MILESTONE
   - >=$150K no WBS    → EMAIL_INQUIRY
   - <$150K            → DELIVERY_DATE
2. SAP API CALLS: correct OData endpoints with valid parameters?
3. ACCRUAL CALCULATION: Monthly Rate = Outstanding Balance / Duration;
   Accrual = Monthly Rate × Months Elapsed; result must be <= Outstanding Balance.
4. DATA INTEGRITY: used actual SAP response data, not hallucinated values?
5. PROCESS COMPLETENESS: data gathering, validation, calculation, approval request?

Score 0.0 if hallucinated SAP data or a calculation error.
Score 0.5 if the right process but minor mistakes.
Score 1.0 if all actions correct and well-reasoned.

{{input}} {{output}}
```

Rating scale: `NUMERIC`, `min=0.0`, `max=1.0`.

> The evaluator instructions reference the session input/output via the `{{input}} {{output}}`
> placeholders as written in `setup_evaluations.py`. Once created, `SAPActionAccuracy` is usable in
> both online and on-demand evaluations exactly like a built-in.

To change the thresholds or scoring, edit `create_custom_evaluator` in `setup_evaluations.py` and
re-run setup.

---

## On-demand evaluation

Use on-demand evals to spot-check a single session — debugging a reported issue or validating a
prompt/SOP change before a full regression run. The starter toolkit retrieves the session traces
automatically.

```python
from bedrock_agentcore_starter_toolkit import Evaluation

eval_client = Evaluation(region="<region>")

results = eval_client.run(
    agent_id="<agent-id>",        # last segment of the runtime ARN
    session_id="<session-id>",
    evaluators=[
        "Builtin.Correctness",
        "Builtin.ToolSelectionAccuracy",
        "SAPActionAccuracy-XXXXXXXXXX",  # ID from setup_evaluations.py / list_evaluators()
    ],
)

for r in results.results:
    print(f"{r.evaluator_name}: {r.value:.2f} [{r.label}] — {r.explanation}")
```

`run_regression.py` uses exactly this `eval_client.run(...)` path per case. Each evaluator takes
~5–15s; expect ~15–45s for three evaluators on one session.

---

## Built-in evaluators we use

This stack relies on six evaluators (five built-in + `SAPActionAccuracy`). The full built-in
catalog and placeholder reference live in the official docs.

| Evaluator | Level | Why this stack uses it |
|-----------|-------|------------------------|
| `Builtin.Correctness` | TRACE | Are the agent's stated facts/figures accurate? |
| `Builtin.Faithfulness` | TRACE | Did it stay grounded in SAP/SOP context (no hallucination)? |
| `Builtin.GoalSuccessRate` | SESSION | Did it resolve the exception end-to-end? |
| `Builtin.ToolSelectionAccuracy` | TOOL_CALL | Did it call the right gateway tools? |
| `Builtin.ToolParameterAccuracy` | TOOL_CALL | Correct OData params / case keys? |
| `SAPActionAccuracy` (custom) | TRACE | Workflow choice vs. materiality thresholds + accrual math |

---

## Where results land

| Eval type | Location |
|-----------|----------|
| Online | CloudWatch Logs `/aws/bedrock-agentcore/evaluations/results/{config-id}` (log group uses the **config ID**, not the name) |
| On-demand / regression | Returned synchronously from `eval_client.run(...)`; regression prints a summary to stdout |

`setup_evaluations.py` prints a ready-made CloudWatch console URL for the online results log group
on completion. For programmatic querying, aggregation, and CSV export, use standard CloudWatch
Logs APIs (`FilterLogEvents`, Logs Insights) — see the official docs.

---

## Best practices

**Gate deploys on regression.** Run `run_regression.py` before every model or SOP change. Keep the
threshold at `0.7` unless you have a reason to move it; investigate any case that regresses rather
than lowering the bar.

**Keep ground truth current.** When you add a process type or change a materiality threshold, add a
matching `ground_truth.json` case and update the `SAPActionAccuracy` instructions in lockstep — the
custom evaluator's thresholds and the agent's SOPs must agree.

**Sample by environment.** Dev/CI can run at high sampling for visibility; production `sap_agent_eval`
defaults to 25%. Lower it for cost, raise it when investigating a quality dip.

**Validate cost-optimization changes with evals.** Before enabling multi-agent mode or other levers
in [INFERENCE_COST_OPTIMIZATION.md](INFERENCE_COST_OPTIMIZATION.md), run the regression suite with
the change and compare scores against the single-agent baseline. A cost win that drops accuracy is
not a win.

**Set log retention.** Online results never expire by default; put a retention policy on the
eval-results log group to control CloudWatch storage cost.

**Watch the SAP-specific failure modes.** The two that matter most for this agent: hallucinated SAP
values (caught by `Faithfulness` + `SAPActionAccuracy` data-integrity check) and wrong workflow
selection at materiality boundaries (caught by `SAPActionAccuracy`). Low scores there usually point
to SOP ambiguity, not model regression.

---

## References

- [AgentCore Evaluations documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/evaluations.html) — generic setup, full evaluator catalog, querying, dashboards
- [CreateOnlineEvaluationConfig API](https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_CreateOnlineEvaluationConfig.html)
- [Evaluate API](https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_Evaluate.html)
- [EVALUATIONS_QUICKSTART.md](EVALUATIONS_QUICKSTART.md) · [COST_BENCHMARK.md](COST_BENCHMARK.md) · [INFERENCE_COST_OPTIMIZATION.md](INFERENCE_COST_OPTIMIZATION.md)
</content>
