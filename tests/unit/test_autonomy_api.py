# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""`/autonomy` — the trigger mode, and whether anything can honour it.

The trigger-mode SSM parameter is seeded unconditionally by the CDK, but the poller
that consumes it is only built when the auth profile declares `autonomous`. So a
live-only deployment can store `auto` with nothing to act on it, and a caller reading
the mode alone would report live unattended SAP writes on a deployment incapable of
one. `autonomous-capable` is what distinguishes those, and its parse is the seam that
inverts the whole claim if written naively — hence the string comparison below.
"""

import importlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def api(monkeypatch):
    """Import the handler with a given environment. Callers set AUTONOMOUS_CAPABLE via
    the factory below, because the module reads it at import time."""

    def _load(capable=None, queue_url=""):
        monkeypatch.setenv("STACK_NAME_BASE", "test-proj")
        monkeypatch.setenv("AGENT_QUEUE_URL", queue_url)
        if capable is None:
            monkeypatch.delenv("AUTONOMOUS_CAPABLE", raising=False)
        else:
            monkeypatch.setenv("AUTONOMOUS_CAPABLE", capable)
        sys.path.insert(0, str(_ROOT / "lambdas" / "autonomy_api"))
        with patch("boto3.client"):
            import index as mod

            importlib.reload(mod)
        mod.ssm = MagicMock()
        mod.ssm.get_parameter.return_value = {"Parameter": {"Value": "manual"}}
        return mod

    return _load


def _get(mod):
    return json.loads(mod.handler({"httpMethod": "GET"}, None)["body"])


def test_capable_true_reported_as_true(api):
    assert _get(api(capable="true"))["autonomous-capable"] is True


def test_capable_false_reported_as_false(api):
    # The seam: bool("false") is True, so a truthiness check here would report every
    # live-only deployment as capable — the exact overstatement this field prevents.
    assert _get(api(capable="false"))["autonomous-capable"] is False


def test_absent_variable_is_unknown_not_false(api):
    # A Lambda deployed before this field existed. Claiming "cannot go auto" for a
    # capable stack is a confident wrong answer, so absence must stay null.
    assert _get(api(capable=None))["autonomous-capable"] is None


def test_capability_ships_with_the_mode_in_one_response(api):
    # Atomicity is the reason this rides GET /autonomy rather than its own endpoint:
    # split across two fetches, a stored `auto` could paint before it is known inert.
    body = _get(api(capable="false"))
    assert body["trigger-mode"] == "manual"
    assert "autonomous-capable" in body


def test_unreadable_parameter_still_reports_capability(api):
    mod = api(capable="true")
    mod.ssm.get_parameter.side_effect = Exception("ParameterNotFound")
    body = _get(mod)
    assert body["trigger-mode"] is None
    assert body["autonomous-capable"] is True
