# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# This is sample code. Not for use in production.
# See NOTICE and LICENSE for more information.
"""Unit tests for scripts/deploy/deploy-frontend.py OIDC-config resolution."""

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
# deploy-frontend.py has a hyphen — load it by path.
_spec = importlib.util.spec_from_file_location(
    "deploy_frontend", _REPO_ROOT / "scripts" / "deploy" / "deploy-frontend.py"
)
deploy_frontend = importlib.util.module_from_spec(_spec)
sys.modules["deploy_frontend"] = deploy_frontend
_spec.loader.exec_module(deploy_frontend)

_resolve_oidc_config = deploy_frontend._resolve_oidc_config

COGNITO_OUTPUTS = {
    "CognitoUserPoolId": "us-east-1_ABC",
    "CognitoClientId": "cog-client",
}


def test_cognito_path_builds_authority_from_pool():
    cfg = _resolve_oidc_config(COGNITO_OUTPUTS, "us-east-1", None)
    assert (
        cfg["authority"] == "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_ABC"
    )
    assert cfg["client_id"] == "cog-client"
    assert cfg["scope"] == "email openid profile"


def test_cognito_path_missing_outputs_raises():
    with pytest.raises(ValueError, match="CognitoUserPoolId|CognitoClientId"):
        _resolve_oidc_config({}, "us-east-1", None)


def test_frontend_block_emits_metadata_url_verbatim():
    block = {
        "issuer_type": "entra",
        "discovery_url": "https://login.microsoftonline.com/T/v2.0/.well-known/openid-configuration",
        "client_id": "spa-client-id",
    }
    cfg = _resolve_oidc_config({}, "us-east-1", block)  # no Cognito outputs needed
    assert (
        cfg["metadata_url"] == block["discovery_url"]
    )  # passed through, not surgically stripped
    assert "authority" not in cfg
    assert cfg["client_id"] == "spa-client-id"
    assert cfg["scope"] == "email openid profile"


def test_frontend_block_metadata_url_handles_okta_custom_authserver():
    # A non-standard (Okta custom auth-server) discovery path must pass through
    # verbatim as metadata_url rather than being rewritten into an authority.
    block = {
        "issuer_type": "okta",
        "discovery_url": "https://dev.okta.com/oauth2/aus1abc/.well-known/openid-configuration",
        "client_id": "okta-spa",
        "scope": "email openid profile offline_access",
    }
    cfg = _resolve_oidc_config({}, "us-east-1", block)
    assert cfg["metadata_url"] == block["discovery_url"]
    assert cfg["scope"] == "email openid profile offline_access"


def test_direct_entra_block_from_run_emit_resolves_authority_and_metadata(tmp_path):
    # oidc-client-ts requires authority at signin even when metadata_url is set,
    # so the direct-entra path must emit both.
    from run_emit import run_emit

    frontend_overrides = {
        "discovery_url": "https://login.microsoftonline.com/T/v2.0/.well-known/openid-configuration",
        "client_id": "spa-client-id",
        "authority": "https://login.microsoftonline.com/T/v2.0",
        "scope": "email openid profile offline_access",
    }
    inbound_overrides = {
        "discovery_url": "https://login.microsoftonline.com/T/v2.0/.well-known/openid-configuration",
        "allowed_clients": ["spa-client-id"],
    }
    out = tmp_path / "artifact.json"
    artifact = run_emit(
        "entra-obo",
        overrides=inbound_overrides,
        out_path=str(out),
        frontend_overrides=frontend_overrides,
        include_frontend=True,
    )
    assert artifact is not None
    block = artifact["frontend"]
    assert block["issuer_type"] == "entra"
    assert block["authority"] == "https://login.microsoftonline.com/T/v2.0"

    cfg = _resolve_oidc_config({}, "us-east-1", block)  # no Cognito outputs
    assert cfg["metadata_url"] == frontend_overrides["discovery_url"]
    assert cfg["authority"] == "https://login.microsoftonline.com/T/v2.0"
    assert cfg["client_id"] == "spa-client-id"
    assert cfg["scope"] == "email openid profile offline_access"


def test_cdk_inputs_unpacks_into_frontend_deploy_arity():
    # deploy-frontend.py main() unpacks _cdk_inputs() into 4 targets. Lock that
    # arity here so a producer arity change fails a test, not a customer deploy.
    from run_emit import _cdk_inputs

    result = _cdk_inputs()
    assert len(result) == 4
    profile_name, inbound_overrides, frontend_overrides, _mcp_enabled = result
    assert isinstance(profile_name, str)
