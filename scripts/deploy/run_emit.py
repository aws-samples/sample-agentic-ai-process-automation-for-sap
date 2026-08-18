# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# This is sample code. Not for use in production.
# See NOTICE and LICENSE for more information.
"""Deploy-time wrapper that emits the inbound-authorizer artifact for a selected
auth profile — unless the profile's inbound axis is Cognito, in which case both
IaC backends use their built-in fallback and nothing is emitted.

Two backend modes:
  --backend cdk        Reads auth_profile + inbound overrides from env vars
                       (AUTH_PROFILE / AUTH_INBOUND_DISCOVERY_URL /
                       AUTH_INBOUND_ALLOWED_CLIENTS) when set — the only source
                       reliably delivered into CodeBuild — else falls back to
                       cdk/config.yaml for local runs. Writes
                       .auth-profile-resolved.json (the CDK synth reads it),
                       prints the banner to stdout.
  --backend terraform  Terraform `external` data source protocol: reads a JSON query
                       {auth_profile, discovery_url, allowed_clients} from stdin, writes
                       a JSON map(string) to stdout ({} for cognito, else
                       {discovery_url, allowed_clients(csv)}), and ALSO writes the
                       artifact file. Banner/diagnostics go to stderr (stdout must be
                       pure JSON for the external provider).

Resolution/validation logic is NOT duplicated here — this only dispatches to
emit_resolved_profile() and resolve_profile()."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
# auth_profiles lives under agentcore/agent; emit_resolved_profile is a sibling here.
sys.path.insert(0, str(_REPO_ROOT / "agentcore" / "agent"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml  # noqa: E402  (PyYAML — same dep auth_profiles already requires)
from emit_resolved_profile import ARTIFACT_FILENAME, emit_resolved_profile  # noqa: E402
from utils.auth_profiles import (  # noqa: E402
    load_catalog,
    resolve_profile,
    stub_blockers,
    stubbed_axes,
    validate_profile,
)

_DEFAULT_OUT = _REPO_ROOT / ARTIFACT_FILENAME
_CDK_CONFIG = _REPO_ROOT / "cdk" / "config.yaml"


def _overrides_from_strings(
    discovery_url: str, allowed_clients_csv: str
) -> dict | None:
    """Build an overrides dict, OMITTING empty values so a genuinely-missing
    entra/okta override still triggers emit_resolved_profile's ValueError."""
    overrides: dict = {}
    if discovery_url:
        overrides["discovery_url"] = discovery_url
    if allowed_clients_csv:
        overrides["allowed_clients"] = [c for c in allowed_clients_csv.split(",") if c]
    return overrides or None


_USER_FLOWS = {"USER_FEDERATION", "ON_BEHALF_OF_TOKEN_EXCHANGE"}
# Placeholder MCP invocation URL; the CDK/Terraform synth publishes the real value
# resolved from the external SAP MCP stack at deploy.
_PLACEHOLDER_MCP_URL = "https://example-mcp.invalid/mcp"


