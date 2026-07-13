# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Pluggable Notification Gateway Tool Lambda

Dispatches send_notification calls to the configured channel adapter.
Channel is set via NOTIFICATION_CHANNEL env var (ses/servicenow/jira/slack).
Credentials come from Secrets Manager via NOTIFICATION_SECRET env var.
"""

import json
import logging
import os

logger = logging.getLogger()
logger.setLevel(logging.INFO)

CHANNEL = os.environ.get("NOTIFICATION_CHANNEL", "ses")


def _get_adapter():
    """Lazy-import the channel adapter."""
    if CHANNEL == "ses":
        from adapters import ses_adapter as mod
    elif CHANNEL == "servicenow":
        from adapters import servicenow_adapter as mod
    elif CHANNEL == "jira":
        from adapters import jira_adapter as mod
    elif CHANNEL == "slack":
        from adapters import slack_adapter as mod
    elif CHANNEL == "tickets":
        from adapters import tickets_adapter as mod
    else:
        raise ValueError(f"Unknown notification channel: {CHANNEL}")
    return mod


def _resolve_tool_name(context) -> str:
    """Return the bare tool name, asserting the call came through the Gateway.

    The AgentCore Gateway sets ``bedrockAgentCoreToolName`` in the Lambda client
    context after evaluating Cedar authorization. A direct invocation that
    bypasses the Gateway (confused-deputy, threat T14) won't carry this marker,
    so we reject it rather than executing unauthorized.
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
    logger.info(f"Event: {json.dumps(event)}")

    try:
        tool_name = _resolve_tool_name(context)

        if tool_name != "send_notification":
            return {"error": f"Unknown tool: {tool_name}"}

        adapter = _get_adapter()
        result = adapter.send(
            recipient=event.get("recipient", ""),
            subject=event.get("subject", ""),
            body=event.get("body", ""),
            case_id=event.get("case_id"),
            priority=event.get("priority", "medium"),
        )
        return {"content": [{"type": "text", "text": json.dumps(result)}]}

    except PermissionError as e:
        logger.warning(f"Rejected unauthorized invocation: {e}")
        return {
            "error": "Unauthorized: calls must originate from the AgentCore Gateway"
        }
    except Exception as e:
        logger.error(f"Error: {e}")
        return {"error": f"Notification failed: {type(e).__name__}"}
