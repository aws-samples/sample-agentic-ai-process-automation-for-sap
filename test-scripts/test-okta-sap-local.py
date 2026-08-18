#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Phase 1 smoke test: Okta login -> SAP OData directly (no AgentCore, no MCP).

Proves the Okta -> SOIDC -> SAP trust round-trip in isolation, exactly the
vendor guide's `test_sap_local.py` pattern, against your own SAP system. Once
this is green, the same SAP-side trust is what USER_FEDERATION reuses.

Flow:
  1. Local HTTP server on :8086 catches the OAuth callback.
  2. Browser opens Okta authorize (custom /oauth2/default server).
  3. Exchange the auth code for tokens (client_secret_basic).
  4. Decode + print the access_token claims (check iss / aud / cid).
  5. Call SAP OData directly with `Authorization: Bearer <access_token>`.

Secret handling: the client secret is read from OKTA_CLIENT_SECRET only
(never a file). Put it in a git-ignored .env and `set -a; . test-scripts/.env`.

Usage:
    export OKTA_CLIENT_SECRET=...            # or source test-scripts/.env
    uv run test-scripts/test-okta-sap-local.py
    uv run test-scripts/test-okta-sap-local.py --service API_SALES_ORDER_SRV --entity A_SalesOrder
    uv run test-scripts/test-okta-sap-local.py --self-check   # offline decode test, no network
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

# PKCE (S256) — reproduces the EXACT authorize+token exchange AgentCore's
# USER_FEDERATION 3LO performs (it always sends code_challenge=S256). Used to
# prove whether this Okta app completes a client_secret_basic + PKCE exchange.
_PKCE_VERIFIER: str | None = None


