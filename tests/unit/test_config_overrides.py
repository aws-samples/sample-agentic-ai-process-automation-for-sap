# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Read-through for the /config overrides, and the mirror that keeps it honest.

Two independent code paths substitute the same symbols into SOP text: the agent's
skill_router (prompt assembly) and the `load_sop` Gateway tool (mid-case reload).
If only one honoured an operator's edit, the prompt would say one tolerance and
the reloaded SOP another — the drift SOP_INDEX_JSON already exists to prevent.
The reader is therefore mirrored, and the first test is what stops the two copies
diverging: the agent runs in a container whose Dockerfile copies only
``agentcore/`` and ``skills/``, and the Gateway tool is a separate Lambda asset,
so neither can import the other.
"""

import importlib
import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_CANONICAL = _REPO_ROOT / "agentcore" / "agent" / "utils" / "config_overrides.py"
_MIRROR = (
    _REPO_ROOT
    / "agentcore"
    / "gateway"
    / "tools"
    / "knowledge_base"
    / "config_overrides.py"
)


def test_both_copies_of_the_reader_exist():
    assert _CANONICAL.is_file(), f"missing canonical reader: {_CANONICAL}"
    assert _MIRROR.is_file(), (
        f"missing Gateway-tool mirror: {_MIRROR} — the knowledge_base Lambda is "
        "its own asset bundle and cannot import the agent's utils/"
    )


def test_the_gateway_mirror_is_byte_identical_to_the_agent_copy():
    assert _MIRROR.read_text(encoding="utf-8") == _CANONICAL.read_text(
        encoding="utf-8"
    ), (
        "config_overrides.py has drifted between the agent and the knowledge_base "
        "Gateway tool, so an operator's edit could reach one substitution path and "
        "not the other. Copy the canonical file over the mirror:\n"
        f"  cp {_CANONICAL.relative_to(_REPO_ROOT)} {_MIRROR.relative_to(_REPO_ROOT)}"
    )


@pytest.fixture
def overrides(monkeypatch):
    monkeypatch.setenv("CONFIG_TABLE", "cfg-table")
    sys.path.insert(0, str(_CANONICAL.parent))
    with patch("boto3.resource"):
        import config_overrides as mod

        importlib.reload(mod)
    mod._table = MagicMock()
    return mod


def _serve(overrides, items):
    overrides._table.query.return_value = {"Items": items}


def test_contact_overrides_are_keyed_to_match_the_placeholder(overrides):
    # The table stores the config.yaml key ("ap_team"); the SOP writes
    # {{CONTACT_AP_TEAM}}. A mismatch here leaves the placeholder verbatim.
    _serve(overrides, [{"config_key": "ap_team", "value": "new@example.com"}])
    assert overrides.contact_overrides() == {"CONTACT_AP_TEAM": "new@example.com"}


def test_constant_overrides_query_the_skills_own_namespace(overrides):
    _serve(overrides, [{"config_key": "QTY_VARIANCE_PCT", "value": Decimal("7")}])
    assert overrides.constant_overrides("finance_ap") == {
        "QTY_VARIANCE_PCT": Decimal("7")
    }
    condition = overrides._table.query.call_args.kwargs["KeyConditionExpression"]
    assert "constant#finance_ap" in str(condition.get_expression()["values"])


def test_no_config_table_means_no_overrides_not_a_crash(overrides, monkeypatch):
    # Local dev and any deployment that predates the config table. The deployed
    # defaults must still resolve.
    monkeypatch.delenv("CONFIG_TABLE")
    overrides._table = None
    assert overrides.contact_overrides() == {}
    assert overrides.constant_overrides("finance_ap") == {}


def test_a_failed_read_falls_back_to_the_deployed_default(overrides):
    # Throttle, permission change, table deleted. Returning {} means the SOP still
    # names a real threshold; raising would fail the case, and returning a blank
    # would have the agent compare against nothing.
    overrides._table.query.side_effect = RuntimeError("throttled")
    assert overrides.constant_overrides("finance_ap") == {}


def test_rows_without_a_value_are_skipped(overrides):
    _serve(overrides, [{"config_key": "QTY_VARIANCE_PCT"}])
    assert overrides.constant_overrides("finance_ap") == {}


def test_an_empty_skill_id_does_not_query_the_contact_namespace(overrides):
    # "constant#" + "" would be a namespace of its own, but a bug that passed the
    # empty string should read nothing rather than something.
    assert overrides.constant_overrides("") == {}
    overrides._table.query.assert_not_called()


# The reader is only useful if both substitution paths consult it. These two pin
# the seam — a plausible refactor that drops the merge in either place would leave
# every unit above passing while operator edits silently did nothing.


def test_an_override_wins_over_the_deployed_tolerance_in_the_prompt(monkeypatch):
    from utils import skill_router as sr

    monkeypatch.setattr(sr, "_contacts", {})
    monkeypatch.setattr(
        sr.config_overrides, "constant_overrides", lambda _: {"QTY_VARIANCE_PCT": 9}
    )
    config = {"skill_id": "finance_ap", "constants": {"QTY_VARIANCE_PCT": 5}}
    assert sr._substitute("above {{QTY_VARIANCE_PCT}}%", config) == "above 9%"


def test_an_override_for_an_undeclared_symbol_cannot_introduce_one(monkeypatch):
    from utils import skill_router as sr

    monkeypatch.setattr(sr, "_contacts", {})
    monkeypatch.setattr(
        sr.config_overrides, "constant_overrides", lambda _: {"SMUGGLED_LIMIT": 1}
    )
    config = {"skill_id": "finance_ap", "constants": {"QTY_VARIANCE_PCT": 5}}
    text = "cap {{SMUGGLED_LIMIT}}"
    # Verbatim, exactly as for any undeclared symbol: a value nothing declared is
    # a typo, and blanking it would hide the typo behind a working-looking prompt.
    assert sr._substitute(text, config) == text


@pytest.fixture
def kb_lambda(monkeypatch):
    """The `load_sop` Gateway tool, serving one SOP whose text the test sets."""
    import json

    monkeypatch.setenv("STACK_NAME_BASE", "test-stack")
    monkeypatch.setenv(
        "SOP_INDEX_JSON",
        json.dumps(
            {
                "finance_ap": {
                    "sops": {"quantity_variance": "finance_ap/quantity_variance.txt"},
                    "constants": {"QTY_VARIANCE_PCT": 5},
                }
            }
        ),
    )
    sys.path.insert(0, str(_MIRROR.parent))
    with patch("boto3.client"):
        import knowledge_base_lambda as kb

        importlib.reload(kb)
    kb._params = {"/test-stack/s3/sops-bucket": "sop-bucket"}
    kb.s3 = MagicMock()
    return kb


def test_an_override_reaches_the_reloaded_sop_too(monkeypatch, kb_lambda):
    # load_sop is the other consumer. If it kept using the deploy-time constant,
    # the prompt and the mid-case SOP reload would state different tolerances.
    kb_lambda.s3.get_object.return_value = {
        "Body": MagicMock(read=lambda: b"above {{QTY_VARIANCE_PCT}}%")
    }
    monkeypatch.setattr(
        kb_lambda.config_overrides,
        "constant_overrides",
        lambda _: {"QTY_VARIANCE_PCT": 9},
    )

    ctx = MagicMock()
    ctx.client_context.custom = {"bedrockAgentCoreToolName": "kb-target___load_sop"}
    result = kb_lambda.handler({"process_type": "quantity_variance"}, ctx)
    assert result["content"][0]["text"] == "above 9%"


# Both paths now call config_overrides.substitute rather than each owning a copy
# of the placeholder rules. The copies did diverge: the router matched
# CONTACT_[A-Z_]+ and the Gateway tool [A-Z][A-Z0-9_]*, so a contact key with a
# digit resolved on a mid-case load_sop and reached the model verbatim in the
# injected prompt. These tests pin that both still route through the one copy.

_PARITY_TEXT = (
    "Above {{QTY_VARIANCE_PCT}}% notify {{CONTACT_AP_TEAM}} and "
    "{{CONTACT_TIER2_OWNER}}; {{UNDECLARED}} stays."
)
_PARITY_CONTACTS = {"ap_team": "ap@example.com", "tier2_owner": "t2@example.com"}
_PARITY_CONSTANTS = {"QTY_VARIANCE_PCT": 5}


def test_both_substitution_paths_resolve_the_same_text_identically(
    monkeypatch, kb_lambda
):
    """The one assertion that matters: `load_sop` and the injected prompt must
    never disagree about a tolerance, because that decides whether money moves."""
    from utils import skill_router as sr

    contacts = {f"CONTACT_{k.upper()}": v for k, v in _PARITY_CONTACTS.items()}
    monkeypatch.setattr(sr, "_contacts", contacts)
    monkeypatch.setattr(kb_lambda, "_contacts", contacts)
    for module in (sr.config_overrides, kb_lambda.config_overrides):
        monkeypatch.setattr(module, "contact_overrides", dict)
        monkeypatch.setattr(module, "constant_overrides", lambda _: {})

    from_prompt = sr._substitute(
        _PARITY_TEXT, {"skill_id": "finance_ap", "constants": _PARITY_CONSTANTS}
    )
    kb_lambda.s3.get_object.return_value = {
        "Body": MagicMock(read=lambda: _PARITY_TEXT.encode("utf-8"))
    }
    ctx = MagicMock()
    ctx.client_context.custom = {"bedrockAgentCoreToolName": "kb-target___load_sop"}
    from_load_sop = kb_lambda.handler({"process_type": "quantity_variance"}, ctx)[
        "content"
    ][0]["text"]

    assert from_prompt == from_load_sop
    # Not vacuous: both really did resolve, including the digit-bearing contact
    # key that the two old patterns disagreed about.
    assert "5%" in from_prompt
    assert "t2@example.com" in from_prompt
    assert "{{UNDECLARED}}" in from_prompt


def test_neither_path_keeps_its_own_placeholder_pattern():
    # A re-added local regex is how the two drifted the first time, and it would
    # pass every test above until the day the patterns disagreed.
    for path in (
        _CANONICAL.parent / "skill_router.py",
        _MIRROR.parent / "knowledge_base_lambda.py",
    ):
        source = path.read_text(encoding="utf-8")
        assert "config_overrides.substitute" in source, (
            f"{path.name} no longer routes through the shared substitution"
        )
        assert r"\{\{" not in source, (
            f"{path.name} compiles its own placeholder pattern — the two copies "
            f"already drifted once (CONTACT_[A-Z_]+ vs [A-Z][A-Z0-9_]*)"
        )
