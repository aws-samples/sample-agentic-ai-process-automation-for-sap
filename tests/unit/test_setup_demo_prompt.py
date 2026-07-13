# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# This is sample code. Not for use in production.
# See NOTICE and LICENSE for more information.
"""Unit tests for scripts/setup.py demo-block rendering (_apply_demo_choice)."""

import importlib.util
import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "setup_wizard", _REPO_ROOT / "scripts" / "setup.py"
)
setup_wizard = importlib.util.module_from_spec(_spec)
sys.modules["setup_wizard"] = setup_wizard
_spec.loader.exec_module(setup_wizard)

_apply_demo_choice = setup_wizard._apply_demo_choice
_TEMPLATE = (_REPO_ROOT / "cdk" / "config.yaml.example").read_text()


def _demo(text: str):
    """Parse the rendered config and return its `demo` block (None if commented out)."""
    return yaml.safe_load(text).get("demo")


def test_neither_selected_leaves_template_commented():
    out = _apply_demo_choice(_TEMPLATE, ticketing=False, test_data=False)
    assert out == _TEMPLATE  # untouched
    assert _demo(out) is None  # still commented → production-clean


def test_ticketing_only():
    demo = _demo(_apply_demo_choice(_TEMPLATE, ticketing=True, test_data=False))
    assert demo == {"ticketing": {"enabled": True}, "test_data": {"enabled": False}}


def test_test_data_only():
    demo = _demo(_apply_demo_choice(_TEMPLATE, ticketing=False, test_data=True))
    assert demo == {"ticketing": {"enabled": False}, "test_data": {"enabled": True}}


def test_both_selected():
    demo = _demo(_apply_demo_choice(_TEMPLATE, ticketing=True, test_data=True))
    assert demo == {"ticketing": {"enabled": True}, "test_data": {"enabled": True}}


def test_swap_does_not_disturb_neighbouring_sections():
    # The block match must stop at the blank line before "Contact Directory";
    # contacts (and the section above demo) must survive intact.
    out = _apply_demo_choice(_TEMPLATE, ticketing=True, test_data=False)
    parsed = yaml.safe_load(out)
    assert "contacts" in parsed
    assert parsed["autonomy"]["trigger_mode"] == "manual"
