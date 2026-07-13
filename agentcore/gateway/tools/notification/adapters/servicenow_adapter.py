# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""ServiceNow adapter — creates/updates incidents via REST API."""

import base64
import json
import urllib.request
from datetime import datetime, timezone

from ._secrets import get_creds

PRIORITY_MAP = {"high": "1", "medium": "3", "low": "4"}


def send(
    *,
    recipient: str,
    subject: str,
    body: str,
    case_id: str | None = None,
    priority: str = "medium",
) -> dict:
    creds = get_creds()
    instance = creds["instance_url"].rstrip("/")
    url = f"{instance}/api/now/table/incident"

    payload = json.dumps(
        {
            "short_description": subject,
            "description": body,
            "assignment_group": recipient,
            "urgency": PRIORITY_MAP.get(priority, "3"),
            "correlation_id": case_id or "",
        }
    ).encode()

    auth = base64.b64encode(
        f"{creds['username']}:{creds['password']}".encode()
    ).decode()
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )

    with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310 — URL from config  # nosemgrep: dynamic-urllib-use-detected
        result = json.loads(resp.read())

    return {
        "channel": "servicenow",
        "incident_number": result.get("result", {}).get("number"),
        "sys_id": result.get("result", {}).get("sys_id"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
