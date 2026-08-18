# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# This is sample code. Not for use in production.
# See NOTICE and LICENSE for more information.
"""
Observability API Lambda

Queries CloudWatch metrics and returns agent performance data for the
Observability dashboard. Read-only — no writes to any resource.

Routes:
  GET /observability/metrics   — agent performance metrics (last N hours)
  GET /observability/health    — infrastructure health (Lambda errors, SQS depth, alarms)
  GET /observability/traces    — recent agent traces with case context
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import boto3

# Canonical case identity codec — ships in the shared_types layer.
from case_key import CaseKeyError, format_case_id

logger = logging.getLogger()
logger.setLevel(logging.INFO)

cw = boto3.client("cloudwatch")
sqs = boto3.client("sqs")
cw_alarms = boto3.client("cloudwatch")
dynamodb = boto3.resource("dynamodb")

METRICS_NAMESPACE = os.environ.get("METRICS_NAMESPACE", "ERPAgent")
STACK_NAME = os.environ["STACK_NAME_BASE"]
QUEUE_URL = os.environ.get("AGENT_QUEUE_URL", "")
DLQ_URL = os.environ.get("AGENT_DLQ_URL", "")
TABLE_NAME = os.environ.get("TABLE_NAME", "")
ALLOWED_ORIGINS = os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:3000")


def _cors_headers(origin: str) -> dict:
    allowed = [o.strip() for o in ALLOWED_ORIGINS.split(",")]
    if origin in allowed:
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,OPTIONS",
        }
    return {}


def _response(status_code: int, body: object, origin: str = "") -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json", **_cors_headers(origin)},
        "body": json.dumps(body, default=str),
    }


def _get_metric(
    metric_name: str, stat: str, period: int, hours: int, by_model: bool = False
) -> list[dict] | dict[str, list[dict]]:
    """Query a single CloudWatch metric from the ERPAgent namespace.

    Uses get_metric_data with a SEARCH expression to aggregate across all
    dimension combinations (ProcessType × ModelTier).  Falls back to
    get_metric_statistics (no dimensions) for backwards compatibility when
    SEARCH returns nothing.

    When by_model=True, returns a dict keyed by ModelTier dimension value
    instead of merging all dimension combos into a single series.
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)

    # Map friendly stat names to CloudWatch SEARCH stat functions
    stat_fn = stat  # SampleCount, Average, Sum, Maximum, etc.
    is_percentile = stat.startswith("p") and stat[1:].isdigit()

    # SEARCH expression: find all dimension combos for this metric and aggregate
    search_expr = (
        f"SEARCH('{{{METRICS_NAMESPACE},{metric_name}}}', '{stat_fn}', {period})"
        if not is_percentile
        else None
    )

    # For percentile stats, SEARCH doesn't support them directly — use
    # get_metric_statistics with no dimensions (will only work for
    # non-dimensioned metrics).  For dimensioned percentiles we fall through
    # to the empty-result path.
    if search_expr:
        try:
            resp = cw.get_metric_data(
                MetricDataQueries=[
                    {
                        "Id": "search_agg",
                        "Expression": search_expr,
                        "Period": period,
                    }
                ],
                StartTime=start,
                EndTime=end,
            )
            results = resp.get("MetricDataResults", [])

            if by_model:
                # Return per-ModelTier series instead of merging
                per_model: dict[str, dict[str, float]] = {}
                for r in results:
                    # Extract ModelTier from the result label (format: "MetricName ModelTier DimVal ...")
                    model_tier = _extract_model_tier(r.get("Label", ""))
                    if not model_tier:
                        model_tier = "unknown"
                    if model_tier not in per_model:
                        per_model[model_tier] = {}
                    for ts, val in zip(r.get("Timestamps", []), r.get("Values", [])):
                        key = ts.isoformat()
                        if stat_fn in ("SampleCount", "Sum"):
                            per_model[model_tier][key] = (
                                per_model[model_tier].get(key, 0) + val
                            )
                        elif stat_fn == "Maximum":
                            per_model[model_tier][key] = max(
                                per_model[model_tier].get(key, 0), val
                            )
                        else:
                            if key in per_model[model_tier]:
                                per_model[model_tier][key] = (
                                    per_model[model_tier][key] + val
                                ) / 2
                            else:
                                per_model[model_tier][key] = val

                result = {}
                for tier, merged in per_model.items():
                    points = [{"t": k, "v": v} for k, v in merged.items()]
                    points.sort(key=lambda p: p["t"])
                    result[tier] = points
                return result if result else {}

            # Merged (default) — aggregate across all dimension combos
            merged: dict[str, float] = {}
            for r in results:
                timestamps = r.get("Timestamps", [])
                values = r.get("Values", [])
                for ts, val in zip(timestamps, values):
                    key = ts.isoformat()
                    if stat_fn == "SampleCount" or stat_fn == "Sum":
                        merged[key] = merged.get(key, 0) + val
                    elif stat_fn == "Maximum":
                        merged[key] = max(merged.get(key, 0), val)
                    else:  # Average — weighted average would need counts, use simple avg
                        if key in merged:
                            merged[key] = (merged[key] + val) / 2
                        else:
                            merged[key] = val

            if merged:
                points = [{"t": k, "v": v} for k, v in merged.items()]
                points.sort(key=lambda p: p["t"])
                return points
        except Exception:
            logger.warning(
                "SEARCH query failed for %s/%s, falling back", metric_name, stat
            )

    # Fallback: original get_metric_statistics (no dimensions)
    params = {
        "Namespace": METRICS_NAMESPACE,
        "MetricName": metric_name,
        "StartTime": start,
        "EndTime": end,
        "Period": period,
    }
    if is_percentile:
        params["ExtendedStatistics"] = [stat]
    else:
        params["Statistics"] = [stat]

    resp = cw.get_metric_statistics(**params)

    points = resp.get("Datapoints", [])
    points.sort(key=lambda p: p["Timestamp"])

    if is_percentile:
        result = [
            {
                "t": p["Timestamp"].isoformat(),
                "v": p.get("ExtendedStatistics", {}).get(stat, 0),
            }
            for p in points
        ]
    else:
        result = [{"t": p["Timestamp"].isoformat(), "v": p[stat]} for p in points]

    if by_model:
        return {"unknown": result} if result else {}
    return result


