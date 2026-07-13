# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Slack adapter — posts messages via Slack Web API (chat.postMessage)."""

import json
import urllib.request
from datetime import datetime, timezone

from ._secrets import get_creds


def send(
    *,
    recipient: str,
    subject: str,
    body: str,
    case_id: str | None = None,
    priority: str = "medium",
) -> dict:
    creds = get_creds()
    url = "https://slack.com/api/chat.postMessage"

    # recipient = channel ID or channel name
    text = f"*{subject}*\n{body}"
    if case_id:
        text += f"\n_Case: {case_id}_"

    payload = json.dumps(
        {"channel": recipient, "text": text, "unfurl_links": False}
    ).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {creds['bot_token']}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )

    with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310 — URL from config  # nosemgrep: dynamic-urllib-use-detected
        result = json.loads(resp.read())

    if not result.get("ok"):
        raise RuntimeError(f"Slack API error: {result.get('error')}")

    return {
        "channel": "slack",
        "channel_id": result.get("channel"),
        "message_ts": result.get("ts"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
