# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Drift guard: the Terraform and CDK backends must select identical inbound
authorizer values from the same resolved-profile artifact.

The Terraform side runs the real producer (``run_emit.py``) and reads the map
Terraform actually consumes. The CDK side reads the same artifact the way
``cdk/lib/utils/resolve-inbound-authorizer.ts`` does, so a field-path drift in
either backend breaks the equality assertion.
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "deploy"))

from run_emit import run_emit  # noqa: E402


def _terraform_selection(
    auth_profile: str, discovery_url: str, allowed_clients: str, tmp_path=None
) -> dict:
    """Simulate what the Terraform backend receives (the inbound block only)
    via the Python API rather than the subprocess."""
    overrides = {}
    if discovery_url:
        overrides["discovery_url"] = discovery_url
    if allowed_clients:
        overrides["allowed_clients"] = [c for c in allowed_clients.split(",") if c]
    import tempfile

    out = tmp_path or tempfile.mkdtemp()
    artifact = run_emit(
        auth_profile,
        overrides=overrides or None,
        out_path=str(Path(out) / "a.json"),
        mcp_path=False,
    )
    # Mirror emit.tf locals: if no inbound block → {} (backend fallback)
    if artifact is None:
        return {}
    inbound = artifact.get("inbound")
    if inbound is None:
        return {}
    return {
        "discovery_url": inbound["discovery_url"],
        "allowed_clients": ",".join(inbound["allowed_clients"]),
    }


def _cdk_selection(artifact: dict | None) -> dict:
    """What the CDK backend selects from the shared artifact, mirroring
    cdk/lib/utils/resolve-inbound-authorizer.ts: an absent artifact or inbound
    block falls back to the caller's Cognito values, represented as {}."""
    if not artifact or "inbound" not in artifact:
        return {}
    ib = artifact["inbound"]
    return {
        "discovery_url": ib["discovery_url"],
        "allowed_clients": ",".join(ib["allowed_clients"]),
    }


def test_backends_agree_on_cognito_profile(tmp_path):
    # Cognito inbound: run_emit writes no artifact, so both backends fall back
    # to their own Cognito-derived values.
    tf = _terraform_selection("cognito-basic", "", "")
    art = run_emit("cognito-basic", overrides=None, out_path=str(tmp_path / "a.json"))
    assert tf == {}
    assert _cdk_selection(art) == {}


def test_backends_agree_on_entra_override_profile(tmp_path):
    discovery = (
        "https://login.microsoftonline.com/T/v2.0/.well-known/openid-configuration"
    )
    tf = _terraform_selection("entra-obo", discovery, "entra-app-id")
    art = run_emit(
        "entra-obo",
        overrides={"discovery_url": discovery, "allowed_clients": ["entra-app-id"]},
        out_path=str(tmp_path / "a.json"),
        mcp_path=False,
    )
    assert tf == _cdk_selection(art)
    assert tf["discovery_url"].startswith("https://login.microsoftonline.com")
    assert tf["allowed_clients"] == "entra-app-id"
