#!/usr/bin/env bash

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Re-point the local Okta MCP server at a new Okta org (device-auth mode).
#
# Two things make this more than `claude mcp add`, and both fail silently:
#
#   1. The cached token is a single global keyring entry ("OktaAuthManager"/
#      "api_token") that is NOT keyed by org, and auth_manager validates it on
#      `exp` alone — never on `iss`. An unexpired old-org token is therefore
#      reused against the new org, and every call 403s against a tenant you
#      think you replaced.
#   2. OKTA_PRIVATE_KEY + OKTA_KEY_ID being present forces browserless auth
#      (auth_manager.__init__). Overwriting only ORG_URL/CLIENT_ID leaves the
#      old org's key material selecting the wrong mode entirely.
#
# So: purge the token, re-register with NO key vars, then authenticate fresh.
#
# Usage:
#   test-scripts/rewire-okta-mcp.sh https://<new-org>.okta.com <mcp-app-client-id>

set -euo pipefail

MCP_DIR="${OKTA_MCP_DIR:-$HOME/dev/okta-mcp-server}"
# apps.manage is deliberate: it lets the MCP create the O2 web app rather than
# you clicking it. logs.read is how a SAP 401 gets traced in the Okta System Log.
SCOPES="${OKTA_SCOPES:-okta.users.read okta.groups.read okta.apps.read okta.apps.manage okta.logs.read}"

if [[ "${1:-}" == "--verify" ]]; then
	# The ONLY real proof that scopes were granted in the console. The device
	# authorize endpoint accepts any scope string (verified: it accepts
	# okta.brands.manage on an app that was never granted it), so grants are
	# enforced solely at token issuance — read them off the issued token's `scp`.
	"$MCP_DIR/.venv/bin/python" - "$SCOPES" <<'PY'
import base64, json, sys, time, keyring

tok = keyring.get_password("OktaAuthManager", "api_token")
if not tok:
	raise SystemExit("no cached token — restart Claude Code and use an Okta tool to authenticate")
b = tok.split(".")[1]
c = json.loads(base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)))
print(f"iss = {c.get('iss')}")
print(f"cid = {c.get('cid')}")
print(f"exp in {int(c.get('exp', 0) - time.time())}s")
got = set(c.get("scp", []))
missing = [s for s in sys.argv[1].split() if s not in got]
print(f"granted: {' '.join(sorted(got)) or '(none)'}")
if missing:
	raise SystemExit(
		f"\nNOT GRANTED: {', '.join(missing)}\n"
		"Admin → Applications → <app> → Okta API Scopes → Grant, then re-run the rewire\n"
		"(the token caches, so a fresh grant needs a fresh token). Tools needing these\n"
		"scopes are silently absent from tools/list until then."
	)
print("\nok: every configured scope is present in the token")
PY
	exit $?
fi

if [[ $# -ne 2 ]]; then
	echo "usage: $0 <org-url> <client-id>   # rewire" >&2
	echo "       $0 --verify                # check granted scopes on the cached token" >&2
	echo "  e.g. $0 https://your-org.okta.com 0oaAbC123" >&2
	exit 64
fi
ORG_URL="${1%/}"
CLIENT_ID="$2"

case "$ORG_URL" in
	https://*.okta.com | https://*.oktapreview.com) ;;
	*) echo "refusing: org URL must be https://<org>.okta[preview].com (got '$ORG_URL')" >&2; exit 64 ;;
esac
[[ -d "$MCP_DIR" ]] || { echo "no Okta MCP checkout at $MCP_DIR (set OKTA_MCP_DIR)" >&2; exit 66; }

echo "org:    $ORG_URL"
echo "client: $CLIENT_ID"
echo "scopes: $SCOPES"

# Purge FIRST. If the re-register succeeded and this failed, the next call would
# silently authenticate as the old org.
echo "→ purging cached token"
"$MCP_DIR/.venv/bin/python" - <<'PY'
import base64, json, keyring
try:
	tok = keyring.get_password("OktaAuthManager", "api_token")
except Exception as e:  # no backend / locked keychain
	raise SystemExit(f"could not read keyring: {e}")
if tok:
	try:
		b = tok.split(".")[1]
		iss = json.loads(base64.urlsafe_b64decode(b + "=" * (-len(b) % 4))).get("iss")
	except Exception:
		iss = "opaque"
	print(f"  removing cached token (iss={iss})")
else:
	print("  no cached token")
for k in ("api_token", "refresh_token"):
	try:
		keyring.delete_password("OktaAuthManager", k)
	except keyring.errors.PasswordDeleteError:
		pass
PY

echo "→ re-registering MCP server (device auth — no key material)"
# -s user on BOTH: `add` otherwise defaults to project scope, which would leave the
# old user-scope entry live everywhere else and bind the new one to one worktree.
claude mcp remove -s user okta 2>/dev/null || true
claude mcp remove okta 2>/dev/null || true
# No OKTA_PRIVATE_KEY / OKTA_KEY_ID: their presence would force browserless auth.
claude mcp add -s user okta \
	-e "OKTA_ORG_URL=$ORG_URL" \
	-e "OKTA_CLIENT_ID=$CLIENT_ID" \
	-e "OKTA_SCOPES=$SCOPES" \
	-- uv run --directory "$MCP_DIR" okta-mcp-server

echo "→ verifying no stale key material or duplicate entry survived"
python3 - "$ORG_URL" "$CLIENT_ID" <<'PY'
import json, pathlib, sys

want_org, want_cid = sys.argv[1], sys.argv[2]
cfg = json.loads((pathlib.Path.home() / ".claude.json").read_text())

# A project-scope leftover shadows the user entry in that directory only — the
# subtlest way to end up talking to two orgs depending on where you launched.
shadows = [p for p, v in cfg.get("projects", {}).items() if "okta" in v.get("mcpServers", {})]
if shadows:
	raise SystemExit("FAIL: project-scope 'okta' still set in:\n  " + "\n  ".join(shadows))

env = cfg.get("mcpServers", {}).get("okta", {}).get("env")
if env is None:
	raise SystemExit("FAIL: no user-scope 'okta' server registered")
stale = [k for k in ("OKTA_PRIVATE_KEY", "OKTA_KEY_ID") if env.get(k)]
if stale:
	raise SystemExit(f"FAIL: {', '.join(stale)} still set — would force browserless auth")
assert env.get("OKTA_ORG_URL") == want_org, f"FAIL: org is {env.get('OKTA_ORG_URL')!r}"
assert env.get("OKTA_CLIENT_ID") == want_cid, f"FAIL: client is {env.get('OKTA_CLIENT_ID')!r}"
print("  ok: user scope, device auth, new org, no key material, no shadows")
PY

cat <<EOF

Done. Restart Claude Code so it re-spawns the server, then ask it to list your
Okta applications — that triggers the device-auth prompt.

Then confirm the console grants actually took:

    $0 --verify

Do not infer grants from the device prompt succeeding: that endpoint accepts any
scope string, so only the issued token's \`scp\` claim is evidence. A scope you
listed but never granted yields no error — the tools needing it just vanish from
tools/list (Admin → Applications → <app> → Okta API Scopes → Grant).
EOF
