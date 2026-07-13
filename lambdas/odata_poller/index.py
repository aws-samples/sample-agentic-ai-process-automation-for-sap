# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
SAP OData Poller Lambda Function

Config-driven poller — domain definitions live in domains/*.json.
The polling_engine handles the generic pipeline; this file is just
the Lambda wiring (AWS clients, SSM, SQS, DynamoDB).
"""

import json
import os
import uuid

import boto3
from polling_engine import load_domain_configs, poll_domain
from sap_auth import get_sap_session

ssm = boto3.client("ssm")
dynamodb = boto3.resource("dynamodb")
sqs = boto3.client("sqs")

QUEUE_URL = os.environ.get("AGENT_QUEUE_URL", "")
STACK_NAME = os.environ["STACK_NAME_BASE"]

_trigger_mode_cache = None


def _get_trigger_mode() -> str:
    global _trigger_mode_cache
    if _trigger_mode_cache is None:
        try:
            _trigger_mode_cache = ssm.get_parameter(
                Name=f"/{STACK_NAME}/autonomy/trigger-mode"
            )["Parameter"]["Value"]
        except Exception:
            _trigger_mode_cache = "manual"
    return _trigger_mode_cache


def _get_ssm(name: str) -> str:
    return ssm.get_parameter(Name=name)["Parameter"]["Value"]


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


def _case_exists(table, doc_number: str, item_id: str) -> bool:
    """Return True if case exists and is past 'detected' status."""
    try:
        resp = table.get_item(Key={"document_number": doc_number, "item_id": item_id})
        if "Item" in resp:
            return resp["Item"].get("status", "detected") != "detected"
        return False
    except Exception as e:
        print(f"Error checking case {doc_number}-{item_id}: {e}")
        return False


def _put_case(table, case_item: dict) -> bool:
    """Conditional put — skip if case already exists."""
    try:
        table.put_item(
            Item=case_item,
            ConditionExpression="attribute_not_exists(document_number)",
        )
        return True
    except dynamodb.meta.client.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def _enqueue(case_id: str, domain: str, process_type: str):
    """Enqueue case for agent processing if in auto trigger mode."""
    if not QUEUE_URL or _get_trigger_mode() != "auto":
        return
    sqs.send_message(
        QueueUrl=QUEUE_URL,
        MessageBody=json.dumps(
            {
                "case_id": case_id,
                "domain": domain,
                "process_type": process_type,
                "trigger": "poller",
            }
        ),
        MessageGroupId=case_id,
    )


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


def lambda_handler(event, context):
    print("Starting SAP OData polling...")

    table_name = _get_ssm(f"/{STACK_NAME}/dynamodb/cases-table")
    session, sap_base_url = get_sap_session()

    # Audit baggage — system-initiated polling, no user identity
    correlation_id = f"poller-{uuid.uuid4().hex[:12]}"
    session.headers.update(
        {
            "x-correlationid": correlation_id,
            "x-sap-ext-initiator": f"system/{STACK_NAME}",
            "x-sap-ext-trigger": "poller",
        }
    )

    table = dynamodb.Table(table_name)

    print(f"SAP endpoint: {sap_base_url}")

    configs = load_domain_configs()
    print(f"Loaded {len(configs)} domain configs")

    results = {}
    total_created = total_skipped = 0

    for cfg in configs:
        domain = cfg["domain"]
        created, skipped = poll_domain(
            config=cfg,
            sap_base_url=sap_base_url,
            sap_session=session,
            table=table,
            case_exists_fn=_case_exists,
            put_case_fn=_put_case,
            enqueue_fn=_enqueue,
        )
        results[domain] = {"created": created, "skipped": skipped}
        total_created += created
        total_skipped += skipped

    print(f"Polling complete: {total_created} created, {total_skipped} skipped")

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "cases_created": total_created,
                "cases_skipped": total_skipped,
                "domains": results,
            }
        ),
    }
