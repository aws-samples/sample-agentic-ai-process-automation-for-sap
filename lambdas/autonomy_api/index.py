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

        case_id = body.get("enqueue_case_id")
        if case_id and SQS_URL:
            sqs.send_message(
                QueueUrl=SQS_URL,
                MessageBody=json.dumps({"case_id": case_id, "trigger": "manual"}),
                MessageGroupId=case_id,
            )
            updated["enqueued"] = case_id

        case_ids = body.get("enqueue_case_ids")
        if case_ids and SQS_URL:
            enqueued = []
            for cid in case_ids:
                sqs.send_message(
                    QueueUrl=SQS_URL,
                    MessageBody=json.dumps({"case_id": cid, "trigger": "manual"}),
                    MessageGroupId=cid,
                )
                enqueued.append(cid)
            updated["enqueued"] = enqueued

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
