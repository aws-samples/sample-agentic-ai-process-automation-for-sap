# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# This is sample code. Not for use in production.
# See NOTICE and LICENSE for more information.
"""Deploy-time: resolve + validate the selected auth profile and emit the
inbound-authorizer contract other IaC backends read (.auth-profile-resolved.json).

The single source of truth for resolution/validation is utils.auth_profiles;
this module only maps the resolved inbound axis value to concrete JWT-authorizer
fields (discovery_url + allowed_clients) and writes the artifact."""

from __future__ import annotations

import json

from utils.auth_profiles import ResolvedProfile, resolve_profile, validate_profile

ARTIFACT_FILENAME = ".auth-profile-resolved.json"


def banner(profile: ResolvedProfile) -> str:
    """One-line deploy banner: GA profiles get a check, everything else a maturity warning."""
    if profile.maturity == "ga":
        return f"✓ auth profile '{profile.name}' (GA) — {profile.outbound} outbound"
    if profile.verified:
        return (
            f"✓ auth profile '{profile.name}' ({profile.maturity.upper()}) — "
            f"{profile.outbound} outbound; verified end-to-end against a live system"
        )
    return (
        f"⚠ profile '{profile.name}' is {profile.maturity.upper()} — "
        "architecturally supported, not verified end-to-end"
    )


def _cognito_discovery_url(region: str, pool_id: str) -> str:
    return (
        f"https://cognito-idp.{region}.amazonaws.com/"
        f"{pool_id}/.well-known/openid-configuration"
    )


def emit_resolved_profile(
    profile_name: str,
    *,
    region: str,
    pool_id: str,
    web_client_ids: list[str],
    overrides: dict | None = None,
    mcp_path: bool = False,
    catalog: dict | None = None,
) -> dict:
    """Resolve+validate a profile and return the inbound-authorizer contract.

    For a Cognito inbound axis the discovery URL is built from region+pool_id and
    allowed_clients are the passed-in web/machine client ids. For entra/okta the
    caller must supply overrides={'discovery_url': ..., 'allowed_clients': [...]}.

    NOTE: the returned ``inbound.allowed_clients`` is a single list applied to
    BOTH authorizer sites (user->Runtime and Gateway) by each IaC backend. Any
    client id passed here becomes valid at both sites — pass only the clients
    you intend both to accept.
    """
    profile = resolve_profile(profile_name, catalog)
    validate_profile(profile, mcp_path=mcp_path)

    issuer_type = profile.inbound
    if issuer_type == "cognito":
        discovery_url = _cognito_discovery_url(region, pool_id)
        allowed_clients = list(web_client_ids)
    else:
        overrides = overrides or {}
        if "discovery_url" not in overrides:
            raise ValueError(
                f"inbound {issuer_type!r} requires overrides['discovery_url'] "
                "(no Cognito pool to derive it from)."
            )
        if "allowed_clients" not in overrides:
            raise ValueError(
                f"inbound {issuer_type!r} requires overrides['allowed_clients']."
            )
        discovery_url = overrides["discovery_url"]
        allowed_clients = list(overrides["allowed_clients"])

    return {
        "profile": profile.name,
        "maturity": profile.maturity,
        "banner": banner(profile),
        "inbound": {
            "issuer_type": issuer_type,
            "discovery_url": discovery_url,
            "allowed_clients": allowed_clients,
        },
    }


if __name__ == "__main__":  # pragma: no cover
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Emit resolved auth-profile artifact.")
    parser.add_argument("profile", nargs="?", default="cognito-basic")
    parser.add_argument("--region", required=True)
    parser.add_argument("--pool-id", required=True)
    parser.add_argument("--client-id", action="append", default=[], dest="client_ids")
    parser.add_argument("--discovery-url")
    parser.add_argument(
        "--allowed-client", action="append", default=[], dest="allowed_clients"
    )
    parser.add_argument("--mcp-path", action="store_true")
    parser.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parents[2] / ARTIFACT_FILENAME),
    )
    args = parser.parse_args()

    # Omit empty values so a partial override (e.g. only --allowed-client) still
    # trips emit_resolved_profile's explicit "requires discovery_url" ValueError,
    # rather than silently passing discovery_url=None.
    overrides = {
        k: v
        for k, v in (
            ("discovery_url", args.discovery_url),
            ("allowed_clients", args.allowed_clients or None),
        )
        if v
    } or None

    artifact = emit_resolved_profile(
        args.profile,
        region=args.region,
        pool_id=args.pool_id,
        web_client_ids=args.client_ids,
        overrides=overrides,
        mcp_path=args.mcp_path,
    )
    Path(args.out).write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    print(artifact["banner"])
