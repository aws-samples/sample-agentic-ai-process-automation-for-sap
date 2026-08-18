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

# Canonical case identity codec — ships in the shared_types layer.
from case_key import CaseKeyError, to_case_key

# WorkItem model + validator ship in the shared_types Lambda layer. Best-effort
# import: absent in local dev/test (validation no-ops), present in the Lambda.
try:
    from generated_cases import CaseStatus, WorkItem
    from validate import validate_or_log
except ImportError:
    CaseStatus = None
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


def _resolve_case_key(event: dict) -> dict[str, str]:
    """Return the DynamoDB key for the case the agent named.

    The model is given a ``case_id`` in its prompt, so that is the contract.

    Raises:
        CaseKeyError: If ``case_id`` is not a well-formed identity.
    """
    return to_case_key(event.get("case_id", ""))


def _get_case(event: dict):
    try:
        key = _resolve_case_key(event)
    except CaseKeyError as e:
        return {"error": f"Invalid case identity: {e}"}

    table = _get_table()
    resp = table.get_item(Key=key, ConsistentRead=True)
    item = resp.get("Item")
    if not item:
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"No case found for {key['case_id']}",
                }
            ]
        }

    validate_or_log(WorkItem, item, context="case_management.get")

    return {
        "content": [{"type": "text", "text": json.dumps(item, default=str, indent=2)}]
    }


def _update_case(event: dict):
    try:
        key = _resolve_case_key(event)
    except CaseKeyError as e:
        return {"error": f"Invalid case identity: {e}"}

    updates_json = event.get("updates", "{}")
    action = event.get("action", "update")

    try:
        updates = json.loads(updates_json)
    except json.JSONDecodeError:
        return {"error": "Invalid JSON in updates field"}

    # Trust boundary: `status` is model-authored free text. An out-of-enum value
    # is not merely invalid — the UI's caseStatusMeta falls back to "Detected",
    # so a failed case would render as brand new. Reject instead of warning
    # (validate_or_log is a log-and-continue net) and name the legal values so
    # the agent can self-correct on the next turn.
    if CaseStatus is not None and "status" in updates:
        allowed = [s.value for s in CaseStatus]
        if updates["status"] not in allowed:
            return {
                "error": (
                    f"Invalid status {updates['status']!r}. "
                    f"Must be one of: {', '.join(sorted(allowed))}"
                )
            }

    table = _get_table()
    ts = datetime.now(timezone.utc).isoformat()

    update_parts = []
    remove_parts = []
    expr_values = {
        ":ts": ts,
    }
    expr_names = {}

    # Server-owned fields are dropped from model-authored `updates` rather than
    # merged. Two reasons, and the first is a hard failure: this function already
    # writes each of these itself, and DynamoDB rejects an UpdateExpression whose
    # paths overlap ("Two document paths overlap") — so a model passing any of
    # them used to fail the whole call, losing the status write with it. The
    # second is trust: these three are the audit trail and the basis of the
    # handover's age claim, so a fabricated value is worse than no value.
    for reserved in ("updated_at", "action_log", "inquiry_sent_at"):
        updates.pop(reserved, None)

    for key_name, value in updates.items():
        update_parts.append(f"#{key_name} = :{key_name}")
        expr_names[f"#{key_name}"] = key_name
        expr_values[f":{key_name}"] = value

    update_parts.append("updated_at = :ts")

    # `inquiry_sent_at` is stamped here rather than asked of the model. Reaching
    # awaiting_human_input *is* the moment a human was asked: the platform prompt
    # sends the ticket or notification, then sets this status, and both channels
    # plus every SOP route through this one call. Asking eight SOP clauses to pass
    # the field instead would make the handover's "waiting 6d" contingent on model
    # cooperation, and a missed write reads as recent activity on a stale case.
    #
    # if_not_exists, because a re-invoked case that is still waiting writes the
    # status again and the *first* inquiry is the one the age claim is about.
    # Leaving the status clears it, so a case that comes back and escalates a
    # second time is not aged from the first inquiry. An update that names no
    # status touches neither — a field edit is not a change of who is waiting.
    status = updates.get("status")
    if status == "awaiting_human_input":
        update_parts.append("inquiry_sent_at = if_not_exists(inquiry_sent_at, :ts)")
    elif status is not None:
        remove_parts.append("inquiry_sent_at")

    # Append to action_log for audit trail
    if action:
        update_parts.append(
            "action_log = list_append(if_not_exists(action_log, :empty_list), :log_entry)"
        )
        expr_values[":empty_list"] = []
        expr_values[":log_entry"] = [{"action": action, "timestamp": ts}]

    expression = "SET " + ", ".join(update_parts)
    if remove_parts:
        expression += " REMOVE " + ", ".join(remove_parts)

    resp = table.update_item(
        Key=key,
        UpdateExpression=expression,
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
            return _get_case(event)
        elif tool_name == "update_case_state":
            return _update_case(event)
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
