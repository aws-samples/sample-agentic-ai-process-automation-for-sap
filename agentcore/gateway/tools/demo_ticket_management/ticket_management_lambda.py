# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Ticket Management Gateway Tool Lambda

Proxies agent tool calls to the Tickets DynamoDB table.
Separate from the API Lambda — this one is invoked by AgentCore Gateway.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone

import boto3

# Canonical case identity codec — ships in the shared_types layer. The agent
# supplies the case_id it was invoked with, so it is normalized once here rather
# than parsed ad hoc.
from case_key import to_case_key, try_normalize_case_id

# Ticket model + validator ship in the shared_types Lambda layer. Best-effort
# import: absent in local dev/test (validation no-ops), present in the Lambda.
try:
    from generated_tickets import ResponseType, Ticket
    from validate import validate_or_log
except ImportError:
    Ticket = None
    VALID_RESPONSE_TYPES = {"approval", "free_text"}

    def validate_or_log(model, data, *, context=""):
        return data
else:
    VALID_RESPONSE_TYPES = {response_type.value for response_type in ResponseType}


logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
_table = None

# Keep in sync with types/tickets.schema.json (TicketPriority)
VALID_PRIORITIES = {"high", "medium", "low"}


def _get_table():
    global _table
    if _table is None:
        ssm = boto3.client("ssm")
        name = ssm.get_parameter(Name=os.environ["TICKETS_TABLE_SSM_PARAM"])[
            "Parameter"
        ]["Value"]
        _table = dynamodb.Table(name)
    return _table


def _create_ticket(event: dict) -> dict:
    title = event.get("title", "").strip()
    if not title:
        return {"error": "title is required"}

    response_type = event.get("response_type", "approval")
    if response_type not in VALID_RESPONSE_TYPES:
        return {
            "error": f"response_type must be one of: {sorted(VALID_RESPONSE_TYPES)}"
        }

    now = datetime.now(timezone.utc).isoformat()
    case_id = try_normalize_case_id(event.get("case_id"))
    ticket = {
        "ticket_id": f"TKT-{uuid.uuid4().hex[:8].upper()}",
        "title": title,
        "description": event.get("description", ""),
        "status": "open",
        "priority": event.get("priority", "medium")
        if event.get("priority") in VALID_PRIORITIES
        else "medium",
        "created_by": "agent",
        "assigned_to": event.get("assigned_to", ""),
        "case_id": case_id or "",
        "category": event.get("category", "general"),
        "response_type": response_type,
        "resolution": "",
        "comments": [],
        "created_at": now,
        "updated_at": now,
    }

    validate_or_log(Ticket, ticket, context="ticket_management.create")
    _get_table().put_item(Item=ticket)

    # Write ticket_id back to the linked case for correlation
    if case_id:
        try:
            cases_param = os.environ.get("CASES_TABLE_SSM_PARAM", "")
            if cases_param:
                ssm = boto3.client("ssm")
                cases_table_name = ssm.get_parameter(Name=cases_param)["Parameter"][
                    "Value"
                ]
                cases_table = dynamodb.Table(cases_table_name)
                cases_table.update_item(
                    Key=to_case_key(case_id),
                    UpdateExpression="SET ticket_id = :tid",
                    ExpressionAttributeValues={":tid": ticket["ticket_id"]},
                    ConditionExpression="attribute_exists(case_id)",
                )
        except Exception as e:
            logger.warning(f"Failed to write ticket_id to case {case_id}: {e}")

    return {"content": [{"type": "text", "text": json.dumps(ticket, default=str)}]}


def _get_ticket(event: dict) -> dict:
    ticket_id = event.get("ticket_id", "")
    if not ticket_id:
        return {"error": "ticket_id is required"}

    resp = _get_table().get_item(Key={"ticket_id": ticket_id}, ConsistentRead=True)
    item = resp.get("Item")
    if not item:
        return {"content": [{"type": "text", "text": f"No ticket found: {ticket_id}"}]}
    return {"content": [{"type": "text", "text": json.dumps(item, default=str)}]}


def _resolve_tool_name(context) -> str:
    """Return the bare tool name, asserting the call came through the Gateway.

    The AgentCore Gateway sets ``bedrockAgentCoreToolName`` in the Lambda client
    context after evaluating Cedar authorization. A direct invocation that
    bypasses the Gateway won't carry this marker, so we reject it rather than
    executing unauthorized.
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

        dispatch = {
            "demo_create_ticket": _create_ticket,
            "demo_get_ticket": _get_ticket,
        }

        fn = dispatch.get(tool_name)
        if not fn:
            return {"error": f"Unknown tool: {tool_name}"}
        return fn(event)

    except PermissionError as e:
        logger.warning(f"Rejected unauthorized invocation: {e}")
        return {
            "error": "Unauthorized: calls must originate from the AgentCore Gateway"
        }
    except Exception as e:
        logger.error(f"Error: {e}")
        return {"error": f"Ticket management error: {type(e).__name__}"}
