# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for scripts/deploy/emit_resolved_profile.py."""

import sys
from pathlib import Path

import pytest

# agentcore/agent is on sys.path via conftest.py; scripts/deploy is local-only.
sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent.parent / "scripts" / "deploy")
)

from emit_resolved_profile import emit_resolved_profile  # noqa: E402
from utils.auth_profiles import ProfileValidationError  # noqa: E402

_REGION = "us-east-1"
_POOL = "us-east-1_ABC123"
_CLIENTS = ["webclient123", "machineclient456"]


def test_cognito_profile_builds_cognito_discovery_and_clients():
    art = emit_resolved_profile(
        "cognito-basic", region=_REGION, pool_id=_POOL, web_client_ids=_CLIENTS
    )
    assert art["profile"] == "cognito-basic"
    assert art["maturity"] == "ga"
    assert art["inbound"]["issuer_type"] == "cognito"
    assert art["inbound"]["discovery_url"] == (
        "https://cognito-idp.us-east-1.amazonaws.com/"
        "us-east-1_ABC123/.well-known/openid-configuration"
    )
    assert art["inbound"]["allowed_clients"] == _CLIENTS


def test_ga_profile_has_no_warning_banner():
    art = emit_resolved_profile(
        "cognito-basic", region=_REGION, pool_id=_POOL, web_client_ids=_CLIENTS
    )
    assert "⚠" not in art["banner"]


def test_entra_profile_uses_overrides():
    # entra-obo has inbound: entra, so it exercises the override branch (unlike
    # entra-userfed, which has inbound: cognito).
    art = emit_resolved_profile(
        "entra-obo",
        region=_REGION,
        pool_id=_POOL,
        web_client_ids=_CLIENTS,
        mcp_path=False,  # entra-obo is mcp_supported:false; validate off the MCP path
        overrides={
            "discovery_url": "https://login.microsoftonline.com/tid/v2.0/.well-known/openid-configuration",
            "allowed_clients": ["entra-app-id"],
        },
    )
    assert art["inbound"]["issuer_type"] == "entra"
    assert art["inbound"]["discovery_url"].startswith(
        "https://login.microsoftonline.com"
    )
    assert art["inbound"]["allowed_clients"] == ["entra-app-id"]
    assert "PREVIEW" in art["banner"] and "verified end-to-end" in art["banner"]


def test_non_cognito_inbound_missing_overrides_raises():
    with pytest.raises(ValueError, match="discovery_url"):
        emit_resolved_profile(
            "entra-obo",
            region=_REGION,
            pool_id=_POOL,
            web_client_ids=_CLIENTS,
            mcp_path=False,
            overrides=None,
        )


def test_gateway_unsupported_outbound_on_mcp_path_raises():
    # A Gateway-mediated outbound marked mcp_supported:false (no obo_direct_mcp) is
    # rejected on the MCP path even when nothing else requires an override.
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
    with pytest.raises(ProfileValidationError, match="mcp_supported"):
        emit_resolved_profile(
            "_gw_unsupported",
            region=_REGION,
            pool_id=_POOL,
            web_client_ids=_CLIENTS,
            mcp_path=True,
            catalog=cat,
        )


def test_direct_obo_on_mcp_path_is_exempt():
    # Direct-to-MCP OBO (obo_direct_mcp:true) bypasses the Gateway, so the
    # mcp_supported:false guard does not fire — the inbound block is emitted.
    art = emit_resolved_profile(
        "entra-obo",
        region=_REGION,
        pool_id=_POOL,
        web_client_ids=_CLIENTS,
        mcp_path=True,
        overrides={
            "discovery_url": "https://login.microsoftonline.com/tid/v2.0/.well-known/openid-configuration",
            "allowed_clients": ["entra-app-id"],
        },
    )
    assert art["inbound"]["issuer_type"] == "entra"