def _extract_model_tier(label: str) -> str | None:
    """Extract ModelTier value from a CloudWatch SEARCH result label.

    Labels from SEARCH typically contain dimension values. We look for known
    model tier names (sonnet, haiku) in the label string.
    """
    label_lower = label.lower()
    for tier in ("sonnet", "haiku"):
        if tier in label_lower:
            return tier
    return None


def _handle_metrics(qs: dict, origin: str) -> dict:
    """GET /observability/metrics — agent performance over time.

    Query params:
      hours   — lookback window (default 24)
      period  — CloudWatch period in seconds (default 3600)
      by_model — when "true", adds a `byModel` key with per-ModelTier series
    """
    hours = int(qs.get("hours", "24"))
    period = int(qs.get("period", "3600"))  # default 1h buckets
    want_by_model = qs.get("by_model", "").lower() == "true"

    data = {
        "timeRange": {"hours": hours, "period": period},
        "casesProcessed": _get_metric("AgentSuccess", "SampleCount", period, hours),
        "successRate": _get_metric("AgentSuccess", "Average", period, hours),
        "avgTurns": _get_metric("AgentTurns", "Average", period, hours),
        "maxTurns": _get_metric("AgentTurns", "Maximum", period, hours),
        "avgLatencyMs": _get_metric("AgentLatencyMs", "Average", period, hours),
        "p90LatencyMs": _get_metric("AgentLatencyMs", "p90", period, hours),
        "avgCostUSD": _get_metric("AgentEstimatedCostUSD", "Average", period, hours),
        "totalCostUSD": _get_metric("AgentEstimatedCostUSD", "Sum", period, hours),
        "inputTokens": _get_metric("AgentInputTokens", "Sum", period, hours),
        "outputTokens": _get_metric("AgentOutputTokens", "Sum", period, hours),
        "cacheReadTokens": _get_metric("AgentCacheReadTokens", "Sum", period, hours),
        "cacheWriteTokens": _get_metric("AgentCacheWriteTokens", "Sum", period, hours),
    }

    # Per-model breakdown (opt-in via ?by_model=true)
    if want_by_model:
        data["byModel"] = {
            "inputTokens": _get_metric(
                "AgentInputTokens", "Sum", period, hours, by_model=True
            ),
            "outputTokens": _get_metric(
                "AgentOutputTokens", "Sum", period, hours, by_model=True
            ),
            "cacheReadTokens": _get_metric(
                "AgentCacheReadTokens", "Sum", period, hours, by_model=True
            ),
            "cacheWriteTokens": _get_metric(
                "AgentCacheWriteTokens", "Sum", period, hours, by_model=True
            ),
            "avgLatencyMs": _get_metric(
                "AgentLatencyMs", "Average", period, hours, by_model=True
            ),
            "totalCostUSD": _get_metric(
                "AgentEstimatedCostUSD", "Sum", period, hours, by_model=True
            ),
            "casesProcessed": _get_metric(
                "AgentSuccess", "SampleCount", period, hours, by_model=True
            ),
            "avgTurns": _get_metric(
                "AgentTurns", "Average", period, hours, by_model=True
            ),
        }

    # Summary stats (last 24h single-point)
    summary_period = 86400
    summary = {
        "totalCases": _get_metric("AgentSuccess", "SampleCount", summary_period, 24),
        "avgSuccess": _get_metric("AgentSuccess", "Average", summary_period, 24),
        "avgCost": _get_metric("AgentEstimatedCostUSD", "Average", summary_period, 24),
        "avgLatency": _get_metric("AgentLatencyMs", "Average", summary_period, 24),
    }
    data["summary"] = {
        "totalCases": summary["totalCases"][0]["v"] if summary["totalCases"] else 0,
        "successRate": round(
            (summary["avgSuccess"][0]["v"] if summary["avgSuccess"] else 0) * 100, 1
        ),
        "avgCostUSD": round(summary["avgCost"][0]["v"] if summary["avgCost"] else 0, 4),
        "avgLatencyMs": round(
            summary["avgLatency"][0]["v"] if summary["avgLatency"] else 0
        ),
    }

    # If CloudWatch metrics are empty, derive from DynamoDB traces as fallback
    if data["summary"]["totalCases"] == 0:
        trace_derived = _derive_metrics_from_traces(hours)
        if trace_derived:
            data["summary"]["totalCases"] = trace_derived.get("totalCases", 0)
            data["summary"]["successRate"] = trace_derived.get("successRate", 0)
            data["summary"]["avgCostUSD"] = trace_derived.get(
                "avgCostUSD", data["summary"]["avgCostUSD"]
            )
            data["summary"]["avgLatencyMs"] = trace_derived.get(
                "avgLatencyMs", data["summary"]["avgLatencyMs"]
            )
            data["summary"]["source"] = "traces"

            # Populate ALL chart series from trace data
            for key, trace_key in [
                ("casesProcessed", "casesProcessed"),
                ("successRate", "successRate_series"),
                ("avgLatencyMs", "avgLatencyMs_series"),
                ("p90LatencyMs", "p90LatencyMs_series"),
                ("totalCostUSD", "totalCostUSD_series"),
                ("inputTokens", "inputTokens_series"),
                ("outputTokens", "outputTokens_series"),
                ("cacheReadTokens", "cacheReadTokens_series"),
            ]:
                if not data[key] and trace_derived.get(trace_key):
                    data[key] = trace_derived[trace_key]

            # Per-model from traces when CW is empty
            if want_by_model and "byModelTokens" in trace_derived:
                data["byModel"] = trace_derived["byModelTokens"]

    return _response(200, data, origin)


