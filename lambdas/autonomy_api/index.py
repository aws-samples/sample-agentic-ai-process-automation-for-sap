# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Autonomy controls API Lambda — GET/PUT for trigger-mode."""

import json
import os

import boto3

ssm = boto3.client("ssm")
STACK = os.environ["STACK_NAME_BASE"]
SQS_URL = os.environ.get("AGENT_QUEUE_URL", "")
sqs = boto3.client("sqs") if SQS_URL else None

VALID = {
    "trigger-mode": {"auto", "manual"},
}

# Whether this deployment has an unattended caller at all. A profile that does not
# declare `autonomous` gets no poller and no PUT, but the trigger-mode parameter is
# seeded regardless — so `auto` can be stored and inert. Callers need to tell those
# apart; without it a UI reads a stored `auto` as live unattended SAP writes.
#
# Three-state on purpose. An absent variable is a Lambda deployed before this field
# existed: UNKNOWN, never False. Reporting "cannot go auto" for a capable stack is a
# confident wrong answer, and this claim's failure mode is the one that matters.
# Compared as a string because bool("false") is True.
_CAPABLE_RAW = os.environ.get("AUTONOMOUS_CAPABLE")
AUTONOMOUS_CAPABLE = None if _CAPABLE_RAW is None else _CAPABLE_RAW == "true"


def handler(event, context):
    method = event.get("httpMethod", "GET")

    if method == "GET":
        modes = {}
        for param in VALID:
            try:
                modes[param] = ssm.get_parameter(Name=f"/{STACK}/autonomy/{param}")[
                    "Parameter"
                ]["Value"]
            except Exception:
                modes[param] = None
        # Same payload as the mode on purpose: a caller that fetched these separately
        # could paint a stored `auto` before learning it is inert.
        modes["autonomous-capable"] = AUTONOMOUS_CAPABLE
        return _resp(200, modes)

    if method == "PUT":
        body = json.loads(event.get("body") or "{}")

        updated = {}
        for param, allowed in VALID.items():
            val = body.get(
                param.replace("-", "_")
            )  # accept trigger_mode or trigger-mode
            if val is None:
                val = body.get(param)
            if val and val in allowed:
                ssm.put_parameter(
                    Name=f"/{STACK}/autonomy/{param}",
                    Value=val,
                    Type="String",
                    Overwrite=True,
                )
                updated[param] = val

        # Single-case operator enqueue. The UI's multi-select goes to /cases/enqueue
        # (API Gateway → SQS direct, one request per case), so there is no plural
        # form here.
        case_id = body.get("enqueue_case_id")
        if case_id and SQS_URL:
            sqs.send_message(
                QueueUrl=SQS_URL,
                MessageBody=json.dumps({"case_id": case_id, "trigger": "manual"}),
                MessageGroupId=case_id,
            )
            updated["enqueued"] = case_id

        if not updated:
            return _resp(400, {"error": "No valid fields provided"})
        return _resp(200, updated)

    return _resp(405, {"error": "Method not allowed"})


def _resp(code, body):
    return {
        "statusCode": code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }
