# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Ticket Management API Lambda

Simulates a ServiceNow-like ticketing system with its own DynamoDB table.
Used for demos: the agent creates/escalates tickets, a human approves or denies.

Routes:
  GET    /tickets              — list tickets (optional ?status=&assigned_to= filters)
  GET    /tickets/{id}         — get single ticket
  POST   /tickets              — create ticket
  PUT    /tickets/{id}         — update ticket (assign, approve, deny, add comment)
  POST   /tickets/{id}/action  — approve/deny/reply: update status + enqueue linked case
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

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
table = dynamodb.Table(os.environ["TICKETS_TABLE_NAME"])
sqs = boto3.client("sqs")
# Optional — only the /action route needs it; absent in deployments that never
# wire the agent queue.
QUEUE_URL = os.environ.get("AGENT_QUEUE_URL", "")
ALLOWED_ORIGINS = os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:3000")

VALID_STATUSES = {"open", "assigned", "approved", "denied", "replied", "closed"}
VALID_PRIORITIES = {"high", "medium", "low"}
# Keep in sync with types/tickets.schema.json (TicketStatus)
VALID_ACTIONS = {"approved", "denied", "replied"}


def _decimal_default(obj):
    if isinstance(obj, Decimal):
        return int(obj) if obj == int(obj) else float(obj)
    raise TypeError(f"Not serializable: {type(obj)}")


def _cors_headers(origin: str) -> dict:
    allowed = [o.strip() for o in ALLOWED_ORIGINS.split(",")]
    if origin in allowed:
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,POST,PUT,OPTIONS",
        }
    return {}


def _response(status_code: int, body: object, origin: str = "") -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json", **_cors_headers(origin)},
        "body": json.dumps(body, default=_decimal_default),
    }


def handler(event: dict, context: object) -> dict:
    method = event.get("httpMethod", "")
    path = event.get("path", "")
    origin = (event.get("headers") or {}).get("origin", "")
    params = event.get("pathParameters") or {}

    logger.info("Request: %s %s", method, path)

    try:
        ticket_id = params.get("id")

        if method == "POST" and ticket_id and path.endswith("/action"):
            return _action_ticket(ticket_id, event, origin)

        if method == "POST" and not ticket_id:
            return _create_ticket(event, origin)

        if method == "PUT" and ticket_id:
            return _update_ticket(ticket_id, event, origin)

        if method == "GET" and ticket_id:
            resp = table.get_item(Key={"ticket_id": ticket_id}, ConsistentRead=True)
            item = resp.get("Item")
            if not item:
                return _response(404, {"error": "Ticket not found"}, origin)
            return _response(200, item, origin)

        if method == "GET":
            return _list_tickets(event, origin)

        return _response(405, {"error": "Method not allowed"}, origin)

    except Exception as e:
        logger.exception("Tickets API error")
        return _response(500, {"error": str(e)}, origin)


def _create_ticket(event: dict, origin: str) -> dict:
    try:
        body = json.loads(event.get("body", "{}"))
    except json.JSONDecodeError:
        return _response(400, {"error": "Invalid JSON"}, origin)

    title = body.get("title", "").strip()
    if not title:
        return _response(400, {"error": "title is required"}, origin)

    now = datetime.now(timezone.utc).isoformat()
    ticket = {
        "ticket_id": f"TKT-{uuid.uuid4().hex[:8].upper()}",
        "title": title,
        "description": body.get("description", ""),
        "status": "open",
        "priority": body.get("priority", "medium")
        if body.get("priority") in VALID_PRIORITIES
        else "medium",
        "created_by": body.get("created_by", "agent"),
        "assigned_to": body.get("assigned_to", ""),
        "case_id": body.get("case_id", ""),
        "category": body.get("category", "general"),
        "response_type": body.get("response_type", "approval"),
        "resolution": "",
        "comments": [],
        "created_at": now,
        "updated_at": now,
    }

    validate_or_log(Ticket, ticket, context="demo_tickets.create")
    table.put_item(Item=ticket)
    return _response(201, ticket, origin)


def _update_ticket(ticket_id: str, event: dict, origin: str) -> dict:
    try:
        body = json.loads(event.get("body", "{}"))
    except json.JSONDecodeError:
        return _response(400, {"error": "Invalid JSON"}, origin)

    allowed = {"status", "assigned_to", "priority", "resolution", "category"}
    update_parts = ["updated_at = :ts"]
    expr_values: dict = {":ts": datetime.now(timezone.utc).isoformat()}
    expr_names: dict = {}

    for key in allowed:
        if key in body:
            val = body[key]
            if key == "status" and val not in VALID_STATUSES:
                return _response(400, {"error": f"Invalid status: {val}"}, origin)
            if key == "priority" and val not in VALID_PRIORITIES:
                return _response(400, {"error": f"Invalid priority: {val}"}, origin)
            update_parts.append(f"#{key} = :{key}")
            expr_names[f"#{key}"] = key
            expr_values[f":{key}"] = val

    comment_text = body.get("comment", "").strip()
    if comment_text:
        comment = {
            "author": body.get("comment_author", "system"),
            "text": comment_text,
            "timestamp": expr_values[":ts"],
        }
        update_parts.append(
            "comments = list_append(if_not_exists(comments, :empty), :comment)"
        )
        expr_values[":empty"] = []
        expr_values[":comment"] = [comment]

    try:
        resp = table.update_item(
            Key={"ticket_id": ticket_id},
            UpdateExpression="SET " + ", ".join(update_parts),
            ExpressionAttributeNames=expr_names if expr_names else None,
            ExpressionAttributeValues=expr_values,
            ConditionExpression="attribute_exists(ticket_id)",
            ReturnValues="ALL_NEW",
        )
        return _response(200, resp["Attributes"], origin)
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        return _response(404, {"error": "Ticket not found"}, origin)


def _list_tickets(event: dict, origin: str) -> dict:
    qs = event.get("queryStringParameters") or {}
    filter_parts = []
    expr_names = {}
    expr_values = {}

    if qs.get("status"):
        filter_parts.append("#s = :status")
        expr_names["#s"] = "status"
        expr_values[":status"] = qs["status"]

    if qs.get("assigned_to"):
        filter_parts.append("assigned_to = :assigned")
        expr_values[":assigned"] = qs["assigned_to"]

    scan_kwargs = {}
    if filter_parts:
        scan_kwargs["FilterExpression"] = " AND ".join(filter_parts)
        if expr_names:
            scan_kwargs["ExpressionAttributeNames"] = expr_names
        scan_kwargs["ExpressionAttributeValues"] = expr_values

    resp = table.scan(**scan_kwargs)
    items = resp.get("Items", [])
    items.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return _response(200, items, origin)


def _action_ticket(ticket_id: str, event: dict, origin: str) -> dict:
    """Approve/deny/reply: set the ticket status, then enqueue the linked case
    onto the agent SQS FIFO queue with an explicit 'ticket-action' trigger."""
    try:
        body = json.loads(event.get("body", "{}"))
    except json.JSONDecodeError:
        return _response(400, {"error": "Invalid JSON"}, origin)

    action = body.get("action", "")
    if action not in VALID_ACTIONS:
        return _response(
            400, {"error": f"action must be one of: {VALID_ACTIONS}"}, origin
        )

    resolution = body.get("resolution", f"{action.title()} by reviewer")
    comment = body.get("comment", f"Ticket {action} by user")
    response_text = body.get("response_text", "")

    now = datetime.now(timezone.utc).isoformat()
    try:
        resp = table.update_item(
            Key={"ticket_id": ticket_id},
            UpdateExpression=(
                "SET #s = :status, resolution = :res, updated_at = :ts, "
                "comments = list_append(if_not_exists(comments, :empty), :comment)"
            ),
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":status": action,
                ":res": resolution,
                ":ts": now,
                ":empty": [],
                ":comment": [{"author": "user", "text": comment, "timestamp": now}],
            },
            ConditionExpression="attribute_exists(ticket_id)",
            ReturnValues="ALL_NEW",
        )
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        return _response(404, {"error": "Ticket not found"}, origin)

    ticket = resp["Attributes"]
    case_id = ticket.get("case_id", "")

    enqueued = False
    if case_id and QUEUE_URL:
        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps(
                {
                    "case_id": case_id,
                    "trigger": "ticket-action",
                    "payload": {
                        "source": "ticket-action",
                        "ticket_id": ticket_id,
                        "ticket_decision": action,
                        "resolution": resolution,
                        **({"response_text": response_text} if response_text else {}),
                    },
                }
            ),
            MessageGroupId=case_id,
        )
        enqueued = True
        logger.info("Enqueued case=%s after ticket %s %s", case_id, ticket_id, action)

    return _response(
        200, {"ticket": ticket, "enqueued": enqueued, "case_id": case_id}, origin
    )
