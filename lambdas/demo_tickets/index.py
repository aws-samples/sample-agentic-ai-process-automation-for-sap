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

# Canonical case identity codec — ships in the shared_types layer. Ticket
# correlation and the agent resume message both key on a case_id, so it is
# imported unconditionally.
from case_key import try_normalize_case_id

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


def _reviewer_identity(event: dict) -> str | None:
    """Return a human-readable identity from the trusted authorizer context."""
    authorizer = (event.get("requestContext") or {}).get("authorizer") or {}
    claims = authorizer.get("claims") or authorizer
    for key in (
        "email",
        "preferred_username",
        "cognito:username",
        "username",
        "upn",
        "sub",
        "principalId",
    ):
        value = claims.get(key)
        if value:
            return str(value).strip()[:256]
    return None


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

    response_type = body.get("response_type", "approval")
    if response_type not in VALID_RESPONSE_TYPES:
        return _response(
            400,
            {"error": f"response_type must be one of: {sorted(VALID_RESPONSE_TYPES)}"},
            origin,
        )

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
        # Store the canonical form so the tickets UI can filter on, and the
        # resume path can route by, one representation. An id we cannot parse is
        # dropped rather than stored in a shape nothing else understands.
        "case_id": try_normalize_case_id(body.get("case_id")) or "",
        "category": body.get("category", "general"),
        "response_type": response_type,
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
        reviewer = _reviewer_identity(event)
        if not reviewer:
            return _response(
                401, {"error": "Authenticated reviewer is required"}, origin
            )
        comment = {
            "author": reviewer,
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
    """Validate a human response, persist it, and resume the linked case."""
    try:
        body = json.loads(event.get("body", "{}"))
    except json.JSONDecodeError:
        return _response(400, {"error": "Invalid JSON"}, origin)

    action = body.get("action", "")
    if action not in VALID_ACTIONS:
        return _response(
            400, {"error": f"action must be one of: {sorted(VALID_ACTIONS)}"}, origin
        )
    if not QUEUE_URL:
        return _response(503, {"error": "Agent resume queue is unavailable"}, origin)

    reviewer = _reviewer_identity(event)
    if not reviewer:
        return _response(401, {"error": "Authenticated reviewer is required"}, origin)

    current = table.get_item(Key={"ticket_id": ticket_id}, ConsistentRead=True).get(
        "Item"
    )
    if not current:
        return _response(404, {"error": "Ticket not found"}, origin)

    current_status = current.get("status", "open")
    decided_statuses = {"approved", "denied", "replied"}
    if current_status == "closed":
        return _response(409, {"error": "Ticket is already closed"}, origin)
    if current_status in decided_statuses and action != current_status:
        return _response(
            409,
            {
                "error": (
                    f"Ticket already has decision {current_status}; "
                    f"cannot change it to {action}"
                )
            },
            origin,
        )
    if current_status not in {"open", "assigned", *decided_statuses}:
        return _response(
            409, {"error": f"Ticket has unsupported status: {current_status}"}, origin
        )

    response_type = current.get("response_type", "approval")
    if response_type not in VALID_RESPONSE_TYPES:
        return _response(
            409,
            {"error": f"Ticket has unsupported response_type: {response_type}"},
            origin,
        )

    response_text = body.get("response_text", "")
    if not isinstance(response_text, str):
        return _response(400, {"error": "response_text must be a string"}, origin)
    response_text = response_text.strip()

    if response_type == "free_text":
        if action != "replied":
            return _response(
                400,
                {"error": "This ticket requires a free-text reply"},
                origin,
            )
        if not response_text:
            return _response(400, {"error": "response_text is required"}, origin)
        response_text = response_text[:5000]
    elif action not in {"approved", "denied"}:
        return _response(
            400,
            {"error": "This ticket requires an approve or deny decision"},
            origin,
        )

    # Tickets created before the canonical form existed still hold `doc#item`;
    # normalize so the resume message and its FIFO group match every other
    # producer for this case.
    case_id = try_normalize_case_id(current.get("case_id"))
    if not case_id:
        return _response(409, {"error": "Ticket is not linked to a case"}, origin)

    default_resolution = (
        response_text if action == "replied" else f"{action.title()} by reviewer"
    )
    resolution = body.get("resolution") or default_resolution
    comment = body.get("comment") or default_resolution

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
                ":comment": [{"author": reviewer, "text": comment, "timestamp": now}],
            },
            ConditionExpression="attribute_exists(ticket_id)",
            ReturnValues="ALL_NEW",
        )
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        return _response(404, {"error": "Ticket not found"}, origin)

    ticket = resp["Attributes"]
    message_payload = {
        "source": "ticket-action",
        "ticket_id": ticket_id,
        "ticket_decision": action,
        "resolution": resolution,
        **({"response_text": response_text} if response_text else {}),
    }
    sqs.send_message(
        QueueUrl=QUEUE_URL,
        MessageBody=json.dumps(
            {
                "case_id": case_id,
                "trigger": "ticket-action",
                "payload": message_payload,
            }
        ),
        MessageGroupId=case_id,
    )
    logger.info("Enqueued case=%s after ticket %s %s", case_id, ticket_id, action)

    return _response(
        200, {"ticket": ticket, "enqueued": True, "case_id": case_id}, origin
    )
