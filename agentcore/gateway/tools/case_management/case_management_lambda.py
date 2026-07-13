# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Case Management Gateway Tool Lambda

DynamoDB state management for ERP exception cases with history tracking.
The wired domain is finance_ap (supplier-invoice three-way-match exceptions); the
store is schema-driven (types/cases.schema.json) and domain-agnostic, so it works
for any additional domain you wire in.
"""

import json
import logging
import os
from datetime import datetime, timezone

import boto3

# WorkItem model + validator ship in the shared_types Lambda layer. Best-effort
# import: absent in local dev/test (validation no-ops), present in the Lambda.
try:
    from generated_cases import WorkItem
    from validate import validate_or_log
except ImportError:
    WorkItem = None

    def validate_or_log(model, data, *, context=""):
        return data


logger = logging.getLogger()
logger.setLevel(logging.INFO)

ssm = boto3.client("ssm")
dynamodb = boto3.resource("dynamodb")

STACK_NAME = os.environ["STACK_NAME_BASE"]

_table = None


def _get_table():
    global _table
    if _table is None:
        name = ssm.get_parameter(Name=f"/{STACK_NAME}/dynamodb/cases-table")[
            "Parameter"
        ]["Value"]
        _table = dynamodb.Table(name)
    return _table


def _validate_key(val: str) -> bool:
    """Validate a case key field (document_number or item_id). Accepts any non-empty
    alphanumeric string up to 40 chars (covers invoice numbers, PO numbers,
    fiscal years, item sequences)."""
    return bool(val and len(val) <= 40)


def _get_case(document_number: str, item_id: str):
    if not _validate_key(document_number):
        return {
            "error": "Invalid document_number (case key). Must be non-empty, max 40 chars."
        }
    if not _validate_key(item_id):
        return {
            "error": "Invalid item_id (case sort key). Must be non-empty, max 40 chars."
        }

    table = _get_table()
    resp = table.get_item(
        Key={"document_number": document_number, "item_id": item_id},
        ConsistentRead=True,
    )
    item = resp.get("Item")
    if not item:
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"No case found for document {document_number} item {item_id}",
                }
            ]
        }

    validate_or_log(WorkItem, item, context="case_management.get")

    return {
        "content": [{"type": "text", "text": json.dumps(item, default=str, indent=2)}]
    }


def _update_case(document_number: str, item_id: str, updates_json: str, action: str):
    if not _validate_key(document_number):
        return {
            "error": "Invalid document_number (case key). Must be non-empty, max 40 chars."
        }
    if not _validate_key(item_id):
        return {
            "error": "Invalid item_id (case sort key). Must be non-empty, max 40 chars."
        }

    try:
        updates = json.loads(updates_json)
    except json.JSONDecodeError:
        return {"error": "Invalid JSON in updates field"}

    table = _get_table()
    ts = datetime.now(timezone.utc).isoformat()

    update_parts = []
    expr_values = {
        ":ts": ts,
    }
    expr_names = {}

    for key, value in updates.items():
        update_parts.append(f"#{key} = :{key}")
        expr_names[f"#{key}"] = key
        expr_values[f":{key}"] = value

    update_parts.append("updated_at = :ts")

    # Append to action_log for audit trail
    if action:
        update_parts.append(
            "action_log = list_append(if_not_exists(action_log, :empty_list), :log_entry)"
        )
        expr_values[":empty_list"] = []
        expr_values[":log_entry"] = [{"action": action, "timestamp": ts}]

    resp = table.update_item(
        Key={"document_number": document_number, "item_id": item_id},
        UpdateExpression="SET " + ", ".join(update_parts),
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
        ReturnValues="ALL_NEW",
    )
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(resp["Attributes"], default=str, indent=2),
            }
        ]
    }


def _resolve_tool_name(context) -> str:
    """Return the bare tool name, asserting the call came through the Gateway.

    The AgentCore Gateway sets ``bedrockAgentCoreToolName`` in the Lambda client
    context after it has evaluated Cedar authorization. A direct invocation that
    bypasses the Gateway won't carry this marker, so we reject it rather than
    executing unauthorized. This does not replace Cedar — it ensures Cedar was
    actually in the path.
    """
    delimiter = "___"
    try:
        original = context.client_context.custom["bedrockAgentCoreToolName"]
    except (AttributeError, KeyError, TypeError):
        raise PermissionError(
            "Missing Gateway tool context — direct invocation is not permitted"
        )
    if delimiter not in original:
        raise PermissionError(f"Unexpected tool context format: {original!r}")
    return original[original.index(delimiter) + len(delimiter) :]


def handler(event, context):
    logger.info(f"Received event: {json.dumps(event)}")

    try:
        tool_name = _resolve_tool_name(context)

        if tool_name == "get_case_state":
            return _get_case(event.get("document_number", ""), event.get("item_id", ""))
        elif tool_name == "update_case_state":
            return _update_case(
                event.get("document_number", ""),
                event.get("item_id", ""),
                event.get("updates", "{}"),
                event.get("action", "update"),
            )
        else:
            return {"error": f"Unknown tool: {tool_name}"}

    except PermissionError as e:
        logger.warning(f"Rejected unauthorized invocation: {e}")
        return {
            "error": "Unauthorized: calls must originate from the AgentCore Gateway"
        }
    except Exception as e:
        logger.error(f"Error: {e}")
        return {"error": f"Case management error: {type(e).__name__}"}
