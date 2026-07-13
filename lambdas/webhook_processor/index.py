# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Webhook Processor Lambda

Unified inbound processor for all notification channels.
Receives events from SES (raw email via S3), Slack, Jira, or ServiceNow.
Normalizes into a standard payload and enqueues to the agent invocation
queue (SQS FIFO).

Frontend batch enqueue uses a direct API Gateway → SQS integration
(no Lambda in the path). This Lambda handles only external webhooks
and SES inbound email.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
import uuid

import boto3
import mailparser
from email_reply_parser import EmailReplyParser

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
sqs = boto3.client("sqs")

CHANNEL = os.environ.get("NOTIFICATION_CHANNEL", "ses")
QUEUE_URL = os.environ.get("AGENT_QUEUE_URL", "")

# Read webhook signing secret from Secrets Manager at cold start (same secret
# that holds outbound channel credentials). Avoids plaintext in env vars.
_NOTIFICATION_SECRET_ARN = os.environ.get("NOTIFICATION_SECRET", "")
WEBHOOK_SECRET = ""
if _NOTIFICATION_SECRET_ARN:
    try:
        _secret = boto3.client("secretsmanager").get_secret_value(
            SecretId=_NOTIFICATION_SECRET_ARN
        )
        WEBHOOK_SECRET = json.loads(_secret["SecretString"]).get("webhook_secret", "")
    except Exception as e:
        logger.warning(f"Could not read webhook_secret from Secrets Manager: {e}")

# Lightweight injection pattern filter — strips obvious prompt injection
# attempts at ingestion time before content reaches the agent.
_INJECTION_RE = re.compile(
    r"(?i)"
    r"(?:ignore\s+(?:all\s+)?previous\s+instructions)"
    r"|(?:disregard\s+(?:all\s+)?(?:previous|above|prior)\s+instructions)"
    r"|(?:you\s+are\s+now\s+a\b)"
    r"|(?:(?:^|\n)\s*system\s*:)"
    r"|(?:<\s*/?\s*system\s*>)"
    r"|(?:(?:^|\n)\s*(?:ASSISTANT|HUMAN)\s*:)"
    r"|(?:(?:^|\n)\s*\[INST\])"
    r"|(?:<\s*/?\s*(?:external_data|sop_document)\s*>)",
    re.MULTILINE,
)


def _sanitize(text: str, source: str = "unknown") -> str:
    """Strip obvious prompt injection patterns from inbound content."""
    if not text:
        return text
    cleaned = _INJECTION_RE.sub("[FILTERED]", text)
    if cleaned != text:
        logger.warning(f"Sanitized suspicious content from {source}")
    return cleaned


def _verify_webhook_signature(event: dict) -> dict | None:
    """Verify inbound webhook signature based on the configured channel.

    Returns None if verification passes, or an HTTP error response dict if it fails.
    Skips verification for SES (S3-triggered) and when no secret is configured.
    """
    if not WEBHOOK_SECRET:
        logger.warning(
            "WEBHOOK_SECRET not configured — skipping signature verification"
        )
        return None

    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    raw_body = event.get("body", "") or ""
    if event.get("isBase64Encoded"):
        raw_body = base64.b64decode(raw_body).decode()

    if CHANNEL == "slack":
        ts = headers.get("x-slack-request-timestamp", "")
        if not ts or abs(time.time() - int(ts)) > 300:
            return _resp(401, {"error": "Request timestamp expired"})
        sig_base = f"v0:{ts}:{raw_body}".encode()
        expected = (
            "v0="
            + hmac.new(WEBHOOK_SECRET.encode(), sig_base, hashlib.sha256).hexdigest()
        )
        if not hmac.compare_digest(expected, headers.get("x-slack-signature", "")):
            return _resp(401, {"error": "Invalid signature"})

    elif CHANNEL == "jira":
        sig_header = headers.get("x-hub-signature", "")
        if not sig_header.startswith("sha256="):
            return _resp(401, {"error": "Missing signature"})
        expected = hmac.new(
            WEBHOOK_SECRET.encode(), raw_body.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, sig_header[7:]):
            return _resp(401, {"error": "Invalid signature"})

    elif CHANNEL == "servicenow":
        token = headers.get("x-webhook-secret", "")
        if not hmac.compare_digest(token, WEBHOOK_SECRET):
            return _resp(401, {"error": "Invalid token"})

    return None


