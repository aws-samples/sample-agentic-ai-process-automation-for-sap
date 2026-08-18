# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Batch Runner Lambda

Sweeps cases that were detected but never handed to the agent, and enqueues them
on the existing agent-invocation FIFO queue. The poller enqueues a case only at
the moment it creates it, so anything created while `autonomy/trigger-mode` was
`manual` — or whose enqueue failed — sits in `detected` forever with no
unattended caller. This is that caller.

Identity: nothing here carries a human. The agent invoker authenticates with the
Cognito machine client (client_credentials) and mints a fresh token per run, so
no stored refresh token is involved. That is what makes this mode deployable
against `m2m-sap` / `basic` today; the user-identity flavour of batch — acting as
a specific absent human — still needs a refresh-capable outbound.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key

# Canonical case identity codec — ships in the shared_types layer.
from case_key import try_normalize_case_id

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ssm = boto3.client("ssm")
sqs = boto3.client("sqs")
dynamodb = boto3.resource("dynamodb")

STACK_NAME = os.environ["STACK_NAME_BASE"]
TABLE_NAME = os.environ["CASES_TABLE"]
QUEUE_URL = os.environ.get("AGENT_QUEUE_URL", "")

# A case the poller created moments ago may still be mid-enqueue. The queue's
# content-based dedup does not help here: the batch body differs from the
# poller's (trigger differs), so both would be accepted. This age floor is the
# actual double-invocation guard, and it must stay above the poller schedule
# (default rate(5 minutes)).
MIN_AGE_MINUTES = int(os.environ.get("BATCH_MIN_AGE_MINUTES", "15"))
# Bounds one sweep so a large backlog cannot bury the queue in a single run;
# the next scheduled sweep picks up the remainder.
# ponytail: fixed cap, make it a config knob if a real backlog outgrows it.
MAX_CASES = int(os.environ.get("BATCH_MAX_CASES", "100"))


def _trigger_mode() -> str:
    """Read the autonomy switch. Governs every unattended enqueue path, not just
    the poller's — `manual` means a human triggers work, so the sweep is a no-op."""
    try:
        return ssm.get_parameter(Name=f"/{STACK_NAME}/autonomy/trigger-mode")[
            "Parameter"
        ]["Value"]
    except Exception:
        return "manual"


def _stale_detected_cases(table, cutoff: str) -> list[dict]:
    """Cases still in `detected` and older than the cutoff, capped at MAX_CASES."""
    cases: list[dict] = []
    kwargs = {
        "IndexName": "status-index",
        "KeyConditionExpression": Key("status").eq("detected"),
        "FilterExpression": "created_at <= :cutoff",
        "ExpressionAttributeValues": {":cutoff": cutoff},
    }
    while True:
        resp = table.query(**kwargs)
        cases.extend(resp.get("Items", []))
        key = resp.get("LastEvaluatedKey")
        if not key or len(cases) >= MAX_CASES:
            break
        kwargs["ExclusiveStartKey"] = key
    return cases[:MAX_CASES]


def _enqueue(case: dict) -> bool:
    """Enqueue one case. Returns False when its identity is unusable."""
    case_id = try_normalize_case_id(case.get("case_id"))
    if not case_id:
        logger.warning("Skipping case with unusable key: %r", case.get("case_id"))
        return False
    sqs.send_message(
        QueueUrl=QUEUE_URL,
        MessageBody=json.dumps(
            {
                "case_id": case_id,
                "domain": case.get("domain"),
                "process_type": case.get("process_type"),
                "trigger": "batch",
            }
        ),
        MessageGroupId=case_id,
    )
    return True


def handler(event, context):
    if not QUEUE_URL:
        logger.error("No AGENT_QUEUE_URL — nothing to enqueue into.")
        return {"swept": 0, "enqueued": 0, "skipped": "no-queue"}

    mode = _trigger_mode()
    if mode != "auto":
        logger.info("trigger-mode=%s — batch sweep is a no-op.", mode)
        return {"swept": 0, "enqueued": 0, "skipped": "manual"}

    cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=MIN_AGE_MINUTES)
    ).isoformat()
    table = dynamodb.Table(TABLE_NAME)
    cases = _stale_detected_cases(table, cutoff)

    enqueued = 0
    for case in cases:
        try:
            if _enqueue(case):
                enqueued += 1
        except Exception as e:
            # One bad case must not abandon the rest of the backlog.
            logger.warning("Enqueue failed for %s: %s", case.get("case_id"), e)

    logger.info("Batch sweep: %d stale, %d enqueued.", len(cases), enqueued)
    return {"swept": len(cases), "enqueued": enqueued}
