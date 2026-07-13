#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
AP Cost Benchmark Runner

Creates AP exception cases in SAP (via the existing /test-data/ap-cases API),
seeds them into DynamoDB, enqueues them for agent processing, simulates ticket
approvals, and reports per-case Bedrock cost.

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
ESCALATION_WAIT = 30  # seconds to wait before simulating ticket approvals
CASES_FILE = Path(__file__).parent / "cases.json"

# Statuses that mean the agent is still working
PENDING_STATUSES = {"new", "processing", "analyzing"}


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
    config = {
        "demo_api_url": _get_ssm(ssm, stack, "demo/api-url").rstrip("/"),
        "api_url": _get_ssm(ssm, stack, "feedback-api-url").rstrip("/"),
        "cases_table": _get_ssm(ssm, stack, "dynamodb/cases-table"),
        "queue_name": f"{stack}-agent-queue.fifo",
    }
    print(f"  Table:     {config['cases_table']}")
    print(f"  Queue:     {config['queue_name']}")
    print(f"  Demo API:  {config['demo_api_url']}")
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
                    "document_number": case["po_number"],
                    "item_id": "10",
                    "domain": "finance_ap",
                    "process_type": case["process_type"],
                    "status": "new",
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
        case_id = f"{case['po_number']}#10"
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


def poll_completion(
    cases: list, table_name: str, region: str, max_wait: int = MAX_WAIT
) -> dict[str, dict]:
    """Poll DynamoDB until all cases leave pending statuses."""
    po_numbers = [c["po_number"] for c in cases if c.get("po_number")]
    pending = set(po_numbers)
    results = {}
    start = time.time()
    last_status_log = ""

    while pending and (time.time() - start) < max_wait:
        # Refresh client each iteration to avoid expired token on long runs
        table = boto3.resource("dynamodb", region_name=region).Table(table_name)
        newly_done = []
        for po in list(pending):
            try:
                resp = table.get_item(Key={"document_number": po, "item_id": "10"})
            except Exception as e:
                print(f"  [{_ts()}] DynamoDB error (will retry): {e}")
                break
            item = resp.get("Item", {})
            status = item.get("status", "unknown")
            if status not in PENDING_STATUSES:
                results[po] = item
                pending.discard(po)
                bid = item.get("benchmark_id", po)
                newly_done.append(f"{bid}→{status}")

        if newly_done:
            print(f"  [{_ts()}] Completed: {', '.join(newly_done)}")

        if pending:
            # Show status breakdown of remaining cases
            statuses = Counter()
            for po in pending:
                try:
                    r = table.get_item(
                        Key={"document_number": po, "item_id": "10"},
                        ProjectionExpression="#s",
                        ExpressionAttributeNames={"#s": "status"},
                    )
                    statuses[r.get("Item", {}).get("status", "unknown")] += 1
                except Exception:
                    statuses["error"] += 1
            status_str = ", ".join(f"{s}={n}" for s, n in sorted(statuses.items()))
            elapsed = _elapsed(start)
            # Only print if status changed or every 60s
            log_line = f"{len(pending)} pending ({status_str})"
            if (
                log_line != last_status_log
                or int(time.time() - start) % 60 < POLL_INTERVAL
            ):
                print(f"  [{_ts()}] {log_line} [{elapsed}]")
                last_status_log = log_line
            time.sleep(POLL_INTERVAL)

    # Grab any remaining
    if pending:
        print(f"  [{_ts()}] Timeout reached — {len(pending)} cases still pending")
        table = boto3.resource("dynamodb", region_name=region).Table(table_name)
        for po in pending:
            try:
                resp = table.get_item(Key={"document_number": po, "item_id": "10"})
                results[po] = resp.get("Item", {})
            except Exception:
                results[po] = {}

    return results


# Phase 4: Simulate ticket approvals