def handler(event: dict, context) -> dict:
    """
    Lambda entry point. Routes to SES or webhook normalization based on event shape.

    Args:
        event: S3 notification (SES path) or Function URL / API Gateway event (webhook path).
        context: Lambda context object.

    Returns:
        dict: HTTP-style response with statusCode and body.
    """
    logger.info(f"Event: {json.dumps(event)[:2000]}")

    try:
        # S3 events have "Records" with "s3" key — this is the SES inbound path
        if "Records" in event and event["Records"][0].get("s3"):
            results = _handle_ses_inbound(event)
            return _resp(
                200,
                {"message": f"Processed {len(results)} email(s)", "results": results},
            )

        # Everything else is a webhook — verify signature first
        sig_error = _verify_webhook_signature(event)
        if sig_error:
            logger.warning("Webhook signature verification failed")
            return sig_error

        normalized = _normalize_webhook(event)
        if not normalized:
            return _resp(200, {"message": "Event ignored (no actionable content)"})

        _enqueue(normalized)
        return _resp(
            200, {"message": "Enqueued", "case_id": normalized.get("case_id", "")}
        )

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        return _resp(500, {"error": str(e)})


def _handle_ses_inbound(event: dict) -> list[dict]:
    """
    Process one or more SES emails deposited in S3.

    Args:
        event: S3 event notification containing Records.

    Returns:
        list[dict]: Processing results per record.
    """
    results = []

    for record in event["Records"]:
        bucket = record["s3"]["bucket"]["name"]
        key = record["s3"]["object"]["key"]
        logger.info(f"Processing email: s3://{bucket}/{key}")

        try:
            raw_email = _download_from_s3(bucket=bucket, key=key)
            parsed = _parse_email(raw_email=raw_email)
            normalized = _normalize_email(parsed=parsed, bucket=bucket, key=key)
            _enqueue(normalized)
            results.append(
                {
                    "key": key,
                    "status": "enqueued",
                    "case_id": normalized.get("case_id", ""),
                }
            )
        except Exception as e:
            logger.error(f"Failed to process {key}: {e}", exc_info=True)
            results.append({"key": key, "status": "error", "error": str(e)})

    return results


def _download_from_s3(*, bucket: str, key: str) -> str:
    """
    Download raw email content from S3.

    Args:
        bucket: S3 bucket name.
        key: S3 object key.

    Returns:
        str: Raw RFC 822 email content.
    """
    resp = s3.get_object(Bucket=bucket, Key=key)
    return resp["Body"].read().decode("utf-8", errors="replace")


def _parse_email(*, raw_email: str) -> dict:
    """
    Parse raw email into structured data using mail-parser and email-reply-parser.

    mail-parser handles all MIME complexity (multipart, charset, attachments).
    email-reply-parser extracts only the new reply content, stripping quoted text
    and signatures.

    Args:
        raw_email: Raw RFC 822 email string.

    Returns:
        dict: Parsed email with keys: subject, from, to, date, body, reply_text,
              message_id, in_reply_to, references, has_attachments.
    """
    mail = mailparser.parse_from_string(raw_email)

    body_plain = mail.text_plain[0] if mail.text_plain else ""
    body_html = mail.text_html[0] if mail.text_html else ""

    if body_plain:
        reply_text = EmailReplyParser.parse_reply(body_plain)
    elif body_html:
        plain_from_html = re.sub(r"<[^>]+>", "", body_html).strip()
        reply_text = EmailReplyParser.parse_reply(plain_from_html)
    else:
        reply_text = ""

    headers = mail.headers or {}

    return {
        "subject": mail.subject or "",
        "from": mail.from_[0][1] if mail.from_ else "",
        "from_display": mail.from_[0][0] if mail.from_ else "",
        "to": [addr[1] for addr in (mail.to or [])],
        "date": mail.date.isoformat() if mail.date else "",
        "body": body_plain or body_html,
        "reply_text": reply_text,
        "message_id": headers.get("Message-ID", ""),
        "in_reply_to": headers.get("In-Reply-To", ""),
        "references": headers.get("References", ""),
        "has_attachments": bool(mail.attachments),
    }


def _normalize_email(*, parsed: dict, bucket: str, key: str) -> dict:
    """
    Convert parsed email into the standard normalized payload for the agent queue.

    Args:
        parsed: Output from _parse_email().
        bucket: S3 bucket where raw email is stored.
        key: S3 object key.

    Returns:
        dict: Normalized payload with source, case_id, sender, message, and metadata.
    """
    # Prefer canonical "Case ID: X#Y" from the email body (round-tripped from
    # outbound notification footer) over fuzzy subject-line extraction.
    case_id = _extract_case_id(parsed["body"]) or _extract_case_id(parsed["subject"])

    return {
        "source": "ses",
        "case_id": case_id,
        "sender": parsed["from"],
        "message": _sanitize(parsed["reply_text"] or parsed["body"], source="ses"),
        "subject": _sanitize(parsed["subject"], source="ses"),
        "is_reply": bool(parsed["in_reply_to"]),
        "s3_bucket": bucket,
        "s3_key": key,
    }


