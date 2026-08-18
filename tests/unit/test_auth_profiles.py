# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for agentcore/agent/utils/auth_profiles.py."""

import pytest
from utils.auth_profiles import (
    ProfileValidationError,
    load_catalog,
    resolve_profile,
    stub_blockers,
    stubbed_axes,
    validate_profile,
)


def test_default_profile_resolves_and_is_ga():
    p = resolve_profile("cognito-basic")
    assert p.frontend == "cognito"
    assert p.inbound == "cognito"
    assert p.outbound == "basic"
    assert "autonomous" in p.mode and "live" in p.mode
    assert p.maturity == "ga"


def test_maturity_is_minimum_across_axes():
    # entra-obo: direct-entra(preview) + entra(preview) + live(ga) + obo(preview) -> preview.
    p = resolve_profile("entra-obo")
    assert p.maturity == "preview"
    assert p.verified is True


def test_userfed_profile_is_preview():
    # cognito(ga) + cognito(ga) + live(ga) + user-federation(preview) -> preview
    p = resolve_profile("cognito-userfed-ias")
    assert p.maturity == "preview"


def test_axis_meta_carries_outbound_mcp_flow():
    p = resolve_profile("cognito-m2m")
    assert p.axis_meta["outbound"]["mcp_oauth_flow"] == "M2M"


def test_unknown_profile_raises():
    with pytest.raises(KeyError):
        resolve_profile("does-not-exist")


def test_custom_disabled_raises():
    with pytest.raises(ValueError):
        resolve_profile("custom")


def test_catalog_has_expected_axes():
    cat = load_catalog()
    assert set(cat["axes"]) == {"frontend", "inbound", "mode", "outbound"}


def test_default_profile_validates():
    validate_profile(resolve_profile("cognito-basic"))  # no raise


def test_cognito_inbound_cannot_obo():
    # entra-obo has entra inbound so passes rule 2; build a cognito+obo tuple via catalog edit
    cat = load_catalog()
    cat["profiles"]["cognito-obo-bad"] = {
        "frontend": "cognito",
        "inbound": "cognito",
        "mode": ["live"],
        "outbound": "obo",
    }
    p = resolve_profile("cognito-obo-bad", cat)
    with pytest.raises(ProfileValidationError, match="OBO"):
        validate_profile(p)


def test_obo_requires_same_issuer():
    p = resolve_profile("entra-obo")  # entra/entra/entra -> valid
    validate_profile(p)  # no raise
    cat = load_catalog()
    cat["profiles"]["mixed-obo"] = {
        "frontend": "direct-okta",
        "inbound": "entra",
        "mode": ["live"],
        "outbound": "obo",
    }
    with pytest.raises(ProfileValidationError, match="issuer"):
        validate_profile(resolve_profile("mixed-obo", cat))


def test_batch_requires_refresh_only_for_user_identity_outbound():
    # Refresh is required by acting as an ABSENT HUMAN, not by being unattended.
    # A user-identity outbound with no refresh cannot outlive the authorizing
    # session, so it is rejected...
    cat = load_catalog()
    cat["profiles"]["batch-obo-bad"] = {
        "frontend": "direct-entra",
        "inbound": "entra",
        "mode": ["batch"],
        "outbound": "obo",
    }
    with pytest.raises(ProfileValidationError, match="refresh"):
        validate_profile(resolve_profile("batch-obo-bad", cat))

    # ...but a service identity re-mints per run (client_credentials), so batch over
    # m2m/basic needs no stored token and MUST be allowed — that is the built path.
    cat["profiles"]["batch-m2m-ok"] = {
        "frontend": "cognito",
        "inbound": "cognito",
        "mode": ["autonomous", "batch"],
        "outbound": "m2m-sap",
    }
    validate_profile(resolve_profile("batch-m2m-ok", cat))  # no raise
    validate_profile(resolve_profile("cognito-m2m-batch", cat))  # the shipped profile


def test_mcp_path_allows_direct_obo():
    # obo/obo-okta carry mcp_supported:false (no Gateway MCP) AND obo_direct_mcp:true
    # (the agent dials the external MCP directly). The mcp_path guard blocks the
    # Gateway combo but MUST exempt the direct path — otherwise entra-obo can never
    # deploy with the SAP MCP path enabled (the two states are mutually exclusive).
    p = resolve_profile("entra-obo")
    validate_profile(p, mcp_path=True)  # no raise — direct-to-MCP path is exempt


