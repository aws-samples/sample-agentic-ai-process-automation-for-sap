# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""``inquiry_sent_at`` is server-owned, and the handover's age claim rests on it.

The shift handover renders "waiting 6d" off this field and falls back to
``updated_at`` — labelled "last activity" — when it is absent. So the field is the
difference between two different claims about a case, and the SOPs cannot be the
thing that writes it: eight clauses each remembering to pass a timestamp makes the
claim contingent on model cooperation, and a missed write reads as recent activity
on a case that has actually been stalled for a week.

These tests pin the stamp to the status transition instead, and pin the drop-list
that keeps a model-supplied value out of the three server-owned fields.
"""

import importlib.util
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_LAMBDA = (
    _REPO_ROOT
    / "agentcore"
    / "gateway"
    / "tools"
    / "case_management"
    / "case_management_lambda.py"
)


@pytest.fixture
def case_mgmt(monkeypatch):
    """Load the Lambda with boto3 stubbed and its table swapped for a recorder."""
    monkeypatch.setenv("STACK_NAME_BASE", "test-stack")
    sys.path.insert(0, str(_REPO_ROOT / "lambdas" / "layers" / "shared_types"))
    with mock.patch("boto3.client"), mock.patch("boto3.resource"):
        spec = importlib.util.spec_from_file_location("case_management_lambda", _LAMBDA)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

    table = mock.MagicMock()
    table.update_item.return_value = {"Attributes": {}}
    monkeypatch.setattr(mod, "_get_table", lambda: table)
    mod._table = table
    return mod, table


def _update(mod, table, updates: dict) -> dict:
    """Run _update_case and return the kwargs it passed to DynamoDB."""
    mod._update_case({"case_id": "5100001976-2026", "updates": json.dumps(updates)})
    return table.update_item.call_args.kwargs


def test_entering_awaiting_stamps_the_inquiry_time(case_mgmt):
    mod, table = case_mgmt
    expr = _update(mod, table, {"status": "awaiting_human_input"})["UpdateExpression"]
    # if_not_exists, not a bare assignment: a case re-invoked while still waiting
    # writes the status again, and the *first* inquiry is what the age is about.
    assert "inquiry_sent_at = if_not_exists(inquiry_sent_at, :ts)" in expr


def test_leaving_awaiting_clears_the_inquiry_time(case_mgmt):
    mod, table = case_mgmt
    expr = _update(mod, table, {"status": "complete"})["UpdateExpression"]
    assert "REMOVE" in expr and "inquiry_sent_at" in expr.split("REMOVE")[1]
    # Otherwise a case that escalates a second time would age from the first
    # inquiry, overstating the wait.
    assert "if_not_exists(inquiry_sent_at" not in expr


def test_an_update_naming_no_status_touches_neither(case_mgmt):
    mod, table = case_mgmt
    expr = _update(mod, table, {"exception_type": "PRICE"})["UpdateExpression"]
    # Editing a field is not a change in who is waiting, so a plain field update
    # must neither stamp nor clear.
    assert "inquiry_sent_at" not in expr


@pytest.mark.parametrize("reserved", ["inquiry_sent_at", "updated_at", "action_log"])
def test_server_owned_fields_are_dropped_from_model_updates(case_mgmt, reserved):
    mod, table = case_mgmt
    kwargs = _update(
        mod, table, {"status": "awaiting_human_input", reserved: "2020-01-01T00:00:00Z"}
    )
    # Two failure modes in one assertion. The hard one: this function writes all
    # three itself, and DynamoDB rejects an expression whose paths overlap, so a
    # merged value used to fail the whole call and lose the status write with it.
    # The quiet one: a model-supplied inquiry time is a fabricated wait age.
    assert f"#{reserved}" not in kwargs["ExpressionAttributeNames"]
    assert f":{reserved}" not in kwargs["ExpressionAttributeValues"]
    assert kwargs["ExpressionAttributeValues"][":ts"] != "2020-01-01T00:00:00Z"


def test_the_status_write_still_lands_alongside_the_stamp(case_mgmt):
    mod, table = case_mgmt
    kwargs = _update(mod, table, {"status": "awaiting_human_input"})
    # The stamp is a side effect of the status write, so it must not displace it.
    assert kwargs["ExpressionAttributeValues"][":status"] == "awaiting_human_input"
    assert "action_log = list_append(" in kwargs["UpdateExpression"]


def test_the_field_is_declared_in_the_schema(case_mgmt):
    # The root sets additionalProperties: false, so an undeclared field makes
    # every GET log a validation warning while returning it anyway.
    schema = json.loads(
        (_REPO_ROOT / "types" / "cases.schema.json").read_text(encoding="utf-8")
    )
    assert "inquiry_sent_at" in schema["properties"]
    assert "action_log" in schema["properties"]