def _normalize_webhook(event: dict) -> dict | None:
    """
    Parse inbound webhook into a standard shape.

    Args:
        event: API Gateway event from POST /webhooks.

    Returns:
        dict | None: Normalized payload, or None if event should be ignored.
    """
    body_str = event.get("body", "")
    if event.get("isBase64Encoded"):
        body_str = base64.b64decode(body_str).decode()

    try:
        body = json.loads(body_str) if isinstance(body_str, str) and body_str else event
    except json.JSONDecodeError:
        body = event

    # Slack url_verification challenge
    if body.get("type") == "url_verification":
        return None

    # Slack message event
    if body.get("event", {}).get("type") == "message":
        evt = body["event"]
        return {
            "source": "slack",
            "case_id": _extract_case_id(evt.get("text", "")),
            "sender": evt.get("user", ""),
            "message": _sanitize(evt.get("text", ""), source="slack"),
            "channel": evt.get("channel", ""),
            "thread_ts": evt.get("thread_ts"),
        }

    # ServiceNow webhook
    if "sys_id" in body and "short_description" in body:
        return {
            "source": "servicenow",
            "case_id": body.get("correlation_id")
            or _extract_case_id(body.get("short_description", "")),
            "sender": body.get("sys_updated_by", ""),
            "message": _sanitize(
                body.get("comments", body.get("work_notes", "")), source="servicenow"
            ),
            "incident_number": body.get("number"),
            "state": body.get("state"),
        }

    # Jira webhook
    if "issue" in body and "webhookEvent" in body:
        issue = body["issue"]
        comment = (body.get("comment") or {}).get("body", "")
        return {
            "source": "jira",
            "case_id": _extract_case_id(
                issue.get("key", "")
                + " "
                + (issue.get("fields", {}).get("summary", ""))
            ),
            "sender": (body.get("user") or {}).get("displayName", ""),
            "message": _sanitize(
                comment or issue.get("fields", {}).get("description", ""), source="jira"
            ),
            "issue_key": issue.get("key"),
            "event_type": body.get("webhookEvent"),
        }

    return None


def _enqueue(normalized: dict) -> None:
    """
    Send normalized payload to the agent invocation queue (SQS FIFO).

    Args:
        normalized: Standard payload dict with at least 'source' and 'case_id'.
    """
    if not QUEUE_URL:
        logger.warning("AGENT_QUEUE_URL not set — skipping enqueue")
        return

    case_id = normalized.get("case_id", "")
    # Only use case_id for routing if it's in canonical document_number#item_id
    # format. Partial matches (e.g. "PO 4500002597") stay in the payload as
    # context for the agent but don't become the authoritative case_id — the
    # agent resolves the actual case via its tools.
    canonical_id = case_id if "#" in case_id else ""

    # SQS FIFO MessageGroupId only allows alphanumeric and punctuation, no spaces
    group_id = (
        canonical_id.replace(" ", "-")
        if canonical_id
        else f"webhook-{uuid.uuid4().hex[:8]}"
    )

    sqs.send_message(
        QueueUrl=QUEUE_URL,
        MessageBody=json.dumps(
            {
                "case_id": canonical_id,
                "trigger": f"webhook-{normalized.get('source', 'unknown')}",
                "payload": normalized,
            }
        ),
        MessageGroupId=group_id,
    )
    logger.info(
        f"Enqueued: source={normalized.get('source')}, case_id={canonical_id or '(agent will resolve)'}, hint={case_id}"
    )


def _extract_case_id(text: str) -> str:
    """
    Extract a case ID from free text (subject lines, messages, etc.).

    Looks for patterns like Case ID: 5100001948#2026, CASE-12345,
    PO 4500012345, or INV 5105600123.

    Args:
        text: Input text to search.

    Returns:
        str: Extracted case ID, or empty string if none found.
    """
    # Explicit "Case ID: X#Y" pattern (from notification emails)
    m = re.search(r"[Cc]ase\s*(?:ID|id)[:\s]+(\S+#\S+)", text)
    if m:
        return m.group(1)
    m = re.search(r"(?:CASE|case)[-_]?(\w+)", text)
    if m:
        return m.group(0)
    m = re.search(r"(?:PO|po|INV|inv|INVOICE|invoice)\s*(\d{7,10})", text)
    if m:
        return m.group(0)
    return ""


def _resp(code: int, body: dict) -> dict:
    """
    Build an HTTP-style Lambda response.

    Args:
        code: HTTP status code.
        body: Response body dict.

    Returns:
        dict: Lambda response with statusCode, headers, and JSON body.
    """
    return {
        "statusCode": code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }
