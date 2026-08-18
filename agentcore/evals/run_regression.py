# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Regression Eval Runner — runs agent against ground truth test cases and evaluates.

Usage:
    # Cases already exist in SAP + DynamoDB:
    python agentcore/evals/run_regression.py --stack-name my-stack --region us-east-1

    # Create the cases first (requires demo.enabled), then run:
    python agentcore/evals/run_regression.py --stack-name my-stack --region us-east-1 --seed

Workflow:
  1. Loads ground_truth.json test cases
  2. (--seed) Creates each case's SAP documents via the demo /test-data/ap-cases API,
     writes the matching DynamoDB case record, and rewrites the test payload to the
     real SAP keys
  3. Invokes agent for each test case via AgentCore runtime
  4. Asserts each case's `expected` block against the persisted case record
     (deterministic — see check_expectations)
  5. Runs on-demand LLM evaluations against each session
  6. Prints pass/fail summary

A case passes only if BOTH the deterministic assertions and the judge threshold
pass. The judges score how well the agent explained itself; only the assertions
can tell whether it did the right thing. A run that auto-posts an above-tolerance
invoice scores well on fluency, so judges alone cannot gate a release.

Run this BEFORE deploying model changes or SOP updates.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3


def get_config(stack_name: str, region: str) -> dict:
    ssm = boto3.client("ssm", region_name=region)
    params = {}
    for key in ["runtime-arn"]:
        params[key] = ssm.get_parameter(Name=f"/{stack_name}/{key}")["Parameter"][
            "Value"
        ]
    return params


def seed_cases(test_cases: list, stack_name: str, region: str) -> list:
    """Create each test case's SAP documents + DynamoDB record, then rewrite the
    test payload to the real SAP keys.

    Requires the stack deployed with demo.enabled (for the /demo/test-data/ap-cases
    endpoint). Cases without a `seed.sap_params` block are left untouched (assumed to
    already exist). Returns the list of cases that are ready to invoke.
    """
    import requests

    ssm = boto3.client("ssm", region_name=region)
    demo_api_url = ssm.get_parameter(Name=f"/{stack_name}/demo/api-url")["Parameter"][
        "Value"
    ].rstrip("/")
    table_name = ssm.get_parameter(Name=f"/{stack_name}/dynamodb/cases-table")[
        "Parameter"
    ]["Value"]
    table = boto3.resource("dynamodb", region_name=region).Table(table_name)
    now = datetime.now(timezone.utc).isoformat()

    ready = []
    for tc in test_cases:
        seed = tc.get("seed")
        if not seed or "sap_params" not in seed:
            # No seed spec — assume the case already exists in SAP + DynamoDB.
            ready.append(tc)
            continue

        print(
            f"  Seeding {tc['test_id']} ({tc['process_type']})...", end=" ", flush=True
        )
        try:
            resp = requests.post(
                f"{demo_api_url}/demo/test-data/ap-cases",
                json={"scenario_name": tc["test_id"], **seed["sap_params"]},
                timeout=90,
            )
            resp.raise_for_status()
            sap = resp.json()
        except Exception as e:  # noqa: BLE001 — surface and skip, don't abort the suite
            print(f"FAILED: {e}")
            continue

        invoice_number = sap.get("invoice_number")
        if not invoice_number or invoice_number == "CREATED":
            print(f"no invoice number returned (po={sap.get('po_number')}); skipping")
            continue

        # AP case identity: {supplier invoice number}-{fiscal year}.
        fiscal_year = str(datetime.now(timezone.utc).year)
        table.put_item(
            Item={
                "case_id": f"{invoice_number}-{fiscal_year}",
                "document_number": invoice_number,
                "item_id": fiscal_year,
                "domain": "finance_ap",
                "process_type": tc["process_type"],
                "status": "detected",
                "created_at": now,
                "updated_at": now,
                "supplier_number": "USSU-VSF04",
                "amount": str(seed["sap_params"]["invoice_amount"]),
                "currency": "USD",
                "exception_type": seed["sap_params"].get("payment_block", "R"),
                "purchase_order": sap.get("po_number", ""),
                "ttl": int(
                    (datetime.now(timezone.utc) + timedelta(days=7)).timestamp()
                ),
            }
        )

        # Rewrite the invoke payload to point at the real SAP keys.
        tc["payload"]["case_id"] = f"{invoice_number}-{fiscal_year}"
        tc["payload"]["document_number"] = invoice_number
        tc["payload"]["item_id"] = fiscal_year
        print(f"invoice={invoice_number} po={sap.get('po_number')}")
        ready.append(tc)
        time.sleep(1)  # pace SAP calls

    return ready


