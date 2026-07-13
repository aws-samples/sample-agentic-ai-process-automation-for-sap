# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Jira adapter — creates issues via Jira REST API v2."""

import base64
import json
import urllib.request
from datetime import datetime, timezone

from ._secrets import get_creds

PRIORITY_MAP = {"high": "High", "medium": "Medium", "low": "Low"}


def send(
    *,
    recipient: str,
    subject: str,
    body: str,
    case_id: str | None = None,
    priority: str = "medium",
) -> dict:
    creds = get_creds()
    base = creds["base_url"].rstrip("/")
    url = f"{base}/rest/api/2/issue"

    payload = json.dumps(
        {
            "fields": {
                "project": {"key": creds.get("project_key", recipient)},
                "summary": subject,
                "description": body,
                "issuetype": {"name": creds.get("issue_type", "Task")},
                "priority": {"name": PRIORITY_MAP.get(priority, "Medium")},
                **({"labels": [f"case-{case_id}"]} if case_id else {}),
            }
        }
    ).encode()

    auth = base64.b64encode(f"{creds['email']}:{creds['api_token']}".encode()).decode()
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
        },
    )

    with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310 — URL from config  # nosemgrep: dynamic-urllib-use-detected
        result = json.loads(resp.read())

    return {
        "channel": "jira",
        "issue_key": result.get("key"),
        "issue_id": result.get("id"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
