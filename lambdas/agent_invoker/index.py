# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Agent Invoker Lambda

Consumes from the agent-invocations SQS FIFO queue and invokes the
Bedrock AgentCore agent. SQS event source mapping maxConcurrency
controls how many agents run in parallel (default 5).

Each message contains:
  { "case_id": "4500012345#00010", "trigger": "poller|webhook|ui",
    "payload": { ... optional context from webhook ... },
    "username": "..." }    // optional
"""

import base64
import json
import logging
import os
import time
import urllib.parse
import urllib.request
import uuid

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ssm = boto3.client("ssm")
secrets = boto3.client("secretsmanager")
dynamodb = boto3.resource("dynamodb")

STACK_NAME = os.environ["STACK_NAME_BASE"]
TABLE_NAME = os.environ.get("CASES_TABLE", "")


def handler(event, context):
    """Process SQS batch (typically 1 message due to FIFO + maxConcurrency)."""
    table = dynamodb.Table(TABLE_NAME) if TABLE_NAME else None
    failures = []

    for record in event.get("Records", []):
        msg_id = record["messageId"]
        try:
            body = json.loads(record["body"])
            case_id = body["case_id"]
            trigger = body.get("trigger", "unknown")
            payload = body.get("payload", {})

            logger.info(f"Processing case={case_id} trigger={trigger}")

            if table and "#" in case_id:
                doc, item = case_id.split("#", 1)
                _update_status(table, doc, item, "processing", trigger)

            # UI messages carry the Cognito username; forwarded to AgentCore so
            # SAP requests are attributed to the actual user, not a service account.
            username = body.get("username", "")

            message = payload.get("message", "")
            sender = payload.get("sender", "")
            subject = payload.get("subject", "")
            if trigger.startswith("webhook-") and message:
                prompt = (
                    f"An inbound message was received for case {case_id}.\n"
                    f"From: {sender}\n"
                    f"Subject: {subject}\n"
                    f"Message:\n{message}\n\n"
                    f"Retrieve the current case state, understand where the case is in the workflow, "
                    f"and continue processing according to the SOP."
                )
            else:
                doc_num = case_id.split("#")[0] if "#" in case_id else case_id
                item_id = case_id.split("#")[1] if "#" in case_id else "10"
                prompt = f"Process ERP exception case: document_number={doc_num}, item_id={item_id}"

            agent_payload = {
                "prompt": prompt,
                "case_id": case_id,
                "trigger": trigger,
                "payload": payload,
            }
            _invoke_agent(agent_payload, username=username)

            logger.info(f"Agent invoked for case={case_id}")

        except Exception as e:
            logger.error(f"Failed msg={msg_id}: {e}")
            # Last retry: flag for manual review instead of leaving the case stuck in "processing".
            receive_count = int(
                record.get("attributes", {}).get("ApproximateReceiveCount", "1")
            )
            if table and "#" in case_id and receive_count >= 3:
                _update_status(
                    table, *case_id.split("#", 1), "manual_review_required", trigger
                )
                logger.warning(
                    f"Case {case_id} moved to manual_review_required after {receive_count} failures"
                )
            failures.append({"itemIdentifier": msg_id})

    if failures:
        return {"batchItemFailures": failures}
    return {}


def _update_status(table, doc: str, item: str, status: str, trigger: str):
    """Update case status in DynamoDB."""
    try:
        from datetime import datetime, timezone

        table.update_item(
            Key={"document_number": doc, "item_id": item},
            UpdateExpression="SET #s = :s, updated_at = :t",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":s": status,
                ":t": datetime.now(timezone.utc).isoformat(),
            },
            ConditionExpression="attribute_exists(document_number)",
        )
    except Exception as e:
        logger.warning(f"Status update failed for {doc}#{item}: {e}")


def _invoke_agent(payload: dict, *, username: str = ""):
    """Invoke AgentCore with Cognito bearer token and optional user identity."""
    region = os.environ.get("AWS_REGION", "us-east-1")
    agent_arn = ssm.get_parameter(Name=f"/{STACK_NAME}/runtime-arn")["Parameter"][
        "Value"
    ]
    escaped = urllib.parse.quote(agent_arn, safe="")
    url = f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{escaped}/invocations?qualifier=DEFAULT"

    token = _get_token(region)
    session_id = f"sqs-{int(time.time())}-{uuid.uuid4().hex}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
    }
    # AgentCore forwards this header to Gateway tools via bedrockAgentCorePropagatedHeaders.
    if username:
        headers["x-user-identity"] = username

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=300) as resp:  # nosec B310 — URL built from trusted config  # nosemgrep: dynamic-urllib-use-detected
        logger.info(f"Agent response: {resp.status} ({len(resp.read())} bytes)")


_cached_token = None
_token_expiry = 0


def _get_token(region: str) -> str:
    """Get access token using OAuth2 client credentials flow with machine client."""
    global _cached_token, _token_expiry
    if _cached_token and time.time() < _token_expiry:
        return _cached_token

    machine_client_id = ssm.get_parameter(Name=f"/{STACK_NAME}/machine_client_id")[
        "Parameter"
    ]["Value"]
    client_secret = secrets.get_secret_value(
        SecretId=f"/{STACK_NAME}/machine_client_secret"
    )["SecretString"]
    cognito_domain = ssm.get_parameter(Name=f"/{STACK_NAME}/cognito_provider")[
        "Parameter"
    ]["Value"]

    token_url = f"https://{cognito_domain}/oauth2/token"
    auth_header = base64.b64encode(
        f"{machine_client_id}:{client_secret}".encode()
    ).decode()

    data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    req = urllib.request.Request(
        token_url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310 — URL from trusted SSM config  # nosemgrep: dynamic-urllib-use-detected
        token_data = json.loads(resp.read())
    _cached_token = token_data["access_token"]
    _token_expiry = time.time() + 3000  # ~50 min (tokens last 60 min)
    return _cached_token
