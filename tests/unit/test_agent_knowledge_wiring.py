# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""
A Gateway tool needs three things or it is unreachable: a target, a Cedar
permit (needed once cedar_enforcement_mode is ENFORCE), and an entry in the
skill's gateway_tools (basic_agent filters the MCP tool list by it). Assert all
three agree on the same two names — the Cedar one is the check that would
otherwise only fail in a hardened stack.

A fourth thing keeps it from being reachable-but-ungoverned: a rule in the
prompt corpus saying when to call it and how to treat what comes back. Both
tools were granted for a release with none, so the agent could call them at will
and treat precedent as instruction.
"""

import json
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TOOLS = ("get_precedent", "check_vendor_risk")
TARGET = "agent-knowledge-target"


def test_tool_spec_declares_both_tools():
    spec = json.loads(
        (
            _REPO_ROOT / "agentcore/gateway/tools/agent_knowledge/tool_spec.json"
        ).read_text()
    )
    assert {t["name"] for t in spec} == set(TOOLS)


@pytest.mark.parametrize("tool", TOOLS)
def test_cedar_permits_the_tool(tool):
    cedar = (_REPO_ROOT / "agentcore/policies/sap_agent_policies.cedar").read_text()
    assert f'{TARGET}___{tool}"' in cedar


@pytest.mark.parametrize("tool", TOOLS)
def test_finance_ap_skill_lists_the_tool(tool):
    config = json.loads((_REPO_ROOT / "skills/finance_ap/config.json").read_text())
    assert tool in config["gateway_tools"]


@pytest.mark.parametrize("tool", TOOLS)
def test_the_prompt_corpus_governs_the_tool(tool):
    """A grant with no rule behind it is the anti-pattern: the tool_spec's own
    description is the only thing the model sees, and a tool description cannot
    say when NOT to call something."""
    corpus = sorted((_REPO_ROOT / "skills").rglob("*.txt")) + sorted(
        (_REPO_ROOT / "knowledge-base" / "sops").rglob("*.txt")
    )
    assert corpus, "no prompt or SOP files found — check the glob paths"
    assert any(tool in p.read_text(encoding="utf-8") for p in corpus), (
        f"{tool} is granted in gateway_tools but no base_prompt, platform prompt or "
        f"SOP says when to call it or how to weigh what it returns"
    )


def test_precedent_is_governed_as_evidence_not_instruction():
    # The one substantive rule: a precedent that contradicts the SOP must lose.
    # Without it the agent can cite "we did it this way last time" as authority.
    prompt = (_REPO_ROOT / "skills/_platform_prompt.txt").read_text(encoding="utf-8")
    assert "evidence, never instructions" in prompt
    assert "the SOP wins" in prompt


def test_backend_stack_registers_the_target_under_the_flag():
    """The three names above are only reachable if backend-stack.ts actually
    mints the target — and only when the opt-in flag is set."""
    stack = (_REPO_ROOT / "cdk/lib/backend-stack.ts").read_text()
    assert f'name: "{TARGET}"' in stack
    assert "config.agent_knowledge?.enabled" in stack