def simulate_ticket_approvals(
    cases: list, case_results: dict[str, dict], api_url: str, region: str = "us-east-1"
) -> list[str]:
    """Find tickets created by cases in awaiting_human_input and approve them."""
    awaiting = [
        c
        for c in cases
        if c.get("po_number")
        and case_results.get(c["po_number"], {}).get("status") == "awaiting_human_input"
    ]
    if not awaiting:
        print("  No cases in awaiting_human_input")
        return []

    with_ticket = sum(
        1 for c in awaiting if case_results.get(c["po_number"], {}).get("ticket_id")
    )
    print(f"  {len(awaiting)} cases awaiting approval, {with_ticket} have ticket_id")

    # Invoke the ticket action processor Lambda directly (bypasses Cognito auth)
    lambda_client = boto3.client("lambda", region_name=region)
    approved = []
    no_ticket = []
    failed = []
    for case in awaiting:
        item = case_results.get(case["po_number"], {})
        ticket_id = _find_ticket_id(item)
        if not ticket_id:
            no_ticket.append(case["id"])
            continue
        try:
            event = {
                "pathParameters": {"id": ticket_id},
                "body": json.dumps(
                    {"action": "approved", "comment": "Benchmark auto-approval"}
                ),
                "headers": {},
            }
            resp = lambda_client.invoke(
                FunctionName="erp-accrual-agent-ticket-action-processor",
                Payload=json.dumps(event),
            )
            payload = json.loads(resp["Payload"].read())
            status_code = payload.get("statusCode", 0)
            if status_code == 200:
                print(f"  [{_ts()}] {case['id']}: ✓ Approved {ticket_id}")
                approved.append(case["po_number"])
            else:
                body = json.loads(payload.get("body", "{}"))
                err = body.get("error", f"HTTP {status_code}")
                print(f"  [{_ts()}] {case['id']}: ✗ {ticket_id} — {err}")
                failed.append(case["id"])
        except Exception as e:
            print(f"  [{_ts()}] {case['id']}: ✗ Error — {e}")
            failed.append(case["id"])

    print(
        f"\n  Approval summary: {len(approved)} approved, {len(no_ticket)} no ticket, {len(failed)} failed"
    )
    if no_ticket:
        print(f"  No ticket: {', '.join(no_ticket)}")
    return approved


def _find_ticket_id(case_item: dict) -> str | None:
    """Extract ticket_id from case item."""
    tid = case_item.get("ticket_id")
    if tid:
        return tid
    for trace in reversed(case_item.get("agent_traces", [])):
        for seg in trace.get("segments", []):
            if seg.get("type") == "tool" and "ticket" in seg.get("tool_name", ""):
                result = seg.get("tool_result", "")
                if isinstance(result, str) and "ticket_id" in result:
                    try:
                        data = json.loads(result)
                        return data.get("ticket_id")
                    except (json.JSONDecodeError, TypeError):
                        pass
    return None


# Phase 5: Report


def generate_report(cases: list, case_results: dict[str, dict]) -> dict:
    """Generate cost report from case results."""
    rows = []
    for case in cases:
        po = case.get("po_number")
        if not po:
            continue
        item = case_results.get(po, {})
        cs = item.get("cost_summary", {})
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
        },
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
        f"\n[{_ts()}] Phase 3: Waiting for agent processing (max {args.max_wait}s)..."
    )
    phase_start = time.time()
    case_results = poll_completion(
        cases, config["cases_table"], args.region, args.max_wait
    )
    completed = sum(
        1 for v in case_results.values() if v.get("status") not in PENDING_STATUSES
    )
    print(
        f"  [{_ts()}] Phase 3 complete: {completed}/{len(case_results)} done "
        f"in {_elapsed(phase_start)}"
    )

    # Phase 4: Simulate ticket approvals for all awaiting_human_input cases
    awaiting_count = sum(
        1
        for c in cases
        if c.get("po_number")
        and case_results.get(c["po_number"], {}).get("status") == "awaiting_human_input"
    )
    if awaiting_count > 0:
        print(
            f"\n[{_ts()}] Phase 4: Simulating ticket approvals ({awaiting_count} cases)..."
        )
        print(f"  Waiting {ESCALATION_WAIT}s for tickets to be created...")
        time.sleep(ESCALATION_WAIT)
        phase_start = time.time()
        approved = simulate_ticket_approvals(
            cases, case_results, config["api_url"], args.region
        )
        if approved:
            print(
                f"\n  [{_ts()}] Waiting for {len(approved)} re-processed cases "
                f"(max {args.max_wait // 2}s)..."
            )
            approved_cases = [c for c in cases if c.get("po_number") in approved]
            updated = poll_completion(
                approved_cases, config["cases_table"], args.region, args.max_wait // 2
            )
            case_results.update(updated)
            re_completed = sum(
                1 for v in updated.values() if v.get("status") not in PENDING_STATUSES
            )
            print(
                f"  [{_ts()}] Phase 4 complete: {re_completed}/{len(approved)} "
                f"re-processed in {_elapsed(phase_start)}"
            )
        else:
            print(f"  [{_ts()}] No tickets approved — skipping re-processing wait")
    else:
        print(f"\n[{_ts()}] Phase 4: No cases awaiting approval, skipping")

    # Phase 5: Re-read final state (cost_summary is written after status change)
    print(
        f"\n[{_ts()}] Phase 5: Final data collection (15s delay for trace persistence)..."
    )
    time.sleep(15)
    table = boto3.resource("dynamodb", region_name=args.region).Table(
        config["cases_table"]
    )
    for case in cases:
        po = case.get("po_number")
        if not po:
            continue
        resp = table.get_item(Key={"document_number": po, "item_id": "10"})
        if resp.get("Item"):
            case_results[po] = resp["Item"]

    print(f"\n[{_ts()}] Phase 6: Generating report...")
    generate_report(cases, case_results)
    print(f"\n[{_ts()}] Benchmark complete — total runtime {_elapsed(run_start)}")


if __name__ == "__main__":
    main()
