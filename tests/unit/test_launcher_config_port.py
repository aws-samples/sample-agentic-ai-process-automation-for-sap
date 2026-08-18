# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Guards on the launcher's port of the config-generation logic.

`launcher/configfile.py` reimplements the text substitutions that
`scripts/setup.py:generate_config` performs on `cdk/config.yaml.example`. A
silent divergence there produces a config that deploys the wrong thing, so the
substitutions are pinned against the original expressions here.

The YAML fallback scanner is covered too: it is the path taken when PyYAML is
not importable, which is exactly the state `doctor` has to work in.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from launcher import awsx, configfile, state

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "cdk" / "config.yaml.example"


# ── Reference implementation, copied from scripts/setup.py ────────────────
# Verbatim so drift in either direction fails a test rather than a deployment.


def _reference_sub_line(text: str, key: str, value: str, indent: str = "") -> str:
    return re.sub(
        rf"(?m)^{re.escape(indent)}{re.escape(key)}:.*$",
        f"{indent}{key}: {value}",
        text,
        count=1,
    )


_REFERENCE_DEMO_BLOCK = re.compile(r"(?m)^# demo:\n(?:^#.*\n)*")


def _reference_render(
    text: str,
    *,
    stack_name: str,
    admin_email: str,
    ses_email: str,
    ticketing: bool,
    test_data: bool,
) -> str:
    text = _reference_sub_line(text, "stack_name_base", stack_name)
    if admin_email:
        text = _reference_sub_line(text, "admin_user_email", admin_email)
    if ses_email:
        text = re.sub(r"(?m)^#\s*(notification:)\s*$", r"\1", text)
        text = re.sub(r"(?m)^#\s*(channel: ses).*$", r"  \1", text)
        text = re.sub(
            r"(?m)^#\s*ses_sender_email:.*$", f"  ses_sender_email: {ses_email}", text
        )
    if ticketing or test_data:
        active = (
            "demo:\n"
            f"  ticketing:\n    enabled: {'true' if ticketing else 'false'}\n"
            f"  test_data:\n    enabled: {'true' if test_data else 'false'}\n"
        )
        text = _REFERENCE_DEMO_BLOCK.sub(active, text, count=1)
    return text


@pytest.fixture(scope="module")
def template_text() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


# ── Rendering parity ─────────────────────────────────────────────────────

_CASES = [
    pytest.param("bare", "", "", False, False, id="stack-name-only"),
    pytest.param("with-admin", "admin@example.com", "", False, False, id="admin-email"),
    pytest.param("with-ses", "", "sender@example.com", False, False, id="ses-sender"),
    pytest.param("tick", "", "", True, False, id="ticketing-only"),
    pytest.param("data", "", "", False, True, id="test-data-only"),
    pytest.param(
        "everything",
        "admin@example.com",
        "sender@example.com",
        True,
        True,
        id="all-options",
    ),
]


@pytest.mark.unit
@pytest.mark.parametrize(("stack", "admin", "ses", "ticketing", "test_data"), _CASES)
def test_render_matches_setup_py(
    template_text: str,
    stack: str,
    admin: str,
    ses: str,
    ticketing: bool,
    test_data: bool,
) -> None:
    ported = configfile.render(
        template_text,
        stack_name=stack,
        admin_email=admin,
        ses_sender_email=ses,
        ticketing=ticketing,
        test_data=test_data,
    )
    reference = _reference_render(
        template_text,
        stack_name=stack,
        admin_email=admin,
        ses_email=ses,
        ticketing=ticketing,
        test_data=test_data,
    )
    assert ported == reference


@pytest.mark.unit
def test_render_preserves_template_comments(template_text: str) -> None:
    """The template's commented options are its documentation — they must survive."""
    rendered = configfile.render(template_text, stack_name="demo-stack")
    for marker in (
        "# ── Backend ",
        "# sap_mcp:",
        "# alarm_email:",
        "#   sops_chunking_strategy: NONE",
    ):
        assert marker in rendered, f"template documentation lost: {marker!r}"


