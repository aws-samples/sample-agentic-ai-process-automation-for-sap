# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Cases API Lambda

DynamoDB queries for the cases dashboard + trace persistence.
Routes:
  GET  /cases              — list/filter cases
  GET  /cases/{doc}/{item}  — single case detail
  POST /cases/{doc}/{item}/traces — append an agent trace to a case
"""

import json
import logging
import os
from decimal import Decimal

import boto3

# Canonical case identity codec — ships in the shared_types layer.
from case_key import CaseKeyError, to_case_key

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

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["TABLE_NAME"])
ALLOWED_ORIGINS = os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:3000")


def _decimal_default(obj: object) -> float | int:
    """JSON serializer for Decimal types from DynamoDB."""
    if isinstance(obj, Decimal):
        return int(obj) if obj == int(obj) else float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _cors_headers(origin: str) -> dict[str, str]:
    """Return CORS headers if origin is allowed."""
    allowed = [o.strip() for o in ALLOWED_ORIGINS.split(",")]
    if origin in allowed:
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,POST,PUT,OPTIONS",
        }
    return {}


def _response(status_code: int, body: object, origin: str = "") -> dict:
    """Build API Gateway proxy response."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            **_cors_headers(origin),
        },
        "body": json.dumps(body, default=_decimal_default),
    }


def handler(event: dict, context: object) -> dict:
    """Lambda handler for cases API."""
    method = event.get("httpMethod", "")
    path = event.get("path", "")
    origin = (event.get("headers") or {}).get("origin", "")
    params = event.get("pathParameters") or {}

    logger.info("Request: %s %s", method, path)

    try:
        # A malformed identity is a 400 here rather than a miss further in: the
        # codec is the only thing that turns a path parameter into a table key.
        raw_case_id = params.get("case_id")
        case_key = None
        if raw_case_id:
            try:
                case_key = to_case_key(raw_case_id)
            except CaseKeyError:
                return _response(400, {"error": "Invalid case_id"}, origin)

        if method == "PUT" and case_key and path.endswith("/rating"):
            return _save_rating(case_key, event, origin)

        if method == "POST" and case_key and path.endswith("/traces"):
            return _save_trace(case_key, event, origin)

        if case_key:
            resp = table.get_item(Key=case_key, ConsistentRead=True)
            item = resp.get("Item")
            if not item:
                return _response(404, {"error": "Case not found"}, origin)
            validate_or_log(WorkItem, item, context="cases_api.get")
            return _response(200, item, origin)

        # GET /cases
        qs = event.get("queryStringParameters") or {}
        status_filter = qs.get("status")
        domain_filter = qs.get("domain")

        items = []

        if domain_filter and status_filter:
            resp = table.query(
                IndexName="domain-status-index",
                KeyConditionExpression="#d = :domain AND #s = :status",
                ExpressionAttributeNames={"#d": "domain", "#s": "status"},
                ExpressionAttributeValues={
                    ":domain": domain_filter,
                    ":status": status_filter,
                },
            )
            items = resp.get("Items", [])
        elif domain_filter:
            resp = table.query(
                IndexName="domain-status-index",
                KeyConditionExpression="#d = :domain",
                ExpressionAttributeNames={"#d": "domain"},
                ExpressionAttributeValues={":domain": domain_filter},
            )
            items = resp.get("Items", [])
        elif status_filter:
            resp = table.query(
                IndexName="status-index",
                KeyConditionExpression="#s = :status",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":status": status_filter},
            )
            items = resp.get("Items", [])
        else:
            resp = table.scan()
            items = resp.get("Items", [])
            while "LastEvaluatedKey" in resp:
                resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
                items.extend(resp.get("Items", []))
        items.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return _response(200, items, origin)

    except Exception as e:
        logger.exception("Cases API error")
        return _response(500, {"error": str(e)}, origin)


def _save_trace(case_key: dict, event: dict, origin: str) -> dict:
    """Append an agent trace to a case's agent_traces list in DynamoDB."""
    try:
        body = json.loads(event.get("body", "{}"))
    except json.JSONDecodeError:
        return _response(400, {"error": "Invalid JSON body"}, origin)

    if not body.get("trace_id") or not body.get("segments"):
        return _response(400, {"error": "trace_id and segments are required"}, origin)

    try:
        table.update_item(
            Key=case_key,
            UpdateExpression="SET agent_traces = list_append(if_not_exists(agent_traces, :empty), :trace)",
            ExpressionAttributeValues={
                ":empty": [],
                ":trace": [body],
            },
            ConditionExpression="attribute_exists(case_id)",
        )
        return _response(200, {"saved": True, "trace_id": body["trace_id"]}, origin)
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        return _response(404, {"error": "Case not found"}, origin)


def _save_rating(case_key: dict, event: dict, origin: str) -> dict:
    """Save a case-level resolution rating."""
    try:
        body = json.loads(event.get("body", "{}"))
    except json.JSONDecodeError:
        return _response(400, {"error": "Invalid JSON body"}, origin)

    rating = body.get("rating")
    if rating not in ("positive", "negative"):
        return _response(
            400, {"error": "rating must be 'positive' or 'negative'"}, origin
        )

    from datetime import datetime, timezone

    update_expr = "SET user_rating = :r, user_rating_at = :ts"
    expr_values: dict = {
        ":r": rating,
        ":ts": datetime.now(timezone.utc).isoformat(),
    }

    comment = body.get("comment")
    if comment:
        update_expr += ", user_rating_comment = :c"
        expr_values[":c"] = comment[:5000]

    try:
        table.update_item(
            Key=case_key,
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_values,
            ConditionExpression="attribute_exists(case_id)",
        )
        return _response(200, {"saved": True, "rating": rating}, origin)
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        return _response(404, {"error": "Case not found"}, origin)