def _derive_metrics_from_traces(hours: int) -> dict:
    """Derive summary metrics AND time-series chart data from DynamoDB trace
    data as a fallback when CloudWatch custom metrics are unavailable.

    Returns a dict with:
      - summary fields (totalCases, successRate, avgCostUSD, avgLatencyMs)
      - time-series arrays keyed the same as the CW-based response so the
        frontend charts render without changes
      - byModelTokens when model_tier is present in trace records
    """
    if not TABLE_NAME:
        return {}

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    table = dynamodb.Table(TABLE_NAME)

    try:
        scan_kwargs = {
            "FilterExpression": "updated_at >= :cutoff",
            "ExpressionAttributeValues": {":cutoff": cutoff},
            "ProjectionExpression": "agent_traces, updated_at",
        }
        items = []
        while True:
            resp = table.scan(**scan_kwargs)
            items.extend(resp.get("Items", []))
            last_key = resp.get("LastEvaluatedKey")
            if not last_key:
                break
            scan_kwargs["ExclusiveStartKey"] = last_key
    except Exception:
        logger.warning("Failed to derive metrics from traces", exc_info=True)
        return {}

    # Collect every trace with its timestamp
    all_traces: list[dict] = []
    for case in items:
        for trace in case.get("agent_traces") or []:
            ts = trace.get("timestamp", "")
            if ts >= cutoff:
                all_traces.append(trace)

    if not all_traces:
        return {}

    total_traces = len(all_traces)
    complete_count = sum(1 for t in all_traces if t.get("outcome") == "complete")

    # Bucket key = ISO hour string (truncated to hour)
    buckets: dict[str, dict] = {}
    by_model: dict[str, dict] = {}

    for trace in all_traces:
        ts = trace.get("timestamp", "")
        # Truncate to hour for bucketing
        bucket_key = ts[:13] + ":00:00" if len(ts) >= 13 else ts

        if bucket_key not in buckets:
            buckets[bucket_key] = {
                "cases": 0,
                "successes": 0,
                "latency_sum": 0.0,
                "latency_max": 0.0,
                "cost_sum": 0.0,
                "input": 0,
                "output": 0,
                "cache_read": 0,
                "traces_with_metrics": 0,
            }
        b = buckets[bucket_key]
        b["cases"] += 1
        if trace.get("outcome") == "complete":
            b["successes"] += 1

        if "latency_ms" in trace:
            latency = float(trace.get("latency_ms", 0))
            cost = float(trace.get("estimated_cost_usd", 0))
            inp = int(trace.get("input_tokens", 0))
            out = int(trace.get("output_tokens", 0))
            cache_r = int(trace.get("cache_read_tokens", 0))
            cache_w = int(trace.get("cache_write_tokens", 0))

            b["traces_with_metrics"] += 1
            b["latency_sum"] += latency
            b["latency_max"] = max(b["latency_max"], latency)
            b["cost_sum"] += cost
            b["input"] += inp
            b["output"] += out
            b["cache_read"] += cache_r

            # Per-model accumulation
            tier = trace.get("model_tier", "unknown")
            if tier not in by_model:
                by_model[tier] = {
                    "input": 0,
                    "output": 0,
                    "cache_read": 0,
                    "cache_write": 0,
                    "cost": 0.0,
                    "latency": 0.0,
                    "cases": 0,
                }
            by_model[tier]["input"] += inp
            by_model[tier]["output"] += out
            by_model[tier]["cache_read"] += cache_r
            by_model[tier]["cache_write"] += cache_w
            by_model[tier]["cost"] += cost
            by_model[tier]["latency"] += latency
            by_model[tier]["cases"] += 1

    sorted_keys = sorted(buckets.keys())

    cases_series = [{"t": k, "v": buckets[k]["cases"]} for k in sorted_keys]
    success_series = [
        {
            "t": k,
            "v": (buckets[k]["successes"] / buckets[k]["cases"] * 100)
            if buckets[k]["cases"]
            else 0,
        }
        for k in sorted_keys
    ]
    avg_latency_series = [
        {
            "t": k,
            "v": (buckets[k]["latency_sum"] / buckets[k]["traces_with_metrics"])
            if buckets[k]["traces_with_metrics"]
            else 0,
        }
        for k in sorted_keys
    ]
    p90_latency_series = [
        {"t": k, "v": buckets[k]["latency_max"]}  # max as p90 proxy
        for k in sorted_keys
    ]
    cost_series = [{"t": k, "v": buckets[k]["cost_sum"]} for k in sorted_keys]
    input_series = [{"t": k, "v": buckets[k]["input"]} for k in sorted_keys]
    output_series = [{"t": k, "v": buckets[k]["output"]} for k in sorted_keys]
    cache_series = [{"t": k, "v": buckets[k]["cache_read"]} for k in sorted_keys]

    total_input = sum(b["input"] for b in buckets.values())
    total_output = sum(b["output"] for b in buckets.values())
    total_cache = sum(b["cache_read"] for b in buckets.values())
    total_latency = sum(b["latency_sum"] for b in buckets.values())
    total_cost = sum(b["cost_sum"] for b in buckets.values())
    total_with_metrics = sum(b["traces_with_metrics"] for b in buckets.values())

    result: dict = {
        "totalCases": total_traces,
        "successRate": round((complete_count / total_traces) * 100, 1),
        "source": "traces",
        # Time-series for charts
        "casesProcessed": cases_series,
        "successRate_series": success_series,
        "avgLatencyMs_series": avg_latency_series,
        "p90LatencyMs_series": p90_latency_series,
        "totalCostUSD_series": cost_series,
        "inputTokens_series": input_series,
        "outputTokens_series": output_series,
        "cacheReadTokens_series": cache_series,
    }

    if total_with_metrics > 0:
        result["avgLatencyMs"] = round(total_latency / total_with_metrics)
        result["avgCostUSD"] = round(total_cost / total_with_metrics, 4)
        result["totalInputTokens"] = total_input
        result["totalOutputTokens"] = total_output
        result["totalCacheReadTokens"] = total_cache

    # Build per-model breakdown for frontend
    if by_model:
        now_iso = datetime.now(timezone.utc).isoformat()
        bm: dict[str, dict] = {
            "inputTokens": {},
            "outputTokens": {},
            "cacheReadTokens": {},
            "cacheWriteTokens": {},
            "totalCostUSD": {},
            "avgLatencyMs": {},
            "casesProcessed": {},
            "avgTurns": {},
        }
        for tier, acc in by_model.items():
            bm["inputTokens"][tier] = [{"t": now_iso, "v": acc["input"]}]
            bm["outputTokens"][tier] = [{"t": now_iso, "v": acc["output"]}]
            bm["cacheReadTokens"][tier] = [{"t": now_iso, "v": acc["cache_read"]}]
            bm["cacheWriteTokens"][tier] = [{"t": now_iso, "v": acc["cache_write"]}]
            bm["totalCostUSD"][tier] = [{"t": now_iso, "v": acc["cost"]}]
            bm["casesProcessed"][tier] = [{"t": now_iso, "v": acc["cases"]}]
            bm["avgLatencyMs"][tier] = [
                {
                    "t": now_iso,
                    "v": acc["latency"] / acc["cases"] if acc["cases"] else 0,
                }
            ]
            bm["avgTurns"][tier] = []
        result["byModelTokens"] = bm

    return result


