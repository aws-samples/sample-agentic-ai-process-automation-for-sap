#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
AP Cost Benchmark Runner

Creates AP exception cases in SAP (via the existing /test-data/ap-cases API),
seeds them into DynamoDB, enqueues them for agent processing, drives fixture-based
human ticket responses, and reports per-case Bedrock cost and lifecycle validity.

Usage:
    python agentcore/evals/ap_cost_benchmark/run_benchmark.py \
        --stack-name my-stack --region us-east-1

Prerequisites:
    - Stack deployed with demo.enabled: true (for /test-data/ap-cases endpoint)
    - SAP credentials configured (make sync-sap-secret)
    - Autonomy: trigger-mode=manual
"""

import argparse
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import boto3
import requests

# Config

POLL_INTERVAL = 15  # seconds between DynamoDB polls
MAX_WAIT = 600  # max seconds to wait for all cases to complete
ESCALATION_WAIT = 30  # seconds to wait for a ticket to become durable
MAX_REVIEW_ROUNDS = 3
CASES_FILE = Path(__file__).parent / "cases.json"

ACTIVE_STATUSES = {"new", "detected", "processing", "analyzing", "investigating"}
PAUSED_STATUS = "awaiting_human_input"
TERMINAL_STATUSES = {"complete", "manual_review_required", "sap_updated"}
INITIAL_STOP_STATUSES = {PAUSED_STATUS, *TERMINAL_STATUSES}


def _ts() -> str:
    """Compact timestamp for log lines."""
    return datetime.now().strftime("%H:%M:%S")


def _elapsed(start: float) -> str:
    """Human-readable elapsed time."""
    s = int(time.time() - start)
    if s < 60:
        return f"{s}s"
    return f"{s // 60}m{s % 60:02d}s"


def _get_ssm(ssm, stack: str, key: str) -> str:
    return ssm.get_parameter(Name=f"/{stack}/{key}")["Parameter"]["Value"]


def _get_config(stack: str, region: str) -> dict:
    ssm = boto3.client("ssm", region_name=region)
    cloudformation = boto3.client("cloudformation", region_name=region)
    ticket_action_function = None
    paginator = cloudformation.get_paginator("list_stack_resources")
    for page in paginator.paginate(StackName=f"{stack}-backend"):
        ticket_action_function = next(
            (
                resource["PhysicalResourceId"]
                for resource in page.get("StackResourceSummaries", [])
                if resource.get("ResourceType") == "AWS::Lambda::Function"
                and resource.get("LogicalResourceId", "").startswith("TicketsLambda")
            ),
            None,
        )
        if ticket_action_function:
            break
    if not ticket_action_function:
        raise RuntimeError(
            f"Could not find TicketsLambda in CloudFormation stack {stack}-backend"
        )

    config = {
        "demo_api_url": _get_ssm(ssm, stack, "demo/api-url").rstrip("/"),
        "api_url": _get_ssm(ssm, stack, "feedback-api-url").rstrip("/"),
        "cases_table": _get_ssm(ssm, stack, "dynamodb/cases-table"),
        "tickets_table": _get_ssm(ssm, stack, "dynamodb/tickets-table"),
        "queue_name": f"{stack}-agent-queue.fifo",
        "ticket_action_function": ticket_action_function,
    }
    print(f"  Cases:     {config['cases_table']}")
    print(f"  Tickets:   {config['tickets_table']}")
    print(f"  Queue:     {config['queue_name']}")
    print(f"  Demo API:  {config['demo_api_url']}")
    print(f"  Actions:   {config['ticket_action_function']}")
    return config


# Phase 1: Create SAP documents + seed DynamoDB


def create_sap_cases(cases: list, demo_api_url: str) -> list:
    """Call /demo/test-data/ap-cases for each case. Returns cases with SAP doc numbers."""
    results = []
    phase_start = time.time()
    for i, case in enumerate(cases):
        print(
            f"  [{i + 1}/{len(cases)}] {case['id']}: {case['scenario_name']}...",
            end=" ",
            flush=True,
        )
        if case.get("po_number"):
            print(f"PO={case['po_number']} (prepopulated; skipped creation)")
            results.append(case)
            continue
        call_start = time.time()
        try:
            resp = requests.post(
                f"{demo_api_url}/demo/test-data/ap-cases",
                json={"scenario_name": case["scenario_name"], **case["sap_params"]},
                timeout=60,
            )
            resp.raise_for_status()
            sap_result = resp.json()
            case["po_number"] = sap_result.get("po_number", "")
            case["invoice_number"] = sap_result.get("invoice_number", "")
            case["gr_document"] = sap_result.get("gr_document")
            elapsed = time.time() - call_start
            print(f"PO={case['po_number']} ({elapsed:.1f}s)")
            results.append(case)
            time.sleep(1)  # pace SAP calls
        except Exception as e:
            elapsed = time.time() - call_start
            print(f"FAILED after {elapsed:.1f}s: {e}")
            case["error"] = str(e)
            results.append(case)
    print(f"  Phase 1 complete in {_elapsed(phase_start)}")
    return results


def seed_dynamodb_cases(cases: list, table_name: str, region: str):
    """Write case records to DynamoDB so the agent can find them."""
    table = boto3.resource("dynamodb", region_name=region).Table(table_name)
    now = datetime.now(timezone.utc).isoformat()
    count = 0
    with table.batch_writer() as batch:
        for case in cases:
            if not case.get("po_number"):
                continue
            batch.put_item(
                Item={
                    "case_id": f"{case['po_number']}-10",
                    "document_number": case["po_number"],
                    "item_id": "10",
                    "domain": "finance_ap",
                    "process_type": case["process_type"],
                    "status": "detected",
                    "created_at": now,
                    "updated_at": now,
                    "benchmark_id": case["id"],
                    "benchmark_complexity": case["complexity"],
                    "po_amount": str(case["sap_params"]["po_amount"]),
                    "invoice_amount": str(case["sap_params"]["invoice_amount"]),
                }
            )
            count += 1
    print(f"  Seeded {count} cases into DynamoDB")


# Phase 2: Enqueue for agent processing


def enqueue_cases(cases: list, queue_name: str, region: str):
    """Send cases to the agent SQS FIFO queue."""
    sqs = boto3.client("sqs", region_name=region)
    queue_url = sqs.get_queue_url(QueueName=queue_name)["QueueUrl"]
    enqueued = 0
    skipped = 0
    for case in cases:
        if not case.get("po_number"):
            skipped += 1
            continue
        case_id = f"{case['po_number']}-10"
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(
                {"case_id": case_id, "trigger": "benchmark", "payload": {}}
            ),
            MessageGroupId=case_id,
        )
        enqueued += 1
    print(
        f"  Enqueued {enqueued} cases"
        + (f" (skipped {skipped} without PO)" if skipped else "")
    )


# Phase 3: Poll for completion


def _invocation_count(item: dict) -> int:
    return int(item.get("cost_summary", {}).get("invocation_count", 0))


def poll_case_states(
    cases: list,
    table_name: str,
    region: str,
    max_wait: int,
    stop_statuses: set[str],
    minimum_invocations: dict[str, int] | None = None,
) -> tuple[dict[str, dict], list[str]]:
    """Wait for explicit states, optionally requiring a new agent invocation."""
    po_numbers = [c["po_number"] for c in cases if c.get("po_number")]
    pending = set(po_numbers)
    results: dict[str, dict] = {}
    errors: list[str] = []
    start = time.time()
    last_status_log = ""

    while pending and (time.time() - start) < max_wait:
        table = boto3.resource("dynamodb", region_name=region).Table(table_name)
        newly_done = []
        for po in list(pending):
            try:
                resp = table.get_item(Key={"case_id": f"{po}-10"}, ConsistentRead=True)
            except Exception as e:
                print(f"  [{_ts()}] DynamoDB error (will retry): {e}")
                break
            item = resp.get("Item", {})
            status = item.get("status", "unknown")
            baseline = (minimum_invocations or {}).get(po)
            invocation_advanced = baseline is None or _invocation_count(item) > baseline
            if status in stop_statuses and invocation_advanced:
                results[po] = item
                pending.discard(po)
                bid = item.get("benchmark_id", po)
                newly_done.append(f"{bid}→{status} (inv={_invocation_count(item)})")

        if newly_done:
            print(f"  [{_ts()}] Reached stop state: {', '.join(newly_done)}")

        if pending:
            statuses = Counter()
            for po in pending:
                try:
                    r = table.get_item(Key={"case_id": f"{po}-10"}, ConsistentRead=True)
                    item = r.get("Item", {})
                    status = item.get("status", "unknown")
                    baseline = (minimum_invocations or {}).get(po)
                    if baseline is not None and _invocation_count(item) <= baseline:
                        status = f"{status}/callback-pending"
                    statuses[status] += 1
                except Exception:
                    statuses["read-error"] += 1
            status_str = ", ".join(f"{s}={n}" for s, n in sorted(statuses.items()))
            log_line = f"{len(pending)} pending ({status_str})"
            if (
                log_line != last_status_log
                or int(time.time() - start) % 60 < POLL_INTERVAL
            ):
                print(f"  [{_ts()}] {log_line} [{_elapsed(start)}]")
                last_status_log = log_line
            time.sleep(POLL_INTERVAL)

    if pending:
        table = boto3.resource("dynamodb", region_name=region).Table(table_name)
        print(f"  [{_ts()}] Timeout reached — {len(pending)} cases unresolved")
        for po in sorted(pending):
            try:
                item = table.get_item(
                    Key={"case_id": f"{po}-10"}, ConsistentRead=True
                ).get("Item", {})
            except Exception as e:
                item = {}
                errors.append(f"{po}: final case read failed: {e}")
            results[po] = item
            status = item.get("status", "unknown")
            baseline = (minimum_invocations or {}).get(po)
            detail = f"status={status}, invocations={_invocation_count(item)}"
            if baseline is not None:
                detail += f", required>{baseline}"
            errors.append(f"{po}: timed out ({detail})")

    return results, errors


# Phase 4: Drive human ticket responses


def _scan_case_tickets(table, case_id: str) -> list[dict]:
    """Return every ticket linked to a case, following DynamoDB pagination."""
    items: list[dict] = []
    kwargs = {
        "FilterExpression": "case_id = :case_id",
        "ExpressionAttributeValues": {":case_id": case_id},
        "ConsistentRead": True,
    }
    while True:
        response = table.scan(**kwargs)
        items.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        kwargs["ExclusiveStartKey"] = last_key
    return items


def _wait_for_actionable_ticket(
    case: dict, case_item: dict, tickets_table: str, region: str
) -> dict | None:
    """Wait for the newest open/assigned ticket linked to this case."""
    table = boto3.resource("dynamodb", region_name=region).Table(tickets_table)
    case_id = f"{case['po_number']}-10"
    deadline = time.time() + ESCALATION_WAIT
    while time.time() < deadline:
        ticket_id = case_item.get("ticket_id")
        if ticket_id:
            item = table.get_item(
                Key={"ticket_id": ticket_id}, ConsistentRead=True
            ).get("Item")
            if item and item.get("status") in {"open", "assigned"}:
                return item

        tickets = _scan_case_tickets(table, case_id)
        actionable = [
            ticket for ticket in tickets if ticket.get("status") in {"open", "assigned"}
        ]
        if actionable:
            return max(
                actionable,
                key=lambda ticket: ticket.get(
                    "created_at", ticket.get("updated_at", "")
                ),
            )
        time.sleep(5)
    return None


def _default_response_text(case: dict) -> str:
    params = case["sap_params"]
    po = case["po_number"]
    process_type = case["process_type"]
    if process_type == "missing_goods_receipt":
        quantity = params.get("invoice_quantity", params.get("po_quantity"))
        return (
            f"Warehouse confirms {quantity} units were received against PO {po} "
            "and authorizes the receipt correction required by the SOP."
        )
    if process_type == "missing_purchase_order":
        return (
            f"Procurement confirms PO {po}, item 10 is the correct open purchase "
            "order for this invoice. Continue using that reference."
        )
    if process_type == "uom_mismatch":
        return (
            "Procurement confirms the invoice and PO quantities use equivalent units "
            "with conversion factor 1.0. Continue with the confirmed quantities."
        )
    return (
        "The reviewer confirms the documented quantities and amounts are correct. "
        "Continue according to the applicable SOP."
    )


def _response_for_ticket(
    case: dict, ticket: dict, observed_actions: list[str]
) -> tuple[str, str | None]:
    plan = case.get("human_response", {})
    response_type = ticket.get("response_type", "approval")
    configured_action = plan.get("action")
    if configured_action in observed_actions:
        configured_action = None
    if response_type == "free_text":
        action = configured_action or "replied"
        if action != "replied":
            raise ValueError(
                f"fixture action {action} is incompatible with free_text ticket"
            )
        return action, plan.get("response_text") or _default_response_text(case)

    action = configured_action or "approved"
    if action not in {"approved", "denied"}:
        raise ValueError(
            f"fixture action {action} is incompatible with approval ticket"
        )
    return action, None


def _submit_ticket_action(
    case: dict,
    ticket: dict,
    action: str,
    response_text: str | None,
    ticket_action_function: str,
    tickets_table: str,
    region: str,
) -> dict:
    """Invoke the consolidated ticket action route and verify persistence."""
    ticket_id = ticket["ticket_id"]
    body = {
        "action": action,
        "comment": f"Benchmark reviewer submitted {action}",
        "resolution": f"Benchmark {action} response",
    }
    if response_text:
        body["response_text"] = response_text
        body["resolution"] = response_text

    event = {
        "httpMethod": "POST",
        "path": f"/tickets/{ticket_id}/action",
        "pathParameters": {"id": ticket_id},
        "body": json.dumps(body),
        "headers": {},
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": "benchmark-reviewer",
                    "preferred_username": "benchmark-reviewer",
                }
            }
        },
    }
    response = boto3.client("lambda", region_name=region).invoke(
        FunctionName=ticket_action_function,
        Payload=json.dumps(event),
    )
    payload = json.loads(response["Payload"].read())
    if response.get("FunctionError"):
        raise RuntimeError(f"Lambda {response['FunctionError']}: {payload}")
    status_code = payload.get("statusCode", 0)
    response_body = json.loads(payload.get("body", "{}"))
    if status_code != 200:
        raise RuntimeError(response_body.get("error", f"HTTP {status_code}"))
    if not response_body.get("enqueued"):
        raise RuntimeError("ticket action succeeded without enqueueing the case")
    expected_case_id = f"{case['po_number']}-10"
    if response_body.get("case_id") != expected_case_id:
        raise RuntimeError(
            f"callback case mismatch: {response_body.get('case_id')} != {expected_case_id}"
        )

    persisted = (
        boto3.resource("dynamodb", region_name=region)
        .Table(tickets_table)
        .get_item(Key={"ticket_id": ticket_id}, ConsistentRead=True)
        .get("Item", {})
    )
    if persisted.get("status") != action:
        raise RuntimeError(
            f"ticket status {persisted.get('status')} does not match {action}"
        )
    return persisted


def drive_ticket_lifecycle(
    cases: list,
    case_results: dict[str, dict],
    cases_table: str,
    tickets_table: str,
    ticket_action_function: str,
    region: str,
    max_wait: int,
) -> tuple[dict[str, dict], dict[str, dict], list[str]]:
    """Respond to tickets until every case reaches a supervised terminal state."""
    lifecycle = {
        case["id"]: {"actions": [], "errors": [], "valid": False}
        for case in cases
        if case.get("po_number")
    }
    errors: list[str] = []
    blocked: set[str] = set()

    for review_round in range(1, MAX_REVIEW_ROUNDS + 1):
        awaiting = [
            case
            for case in cases
            if case.get("po_number")
            and case_results.get(case["po_number"], {}).get("status") == PAUSED_STATUS
            and case["id"] not in blocked
        ]
        if not awaiting:
            break
        print(
            f"  [{_ts()}] Review round {review_round}: "
            f"{len(awaiting)} awaiting_human_input"
        )
        actioned: list[dict] = []
        baselines: dict[str, int] = {}

        for case in awaiting:
            po = case["po_number"]
            item = case_results[po]
            record = lifecycle[case["id"]]
            ticket = _wait_for_actionable_ticket(case, item, tickets_table, region)
            if not ticket:
                refreshed = (
                    boto3.resource("dynamodb", region_name=region)
                    .Table(cases_table)
                    .get_item(Key={"case_id": f"{po}-10"}, ConsistentRead=True)
                    .get("Item", {})
                )
                if refreshed.get("status") in TERMINAL_STATUSES:
                    case_results[po] = refreshed
                    print(
                        f"  [{_ts()}] ✓ {case['id']}: reached "
                        f"{refreshed['status']} while waiting for the next ticket"
                    )
                    continue
                message = f"{case['id']}: no actionable ticket became durable"
                print(f"  [{_ts()}] ✗ {message}")
                record["errors"].append(message)
                errors.append(message)
                blocked.add(case["id"])
                continue

            try:
                observed_actions = [entry["action"] for entry in record["actions"]]
                action, response_text = _response_for_ticket(
                    case, ticket, observed_actions
                )
                baselines[po] = _invocation_count(item)
                persisted = _submit_ticket_action(
                    case,
                    ticket,
                    action,
                    response_text,
                    ticket_action_function,
                    tickets_table,
                    region,
                )
                record["actions"].append(
                    {
                        "round": review_round,
                        "ticket_id": ticket["ticket_id"],
                        "response_type": ticket.get("response_type", "approval"),
                        "action": action,
                        "ticket_status": persisted.get("status"),
                    }
                )
                actioned.append(case)
                print(
                    f"  [{_ts()}] ✓ {case['id']}: {action} "
                    f"{ticket['ticket_id']} ({ticket.get('response_type', 'approval')})"
                )
            except Exception as e:
                message = f"{case['id']}: ticket action failed: {e}"
                print(f"  [{_ts()}] ✗ {message}")
                record["errors"].append(message)
                errors.append(message)
                blocked.add(case["id"])

        if not actioned:
            break
        updated, poll_errors = poll_case_states(
            actioned,
            cases_table,
            region,
            max_wait,
            INITIAL_STOP_STATUSES,
            baselines,
        )
        case_results.update(updated)
        errors.extend(poll_errors)
        for message in poll_errors:
            po = message.split(":", 1)[0]
            case = next(
                (candidate for candidate in actioned if candidate["po_number"] == po),
                None,
            )
            if case:
                lifecycle[case["id"]]["errors"].append(message)
                blocked.add(case["id"])

    return case_results, lifecycle, errors


def validate_final_lifecycle(
    cases: list,
    case_results: dict[str, dict],
    lifecycle: dict[str, dict],
) -> list[str]:
    """Validate ticket actions against the final consistent case state."""
    errors: list[str] = []

    def add_error(record: dict, message: str) -> None:
        if message not in record["errors"]:
            record["errors"].append(message)
        errors.append(message)

    for case in cases:
        po = case.get("po_number")
        if not po:
            continue

        record = lifecycle[case["id"]]
        status = case_results.get(po, {}).get("status", "unknown")
        record["final_status"] = status
        observed_actions = [entry["action"] for entry in record["actions"]]
        expected_action = case.get("human_response", {}).get("action")

        if expected_action and expected_action not in observed_actions:
            add_error(
                record,
                f"{case['id']}: expected ticket action {expected_action}, "
                f"observed {observed_actions or 'none'}",
            )

        explicit_statuses = case.get("expected_final_statuses")
        if explicit_statuses:
            expected_statuses = set(explicit_statuses)
        elif observed_actions and observed_actions[-1] == "denied":
            expected_statuses = {"manual_review_required"}
        else:
            expected_statuses = TERMINAL_STATUSES

        record["expected_final_statuses"] = sorted(expected_statuses)
        if status not in expected_statuses:
            add_error(
                record,
                f"{case['id']}: final status {status} does not match "
                f"expected {sorted(expected_statuses)} after actions "
                f"{observed_actions or 'none'}",
            )
        record["valid"] = not record["errors"]

    return errors


# Phase 5: Report


def generate_report(
    cases: list,
    case_results: dict[str, dict],
    lifecycle: dict[str, dict],
    validation_errors: list[str],
) -> dict:
    """Generate cost and lifecycle report from case results."""
    rows = []
    for case in cases:
        po = case.get("po_number")
        if not po:
            continue
        item = case_results.get(po, {})
        cs = item.get("cost_summary", {})
        lifecycle_record = lifecycle.get(case["id"], {})
        rows.append(
            {
                "id": case["id"],
                "complexity": case["complexity"],
                "process_type": case["process_type"],
                "scenario": case["scenario_name"],
                "status": item.get("status", "unknown"),
                "cost_usd": float(cs.get("total_cost_usd", 0)),
                "input_tokens": int(cs.get("total_input_tokens", 0)),
                "output_tokens": int(cs.get("total_output_tokens", 0)),
                "cache_read_tokens": int(cs.get("total_cache_read_tokens", 0)),
                "invocations": int(cs.get("invocation_count", 0)),
                "ticket_actions": lifecycle_record.get("actions", []),
                "lifecycle_valid": lifecycle_record.get("valid", False),
                "lifecycle_errors": lifecycle_record.get("errors", []),
            }
        )

    costs = [r["cost_usd"] for r in rows if r["cost_usd"] > 0]
    with_cost = [r for r in rows if r["cost_usd"] > 0]
    without_cost = [r for r in rows if r["cost_usd"] == 0]

    # Status distribution
    status_counts = Counter(r["status"] for r in rows)

    print("\n" + "=" * 70)
    print("AP COST BENCHMARK RESULTS")
    print("=" * 70)

    # Status overview
    print("\n  Status distribution:")
    for s, n in sorted(status_counts.items(), key=lambda x: -x[1]):
        print(f"    {s:30s} {n:3d}")

    action_counts = Counter(
        action["action"] for row in rows for action in row.get("ticket_actions", [])
    )
    valid_count = sum(1 for row in rows if row["lifecycle_valid"])
    print(f"\n  Lifecycle-valid cases: {valid_count}/{len(rows)}")
    print(f"  Ticket actions: {dict(action_counts)}")
    if validation_errors:
        print(f"  Validation errors ({len(validation_errors)}):")
        for error in validation_errors:
            print(f"    - {error}")

    if costs:
        total_tokens = sum(
            r["input_tokens"] + r["output_tokens"] + r["cache_read_tokens"]
            for r in with_cost
        )
        total_invocations = sum(r["invocations"] for r in with_cost)
        print(f"\n  Cases with cost data: {len(with_cost)}/{len(rows)}")
        print(f"  Total invocations:   {total_invocations}")
        print(f"  Total tokens:        {total_tokens:,}")
        print(f"  Total Bedrock cost:  ${sum(costs):.2f}")
        print(f"  Avg cost/case:       ${statistics.mean(costs):.4f}")
        print(f"  Median cost/case:    ${statistics.median(costs):.4f}")
        if len(costs) > 1:
            print(f"  Std dev:             ${statistics.stdev(costs):.4f}")
        sorted_costs = sorted(costs)
        p90_idx = int(len(sorted_costs) * 0.9)
        print(
            f"  p90 cost/case:       ${sorted_costs[min(p90_idx, len(sorted_costs) - 1)]:.4f}"
        )
        print(f"  Min / Max:           ${min(costs):.4f} / ${max(costs):.4f}")
    else:
        print("  No cost data collected")

    if without_cost:
        print(f"\n  Cases without cost data ({len(without_cost)}):")
        for r in without_cost:
            print(f"    {r['id']:10s} status={r['status']}")

    # By complexity
    print("\n  By complexity:")
    for tier in ("simple", "medium", "escalation"):
        tier_rows = [r for r in rows if r["complexity"] == tier]
        tier_costs = [r["cost_usd"] for r in tier_rows if r["cost_usd"] > 0]
        total = len(tier_rows)
        if tier_costs:
            print(
                f"    {tier:12s}  ${statistics.mean(tier_costs):.4f} avg  "
                f"({len(tier_costs)}/{total} with cost, "
                f"avg {statistics.mean([r['invocations'] for r in tier_rows if r['cost_usd'] > 0]):.1f} invocations)"
            )
        else:
            print(f"    {tier:12s}  no data  ({total} cases)")

    # By process type
    print("\n  By process type:")
    by_type = defaultdict(lambda: {"costs": [], "total": 0})
    for r in rows:
        by_type[r["process_type"]]["total"] += 1
        if r["cost_usd"] > 0:
            by_type[r["process_type"]]["costs"].append(r["cost_usd"])
    for pt, d in sorted(by_type.items()):
        if d["costs"]:
            print(
                f"    {pt:25s}  ${statistics.mean(d['costs']):.4f} avg  "
                f"({len(d['costs'])}/{d['total']} with cost)"
            )

    # Per-case detail
    print(
        f"\n{'ID':10s} {'Cplx':12s} {'Type':25s} {'Cost':>8s} {'Inv':>4s} "
        f"{'InTok':>7s} {'OutTok':>7s} {'Cache':>8s} {'Status'}"
    )
    print("-" * 105)
    for r in rows:
        print(
            f"{r['id']:10s} {r['complexity']:12s} {r['process_type']:25s} "
            f"${r['cost_usd']:>7.4f} {r['invocations']:>4d} "
            f"{r['input_tokens']:>7,d} {r['output_tokens']:>7,d} "
            f"{r['cache_read_tokens']:>8,d} {r['status']}"
        )

    # Save JSON report
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_cases": len(rows),
            "cases_with_cost": len(with_cost),
            "total_cost_usd": round(sum(costs), 4) if costs else 0,
            "avg_cost_usd": round(statistics.mean(costs), 4) if costs else 0,
            "median_cost_usd": round(statistics.median(costs), 4) if costs else 0,
            "status_distribution": dict(status_counts),
            "lifecycle_valid_cases": valid_count,
            "ticket_action_distribution": dict(action_counts),
            "valid": not validation_errors and valid_count == len(rows),
        },
        "validation_errors": validation_errors,
        "cases": rows,
    }
    report_path = Path(__file__).parent / "report.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(f"\n  Full report saved to {report_path}")
    return report


# Main


def main():
    parser = argparse.ArgumentParser(description="AP Cost Benchmark")
    parser.add_argument("--stack-name", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--cases-file", default=str(CASES_FILE))
    parser.add_argument(
        "--skip-sap", action="store_true", help="Skip SAP creation (reuse existing POs)"
    )
    parser.add_argument("--max-wait", type=int, default=MAX_WAIT)
    parser.add_argument(
        "--limit", type=int, default=0, help="Run only the first N cases (0 = all)"
    )
    args = parser.parse_args()

    run_start = time.time()
    print(f"[{_ts()}] AP Cost Benchmark starting")
    print(
        f"  Stack: {args.stack_name}, Region: {args.region}, Max wait: {args.max_wait}s"
    )

    print(f"\n[{_ts()}] Loading cases from {args.cases_file}")
    cases = json.loads(Path(args.cases_file).read_text())
    if args.limit > 0:
        cases = cases[: args.limit]
    complexity_counts = Counter(c["complexity"] for c in cases)
    type_counts = Counter(c["process_type"] for c in cases)
    print(f"  {len(cases)} cases: {dict(complexity_counts)}")
    print(f"  Types: {dict(type_counts)}")

    print(f"\n[{_ts()}] Loading stack config...")
    config = _get_config(args.stack_name, args.region)

    if not args.skip_sap:
        print(f"\n[{_ts()}] Phase 1: Creating SAP documents...")
        phase_start = time.time()
        cases = create_sap_cases(cases, config["demo_api_url"])
        created = sum(1 for c in cases if c.get("po_number"))
        failed = len(cases) - created
        print(f"  Created {created}, failed {failed} in {_elapsed(phase_start)}")
        if created == 0:
            print("ERROR: No SAP documents created. Check SAP connectivity.")
            sys.exit(1)

        print(f"\n[{_ts()}] Seeding DynamoDB...")
        seed_dynamodb_cases(cases, config["cases_table"], args.region)
    else:
        print(f"\n[{_ts()}] Phase 1: Skipping SAP creation (--skip-sap)")
        table = boto3.resource("dynamodb", region_name=args.region).Table(
            config["cases_table"]
        )
        resp = table.scan(
            FilterExpression="attribute_exists(benchmark_id)",
            ProjectionExpression="document_number, benchmark_id",
        )
        po_by_id = {
            it["benchmark_id"]: it["document_number"] for it in resp.get("Items", [])
        }
        latest = {}
        for bid, po in po_by_id.items():
            if bid not in latest or po > latest[bid]:
                latest[bid] = po
        matched = 0
        for case in cases:
            po = latest.get(case["id"])
            if po:
                case["po_number"] = po
                matched += 1
        print(f"  Loaded {matched}/{len(cases)} PO numbers from DynamoDB")

    print(f"\n[{_ts()}] Phase 2: Enqueuing cases for agent processing...")
    enqueue_cases(cases, config["queue_name"], args.region)

    print(
        f"\n[{_ts()}] Phase 3: Waiting for a terminal or review state "
        f"(max {args.max_wait}s)..."
    )
    phase_start = time.time()
    case_results, initial_errors = poll_case_states(
        cases,
        config["cases_table"],
        args.region,
        args.max_wait,
        INITIAL_STOP_STATUSES,
    )
    reached = sum(
        1
        for value in case_results.values()
        if value.get("status") in INITIAL_STOP_STATUSES
    )
    print(
        f"  [{_ts()}] Phase 3 complete: {reached}/{len(case_results)} reached "
        f"a terminal or review state in {_elapsed(phase_start)}"
    )

    print(f"\n[{_ts()}] Phase 4: Driving human ticket responses...")
    phase_start = time.time()
    case_results, lifecycle, lifecycle_errors = drive_ticket_lifecycle(
        cases,
        case_results,
        config["cases_table"],
        config["tickets_table"],
        config["ticket_action_function"],
        args.region,
        max(60, args.max_wait // 2),
    )
    print(f"  [{_ts()}] Phase 4 complete in {_elapsed(phase_start)}")

    validation_errors = [
        *initial_errors,
        *lifecycle_errors,
        *[
            f"{case['id']}: SAP fixture was not created"
            for case in cases
            if not case.get("po_number")
        ],
    ]

    print(
        f"\n[{_ts()}] Phase 5: Final data collection "
        "(15s delay for trace persistence)..."
    )
    time.sleep(15)
    table = boto3.resource("dynamodb", region_name=args.region).Table(
        config["cases_table"]
    )
    active_cases = []
    for case in cases:
        po = case.get("po_number")
        if not po:
            continue
        item = table.get_item(Key={"case_id": f"{po}-10"}, ConsistentRead=True).get(
            "Item"
        )
        if item:
            case_results[po] = item
            if item.get("status") in ACTIVE_STATUSES:
                active_cases.append(case)

    if active_cases:
        print(
            f"  [{_ts()}] Waiting for {len(active_cases)} active final "
            "invocation(s) to stabilize..."
        )
        stabilized, stabilization_errors = poll_case_states(
            active_cases,
            config["cases_table"],
            args.region,
            max(60, min(300, args.max_wait)),
            TERMINAL_STATUSES,
        )
        case_results.update(stabilized)
        validation_errors.extend(stabilization_errors)

    final_lifecycle_errors = validate_final_lifecycle(cases, case_results, lifecycle)
    validation_errors.extend(final_lifecycle_errors)
    validation_errors = list(dict.fromkeys(validation_errors))
    print(f"\n[{_ts()}] Phase 6: Generating report...")
    report = generate_report(cases, case_results, lifecycle, validation_errors)
    print(f"\n[{_ts()}] Benchmark finished — total runtime {_elapsed(run_start)}")
    if not report["summary"]["valid"]:
        print("ERROR: Benchmark lifecycle validation failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