def _outbound_block(
    profile,
    mcp_invocation_url: str = _PLACEHOLDER_MCP_URL,
    *,
    mcp_path: bool = False,
) -> dict | None:
    """Derive the SAP MCP target-variant flags from the resolved outbound axis.

    Returns None for the `basic` flow when sap_mcp is disabled (no SAP MCP target
    needed). When mcp_path is True (sap_mcp.enabled), BASIC emits a block with
    service_enabled=True so the external SAP MCP Service Gateway target is retained
    — BASIC describes the external MCP-to-SAP hop (service-account Basic Auth); the
    Gateway-to-external-runtime leg still uses OAuth2 client credentials.

    For non-basic flows returns {flow, service_enabled, user_enabled, issuer_type}.
    Mapping:
      M2M                       -> Service target
      USER_FEDERATION / OBO     -> User target

    For an OBO value carrying obo_direct_mcp (the direct-to-MCP path — the agent
    calls the external MCP directly with the user's Entra JWT, bypassing our
    Gateway), also emits obo_direct_mcp: true and mcp_invocation_url. This is a
    DISTINCT signal from mcp_supported: a Gateway-mediated mcp_supported:false
    outbound is blocked at the mcp-path emit guard, but the direct-to-MCP path is
    exempt (it doesn't use the Gateway).
    """
    meta = profile.axis_meta["outbound"]
    flow = meta.get("mcp_oauth_flow")
    if flow == "BASIC":
        if not mcp_path:
            return None
        # When the SAP MCP path is enabled, BASIC still needs a service target —
        # the Gateway dials the external runtime with OAuth2 client credentials,
        # and the external runtime uses Basic Auth toward SAP. Emit the block so
        # resolveOutboundProfile() sees service_enabled=true.
        return {
            "flow": "BASIC",
            "service_enabled": True,
            "user_enabled": False,
            "issuer_type": None,
        }
    block = {
        "flow": flow,
        "service_enabled": flow == "M2M",
        "user_enabled": flow in _USER_FLOWS,
        "issuer_type": meta.get("issuer"),
    }
    if meta.get("obo_direct_mcp"):
        block["obo_direct_mcp"] = True
        block["mcp_invocation_url"] = mcp_invocation_url
    return block


def _frontend_block(profile, frontend_overrides: dict | None) -> dict | None:
    """Assemble the SPA OIDC-issuer block for a non-cognito frontend axis.

    Returns None when the frontend axis resolves to a cognito issuer (plain
    `cognito` has no issuer key; `cognito+federated` has issuer 'cognito') — the
    SPA then uses its Cognito-built authority. For a direct-* frontend the caller
    MUST supply frontend_overrides['discovery_url'] and ['client_id']; a missing
    key raises ValueError (aborting the deploy before aws-exports.json is written).
    'scope' is optional — included only when supplied."""
    issuer = profile.axis_meta["frontend"].get("issuer")
    if issuer in (None, "cognito"):
        return None
    fo = frontend_overrides or {}
    for key in ("discovery_url", "client_id", "authority"):
        if not fo.get(key):
            raise ValueError(
                f"frontend {issuer!r} requires frontend_overrides[{key!r}] "
                "(direct-entra/direct-okta has no Cognito pool to derive it from)."
            )
    block = {
        "issuer_type": issuer,
        "discovery_url": fo["discovery_url"],
        "client_id": fo["client_id"],
        # authority = the IdP issuer, supplied explicitly (NOT derived from
        # discovery_url). oidc-client-ts requires a truthy authority at signin
        # even when metadata_url drives discovery.
        "authority": fo["authority"],
    }
    if fo.get("scope"):
        block["scope"] = fo["scope"]
    return block


def _cdk_only_axes(profile, catalog) -> list[str]:
    """Axes the resolved profile selects that the Terraform backend does NOT
    provision. Terraform consumes the inbound axis only (emit.tf → the JWT
    authorizer); the outbound SAP MCP target / OBO, the batch-mode runner, and
    the direct-IdP frontend are all wired by CDK, which has no Terraform module.
    A profile mixing those with a Terraform deploy would SILENTLY come up as plain
    Cognito on the missing axes — this lists the reasons so the caller can fail loud.
    Returns [] when the profile is inbound-axis-only (Terraform can deploy it)."""
    reasons: list[str] = []
    out_flow = profile.axis_meta["outbound"].get("mcp_oauth_flow")
    if out_flow != "BASIC":
        reasons.append(
            f"outbound '{profile.outbound}' (flow {out_flow}) needs the SAP MCP "
            "adapter — CDK-only, no Terraform module"
        )
    if _mode_requires_cdk(profile, catalog):
        reasons.append(
            f"mode {list(profile.mode)} includes 'batch' — the batch runner is CDK-only"
        )
    if "autonomous" not in profile.mode:
        # The inverse of the batch case: not something Terraform lacks a module for,
        # but something it cannot *withhold*. CDK reads the mode list and skips the
        # poller schedule, SQS queue and invoker for a live-only profile
        # (shouldProvisionAutonomous in backend-stack.ts). Terraform wires that
        # pipeline unconditionally, so a live-only profile would deploy an
        # autonomous path with no structurally possible caller. Fail loud instead.
        reasons.append(
            f"mode {list(profile.mode)} omits 'autonomous' — Terraform always wires "
            "the poller + SQS + invoker, which that profile can never trigger; only "
            "CDK can withhold them"
        )
    fe_issuer = profile.axis_meta["frontend"].get("issuer")
    if fe_issuer not in (None, "cognito"):
        reasons.append(
            f"frontend '{profile.frontend}' (issuer {fe_issuer}) is a direct-IdP SPA — "
            "the Terraform frontend deploy only emits the Cognito authority"
        )
    return reasons