def test_mcp_path_rejects_gateway_unsupported_outbound():
    # A non-direct outbound marked mcp_supported:false (Gateway can't carry it) IS
    # still rejected on the MCP path. Synthesize one so the guard stays load-bearing
    # even though every catalog obo value happens to be obo_direct_mcp.
    cat = load_catalog()
    cat["axes"]["outbound"]["gateway-unsupported"] = {
        "maturity": "experimental",
        "mcp_oauth_flow": "M2M",
        "issuer": "sap",
        "mcp_supported": False,
    }
    cat["profiles"]["gateway-unsupported-bad"] = {
        "frontend": "cognito",
        "inbound": "cognito",
        "mode": ["autonomous", "live"],
        "outbound": "gateway-unsupported",
    }
    p = resolve_profile("gateway-unsupported-bad", cat)
    with pytest.raises(ProfileValidationError, match="mcp_supported"):
        validate_profile(p, mcp_path=True)


def test_all_curated_profiles_pass_validator():
    # Both deployable and preview profiles must resolve + validate (preview means
    # "IaC not built", not "invalid topology").
    cat = load_catalog()
    for name in {**cat["profiles"], **cat.get("preview_profiles", {})}:
        validate_profile(resolve_profile(name, cat))


def test_autonomous_only_cannot_user_federation():
    # autonomous has no user present -> UF/OBO impossible
    cat = load_catalog()
    cat["profiles"]["auto-uf-bad"] = {
        "frontend": "cognito",
        "inbound": "cognito",
        "mode": ["autonomous"],
        "outbound": "user-federation",
    }
    with pytest.raises(ProfileValidationError, match="user-identity mode"):
        validate_profile(resolve_profile("auto-uf-bad", cat))


def test_autonomous_only_cannot_obo():
    cat = load_catalog()
    cat["profiles"]["auto-obo-bad"] = {
        "frontend": "direct-entra",
        "inbound": "entra",
        "mode": ["autonomous"],
        "outbound": "obo",
    }
    with pytest.raises(ProfileValidationError, match="user-identity mode"):
        validate_profile(resolve_profile("auto-obo-bad", cat))


def test_live_with_basic_is_legal():
    # The relaxation: live/batch MAY use service-identity outbound (no user
    # propagation, but not illegal). cognito-basic is exactly this shape.
    validate_profile(resolve_profile("cognito-basic"))  # no raise
    validate_profile(resolve_profile("cognito-m2m"))  # live + m2m, no raise


def test_mixed_mode_with_userfed_is_legal():
    # A profile carrying [autonomous, live] + user-federation is legal because
    # 'live' supplies the user-identity mode; autonomy is just also-supported.
    cat = load_catalog()
    cat["profiles"]["mixed-uf-ok"] = {
        "frontend": "cognito",
        "inbound": "cognito",
        "mode": ["autonomous", "live"],
        "outbound": "user-federation",
    }
    validate_profile(resolve_profile("mixed-uf-ok", cat))  # no raise


def test_deployable_profiles_have_no_stub_axes():
    # Contract for the `profiles` block: everything in it deploys today (no stub
    # axis). Anything with a stub axis belongs in `preview_profiles`.
    cat = load_catalog()
    for name in cat["profiles"]:
        assert stubbed_axes(resolve_profile(name, cat)) == [], (
            f"{name!r} is under `profiles` but has stub axes — move it to `preview_profiles`"
        )


def test_preview_profiles_each_have_a_stub_axis():
    # Contract for the `preview_profiles` block: it exists to hold not-yet-built
    # topologies, so each entry must have >=1 stub axis (else it should be promoted).
    cat = load_catalog()
    preview = cat.get("preview_profiles", {})
    assert preview, "expected a preview_profiles block"
    for name in preview:
        assert stubbed_axes(resolve_profile(name, cat)), (
            f"{name!r} is under `preview_profiles` but has no stub axis — promote it to `profiles`"
        )


def test_default_profile_has_no_stub_axes():
    assert stubbed_axes(resolve_profile("cognito-basic")) == []


def test_cognito_m2m_has_no_stub_axes():
    # m2m-sap is a built (live) outbound
    assert stubbed_axes(resolve_profile("cognito-m2m")) == []


