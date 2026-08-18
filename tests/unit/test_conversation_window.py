# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""The conversation window, and the cross-SDK offset bug it works around.

``removed_message_count`` means two different things to the two SDKs that share it:
Strands counts messages the agent appended, AgentCore Memory applies it to a list
already stripped of tool blocks. The first test reproduces the resulting data loss
directly against the real ``_filter_restored_tool_context``, so it fails if the SDK
ever fixes the ordering (at which point ``MemorySafeSlidingWindow`` can go).

``utils.conversation`` imports only strands, so unlike basic_agent.py it is
importable here. The wiring in ``_create_agent`` is pinned as source text (same
constraint as test_memory_session_config.py).
"""

import re
from pathlib import Path

from strands.agent.conversation_manager import SlidingWindowConversationManager
from utils.conversation import MemorySafeSlidingWindow

_AGENT = Path(__file__).resolve().parents[2] / "agentcore" / "agent" / "basic_agent.py"


def _tool_heavy_history(pairs: int) -> list[dict]:
    """`pairs` investigation rounds: a tool call and its result, then a text answer."""
    messages: list[dict] = [{"role": "user", "content": [{"text": "process case 42"}]}]
    for i in range(pairs):
        messages.append(
            {
                "role": "assistant",
                "content": [
                    {
                        "toolUse": {
                            "toolUseId": f"t{i}",
                            "name": "odata_read",
                            "input": {},
                        }
                    }
                ],
            }
        )
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "toolResult": {
                            "toolUseId": f"t{i}",
                            "status": "success",
                            # Over 2 * _PRESERVE_CHARS (200), or truncation is a no-op.
                            "content": [{"text": "x" * 1200}],
                        }
                    }
                ],
            }
        )
        messages.append({"role": "assistant", "content": [{"text": f"step {i} done"}]})
    return messages


def test_a_nonzero_offset_would_discard_restored_history():
    """Why the offset is suppressed: the two SDKs count different message spaces.

    AgentCoreMemorySessionManager.list_messages filters tool blocks and THEN slices
    messages[offset:]. Feeding it a count taken over unfiltered messages skips past
    the end of the filtered list — the case's whole history, dropped with no error.
    """
    from bedrock_agentcore.memory.integrations.strands.session_manager import (
        AgentCoreMemorySessionManager,
    )
    from strands.types.session import SessionMessage

    messages = _tool_heavy_history(pairs=6)
    stored = [SessionMessage.from_message(m, i) for i, m in enumerate(messages)]

    filtered = AgentCoreMemorySessionManager._filter_restored_tool_context(
        object.__new__(AgentCoreMemorySessionManager), stored
    )
    assert len(filtered) < len(stored), (
        "filter_restored_tool_context no longer drops tool blocks — re-check whether "
        "the offset mismatch MemorySafeSlidingWindow works around still exists"
    )

    # Run one eviction to get a real count, then persist it the way sync_agent does.
    window = MemorySafeSlidingWindow(window_size=4)
    agent = type("_A", (), {"messages": list(messages)})()
    window.apply_management(agent)
    state = window.get_state()

    assert state["removed_message_count"] > 0, (
        "window_size=4 over 19 messages must evict — the test setup is wrong"
    )
    assert filtered[state["removed_message_count"] :] == [], (
        "the offset happens to stay in range here, so this test no longer demonstrates "
        "the failure it guards; re-derive it against a longer history"
    )

    # What the next invocation actually restores with.
    resumed = MemorySafeSlidingWindow(window_size=120)
    resumed.restore_from_session(state)
    assert resumed.removed_message_count == 0, (
        "restore must report 0 to list_messages, or the offset over-skips the filtered "
        "list and the session resumes with no history"
    )
    assert filtered[resumed.removed_message_count :] == filtered


def test_restore_survives_state_written_by_the_bare_default():
    # The agent ran on the silent default, so every live session's persisted state
    # says SlidingWindowConversationManager. ConversationManager.restore_from_session
    # raises ValueError on a __name__ mismatch, so a rename would break every resume.
    written_before = SlidingWindowConversationManager(window_size=40)
    written_before.removed_message_count = 7

    restored = MemorySafeSlidingWindow(window_size=120)
    restored.restore_from_session(written_before.get_state())

    assert restored.removed_message_count == 0


def test_state_written_by_the_subclass_restores_into_the_base_class():
    # ...and the reverse, so rolling this change back does not strand the sessions
    # written while it was deployed.
    written_after = MemorySafeSlidingWindow(window_size=120)
    written_after.removed_message_count = 3

    rolled_back = SlidingWindowConversationManager(window_size=40)
    rolled_back.restore_from_session(written_after.get_state())

    assert rolled_back.removed_message_count == 3


def test_truncating_tool_results_does_not_count_as_eviction():
    """The lever the window actually relies on, and why it is safe.

    An oversized tool result is what blows the context window, and reduce_context
    truncates the oldest one instead of evicting messages — leaving both the cache
    prefix and removed_message_count untouched.
    """
    messages = _tool_heavy_history(pairs=2)
    window = MemorySafeSlidingWindow(window_size=120, should_truncate_results=True)
    agent = type("_A", (), {"messages": messages})()

    window.reduce_context(agent, e=RuntimeError("context overflow"))

    assert len(agent.messages) == 7, "no message should have been evicted"
    assert window.removed_message_count == 0
    assert "[truncated:" in str(agent.messages[2]), "the oldest tool result must shrink"


def _create_agent_source() -> str:
    text = _AGENT.read_text()
    start = text.index("def _create_agent(")
    return text[start : text.index("\ndef ", start + 1)]


def test_the_agent_states_its_conversation_manager():
    # Agent() defaults to SlidingWindowConversationManager(window_size=40) when none is
    # passed, and ag_ui_strands._extract_agent_kwargs DOES forward conversation_manager
    # to the per-thread clone — so an unset manager is not "no management", it is
    # unstated management on the agent that serves the turn.
    source = _create_agent_source()
    match = re.search(
        r"conversation_manager=MemorySafeSlidingWindow\(\s*window_size=(\d+)", source
    )
    assert match, "_create_agent must pass MemorySafeSlidingWindow explicitly"
    assert int(match.group(1)) > 40, (
        "a window at or below the Strands default re-introduces routine mid-run "
        "eviction, which moves the cached prompt prefix and re-triggers the restore "
        "offset mismatch"
    )