def _handle_health(origin: str) -> dict:
    """GET /observability/health — infrastructure health status."""
    health = {"lambdas": [], "queues": {}, "alarms": []}

    # Lambda error rates (last 1 hour)
    lambda_names = [
        "odata-poller",
        "webhook-processor",
        "agent-invoker",
        "exemplar-builder",
        "test-data",
    ]
    for name in lambda_names:
        fn_name = f"{STACK_NAME}-{name}"
        try:
            errors = cw.get_metric_statistics(
                Namespace="AWS/Lambda",
                MetricName="Errors",
                Dimensions=[{"Name": "FunctionName", "Value": fn_name}],
                StartTime=datetime.now(timezone.utc) - timedelta(hours=1),
                EndTime=datetime.now(timezone.utc),
                Period=3600,
                Statistics=["Sum"],
            )
            invocations = cw.get_metric_statistics(
                Namespace="AWS/Lambda",
                MetricName="Invocations",
                Dimensions=[{"Name": "FunctionName", "Value": fn_name}],
                StartTime=datetime.now(timezone.utc) - timedelta(hours=1),
                EndTime=datetime.now(timezone.utc),
                Period=3600,
                Statistics=["Sum"],
            )
            err_count = errors["Datapoints"][0]["Sum"] if errors["Datapoints"] else 0
            inv_count = (
                invocations["Datapoints"][0]["Sum"] if invocations["Datapoints"] else 0
            )
            status = (
                "healthy"
                if err_count == 0
                else ("degraded" if err_count < inv_count * 0.1 else "error")
            )
            health["lambdas"].append(
                {
                    "name": name,
                    "invocations": int(inv_count),
                    "errors": int(err_count),
                    "status": status,
                }
            )
        except Exception:
            health["lambdas"].append(
                {"name": name, "invocations": 0, "errors": 0, "status": "unknown"}
            )

    for label, url in [("main", QUEUE_URL), ("dlq", DLQ_URL)]:
        if not url:
            continue
        try:
            attrs = sqs.get_queue_attributes(
                QueueUrl=url,
                AttributeNames=[
                    "ApproximateNumberOfMessages",
                    "ApproximateNumberOfMessagesNotVisible",
                ],
            )["Attributes"]
            visible = int(attrs.get("ApproximateNumberOfMessages", 0))
            in_flight = int(attrs.get("ApproximateNumberOfMessagesNotVisible", 0))
            health["queues"][label] = {"visible": visible, "inFlight": in_flight}
        except Exception:
            health["queues"][label] = {"visible": 0, "inFlight": 0}

    try:
        alarms = cw_alarms.describe_alarms(AlarmNamePrefix=STACK_NAME, MaxRecords=10)
        for a in alarms.get("MetricAlarms", []):
            health["alarms"].append(
                {
                    "name": a["AlarmName"].replace(f"{STACK_NAME}-", ""),
                    "state": a["StateValue"],
                    "reason": a.get("StateReason", ""),
                }
            )
    except Exception:
        health["alarms_error"] = "Failed to fetch alarms"

    # Recent Lambda errors from CloudWatch Logs (last 1 hour)
    logs_client = boto3.client("logs")
    health["recentErrors"] = []
    error_lambdas = ["agent-invoker", "odata-poller", "webhook-processor"]
    for name in error_lambdas:
        log_group = f"/aws/lambda/{STACK_NAME}-{name}"
        try:
            resp = logs_client.filter_log_events(
                logGroupName=log_group,
                startTime=int(
                    (datetime.now(timezone.utc) - timedelta(hours=1)).timestamp() * 1000
                ),
                filterPattern="ERROR",
                limit=5,
            )
            for evt in resp.get("events", []):
                msg = evt.get("message", "").strip()
                # Extract the useful part — skip REPORT/START/END lines
                if msg.startswith(("[ERROR]", "ERROR")):
                    # Truncate long messages
                    short_msg = msg[:300] + ("…" if len(msg) > 300 else "")
                    health["recentErrors"].append(
                        {
                            "lambda": name,
                            "timestamp": datetime.fromtimestamp(
                                evt["timestamp"] / 1000, tz=timezone.utc
                            ).isoformat(),
                            "message": short_msg,
                        }
                    )
        except Exception:
            pass  # Log group might not exist yet

    return _response(200, health, origin)


