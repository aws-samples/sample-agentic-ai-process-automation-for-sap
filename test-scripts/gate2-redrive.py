#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Gate 2 (`cognito-basic`) redrive verifier — the last autonomous checklist item.

    Confirm a retryable error redrives and the final receive attempt cannot
    leave the case stuck in `processing`.

Proving this needs a failure the invoker treats as retryable, so it injects one:
`STACK_NAME_BASE` is pointed at a stack that does not exist, which makes the
runtime-ARN lookup raise before any agent work or SAP call happens. That is the
same `except` -> `batchItemFailures` path a transport failure to AgentCore takes,
which is the branch under test; `CASES_TABLE` is left alone so status writes still
land.

Two deployment settings are changed and restored in a `finally` block:
  - invoker `STACK_NAME_BASE`      (the injected fault)
  - queue `VisibilityTimeout`      960s -> 20s. Observed effect is partial: the
    first redelivery still took the full 960s, later ones honored 20s. Safe to
    lower only because the injected fault fails in about a second, so no two
    receives of the same message can overlap.

Budget ~20 minutes of wall clock for the same reason.

    python3 test-scripts/gate2-redrive.py --token-file /tmp/g2a-id.txt
"""

import argparse
import json
import subprocess  # nosec B404 - fixed argv, no shell
import sys
import time

import requests

REGION = "us-east-1"
STACK_BASE = "erp-obo-v1"
INVOKER = f"{STACK_BASE}-agent-invoker"
BOGUS_STACK = f"{STACK_BASE}-does-not-exist-redrive-probe"
PROBE_VISIBILITY = "20"
# The first redelivery ignored the lowered visibility timeout and took the original
# 960s, so the window has to outlast that, not the nominal 3 x PROBE_VISIBILITY.
WATCH_TIMEOUT_SECONDS = 1500

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
    return outs["FeedbackApiUrl"].rstrip("/")


def invoker_env():
    cfg = aws("lambda", "get-function-configuration", "--function-name", INVOKER)
    return (cfg.get("Environment") or {}).get("Variables", {})


def set_invoker_env(variables):
    aws(
        "lambda",
        "update-function-configuration",
        "--function-name",
        INVOKER,
        "--environment",
        json.dumps({"Variables": variables}),
    )
    aws("lambda", "wait", "function-updated", "--function-name", INVOKER)


def set_visibility(qurl, seconds):
    aws(
        "sqs",
        "set-queue-attributes",
        "--queue-url",
        qurl,
        "--attributes",
        json.dumps({"VisibilityTimeout": str(seconds)}),
    )


def pick_case(table, exclude):
    resp = aws(
        "dynamodb",
        "scan",
        "--table-name",
        table,
        "--filter-expression",
        "#s = :d",
        "--expression-attribute-names",
        '{"#s":"status"}',
        "--expression-attribute-values",
        '{":d":{"S":"detected"}}',
        "--max-items",
        "5",
        "--projection-expression",
        "case_id",
    )
    for it in resp.get("Items", []):
        cid = it["case_id"]["S"]
        if cid != exclude:
            return cid
    raise SystemExit("no detected case available")


def case_status(table, case_id):
    resp = aws(
        "dynamodb",
        "get-item",
        "--table-name",
        table,
        "--key",
        json.dumps({"case_id": {"S": case_id}}),
        "--consistent-read",
        "--projection-expression",
        "#s,status_reason",
        "--expression-attribute-names",
        '{"#s":"status"}',
    )
    item = resp.get("Item", {})
    return item.get("status", {}).get("S"), item.get("status_reason", {}).get("S")


def attempt_logs(log_group, since_ms, case_id):
    """Return the invoker's log lines for this case's attempts.

    The failure line is keyed by SQS message id, not case id (`Failed msg=...`),
    so filtering on the case id alone would silently find zero attempts.
    """
    events = aws(
        "logs",
        "filter-log-events",
        "--log-group-name",
        log_group,
        "--start-time",
        str(since_ms),
    ).get("events", [])
    msgs = [e["message"].rstrip() for e in events]
    return [m for m in msgs if case_id in m or "Failed msg=" in m]


def drain_dlq(dlq_url, case_id):
    """Delete our own synthetic message from the DLQ; leave anything else alone."""
    removed = 0
    for _ in range(5):
        msgs = aws(
            "sqs",
            "receive-message",
            "--queue-url",
            dlq_url,
            "--max-number-of-messages",
            "10",
            "--visibility-timeout",
            "5",
            "--wait-time-seconds",
            "2",
        ).get("Messages", [])
        if not msgs:
            break
        for m in msgs:
            if case_id in m["Body"]:
                aws(
                    "sqs",
                    "delete-message",
                    "--queue-url",
                    dlq_url,
                    "--receipt-handle",
                    m["ReceiptHandle"],
                )
                removed += 1
    return removed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token-file", required=True)
    ap.add_argument("--exclude-case", default="")
    args = ap.parse_args()

    token = open(args.token_file).read().strip()
    table = ssm(f"/{STACK_BASE}/dynamodb/cases-table")
    qurl = ssm(f"/{STACK_BASE}/sqs/agent-queue-url")
    dlq_url = qurl.replace("-agent-queue.fifo", "-agent-dlq.fifo")
    base = api_base()
    case_id = pick_case(table, args.exclude_case)
    log_group = f"/aws/lambda/{INVOKER}"

    original_env = invoker_env()
    original_visibility = aws(
        "sqs",
        "get-queue-attributes",
        "--queue-url",
        qurl,
        "--attribute-names",
        "VisibilityTimeout",
    )["Attributes"]["VisibilityTimeout"]

    print(f"case:            {case_id}")
    print(f"queue:           {qurl.rsplit('/', 1)[-1]}")
    print(
        f"restore on exit: STACK_NAME_BASE={original_env.get('STACK_NAME_BASE')} "
        f"VisibilityTimeout={original_visibility}\n"
    )

    try:
        print("inject a retryable failure into the invoker")
        set_visibility(qurl, PROBE_VISIBILITY)
        set_invoker_env({**original_env, "STACK_NAME_BASE": BOGUS_STACK})
        print(
            f"  STACK_NAME_BASE -> {BOGUS_STACK}, VisibilityTimeout -> {PROBE_VISIBILITY}s"
        )

        start_ms = int(time.time() * 1000) - 5000
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

        print(f"\nwatching the redrive (up to {WATCH_TIMEOUT_SECONDS // 60} min)")
        seen_processing = False
        final = None
        deadline = time.time() + WATCH_TIMEOUT_SECONDS
        while time.time() < deadline:
            status, reason = case_status(table, case_id)
            if status == "processing":
                seen_processing = True
            if status == "manual_review_required":
                final = (status, reason)
                break
            time.sleep(30)
            print(f"    status: {status}")

        lines = attempt_logs(log_group, start_ms, case_id)
        failures = [ln for ln in lines if "Failed msg=" in ln]
        print(f"\n  invoker attempts logged: {len(failures)}")
        for ln in lines:
            print(f"    {ln[:160]}")

        print("\nredrive behavior")
        check("the case entered processing before failing", seen_processing)
        check(
            "the retryable error redrove (more than one receive)",
            len(failures) >= 2,
            f"{len(failures)} failed attempts",
        )
        check(
            "it exhausted maxReceiveCount=3",
            len(failures) >= 3,
            f"{len(failures)} failed attempts",
        )
        check(
            "the final receive did not leave the case in processing",
            final is not None and final[0] == "manual_review_required",
            f"final status={final[0] if final else case_status(table, case_id)[0]}",
        )
        check(
            "the last-retry log records the escalation",
            any("moved to manual_review_required after" in ln for ln in lines),
        )

        print("\ndead-letter queue")
        time.sleep(5)
        removed = drain_dlq(dlq_url, case_id)
        check(
            "the exhausted message landed in the DLQ",
            removed >= 1,
            f"{removed} message(s)",
        )

    finally:
        print("\nrestoring deployment settings")
        set_invoker_env(original_env)
        set_visibility(qurl, original_visibility)
        now = invoker_env().get("STACK_NAME_BASE")
        vis = aws(
            "sqs",
            "get-queue-attributes",
            "--queue-url",
            qurl,
            "--attribute-names",
            "VisibilityTimeout",
        )["Attributes"]["VisibilityTimeout"]
        print(f"  STACK_NAME_BASE={now} VisibilityTimeout={vis}")
        if now != original_env.get("STACK_NAME_BASE") or vis != original_visibility:
            print("  !! RESTORE INCOMPLETE — fix by hand before leaving the stack")
            FAILED.append("restore deployment settings")

    print(f"\n{'FAILURES: ' + ', '.join(FAILED) if FAILED else 'all checks passed'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