@pytest.mark.unit
def test_render_leaves_demo_commented_when_nothing_selected(template_text: str) -> None:
    rendered = configfile.render(template_text, stack_name="demo-stack")
    assert "# demo:" in rendered
    assert not re.search(r"(?m)^demo:$", rendered)


@pytest.mark.unit
def test_render_activates_demo_block(template_text: str) -> None:
    rendered = configfile.render(
        template_text, stack_name="demo-stack", ticketing=True, test_data=False
    )
    assert re.search(r"(?m)^demo:$", rendered)
    assert re.search(r"(?m)^  ticketing:\n    enabled: true$", rendered)
    assert re.search(r"(?m)^  test_data:\n    enabled: false$", rendered)


# ── Validation ───────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    ("name", "valid"),
    [
        ("my-erp-agent", True),
        ("erp1", True),
        ("", False),
        ("has_underscore", False),
        ("1-leading-digit", False),
        ("has space", False),
        ("x" * 36, False),
        ("x" * 35, True),
    ],
)
def test_validate_stack_name(name: str, valid: bool) -> None:
    assert (configfile.validate_stack_name(name) is None) is valid


@pytest.mark.unit
@pytest.mark.parametrize(
    ("value", "valid"),
    [("", True), ("a@b.co", True), ("no-at-sign", False), ("a@b", False)],
)
def test_validate_email(value: str, valid: bool) -> None:
    assert (configfile.validate_email(value) is None) is valid


# ── PyYAML-free fallback reader ──────────────────────────────────────────


@pytest.mark.unit
def test_scan_fallback_reads_nested_keys(template_text: str) -> None:
    """The fallback must resolve the keys the launcher actually reads."""
    scanned = configfile._scan(template_text)
    assert configfile.get(scanned, "stack_name_base") == "erp-accrual-agent"
    assert configfile.get(scanned, "backend.deployment_type") == "zip"
    assert configfile.get(scanned, "backend.network_mode") == "PUBLIC"
    assert configfile.get(scanned, "auth_profile") == "cognito-basic"
    assert configfile.get(scanned, "cedar_enforcement_mode") == "LOG_ONLY"
    assert configfile.get(scanned, "autonomy.trigger_mode") == "manual"
    # Commented-out keys must not appear as configured values.
    assert configfile.get(scanned, "sap.base_url") is None
    assert configfile.get(scanned, "demo.enabled") is None


@pytest.mark.unit
def test_scan_fallback_agrees_with_pyyaml(template_text: str) -> None:
    yaml = pytest.importorskip("yaml")
    parsed = yaml.safe_load(template_text)
    scanned = configfile._scan(template_text)
    for key in (
        "stack_name_base",
        "backend.deployment_type",
        "backend.network_mode",
        "auth_profile",
        "cedar_enforcement_mode",
        "autonomy.trigger_mode",
        "sap.embedding_model",
    ):
        assert configfile.get(scanned, key) == configfile.get(parsed, key), key


@pytest.mark.unit
def test_get_treats_blank_as_absent() -> None:
    assert configfile.get({"a": ""}, "a", "fallback") == "fallback"
    assert configfile.get({"a": None}, "a", "fallback") == "fallback"
    assert configfile.get({"a": {"b": "v"}}, "a.b") == "v"
    assert configfile.get({"a": "scalar"}, "a.b", "fallback") == "fallback"


# ── State file must never hold secrets ───────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    "key",
    ["password", "Secret", "session_token", "client_secret", "credentials"],
)
def test_state_refuses_secret_keys(key: str) -> None:
    with pytest.raises(ValueError, match="Refusing to write"):
        state._assert_no_secrets({key: "value"})


@pytest.mark.unit
def test_state_allows_non_secret_keys() -> None:
    state._assert_no_secrets({"account": "1", "region": "us-east-1", "stack_base": "x"})


