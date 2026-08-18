# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""RUN_ERROR messages reach the browser verbatim, so adapter detail must be stripped.

`aguiReducer.appendRunError` renders `RUN_ERROR.message` directly into the chat. A
failure raised inside the agent loop arrives formatted by whichever library raised
it and can carry ARNs, endpoint hostnames, or SAP response fragments. Errors this
module builds itself are written for the user and pass through.

`_sanitized_run_error` is lifted out of basic_agent.py, which pulls in strands/mcp
and is not importable in the hermetic test environment.
"""

import ast
import pathlib

import pytest
from ag_ui.core import EventType, RunErrorEvent

_AGENT = (
    pathlib.Path(__file__).resolve().parents[2]
    / "agentcore"
    / "agent"
    / "basic_agent.py"
)


def _load():
    tree = ast.parse(_AGENT.read_text())
    wanted = {"_sanitized_run_error", "_OWN_ERROR_CODES"}
    kept, found = [], set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            kept.append(node)
            found.add(node.name)
        elif isinstance(node, ast.Assign):
            names = {getattr(t, "id", None) for t in node.targets} & wanted
            if names:
                kept.append(node)
                found |= names
    assert found == wanted, f"missing from basic_agent.py: {wanted - found}"
    namespace = {
        "EventType": EventType,
        "RunErrorEvent": RunErrorEvent,
        "frozenset": frozenset,
        "print": lambda *a, **k: None,
    }
    exec(  # nosec B102 - trusted source (this repo's own basic_agent.py), test-only
        compile(ast.Module(body=kept, type_ignores=[]), str(_AGENT), "exec"), namespace
    )
    return namespace


_NS = _load()
_sanitized_run_error = _NS["_sanitized_run_error"]
_OWN_ERROR_CODES = _NS["_OWN_ERROR_CODES"]


def _event(message, code=None):
    event = RunErrorEvent(type=EventType.RUN_ERROR, message=message, code=code)
    return event, event.model_dump(mode="json", by_alias=True)


@pytest.mark.parametrize("code", sorted(_OWN_ERROR_CODES))
def test_our_own_errors_pass_through_untouched(code):
    # These messages are written for the user; rewriting them would lose meaning.
    event, canonical = _event(
        "The agent reached its configured processing limit.", code
    )

    assert _sanitized_run_error(event, canonical, run_id="r1") is event


def test_exact_strands_max_tokens_error_becomes_safe_owned_code():
    event, canonical = _event(
        "Model stopped generating due to maximum token limit. "
        "The partial message has been added to the conversation history.",
        code="STRANDS_ERROR",
    )

    sanitized = _sanitized_run_error(event, canonical, run_id="r1")

    assert sanitized is not event
    assert sanitized.code == "MAX_TOKENS_REACHED"
    assert "conversation history" not in sanitized.message
    assert "case state" in sanitized.message.lower()


def test_other_strands_errors_remain_generic_and_sanitized():
    event, canonical = _event(
        "Model stopped generating for a different reason.", code="STRANDS_ERROR"
    )

    sanitized = _sanitized_run_error(event, canonical, run_id="r1")

    assert sanitized.code == "AGENT_INTERNAL_ERROR"
    assert "different reason" not in sanitized.message


def test_adapter_detail_is_replaced():
    leak = (
        "ClientError calling bedrock-agentcore at "
        "https://internal.endpoint.example/mcp: arn:aws:iam::111122223333:role/Secret"
    )
    event, canonical = _event(leak, code="SomeLibraryError")

    sanitized = _sanitized_run_error(event, canonical, run_id="r1")

    assert sanitized is not event
    assert sanitized.code == "AGENT_INTERNAL_ERROR"
    assert "internal.endpoint.example" not in sanitized.message
    assert "arn:aws" not in sanitized.message
    assert "111122223333" not in sanitized.message


def test_an_error_with_no_code_is_replaced():
    # The adapter is not obliged to set a code, and an absent one is not ours.
    event, canonical = _event("s3://private-bucket/key exploded", code=None)

    sanitized = _sanitized_run_error(event, canonical, run_id="r1")

    assert sanitized.code == "AGENT_INTERNAL_ERROR"
    assert "private-bucket" not in sanitized.message


def test_the_replacement_still_tells_the_user_what_to_do():
    _, canonical = _event("boom", code="X")
    sanitized = _sanitized_run_error(
        RunErrorEvent(**{"type": EventType.RUN_ERROR, "message": "boom", "code": "X"}),
        canonical,
        run_id="r1",
    )

    assert "case state" in sanitized.message.lower()
    assert sanitized.type == EventType.RUN_ERROR, "it must remain a terminal RUN_ERROR"
