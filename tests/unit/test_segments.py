# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Trace segment folding.

`types/cases.schema.json` types `tool_input` as a string, and the case timeline passes
it straight into a React child, so a dict there both violates the schema and cannot
render. These tests pin the type and the absence of any scratch key.
"""

import json

from utils.segments import accumulate_segment


def _tool_call(tool_call_id="t1", name="odata_read", deltas=(), result=None, end=True):
    events = [
        {"type": "TOOL_CALL_START", "toolCallId": tool_call_id, "toolCallName": name},
    ]
    for delta in deltas:
        events.append(
            {"type": "TOOL_CALL_ARGS", "toolCallId": tool_call_id, "delta": delta}
        )
    if end:
        events.append({"type": "TOOL_CALL_END", "toolCallId": tool_call_id})
    if result is not None:
        events.append(
            {"type": "TOOL_CALL_RESULT", "toolCallId": tool_call_id, "content": result}
        )
    return events


def _fold(events):
    segments: list = []
    for event in events:
        accumulate_segment(segments, event)
    return segments


def test_tool_input_is_a_string_matching_the_schema():
    segments = _fold(_tool_call(deltas=['{"doc":', '"4500012345"}']))

    (segment,) = segments
    assert isinstance(segment["tool_input"], str), (
        "cases.schema.json types this as a string"
    )
    assert json.loads(segment["tool_input"]) == {"doc": "4500012345"}


def test_unparseable_arguments_keep_the_same_type():
    # The bug this replaces: parseable args produced a dict and unparseable ones a
    # string, so consumers saw two different types in the same field.
    segments = _fold(_tool_call(deltas=["not json at all"]))

    assert isinstance(segments[0]["tool_input"], str)
    assert segments[0]["tool_input"] == "not json at all"


def test_no_scratch_key_survives_a_completed_tool_call():
    segments = _fold(_tool_call(deltas=['{"a":1}'], result="ok"))

    assert "tool_input_raw" not in segments[0]


def test_no_scratch_key_survives_a_run_that_ends_mid_arguments():
    # A run cancelled or failed between TOOL_CALL_ARGS and TOOL_CALL_END used to
    # persist the accumulator alongside the real field.
    segments = _fold(_tool_call(deltas=['{"partial":'], end=False))

    assert "tool_input_raw" not in segments[0]
    assert segments[0]["tool_input"] == '{"partial":'


def test_arguments_accumulate_across_deltas_in_order():
    segments = _fold(_tool_call(deltas=["a", "b", "c"]))

    assert segments[0]["tool_input"] == "abc"


def test_result_is_recorded_against_the_matching_call():
    segments = _fold(
        _tool_call(tool_call_id="one", deltas=['{"x":1}'], result="first")
        + _tool_call(tool_call_id="two", deltas=['{"y":2}'], result="second")
    )

    assert [s["tool_result"] for s in segments] == ["first", "second"]
    assert [s["tool_call_id"] for s in segments] == ["one", "two"]


def test_text_deltas_fold_into_one_segment():
    segments = _fold(
        [
            {"type": "TEXT_MESSAGE_CONTENT", "delta": "Hello "},
            {"type": "TEXT_MESSAGE_CONTENT", "delta": "world"},
        ]
    )

    assert segments == [{"type": "text", "content": "Hello world"}]


def test_text_after_a_tool_call_starts_a_new_segment():
    segments = _fold(
        _tool_call(deltas=['{"a":1}'], result="ok")
        + [{"type": "TEXT_MESSAGE_CONTENT", "delta": "done"}]
    )

    assert [s["type"] for s in segments] == ["tool", "text"]
