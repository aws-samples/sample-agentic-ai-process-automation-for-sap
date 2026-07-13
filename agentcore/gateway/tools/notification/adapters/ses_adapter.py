# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""SES adapter — sends plain-text email via Amazon SES."""

import os
import re
from datetime import datetime, timezone

import boto3

# Use SES_REGION env var if set, otherwise fall back to the Lambda's region.
# Gateway tool Lambdas may run in a different region than where SES is configured.
_ses_region = os.environ.get("SES_REGION", os.environ.get("AWS_REGION", "us-east-1"))
ses = boto3.client("ses", region_name=_ses_region)
SENDER = os.environ.get("NOTIFICATION_SENDER", "agent@example.com")


def send(
    *,
    recipient: str,
    subject: str,
    body: str,
    case_id: str | None = None,
    priority: str = "medium",
) -> dict:
    if not recipient or not re.match(
        r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", recipient
    ):
        raise ValueError(f"Invalid email: {recipient}")

    # Append case_id footer so replies carry it back for automated routing.
    # The webhook processor's _extract_case_id regex matches "Case ID: X#Y".
    email_body = body
    if case_id:
        email_body += f"\n\n---\nCase ID: {case_id}\n"

    resp = ses.send_email(
        Source=f"SAP Agent <{SENDER}>",
        Destination={"ToAddresses": [recipient]},
        Message={
            "Subject": {"Data": subject},
            "Body": {"Text": {"Data": email_body}},
        },
    )
    return {
        "channel": "ses",
        "message_id": resp["MessageId"],
        "recipient": recipient,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