def _pkce_pair() -> tuple[str, str]:
    """Return (verifier, S256 challenge) per RFC 7636."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


# ── Config (non-secret; supplied via env — see .env.example) ────────────────
# No defaults for the tenant or the SAP host: a baked-in value would silently
# test somebody else's system instead of yours. Fail closed.
OKTA_ISSUER = os.environ.get("OKTA_ISSUER", "")
OKTA_CLIENT_ID = os.environ.get("OKTA_CLIENT_ID", "")
REDIRECT_URI = "http://localhost:8086/callback"  # MUST match the Okta app exactly
SCOPES = os.environ.get("OKTA_SCOPES", "openid email")
# Gotcha #2: SAP rejects any token whose `aud` lacks the SOIDC-configured client
# id. Set this to SAP's own client id to turn that into a loud failure instead of
# a 401 hunted down at the SAP end.
EXPECT_AUDIENCE = os.environ.get("OKTA_EXPECT_AUDIENCE", "")

SAP_BASE_URL = os.environ.get("SAP_BASE_URL", "")
SAP_CLIENT = os.environ.get("SAP_CLIENT", "100")


def _missing_env_msg(names: list[str]) -> str:
    return (
        f"Missing required env: {', '.join(names)}.\n"
        "Copy test-scripts/.env.example to test-scripts/.env, fill in your Okta\n"
        "and SAP values, then: set -a; . test-scripts/.env; set +a"
    )


def preflight(issuer: str) -> dict:
    """Check the issuer's discovery doc before opening a browser.

    Catches the two traps that historically cost hours, at the cheapest possible
    point. Both are IdP-side config, invisible until SAP or AgentCore 401s:

    1. Wrong authorization-server shape. Okta's org server and custom server emit
       DIFFERENT `iss` claims. `iss` must equal the configured issuer verbatim, or
       SAP (SOIDC) and AgentCore (discoveryUrl) both reject the token. A trailing
       slash or an org-server URL where a custom one is meant fails here.
    2. Audience. Okta's default `api://default` will NOT match SAP's SOIDC config,
       which requires SAP's own client id in `aud`. Only checkable post-token, but
       we surface the expectation now.

    Returns the discovery document so callers can reuse the real endpoints.
    """
    url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
    print(f"Preflight: {url}")
    try:
        resp = requests.get(url, timeout=20)
    except requests.exceptions.RequestException as e:
        sys.exit(
            f"  ✗ discovery unreachable: {e}\n    Check OKTA_ISSUER and the tenant is live."
        )
    if resp.status_code != 200:
        sys.exit(
            f"  ✗ discovery returned HTTP {resp.status_code}.\n"
            "    A 404 usually means the authorization-server id is wrong.\n"
            "    Org server:    https://<org>.okta.com\n"
            "    Custom server: https://<org>.okta.com/oauth2/<id>  (default: .../oauth2/default)"
        )
    doc = resp.json()

    declared = doc.get("issuer", "")
    if declared.rstrip("/") != issuer.rstrip("/"):
        sys.exit(
            f"  ✗ ISSUER MISMATCH — this is trap #1, fix it before going further.\n"
            f"      you configured: {issuer}\n"
            f"      Okta will emit: {declared}\n"
            "    SAP SOIDC and AgentCore both compare `iss` verbatim. Use the value\n"
            "    Okta emits, consistently, in all three places (Okta app, SOIDC, AgentCore)."
        )
    print(f"  ✓ issuer matches: {declared}")

    grants = doc.get("grant_types_supported", [])
    if "authorization_code" not in grants:
        sys.exit(f"  ✗ authorization_code not offered here. grant_types={grants}")
    print(f"  ✓ authorization_code supported ({len(grants)} grants offered)")
    if EXPECT_AUDIENCE:
        print(f"  · will assert aud contains: {EXPECT_AUDIENCE!r}")
    else:
        print(
            "  · OKTA_EXPECT_AUDIENCE unset — `aud` will be reported but not checked.\n"
            "    Set it to SAP's SOIDC client id to catch trap #2 automatically."
        )
    return doc


def b64url_decode_segment(seg: str) -> bytes:
    """Decode a base64url JWT segment, restoring the padding JWT strips."""
    return base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))


def decode_jwt_payload(token: str) -> dict:
    """Decode a JWT's claims WITHOUT verifying the signature (display only —
    SAP verifies the signature against JWKS). Raises on a malformed token."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError(f"not a JWT (expected 3 segments, got {len(parts)})")
    return json.loads(b64url_decode_segment(parts[1]))


