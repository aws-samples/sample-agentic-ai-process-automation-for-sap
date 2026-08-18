# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Drift guard: the two Python homes of the case identity codec must be identical.

The codec cannot live in one Python file. Lambdas import it from the
``shared_types`` layer, but the agent runs in a container whose Dockerfile copies
only ``agentcore/`` and ``skills/`` — it has no access to ``lambdas/layers/``. So
the file is mirrored, and this test is what keeps the mirror honest: if the two
ever disagree, an id minted by the agent could fail to parse in a Lambda (or vice
versa), which is exactly the class of bug the codec exists to remove.

The TypeScript twin (``frontend/src/lib/caseKey.ts``) cannot be compared
byte-for-byte; its behaviour is pinned by ``frontend/src/lib/caseKey.test.ts``,
which asserts the same cases as ``tests/unit/test_case_key.py``.
"""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_CANONICAL = _REPO_ROOT / "lambdas" / "layers" / "shared_types" / "case_key.py"
_MIRROR = _REPO_ROOT / "agentcore" / "agent" / "utils" / "case_key.py"


def test_both_copies_of_the_codec_exist():
    assert _CANONICAL.is_file(), f"missing canonical codec: {_CANONICAL}"
    assert _MIRROR.is_file(), (
        f"missing agent-side mirror: {_MIRROR} — the agent container cannot import "
        "the shared_types layer, so it needs its own copy"
    )


def test_the_agent_mirror_is_byte_identical_to_the_layer_copy():
    canonical = _CANONICAL.read_text(encoding="utf-8")
    mirror = _MIRROR.read_text(encoding="utf-8")
    assert mirror == canonical, (
        "case_key.py has drifted between the shared_types layer and the agent's "
        "utils/. Copy the canonical file over the mirror:\n"
        f"  cp {_CANONICAL.relative_to(_REPO_ROOT)} {_MIRROR.relative_to(_REPO_ROOT)}"
    )