def _mode_requires_cdk(profile, catalog) -> bool:
    """True when a selected mode value declares an iac_module, i.e. the mode axis
    provisions infrastructure only CDK can build (today: batch → mode/batch-runner).

    Split out of _mode_block deliberately. This is the *predicate* the Terraform
    loud-fail needs ("does the mode axis need CDK?"); _mode_block is the *payload*
    CDK reads. They used to be the same call, which forced _mode_block to return
    None for autonomous/live and so prevented the mode LIST from ever reaching CDK.
    Scans profile.mode, not axis_meta["mode"] (which holds only the last value)."""
    mode_axis = catalog["axes"]["mode"]
    return any(mode_axis[v].get("iac_module") for v in profile.mode)


def _mode_block(profile, catalog) -> dict | None:
    """Build the mode-axis block CDK reads, or None when the axis is inert.

    Returns {modes, batch_runner_enabled, requires_refresh} when the mode axis is
    ACTIONABLE, meaning it either provisions something (a value with an iac_module,
    today only batch) or CONSTRAINS something (the profile does not declare
    'autonomous', so the poller schedule and SQS consumer must not be wired).

    Returns None only when the axis is inert — autonomous IS declared and there is
    nothing to build. That avoids emitting a mode block for the cognito-basic default
    (when mcp_path is disabled, no other axis fires either and run_emit returns None;
    when mcp_path is enabled, the outbound block causes an artifact to be written but
    the mode axis is still inert). A profile missing 'autonomous' emits even when
    every other axis is a no-op, so the gate cannot be silently skipped.

    Discriminator = iac_module presence read from the catalog, not the value name."""
    mode_axis = catalog["axes"]["mode"]
    metas = [mode_axis[v] for v in profile.mode]
    batch_runner_enabled = any(m.get("iac_module") for m in metas)
    autonomous_declared = "autonomous" in profile.mode
    if not batch_runner_enabled and autonomous_declared:
        return None
    return {
        "modes": list(profile.mode),
        "batch_runner_enabled": batch_runner_enabled,
        "requires_refresh": any(m.get("requires_refresh") for m in metas),
    }


