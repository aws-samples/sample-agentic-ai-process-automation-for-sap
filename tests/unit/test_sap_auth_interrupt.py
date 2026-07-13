# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the SAP auth-interrupt wrapper (agentcore/agent/utils/sap_auth_interrupt).

`parse_auth_required` mirrors the wire-shape contract used by the frontend's
ToolCallDisplay.parseAuthRequired.
"""

import asyncio
import json

import pytest

# sap_auth_interrupt imports strands at module load (agent-runtime code), so skip
# the whole module where strands isn't installed. The frontend mirror
# (parseAuthRequired) has its own separate test.
pytest.importorskip("strands", reason="strands not installed in this env")

from utils.sap_auth_interrupt import parse_auth_required  # noqa: E402

AUTH_RESULT = json.dumps(
    {
        "message": "Sign in to SAP",
        "data": {
            "error_type": "authentication_required",
            "auth_url": "https://idp.example/authorize",
        },
    }
)


class TestParseAuthRequired:
    def test_detects_error_type(self):
        got = parse_auth_required(AUTH_RESULT)
        assert got == {
            "auth_url": "https://idp.example/authorize",
            "message": "Sign in to SAP",
        }

    def test_detects_requires_user_action_flag(self):
        text = json.dumps(
            {"data": {"requires_user_action": True, "auth_url": "https://x/y"}}
        )
        assert parse_auth_required(text)["auth_url"] == "https://x/y"

    def test_normal_result_is_none(self):
        assert parse_auth_required(json.dumps({"data": {"orders": 3}})) is None

    def test_auth_flag_without_url_is_none(self):
        # Auth demanded but no URL to act on → not actionable, treat as normal.
        assert (
            parse_auth_required(
                json.dumps({"data": {"error_type": "authentication_required"}})
            )
            is None
        )

    def test_non_https_auth_url_is_rejected(self):
        # auth_url reaches window.open() on the frontend; a javascript:/data:/http: URL
        # from the semi-trusted MCP server must not pass (XSS sink / downgrade).
        for bad in (
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "http://idp.example/authorize",
            "HTTPS_not_a_scheme",
        ):
            text = json.dumps(
                {"data": {"error_type": "authentication_required", "auth_url": bad}}
            )
            assert parse_auth_required(text) is None, bad

    def test_non_json_is_none(self):
        assert parse_auth_required("all good") is None

    def test_none_is_none(self):
        assert parse_auth_required(None) is None


def _run(coro):
    return asyncio.run(coro)


from strands.types.tools import AgentTool  # noqa: E402


class _InnerTool(AgentTool):
    """Minimal AgentTool stand-in for an MCP tool: auth-required until `vault['ok']`."""

    def __init__(self, vault, calls):
        super().__init__()
        self._vault = vault
        self._calls = calls

    @property
    def tool_name(self):
        return "read_sap"

    @property
    def tool_spec(self):
        return {
            "name": "read_sap",
            "description": "Read SAP",
            "inputSchema": {
                "json": {"type": "object", "properties": {}, "required": []}
            },
        }

    @property
    def tool_type(self):
        return "python"

    async def stream(self, tool_use, invocation_state, **kwargs):
        from strands.types._events import ToolResultEvent

        self._calls["n"] += 1
        text = json.dumps({"data": {"orders": 3}}) if self._vault["ok"] else AUTH_RESULT
        yield ToolResultEvent(
            {
                "toolUseId": tool_use["toolUseId"],
                "status": "success",
                "content": [{"text": text}],
            }
        )


def test_wrapper_interrupts_then_resumes(tmp_path):
    """First run → interrupt with auth_url; resume (vaulted) → tool re-runs, no interrupt."""
    from strands import Agent
    from strands.models.model import Model
    from strands.session.file_session_manager import FileSessionManager
    from utils.sap_auth_interrupt import SapAuthInterruptTool

    vault = {"ok": False}
    calls = {"n": 0}

    class StubModel(Model):
        def get_config(self):
            return {}

        def update_config(self, **k):
            pass

        async def structured_output(self, *a, **k):
            raise NotImplementedError

        async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
            has_result = any(
                isinstance(m.get("content"), list)
                and any("toolResult" in c for c in m["content"])
                for m in messages[-2:]
            )
            yield {"messageStart": {"role": "assistant"}}
            if has_result:
                yield {"contentBlockStart": {"start": {}}}
                yield {"contentBlockDelta": {"delta": {"text": "Done."}}}
                yield {"contentBlockStop": {}}
                yield {"messageStop": {"stopReason": "end_turn"}}
            else:
                tu = {"toolUseId": "tu-1", "name": "read_sap", "input": {}}
                yield {"contentBlockStart": {"start": {"toolUse": tu}}}
                yield {"contentBlockDelta": {"delta": {"toolUse": {"input": "{}"}}}}
                yield {"contentBlockStop": {}}
                yield {"messageStop": {"stopReason": "tool_use"}}

    sdir = str(tmp_path)

    def build():
        a = Agent(
            name="p",
            agent_id="p",
            model=StubModel(),
            tools=[_InnerTool(vault, calls)],
            session_manager=FileSessionManager(session_id="s1", storage_dir=sdir),
            callback_handler=None,
        )
        a.tool_registry.registry["read_sap"] = SapAuthInterruptTool(
            a.tool_registry.registry["read_sap"]
        )
        return a

    async def invoke(agent, prompt):
        result = None
        async for event in agent.stream_async(prompt):
            if isinstance(event, dict) and "result" in event:
                result = event["result"]
        return result

    async def scenario():
        r1 = await invoke(build(), "read my SAP orders")
        assert r1.stop_reason == "interrupt"
        intr = r1.interrupts[0]
        assert intr.reason["auth_url"].startswith("https://")

        # User signs in → vault populates. Fresh agent restores interrupt state from session.
        vault["ok"] = True
        a2 = build()
        assert a2._interrupt_state.activated, (
            "interrupt state not restored across re-instantiation"
        )
        r2 = await invoke(
            a2, [{"interruptResponse": {"interruptId": intr.id, "response": "ok"}}]
        )
        assert r2.stop_reason == "end_turn"
        assert calls["n"] == 2  # tool ran once before interrupt, once on resume

    _run(scenario())


def test_loop_guard_no_reinterrupt(tmp_path):
    """If auth STILL fails on resume, the wrapper does NOT interrupt again for the same tool."""
    from strands import Agent
    from strands.models.model import Model
    from strands.session.file_session_manager import FileSessionManager
    from utils.sap_auth_interrupt import SapAuthInterruptTool

    vault = {"ok": False}  # never flips — models a sign-in that never succeeds
    calls = {"n": 0}

    class StubModel(Model):
        def get_config(self):
            return {}

        def update_config(self, **k):
            pass

        async def structured_output(self, *a, **k):
            raise NotImplementedError

        async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
            has_result = any(
                isinstance(m.get("content"), list)
                and any("toolResult" in c for c in m["content"])
                for m in messages[-2:]
            )
            yield {"messageStart": {"role": "assistant"}}
            if has_result:
                yield {"contentBlockStart": {"start": {}}}
                yield {"contentBlockDelta": {"delta": {"text": "Done."}}}
                yield {"contentBlockStop": {}}
                yield {"messageStop": {"stopReason": "end_turn"}}
            else:
                tu = {"toolUseId": "tu-1", "name": "read_sap", "input": {}}
                yield {"contentBlockStart": {"start": {"toolUse": tu}}}
                yield {"contentBlockDelta": {"delta": {"toolUse": {"input": "{}"}}}}
                yield {"contentBlockStop": {}}
                yield {"messageStop": {"stopReason": "tool_use"}}

    sdir = str(tmp_path)

    def build():
        a = Agent(
            name="p",
            agent_id="p",
            model=StubModel(),
            tools=[_InnerTool(vault, calls)],
            session_manager=FileSessionManager(session_id="s2", storage_dir=sdir),
            callback_handler=None,
        )
        a.tool_registry.registry["read_sap"] = SapAuthInterruptTool(
            a.tool_registry.registry["read_sap"]
        )
        return a

    async def invoke(agent, prompt):
        result = None
        async for event in agent.stream_async(prompt):
            if isinstance(event, dict) and "result" in event:
                result = event["result"]
        return result

    async def scenario():
        r1 = await invoke(build(), "read my SAP orders")
        assert r1.stop_reason == "interrupt"
        intr = r1.interrupts[0]
        r2 = await invoke(
            build(), [{"interruptResponse": {"interruptId": intr.id, "response": "ok"}}]
        )
        assert r2.stop_reason != "interrupt", (
            "LOOP: re-interrupted the same tool_use on resume"
        )

    _run(scenario())


def test_plaintext_prompt_on_interrupted_session_raises(tmp_path):
    """If a turn is paused on an interrupt and the next invocation on the SAME session
    sends a plain-text prompt (user ignored the sign-in banner and typed a new question)
    instead of an interruptResponse, Strands raises. Callers must rotate to a fresh
    session for that new turn (see WorkspacePage.sendMessage in the frontend)."""
    from strands import Agent
    from strands.models.model import Model
    from strands.session.file_session_manager import FileSessionManager
    from utils.sap_auth_interrupt import SapAuthInterruptTool

    vault = {"ok": False}
    calls = {"n": 0}

    class StubModel(Model):
        def get_config(self):
            return {}

        def update_config(self, **k):
            pass

        async def structured_output(self, *a, **k):
            raise NotImplementedError

        async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
            yield {"messageStart": {"role": "assistant"}}
            tu = {"toolUseId": "tu-1", "name": "read_sap", "input": {}}
            yield {"contentBlockStart": {"start": {"toolUse": tu}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": "{}"}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}

    sdir = str(tmp_path)

    def build():
        a = Agent(
            name="p",
            agent_id="p",
            model=StubModel(),
            tools=[_InnerTool(vault, calls)],
            session_manager=FileSessionManager(session_id="s3", storage_dir=sdir),
            callback_handler=None,
        )
        a.tool_registry.registry["read_sap"] = SapAuthInterruptTool(
            a.tool_registry.registry["read_sap"]
        )
        return a

    async def invoke(agent, prompt):
        result = None
        async for event in agent.stream_async(prompt):
            if isinstance(event, dict) and "result" in event:
                result = event["result"]
        return result

    async def scenario():
        r1 = await invoke(build(), "read my SAP orders")
        assert r1.stop_reason == "interrupt"
        # Same session, plain-text prompt instead of an interruptResponse → must raise.
        with pytest.raises(TypeError, match="interrupt"):
            await invoke(build(), "actually, what's the weather?")

    _run(scenario())