def invoke_agent(runtime_arn: str, payload: dict, region: str) -> str:
    """Invoke agent and return session_id."""
    client = boto3.client("bedrock-agentcore", region_name=region)
    session_id = f"eval-{int(time.time())}-{payload['document_number']}"
    payload["runtimeSessionId"] = session_id

    resp = client.invoke_agent_runtime(
        agentRuntimeArn=runtime_arn,
        payload=json.dumps(payload).encode(),
    )

    body = b""
    for event in resp.get("body", []):
        if "chunk" in event:
            body += event["chunk"]["bytes"]

    return session_id


# Maps an `expected.outcome` in ground_truth.json to the CaseStatus values that
# satisfy it. Kept here rather than in the schema because "auto_release" is an
# eval-level assertion about agent behaviour, not a case state.
OUTCOME_TO_STATUS = {
    "auto_release": {"sap_updated", "complete"},
    "approval_required": {"awaiting_human_input", "manual_review_required"},
    "manual_review_required": {"manual_review_required", "awaiting_human_input"},
}


def get_case_record(case_id: str, stack_name: str, region: str) -> dict:
    """Read back the persisted case, which is where the agent's real effect landed."""
    from utils.case_key import to_case_key

    ssm = boto3.client("ssm", region_name=region)
    table_name = ssm.get_parameter(Name=f"/{stack_name}/dynamodb/cases-table")[
        "Parameter"
    ]["Value"]
    table = boto3.resource("dynamodb", region_name=region).Table(table_name)
    return table.get_item(Key=to_case_key(case_id)).get("Item") or {}


def check_expectations(expected: dict, case: dict) -> list[str]:
    """Assert an `expected` block against a persisted case. Returns failure strings.

    Deterministic counterpart to the LLM judges: it reads what the agent actually
    did (tool calls in `agent_traces`, final `status`) rather than how well it
    narrated it.
    """
    failures = []

    called = {
        seg.get("tool_name")
        for trace in case.get("agent_traces") or []
        for seg in trace.get("segments") or []
        if seg.get("type") == "tool" and seg.get("tool_name")
    }

    missing = [t for t in expected.get("required_tool_calls", []) if t not in called]
    if missing:
        failures.append(
            f"missing required tool calls {missing} (called: {sorted(called) or 'none'})"
        )

    outcome = expected.get("outcome")
    if outcome:
        allowed = OUTCOME_TO_STATUS.get(outcome)
        if allowed is None:
            failures.append(
                f"unknown expected.outcome '{outcome}' — add it to OUTCOME_TO_STATUS"
            )
        else:
            actual = case.get("status")
            if actual not in allowed:
                failures.append(
                    f"outcome '{outcome}' expects status in {sorted(allowed)}, got '{actual}'"
                )

    # A tool that errored but left the case in an acceptable status still means the
    # run did not go as designed, so surface it rather than passing silently.
    errored = [
        seg.get("tool_name")
        for trace in case.get("agent_traces") or []
        for seg in trace.get("segments") or []
        if seg.get("status") == "error"
    ]
    if errored:
        failures.append(f"tool calls reported status=error: {sorted(set(errored))}")

    return failures


def run_evals(agent_id: str, session_id: str, region: str) -> list[dict]:
    """Run on-demand evaluations against a session."""
    try:
        from bedrock_agentcore_starter_toolkit import Evaluation
    except ImportError:
        print("ERROR: pip install bedrock-agentcore-starter-toolkit")
        sys.exit(1)

    eval_client = Evaluation(region=region)

    time.sleep(5)  # nosemgrep: arbitrary-sleep — wait for traces to be available

    results = eval_client.run(
        agent_id=agent_id,
        session_id=session_id,
        evaluators=[
            "Builtin.Correctness",
            "Builtin.GoalSuccessRate",
            "Builtin.ToolSelectionAccuracy",
            "Builtin.ToolParameterAccuracy",
            "Builtin.Faithfulness",
        ],
    )

    return [
        {
            "evaluator": r.evaluator_name,
            "score": r.value,
            "label": r.label,
            "explanation": r.explanation,
        }
        for r in results.results
    ]


