# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""
The agent knowledge tools are read-only evidence sources reached only through
the Gateway. Assert the origin guard rejects direct invocation, that agent
input never reaches SQL as text, and that an empty result is explicit rather
than silent.
"""

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_TOOL_DIR = _REPO_ROOT / "agentcore" / "gateway" / "tools" / "agent_knowledge"
sys.path.insert(0, str(_TOOL_DIR))


@pytest.fixture
def lam(monkeypatch):
    monkeypatch.setenv("CLUSTER_ARN", "arn:aws:rds:us-east-1:1:cluster:c")
    monkeypatch.setenv("SECRET_ARN", "arn:aws:secretsmanager:us-east-1:1:secret:s")
    monkeypatch.setenv("DATABASE_NAME", "agentknowledge")
    import agent_knowledge_lambda as m

    return m


class _Ctx:
    def __init__(self, tool_name=None):
        if tool_name is None:
            self.client_context = None
        else:
            self.client_context = type(
                "CC", (), {"custom": {"bedrockAgentCoreToolName": tool_name}}
            )()


class _FakeData:
    """Records the statements issued so the test can assert on them."""

    def __init__(self, records):
        self._records = records
        self.calls = []

    def execute_statement(self, **kwargs):
        self.calls.append(kwargs)
        return {"formattedRecords": json.dumps(self._records)}


def test_direct_invocation_is_rejected(lam):
    result = lam.handler({"process_type": "price_variance"}, _Ctx())
    assert "Unauthorized" in result["error"]


def test_unknown_tool_is_rejected(lam, monkeypatch):
    monkeypatch.setattr(lam, "_data", lambda: _FakeData([]))
    result = lam.handler({}, _Ctx("agent-knowledge-target___delete_everything"))
    assert "Unknown tool" in result["error"]


def test_get_precedent_parameterises_input(lam, monkeypatch):
    fake = _FakeData(
        [
            {
                "case_id": "INV-1",
                "disposition": "released",
                "tool_sequence": '["get_case_state"]',
                "sop_version": "v2",
                "user_rating": 1,
            }
        ]
    )
    monkeypatch.setattr(lam, "_data", lambda: fake)

    result = lam.handler(
        {
            "process_type": "price_variance",
            "supplier_number": "V1'; DROP TABLE x;--",
            "amount": 4200,
        },
        _Ctx("agent-knowledge-target___get_precedent"),
    )

    body = json.loads(result["content"][0]["text"])
    assert body["precedents"][0]["case_id"] == "INV-1"
    assert body["precedents"][0]["sop_version"] == "v2"

    # Every statement must have injection input bound, never interpolated as SQL.
    injection_string = "V1'; DROP TABLE x;--"
    for call in fake.calls:
        assert injection_string not in call["sql"], (
            f"Injection found in SQL: {call['sql']}"
        )
        for param in call["parameters"]:
            if param["name"] == "supplier_number":
                assert param["value"]["stringValue"] == injection_string


def test_check_vendor_risk_reports_an_empty_result_explicitly(lam, monkeypatch):
    monkeypatch.setattr(lam, "_data", lambda: _FakeData([]))
    result = lam.handler(
        {"supplier_number": "V9"},
        _Ctx("agent-knowledge-target___check_vendor_risk"),
    )
    body = json.loads(result["content"][0]["text"])
    assert body["related_vendors"] == []
    assert body["checked"] == "V9"


def test_every_statement_is_read_only(lam, monkeypatch):
    fake = _FakeData([])
    monkeypatch.setattr(lam, "_data", lambda: fake)
    lam.handler(
        {"process_type": "price_variance", "amount": 10},
        _Ctx("agent-knowledge-target___get_precedent"),
    )
    lam.handler(
        {"supplier_number": "V1"}, _Ctx("agent-knowledge-target___check_vendor_risk")
    )

    # Three statements expected: PRECEDENT_SQL + LESSON_SQL from get_precedent,
    # VENDOR_RISK_SQL from check_vendor_risk.
    assert len(fake.calls) == 3, f"Expected 3 calls, got {len(fake.calls)}"

    # Each statement must open with SELECT or WITH (read-only).
    for call in fake.calls:
        first_keyword = call["sql"].strip().upper().split()[0]
        assert first_keyword in (
            "SELECT",
            "WITH",
        ), f"Non-read-only keyword: {first_keyword} in {call['sql']}"


def test_missing_required_argument_is_an_error_not_a_query(lam, monkeypatch):
    fake = _FakeData([])
    monkeypatch.setattr(lam, "_data", lambda: fake)
    result = lam.handler({}, _Ctx("agent-knowledge-target___check_vendor_risk"))
    assert "error" in result
    assert fake.calls == []


def test_get_precedent_requires_an_amount():
    """Band matching is meaningless without an amount: omitting it would
    silently narrow every result to the lowest band."""
    spec = json.loads((_TOOL_DIR / "tool_spec.json").read_text())
    precedent = next(t for t in spec if t["name"] == "get_precedent")
    assert set(precedent["inputSchema"]["required"]) == {"process_type", "amount"}


def test_exception_messages_never_leak_secrets(lam, monkeypatch):
    """Errors must never expose ARN, password, or database names."""

    class FakeDataRaisesSecret:
        def execute_statement(self, **kwargs):
            raise RuntimeError(
                "arn:aws:secretsmanager:us-east-1:1:secret:s password=hunter2"
            )

    monkeypatch.setattr(lam, "_data", lambda: FakeDataRaisesSecret())
    result = lam.handler(
        {"process_type": "price_variance", "amount": 10},
        _Ctx("agent-knowledge-target___get_precedent"),
    )

    error_msg = result.get("error", "")
    assert "RuntimeError" in error_msg, "Error type should be reported for debugging"
    assert "password" not in error_msg.lower(), "Password should not leak"
    assert "hunter2" not in error_msg, "Secret value should not leak"
    assert "secretsmanager" not in error_msg.lower(), "ARN should not leak"
