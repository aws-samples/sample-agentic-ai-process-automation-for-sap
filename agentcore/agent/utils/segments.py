# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Fold canonical AG-UI events into persisted trace segments."""

_AGUI_EVENT_TYPES = {
    "TEXT_MESSAGE_CONTENT",
    "TOOL_CALL_START",
    "TOOL_CALL_ARGS",
    "TOOL_CALL_END",
    "TOOL_CALL_RESULT",
}


def _event_type(evt: dict) -> str:
    value = evt.get("type", "")
    return value.value if hasattr(value, "value") else str(value)


def _field(evt: dict, snake_case: str, camel_case: str, default=None):
    return evt.get(snake_case, evt.get(camel_case, default))


def _matching_tool_segment(segments: list, tool_call_id: str | None) -> dict | None:
    for segment in reversed(segments):
        if segment.get("type") != "tool":
            continue
        if tool_call_id is None or segment.get("tool_call_id") == tool_call_id:
            return segment
    return None


def _accumulate_agui_segment(segments: list, evt: dict, event_type: str) -> None:
    if event_type == "TEXT_MESSAGE_CONTENT":
        delta = evt.get("delta", "")
        if not isinstance(delta, str) or not delta:
            return
        if segments and segments[-1].get("type") == "text":
            segments[-1]["content"] += delta
        else:
            segments.append({"type": "text", "content": delta})
        return

    tool_call_id = _field(evt, "tool_call_id", "toolCallId")
    if event_type == "TOOL_CALL_START":
        segments.append(
            {
                "type": "tool",
                "tool_call_id": tool_call_id,
                "tool_name": _field(evt, "tool_call_name", "toolCallName", ""),
                "tool_input": "",
            }
        )
        return

    segment = _matching_tool_segment(segments, tool_call_id)
    if segment is None:
        return

    if event_type == "TOOL_CALL_ARGS":
        # cases.schema.json types tool_input as a string, and CaseTimeline renders it
        # directly as a React child, so the accumulated argument text is stored as-is.
        # Parsing it into a dict here produced a value the schema disallows and the
        # viewer cannot render, and needed a scratch key that leaked whenever a run
        # ended before TOOL_CALL_END.
        delta = evt.get("delta", "")
        if isinstance(delta, str):
            segment["tool_input"] = segment.get("tool_input", "") + delta
    elif event_type == "TOOL_CALL_RESULT":
        segment["tool_result"] = evt.get("content", "")


def accumulate_segment(segments: list, evt: dict) -> None:
    """Fold one canonical AG-UI event into ``segments`` in place."""
    event_type = _event_type(evt)
    if event_type in _AGUI_EVENT_TYPES:
        _accumulate_agui_segment(segments, evt, event_type)
