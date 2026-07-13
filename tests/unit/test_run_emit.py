# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# This is sample code. Not for use in production.
# See NOTICE and LICENSE for more information.
"""Unit tests for scripts/deploy/run_emit.py."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "deploy"))

from run_emit import (  # noqa: E402
    _cdk_inputs,
    _frontend_block,
    _overrides_from_strings,
    run_emit,
)
from utils.auth_profiles import ProfileValidationError  # noqa: E402

ENTRA_OVERRIDES = {
    "discovery_url": "https://login.microsoftonline.com/T/v2.0/.well-known/openid-configuration",
    "allowed_clients": ["entra-app-id"],
}


def test_cognito_profile_skips_and_writes_nothing(tmp_path):
    out = tmp_path / "artifact.json"
    result = run_emit("cognito-basic", overrides=None, out_path=str(out))
    assert result is None
    assert not out.exists()


def test_entra_profile_writes_artifact_with_overrides(tmp_path):
    out = tmp_path / "artifact.json"
    result = run_emit(
        "entra-obo", overrides=ENTRA_OVERRIDES, out_path=str(out), mcp_path=False
    )
    assert result is not None
    assert out.exists()
    written = json.loads(out.read_text())
    assert written["inbound"]["discovery_url"].startswith(
        "https://login.microsoftonline.com"
    )
    assert written["inbound"]["allowed_clients"] == ["entra-app-id"]


def test_entra_missing_override_raises(tmp_path):
    out = tmp_path / "artifact.json"
    with pytest.raises(ValueError, match="allowed_clients"):
        run_emit(
            "entra-obo",
            overrides={"discovery_url": ENTRA_OVERRIDES["discovery_url"]},
            out_path=str(out),
            mcp_path=False,
        )


def test_direct_obo_emits_outbound_block_on_mcp_path(tmp_path):
    # entra-obo is a direct-to-MCP profile (obo_direct_mcp:true), so enabling the
    # SAP MCP path (mcp_path=True) must emit the outbound block, not abort — the
    # Gateway's mcp_supported:false guard does not apply to direct-to-MCP profiles.
    out = tmp_path / "artifact.json"
    result = run_emit(
        "entra-obo", overrides=ENTRA_OVERRIDES, out_path=str(out), mcp_path=True
    )
    assert result is not None
    outbound = result["outbound"]
    assert outbound["flow"] == "ON_BEHALF_OF_TOKEN_EXCHANGE"
    assert outbound["obo_direct_mcp"] is True
    assert outbound["mcp_invocation_url"]  # placeholder or resolved, but present


def test_overrides_from_strings_omits_empty():
    assert _overrides_from_strings("", "") is None
    assert _overrides_from_strings(
        "https://x/.well-known/openid-configuration", ""
    ) == {"discovery_url": "https://x/.well-known/openid-configuration"}
    assert _overrides_from_strings("https://x", "a,b") == {
        "discovery_url": "https://x",
        "allowed_clients": ["a", "b"],
    }


def test_cdk_inputs_env_wins(tmp_path, monkeypatch):
    # Env vars are the only source reliably delivered into CodeBuild; they win
    # over any local config.yaml. Pin a temp config so this test doesn't depend
    # on whatever the repo's own config.yaml currently selects.
    import run_emit

    cfg = tmp_path / "config.yaml"
    cfg.write_text("auth_profile: cognito-basic\n")
    monkeypatch.setattr(run_emit, "_CDK_CONFIG", cfg)
    monkeypatch.setenv("AUTH_PROFILE", "okta-userfed")
    monkeypatch.setenv(
        "AUTH_INBOUND_DISCOVERY_URL",
        "https://dev.okta.com/oauth2/default/.well-known/openid-configuration",
    )
    monkeypatch.setenv("AUTH_INBOUND_ALLOWED_CLIENTS", "okta-1,okta-2")
    profile, overrides, frontend_overrides, _mcp = _cdk_inputs()
    assert profile == "okta-userfed"  # env wins over the temp config's cognito-basic
    assert frontend_overrides is None  # no frontend_overrides key in temp config
    assert overrides == {
        "discovery_url": "https://dev.okta.com/oauth2/default/.well-known/openid-configuration",
        "allowed_clients": ["okta-1", "okta-2"],
    }


def test_cdk_inputs_falls_back_to_config_when_env_unset(tmp_path, monkeypatch):
    # With no AUTH_PROFILE env var, read the config.yaml. Pin a temp config so this
    # test asserts the fallback behavior, not whatever the repo's config.yaml selects.
    import run_emit

    cfg = tmp_path / "config.yaml"
    cfg.write_text("auth_profile: cognito-basic\n")
    monkeypatch.setattr(run_emit, "_CDK_CONFIG", cfg)
    monkeypatch.delenv("AUTH_PROFILE", raising=False)
    profile, _overrides, frontend_overrides, _mcp = _cdk_inputs()
    assert frontend_overrides is None
    assert profile == "cognito-basic"


def test_cdk_inputs_reads_sap_mcp_enabled(tmp_path, monkeypatch):
    import run_emit

    cfg = tmp_path / "config.yaml"
    cfg.write_text("auth_profile: cognito-m2m\nsap_mcp:\n  enabled: true\n")
    monkeypatch.setattr(run_emit, "_CDK_CONFIG", cfg)
    monkeypatch.delenv("AUTH_PROFILE", raising=False)
    profile, inbound, frontend, mcp_enabled = run_emit._cdk_inputs()
    assert profile == "cognito-m2m"
    assert mcp_enabled is True


def test_cdk_inputs_sap_mcp_absent_defaults_false(tmp_path, monkeypatch):
    import run_emit

    cfg = tmp_path / "config.yaml"
    cfg.write_text("auth_profile: cognito-basic\n")
    monkeypatch.setattr(run_emit, "_CDK_CONFIG", cfg)
    monkeypatch.delenv("AUTH_PROFILE", raising=False)
    profile, inbound, frontend, mcp_enabled = run_emit._cdk_inputs()
    assert mcp_enabled is False


def test_cdk_inputs_env_branch_reads_mcp_from_config(tmp_path, monkeypatch):
    # env delivers profile/overrides; sap_mcp.enabled still comes from config.yaml.
    import run_emit

    cfg = tmp_path / "config.yaml"
    cfg.write_text("sap_mcp:\n  enabled: true\n")
    monkeypatch.setattr(run_emit, "_CDK_CONFIG", cfg)
    monkeypatch.setenv("AUTH_PROFILE", "entra-obo")
    profile, inbound, frontend, mcp_enabled = run_emit._cdk_inputs()
    assert profile == "entra-obo"
    assert mcp_enabled is True


def test_terraform_external_protocol_cognito_emits_empty_map(tmp_path):
    # external data source protocol: JSON query on stdin, JSON map(string) on stdout
    script = str(_REPO_ROOT / "scripts" / "deploy" / "run_emit.py")
    query = json.dumps(
        {"auth_profile": "cognito-basic", "discovery_url": "", "allowed_clients": ""}
    )
    proc = subprocess.run(
        [sys.executable, script, "--backend", "terraform"],
        input=query,
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {}  # stdout is pure JSON, empty map for cognito


def test_terraform_rejects_cdk_only_profile():
    """Terraform plan-time guard: profiles with CDK-only axes (non-basic outbound,
    batch mode, direct-* frontend) must fail at plan, not silently deploy wrong."""
    script = str(_REPO_ROOT / "scripts" / "deploy" / "run_emit.py")
    query = json.dumps(
        {
            "auth_profile": "okta-userfed",
            "discovery_url": "https://dev.okta.com/oauth2/default/.well-known/openid-configuration",
            "allowed_clients": "okta-client-1,okta-client-2",
        }
    )
    proc = subprocess.run(
        [sys.executable, script, "--backend", "terraform"],
        input=query,
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert proc.returncode == 1
    assert "CDK-only" in proc.stderr
    assert "outbound" in proc.stderr  # names the problematic axis


from run_emit import _outbound_block  # noqa: E402


def test_outbound_block_basic_is_none():
    from utils.auth_profiles import resolve_profile

    assert _outbound_block(resolve_profile("cognito-basic")) is None


def test_outbound_block_m2m_service_only():
    from utils.auth_profiles import resolve_profile

    block = _outbound_block(resolve_profile("cognito-m2m"))
    assert block == {
        "flow": "M2M",
        "service_enabled": True,
        "user_enabled": False,
        "issuer_type": "sap",
    }


def test_outbound_block_userfed_user_only():
    from utils.auth_profiles import resolve_profile

    block = _outbound_block(resolve_profile("cognito-userfed-ias"))
    assert block["service_enabled"] is False
    assert block["user_enabled"] is True
    assert block["flow"] == "USER_FEDERATION"


def test_run_emit_cognito_m2m_writes_outbound_block(tmp_path):
    # inbound cognito + outbound m2m-sap: previously returned None; now writes an
    # artifact carrying the outbound block (no inbound block).
    out = tmp_path / "artifact.json"
    result = run_emit("cognito-m2m", overrides=None, out_path=str(out))
    assert result is not None
    assert result["outbound"]["service_enabled"] is True
    assert "inbound" not in result
    assert out.exists()


def test_run_emit_cognito_basic_still_writes_nothing(tmp_path):
    out = tmp_path / "artifact.json"
    assert run_emit("cognito-basic", overrides=None, out_path=str(out)) is None
    assert not out.exists()


def test_run_emit_direct_obo_on_mcp_path_emits(tmp_path):
    # Direct-to-MCP OBO (obo_direct_mcp:true) is exempt from the Gateway
    # mcp_supported:false guard, so enabling the MCP path emits rather than aborts.
    out = tmp_path / "artifact.json"
    art = run_emit(
        "entra-obo", overrides=ENTRA_OVERRIDES, out_path=str(out), mcp_path=True
    )
    assert art is not None
    assert art["outbound"]["obo_direct_mcp"] is True


FRONTEND_OVERRIDES = {
    "discovery_url": "https://login.microsoftonline.com/T/v2.0/.well-known/openid-configuration",
    "client_id": "spa-client-id",
    "authority": "https://login.microsoftonline.com/T/v2.0",
}


def test_okta_userfed_emits_frontend_and_inbound_blocks(tmp_path):
    # okta-userfed: frontend direct-okta (issuer okta) AND inbound okta -> both blocks.
    out = tmp_path / "artifact.json"
    result = run_emit(
        "okta-userfed",
        overrides=ENTRA_OVERRIDES,  # reused as a generic non-cognito inbound override
        out_path=str(out),
        frontend_overrides=FRONTEND_OVERRIDES,
        include_frontend=True,
    )
    assert result is not None
    assert "frontend" in result
    assert "inbound" in result
    assert result["frontend"]["issuer_type"] == "okta"
    assert result["frontend"]["client_id"] == "spa-client-id"
    assert "scope" not in result["frontend"]  # not supplied
    assert out.exists()


def test_entra_userfed_cognito_federated_omits_frontend_block(tmp_path):
    # frontend cognito+federated (issuer cognito) -> NO frontend block; but
    # outbound user-federation -> outbound block, so result is not None.
    out = tmp_path / "artifact.json"
    result = run_emit(
        "entra-userfed",
        overrides=None,
        out_path=str(out),
        frontend_overrides=None,
        include_frontend=True,
    )
    assert result is not None
    assert "frontend" not in result
    assert "outbound" in result


def test_entra_obo_emits_both_frontend_and_inbound(tmp_path):
    out = tmp_path / "artifact.json"
    result = run_emit(
        "entra-obo",
        overrides=ENTRA_OVERRIDES,
        out_path=str(out),
        frontend_overrides=FRONTEND_OVERRIDES,
        include_frontend=True,
    )
    assert result is not None
    assert result["frontend"]["issuer_type"] == "entra"
    assert result["inbound"]["issuer_type"] == "entra"


def test_frontend_scope_included_when_supplied():
    from utils.auth_profiles import resolve_profile

    profile = resolve_profile("okta-userfed")
    block = _frontend_block(
        profile, {**FRONTEND_OVERRIDES, "scope": "email openid profile offline_access"}
    )
    assert block["scope"] == "email openid profile offline_access"


def test_direct_frontend_missing_client_id_raises():
    from utils.auth_profiles import resolve_profile

    profile = resolve_profile("okta-userfed")
    with pytest.raises(ValueError, match="client_id"):
        _frontend_block(
            profile, {"discovery_url": "https://x/.well-known/openid-configuration"}
        )


def test_cognito_basic_frontend_block_is_none():
    from utils.auth_profiles import resolve_profile

    profile = resolve_profile("cognito-basic")  # frontend: cognito, no issuer key
    assert _frontend_block(profile, None) is None


from run_emit import _mode_block  # noqa: E402


def _catalog():
    from utils.auth_profiles import load_catalog

    return load_catalog()


def test_mode_block_autonomous_live_is_none():
    from utils.auth_profiles import resolve_profile

    assert _mode_block(resolve_profile("cognito-basic"), _catalog()) is None


def test_mode_block_live_only_is_none():
    from utils.auth_profiles import resolve_profile

    assert _mode_block(resolve_profile("cognito-userfed-ias"), _catalog()) is None


def test_mode_block_batch_enabled():
    from utils.auth_profiles import resolve_profile

    block = _mode_block(resolve_profile("entra-userfed"), _catalog())
    assert block == {
        "modes": ["live", "batch"],
        "batch_runner_enabled": True,
        "requires_refresh": True,
    }


def test_mode_block_reads_full_list_not_last_value():
    # order-independence: batch anywhere in the list enables the runner (proves it
    # does NOT rely on axis_meta["mode"] == values[-1]). Build an in-test profile.
    from utils.auth_profiles import resolve_profile

    cat = _catalog()
    cat["profiles"]["_t_batch_first"] = {
        "frontend": "cognito",
        "inbound": "cognito",
        "mode": ["batch", "live"],
        "outbound": "user-federation",
    }
    block = _mode_block(resolve_profile("_t_batch_first", cat), cat)
    assert block["batch_runner_enabled"] is True


def test_run_emit_entra_userfed_writes_mode_block(tmp_path):
    out = tmp_path / "artifact.json"
    result = run_emit("entra-userfed", overrides=None, out_path=str(out))
    assert result is not None
    assert result["mode"]["batch_runner_enabled"] is True
    assert "inbound" not in result  # inbound is cognito -> no inbound block
    assert out.exists()


def test_run_emit_batch_with_non_refresh_outbound_raises(tmp_path):
    # existing validate_profile guard must fire BEFORE emit — not duplicated here.
    from utils.auth_profiles import load_catalog

    cat = load_catalog()
    cat["profiles"]["_t_batch_basic"] = {
        "frontend": "cognito",
        "inbound": "cognito",
        "mode": ["batch"],
        "outbound": "basic",
    }
    out = tmp_path / "artifact.json"
    with pytest.raises(ProfileValidationError):
        run_emit("_t_batch_basic", overrides=None, out_path=str(out), catalog=cat)
    assert not out.exists()


def test_terraform_guard_rejects_obo_profile_as_cdk_only(tmp_path):
    """entra-obo has a CDK-only outbound (obo) + direct-* frontend, so the
    Terraform plan-time guard fires BEFORE the mcp_path check. The mcp_path
    exemption is still verified at the Python API level (test_auth_profiles.py)."""
    script = str(_REPO_ROOT / "scripts" / "deploy" / "run_emit.py")
    for mcp_flag in ("true", "false"):
        query = json.dumps(
            {
                "auth_profile": "entra-obo",
                "discovery_url": ENTRA_OVERRIDES["discovery_url"],
                "allowed_clients": "entra-app-id",
                "sap_mcp_enabled": mcp_flag,
            }
        )
        proc = subprocess.run(
            [sys.executable, script, "--backend", "terraform"],
            input=query,
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
        )
        assert proc.returncode == 1, f"mcp={mcp_flag}: expected exit 1"
        assert "CDK-only" in proc.stderr
        assert "outbound" in proc.stderr


def test_run_emit_banner_names_stub_axes():
    # entra-obo has no stub axes left, so use okta-userfed (still has stub axes)
    # to exercise the "names stub axes" banner path.
    from run_emit import run_emit

    art = run_emit("okta-userfed", overrides=ENTRA_OVERRIDES, out_path="/dev/null")
    assert "stub_axes" in art
    assert "stub axes" in art["banner"]


def test_run_emit_entra_obo_is_verified_no_stubs():
    # entra-obo has no stub axes, so its banner reports verified end-to-end
    # rather than the "not verified" warning.
    from run_emit import run_emit

    art = run_emit("entra-obo", overrides=ENTRA_OVERRIDES, out_path="/dev/null")
    assert "stub_axes" not in art
    assert "verified end-to-end" in art["banner"]


def test_run_emit_default_has_no_stub_axes_key():
    from run_emit import run_emit

    art = run_emit("cognito-basic", overrides=None, out_path="/dev/null")
    # cognito-basic is all-live -> None artifact (cognito+basic no-op) OR no stub_axes
    assert art is None or "stub_axes" not in art


def test_direct_frontend_missing_authority_raises():
    from utils.auth_profiles import resolve_profile

    profile = resolve_profile("okta-userfed")
    # direct frontend now REQUIRES authority (the issuer) so SPA signin can't crash
    with pytest.raises(ValueError, match="authority"):
        _frontend_block(
            profile,
            {
                "discovery_url": "https://x/.well-known/openid-configuration",
                "client_id": "spa-client-id",
            },
        )


def test_cognito_m2m_artifact_shape_is_outbound_only(tmp_path):
    # cognito-m2m is GA: inbound cognito (NO inbound block) + outbound m2m-sap
    # (outbound block present). This is the exact shape the CDK resolvers must
    # handle — resolveInboundAuthorizer falls back to Cognito (no inbound key),
    # resolveOutboundProfile reads the outbound block. Lock the contract here.
    out = tmp_path / "artifact.json"
    art = run_emit("cognito-m2m", overrides=None, out_path=str(out))
    assert art is not None
    assert "inbound" not in art  # cognito inbound -> no override, CDK falls back
    assert art["outbound"]["service_enabled"] is True
    assert art["outbound"]["user_enabled"] is False
    assert art["outbound"]["flow"] == "M2M"
    # Snake_case keys the TS consumers read verbatim — a rename must fail here.
    assert set(art["outbound"]) >= {
        "flow",
        "service_enabled",
        "user_enabled",
        "issuer_type",
    }


def test_obo_catalog_values_carry_direct_mcp_signal_and_keep_mcp_unsupported():
    from utils.auth_profiles import load_catalog

    outbound = load_catalog()["axes"]["outbound"]
    for value in ("obo", "obo-okta"):
        meta = outbound[value]
        assert meta["obo_direct_mcp"] is True
        # mcp_supported MUST stay false — Gateway+OBO is honestly blocked.
        # (obo_direct_mcp is the separate signal for the allowed direct-to-MCP path.)
        assert meta["mcp_supported"] is False
    # obo (entra) has no stub status; obo-okta is still a stub.
    assert "status" not in outbound["obo"]
    assert outbound["obo-okta"].get("status") == "stub"


def test_outbound_block_obo_carries_direct_mcp_and_invocation_url():
    from utils.auth_profiles import resolve_profile

    block = _outbound_block(resolve_profile("entra-obo"))
    # Existing keys unchanged (OBO is a user flow).
    assert block["flow"] == "ON_BEHALF_OF_TOKEN_EXCHANGE"
    assert block["service_enabled"] is False
    assert block["user_enabled"] is True
    assert block["issuer_type"] == "entra"
    # New OBO-only keys for the direct-to-MCP path.
    assert block["obo_direct_mcp"] is True
    assert block["mcp_invocation_url"] == "https://example-mcp.invalid/mcp"


def test_outbound_block_obo_honors_custom_invocation_url():
    from utils.auth_profiles import resolve_profile

    block = _outbound_block(
        resolve_profile("entra-obo"),
        mcp_invocation_url="https://other-mcp.invalid/mcp",
    )
    assert block["mcp_invocation_url"] == "https://other-mcp.invalid/mcp"


def test_outbound_block_non_obo_has_no_direct_mcp_keys():
    from utils.auth_profiles import resolve_profile

    block = _outbound_block(resolve_profile("cognito-m2m"))
    assert "obo_direct_mcp" not in block
    assert "mcp_invocation_url" not in block


def test_run_emit_obo_artifact_has_direct_mcp_outbound(tmp_path):
    out = tmp_path / "artifact.json"
    art = run_emit("entra-obo", overrides=ENTRA_OVERRIDES, out_path=str(out))
    assert art is not None
    assert art["outbound"]["obo_direct_mcp"] is True
    assert art["outbound"]["mcp_invocation_url"] == "https://example-mcp.invalid/mcp"


def test_gateway_unsupported_outbound_still_blocked_on_mcp_path(tmp_path):
    # Exempting the DIRECT-MCP path did NOT weaken the guard: a Gateway-mediated
    # outbound marked mcp_supported:false (no obo_direct_mcp) must STILL abort at
    # emit on the MCP path. Synthesize one, since every catalog obo value is direct.
    from utils.auth_profiles import load_catalog

    cat = load_catalog()
    cat["axes"]["outbound"]["gateway-unsupported"] = {
        "maturity": "experimental",
        "mcp_oauth_flow": "M2M",
        "issuer": "sap",
        "mcp_supported": False,
    }
    cat["profiles"]["_gw_unsupported"] = {
        "frontend": "cognito",
        "inbound": "cognito",
        "mode": ["autonomous", "live"],
        "outbound": "gateway-unsupported",
    }
    out = tmp_path / "artifact.json"
    with pytest.raises(ProfileValidationError):
        run_emit(
            "_gw_unsupported",
            overrides=None,
            out_path=str(out),
            mcp_path=True,
            catalog=cat,
        )
    assert not out.exists()


def test_cognito_basic_unchanged_after_obo_change(tmp_path):
    out = tmp_path / "artifact.json"
    assert run_emit("cognito-basic", overrides=None, out_path=str(out)) is None
    assert not out.exists()


def test_cognito_m2m_outbound_block_unchanged_after_obo_change(tmp_path):
    out = tmp_path / "artifact.json"
    art = run_emit("cognito-m2m", overrides=None, out_path=str(out))
    assert art["outbound"] == {
        "flow": "M2M",
        "service_enabled": True,
        "user_enabled": False,
        "issuer_type": "sap",
    }
    assert "inbound" not in art
