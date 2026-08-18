# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Precedent rows must be derived mechanically from traces — no FM in the write
path, so the same case always yields the same row. Also asserts the ratings
mapping, since DynamoDB stores strings and the column is smallint.
"""

import importlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def builder(monkeypatch):
    """Same fixture as tests/unit/test_exemplar_key_parity.py — the path insert
    and reload are per-test because several lambdas/ dirs export `index`."""
    monkeypatch.setenv("CASES_TABLE", "t")
    monkeypatch.setenv("EXEMPLAR_BUCKET", "b")
    sys.path.insert(0, str(_REPO_ROOT / "lambdas" / "exemplar_builder"))
    with patch("boto3.resource"), patch("boto3.client"):
        import index as m

        importlib.reload(m)
    return m


def test_tool_sequence_is_ordered_and_deterministic(builder):
    # Deliberately NOT in alphabetical order: notify-after-update is the real AP
    # flow, and an accidentally-sorted expectation would pass even if the
    # extractor sorted its output, silently losing the ordering guarantee.
    traces = [
        {
            "segments": [
                {"type": "tool", "tool_name": "get_case_state"},
                {"type": "text", "content": "thinking"},
                {"type": "tool", "tool_name": "odata_read"},
                {"type": "tool", "tool_name": "update_case_state"},
                {"type": "tool", "tool_name": "send_notification"},
            ]
        }
    ]
    first = builder.tool_sequence_from_traces(traces)
    assert first == [
        "get_case_state",
        "odata_read",
        "update_case_state",
        "send_notification",
    ]
    assert builder.tool_sequence_from_traces(traces) == first


def test_tool_sequence_ignores_segments_without_a_tool_name(builder):
    traces = [{"segments": [{"type": "tool"}, {"type": "tool", "tool_name": "ok"}]}]
    assert builder.tool_sequence_from_traces(traces) == ["ok"]


def test_empty_traces_yield_an_empty_sequence(builder):
    assert builder.tool_sequence_from_traces([]) == []


@pytest.mark.parametrize(
    "raw,expected", [("positive", 1), ("negative", -1), (None, None), ("weird", None)]
)
def test_rating_maps_to_smallint(builder, raw, expected):
    assert builder.rating_to_smallint(raw) == expected


@pytest.fixture
def enabled_builder(builder, monkeypatch):
    """The three env vars ARE the flag on this Lambda."""
    for name in ("CLUSTER_ARN", "SECRET_ARN", "DATABASE_NAME"):
        monkeypatch.setattr(builder, name, f"test-{name.lower()}")
    return builder


def _params(call):
    """Data API parameters as a plain name → value dict."""
    return {p["name"]: p["value"] for p in call.kwargs["parameters"]}


def test_flag_is_off_until_all_three_env_vars_are_set(builder, monkeypatch):
    assert builder._agent_knowledge_enabled() is False
    monkeypatch.setattr(builder, "CLUSTER_ARN", "arn")
    monkeypatch.setattr(builder, "SECRET_ARN", "arn")
    assert builder._agent_knowledge_enabled() is False
    monkeypatch.setattr(builder, "DATABASE_NAME", "agentknowledge")
    assert builder._agent_knowledge_enabled() is True


def test_write_uses_the_shared_band_definition(enabled_builder):
    """The read side keys on amount_band's exact output. A local redefinition
    here would drift and the precedent join would silently return nothing."""
    from amount_band import amount_band

    with patch.object(enabled_builder.boto3, "client") as client:
        enabled_builder._write_precedent(
            {"case_id": "c1", "amount": 5000}, "price_variance"
        )

    assert _params(client.return_value.execute_statement.call_args)["amount_band"] == {
        "stringValue": amount_band(5000)
    }


def test_rating_is_sent_as_sql_null_not_a_zero(enabled_builder):
    """smallint 0 would read as a real neutral rating; absent must stay NULL."""
    with patch.object(enabled_builder.boto3, "client") as client:
        enabled_builder._write_precedent({"case_id": "c1"}, "price_variance")
    assert _params(client.return_value.execute_statement.call_args)["user_rating"] == {
        "isNull": True
    }

    with patch.object(enabled_builder.boto3, "client") as client:
        enabled_builder._write_precedent(
            {"case_id": "c1", "user_rating": "negative"}, "price_variance"
        )
    assert _params(client.return_value.execute_statement.call_args)["user_rating"] == {
        "longValue": -1
    }


def test_sop_version_is_never_null(enabled_builder):
    """The column is NOT NULL — a null would surface as a silent write failure."""
    with patch.object(enabled_builder.boto3, "client") as client:
        enabled_builder._write_precedent({"case_id": "c1"}, "price_variance")
    assert _params(client.return_value.execute_statement.call_args)["sop_version"] == {
        "stringValue": "unversioned"
    }


def test_sop_version_comes_from_the_run_that_reached_the_disposition(enabled_builder):
    # The last trace, not the first: an escalation resumption runs against whatever
    # SOP was current then, and that is the authority the outcome followed.
    case = {
        "case_id": "c1",
        "agent_traces": [
            {"sop_version": "1.0", "segments": []},
            {"sop_version": "2.0", "segments": []},
        ],
    }
    with patch.object(enabled_builder.boto3, "client") as client:
        enabled_builder._write_precedent(case, "price_variance")
    assert _params(client.return_value.execute_statement.call_args)["sop_version"] == {
        "stringValue": "2.0"
    }


def test_a_trace_without_a_version_falls_back_to_an_earlier_one(enabled_builder):
    # Chat turns and pre-field traces carry none. Skipping them beats recording
    # "unversioned" for a case whose queued run did name its SOP.
    traces = [{"sop_version": "1.0"}, {"segments": []}]
    assert enabled_builder.sop_version_from_traces(traces) == "1.0"


def test_enabled_handler_writes_precedent_and_never_calls_bedrock(enabled_builder):
    """No FM in the precedent write path — that is what makes a citation
    reproducible, so assert Bedrock is not reached at all."""
    case = {
        "case_id": "c1",
        "document_number": "5100000001",
        "process_type": "price_variance",
        "agent_traces": [{"segments": [{"type": "tool", "tool_name": "odata_read"}]}],
    }
    with (
        patch.object(enabled_builder, "_query_successful_cases", return_value=[case]),
        patch.object(enabled_builder, "boto3") as b3,
        patch.object(enabled_builder, "bedrock") as bedrock,
        patch.object(enabled_builder, "s3") as s3,
    ):
        result = enabled_builder.handler({}, None)

    assert result == {"status": "ok", "generated": ["price_variance"]}
    b3.client.return_value.execute_statement.assert_called_once()
    bedrock.invoke_model.assert_not_called()
    s3.put_object.assert_not_called()


def test_disabled_handler_keeps_the_legacy_exemplar_path(builder):
    """Flag off must behave exactly as before: condense via Bedrock, write S3."""
    case = {
        "case_id": "c1",
        "document_number": "5100000001",
        "process_type": "price_variance",
        "agent_traces": [{"segments": [{"type": "tool", "tool_name": "odata_read"}]}],
    }
    with (
        patch.object(builder, "_query_successful_cases", return_value=[case]),
        patch.object(builder, "_condense_trace", return_value="1. odata_read"),
        patch.object(builder, "boto3") as b3,
        patch.object(builder, "s3") as s3,
    ):
        result = builder.handler({}, None)

    assert result == {"status": "ok", "generated": ["price_variance"]}
    s3.put_object.assert_called_once()
    b3.client.assert_not_called()