def test_entra_obo_reports_no_stub_axes():
    # All three entra-obo axes (direct-entra frontend, entra inbound, obo outbound)
    # are verified and their status:stub cleared — the profile deploys today.
    stubs = stubbed_axes(resolve_profile("entra-obo"))
    assert stubs == []


def test_entra_and_okta_inbound_both_proven_independently():
    # entra + okta inbound share the generic inbound/jwt-authorizer module. Each had
    # its stub cleared only on its own evidence — entra via entra-obo, okta via a real
    # Okta id_token accepted by the deployed authorizer. Sharing a module must never be
    # the reason a value is live, so this asserts both are non-stub while
    # test_okta_userfed_still_stub_via_outbound keeps the shared axis from over-clearing.
    cat = load_catalog()
    for value in ("entra", "okta"):
        status = cat["axes"]["inbound"][value].get("status", "live")
        assert status == "live", (
            f"{value} inbound proven, should not be stub (got {status})"
        )


def test_every_stub_axis_declares_a_real_blocker():
    # blocked_by is what keeps `status: stub` from reading as "nobody built it" for
    # axes that are built and only awaiting external config. An unannotated stub
    # silently defaults to 'repo', so the vocabulary is pinned here.
    cat = load_catalog()
    for axis, values in cat["axes"].items():
        for value, meta in values.items():
            if meta.get("status", "live") == "stub":
                assert meta.get("blocked_by") in ("repo", "operator", "upstream"), (
                    f"axes.{axis}.{value} is stub with blocked_by="
                    f"{meta.get('blocked_by')!r}; use repo | operator | upstream"
                )


def test_okta_basic_has_no_stub_axes():
    # Both Okta axes cleared on their own evidence: a real login through the deployed
    # SPA (PKCE public client) and the id_token it issued accepted by the deployed
    # jwt-authorizer. `verified` stays unset — this profile's outbound is a Basic
    # technical user, so no live-SAP run happened through it.
    assert stubbed_axes(resolve_profile("okta-basic")) == []


def test_okta_userfed_still_stub_via_outbound():
    # okta-userfed shares both Okta axes with okta-basic, so clearing them must not
    # promote it — its `user-federation` outbound is still upstream-blocked in
    # AgentCore Identity's 3LO vault. Guards the shared-axis clear from over-reaching.
    assert stub_blockers(resolve_profile("okta-userfed")) == {"outbound": "upstream"}


def test_verified_profiles_have_no_stub_axes():
    # Coherence gate for the two promotion signals (docs/sap/PROFILE_PROMOTION.md):
    # `verified: true` means "run end-to-end against live SAP", which is impossible
    # if any selected axis is status:stub (its IaC isn't built). So verified ⇒ no
    # stub axes ⇒ it must live in `profiles:`, not `preview_profiles:`. Catches a
    # verified badge set on a not-yet-built profile.
    cat = load_catalog()
    both = {**cat.get("profiles", {}), **cat.get("preview_profiles", {})}
    for name, spec in both.items():
        if spec.get("verified"):
            assert stubbed_axes(resolve_profile(name, cat)) == [], (
                f"{name!r} is verified:true but has stub axes — cannot have run E2E "
                f"against IaC that isn't built; clear the stubs or drop verified"
            )
            assert name in cat.get("profiles", {}), (
                f"{name!r} is verified:true but sits in preview_profiles — promote it to `profiles`"
            )


def test_stubbed_axes_flags_mode_when_any_member_stub():
    # No shipped mode value is a stub any more (batch-runner is built), so drive the
    # ANY-member logic off a synthetic stub rather than a real profile — otherwise
    # this test silently stops exercising it.
    cat = load_catalog()
    cat["axes"]["mode"]["_t_stub_mode"] = {"maturity": "experimental", "status": "stub"}
    cat["profiles"]["_t_mixed_mode"] = {
        "frontend": "cognito",
        "inbound": "cognito",
        "mode": ["live", "_t_stub_mode"],
        "outbound": "basic",
    }
    stubs = stubbed_axes(resolve_profile("_t_mixed_mode", cat), cat)
    assert "mode" in stubs  # one stub member is enough
    assert stubbed_axes(resolve_profile("cognito-m2m-batch", cat), cat) == []
