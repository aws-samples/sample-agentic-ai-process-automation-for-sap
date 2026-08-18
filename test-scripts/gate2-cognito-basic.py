#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Gate 2 (`cognito-basic`) interactive-path verifier.

Signs in as a real Cognito human, sends one read-only SAP prompt through the
AG-UI Runtime, and asserts the lifecycle/tool/identity properties Gate 2 lists.
The token is read from a caller-supplied file so no credential is ever printed
or passed on the command line.

    python3 test-scripts/gate2-cognito-basic.py --token-file /tmp/gate2-id.txt
"""

import argparse
import json
import subprocess  # nosec B404 - fixed argv, no shell
import sys
import uuid

import requests

REGION = "us-east-1"
STACK_BASE = "erp-obo-v1"

PROMPT = (
    "Using the SAP OData service API_PURCHASEORDER_PROCESS_SRV, read purchase order "
    "4500002664 from entity set A_PurchaseOrder and report its company code and "
    "document type. Read only — do not create, update or delete anything."
)


def aws(*args):
    out = subprocess.run(  # nosec B603 - fixed argv, no shell
        ["aws", *args, "--region", REGION, "--output", "json"],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)


def runtime_url():
    stack = aws(
        "cloudformation", "describe-stacks", "--stack-name", f"{STACK_BASE}-backend"
    )
    outs = {
        o["OutputKey"]: o["OutputValue"] for o in stack["Stacks"][0].get("Outputs", [])
    }
    for v in outs.values():
        if "arn:aws:bedrock-agentcore" in v and "runtime/" in v:
            escaped = requests.utils.quote(v, safe="")
            return (
                f"https://bedrock-agentcore.{REGION}.amazonaws.com"
                f"/runtimes/{escaped}/invocations?qualifier=DEFAULT"
            ), v
    raise SystemExit(f"no runtime ARN in {STACK_BASE}-backend outputs: {list(outs)}")


def agui_input(prompt, session_id):
    """A RunAgentInput matching frontend/src/services/agentRuntimeService.ts."""
    run_id = f"run-{session_id}"
    return {
        "threadId": session_id,
        "runId": run_id,
        "state": None,
        "messages": [{"id": f"input-{run_id}", "role": "user", "content": prompt}],
        "tools": [],
        "context": [],
        "forwardedProps": {
            "erpPayload": {
                "prompt": prompt,
                "case_id": "",
                "trigger": "ui",
                "run_id": run_id,
                "thread_id": session_id,
            }
        },
    }


def stream(url, token, prompt, session_id):
    headers = {
        "Content-Type": "application/json",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
    }
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.post(
        url,
        headers=headers,
        json=agui_input(prompt, session_id),
        stream=True,
        timeout=420,
    )
    if r.status_code != 200:
        return r.status_code, [], r.text[:400]
    events, raw = [], []
    for line in r.iter_lines(decode_unicode=True):
        if line is None:
            continue
        raw.append(line)
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return r.status_code, events, "\n".join(raw)


FAILED = []


def check(label, ok, detail=""):
    print(
        f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else "")
    )
    if not ok:
        FAILED.append(label)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--token-file", required=True, help="file holding the Cognito ID token"
    )
    args = ap.parse_args()

    token = open(args.token_file).read().strip()
    url, arn = runtime_url()
    session_id = f"gate2-{uuid.uuid4()}"

    print(f"runtime: {arn}")
    print(f"session: {session_id}\n")

    print("negative: no Authorization header")
    status, _, body = stream(url, None, PROMPT, f"{session_id}-noauth")
    check("unauthenticated call is refused", status in (401, 403), f"http={status}")

    print("\ninteractive human run")
    status, events, raw = stream(url, token, PROMPT, session_id)
    check("runtime accepts the human Cognito token", status == 200, f"http={status}")
    if status != 200:
        print(f"  body: {body if not raw else raw[:400]}")
        return 1

    types = [e.get("type") for e in events]
    print(f"  {len(events)} events: {sorted(set(t for t in types if t))}")

    check("RUN_STARTED emitted", "RUN_STARTED" in types)
    terminal = [t for t in types if t in ("RUN_FINISHED", "RUN_ERROR")]
    check(
        "exactly one terminal event, RUN_FINISHED",
        terminal == ["RUN_FINISHED"],
        f"{terminal}",
    )
    check("text content streamed", any(t and "TEXT_MESSAGE" in t for t in types))

    starts = [e for e in events if e.get("type") == "TOOL_CALL_START"]
    ends = [e for e in events if e.get("type") == "TOOL_CALL_END"]
    results = [e for e in events if e.get("type") == "TOOL_CALL_RESULT"]
    names = [e.get("toolCallName") for e in starts]
    print(f"  tools: {names}")
    check("at least one SAP tool call", len(starts) >= 1, f"{len(starts)} calls")
    check(
        "every started tool call resolved",
        len(starts) == len(ends) == len(results),
        f"start={len(starts)} end={len(ends)} result={len(results)}",
    )

    text = "".join(
        e.get("delta", "") for e in events if e.get("type") == "TEXT_MESSAGE_CONTENT"
    )
    check("answer reports company code 1710", "1710" in text, "from the SAP read")
    check("answer reports document type NB", "NB" in text)

    writes = [
        n
        for n in names
        if n
        and any(
            w in n.lower() for w in ("create", "update", "delete", "function_import")
        )
    ]
    check(
        "no write tool was invoked", not writes, f"{writes}" if writes else "read-only"
    )

    print(f"\nagent text ({len(text)} chars):\n{text[:600]}")

    print(f"\n{'FAILURES: ' + ', '.join(FAILED) if FAILED else 'all checks passed'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
