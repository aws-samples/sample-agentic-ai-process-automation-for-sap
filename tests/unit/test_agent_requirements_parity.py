# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Drift guard: the ``agent-strands`` extra must match the container's requirements.

``agentcore/agent/requirements.txt`` is what the Dockerfile installs, so it is the
version set the deployed runtime actually gets. ``pyproject.toml``'s ``agent-strands``
extra is what a contributor gets from ``pip install -e .[agent-strands]``. Those two
carried a "MUST stay in sync" comment and nothing enforcing it, and they drifted: the
extra omitted ag-ui-strands, ag-ui-protocol, fastapi and uvicorn entirely, so the
documented local-dev install produced an environment that could not import
basic_agent — while the pinned strands version sat 26 minor releases behind the one
the test suite was resolving locally.

Both halves matter and fail differently. A missing package means local dev cannot run
the agent; a differing pin means tests pass against a version the container never
installs, which is how a green suite ships a broken image.
"""

import re
import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REQUIREMENTS = _REPO_ROOT / "agentcore" / "agent" / "requirements.txt"
_PYPROJECT = _REPO_ROOT / "pyproject.toml"

# name, extras, specifier — extras are part of identity ("bedrock-agentcore" and
# "bedrock-agentcore[strands-agents]" resolve to different dependency closures).
_REQUIREMENT = re.compile(
    r"^(?P<name>[A-Za-z0-9._-]+)(?P<extras>\[[^\]]*\])?(?P<spec>.*)$"
)


def _parse(lines: list[str]) -> dict[str, str]:
    """Map canonical requirement name -> version constraint, markers dropped.

    An environment marker is not a version: the extra carries a python_version
    marker on ag-ui-strands because that wheel is 3.12-3.13 only and the project's
    floor is 3.10, while requirements.txt needs none (the container is 3.13). Both
    still have to agree on *which release* they install.
    """
    parsed = {}
    for line in lines:
        line = line.split("#", 1)[0].split(";", 1)[0].strip()
        if not line:
            continue
        match = _REQUIREMENT.match(line)
        assert match, f"unparsable requirement: {line!r}"
        key = match["name"].lower().replace("_", "-") + (match["extras"] or "")
        parsed[key] = match["spec"].strip()
    return parsed


def _container_requirements() -> dict[str, str]:
    return _parse(_REQUIREMENTS.read_text().splitlines())


def _extra_requirements() -> dict[str, str]:
    pyproject = tomllib.loads(_PYPROJECT.read_text())
    extra = pyproject["project"]["optional-dependencies"]["agent-strands"]
    return _parse(extra)


def test_the_extra_covers_every_container_requirement():
    missing = sorted(set(_container_requirements()) - set(_extra_requirements()))
    assert not missing, (
        f"agent-strands is missing {missing}. `pip install -e .[agent-strands]` must "
        f"produce an environment that can import basic_agent, which imports every "
        f"package the container installs."
    )


def test_the_extra_pins_the_same_versions_as_the_container():
    extra = _extra_requirements()
    mismatched = {
        name: (spec, extra[name])
        for name, spec in _container_requirements().items()
        if name in extra and extra[name] != spec
    }
    assert not mismatched, (
        f"pin drift between requirements.txt and the agent-strands extra: "
        f"{mismatched} (container spec, extra spec). Tests resolve the extra's "
        f"versions; the deployed image resolves requirements.txt's."
    )
