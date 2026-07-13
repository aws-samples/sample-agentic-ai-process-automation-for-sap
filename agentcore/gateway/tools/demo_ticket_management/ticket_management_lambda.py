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

# Ticket model + validator ship in the shared_types Lambda layer. Best-effort
# import: absent in local dev/test (validation no-ops), present in the Lambda.
try:
    from generated_tickets import Ticket
    from validate import validate_or_log
except ImportError:
    Ticket = None

    def validate_or_log(model, data, *, context=""):
        return data


logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
_table = None

# Keep in sync with types/tickets.schema.json (TicketStatus, TicketPriority)
VALID_STATUSES = {"open", "assigned", "approved", "denied", "replied", "closed"}
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

    now = datetime.now(timezone.utc).isoformat()
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
        "case_id": event.get("case_id", ""),
        "category": event.get("category", "general"),
        "response_type": event.get("response_type", "approval"),
        "resolution": "",
        "comments": [],
        "created_at": now,
        "updated_at": now,
    }

    validate_or_log(Ticket, ticket, context="ticket_management.create")
    _get_table().put_item(Item=ticket)

    # Write ticket_id back to the linked case for correlation
    case_id = event.get("case_id", "")
    if case_id and "#" in case_id:
        try:
            doc, item_id = case_id.split("#", 1)
            cases_param = os.environ.get("CASES_TABLE_SSM_PARAM", "")
            if cases_param:
                ssm = boto3.client("ssm")
                cases_table_name = ssm.get_parameter(Name=cases_param)["Parameter"][
                    "Value"
                ]
                cases_table = dynamodb.Table(cases_table_name)
                cases_table.update_item(
                    Key={"document_number": doc, "item_id": item_id},
                    UpdateExpression="SET ticket_id = :tid",
                    ExpressionAttributeValues={":tid": ticket["ticket_id"]},
                    ConditionExpression="attribute_exists(document_number)",
                )
        except Exception as e:
            logger.warning(f"Failed to write ticket_id to case {case_id}: {e}")

    return {"content": [{"type": "text", "text": json.dumps(ticket, default=str)}]}


def _update_ticket(event: dict) -> dict:
    ticket_id = event.get("ticket_id", "")
    if not ticket_id:
        return {"error": "ticket_id is required"}

    now = datetime.now(timezone.utc).isoformat()
    update_parts = ["updated_at = :ts"]
    expr_values = {":ts": now}
    expr_names = {}

    for key in ("status", "assigned_to", "priority", "resolution", "category"):
        if key in event:
            val = event[key]
            if key == "status" and val not in VALID_STATUSES:
                return {"error": f"Invalid status: {val}"}
            update_parts.append(f"#{key} = :{key}")
            expr_names[f"#{key}"] = key
            expr_values[f":{key}"] = val

    comment_text = event.get("comment", "").strip()
    if comment_text:
        comment = {
            "author": event.get("comment_author", "agent"),
            "text": comment_text,
            "timestamp": now,
        }
        update_parts.append(
            "comments = list_append(if_not_exists(comments, :empty), :comment)"
        )
        expr_values[":empty"] = []
        expr_values[":comment"] = [comment]

    table = _get_table()
    try:
        resp = table.update_item(
            Key={"ticket_id": ticket_id},
            UpdateExpression="SET " + ", ".join(update_parts),
            ExpressionAttributeNames=expr_names if expr_names else None,
            ExpressionAttributeValues=expr_values,
            ConditionExpression="attribute_exists(ticket_id)",
            ReturnValues="ALL_NEW",
        )
        return {
            "content": [
                {"type": "text", "text": json.dumps(resp["Attributes"], default=str)}
            ]
        }
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        return {"error": f"Ticket {ticket_id} not found"}


def _get_ticket(event: dict) -> dict:
    ticket_id = event.get("ticket_id", "")
    if not ticket_id:
        return {"error": "ticket_id is required"}

    resp = _get_table().get_item(Key={"ticket_id": ticket_id}, ConsistentRead=True)
    item = resp.get("Item")
    if not item:
        return {"content": [{"type": "text", "text": f"No ticket found: {ticket_id}"}]}
    return {"content": [{"type": "text", "text": json.dumps(item, default=str)}]}


def _list_tickets(event: dict) -> dict:
    scan_kwargs = {}
    filter_parts = []
    expr_names = {}
    expr_values = {}

    if event.get("status"):
        filter_parts.append("#s = :status")
        expr_names["#s"] = "status"
        expr_values[":status"] = event["status"]

    if event.get("assigned_to"):
        filter_parts.append("assigned_to = :assigned")
        expr_values[":assigned"] = event["assigned_to"]

    if filter_parts:
        scan_kwargs["FilterExpression"] = " AND ".join(filter_parts)
        if expr_names:
            scan_kwargs["ExpressionAttributeNames"] = expr_names
        scan_kwargs["ExpressionAttributeValues"] = expr_values

    items = _get_table().scan(**scan_kwargs).get("Items", [])
    items.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return {"content": [{"type": "text", "text": json.dumps(items, default=str)}]}


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
            "demo_update_ticket": _update_ticket,
            "demo_get_ticket": _get_ticket,
            "demo_list_tickets": _list_tickets,
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
