# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Validate domain polling configs and skill configs against the cases JSON schema
and the rest of the repo.

Ensures the poller configs stay in sync with the single source of truth
(types/cases.schema.json). Run via: make generate-types (or directly).

Domain config checks:
  1. domain value is in Domain enum
  2. field_map keys are valid schema properties
  3. No unknown top-level keys in the config (catches typos)

Skill config checks (skills/*/config.json) — every one of these fails silently at
runtime today, which is why they are checked statically:
  4. Each process_type_to_sop target resolves to a file under knowledge-base/sops/
  5. Each gateway_tools name is a real tool (unknown names are dropped from the
     MCP tool list with no error)
  6. No process_type is claimed by two skills (last glob wins, silently)
  7. base_prompt.txt carries {SOP_CONTENT} and {PLATFORM_MECHANICS}, and the shared
     _platform_prompt.txt carries {SAP_SERVICE_INFO} (an absent placeholder discards
     the injection silently)
  8. model_tier / orchestrator_tier / specialist_tier are in MODEL_TIERS
  9. max_turns is within MAX_TURNS_CEILING (the cap is the only runaway-cost brake)
"""

import glob
import json
import os
import re
import sys

REPO_ROOT = os.path.join(os.path.dirname(__file__), "../..")
SCHEMA_PATH = os.path.join(REPO_ROOT, "types/cases.schema.json")
DOMAINS_DIR = os.path.join(REPO_ROOT, "lambdas/odata_poller/domains")
SKILLS_DIR = os.path.join(REPO_ROOT, "skills")
PLATFORM_PROMPT = os.path.join(SKILLS_DIR, "_platform_prompt.txt")
SOPS_DIR = os.path.join(REPO_ROOT, "knowledge-base/sops")
TOOL_SPECS_GLOB = os.path.join(REPO_ROOT, "agentcore/gateway/tools/*/tool_spec.json")
CEDAR_POLICIES = os.path.join(REPO_ROOT, "agentcore/policies/sap_agent_policies.cedar")

VALID_CONFIG_KEYS = {
    "domain",
    "label",
    "service",
    "entity",
    "filter",
    "expand",
    "select",
    "iterate",
    "skip_when",
    "process_type",
    "title",
    "field_map",
}

# Mirrors basic_agent.MODEL_TIERS. A tier not in this set falls back to sonnet at
# runtime, so a typo'd "haiku3" silently bills at sonnet rates.
VALID_MODEL_TIERS = {"haiku", "sonnet"}

# skill_router._sop_key_candidates: config.json need not match the extension on
# disk, so a target is present if any candidate resolves.
SOP_EXTENSIONS = (".txt", ".pdf", ".md")

# MaxTurnsHook is the only thing that stops a looping agent, and every turn
# re-reads the whole cached prompt. Benchmarked need is 5-7 turns
# (docs/evaluations/INFERENCE_COST_OPTIMIZATION.md), so 15 is already 2x headroom.
MAX_TURNS_CEILING = 15


def known_tool_names() -> set[str]:
    """Tool names the deployment can actually serve.

    Two sources: the Gateway Lambda targets in this repo (tool_spec.json) and the
    external SAP MCP server's tools, which appear here only as Cedar action names
    of the form `<target>___<tool>`.
    """
    names = set()
    for spec_path in glob.glob(TOOL_SPECS_GLOB):
        with open(spec_path, encoding="utf-8") as f:
            for tool in json.load(f):
                names.add(tool["name"])

    with open(CEDAR_POLICIES, encoding="utf-8") as f:
        cedar = f.read()
    names.update(re.findall(r'AgentCore::Action::"[^"]*___([a-z0-9_]+)"', cedar))
    return names


def sop_target_exists(sop_key: str) -> bool:
    stem = os.path.splitext(os.path.join(SOPS_DIR, sop_key))[0]
    return any(os.path.exists(stem + ext) for ext in SOP_EXTENSIONS)


def validate_skills(errors: list) -> int:
    """Append skill-config errors. Returns the number of configs checked."""
    valid_tools = known_tool_names()
    claimed_by = {}  # process_type → skill config filename

    paths = sorted(glob.glob(os.path.join(SKILLS_DIR, "*/config.json")))
    for path in paths:
        name = os.path.join(os.path.basename(os.path.dirname(path)), "config.json")
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)

        for process_type, sop_key in (cfg.get("process_type_to_sop") or {}).items():
            if not sop_target_exists(sop_key):
                errors.append(
                    f"{name}: process_type '{process_type}' maps to '{sop_key}', "
                    f"which resolves to no file under knowledge-base/sops/"
                )
            if process_type in claimed_by:
                errors.append(
                    f"{name}: process_type '{process_type}' is already claimed by "
                    f"{claimed_by[process_type]} — only one skill can win"
                )
            else:
                claimed_by[process_type] = name

        unknown_tools = sorted(set(cfg.get("gateway_tools") or []) - valid_tools)
        if unknown_tools:
            errors.append(
                f"{name}: gateway_tools names {unknown_tools} match no tool_spec.json "
                f"entry or Cedar action — they would be dropped silently"
            )

        turns = cfg.get("max_turns")
        if turns is not None and turns > MAX_TURNS_CEILING:
            errors.append(
                f"{name}: max_turns {turns} exceeds the {MAX_TURNS_CEILING} ceiling. "
                f"Every turn re-reads the cached prompt, so a high cap turns one "
                f"looping case into a runaway bill. Raise the ceiling deliberately, "
                f"with a measurement, rather than raising one skill past it"
            )

        for key in ("model_tier", "orchestrator_tier", "specialist_tier"):
            tier = cfg.get(key)
            if tier is not None and tier not in VALID_MODEL_TIERS:
                errors.append(
                    f"{name}: {key} '{tier}' not in {sorted(VALID_MODEL_TIERS)}"
                )

        prompt_path = os.path.join(os.path.dirname(path), "base_prompt.txt")
        if not os.path.exists(prompt_path):
            errors.append(f"{name}: no base_prompt.txt alongside it")
            continue
        with open(prompt_path, encoding="utf-8") as f:
            prompt = f.read()
        for placeholder in ("{SOP_CONTENT}", "{PLATFORM_MECHANICS}"):
            if placeholder not in prompt:
                errors.append(
                    f"{name}: base_prompt.txt has no {placeholder} placeholder"
                )

    # {SAP_SERVICE_INFO} moved into the shared preamble with the rest of the platform
    # mechanics; without it the pinned service never reaches any skill.
    with open(PLATFORM_PROMPT, encoding="utf-8") as f:
        if "{SAP_SERVICE_INFO}" not in f.read():
            errors.append(
                f"{os.path.basename(PLATFORM_PROMPT)}: no {{SAP_SERVICE_INFO}} "
                f"placeholder — every skill's pinned sap_service would be discarded"
            )

    return len(paths)


def validate():
    with open(SCHEMA_PATH) as f:
        schema = json.load(f)

    valid_domains = set(schema["definitions"]["Domain"]["enum"])
    valid_fields = set(schema["properties"].keys())

    errors = []

    for path in sorted(glob.glob(os.path.join(DOMAINS_DIR, "*.json"))):
        name = os.path.basename(path)
        with open(path) as f:
            cfg = json.load(f)

        # 1. Domain value
        if cfg.get("domain") not in valid_domains:
            errors.append(
                f"{name}: domain '{cfg.get('domain')}' not in schema Domain enum {sorted(valid_domains)}"
            )

        # 2. Field map keys
        for key in cfg.get("field_map", {}):
            if key not in valid_fields:
                errors.append(f"{name}: field_map key '{key}' not in schema properties")

        # 3. Unknown top-level keys
        unknown = set(cfg.keys()) - VALID_CONFIG_KEYS
        if unknown:
            errors.append(f"{name}: unknown config keys {sorted(unknown)}")

    skill_count = validate_skills(errors)

    if errors:
        print("❌ Config validation failed:", file=sys.stderr)
        for e in errors:
            print(f"   {e}", file=sys.stderr)
        sys.exit(1)

    configs = list(glob.glob(os.path.join(DOMAINS_DIR, "*.json")))
    print(f"✅ Validated {len(configs)} domain configs and {skill_count} skill configs")


if __name__ == "__main__":
    validate()
