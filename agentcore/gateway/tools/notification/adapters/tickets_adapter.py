# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tickets adapter — creates a ticket in the tickets DynamoDB table."""

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


dynamodb = boto3.resource("dynamodb")
ssm = boto3.client("ssm")
_table = None

SSM_PARAM = os.environ.get(
    "TICKETS_TABLE_SSM_PARAM",
    "/erp-accrual-agent/dynamodb/tickets-table",
)


def _get_table():
    global _table
    if _table is None:
        name = ssm.get_parameter(Name=SSM_PARAM)["Parameter"]["Value"]
        _table = dynamodb.Table(name)
    return _table


def send(
    *,
    recipient: str,
    subject: str,
    body: str,
    case_id: str | None = None,
    priority: str = "medium",
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    ticket = {
        "ticket_id": f"TKT-{uuid.uuid4().hex[:8].upper()}",
        "title": subject or "Agent Notification",
        "description": body,
        "status": "open",
        "priority": priority if priority in {"high", "medium", "low"} else "medium",
        "created_by": "agent",
        "assigned_to": recipient,
        "case_id": case_id or "",
        "category": "agent_notification",
        "resolution": "",
        "comments": [],
        "created_at": now,
        "updated_at": now,
    }
    validate_or_log(Ticket, ticket, context="notification.tickets")
    _get_table().put_item(Item=ticket)
    return {
        "channel": "tickets",
        "ticket_id": ticket["ticket_id"],
        "assigned_to": recipient,
        "timestamp": now,
    }
