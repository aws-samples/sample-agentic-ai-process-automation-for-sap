# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Pins that the agent's AgentCore Memory session strips restored tool payloads.

Without ``filter_restored_tool_context=True``, resuming a case's Memory session
reloads every historical toolUse/toolResult blob into context — including large
SAP OData responses — on every turn. This is a one-line SDK config flag, not
custom logic, so the test simply pins that the flag is present and set True in
the ``AgentCoreMemoryConfig(...)`` construction inside ``_create_agent``.
"""

import re
from pathlib import Path

_AGENT = Path(__file__).resolve().parents[2] / "agentcore" / "agent" / "basic_agent.py"


def _create_agent_source() -> str:
    """Slice out just the _create_agent function body by textual bounds.

    basic_agent.py imports strands/mcp and cannot be imported directly in this
    test environment (see test_stream_keepalive.py, test_direct_topology_bearer.py
    for the same constraint). AST-slicing a single keyword argument out of a
    constructor call inside a much larger function is not simpler than reading
    the source directly, so this test greps the function's text span instead.
    """
    text = _AGENT.read_text()
    start = text.index("def _create_agent(")
    next_def = text.index("\ndef ", start + 1)
    return text[start:next_def]


def test_agentcore_memory_config_filters_restored_tool_context():
    source = _create_agent_source()
    assert "AgentCoreMemoryConfig(" in source, (
        "AgentCoreMemoryConfig construction not found in _create_agent"
    )
    match = re.search(
        r"AgentCoreMemoryConfig\((?P<args>.*?)\)\s*,\s*\n\s*region_name",
        source,
        re.DOTALL,
    )
    assert match, "could not isolate the AgentCoreMemoryConfig(...) call"
    args = match.group("args")
    assert re.search(r"filter_restored_tool_context\s*=\s*True", args), (
        "AgentCoreMemoryConfig must set filter_restored_tool_context=True so "
        "resuming a session does not reload large historical tool payloads "
        "(e.g. SAP OData responses) into context"
    )
