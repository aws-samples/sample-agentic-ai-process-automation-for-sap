# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for webhook signature verification in lambdas/webhook_processor/index.py.

Run with: pytest tests/unit/test_webhook_signature.py -v
"""

import hashlib
import hmac
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent.parent / "lambdas" / "webhook_processor"
    ),
)

# Mock Lambda-only dependencies not available in test environment
sys.modules.setdefault("mailparser", type(sys)("mailparser"))
sys.modules.setdefault("email_reply_parser", type(sys)("email_reply_parser"))
if not hasattr(sys.modules["email_reply_parser"], "EmailReplyParser"):
    sys.modules["email_reply_parser"].EmailReplyParser = type(
        "EmailReplyParser", (), {"parse_reply": staticmethod(lambda t: t)}
    )

# Import once — tests patch module globals directly (no reload needed).
# Suppress Secrets Manager call at import by ensuring env var is empty.
with patch.dict(
    "os.environ", {"NOTIFICATION_SECRET": "", "NOTIFICATION_CHANNEL": "ses"}
):
    import index as wp


def _make_event(body: str, headers: dict | None = None, b64: bool = False) -> dict:
    """Build a minimal API Gateway-style event."""
    import base64

    return {
        "body": base64.b64encode(body.encode()).decode() if b64 else body,
        "isBase64Encoded": b64,
        "headers": headers or {},
    }


def _jira_signature(secret: str, body: str) -> str:
    return (
        "sha256=" + hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    )


class TestJiraVerification:
    SECRET = "jira-test-secret"

    def test_valid_signature(self):
        with (
            patch.object(wp, "WEBHOOK_SECRET", self.SECRET),
            patch.object(wp, "CHANNEL", "jira"),
        ):
            body = json.dumps({"issue": {}, "webhookEvent": "jira:issue_updated"})
            sig = _jira_signature(self.SECRET, body)
            event = _make_event(body, {"x-hub-signature": sig})
            assert wp._verify_webhook_signature(event) is None

    def test_invalid_signature(self):
        with (
            patch.object(wp, "WEBHOOK_SECRET", self.SECRET),
            patch.object(wp, "CHANNEL", "jira"),
        ):
            body = json.dumps({"issue": {}})
            event = _make_event(body, {"x-hub-signature": "sha256=wrong"})
            assert wp._verify_webhook_signature(event)["statusCode"] == 401

    def test_missing_signature_header(self):
        with (
            patch.object(wp, "WEBHOOK_SECRET", self.SECRET),
            patch.object(wp, "CHANNEL", "jira"),
        ):
            event = _make_event("{}", {})
            assert wp._verify_webhook_signature(event)["statusCode"] == 401


class TestServiceNowVerification:
    SECRET = "sn-shared-token"

    def test_valid_token(self):
        with (
            patch.object(wp, "WEBHOOK_SECRET", self.SECRET),
            patch.object(wp, "CHANNEL", "servicenow"),
        ):
            event = _make_event("{}", {"x-webhook-secret": self.SECRET})
            assert wp._verify_webhook_signature(event) is None

    def test_invalid_token(self):
        with (
            patch.object(wp, "WEBHOOK_SECRET", self.SECRET),
            patch.object(wp, "CHANNEL", "servicenow"),
        ):
            event = _make_event("{}", {"x-webhook-secret": "wrong"})
            assert wp._verify_webhook_signature(event)["statusCode"] == 401


class TestNoSecretConfigured:
    def test_skips_verification_with_warning(self):
        with (
            patch.object(wp, "WEBHOOK_SECRET", ""),
            patch.object(wp, "CHANNEL", "jira"),
        ):
            event = _make_event("{}", {})
            assert wp._verify_webhook_signature(event) is None
