# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Self-check for the stream→trace segment parser (accumulate_segment).

Run: python utils/test_segments.py
Feeds a canned event sequence mirroring a real Strands stream and asserts the
resulting segment shape. Fails loudly if the event-folding logic breaks.
"""

from segments import accumulate_segment


def _run(events: list) -> list:
    segments: list = []
    for evt in events:
        accumulate_segment(segments, evt)
    return segments


def test_text_deltas_coalesce():
    segs = _run([{"data": "Hello "}, {"data": "world"}])
    assert segs == [{"type": "text", "content": "Hello world"}], segs


def test_tool_lifecycle():
    # start → text delta after → result → final assistant message with input
    events = [
        {"current_tool_use": {"name": "get_case_state"}, "delta": {"toolUse": {"input": ""}}},
        {"tool_result": {"content": "case data"}},
        {"message": {"role": "assistant", "content": [
            {"toolUse": {"name": "get_case_state", "input": {"case_id": "141#1"}}}
        ]}},
    ]
    segs = _run(events)
    assert len(segs) == 1, segs
    assert segs[0] == {
        "type": "tool",
        "tool_name": "get_case_state",
        "tool_input": {"case_id": "141#1"},
        "tool_result": "case data",
    }, segs


def test_text_then_tool_then_text():
    events = [
        {"data": "Looking up. "},
        {"current_tool_use": {"name": "odata_read"}, "delta": {"toolUse": {"input": ""}}},
        {"tool_result": {"content": "rows"}},
        {"data": "Done."},
    ]
    segs = _run(events)
    assert [s["type"] for s in segs] == ["text", "tool", "text"], segs
    assert segs[0]["content"] == "Looking up. "
    assert segs[1]["tool_result"] == "rows"
    assert segs[2]["content"] == "Done."


def test_final_message_fills_correct_tool_by_name():
    # Two tools of different names; final message input must land on the match.
    events = [
        {"current_tool_use": {"name": "get_case_state"}, "delta": {"toolUse": {"input": ""}}},
        {"tool_result": {"content": "a"}},
        {"current_tool_use": {"name": "update_case_state"}, "delta": {"toolUse": {"input": ""}}},
        {"tool_result": {"content": "b"}},
        {"message": {"role": "assistant", "content": [
            {"toolUse": {"name": "update_case_state", "input": {"status": "closed"}}},
        ]}},
    ]
    segs = _run(events)
    assert segs[0]["tool_input"] == {}, segs        # untouched
    assert segs[1]["tool_input"] == {"status": "closed"}, segs


def test_partial_tool_delta_ignored():
    # A current_tool_use with non-empty input (mid-stream) must not open a segment.
    segs = _run([{"current_tool_use": {"name": "x"}, "delta": {"toolUse": {"input": "{\"a\""}}}])
    assert segs == [], segs


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("all segment-parser checks passed")
