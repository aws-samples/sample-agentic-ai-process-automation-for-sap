<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# AP Cost Benchmark Analysis — August 2026

This document explains the cost change observed in the August 8, 2026 AP benchmark run. It supplements the historical [AP Cost-Per-Exception Benchmark](COST_BENCHMARK.md), which remains the record of the earlier run.

## Result

The benchmark ran 50 AP cases against the non-production `erp-agent-dd3` stack in `us-east-1`. All 50 cases produced cost data and reached a verified terminal state. The durable result is [`agentcore/evals/ap_cost_benchmark/report.json`](../../agentcore/evals/ap_cost_benchmark/report.json), timestamped `2026-08-08T02:47:25.760169+00:00`.

| Metric | Earlier run | August 2026 run | Change |
|---|---:|---:|---:|
| Cases with cost | 41 / 50 | 50 / 50 | +9 cases |
| Total estimated inference cost | $10.527812 | $26.169988 | +$15.642176 (+148.6%) |
| Average reported cost | $0.2568 | $0.5234 | +103.8% |
| Median reported cost | $0.2141 | $0.5070 | +136.8% |
| p90 cost | $0.40 | $0.8014 | approximately +100% |
| Cost-bearing invocations | 46 | 77 | +67.4% |
| Total measured tokens | 11,629,624 | 21,903,542 | +88.3% |
| Terminal lifecycle validation | incomplete | 50 / 50 | complete |

The p90 value uses the benchmark runner's rank convention: `sorted_costs[int(n * 0.9)]`.

## Why the headline increase is not an architecture-only regression

The 148.6% total increase combines three different effects. It should not be reported as a controlled before-and-after measurement of the architecture.

### 1. The new run measured nine cases the earlier run missed

The earlier report contained no cost for nine cases. The new run measured all nine, adding:

- 14 invocations;
- $5.360734 of cost; and
- 34.3% of the total $15.642176 increase.

This is improved benchmark coverage, not increased cost for previously measured work.

### 2. The new run completed the human ticket lifecycle

The earlier report recorded 46 cost-bearing invocations for 41 costed cases. Most cases stopped after initial analysis or while waiting for another approval round. The new runner continued through fixture-driven approvals, denials, and context replies until each case reached a terminal state.

The new report contains 77 invocations:

- 50 initial case invocations; and
- 27 ticket-action callbacks: 15 approvals, 11 context replies, and 1 denial.

The extra lifecycle coverage is intentional. It measures more work per case than the earlier run. The strict fixtures also prove the three required paths:

- `AP-B24`: context reply → `complete`;
- `AP-B44`: denial → `manual_review_required`;
- `AP-B45`: approval → `complete`.

### 3. Cost per invocation also increased

Coverage and lifecycle depth do not explain the entire change. Estimated cost per invocation increased from $0.2289 to $0.3399, or 48.5%.

| Token measure | Earlier run | August 2026 run | Change |
|---|---:|---:|---:|
| Output tokens, total | 142,483 | 457,090 | +220.8% |
| Output tokens per invocation | 3,097 | 5,936 | +91.7% |
| Cache-read tokens, total | 10,433,442 | 21,444,976 | +105.5% |
| Input + cache-read tokens per invocation | 249,720 | 278,525 | +11.5% |

The strongest efficiency signal is output generation: the agent produced almost twice as many output tokens per invocation. Output tokens use a higher price than cached input, so this disproportionately affects cost.

The current run also exercised Agent Knowledge. It recorded 27 successful Gateway-backed graph calls across 21 cases: 21 `get_precedent` calls and 6 `check_vendor_risk` calls. Every call had `via_gateway=true`, `outcome=permitted`, and `mode=LOG_ONLY`. Graph retrieval, additional tool results, longer reasoning paths, and stricter SOP/evidence handling are plausible contributors to longer conversations, but this benchmark does not isolate their individual effects.

## Like-for-like view

Restricting the comparison to the same 41 cases that had cost in the earlier report removes the missing-case effect:

| Metric for the same 41 cases | Earlier run | August 2026 run | Change |
|---|---:|---:|---:|
| Estimated cost | $10.527812 | $20.809254 | +97.7% |
| Invocations | 46 | 63 | +37.0% |

This remains an imperfect comparison because the new run deliberately executes more callback rounds, Agent Knowledge was enabled, and the default model generation changed from the model used by the historical baseline. The cost estimator applies the configured `sonnet` tier rates, but model behavior can still change turn count and response length.

Raw input-token counts are also not directly comparable. They moved from 1,053,699 to 1,476 while cache reads increased, indicating a material change in cache attribution or instrumentation. The combined input-plus-cache measure is more useful for this comparison.

## Interpretation

Use the August result for current end-to-end budget planning: a fully lifecycle-valid AP case averaged $0.5234 in estimated Bedrock inference under this configuration.

Do not use the 148.6% total increase as the architecture regression number. A more accurate summary is:

1. About one-third of the total increase came from measuring nine previously uncosted cases.
2. Much of the remainder came from executing additional human-action callbacks needed to verify terminal outcomes.
3. The actionable efficiency regression is higher cost per invocation, led by a 91.7% increase in output tokens per invocation.

## Recommended follow-up

Run a controlled benchmark that records cost by invocation role and holds the case set, model, prompts, and lifecycle depth constant:

1. Classify each invocation as initial analysis, approval callback, denial callback, or context-reply callback.
2. Record model ID, turn count, tool-call count, Agent Knowledge call count, and token categories per invocation.
3. Compare cases with and without Agent Knowledge using the same fixtures and terminal-state requirements.
4. Identify the turns producing the largest output and tool-result payloads.
5. Re-run after any optimization and compare the same 50 fixtures with the same lifecycle policy.

The first optimization target should be output and turn reduction, not SOP compression. Narrow SAP reads, eliminate redundant tool calls, and inspect whether graph results or repeated approval reasoning remain in context longer than needed.

## Validation evidence

The August report passed these checks before commit:

- 50 cases and 50 unique benchmark IDs;
- `summary.valid=true` and no validation errors;
- 40 `complete` and 10 `manual_review_required`, with no nonterminal states;
- 27/27 valid Agent Knowledge Gateway calls;
- 48 focused unit tests;
- Python compilation, Ruff lint, selected-file formatting, JSON integrity, and Git whitespace checks.

`agentcore/agent/basic_agent.py` has broad pre-existing Ruff formatting drift and was not autoformatted because doing so would create unrelated changes. Pyright diagnostics were unavailable because `pyright-langserver` was not installed in the validation environment.
