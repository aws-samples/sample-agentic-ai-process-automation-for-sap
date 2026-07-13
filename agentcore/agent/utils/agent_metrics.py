# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Agent Metrics — CloudWatch custom metrics emitted after each agent run.

Emits:
  - AgentTurns (count per run, dimensioned by process_type + model_tier)
  - AgentInputTokens / AgentOutputTokens / AgentCacheReadTokens
  - AgentLatencyMs (wall-clock time)
  - AgentEstimatedCost (USD estimate based on token counts)
  - AgentSuccess (1 or 0)

All metrics go to a custom namespace so they can be dashboarded alongside
Lambda/SQS/DDB metrics without polluting AWS/ namespaces.
"""

import os
import time
from typing import Optional

import boto3

_cw = None
NAMESPACE = os.environ.get("METRICS_NAMESPACE", "ERPAgent")

# Approximate pricing per 1K tokens (Bedrock on-demand, us-east-1).
# Verify at: https://aws.amazon.com/bedrock/pricing/
# These are estimates — for exact costs, use AWS Cost Explorer with the
# 'project' cost-allocation tag (see scripts/ops/infra_cost_report.py).
_PRICING = {
    "sonnet": {"input": 0.003, "output": 0.015, "cache_read": 0.0003, "cache_write": 0.00375},
    "haiku": {"input": 0.0008, "output": 0.004, "cache_read": 0.00008, "cache_write": 0.001},
}


def _get_cw():
    global _cw
    if _cw is None:
        region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
        _cw = boto3.client("cloudwatch", region_name=region)
    return _cw


def _estimate_cost(model_tier: str, input_tokens: int, output_tokens: int,
                   cache_read_tokens: int, cache_write_tokens: int = 0) -> float:
    prices = _PRICING.get(model_tier, _PRICING["sonnet"])
    billable_input = max(0, input_tokens - cache_read_tokens)
    return (
        (billable_input / 1000) * prices["input"]
        + (output_tokens / 1000) * prices["output"]
        + (cache_read_tokens / 1000) * prices["cache_read"]
        + (cache_write_tokens / 1000) * prices["cache_write"]
    )


def emit_agent_metrics(
    process_type: str,
    model_tier: str,
    turns: int,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
    latency_ms: float,
    success: bool,
):
    """Emit a batch of CloudWatch metrics for one agent run."""
    dims = [
        {"Name": "ProcessType", "Value": process_type},
        {"Name": "ModelTier", "Value": model_tier},
    ]

    cost = _estimate_cost(model_tier, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens)

    metric_data = [
        {"MetricName": "AgentTurns", "Value": turns, "Unit": "Count", "Dimensions": dims},
        {"MetricName": "AgentInputTokens", "Value": input_tokens, "Unit": "Count", "Dimensions": dims},
        {"MetricName": "AgentOutputTokens", "Value": output_tokens, "Unit": "Count", "Dimensions": dims},
        {"MetricName": "AgentCacheReadTokens", "Value": cache_read_tokens, "Unit": "Count", "Dimensions": dims},
        {"MetricName": "AgentCacheWriteTokens", "Value": cache_write_tokens, "Unit": "Count", "Dimensions": dims},
        {"MetricName": "AgentLatencyMs", "Value": latency_ms, "Unit": "Milliseconds", "Dimensions": dims},
        {"MetricName": "AgentEstimatedCostUSD", "Value": cost, "Unit": "None", "Dimensions": dims},
        {"MetricName": "AgentSuccess", "Value": 1 if success else 0, "Unit": "Count", "Dimensions": dims},
    ]

    try:
        _get_cw().put_metric_data(Namespace=NAMESPACE, MetricData=metric_data)
    except Exception as e:
        # Metrics are best-effort — never fail the agent run
        print(f"[METRICS] Failed to emit: {e}")