def run_emit(
    profile_name: str,
    *,
    overrides: dict | None,
    out_path: str,
    catalog: dict | None = None,
    mcp_path: bool = False,
    frontend_overrides: dict | None = None,
    include_frontend: bool = False,
    mcp_invocation_url: str = _PLACEHOLDER_MCP_URL,
) -> dict | None:
    """Emit the resolved-profile artifact for the inbound, outbound and/or frontend axes.

    Writes .auth-profile-resolved.json when the inbound axis is non-cognito, the
    outbound axis is non-basic, BASIC is selected with the SAP MCP path enabled,
    OR the mode axis is actionable (provisions a batch runner, or withholds
    'autonomous' so CDK must refuse the autonomous path).
    Returns the artifact dict, or None when every axis is its no-op value (cognito
    inbound + basic outbound + a mode list declaring 'autonomous'). The frontend block
    is assembled only when include_frontend is True (the frontend-deploy path); on that
    path a direct-* frontend with missing overrides raises ValueError (fail-loud).
    Always validates the profile (raising ProfileValidationError / ValueError)."""
    cat = catalog or load_catalog()
    profile = resolve_profile(profile_name, cat)
    validate_profile(profile, mcp_path=mcp_path)

    stubs = stubbed_axes(profile, cat)

    artifact: dict = {"profile": profile.name, "maturity": profile.maturity}
    if stubs:
        artifact["stub_axes"] = stubs

    if profile.inbound != "cognito":
        # emit_resolved_profile re-resolves + re-validates + shapes the inbound block.
        inbound_art = emit_resolved_profile(
            profile_name,
            region="",
            pool_id="",
            web_client_ids=[],
            overrides=overrides,
            mcp_path=mcp_path,
            catalog=catalog,
        )
        artifact["banner"] = inbound_art["banner"]
        artifact["inbound"] = inbound_art["inbound"]

    outbound = _outbound_block(
        profile, mcp_invocation_url=mcp_invocation_url, mcp_path=mcp_path
    )
    if outbound is not None:
        artifact["outbound"] = outbound

    if include_frontend:
        frontend = _frontend_block(profile, frontend_overrides)
        if frontend is not None:
            artifact["frontend"] = frontend

    mode_blk = _mode_block(profile, cat)
    if mode_blk is not None:
        artifact["mode"] = mode_blk

    if stubs:
        # Name the cause per axis: "no IaC yet" was wrong for axes whose wiring is
        # built and only awaiting external config (operator) or an AWS fix (upstream).
        blockers = stub_blockers(profile, cat)
        _CAUSE = {
            "repo": "wiring not built here",
            "operator": "wiring built, awaiting external config",
            "upstream": "wiring built, blocked in an AWS service",
        }
        detail = ", ".join(
            f"{a} ({_CAUSE[blockers[a]]})" if blockers.get(a) in _CAUSE else a
            for a in stubs
        )
        note = f"stub axes — not deployable end to end: {detail}"
        artifact["banner"] = (artifact.get("banner", "").rstrip() + "\n" + note).strip()
        artifact["stub_blockers"] = blockers

    if (
        "inbound" not in artifact
        and "outbound" not in artifact
        and "frontend" not in artifact
        and "mode" not in artifact
    ):
        return None
    Path(out_path).write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    return artifact


def _cdk_inputs() -> tuple[str, dict | None, dict | None, bool]:
    """Resolve (profile_name, inbound_overrides, frontend_overrides, mcp_enabled)
    for the CDK path.

    Env vars win for profile + inbound overrides (the only source reliably delivered
    into CodeBuild; cdk/config.yaml is git-ignored and not in the deployed zip).
    The canonical YAML keys auth_profile, inbound_overrides, and frontend_overrides
    are root-level; the former sap.* nesting remains a compatibility fallback.
    frontend_overrides and sap_mcp.enabled are read from cdk/config.yaml — both the
    frontend deploy and the SAP MCP adapter run locally where config.yaml is present,
    and the CDK adapter re-reads sap_mcp.enabled from config at synth regardless.
    mcp_enabled feeds the mcp_path guard so an mcp_supported:false profile aborts at
    emit when MCP is on; defaults False when the sap_mcp block/key is absent."""
    config: dict = {}
    if _CDK_CONFIG.exists():
        with open(_CDK_CONFIG, encoding="utf-8") as fh:
            config = yaml.safe_load(fh) or {}
    # Auth-profile settings are top-level in the public config contract. Accept
    # the briefly-shipped sap.* nesting as a compatibility fallback so existing
    # copied configs do not silently fall back to cognito-basic.
    legacy_sap = config.get("sap") or {}
    frontend_overrides = config.get(
        "frontend_overrides", legacy_sap.get("frontend_overrides")
    )
    inbound_overrides = config.get(
        "inbound_overrides", legacy_sap.get("inbound_overrides")
    )
    profile_name = config.get(
        "auth_profile", legacy_sap.get("auth_profile", "cognito-basic")
    )
    mcp_enabled = bool((config.get("sap_mcp") or {}).get("enabled", False))

    env_profile = os.environ.get("AUTH_PROFILE")
    if env_profile:
        overrides = _overrides_from_strings(
            os.environ.get("AUTH_INBOUND_DISCOVERY_URL", ""),
            os.environ.get("AUTH_INBOUND_ALLOWED_CLIENTS", ""),
        )
        return env_profile, overrides, frontend_overrides, mcp_enabled
    return profile_name, inbound_overrides, frontend_overrides, mcp_enabled