def _handle_traces(qs: dict, origin: str) -> dict:
    """GET /observability/traces — recent agent traces with case context."""
    try:
        hours = int(qs.get("hours", "24"))
    except (ValueError, TypeError):
        hours = 24

    if hours <= 0:
        hours = 24

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    if not TABLE_NAME:
        return _response(500, {"error": "TABLE_NAME not configured"}, origin)

    table = dynamodb.Table(TABLE_NAME)

    try:
        scan_kwargs = {
            "FilterExpression": "updated_at >= :cutoff",
            "ExpressionAttributeValues": {":cutoff": cutoff},
            "ProjectionExpression": "document_number, item_id, process_type, agent_traces, updated_at",
        }

        items = []
        while True:
            resp = table.scan(**scan_kwargs)
            items.extend(resp.get("Items", []))
            last_key = resp.get("LastEvaluatedKey")
            if not last_key:
                break
            scan_kwargs["ExclusiveStartKey"] = last_key
    except Exception as e:
        logger.exception("DynamoDB scan failed for traces")
        return _response(500, {"error": f"Failed to query traces: {e}"}, origin)

    total_cases_scanned = len(items)
    traces = []

    for case in items:
        agent_traces = case.get("agent_traces")
        if not agent_traces:
            continue

        doc_num = case.get("document_number", "")
        item_id = case.get("item_id", "")
        process_type = case.get("process_type", "")
        # Label traces with the same identity the rest of the system uses, so the UI
        # can link a trace straight to its case. Records written before the poller
        # stored case_id are derived from their key.
        case_id = case.get("case_id")
        if not case_id:
            try:
                case_id = format_case_id(doc_num, item_id)
            except CaseKeyError:
                logger.warning(
                    "Skipping traces for case with unusable key: %r/%r",
                    doc_num,
                    item_id,
                )
                continue

        for trace in agent_traces:
            try:
                trace_id = trace.get("trace_id")
                timestamp = trace.get("timestamp")
                if not trace_id or not timestamp:
                    logger.warning(
                        "Skipping malformed trace in case %s: missing trace_id or timestamp",
                        case_id,
                    )
                    continue

                segments = trace.get("segments", [])
                traces.append(
                    {
                        "case_id": case_id,
                        "document_number": doc_num,
                        "item_id": item_id,
                        "process_type": process_type,
                        "trace_id": trace_id,
                        "timestamp": timestamp,
                        "trigger": trace.get("trigger", ""),
                        "outcome": trace.get("outcome", ""),
                        "segment_count": len(segments),
                        "segments": segments,
                    }
                )
            except Exception:
                logger.warning(
                    "Skipping malformed trace data in case %s", case_id, exc_info=True
                )
                continue

    traces.sort(key=lambda t: t["timestamp"], reverse=True)
    traces = traces[:50]

    return _response(
        200,
        {"traces": traces, "total_cases_scanned": total_cases_scanned},
        origin,
    )


def handler(event: dict, context: object) -> dict:
    method = event.get("httpMethod", "")
    path = event.get("path", "")
    origin = (event.get("headers") or {}).get("origin", "")
    qs = event.get("queryStringParameters") or {}

    logger.info("Request: %s %s", method, path)

    if method == "OPTIONS":
        return _response(200, {}, origin)

    try:
        if path.endswith("/metrics"):
            return _handle_metrics(qs, origin)
        if path.endswith("/health"):
            return _handle_health(origin)
        if path.endswith("/traces"):
            return _handle_traces(qs, origin)
        return _response(404, {"error": "Not found"}, origin)
    except Exception as e:
        logger.exception("Observability API error")
        return _response(500, {"error": str(e)}, origin)
