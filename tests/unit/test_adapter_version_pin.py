# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""A tripwire on the ag-ui-strands pin.

Three things in this codebase are correct only because of adapter behaviour that is
not part of any documented contract:

1. `aguiReducer.applyMessagesSnapshot` ASSIGNS assistant content rather than
   appending it, and every MESSAGES_SNAPSHOT carries the whole accumulated message
   list. That is safe only because the adapter issues a fresh message id after each
   snapshot splice. An adapter that reused an id would silently truncate assistant
   text to the latest fragment — no error, just missing output.
2. `basic_agent` constructs `StrandsAgent` AFTER `_create_agent`, because the adapter
   captures the tool registry at init and `_create_agent` is what strips the
   `target___` prefix from SAP tool names. Reversing the order exposes prefixed
   names that no longer match the names SOPs reference.
3. The adapter has NO interrupt handling at all, which is why `SAP_AUTH_INTERRUPT`
   defaults off and why `HumanInTheLoop` is not wired. An interrupt raised inside the
   adapter is swallowed and the run reports success. When this stops being true, both
   decisions are worth revisiting.

A fourth thing is worth knowing when re-verifying: 0.2.3 added frontend-tool result
reconciliation (a durable wire->native id map plus session-repository rewrites of the
"Forwarded to client" placeholder). All of it is gated on
`replay_history_into_strands`, which `basic_agent` sets to False, and we declare no
AG-UI client tools — so none of it is reachable here. If either changes, that path
becomes live and needs its own verification.

None is exercised by our own tests, so the pin is asserted here. Where the
behaviour is visible in the installed adapter's source, it is also checked directly —
a pin assertion alone would keep passing if the pinned wheel were ever re-cut, and it
tells a reader nothing about what to look for when the pin does move. When these fail,
re-verify both behaviours against the new version and update VERIFIED_VERSION.
"""

import inspect
import re
from pathlib import Path

import pytest

VERIFIED_VERSION = "0.2.3"

_REQUIREMENTS = (
    Path(__file__).resolve().parents[2] / "agentcore" / "agent" / "requirements.txt"
)


def _pinned(package: str) -> str | None:
    for line in _REQUIREMENTS.read_text().splitlines():
        match = re.fullmatch(rf"{re.escape(package)}==([\w.]+)", line.strip())
        if match:
            return match.group(1)
    return None


def test_ag_ui_strands_is_pinned_to_the_verified_version():
    pinned = _pinned("ag-ui-strands")

    assert pinned is not None, "ag-ui-strands must stay pinned, not floating"
    assert pinned == VERIFIED_VERSION, (
        f"ag-ui-strands moved {VERIFIED_VERSION} -> {pinned}. Re-verify that the adapter "
        f"still issues a fresh message id per MESSAGES_SNAPSHOT splice (otherwise "
        f"aguiReducer.applyMessagesSnapshot truncates assistant text) and that tool "
        f"renames still survive its per-thread agent clone, then update VERIFIED_VERSION."
    )


def test_the_protocol_package_is_pinned_too():
    # The reducer switches on AG-UI event type names, so the event vocabulary is a
    # contract as much as the adapter's behaviour is.
    assert _pinned("ag-ui-protocol") is not None, "ag-ui-protocol must stay pinned"


def _adapter_source() -> str:
    """Source of the installed adapter's agent module.

    Skipped rather than failed when absent: the agent extra is optional, and this
    file's pin assertions above are the part that must run everywhere.
    """
    agent_module = pytest.importorskip("ag_ui_strands.agent")
    return inspect.getsource(agent_module)


def test_the_adapter_still_rotates_the_message_id_after_a_snapshot():
    """Behaviour 1, checked in the installed adapter rather than assumed from the pin.

    Every splice that appends an AssistantMessage and emits a snapshot must also
    retire the id it just committed, or the next text block reuses it and
    applyMessagesSnapshot — which assigns, not appends — overwrites the committed
    text with the newer fragment.
    """
    source = _adapter_source()
    splices = source.count("MessagesSnapshotEvent(")
    rotations = source.count("message_id = str(uuid.uuid4())")

    assert rotations >= 2, (
        "the adapter no longer rotates message_id via uuid4 after committing assistant "
        "text to a snapshot. aguiReducer.applyMessagesSnapshot ASSIGNS content, so a "
        "reused id silently truncates assistant output to the latest fragment."
    )
    assert splices, (
        "no MessagesSnapshotEvent emission found — the adapter shape changed"
    )


def test_the_adapter_still_has_no_interrupt_handling():
    """Behaviour 3: the reason two interrupt-based features are deliberately not wired.

    `SapAuthInterruptTool` is env-gated off and `HumanInTheLoop` is not adopted, both
    because a Strands interrupt has nowhere to surface through this adapter — no
    `stop_reason == "interrupt"` mapping, no resume event, so the run appears to finish
    normally with the demand silently dropped. Upstream PR #1816 would add it.

    Asserted as an absence, which is unusual, because it is the absence that the
    frontend's replay-a-turn workaround exists to compensate for. When this fails, the
    adapter grew interrupt support: re-evaluate `SAP_AUTH_INTERRUPT` and
    `.backlog/resumable-hitl-approval-interrupt.md` rather than just deleting the test.
    """
    package = pytest.importorskip("ag_ui_strands")
    root = Path(package.__file__).parent

    handling = [
        f"{path.name}:{number}:{line.strip()}"
        for path in sorted(root.rglob("*.py"))
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if "interrupt" in line.lower()
        # KeyboardInterrupt in a BaseException comment is not interrupt handling.
        and "KeyboardInterrupt" not in line
    ]

    assert not handling, (
        "ag-ui-strands now mentions interrupts: "
        + "; ".join(handling)
        + ". If it can surface stop_reason == 'interrupt' and accept a resume, the "
        "frontend replay workaround in useAgentChat.ts can become a real resume, "
        "SAP_AUTH_INTERRUPT can default on, and HumanInTheLoop becomes adoptable."
    )


def test_the_adapter_captures_the_tool_registry_at_init():
    """Behaviour 2: why basic_agent builds StrandsAgent AFTER _create_agent.

    The adapter copies the template's tool registry in __init__, so tools registered
    or renamed after construction never reach the per-thread clone. _create_agent is
    what strips the `target___` prefix, so reversing the order exposes prefixed names
    that no longer match the names SOPs reference.
    """
    strands_agent = pytest.importorskip("ag_ui_strands").StrandsAgent
    init_source = inspect.getsource(strands_agent.__init__)

    assert "tool_registry.registry" in init_source, (
        "StrandsAgent.__init__ no longer reads the template's tool_registry. Re-check "
        "whether basic_agent may now construct the adapter before _create_agent, and "
        "whether the target___ prefix stripping still reaches the per-thread agent."
    )