def main():
    parser = argparse.ArgumentParser(description="Run regression evaluations")
    parser.add_argument("--stack-name", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument(
        "--test-file", default=str(Path(__file__).parent / "ground_truth.json")
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.7,
        help="Minimum average score to pass (default: 0.7)",
    )
    parser.add_argument(
        "--results-file",
        help="Write the full per-case results (assertions + judge scores) to this path",
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Create each case's SAP documents + DynamoDB record before invoking "
        "(requires demo.enabled). Without it, cases are assumed to already exist.",
    )
    args = parser.parse_args()

    print(f"Loading test cases from {args.test_file}")
    with open(args.test_file, encoding="utf-8") as f:
        test_cases = json.load(f)

    if args.seed:
        print("\nSeeding cases into SAP + DynamoDB...")
        test_cases = seed_cases(test_cases, args.stack_name, args.region)
        if not test_cases:
            print("No cases were seeded successfully — aborting.")
            sys.exit(1)
        time.sleep(5)  # nosemgrep: arbitrary-sleep — allow seeded data to settle

    print(f"Getting config for {args.stack_name}...")
    config = get_config(args.stack_name, args.region)
    runtime_arn = config["runtime-arn"]
    agent_id = runtime_arn.split("/")[-1]

    results_summary = []

    for i, tc in enumerate(test_cases):
        print(f"\n{'=' * 60}")
        print(f"Test {i + 1}/{len(test_cases)}: {tc['test_id']}")
        print(f"  {tc['description']}")

        try:
            print("  Invoking agent...")
            session_id = invoke_agent(runtime_arn, tc["payload"], args.region)
            print(f"  Session: {session_id}")

            print("  Checking expectations...")
            case_id = tc["payload"].get("case_id") or (
                f"{tc['payload']['document_number']}-{tc['payload']['item_id']}"
            )
            case = get_case_record(case_id, args.stack_name, args.region)
            failures = (
                check_expectations(tc["expected"], case)
                if tc.get("expected")
                else ["no expected block — the case asserts nothing"]
            )
            if not case:
                failures.append(f"no persisted case record found for {case_id}")

            print("  Running evaluations...")
            evals = run_evals(agent_id, session_id, args.region)

            avg_score = sum(e["score"] for e in evals) / len(evals) if evals else 0
            passed = not failures and avg_score >= args.threshold

            results_summary.append(
                {
                    "test_id": tc["test_id"],
                    "session_id": session_id,
                    "avg_score": avg_score,
                    "passed": passed,
                    "failures": failures,
                    "evals": evals,
                }
            )

            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"  {status} (avg: {avg_score:.2f})")
            for f in failures:
                print(f"    ✗ ASSERTION: {f}")
            for e in evals:
                indicator = "✓" if e["score"] >= args.threshold else "✗"
                print(
                    f"    {indicator} {e['evaluator']}: {e['score']:.2f} — {e['label']}"
                )

        except Exception as e:
            print(f"  ❌ ERROR: {e}")
            results_summary.append(
                {
                    "test_id": tc["test_id"],
                    "avg_score": 0,
                    "passed": False,
                    "error": str(e),
                }
            )

    # Summary
    print(f"\n{'=' * 60}")
    print("REGRESSION SUMMARY")
    print(f"{'=' * 60}")
    total = len(results_summary)
    passed = sum(1 for r in results_summary if r["passed"])
    print(f"  Passed: {passed}/{total}")
    print(f"  Threshold: {args.threshold}")

    if args.results_file:
        Path(args.results_file).write_text(
            json.dumps(results_summary, indent=2), encoding="utf-8"
        )
        print(f"  Results written to {args.results_file}")

    if passed < total:
        print("\n  FAILED TESTS:")
        for r in results_summary:
            if not r["passed"]:
                detail = "; ".join(r.get("failures") or []) or r.get("error") or ""
                print(
                    f"    - {r['test_id']}: avg={r.get('avg_score', 0):.2f}"
                    + (f" — {detail}" if detail else "")
                )
        sys.exit(1)
    else:
        print("\n  All tests passed! ✅")


if __name__ == "__main__":
    main()
