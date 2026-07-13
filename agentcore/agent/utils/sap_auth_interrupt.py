# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Turn a SAP MCP `authentication_required` tool result into a Strands interrupt.

The external AWS-for-SAP MCP server (USER_FEDERATION / 3LO) does not fail the
tool call when a per-user login is missing — it returns a NORMAL result
(`isError:false`) whose JSON body carries `{data:{error_type:"authentication_required",
auth_url:...}}`. The auth demand therefore only exists *after* the tool runs, which
rules out a `BeforeToolCallEvent` hook (and `AfterToolCallEvent` is not interruptible).

So we wrap each MCP tool in an AgentTool that runs the underlying tool, inspects the
result, and — when auth is required — raises an interrupt via `ToolContext.interrupt`.
Strands stops the event loop with `stop_reason="interrupt"` and persists the interrupt
state through the session manager. After the user signs in, the runtime is re-invoked
with an `interruptResponse`; the SAME tool body re-runs (now the token is vaulted) and
the agent continues the same turn — no fresh prompt, no lost SOP position.

Loop-guard: on resume `ctx.interrupt(...)` RETURNS the response instead of raising, so a
still-failing auth (e.g. the vault genuinely didn't populate) falls through to the normal
(failing) tool result rather than interrupting forever.
"""

import json

from strands.interrupt import InterruptException
from strands.tools.mcp.mcp_agent_tool import MCPAgentTool
from strands.types._events import ToolInterruptEvent, ToolResultEvent
from strands.types.tools import AgentTool, ToolContext

# Interrupt name is per-tool-use-unique via ToolContext._interrupt_id, so a fixed
# label is fine and keeps the resume id deterministic across re-invocations.
_INTERRUPT_NAME = "sap_auth"


def parse_auth_required(text: str | None) -> dict | None:
    """Return `{auth_url, message}` when a tool-result string signals SAP sign-in.

    Mirrors the frontend `parseAuthRequired` (ToolCallDisplay.tsx) so both ends agree on
    the wire shape. Returns None for anything else (non-JSON, normal results).
    """
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    data = parsed.get("data")
    if not isinstance(data, dict):
        return None
    auth_url = data.get("auth_url")
    is_auth_required = (
        data.get("error_type") == "authentication_required"
        or data.get("requires_user_action") is True
    )
    # Only https: this value comes from a semi-trusted external MCP server and reaches
    # window.open() on the frontend, where a javascript:/data: URL would be an XSS sink.
    if not is_auth_required or not isinstance(auth_url, str):
        return None
    if not auth_url.lower().startswith("https://"):
        return None
    msg = parsed.get("message")
    return {"auth_url": auth_url, "message": msg if isinstance(msg, str) else None}


def _result_text(tool_result: dict) -> str:
    """Concatenate the text blocks of a ToolResult's content (matches frontend join)."""
    parts = []
    for block in tool_result.get("content") or []:
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "".join(parts)


class SapAuthInterruptTool(AgentTool):
    """Wraps an MCP tool; converts an `authentication_required` result into an interrupt."""

    def __init__(self, inner: AgentTool):
        super().__init__()
        self._inner = inner

    @property
    def tool_name(self) -> str:
        return self._inner.tool_name

    @property
    def tool_spec(self):
        return self._inner.tool_spec

    @property
    def tool_type(self) -> str:
        return self._inner.tool_type

    async def stream(self, tool_use, invocation_state, **kwargs):
        # Run the underlying tool, capturing its final result (forwarding any sub-events).
        final = None
        async for ev in self._inner.stream(tool_use, invocation_state, **kwargs):
            if isinstance(ev, ToolResultEvent):
                final = ev.tool_result
            else:
                yield ev

        auth = parse_auth_required(_result_text(final)) if final else None
        if auth is not None and "agent" in invocation_state:
            ctx = ToolContext(
                tool_use=tool_use,
                agent=invocation_state["agent"],
                invocation_state=invocation_state,
            )
            try:
                # First run: raises → event loop stops with stop_reason="interrupt".
                # Resume: returns (response already set) → loop-guard, fall through below.
                ctx.interrupt(_INTERRUPT_NAME, reason=auth)
            except InterruptException as e:
                yield ToolInterruptEvent(tool_use, [e.interrupt])
                return

        # No auth needed, or resuming with auth still unresolved: return the result as-is.
        if final is not None:
            yield ToolResultEvent(final)


def wrap_sap_auth_tools(agent) -> int:
    """Replace MCP tools in the agent's registry with auth-interrupt wrappers.

    Call AFTER the Gateway `target___` rename in basic_agent so wrappers inherit the
    bare tool names. Directly mutates the registry (same pattern as the rename loop).
    Returns the number of tools wrapped.
    """
    registry = agent.tool_registry.registry
    wrapped = 0
    for name, tool in list(registry.items()):
        if isinstance(tool, MCPAgentTool):
            registry[name] = SapAuthInterruptTool(tool)
            wrapped += 1
    return wrapped
