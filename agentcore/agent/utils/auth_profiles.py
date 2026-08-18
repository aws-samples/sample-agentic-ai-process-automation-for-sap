# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# This is sample code. Not for use in production.
# See NOTICE and LICENSE for more information.
"""Load and resolve pluggable auth profiles from auth-profiles.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

# Higher value = weaker maturity. Profile maturity = max() over selected axes.
MATURITY_ORDER = {"ga": 0, "preview": 1, "experimental": 2}
_AXES = ("frontend", "inbound", "mode", "outbound")

# Repo root is three parents up from agentcore/agent/utils/auth_profiles.py
_DEFAULT_PATH = Path(__file__).resolve().parents[3] / "auth-profiles.yaml"


def load_catalog(path: str | None = None) -> dict:
	"""Parse auth-profiles.yaml into a dict."""
	with open(path or _DEFAULT_PATH, encoding="utf-8") as fh:
		return yaml.safe_load(fh)


@dataclass
class ResolvedProfile:
	name: str
	frontend: str
	inbound: str
	mode: list[str]
	outbound: str
	maturity: str
	axis_meta: dict[str, dict] = field(default_factory=dict)
	# True when this exact profile has been run end-to-end against a live system.
	# Distinct from maturity (breadth of hardening); set per-profile in auth-profiles.yaml.
	verified: bool = False


def resolve_profile(name: str, catalog: dict | None = None) -> ResolvedProfile:
	"""Resolve a profile name to its axis tuple + metadata + computed maturity."""
	cat = catalog or load_catalog()

	if name == "custom":
		custom = cat.get("custom", {})
		if not custom.get("enabled"):
			raise ValueError(
				"custom profile selected but custom.enabled is false in auth-profiles.yaml"
			)
		tuple_ = {k: custom[k] for k in _AXES}
	else:
		# A profile name may live in `profiles` (deployable) or `preview_profiles`
		# (roadmap; resolves + validates but its IaC isn't built — see stubbed_axes).
		profiles = {**cat.get("profiles", {}), **cat.get("preview_profiles", {})}
		if name not in profiles:
			raise KeyError(f"Unknown auth profile: {name!r}")
		tuple_ = profiles[name]

	axis_meta: dict[str, dict] = {}
	worst = 0
	for axis in _AXES:
		value = tuple_[axis]
		# mode is a list; grade it by its weakest member
		values = value if isinstance(value, list) else [value]
		for v in values:
			meta = cat["axes"][axis][v]
			worst = max(worst, MATURITY_ORDER[meta["maturity"]])
		# Store the (last) selected value's meta; for non-mode axes that's the single value
		axis_meta[axis] = cat["axes"][axis][values[-1]]

	maturity = next(k for k, rank in MATURITY_ORDER.items() if rank == worst)

	return ResolvedProfile(
		name=name,
		frontend=tuple_["frontend"],
		inbound=tuple_["inbound"],
		mode=tuple_["mode"] if isinstance(tuple_["mode"], list) else [tuple_["mode"]],
		outbound=tuple_["outbound"],
		maturity=maturity,
		axis_meta=axis_meta,
		verified=bool(tuple_.get("verified", False)),
	)


def _selected_values(profile: ResolvedProfile) -> dict[str, list[str]]:
	return {
		"frontend": [profile.frontend],
		"inbound": [profile.inbound],
		"mode": list(profile.mode),
		"outbound": [profile.outbound],
	}


def stubbed_axes(profile: ResolvedProfile, catalog: dict | None = None) -> list[str]:
	"""Axis names whose SELECTED value is status:stub (IaC module not yet built).

	status defaults to 'live' when absent. mode is a list -> flagged if ANY
	selected mode value is stub. Order: frontend, inbound, mode, outbound."""
	cat = catalog or load_catalog()
	selected = _selected_values(profile)
	stubs: list[str] = []
	for axis in _AXES:
		metas = (cat["axes"][axis][v] for v in selected[axis])
		if any(m.get("status", "live") == "stub" for m in metas):
			stubs.append(axis)
	return stubs


def stub_blockers(
	profile: ResolvedProfile, catalog: dict | None = None
) -> dict[str, str]:
	"""Map each stub axis to WHY it is stub: repo | operator | upstream.

	Without this, `stub_axes: [frontend, inbound]` reads as "unbuilt" for every
	axis, which misreports axes whose wiring exists and is only awaiting external
	config. Defaults to 'repo' (the strict reading) when blocked_by is absent, so
	an unannotated stub is never flattered."""
	cat = catalog or load_catalog()
	selected = _selected_values(profile)
	blockers: dict[str, str] = {}
	for axis in stubbed_axes(profile, cat):
		# mode is a list; a stub axis has >=1 stub member — report the first one's cause.
		for v in selected[axis]:
			meta = cat["axes"][axis][v]
			if meta.get("status", "live") == "stub":
				blockers[axis] = meta.get("blocked_by", "repo")
				break
	return blockers


_OBO = {"obo", "obo-okta"}
_USER_IDENTITY_OUTBOUND = {"user-federation", "obo", "obo-okta"}
_USER_IDENTITY_MODES = {"live", "batch"}


class ProfileValidationError(ValueError):
	"""Raised when a profile violates an auth constraint rule."""


def validate_profile(profile: ResolvedProfile, *, mcp_path: bool = False) -> None:
	"""Enforce the auth-profile constraint rules. Raises ProfileValidationError."""
	out_meta = profile.axis_meta["outbound"]

	if profile.outbound in _OBO:
		if profile.inbound == "cognito":
			raise ProfileValidationError(
				f"OBO outbound {profile.outbound!r} is illegal with Cognito inbound: "
				"a Cognito-issued JWT cannot be OBO token-exchanged (issuer mismatch)."
			)
		issuers = {
			profile.axis_meta["frontend"].get("issuer"),
			profile.axis_meta["inbound"].get("issuer"),
			out_meta.get("issuer"),
		}
		if len(issuers) != 1 or None in issuers:
			raise ProfileValidationError(
				f"OBO requires one issuer end-to-end; got frontend/inbound/outbound "
				f"issuers {issuers}."
			)

	# A user-identity outbound (UF/OBO) needs a mode where a user is/was present to
	# authorize. Autonomous-only profiles have no user -> cannot federate or
	# token-exchange. NOTE: the reverse is NOT enforced -- `live` MAY use Basic/M2M
	# (service identity, no per-user SAP propagation); that is legal, just not
	# identity-propagating. `batch` is the exception, constrained by the rule below.
	if profile.outbound in _USER_IDENTITY_OUTBOUND and not (
		_USER_IDENTITY_MODES & set(profile.mode)
	):
		raise ProfileValidationError(
			f"outbound {profile.outbound!r} propagates user identity and requires a "
			f"user-identity mode (live or batch); profile mode {profile.mode} has none."
		)

	# Refresh is required by acting as an ABSENT HUMAN, not by being unattended. A
	# service identity re-mints on demand (client_credentials), so batch over
	# basic/m2m needs no stored token. Only a user-identity outbound must survive the
	# session that authorized it, and OBO cannot: it is just-in-time and rejects an
	# exchange with no inbound token, leaving `user-federation` as the only
	# user-identity outbound that can.
	if (
		"batch" in profile.mode
		and profile.outbound in _USER_IDENTITY_OUTBOUND
		and not out_meta.get("supports_refresh")
	):
		raise ProfileValidationError(
			f"mode 'batch' with user-identity outbound {profile.outbound!r} requires "
			f"token refresh, which {profile.outbound!r} does not support (no stored "
			f"credential outlives the authorizing session)."
		)

	# mcp_supported: false blocks a Gateway-mediated SAP MCP target (the Gateway
	# cannot carry this flow). The direct-to-MCP OBO path (obo_direct_mcp: true)
	# deliberately bypasses the Gateway and dials the external MCP with the user's
	# JWT, so the Gateway restriction does not apply — exempt it, or an OBO profile
	# could never deploy with the SAP MCP path enabled.
	if (
		mcp_path
		and out_meta.get("mcp_supported", True) is False
		and not out_meta.get("obo_direct_mcp")
	):
		raise ProfileValidationError(
			f"outbound {profile.outbound!r} has mcp_supported: false — not usable on the "
			f"AWS-for-SAP MCP path (flow {out_meta.get('mcp_oauth_flow')})."
		)
