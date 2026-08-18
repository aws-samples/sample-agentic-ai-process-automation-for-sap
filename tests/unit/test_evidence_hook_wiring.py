# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Source-text pins on the evidence hook's wiring.

basic_agent.py imports strands/mcp and cannot be imported in this environment
(same constraint as test_memory_session_config.py and test_adapter_version_pin.py),
so these assert on the source text. They are cheap tripwires: if the callback
registration or the env var is dropped, every tool call silently loses provenance
and the UI degrades to today's rendering with no error anywhere.
"""

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_AGENT = _ROOT / "agentcore" / "agent" / "basic_agent.py"
_STACK = _ROOT / "cdk" / "lib" / "backend-stack.ts"


def test_after_tool_call_event_is_imported_from_strands_hooks():
    text = _AGENT.read_text()
    match = re.search(r"from strands\.hooks import \((?P<names>.*?)\)", text, re.DOTALL)
    assert match, "the strands.hooks import block moved"
    assert "AfterToolCallEvent" in match.group("names")


def test_the_evidence_callback_is_registered_on_the_adapters_clone():
    # ag-ui-strands clones the agent per thread; a callback registered anywhere
    # other than the HookProvider passed to StrandsAgent(hooks=[...]) never fires.
    text = _AGENT.read_text()
    start = text.index("class _Hooks(HookProvider)")
    end = text.index("hook_provider = _Hooks()", start)
    assert re.search(
        r"registry\.add_callback\(\s*AfterToolCallEvent,\s*evidence_hook\.on_tool_call",
        text[start:end],
    ), "AfterToolCallEvent must be registered inside _Hooks.register_hooks"


def test_the_evidence_hook_resets_per_invocation():
    text = _AGENT.read_text()
    start = text.index("class _Hooks(HookProvider)")
    end = text.index("hook_provider = _Hooks()", start)
    assert re.search(
        r"registry\.add_callback\(\s*BeforeInvocationEvent,\s*evidence_hook\.on_start",
        text[start:end],
    ), "without a per-invocation reset, evidence leaks across runs on a warm container"


def test_create_agent_returns_the_evidence_hook():
    text = _AGENT.read_text()
    start = text.index("def _create_agent(")
    body = text[start : text.index("\ndef ", start + 1)]
    assert re.search(
        r"return agent, metrics_hook, turns_hook, session_manager, hook_provider, evidence_hook",
        body,
    ), "_create_agent must hand the evidence hook to the run loop"


def test_tool_failure_status_is_stamped_onto_the_streamed_result():
    # AG-UI has no failure field on TOOL_CALL_RESULT, and the hook is the only place
    # ToolResult.status exists mid-stream. Drop this and a failed tool renders with a
    # green check until the page reloads and reads the persisted segment.status.
    text = _AGENT.read_text()
    start = text.index("async for kind, item in _with_keepalive(")
    body = text[start : text.index("if not terminal_emitted:", start)]
    assert re.search(
        r'event_name == "TOOL_CALL_RESULT".*?'
        r'status_for\(canonical\.get\("toolCallId"\)\) == "error".*?'
        r'model_copy\(update=\{"status": "error"\}\)',
        body,
        re.DOTALL,
    ), "the stream loop must stamp ToolResult.status onto TOOL_CALL_RESULT"


def test_the_extra_status_field_survives_the_agui_encoder():
    # ag_ui's models are `extra: allow`, which is what makes the stamp above possible.
    # A future SDK that forbids extras would drop the field silently on the wire.
    from ag_ui.core import EventType, ToolCallResultEvent
    from ag_ui.encoder import EventEncoder

    event = ToolCallResultEvent(
        type=EventType.TOOL_CALL_RESULT,
        tool_call_id="t1",
        message_id="m1",
        content="Error: 403",
    ).model_copy(update={"status": "error"})
    assert '"status":"error"' in EventEncoder().encode(event)


def test_the_cedar_enforcement_mode_reaches_the_agent_runtime():
    # authz.mode has no runtime source without this: cedar_enforcement_mode flows
    # only into the PolicyEngine custom resource today.
    text = _STACK.read_text()
    start = text.index("const envVars: { [key: string]: string } = {")
    end = text.index("}", text.index("DEMO_ENABLED", start))
    assert "CEDAR_ENFORCEMENT_MODE" in text[start:end], (
        "CEDAR_ENFORCEMENT_MODE must be in the agent runtime envVars map"
    )