def _run_cdk() -> int:
    """Emit (or skip) from env-or-config inputs; print banner to stdout."""
    profile_name, overrides, frontend_overrides, mcp_enabled = _cdk_inputs()
    artifact = run_emit(
        profile_name,
        overrides=overrides,
        out_path=str(_DEFAULT_OUT),
        mcp_path=mcp_enabled,
        frontend_overrides=frontend_overrides,
        include_frontend=True,
    )
    if artifact is None:
        print(
            f"auth profile '{profile_name}': cognito inbound — using backend fallback, no artifact written"
        )
    else:
        print(
            artifact.get(
                "banner",
                f"auth profile '{profile_name}': outbound {artifact.get('outbound', {}).get('flow')} target selected",
            )
        )
    return 0


def _run_terraform() -> int:
    """external-data-source protocol: query on stdin, map(string) on stdout,
    diagnostics on stderr, artifact file also written."""
    query = json.load(sys.stdin)
    profile_name = query.get("auth_profile", "cognito-basic")
    overrides = _overrides_from_strings(
        query.get("discovery_url", ""), query.get("allowed_clients", "")
    )
    mcp_enabled = query.get("sap_mcp_enabled", "") == "true"
    cat = load_catalog()
    artifact = run_emit(
        profile_name,
        overrides=overrides,
        out_path=str(_DEFAULT_OUT),
        mcp_path=mcp_enabled,
        catalog=cat,
    )

    # Terraform wires only the inbound JWT authorizer; the outbound (SAP MCP
    # target / OBO), mode (batch runner), and frontend (direct-IdP SPA) axes
    # are CDK-only. Fail at plan rather than silently deploy the wrong thing.
    profile = resolve_profile(profile_name, cat)
    cdk_only = _cdk_only_axes(profile, cat)
    if cdk_only:
        reasons = "; ".join(cdk_only)
        print(
            f"ERROR: auth_profile '{profile_name}' selects axes that are CDK-only "
            f"(no Terraform module exists):\n  {reasons}\n"
            f"Use the CDK backend for this profile, or select 'cognito-basic' for "
            f"a Terraform deploy.",
            file=sys.stderr,
        )
        # Terraform external data sources interpret a non-zero exit + stderr as
        # a plan-time error, surfaced to the user as a terraform plan failure.
        return 1

    if artifact is None:
        print(
            f"auth profile '{profile_name}': cognito inbound — backend fallback",
            file=sys.stderr,
        )
        json.dump({}, sys.stdout)
    else:
        inbound = artifact.get("inbound")
        if inbound is None:
            print(
                artifact.get("banner", "outbound-only profile — no inbound override"),
                file=sys.stderr,
            )
            json.dump({}, sys.stdout)
        else:
            print(artifact["banner"], file=sys.stderr)
            json.dump(
                {
                    "discovery_url": inbound["discovery_url"],
                    "allowed_clients": ",".join(inbound["allowed_clients"]),
                },
                sys.stdout,
            )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Emit resolved auth-profile for a deploy backend."
    )
    parser.add_argument("--backend", required=True, choices=["cdk", "terraform"])
    args = parser.parse_args()
    return _run_cdk() if args.backend == "cdk" else _run_terraform()


if __name__ == "__main__":
    sys.exit(main())
