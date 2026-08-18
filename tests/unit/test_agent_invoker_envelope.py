# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""The invoker's AG-UI contract with the agent, and what it does with the outcome.

The agent reads its ERP fields from ``forwardedProps.erpPayload`` and builds the
prompt itself. Nothing at runtime enforces that contract, so these tests pin it.
HTTP 200 covers both successful and failed runs, so the handler must combine the
AG-UI terminal event with the persisted ERP case outcome. Both contracts are pinned.
"""

import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INVOKER = _REPO_ROOT / "lambdas" / "agent_invoker" / "index.py"


@pytest.fixture()
def invoker():
    """Import the Lambda module with the environment and AWS clients it needs."""
    env = {
        "STACK_NAME_BASE": "test-stack",
        "CASES_TABLE": "",
        "AWS_REGION": "us-east-1",
    }
    with (
        mock.patch.dict(os.environ, env, clear=False),
        mock.patch("boto3.client"),
        mock.patch("boto3.resource"),
    ):
        spec = importlib.util.spec_from_file_location(
            "agent_invoker_under_test", _INVOKER
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        yield module
    sys.modules.pop(spec.name, None)


class _StreamResponse:
    """A response whose body arrives in successive reads, like a real SSE stream."""

    status = 200

    def __init__(self, chunks):
        self._chunks = list(chunks)

    def read(self, size=-1):
        return self._chunks.pop(0) if self._chunks else b""

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _capture_envelope(invoker, payload, chunks=None):
    """Run _invoke_agent against a stubbed transport and return the posted request."""
    captured = {}
    chunks = chunks if chunks is not None else [b'data: {"type":"RUN_FINISHED"}\n\n']

    def _urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = {k.lower(): v for k, v in request.headers.items()}
        captured["body"] = json.loads(request.data.decode())
        return _StreamResponse(chunks)

    invoker.ssm.get_parameter.return_value = {
        "Parameter": {"Value": "arn:aws:test:runtime/x"}
    }
    with (
        mock.patch.object(invoker, "_get_token", return_value="token"),
        mock.patch.object(invoker.urllib.request, "urlopen", _urlopen),
    ):
        captured["result"] = invoker._invoke_agent(payload, username="alice")
    return captured


# --------------------------------------------------------------------------- envelope


def test_erp_fields_travel_where_the_agent_reads_them(invoker):
    payload = {
        "case_id": "4500012345#00010",
        "trigger": "manual",
        "payload": {"k": "v"},
    }

    body = _capture_envelope(invoker, payload)["body"]

    assert body["forwardedProps"]["erpPayload"] == payload
    # RunAgentInput requires the key even though nothing reads it back; it must not
    # duplicate case_id/trigger, which already live in forwardedProps.erpPayload.
    assert body["state"] is None
    for key in ("threadId", "runId", "messages", "tools", "context"):
        assert key in body, f"RunAgentInput is missing {key}"


def test_no_prompt_is_sent_so_the_agent_builds_its_own(invoker):
    payload = {"case_id": "4500012345#00010", "trigger": "manual", "payload": {}}

    body = _capture_envelope(invoker, payload)["body"]

    assert "prompt" not in body["forwardedProps"]["erpPayload"]
    assert "user_prompt" not in body["forwardedProps"]["erpPayload"]


def test_thread_id_matches_the_runtime_session_header(invoker):
    # The agent derives its session from thread_id; a mismatch splits Memory per turn.
    captured = _capture_envelope(
        invoker, {"case_id": "C#1", "trigger": "poller", "payload": {}}
    )

    session_header = captured["headers"]["x-amzn-bedrock-agentcore-runtime-session-id"]
    assert captured["body"]["threadId"] == session_header
    assert captured["headers"]["accept"] == "text/event-stream"


def test_each_queued_invocation_gets_a_disposable_session(invoker):
    """Callbacks for one case must not reuse a completed Runtime or Memory session."""
    first_payload = {
        "case_id": "5100001976-2026",
        "trigger": "poller",
        "payload": {},
    }
    callback_payload = {
        "case_id": "5100001976-2026",
        "trigger": "ticket-action",
        "payload": {
            "ticket_decision": "replied",
            "response_text": "Warehouse confirmed receipt.",
        },
    }

    first = _capture_envelope(invoker, first_payload)
    callback = _capture_envelope(invoker, callback_payload)

    first_session = first["body"]["threadId"]
    callback_session = callback["body"]["threadId"]
    assert first_session.startswith("sqs-")
    assert callback_session.startswith("sqs-")
    assert first_session != callback_session
    assert (
        first_session == first["headers"]["x-amzn-bedrock-agentcore-runtime-session-id"]
    )
    assert (
        callback_session
        == callback["headers"]["x-amzn-bedrock-agentcore-runtime-session-id"]
    )
    assert first["body"]["runId"] != callback["body"]["runId"]
    assert callback["body"]["forwardedProps"]["erpPayload"] == callback_payload


def test_an_unresolvable_case_id_still_gets_a_disposable_session(invoker):
    """No identity to key Memory on, so the run falls back rather than failing."""
    captured = _capture_envelope(
        invoker, {"case_id": "", "trigger": "manual", "payload": {}}
    )

    thread_id = captured["body"]["threadId"]
    assert thread_id.startswith("sqs-"), thread_id


def test_user_identity_is_forwarded_for_gateway_audit(invoker):
    captured = _capture_envelope(
        invoker, {"case_id": "C#1", "trigger": "manual", "payload": {}}
    )

    assert captured["headers"]["x-user-identity"] == "alice"


def test_socket_timeout_is_an_idle_guard_not_a_run_budget(invoker):
    # urllib's timeout is per blocking read. It must be scaled to the agent's 15s
    # keepalive so silence is detected, NOT to the length of a whole run.
    captured = _capture_envelope(
        invoker, {"case_id": "C#1", "trigger": "manual", "payload": {}}
    )

    assert captured["timeout"] == invoker._IDLE_TIMEOUT_SECONDS
    assert 15 < invoker._IDLE_TIMEOUT_SECONDS <= 120


# ----------------------------------------------------------------------- drain/outcome


@pytest.mark.parametrize(
    "chunks,expected",
    [
        ([b'data: {"type":"RUN_FINISHED"}'], "RUN_FINISHED"),
        ([b'data: {"type":"RUN_ERROR","code":"X"}'], "RUN_ERROR"),
        # A failure outranks a completion: a stream reporting both is not a success.
        (
            [b'data: {"type":"RUN_FINISHED"}', b'data: {"type":"RUN_ERROR"}'],
            "RUN_ERROR",
        ),
        ([b'data: {"type":"TEXT_MESSAGE_CONTENT"}'], "none"),
        ([], "none"),
        # A deliberate stop is a RUN_ERROR subtype, and outranks the plain code.
        (
            [b'data: {"type":"RUN_ERROR","code":"MAX_TURNS_REACHED"}\n\n'],
            "MAX_TURNS_REACHED",
        ),
        (
            [b'data: {"type":"RUN_ERROR","code":"MAX_TOKENS_REACHED"}\n\n'],
            "MAX_TOKENS_REACHED",
        ),
        (
            [b'data: {"type":"RUN_ERROR","code":"TOOL_FAILURE"}\n\n'],
            "RUN_ERROR",
        ),
    ],
)
def test_terminal_classification(invoker, chunks, expected):
    terminal = invoker._drain_stream(
        _StreamResponse(chunks), deadline=time.monotonic() + 30
    )[1]

    assert terminal == expected


def test_a_marker_split_across_two_reads_is_still_matched(invoker):
    # The stream is scanned incrementally rather than buffered, so a marker landing on
    # a read boundary must not be missed.
    chunks = [b'data: {"type":"RUN_FIN', b'ISHED"}\n\n']

    byte_count, terminal = invoker._drain_stream(
        _StreamResponse(chunks), deadline=time.monotonic() + 30
    )

    assert terminal == "RUN_FINISHED"
    assert byte_count == sum(len(c) for c in chunks)


def test_exceeding_the_run_budget_raises_rather_than_being_killed(invoker):
    # The whole point of a deadline: fail with a message and a retry instead of being
    # hard-killed by the Lambda runtime mid-run.
    with pytest.raises(TimeoutError, match="exceeded its budget"):
        invoker._drain_stream(
            _StreamResponse([b'data: {"type":"RUN_FINISHED"}']),
            deadline=time.monotonic() - 1,
        )


def test_the_deadline_comes_from_the_lambda_budget_not_a_constant(invoker):
    class _Ctx:
        @staticmethod
        def get_remaining_time_in_millis():
            return 300_000

    budget = invoker._run_deadline(_Ctx()) - time.monotonic()

    assert budget == pytest.approx(300 - invoker._DEADLINE_MARGIN_SECONDS, abs=2)


def test_a_missing_context_falls_back_to_a_bounded_budget(invoker):
    budget = invoker._run_deadline(None) - time.monotonic()

    assert budget == pytest.approx(invoker._FALLBACK_RUN_BUDGET_SECONDS, abs=2)


# --------------------------------------------------------------------------- handler


def _run_handler(invoker, body, result, table=None):
    """Drive handler() with one SQS record and a stubbed agent outcome."""
    seen = {}

    def _capture(payload, *, username="", context=None):
        seen["payload"] = payload
        seen["username"] = username
        return result

    event = {"Records": [{"messageId": "m1", "body": json.dumps(body)}]}
    # The handler builds its table from TABLE_NAME, so a status update is only
    # attempted when the cases table is configured.
    table_name = "cases" if table is not None else ""
    with (
        mock.patch.object(invoker, "_invoke_agent", _capture),
        mock.patch.object(invoker, "_update_status") as status,
        mock.patch.object(invoker, "TABLE_NAME", table_name),
    ):
        if table is not None:
            invoker.dynamodb.Table.return_value = table
        seen["response"] = invoker.handler(event, None)
        seen["status_calls"] = status.call_args_list
    return seen


_FINISHED = {"terminal": "RUN_FINISHED"}
_FAILED = {"terminal": "RUN_ERROR"}
_NO_TERMINAL = {"terminal": "none"}
_TURN_LIMIT = {"terminal": "MAX_TURNS_REACHED"}
_TOKEN_LIMIT = {"terminal": "MAX_TOKENS_REACHED"}


def test_handler_builds_no_prompt_for_an_enqueued_case(invoker):
    # Sending no prompt is what makes trigger="manual" safe to share with interactive
    # chat: _build_prompt returns a user prompt only when one is present, so an
    # enqueued case falls through to the SOP instruction. A prompt here would be read
    # as an explicit user message and strip that instruction from every enqueued case.
    seen = _run_handler(
        invoker,
        {"case_id": "4500012345#00010", "trigger": "manual", "username": "alice"},
        _FINISHED,
    )

    assert "prompt" not in seen["payload"]
    assert "user_prompt" not in seen["payload"]
    # The id is normalized once at ingest, so the agent sees exactly one form even
    # though this message arrived in the legacy `doc#item` shape.
    assert seen["payload"]["case_id"] == "4500012345-00010"
    assert seen["username"] == "alice"


def test_handler_passes_webhook_context_through_unbuilt(invoker):
    # Webhook content must reach the agent as data so _build_prompt can sanitize and
    # fence it. Formatting it into a prompt here would bypass that.
    context = {
        "sender": "sender@example.com",
        "subject": "Re: case",
        "message": "please advise",
    }
    seen = _run_handler(
        invoker,
        {"case_id": "C#1", "trigger": "webhook-ses", "payload": context},
        _FINISHED,
    )

    assert seen["payload"]["payload"] == context
    assert "prompt" not in seen["payload"]


@pytest.mark.parametrize(
    "status",
    ["complete", "awaiting_human_input", "manual_review_required", "sap_updated"],
)
def test_finished_run_accepts_safe_terminal_business_status(invoker, status):
    table = mock.MagicMock()
    table.get_item.return_value = {"Item": {"status": status}}

    seen = _run_handler(
        invoker, {"case_id": "C#1", "trigger": "manual"}, _FINISHED, table
    )

    assert seen["response"] == {}
    assert not any(
        call.args[2] == "manual_review_required" for call in seen["status_calls"]
    )
    table.get_item.assert_called_once_with(
        Key={"case_id": "C-1"},
        ConsistentRead=True,
        ProjectionExpression="#s",
        ExpressionAttributeNames={"#s": "status"},
    )


@pytest.mark.parametrize("status", ["detected", "processing", "error", "invalid", None])
def test_finished_run_routes_unsafe_business_status_to_manual_review(invoker, status):
    table = mock.MagicMock()
    table.get_item.return_value = {"Item": {"status": status}}

    seen = _run_handler(
        invoker, {"case_id": "C#1", "trigger": "manual"}, _FINISHED, table
    )

    assert seen["response"] == {}, "a completed run must not be blindly replayed"
    manual_calls = [
        call
        for call in seen["status_calls"]
        if call.args[2] == "manual_review_required"
    ]
    assert len(manual_calls) == 1
    assert "safe terminal case state" in manual_calls[0].kwargs["reason"]


@pytest.mark.parametrize(
    "get_item_result",
    [{}, {"Item": None}],
    ids=["missing_item_key", "explicit_none"],
)
def test_finished_run_with_missing_case_is_returned_for_redrive(
    invoker, get_item_result
):
    table = mock.MagicMock()
    table.get_item.return_value = get_item_result

    seen = _run_handler(
        invoker, {"case_id": "C#1", "trigger": "manual"}, _FINISHED, table
    )

    assert seen["response"] == {"batchItemFailures": [{"itemIdentifier": "m1"}]}


def test_finished_run_with_unreadable_case_is_returned_for_redrive(invoker):
    table = mock.MagicMock()
    table.get_item.side_effect = RuntimeError("DynamoDB unavailable")

    seen = _run_handler(
        invoker, {"case_id": "C#1", "trigger": "manual"}, _FINISHED, table
    )

    assert seen["response"] == {"batchItemFailures": [{"itemIdentifier": "m1"}]}


def test_finished_run_redrives_if_manual_review_cannot_be_recorded(invoker):
    table = mock.MagicMock()
    table.get_item.return_value = {"Item": {"status": "processing"}}

    with mock.patch.object(invoker, "_update_status", return_value=False):
        with pytest.raises(RuntimeError, match="cannot record manual review"):
            invoker._verify_business_outcome(table, "C#1", "manual")


@pytest.mark.parametrize(
    "outcome", [_FAILED, _NO_TERMINAL], ids=["run_error", "no_terminal"]
)
def test_a_run_that_did_not_complete_is_returned_for_redrive(invoker, outcome):
    # Without this the message is deleted on an HTTP 200 that carried a failure, and the
    # case sits in "processing" forever.
    seen = _run_handler(invoker, {"case_id": "C#1", "trigger": "manual"}, outcome)

    assert seen["response"] == {"batchItemFailures": [{"itemIdentifier": "m1"}]}


@pytest.mark.parametrize(
    "outcome",
    [_TURN_LIMIT, _TOKEN_LIMIT],
    ids=["max_turns", "max_tokens"],
)
def test_hitting_a_processing_limit_goes_to_manual_review_without_retry(
    invoker, outcome
):
    # Retrying deterministic processing limits can replay completed tool side effects,
    # so the redrive budget must not run the same case again.
    table = mock.MagicMock()
    seen = _run_handler(
        invoker,
        {"case_id": "4500012345#00010", "trigger": "manual"},
        outcome,
        table,
    )

    assert seen["response"] == {}, "a deliberate stop must not be retried"
    assert any(
        call.args[2] == "manual_review_required" for call in seen["status_calls"]
    ), f"expected a manual_review_required status update, got {seen['status_calls']}"
