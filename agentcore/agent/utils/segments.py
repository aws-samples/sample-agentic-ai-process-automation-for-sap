# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Fold Strands stream events into trace segments for DynamoDB persistence."""


def accumulate_segment(segments: list, evt: dict) -> None:
    """Fold one stream event into the trace segment list (mutates `segments`).

    Text deltas coalesce into the trailing text segment. A tool-use start opens
    a tool segment; its result and final input arrive in later events and are
    back-filled onto the matching segment.
    """
    if "data" in evt:
        if segments and segments[-1]["type"] == "text":
            segments[-1]["content"] += evt["data"]
        else:
            segments.append({"type": "text", "content": evt["data"]})
    elif "current_tool_use" in evt and evt.get("delta", {}).get("toolUse", {}).get("input") == "":
        # Tool start — create segment, will be filled by tool_result
        tu = evt["current_tool_use"]
        segments.append({"type": "tool", "tool_name": tu.get("name", ""), "tool_input": {}})
    elif "tool_result" in evt and segments and segments[-1]["type"] == "tool":
        segments[-1]["tool_result"] = evt["tool_result"].get("content", "")
    elif "message" in evt and evt["message"].get("role") == "assistant":
        # Complete assistant message has final tool input
        content = evt["message"].get("content", [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and "toolUse" in block:
                    tu = block["toolUse"]
                    # Find the matching segment by name and fill input
                    for seg in reversed(segments):
                        if seg["type"] == "tool" and seg["tool_name"] == tu.get("name") and not seg.get("tool_input"):
                            seg["tool_input"] = tu.get("input", {})
                            break
