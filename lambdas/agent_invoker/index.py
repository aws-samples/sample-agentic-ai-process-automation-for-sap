# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Agent Invoker Lambda

Consumes from the agent-invocations SQS FIFO queue and invokes the
Bedrock AgentCore agent. SQS event source mapping maxConcurrency
controls how many agents run in parallel (default 5).

Each message contains:
  { "case_id": "4500012345-00010", "trigger": "poller|webhook-*|manual|batch",
    "payload": { ... optional context from webhook ... },
    "username": "..." }    // optional

``case_id`` is the canonical identity from the ``case_key`` codec. The webhook path
may legitimately send an empty one when it cannot resolve a case from inbound
content; the agent then resolves it itself.
"""

import base64
import codecs
import json
import logging
import os
import time
import urllib.parse
import urllib.request
import uuid

import boto3

# Canonical case identity codec — ships in the shared_types layer.
from case_key import CaseKeyError, to_case_key, try_normalize_case_id

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ssm = boto3.client("ssm")
secrets = boto3.client("secretsmanager")
dynamodb = boto3.resource("dynamodb")

STACK_NAME = os.environ["STACK_NAME_BASE"]
TABLE_NAME = os.environ.get("CASES_TABLE", "")

# Silence longer than a few of the agent's 15s keepalive comments means the stream is
# dead rather than slow. This is a per-read socket timeout, not a run budget.
_IDLE_TIMEOUT_SECONDS = 60
# Headroom left inside the Lambda's remaining time to record a status and return a
# batch failure before the runtime kills the process.
_DEADLINE_MARGIN_SECONDS = 20
_MIN_RUN_BUDGET_SECONDS = 30
# Used only when no invocation context is available, e.g. under direct test calls.
_FALLBACK_RUN_BUDGET_SECONDS = 840
_READ_CHUNK_BYTES = 65536
# Long enough that a terminal marker split across two reads is still matched.
_MARKER_TAIL_CHARS = 64
# RUN_ERROR codes the agent uses for deliberate processing-limit stops. Retrying
# reruns the same work and can repeat tool side effects, so these go to review.
_DELIBERATE_STOP_CODES = ("MAX_TURNS_REACHED", "MAX_TOKENS_REACHED")
# A normally ended agent stream is safe to acknowledge only when the case reached one
# of these schema-defined outcomes. ``sap_updated`` is included because retrying after
# a recorded ERP side effect risks applying it twice.
_BUSINESS_TERMINAL_STATUSES = frozenset(
    {"awaiting_human_input", "complete", "manual_review_required", "sap_updated"}
)


def handler(event, context):
    """Process one SQS message (event source mapping is pinned to batchSize=1)."""
    records = event.get("Records", [])
    if not records:
        return {}
    record = records[0]
    table = dynamodb.Table(TABLE_NAME) if TABLE_NAME else None
    msg_id = record["messageId"]
    case_id = ""
    case_key = None
    trigger = "unknown"
    try:
        body = json.loads(record["body"])
        raw_case_id = body["case_id"]
        # Normalize once, here, so every status write and the forwarded payload use
        # one representation. An empty id is expected from the webhook path; a
        # non-empty one we cannot parse is a producer bug worth surfacing.
        case_id = try_normalize_case_id(raw_case_id) or ""
        if raw_case_id and not case_id:
            logger.warning(f"Unparseable case_id from producer: {raw_case_id!r}")
        case_key = to_case_key(case_id) if case_id else None
        trigger = body.get("trigger", "unknown")
        payload = body.get("payload", {})

        logger.info(f"Processing case={case_id or '(unresolved)'} trigger={trigger}")

        if table and case_key:
            _update_status(table, case_key, "processing", trigger)

        # UI messages carry the Cognito username; forwarded to AgentCore so
        # SAP requests are attributed to the actual user, not a service account.
        username = body.get("username", "")

        # The prompt is built agent-side by _build_prompt, which fences and
        # sanitizes webhook content and appends the SOP instruction for a plain
        # case. Sending a prompt here would instead be taken as an explicit user
        # message — the enqueue integration stamps trigger="manual" — and would strip
        # that instruction from every enqueued case.
        agent_payload = {
            "case_id": case_id,
            "trigger": trigger,
            "payload": payload,
        }
        result = _invoke_agent(agent_payload, username=username, context=context)
        terminal = result["terminal"]

        if terminal == "RUN_FINISHED":
            business_status = _verify_business_outcome(table, case_id, trigger)
            if business_status:
                logger.info(
                    f"Agent completed case={case_id} business_status={business_status}"
                )
            else:
                # This is reachable only in tests or a deployment without a cases table.
                # Keep the transport-compatible behavior, but do not claim business
                # success when there was no persisted case to verify.
                logger.warning(
                    f"Agent stream finished case={case_id}; "
                    "business outcome was not verified"
                )
        elif terminal in _DELIBERATE_STOP_CODES:
            # The agent stopped at a deterministic processing limit. Retrying can
            # replay already-completed tool side effects, so send it straight to a
            # human instead of spending the redrive budget.
            logger.warning(
                f"Agent stopped at its processing limit ({terminal}) for case={case_id}; "
                f"routing to manual review without retry"
            )
            if table and case_key:
                _update_status(table, case_key, "manual_review_required", trigger)
        else:
            # HTTP 200 with no successful terminal event. Raise so the existing
            # redrive path applies rather than deleting the message and leaving the
            # case stuck in "processing" forever.
            raise RuntimeError(
                f"agent run did not complete for case={case_id}: terminal={terminal}"
            )

    except Exception as e:
        logger.error(f"Failed msg={msg_id}: {e}")
        # Last retry: flag for manual review instead of leaving the case stuck in "processing".
        receive_count = int(
            record.get("attributes", {}).get("ApproximateReceiveCount", "1")
        )
        if table and case_key and receive_count >= 3:
            _update_status(table, case_key, "manual_review_required", trigger)
            logger.warning(
                f"Case {case_id} moved to manual_review_required after {receive_count} failures"
            )
        return {"batchItemFailures": [{"itemIdentifier": msg_id}]}

    return {}


def _verify_business_outcome(table, case_id: str, trigger: str) -> str | None:
    """Verify the persisted ERP outcome after a normally completed AG-UI stream.

    ``RUN_FINISHED`` means the transport/model loop ended normally; it does not mean
    the ERP workflow succeeded. A completed stream must not be blindly retried after
    possible SAP side effects, so a present case in any nonterminal or invalid state is
    routed to manual review. Failure to read the case is different: without a durable
    outcome there is nothing safe to acknowledge, so the caller redrives the message.
    """
    if not table:
        return None
    try:
        key = to_case_key(case_id)
    except CaseKeyError:
        # No resolvable case (webhook path may not have one) — nothing to verify.
        return None

    response = table.get_item(
        Key=key,
        ConsistentRead=True,
        ProjectionExpression="#s",
        ExpressionAttributeNames={"#s": "status"},
    )
    case = response.get("Item")
    if case is None:
        raise RuntimeError(f"cannot verify business outcome; case not found: {case_id}")

    status = case.get("status")
    if status in _BUSINESS_TERMINAL_STATUSES:
        return status

    observed = repr(status) if status is not None else "missing"
    reason = (
        "Agent stream finished without a safe terminal case state; "
        f"observed status={observed}."
    )
    logger.warning(f"{reason} Routing case={case_id} to manual review without retry")
    if not _update_status(
        table,
        key,
        "manual_review_required",
        trigger,
        reason=reason,
    ):
        raise RuntimeError(
            f"cannot record manual review after unverified business outcome: {case_id}"
        )
    return "manual_review_required"


def _update_status(
    table,
    case_key: dict,
    status: str,
    trigger: str,
    *,
    reason: str | None = None,
) -> bool:
    """Update case status in DynamoDB and report whether it was persisted.

    ``case_key`` is the DynamoDB key from ``to_case_key(case_id)`` — callers no
    longer split an id apart to build it.
    """
    try:
        from datetime import datetime, timezone

        update_expression = "SET #s = :s, updated_at = :t"
        expression_values = {
            ":s": status,
            ":t": datetime.now(timezone.utc).isoformat(),
        }
        if reason:
            update_expression += ", status_reason = :r"
            expression_values[":r"] = reason

        table.update_item(
            Key=case_key,
            UpdateExpression=update_expression,
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues=expression_values,
            ConditionExpression="attribute_exists(case_id)",
        )
        return True
    except Exception as e:
        logger.warning(f"Status update failed for {case_key}: {e}")
        return False


def _invoke_agent(payload: dict, *, username: str = "", context=None) -> dict:
    """Invoke AgentCore over AG-UI with a Cognito bearer token and optional identity.

    Returns the run's terminal outcome so the caller can decide whether the case was
    actually processed. Raises on transport failure or on exceeding the run budget.
    """
    deadline = _run_deadline(context)
    region = os.environ.get("AWS_REGION", "us-east-1")
    agent_arn = ssm.get_parameter(Name=f"/{STACK_NAME}/runtime-arn")["Parameter"][
        "Value"
    ]
    escaped = urllib.parse.quote(agent_arn, safe="")
    url = f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{escaped}/invocations?qualifier=DEFAULT"

    token = _get_token(region)
    # Queued invocations are isolated transport/Memory turns. Reusing a completed
    # case-derived Runtime session can make a later ticket-action callback return
    # RUN_FINISHED without executing a model or tool turn. Keep canonical case identity
    # in forwardedProps.erpPayload and use one disposable session for both AG-UI and
    # the Runtime header on every delivery.
    session_id = f"sqs-{int(time.time())}-{uuid.uuid4().hex}"
    run_id = str(uuid.uuid4())

    # The Runtime serves the AG-UI contract, so the request body must be a well-formed
    # RunAgentInput. The ERP fields travel in forwardedProps.erpPayload, which is where
    # the agent reads them from; the prompt is also placed in the AG-UI message history.
    # The agent rewrites the last user message with its own built prompt, so this
    # content is a readable reference rather than the instruction itself.
    agui_input = {
        "threadId": session_id,
        "runId": run_id,
        # RunAgentInput requires the key; nothing reads it back, so it carries no
        # duplicate of the caseId/trigger already in forwardedProps.erpPayload.
        "state": None,
        "messages": [
            {
                "id": f"input-{run_id}",
                "role": "user",
                "content": f"Process ERP exception case {payload.get('case_id', '')}".strip(),
            }
        ],
        "tools": [],
        "context": [],
        "forwardedProps": {"erpPayload": payload},
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
    }
    # AgentCore forwards this header to Gateway tools via bedrockAgentCorePropagatedHeaders.
    if username:
        headers["x-user-identity"] = username

    req = urllib.request.Request(
        url,
        data=json.dumps(agui_input).encode(),
        method="POST",
        headers=headers,
    )
    # urllib's timeout is a SOCKET timeout applied per blocking read, not a budget for
    # the whole run — a stream that keeps producing never trips it. The agent emits a
    # keepalive comment every 15s, so silence beyond a few heartbeats means the stream
    # is dead, and that is what this value detects. The total budget is enforced
    # separately against the Lambda's own remaining time.
    with urllib.request.urlopen(  # nosec B310 — URL built from trusted config  # nosemgrep: dynamic-urllib-use-detected
        req, timeout=_IDLE_TIMEOUT_SECONDS
    ) as resp:
        status = resp.status
        byte_count, terminal = _drain_stream(resp, deadline=deadline)

    # HTTP 200 covers both a completed and a failed run, so the terminal event is the
    # only signal that separates them. The caller acts on it.
    logger.info(
        f"Agent response: {status} ({byte_count} bytes) run={run_id} terminal={terminal}"
    )
    return {"terminal": terminal}


def _run_deadline(context) -> float:
    """A monotonic deadline for the whole run, derived from the Lambda's own budget.

    Taken from the invocation context rather than a constant so it tracks the
    configured timeout instead of duplicating it, and leaves margin to record a
    status and return a batch failure before the runtime kills the process.
    """
    remaining_ms = None
    if context is not None and hasattr(context, "get_remaining_time_in_millis"):
        try:
            remaining_ms = context.get_remaining_time_in_millis()
        except Exception:  # nosec B110 — a missing budget falls back below
            remaining_ms = None
    if not remaining_ms:
        return time.monotonic() + _FALLBACK_RUN_BUDGET_SECONDS
    budget = max(
        remaining_ms / 1000.0 - _DEADLINE_MARGIN_SECONDS, _MIN_RUN_BUDGET_SECONDS
    )
    return time.monotonic() + budget


def _drain_stream(resp, *, deadline: float) -> tuple[int, str]:
    """Consume the AG-UI stream, reporting size and terminal outcome.

    Nothing downstream replays the events, so the body is scanned as it arrives and
    discarded rather than buffered — an agent response can reach hundreds of
    megabytes. Only a short tail is retained so a marker split across two reads is
    still matched.

    Returns (bytes read, terminal outcome: "RUN_FINISHED" / "RUN_ERROR" /
    a value from _DELIBERATE_STOP_CODES / "none").
    """
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    byte_count = 0
    seen: set[str] = set()
    tail = ""

    while True:
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"agent run exceeded its budget after {byte_count} bytes; "
                f"terminal event not yet seen"
            )
        chunk = resp.read(_READ_CHUNK_BYTES)
        if not chunk:
            break
        byte_count += len(chunk)
        text = tail + decoder.decode(chunk)
        for marker in ("RUN_ERROR", "RUN_FINISHED", *_DELIBERATE_STOP_CODES):
            if f'"{marker}"' in text:
                seen.add(marker)
        tail = text[-_MARKER_TAIL_CHARS:]

    # A deliberate stop is a RUN_ERROR subtype, and a failure outranks a completion:
    # a stream reporting both is not a success.
    terminal = next(
        (code for code in _DELIBERATE_STOP_CODES if code in seen),
        "RUN_ERROR"
        if "RUN_ERROR" in seen
        else "RUN_FINISHED"
        if "RUN_FINISHED" in seen
        else "none",
    )
    return byte_count, terminal


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
