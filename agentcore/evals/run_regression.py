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
  4. Runs on-demand evaluations (built-in + custom) against each session
  5. Prints pass/fail summary

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

        # AP case key: document_number = supplier invoice number, item_id = fiscal year.
        fiscal_year = str(datetime.now(timezone.utc).year)
        table.put_item(
            Item={
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

            print("  Running evaluations...")
            evals = run_evals(agent_id, session_id, args.region)

            avg_score = sum(e["score"] for e in evals) / len(evals) if evals else 0
            passed = avg_score >= args.threshold

            results_summary.append(
                {
                    "test_id": tc["test_id"],
                    "session_id": session_id,
                    "avg_score": avg_score,
                    "passed": passed,
                    "evals": evals,
                }
            )

            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"  {status} (avg: {avg_score:.2f})")
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

    if passed < total:
        print("\n  FAILED TESTS:")
        for r in results_summary:
            if not r["passed"]:
                print(f"    - {r['test_id']}: avg={r.get('avg_score', 0):.2f}")
        sys.exit(1)
    else:
        print("\n  All tests passed! ✅")


if __name__ == "__main__":
    main()
