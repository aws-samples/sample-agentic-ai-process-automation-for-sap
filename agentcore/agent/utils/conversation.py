# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Conversation window for the ERP agent, minus one cross-SDK offset bug.

Strands and the AgentCore Memory session manager disagree about what
``removed_message_count`` counts, and the disagreement silently deletes history:

* ``RepositorySessionManager.initialize`` restores by calling
  ``list_messages(offset=agent.conversation_manager.removed_message_count)`` — an
  offset into the messages the agent actually appended.
* ``AgentCoreMemorySessionManager.list_messages`` runs
  ``_filter_restored_tool_context`` (dropping every toolUse/toolResult block, and
  any message left with no content) *before* slicing ``messages[offset:]``.

So the offset is counted in unfiltered messages and applied to a filtered list.
Trimming evicts old, tool-heavy messages — exactly the ones filtering removes — so
the offset always over-skips, and a tool-heavy session can resume with no history
at all. Reporting 0 instead turns that into restoring slightly more than was
evicted, which the next ``apply_management`` re-trims. Extra context costs a cache
write; lost context makes the agent re-derive a case it already investigated.

Only the restore offset is suppressed. Eviction itself, and the state Strands
persists, are unchanged.
"""

from __future__ import annotations

from typing import Any

from strands.agent.conversation_manager import SlidingWindowConversationManager


class MemorySafeSlidingWindow(SlidingWindowConversationManager):
    """Sliding window that never asks AgentCore Memory to skip restored messages.

    Drop this subclass once ``filter_restored_tool_context`` and
    ``removed_message_count`` agree on a message space — either because the flag is
    off, or because ``list_messages`` slices before it filters.
    """

    # ConversationManager.restore_from_session raises ValueError when the persisted
    # `__name__` is not this class's own name, and the agent has been running on the
    # bare default, so every live session's state says SlidingWindowConversationManager.
    # Persisting the base name keeps both directions readable: sessions written before
    # this class restore into it, and sessions written by it survive a rollback.
    _PERSISTED_NAME = SlidingWindowConversationManager.__name__

    def get_state(self) -> dict[str, Any]:
        return {**super().get_state(), "__name__": self._PERSISTED_NAME}

    def restore_from_session(self, state: dict[str, Any]) -> list | None:
        result = super().restore_from_session(
            {**state, "__name__": type(self).__name__}
        )
        # initialize() reads removed_message_count immediately after this returns,
        # so zeroing here is what reaches list_messages(offset=...).
        self.removed_message_count = 0
        return result