# ── Root-cause failure selection ─────────────────────────────────────────
# Regression guard from a real failed deployment: a CloudTrail quota error was
# the cause, and 19 "Resource creation cancelled" events followed it. Reporting
# the newest events hid the only message that explained anything.

_CANCELLED = "Resource creation cancelled"
_TRAIL_QUOTA = (
    'Resource handler returned message: "Invalid request provided: User: '
    "111122223333 already has 5 trails in us-east-1."
)

# DescribeStackEvents order: newest first.
_ROLLBACK_EVENTS = [
    {
        "Timestamp": "2026-07-30T21:26:47Z",
        "LogicalResourceId": "AgentMemory",
        "ResourceStatus": "DELETE_FAILED",
        "ResourceStatusReason": "Memory is in transitional state CREATING.",
    },
    {
        "Timestamp": "2026-07-30T21:26:43Z",
        "LogicalResourceId": "erp-launcher-e2e-backend",
        "ResourceStatus": "ROLLBACK_IN_PROGRESS",
        "ResourceStatusReason": "The following resource(s) failed to create: [...]",
    },
    {
        "Timestamp": "2026-07-30T21:26:42Z",
        "LogicalResourceId": "NotificationLambda",
        "ResourceStatus": "CREATE_FAILED",
        "ResourceStatusReason": _CANCELLED,
    },
    {
        "Timestamp": "2026-07-30T21:26:42Z",
        "LogicalResourceId": "KnowledgeBaseLambda",
        "ResourceStatus": "CREATE_FAILED",
        "ResourceStatusReason": _CANCELLED,
    },
    {
        "Timestamp": "2026-07-30T21:26:42Z",
        "LogicalResourceId": "AgentInvocationQueue",
        "ResourceStatus": "CREATE_FAILED",
        "ResourceStatusReason": _CANCELLED,
    },
    {
        "Timestamp": "2026-07-30T21:26:41Z",
        "LogicalResourceId": "ObservabilitySsmTrail",
        "ResourceStatus": "CREATE_FAILED",
        "ResourceStatusReason": _TRAIL_QUOTA,
    },
    {
        "Timestamp": "2026-07-30T21:25:42Z",
        "LogicalResourceId": "erp-launcher-e2e-backend",
        "ResourceStatus": "CREATE_IN_PROGRESS",
        "ResourceStatusReason": "User Initiated",
    },
]


@pytest.mark.unit
def test_root_cause_is_reported_first() -> None:
    failures = awsx.root_cause_failures(_ROLLBACK_EVENTS)
    assert failures, "expected at least one failure"
    logical, status, reason = failures[0]
    assert logical == "ObservabilitySsmTrail"
    assert status == "CREATE_FAILED"
    assert "already has 5 trails" in reason


@pytest.mark.unit
def test_knock_on_cancellations_are_dropped() -> None:
    failures = awsx.root_cause_failures(_ROLLBACK_EVENTS)
    reasons = [reason for _, _, reason in failures]
    assert not any(_CANCELLED in reason for reason in reasons)


@pytest.mark.unit
def test_non_failure_events_are_ignored() -> None:
    failures = awsx.root_cause_failures(_ROLLBACK_EVENTS)
    assert all("FAILED" in status for _, status, _ in failures)


@pytest.mark.unit
def test_delete_failure_is_kept_after_the_cause() -> None:
    """A stuck delete explains why a rollback wedged, so it must survive."""
    logical_ids = [
        logical for logical, _, _ in awsx.root_cause_failures(_ROLLBACK_EVENTS)
    ]
    assert "AgentMemory" in logical_ids
    assert logical_ids.index("ObservabilitySsmTrail") < logical_ids.index("AgentMemory")


@pytest.mark.unit
def test_limit_is_respected() -> None:
    assert len(awsx.root_cause_failures(_ROLLBACK_EVENTS, limit=1)) == 1


@pytest.mark.unit
def test_no_events_is_not_an_error() -> None:
    assert awsx.root_cause_failures([]) == []
