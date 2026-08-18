#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Gate 2 (`cognito-basic`) autonomous-path verifier.

Enqueues one real case through the supported operator path (`PUT /autonomy`
with `enqueue_case_id`), then asserts the properties Gate 2's autonomous
section lists by reading the artifacts each one leaves behind: the invoker's
CloudWatch logs, the case record in DynamoDB, and the SQS queue depth.

The token is read from a caller-supplied file so no credential is printed or
passed on the command line.

    python3 test-scripts/gate2-autonomous.py --token-file /tmp/g2-id.txt
"""

import argparse
import json
import subprocess  # nosec B404 - fixed argv, no shell
import sys
import time

import requests

REGION = "us-east-1"
STACK_BASE = "erp-obo-v1"
LOG_GROUP = f"/aws/lambda/{STACK_BASE}-agent-invoker"

FAILED = []


def check(label, ok, detail=""):
    print(
        f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else "")
    )
    if not ok:
        FAILED.append(label)
    return ok


def aws(*args):
    out = subprocess.run(  # nosec B603 - fixed argv, no shell
        ["aws", *args, "--region", REGION, "--output", "json"],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout) if out.stdout.strip() else {}


def ssm(name):
    return aws("ssm", "get-parameter", "--name", name)["Parameter"]["Value"]


def api_base():
    stack = aws(
        "cloudformation", "describe-stacks", "--stack-name", f"{STACK_BASE}-backend"
    )
    outs = {
        o["OutputKey"]: o["OutputValue"] for o in stack["Stacks"][0].get("Outputs", [])
    }
    # One REST API serves /cases, /autonomy and /observability; FeedbackApiUrl is the
    # stable output name for its stage root.
    url = outs.get("FeedbackApiUrl")
    if not url:
        raise SystemExit(f"no FeedbackApiUrl in outputs: {list(outs)}")
    return url.rstrip("/")


def pick_case(table):
    """Return the case_id of one freshly-detected (never-processed) case."""
    resp = aws(
        "dynamodb",
        "scan",
        "--table-name",
        table,
        "--filter-expression",
        "#s = :p",
        "--expression-attribute-names",
        '{"#s":"status"}',
        "--expression-attribute-values",
        '{":p":{"S":"detected"}}',
        "--max-items",
        "1",
        "--projection-expression",
        "case_id,document_number,item_id",
    )
    items = resp.get("Items", [])
    if not items:
        raise SystemExit("no detected case to enqueue")
    it = items[0]
    return (
        it.get("case_id", {}).get("S")
        or f"{it['document_number']['S']}-{it['item_id']['S']}"
    )


def get_case(table, case_id):
    # case_id is the table's sole partition key (see shared_types/case_key.to_case_key).
    resp = aws(
        "dynamodb",
        "get-item",
        "--table-name",
        table,
        "--key",
        json.dumps({"case_id": {"S": case_id}}),
        "--consistent-read",
    )
    return resp.get("Item", {})


def invoker_logs(since_ms, needle=None):
    """Return invoker log messages emitted since `since_ms`."""
    args = [
        "logs",
        "filter-log-events",
        "--log-group-name",
        LOG_GROUP,
        "--start-time",
        str(since_ms),
    ]
    if needle:
        args += ["--filter-pattern", f'"{needle}"']
    try:
        return [e["message"] for e in aws(*args).get("events", [])]
    except subprocess.CalledProcessError:
        return []


def wait_for_status(table, case_id, terminal, timeout=420):
    """Poll the case until it leaves 'pending'/'processing'."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        item = get_case(table, case_id)
        status = item.get("status", {}).get("S")
        if status != last:
            print(f"    status: {status}")
            last = status
        if status in terminal:
            return status, item
        time.sleep(10)
    return last, get_case(table, case_id)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--token-file", required=True, help="file holding the Cognito ID token"
    )
    ap.add_argument("--case-id", help="case to enqueue (default: first pending)")
    args = ap.parse_args()

    token = open(args.token_file).read().strip()
    table = ssm(f"/{STACK_BASE}/dynamodb/cases-table")
    base = api_base()
    case_id = args.case_id or pick_case(table)
    start_ms = int(time.time() * 1000) - 5000

    print(f"table:   {table}")
    print(f"api:     {base}")
    print(f"case:    {case_id}\n")

    before = get_case(table, case_id)
    print(f"initial status: {before.get('status', {}).get('S')}")
    traces_before = len(before.get("agent_traces", {}).get("L", []))

    # ── Enqueue through the supported operator path ──────────────────────
    print("\nenqueue one known test case through the supported API path")
    r = requests.put(
        f"{base}/autonomy",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={"enqueue_case_id": case_id},
        timeout=60,
    )
    check("enqueue accepted", r.status_code == 200, f"http={r.status_code}")
    if r.status_code != 200:
        print(f"  body: {r.text[:300]}")
        return 1
    check(
        "response confirms the enqueued case",
        r.json().get("enqueued") == case_id,
        str(r.json()),
    )

    # ── Wait for the run to reach a terminal case state ──────────────────
    print("\nwaiting for the agent run to reach a terminal case state")
    status, item = wait_for_status(
        table,
        case_id,
        {
            "complete",
            "awaiting_human_input",
            "manual_review_required",
            "sap_updated",
            "error",
        },
    )
    check(
        "run reached a terminal case state (case updated, not stuck in processing)",
        status
        in {
            "complete",
            "awaiting_human_input",
            "manual_review_required",
            "sap_updated",
        },
        f"status={status}",
    )

    logs = invoker_logs(start_ms)
    joined = "\n".join(logs)

    # ── Envelope shape: the invoker sends erpPayload, not a duplicated prompt ──
    print("\nAG-UI envelope and prompt ownership")
    check(
        "invoker logged this case (SQS path ran)",
        case_id in joined,
        f"{len(logs)} log lines",
    )
    # The invoker builds forwardedProps.erpPayload and deliberately sends no prompt;
    # the agent's own _build_prompt supplies the SOP instruction. A duplicated user
    # prompt would show up as the invoker sending a "prompt" key.
    check(
        "invoker did not send its own prompt key (agent owns prompt construction)",
        '"prompt"' not in joined,
        "no prompt key in invoker logs",
    )

    # ── Queue consumption ───────────────────────────────────────────────
    print("\nqueue message consumption")
    qurl = ssm(f"/{STACK_BASE}/sqs/agent-queue-url")
    if qurl:
        attrs = aws(
            "sqs",
            "get-queue-attributes",
            "--queue-url",
            qurl,
            "--attribute-names",
            "ApproximateNumberOfMessages",
            "ApproximateNumberOfMessagesNotVisible",
        )["Attributes"]
        visible = int(attrs["ApproximateNumberOfMessages"])
        inflight = int(attrs["ApproximateNumberOfMessagesNotVisible"])
        check(
            "queue drained (message consumed, not left in flight)",
            visible == 0 and inflight == 0,
            f"visible={visible} inflight={inflight}",
        )
    else:
        print("  SKIP  queue URL param not found")

    # ── Trace / correlation / cost persistence ──────────────────────────
    print("\ntrace, correlation ID, case ID, trigger, latency, token/cost persistence")
    traces = item.get("agent_traces", {}).get("L", [])
    check(
        "a new trace was appended to the case",
        len(traces) > traces_before,
        f"{traces_before} -> {len(traces)}",
    )

    if traces:
        t = traces[-1]["M"]
        fields = {
            k: (v.get("S") or v.get("N")) for k, v in t.items() if isinstance(v, dict)
        }
        print(f"    trace fields: {sorted(t)}")
        check("trace has a trace_id", "trace_id" in t, str(fields.get("trace_id")))
        check(
            "trace has a correlation_id",
            "correlation_id" in t,
            str(fields.get("correlation_id")),
        )
        check(
            "trace records the trigger",
            "trigger" in t or "initiator" in t,
            f"trigger={fields.get('trigger')} initiator={fields.get('initiator')}",
        )
        check("trace records latency", "latency_ms" in t, str(fields.get("latency_ms")))
        check(
            "trace records token counts",
            "input_tokens" in t and "output_tokens" in t,
            f"in={fields.get('input_tokens')} out={fields.get('output_tokens')}",
        )
        check(
            "trace records estimated cost",
            "estimated_cost_usd" in t,
            str(fields.get("estimated_cost_usd")),
        )

    cost = item.get("cost_summary", {}).get("M", {})
    if cost:
        print(
            f"    cost_summary: { {k: list(v.values())[0] for k, v in cost.items()} }"
        )
        check(
            "per-case cost accumulator incremented",
            float(cost.get("invocation_count", {}).get("N", 0)) >= 1,
            f"invocations={cost.get('invocation_count', {}).get('N')}",
        )

    # ── The trace is retrievable through the API, keyed to the case ─────
    print("\ntrace retrievable via GET /observability/traces")
    tr = requests.get(
        f"{base}/observability/traces?hours=2",
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    if check(
        "traces endpoint returned 200", tr.status_code == 200, f"http={tr.status_code}"
    ):
        body = tr.json()
        got = [x for x in body.get("traces", []) if x.get("case_id") == case_id]
        check(
            "this case's trace is retrievable and case-scoped",
            bool(got),
            f"scanned={body.get('total_cases_scanned')} matched={len(got)}",
        )

    print(f"\n{'FAILURES: ' + ', '.join(FAILED) if FAILED else 'all checks passed'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
