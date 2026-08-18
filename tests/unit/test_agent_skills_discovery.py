# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""The AgentSkills discovery path: name mapping, substitution, and wiring.

Three things here are correct only by construction and would fail silently:

1. `Skill.name` must be AgentSkills.io-legal, so `process_type` is hyphenated at
   the boundary. If a process_type ever gains a hyphen the mapping stops being
   injective and two exceptions collapse onto one skill.
2. `AgentSkills` serves `skill.instructions` verbatim — there is no substitution
   seam. A skill built from raw SOP text would hand the model literal
   `{{QTY_VARIANCE_PCT}}` instead of a threshold.
3. The plugin's hook must be re-registered on the adapter's per-thread clone.
   `plugins` is not among the constructor params ag_ui_strands forwards, so a
   plugin attached only to the template ships the `skills` tool with no
   `<available_skills>` block behind it.

basic_agent.py imports strands_tools and cannot be imported here (same
constraint as test_evidence_hook_wiring.py), so the wiring assertions read the
source text.
"""

import asyncio
import re
from pathlib import Path

import pytest
from utils import skill_router as sr

_ROOT = Path(__file__).resolve().parents[2]
_AGENT = _ROOT / "agentcore" / "agent" / "basic_agent.py"
_SKILLS_ROOT = _ROOT / "skills"


@pytest.fixture
def local_skills(monkeypatch):
    """Real shipped configs and SOPs, read from the repo rather than S3."""
    sr._skills_index = None
    monkeypatch.setattr(sr, "_skills_dir", lambda: _SKILLS_ROOT)
    monkeypatch.setenv("DEMO_ENABLED", "false")
    monkeypatch.delenv("SOP_BUCKET", raising=False)
    yield
    sr._skills_index = None


def test_skill_names_round_trip_to_process_types(local_skills):
    for process_type in sr._load_skills_index():
        name = sr._skill_name(process_type)
        assert re.fullmatch(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?", name), (
            f"{name!r} is not an AgentSkills.io-legal skill name — Skill.from_content "
            f"rejects it under strict=True"
        )
        assert sr._process_type_from_skill_name(name) == process_type, (
            f"{process_type} does not survive the hyphen round-trip. A process_type "
            f"containing a hyphen breaks the inverse mapping."
        )


def test_discovery_skills_cover_every_process_type_with_resolved_thresholds(
    local_skills,
):
    skills = sr.discovery_skills()
    expected = {sr._skill_name(pt) for pt in sr._load_skills_index()}

    assert {s.name for s in skills} == expected, (
        "every process_type with a loadable SOP must be activatable — a missing "
        "skill silently removes an exception type from the chat path"
    )

    for skill in skills:
        assert not re.search(r"\{\{[A-Z][A-Z0-9_]*\}\}", skill.instructions), (
            f"{skill.name} carries unsubstituted placeholders. AgentSkills returns "
            f"instructions verbatim, so the model would compare against a literal."
        )
        assert "<sop_document>" in skill.instructions
        assert skill.description


def test_a_process_type_with_no_loadable_sop_is_omitted(local_skills, monkeypatch):
    # An activatable skill with no procedure behind it is worse than an absent one:
    # the model activates it, gets nothing, and freelances.
    real = sr.resolve_skill

    def _one_broken(process_type, **kwargs):
        resolved = real(process_type, **kwargs)
        if process_type == "price_variance":
            resolved["sop_loaded"] = False
        return resolved

    monkeypatch.setattr(sr, "resolve_skill", _one_broken)
    assert "price-variance" not in {s.name for s in sr.discovery_skills()}


def test_the_plugin_hook_injects_available_skills_onto_a_clone_shaped_agent(
    local_skills,
):
    """The end-to-end claim: hook + tool carried by hand reach a separate agent.

    Built the way ag_ui_strands builds its per-thread clone — tools and hooks passed
    explicitly, no `plugins` — so this fails if the re-registration in _Hooks stops
    being sufficient.
    """
    from strands import Agent
    from strands.hooks import BeforeInvocationEvent
    from strands.vended_plugins.skills import AgentSkills

    plugin = AgentSkills(skills=sr.discovery_skills())
    agent = Agent(system_prompt="BASE PROMPT", tools=list(plugin.tools))
    for callback in plugin.hooks:
        for event_type in getattr(callback, "_hook_event_types", []):
            agent.hooks.add_callback(event_type, callback)

    asyncio.run(agent.hooks.invoke_callbacks_async(BeforeInvocationEvent(agent=agent)))

    assert "skills" in agent.tool_registry.registry
    assert "<available_skills>" in agent.system_prompt
    assert "<name>price-variance</name>" in agent.system_prompt
    assert agent.system_prompt.startswith("BASE PROMPT")


def test_activating_a_skill_is_recorded_as_a_sop_lookup(local_skills):
    # The SOP arrives as a tool result on this path, so without the mapping the
    # activation falls through to `computation` and no clause is ever cited.
    from utils.evidence import extract_evidence

    skill = next(s for s in sr.discovery_skills() if s.name == "price-variance")
    evidence = extract_evidence(
        "skills",
        {"skill_name": skill.name},
        {"status": "success", "content": [{"text": skill.instructions}]},
        at="2026-01-01T00:00:00Z",
    )

    assert evidence["kind"] == "sop_lookup"
    assert evidence["clauses_retrieved"][:2] == ["1.1", "1.2"]


def _create_agent_body() -> str:
    text = _AGENT.read_text()
    start = text.index("def _create_agent(")
    return text[start : text.index("\ndef ", start + 1)]


def test_the_plugin_hook_is_registered_inside_the_adapters_hook_provider():
    body = _create_agent_body()
    start = body.index("class _Hooks(HookProvider)")
    end = body.index("hook_provider = _Hooks()", start)
    assert "_hook_event_types" in body[start:end], (
        "the plugin's @hook callbacks must be re-registered in _Hooks.register_hooks. "
        "Agent(plugins=...) on the template does not reach the adapter's clone."
    )


def test_the_plugin_tool_is_passed_as_a_plain_tool():
    # The adapter copies the tool registry at init, so the `skills` tool has to be
    # in the template's `tools` list rather than registered by the plugin registry.
    assert re.search(r"tools\.extend\(skills_plugin\.tools\)", _create_agent_body())


def test_discovery_skills_are_not_built_on_the_queued_path():
    # resolve_skill has already injected the right SOP deterministically. Replacing
    # that with a model decision plus a round-trip trades correctness for nothing.
    text = _AGENT.read_text()
    start = text.index("def _discovery_plugin(")
    body = text[start : text.index("\ndef ", start + 1)]
    assert 'if not skill.get("discovery")' in body and "return None" in body