class _CallbackHandler(BaseHTTPRequestHandler):
    """One-shot handler that captures ?code=... from Okta's redirect."""

    code: str | None = None
    error: str | None = None

    def do_GET(self):  # noqa: N802 (stdlib signature)
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        qs = urllib.parse.parse_qs(parsed.query)
        _CallbackHandler.code = qs.get("code", [None])[0]
        _CallbackHandler.error = qs.get("error_description", qs.get("error", [None]))[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        msg = (
            "Auth failed — check the terminal."
            if _CallbackHandler.error
            else "Auth OK — return to the terminal."
        )
        self.wfile.write(f"<html><body><h3>{msg}</h3></body></html>".encode())

    def log_message(self, *_):  # silence per-request stderr noise
        pass


def get_auth_code(pkce: bool = False) -> str:
    """Run the 3-legged browser login and return the authorization code."""
    global _PKCE_VERIFIER
    state = secrets.token_urlsafe(16)
    params = {
        "client_id": OKTA_CLIENT_ID,
        "response_type": "code",
        "scope": SCOPES,
        "redirect_uri": REDIRECT_URI,
        "state": state,
    }
    if pkce:
        _PKCE_VERIFIER, challenge = _pkce_pair()
        params["code_challenge"] = challenge
        params["code_challenge_method"] = "S256"
    authorize_url = f"{OKTA_ISSUER}/v1/authorize?{urllib.parse.urlencode(params)}"

    try:
        server = HTTPServer(("localhost", 8086), _CallbackHandler)
    except OSError as e:
        # A previous run that 400'd at authorize never got its callback and is
        # still listening. Without this, the bind error precedes the browser
        # open and you debug the stale tab instead.
        sys.exit(f"Port 8086 busy ({e}) — kill the earlier run: lsof -nP -iTCP:8086")
    print(f"Opening browser for Okta login…\n  {authorize_url}\n")
    webbrowser.open(authorize_url)

    # Serve requests until the callback populates code/error.
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        while _CallbackHandler.code is None and _CallbackHandler.error is None:
            threading.Event().wait(0.2)
    finally:
        server.shutdown()

    if _CallbackHandler.error:
        sys.exit(f"Okta returned an error: {_CallbackHandler.error}")
    return _CallbackHandler.code


def exchange_code(code: str, client_secret: str) -> dict:
    """Exchange the auth code for tokens using client_secret_basic."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }
    if _PKCE_VERIFIER:
        # Mirrors AgentCore's 3LO: client_secret_basic AND a PKCE code_verifier.
        data["code_verifier"] = _PKCE_VERIFIER
    resp = requests.post(
        f"{OKTA_ISSUER}/v1/token",
        auth=(OKTA_CLIENT_ID, client_secret),  # Basic auth = client_secret_basic
        data=data,
        headers={"Accept": "application/json"},
        timeout=30,
    )
    if resp.status_code != 200:
        sys.exit(f"Token exchange failed ({resp.status_code}): {resp.text}")
    return resp.json()


def call_sap(access_token: str, service: str, entity: str, top: int) -> None:
    """Call SAP OData directly with the Okta access_token as a Bearer token."""
    url = f"{SAP_BASE_URL}/sap/opu/odata/sap/{service}/{entity}"
    params = {"$top": str(top), "$format": "json", "sap-client": SAP_CLIENT}
    print(f"\nCalling SAP OData:\n  GET {url}?{urllib.parse.urlencode(params)}\n")
    try:
        # verify=True on purpose. If TLS fails against your SAP host, add its CA to
        # the trust store — do NOT disable verify.
        resp = requests.get(
            url,
            params=params,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
            timeout=60,
        )
    except requests.exceptions.SSLError as e:
        sys.exit(
            f"TLS error reaching SAP: {e}\nAdd SAP's CA to the trust store; do not disable verification."
        )

    _report_response("Bearer", resp)

    challenge = resp.headers.get("WWW-Authenticate", "")
    if resp.status_code == 401 and "bearer" not in challenge.lower():
        _probe_short_bearer(url, params)


def _probe_short_bearer(url: str, params: dict) -> None:
    """Ask whether the node carries OIDC Bearer Token at all, with a SHORT value.

    Needed because a real token's Basic-only challenge is ambiguous: past ~400
    bytes of Authorization value this system answers Basic regardless of the
    node's configured procedures (measured on S/4HANA 2023 / SAP_BASIS 7.58 —
    invariant to issuer, expiry, signature validity, and JWT-vs-opaque). A short
    value stays below
    that threshold, so the scheme it comes back with reflects the node."""
    resp = requests.get(
        url,
        params=params,
        headers={"Authorization": "Bearer probe", "Accept": "application/json"},
        timeout=60,
    )
    challenge = resp.headers.get("WWW-Authenticate", "")
    print(f"\n[short-bearer probe] HTTP {resp.status_code}\n  {challenge}")
    if "bearer" in challenge.lower():
        # Deliberately coarse: error_description is "malformed" both for junk and
        # for a well-formed token whose issuer has no SOIDC provider, so this
        # rules out S4 without subdividing what is left.
        print(
            "  → the node DOES carry OIDC Bearer Token, so S4 is not the fault. Left: S2\n"
            "    (provider missing / issuer / audience / trust) or S3 (mapping). Paste the\n"
            "    real token into SOIDC's validator (--print-token) to split those."
        )
    else:
        print(
            "  → Basic even for a short value: no OIDC procedure on this node. S4 —\n"
            "    custom logon-procedure list with OIDC Bearer Token first."
        )


def _report_response(label: str, resp: requests.Response) -> None:
    """Print status + the auth-relevant response headers + a body snippet.

    The response headers are the point: when SAP rejects at the ICF logon layer
    (before the Gateway), it returns an HTML 'Anmeldung fehlgeschlagen' page and
    NOTHING lands in /IWFND/ERROR_LOG. `WWW-Authenticate` is SAP telling you which
    auth scheme it actually accepts on this path — the single best on-the-wire clue."""
    print(f"\n[{label}] SAP responded: HTTP {resp.status_code}")
    for h in ("WWW-Authenticate", "www-authenticate", "sap-system", "server"):
        if h in resp.headers:
            print(f"  {h}: {resp.headers[h]}")
    if resp.status_code == 200:
        try:
            body = resp.json()
            results = body.get("d", {}).get("results", body.get("value", body))
            n = len(results) if isinstance(results, list) else "?"
            print(f"  ✓ SAP returned {n} record(s). Round-trip works.")
        except ValueError:
            print("  ✓ 200 but non-JSON body (still a success):")
            print(resp.text[:500])
    else:
        challenge = resp.headers.get("WWW-Authenticate", "")
        offers_bearer = "bearer" in challenge.lower()
        is_html = "<html" in resp.text[:200].lower()

        print("  ✗ Non-200. Diagnose by boundary:")
        if resp.status_code == 401 and challenge and not offers_bearer:
            # A Basic-only challenge does NOT prove the node lacks an OIDC
            # procedure. Measured on S/4HANA 2023: the scheme flips to Basic purely
            # on Authorization-header length, at ~400-500 bytes, invariant to
            # issuer/expiry/signature and to JWT-vs-opaque. Real Okta tokens are
            # 700-1000 chars, i.e. always past that boundary — so this branch
            # cannot distinguish "no Bearer procedure" from "Bearer procedure
            # rejected the token". Use the short-token probe below to tell them
            # apart.
            print(
                f"    → SAP offered only: {challenge}\n"
                "      NOT conclusive: on this system the challenge falls back to Basic for any\n"
                "      Authorization value past ~400 bytes, regardless of the node's procedures.\n"
                "      To test whether the node carries OIDC Bearer Token at all, re-probe with a\n"
                "      short dummy bearer value (<300 chars): a `Bearer` challenge means the\n"
                "      procedure is present and the real token was evaluated and rejected\n"
                "      (S2/S3 — trust or mapping); Basic again means S4, add Bearer to the node."
            )
        elif resp.status_code == 401 and is_html:
            print(
                "    401 + HTML 'Anmeldung fehlgeschlagen' → rejected at ICF logon BEFORE Gateway:\n"
                "      signature not verified (STRUST/JWKS, cmRc=20), trust inactive, no user\n"
                "      mapped, or OIDC Logon ordered ahead of OIDC Bearer Token on the node."
            )
        elif resp.status_code == 401:
            print(
                "    401 (JSON) → reached Gateway: SOIDC issuer/audience mismatch or user-mapping."
            )
        elif resp.status_code == 403:
            print(
                "    403 → user maps to SU01 but lacks the OData service authorization (S_SERVICE)."
            )
        elif resp.status_code == 404:
            print("    404 → wrong service/entity name, or SICF node inactive.")

        body_kind = "HTML logon page" if is_html else "body"
        print(f"\n  ({body_kind}, first 400 chars):\n{resp.text[:400]}")


def call_sap_basic(
    username: str, password: str, service: str, entity: str, top: int
) -> None:
    """Differential probe: call the SAME OData URL with Basic auth (idp_demo).

    Isolates the boundary — if Basic returns 200 but Bearer 401, the endpoint,
    service, and network are all fine and the problem is PURELY SOIDC token
    acceptance. If Basic also 401s, the issue is more fundamental (service/user/net)."""
    url = f"{SAP_BASE_URL}/sap/opu/odata/sap/{service}/{entity}"
    params = {"$top": str(top), "$format": "json", "sap-client": SAP_CLIENT}
    print(f"\nBasic-auth differential probe as {username!r}:\n  GET {url}")
    try:
        resp = requests.get(
            url,
            params=params,
            headers={"Accept": "application/json"},
            auth=(username, password),
            timeout=60,
        )
    except requests.exceptions.SSLError as e:
        sys.exit(
            f"TLS error reaching SAP: {e}\nAdd SAP's CA to the trust store; do not disable verification."
        )
    _report_response("Basic", resp)


def self_check() -> None:
    """Offline sanity check: JWT payload decode round-trips (no network)."""
    payload = {"iss": OKTA_ISSUER, "aud": "api://default", "cid": OKTA_CLIENT_ID}
    seg = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    fake_jwt = f"aaa.{seg}.bbb"
    decoded = decode_jwt_payload(fake_jwt)
    assert decoded == payload, decoded
    try:
        decode_jwt_payload("not.a")  # too few segments → must raise
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError on malformed token")
    # PKCE pair: challenge must be the base64url-S256 of the verifier, no padding.
    v, c = _pkce_pair()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert c == expected and "=" not in c, (v, c)

    # Audience matching must handle both shapes Okta emits, and must not treat a
    # substring as a match — `aud` is compared by whole value.
    def aud_ok(aud, expect):
        return expect in (aud if isinstance(aud, list) else [aud])

    assert aud_ok("0oaSAP", "0oaSAP")
    assert aud_ok(["api://default", "0oaSAP"], "0oaSAP")
    assert not aud_ok("api://default", "0oaSAP")
    assert not aud_ok(["0oaSAPextra"], "0oaSAP")

    # Issuer comparison is trailing-slash tolerant but otherwise exact.
    def iss_ok(a, b):
        return a.rstrip("/") == b.rstrip("/")

    assert iss_ok(
        "https://x.okta.com/oauth2/default/", "https://x.okta.com/oauth2/default"
    )
    assert not iss_ok("https://x.okta.com", "https://x.okta.com/oauth2/default")

    # The 401 branch turns on whether SAP's challenge offers Bearer, but the
    # answer is only meaningful for a SHORT credential: past ~400 bytes the
    # challenge falls back to Basic whatever the node carries, so the real
    # token's 401 is read together with the short-token probe.
    def bearer_offered(challenge):
        return "bearer" in challenge.lower()

    assert not bearer_offered(
        'Basic realm="SAP NetWeaver Application Server [SB2/100]"'
    )
    assert bearer_offered('Bearer realm="SB2"')
    assert bearer_offered('Basic realm="SB2", Bearer realm="SB2"')

    print("self-check OK")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--service", default="API_SALES_ORDER_SRV", help="OData service name"
    )
    parser.add_argument("--entity", default="A_SalesOrder", help="OData entity set")
    parser.add_argument("--top", type=int, default=2, help="$top row count")
    parser.add_argument(
        "--self-check", action="store_true", help="offline decode test, no network"
    )
    # On by default: Okta forces pkce_required on a web app even with
    # client_secret_basic, so a run without it 400s at authorize before the
    # browser ever opens. This also matches AgentCore's 3LO, which always sends
    # code_challenge=S256.
    parser.add_argument(
        "--no-pkce",
        dest="pkce",
        action="store_false",
        help="drop S256 PKCE from authorize+token. Only useful against an org that allows it — "
        "Okta apps with pkce_required 400 at authorize.",
    )
    parser.add_argument(
        "--print-token",
        action="store_true",
        help="print the raw access_token (paste into SOIDC validate)",
    )
    parser.add_argument(
        "--basic",
        action="store_true",
        help="ALSO probe the same URL with Basic auth (SAP_USERNAME/SAP_PASSWORD env) to isolate the boundary",
    )
    parser.add_argument(
        "--basic-only",
        action="store_true",
        help="ONLY do the Basic-auth probe (no Okta login) — quickest endpoint/service smoke test",
    )
    args = parser.parse_args()

    if args.self_check:
        self_check()
        return

    # Checked here rather than in the Okta-path list below, because --basic-only
    # skips that list and still calls SAP.
    if not SAP_BASE_URL:
        sys.exit(_missing_env_msg(["SAP_BASE_URL"]))

    if args.basic_only:
        _basic_probe(args)
        return

    client_secret = os.environ.get("OKTA_CLIENT_SECRET")
    missing = [
        name
        for name, val in (
            ("OKTA_ISSUER", OKTA_ISSUER),
            ("OKTA_CLIENT_ID", OKTA_CLIENT_ID),
            ("OKTA_CLIENT_SECRET", client_secret),
        )
        if not val
    ]
    if missing:
        sys.exit(_missing_env_msg(missing))

    print(
        f"Okta issuer: {OKTA_ISSUER}\nOkta client: {OKTA_CLIENT_ID}\nSAP:         {SAP_BASE_URL} (client {SAP_CLIENT})"
    )
    preflight(OKTA_ISSUER)

    code = get_auth_code(pkce=args.pkce)
    tokens = exchange_code(code, client_secret)

    access_token = tokens.get("access_token")
    if not access_token:
        sys.exit(f"No access_token in response: {json.dumps(tokens)[:500]}")

    claims = decode_jwt_payload(access_token)
    print("\n── access_token claims (verify these against SAP SOIDC + AgentCore) ──")
    for k in ("iss", "aud", "cid", "sub", "scp", "exp"):
        if k in claims:
            print(f"  {k:5} = {claims[k]}")
    print(f"\n  Expected iss = {OKTA_ISSUER}")
    print(
        f"  → set SAP SOIDC Audience = {claims.get('aud')!r}; AgentCore allowedClients = [{claims.get('cid')!r}]"
    )

    # Trap #2, asserted rather than eyeballed. `aud` may be a string or a list.
    if EXPECT_AUDIENCE:
        aud = claims.get("aud")
        aud_values = aud if isinstance(aud, list) else [aud]
        if EXPECT_AUDIENCE not in aud_values:
            sys.exit(
                f"\n  ✗ AUDIENCE MISMATCH — trap #2. SAP will 401 this token.\n"
                f"      aud in token: {aud!r}\n"
                f"      SAP expects:  {EXPECT_AUDIENCE!r}\n"
                "    Fix on the IdP, NOT on SAP: Okta Admin → Security → API →\n"
                "    your authorization server → Settings → Audience."
            )
        print(f"  ✓ aud contains the SAP-expected audience {EXPECT_AUDIENCE!r}")

    # Full claim dump: SOIDC user-mapping reads a SPECIFIC claim. If the mapping
    # mode is "E-Mail" it looks for an `email` claim; Okta puts the address in
    # `sub` and (unless a custom claim is added) emits NO `email` claim. Seeing
    # exactly what's present tells us which claim SOIDC must map on.
    print("\n── ALL claims (which one does SOIDC map the user from?) ──")
    for k in sorted(claims):
        print(f"  {k} = {claims[k]!r}")
    print(f"  email claim present: {'email' in claims}")

    if args.print_token:
        print("\n── raw access_token (paste into SOIDC → validate) ──")
        print(access_token)

    call_sap(access_token, args.service, args.entity, args.top)

    if args.basic:
        _basic_probe(args)


def _basic_probe(args) -> None:
    """Run the Basic-auth differential using SAP_USERNAME / SAP_PASSWORD env vars."""
    user = os.environ.get("SAP_USERNAME", "idp_demo")
    pw = os.environ.get("SAP_PASSWORD")
    if not pw:
        sys.exit(
            "Set SAP_PASSWORD (and optionally SAP_USERNAME, default idp_demo) for the Basic probe."
        )
    call_sap_basic(user, pw, args.service, args.entity, args.top)


if __name__ == "__main__":
    main()
