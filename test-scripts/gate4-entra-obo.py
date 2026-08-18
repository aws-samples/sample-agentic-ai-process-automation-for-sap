#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Gate 4 validation driver for the `entra-obo` auth profile.

Drives the direct-Entra / OBO topology end to end and prints per-check PASS/FAIL
for the `entra-obo` auth profile's validation checklist.

The human Entra token comes from the device-code grant on the SPA client, so the
inbound token is a genuine user token (not client_credentials) without needing a
browser redirect back to the deployed frontend.

Usage:
    python3 test-scripts/gate4-entra-obo.py                 # full run
    python3 test-scripts/gate4-entra-obo.py --negative-only  # skip the SAP round trip
"""

import argparse
import json
import os
import re
import subprocess  # nosec B404 - fixed argv, no shell
import sys
import time
import uuid
from base64 import urlsafe_b64encode

import jwt
import requests

TENANT = "68a36f8c-e7a3-4e4d-b33b-9069169654c2"
ISSUER = f"https://login.microsoftonline.com/{TENANT}/v2.0"
SPA_CLIENT_ID = "ae4bcea0-1f31-4cc3-b7c4-2caab0944eb2"
OBO_APP_ID = "6cf13814-815d-47ff-87dc-75e786f6aeaf"
SCOPE = f"openid profile email offline_access api://{OBO_APP_ID}/SAP.Access"
# A PO that exists in the target SAP system. An absent PO yields an empty result set,
# which the agent handles gracefully — so the turn would look like a pass while
# proving no read.
TEST_PO = os.environ.get("TEST_PO", "4500001940")
STACK_BASE = os.environ.get("STACK_BASE", "erp-obo-v1")
REGION = os.environ.get("AWS_REGION", "us-east-1")
TOKEN_CACHE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), ".gate4-token.json"
)

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))
    return ok


def aws(*args):
    out = subprocess.run(  # nosec B603 - fixed argv
        ["aws", *args, "--region", REGION, "--output", "json"],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout) if out.stdout.strip() else None


def jwt_claims(token):
    """Decode a JWT payload without verifying — inspection only, never for trust."""
    return jwt.decode(  # nosec  # nosemgrep: unverified-jwt-decode
        token, options={"verify_signature": False}
    )


def machine_token():
    """Mint a real Cognito client_credentials token from this stack, or None."""
    try:
        pool = aws(
            "ssm", "get-parameter", "--name", f"/{STACK_BASE}/cognito-user-pool-id"
        )["Parameter"]["Value"]
        client_id = aws(
            "ssm", "get-parameter", "--name", f"/{STACK_BASE}/machine_client_id"
        )["Parameter"]["Value"]
        domain = aws("cognito-idp", "describe-user-pool", "--user-pool-id", pool)[
            "UserPool"
        ]["Domain"]
        desc = aws(
            "cognito-idp",
            "describe-user-pool-client",
            "--user-pool-id",
            pool,
            "--client-id",
            client_id,
        )["UserPoolClient"]
        r = requests.post(
            f"https://{domain}.auth.{REGION}.amazoncognito.com/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "scope": " ".join(desc.get("AllowedOAuthScopes", [])),
            },
            auth=(client_id, desc["ClientSecret"]),
            timeout=30,
        )
        return r.json().get("access_token")
    except (subprocess.CalledProcessError, KeyError, requests.RequestException):
        return None


def forged_entra_token():
    """A token with the trusted issuer + audience but a signature that cannot verify.

    This is the probe that proves signature verification actually runs. A bad-issuer
    token short-circuits on the claim check and never reaches crypto, so it cannot
    demonstrate that the authorizer verifies anything.
    """

    def seg(obj):
        raw = json.dumps(obj, separators=(",", ":")).encode()
        return urlsafe_b64encode(raw).rstrip(b"=").decode()

    now = int(time.time())
    head = seg({"alg": "RS256", "typ": "JWT", "kid": "forged"})
    body = seg(
        {
            "iss": ISSUER,
            "aud": OBO_APP_ID,
            "sub": "forged-subject",
            "exp": now + 3600,
            "iat": now,
            "scp": "SAP.Access",
        }
    )
    sig = urlsafe_b64encode(bytes(256)).rstrip(b"=").decode()
    return f"{head}.{body}.{sig}"


def device_code_login():
    """Interactive human login, cached so a retry does not re-prompt.

    The cache holds a live bearer token: mode 0600, gitignored dir, deleted by
    --fresh-login. Never commit or paste its contents.
    """
    if os.path.exists(TOKEN_CACHE):
        with open(TOKEN_CACHE) as f:
            cached = json.load(f)
        claims = jwt_claims(cached["access_token"])
        if claims.get("exp", 0) - 120 > time.time():
            print(f"(reusing cached token for {claims.get('preferred_username')})")
            return cached

    r = requests.post(
        f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/devicecode",
        data={"client_id": SPA_CLIENT_ID, "scope": SCOPE},
        timeout=30,
    )
    r.raise_for_status()
    d = r.json()
    print(f"\n>>> {d['message']}\n")
    deadline = time.time() + d["expires_in"]
    while time.time() < deadline:
        time.sleep(d["interval"])
        t = requests.post(
            f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": SPA_CLIENT_ID,
                "device_code": d["device_code"],
            },
            timeout=30,
        ).json()
        if "access_token" in t:
            with open(TOKEN_CACHE, "w") as f:
                f.write(json.dumps(t))
            os.chmod(TOKEN_CACHE, 0o600)
            return t
        if t.get("error") != "authorization_pending":
            raise RuntimeError(f"device flow failed: {t.get('error')}")
    raise TimeoutError("device code expired")


def runtime_url():
    arn = aws(
        "cloudformation", "describe-stacks", "--stack-name", f"{STACK_BASE}-backend"
    )["Stacks"][0]
    outs = {o["OutputKey"]: o["OutputValue"] for o in arn.get("Outputs", [])}
    for k, v in outs.items():
        if "arn:aws:bedrock-agentcore" in v and "runtime/" in v:
            escaped = requests.utils.quote(v, safe="")
            return (
                f"https://bedrock-agentcore.{REGION}.amazonaws.com"
                f"/runtimes/{escaped}/invocations?qualifier=DEFAULT"
            ), v
    raise SystemExit(f"no runtime ARN in {STACK_BASE}-backend outputs: {list(outs)}")


def agui_input(prompt, session_id):
    """A RunAgentInput matching frontend/src/services/agentRuntimeService.ts."""
    run_id = f"run-{session_id}"
    return {
        "threadId": session_id,
        "runId": run_id,
        "state": None,
        "messages": [{"id": f"input-{run_id}", "role": "user", "content": prompt}],
        "tools": [],
        "context": [],
        # No process_type: chat mode, so the turn exercises SAP tools directly
        # rather than a skill's SOP.
        "forwardedProps": {
            "erpPayload": {
                "prompt": prompt,
                "case_id": "",
                "trigger": "ui",
                "run_id": run_id,
                "thread_id": session_id,
            }
        },
    }


def stream(url, token, prompt, session_id):
    """POST one AG-UI turn; return (status, events, raw_text).

    token=None omits the Authorization header entirely. That is a different case from
    an empty value: a missing header is refused at the claim stage, an empty one is
    refused as unparseable.
    """
    headers = {
        "Content-Type": "application/json",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
    }
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.post(
        url,
        headers=headers,
        json=agui_input(prompt, session_id),
        stream=True,
        timeout=300,
    )
    if r.status_code != 200:
        return r.status_code, [], r.text[:400]
    events, raw = [], []
    for line in r.iter_lines(decode_unicode=True):
        raw.append(line or "")
        if line and line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return 200, events, "\n".join(raw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--negative-only", action="store_true")
    ap.add_argument(
        "--fresh-login", action="store_true", help="discard the cached token"
    )
    args = ap.parse_args()

    if args.fresh_login and os.path.exists(TOKEN_CACHE):
        os.remove(TOKEN_CACHE)

    url, arn = runtime_url()
    print(f"Runtime: {arn}\n")

    # ── Negative cases first: they need no human token. ───────────────────────
    # The authorizer checks the `iss`/`exp` claims lexically BEFORE verifying the
    # signature, so the status code says which stage refused the token:
    #   401 — no Authorization header, or a claim check failed (crypto never ran)
    #   403 — header present but unparseable, or iss+aud matched and the signature
    #         then failed verification
    # Only the 403-on-forged-signature case proves verification actually happens; a
    # wrong-issuer 401 short-circuits and demonstrates nothing about crypto.
    print("Negative cases (fail-closed):")
    sid = f"gate4neg{uuid.uuid4().hex}"[:40]
    st, _, _ = stream(url, None, "hello", sid)
    check("no Authorization header → 401 (claim stage)", st == 401, f"HTTP {st}")
    st, _, _ = stream(url, "", "hello", sid)
    check("empty bearer value → 403 (unparseable)", st == 403, f"HTTP {st}")
    st, _, _ = stream(url, "not-a-jwt", "hello", sid)
    check("garbage token → 403 (unparseable)", st == 403, f"HTTP {st}")

    # A structurally valid Cognito machine token must still be refused: the Runtime
    # authorizer trusts only the Entra issuer, and the in-agent bearer guard refuses a
    # client_credentials token before MCP construction. Presence alone is not identity.
    machine = machine_token()
    if machine:
        st, _, _ = stream(url, machine, "hello", sid)
        check(
            "rejects a Cognito machine token on issuer → 401", st == 401, f"HTTP {st}"
        )
        mc = jwt_claims(machine)
        check(
            "the machine token really is client_credentials",
            mc.get("token_use") == "access" and "scope" in mc and "sub" in mc,
            f"token_use={mc.get('token_use')} scope={mc.get('scope')}",
        )
    else:
        print("  SKIP  cross-IdP machine-token check — could not mint a Cognito token")

    # The load-bearing probe: trusted issuer and allowed audience, unverifiable
    # signature. A 403 here means the authorizer reached and failed crypto — the only
    # evidence that a caller cannot mint its own claims.
    st, _, _ = stream(url, forged_entra_token(), "hello", sid)
    check("trusted iss+aud with a forged signature → 403", st == 403, f"HTTP {st}")

    if args.negative_only:
        return summarize()

    # ── Positive path with a genuine human Entra token. ───────────────────────
    tok = device_code_login()
    claims = jwt_claims(tok["access_token"])
    human = claims.get("preferred_username") or claims.get("upn") or claims.get("email")
    print("Inbound token (positive path):")
    check(
        "aud is the OBO exchange app",
        claims.get("aud") in (OBO_APP_ID, f"api://{OBO_APP_ID}"),
        f"aud={claims.get('aud')}",
    )
    check(
        "issuer is the expected Entra tenant",
        TENANT in claims.get("iss", ""),
        f"iss={claims.get('iss')}",
    )
    check(
        "carries the SAP scope",
        "SAP.Access" in claims.get("scp", ""),
        claims.get("scp", ""),
    )
    check("identifies a human subject", bool(human), f"user={human}")
    check(
        "is a delegated (not app-only) token",
        "idtyp" not in claims or claims.get("idtyp") != "app",
        f"idtyp={claims.get('idtyp', 'absent')}",
    )

    print("\nInteractive AG-UI turn:")
    sid = f"gate4{uuid.uuid4().hex}"[:40]
    t0 = time.time()
    st, events, raw = stream(
        url,
        tok["access_token"],
        f"Read purchase order {TEST_PO} from SAP and tell me its vendor and net value.",
        sid,
    )
    check("Runtime accepts the human Entra token", st == 200, f"HTTP {st}")
    if st != 200:
        print(f"    body: {raw}")
        return summarize()

    types = [e.get("type") for e in events]
    check(
        "stream opens with RUN_STARTED",
        types and types[0] == "RUN_STARTED",
        types[0] if types else "none",
    )
    terminal = [t for t in types if t in ("RUN_FINISHED", "RUN_ERROR")]
    check("exactly one terminal event", len(terminal) == 1, f"{terminal}")
    check("terminal event is RUN_FINISHED", terminal == ["RUN_FINISHED"], f"{terminal}")

    tools = sorted({e.get("toolCallName") for e in events if e.get("toolCallName")})
    check("called at least one SAP MCP tool", bool(tools), f"tools={tools}")

    text = "".join(
        e.get("delta", "") for e in events if e.get("type") == "TEXT_MESSAGE_CONTENT"
    )
    # A tool call that returns nothing still streams a tidy answer. Require the target
    # PO in the reply so an empty result set cannot pass as a successful read.
    check(
        f"the answer actually reports PO {TEST_PO}",
        TEST_PO in text,
        ""
        if TEST_PO in text
        else "PO absent from answer — read may have returned 0 rows",
    )
    print(f"\n  --- agent answer ({time.time() - t0:.0f}s, {len(events)} events) ---")
    print("  " + (text[:1200].replace("\n", "\n  ") or "(empty)"))

    # ── Token leakage: the stream must not echo bearer material. ──────────────
    print("\nToken hygiene:")
    leaked = []
    for needle, label in [
        (tok["access_token"][:40], "inbound access token"),
        (tok.get("refresh_token", "\0")[:40], "refresh token"),
    ]:
        if needle and needle != "\0" and needle in raw:
            leaked.append(label)
    check("no bearer material in the response stream", not leaked, f"leaked={leaked}")
    check(
        "no runtime ARN echoed to the client",
        arn not in raw,
        "ARN present in stream" if arn in raw else "",
    )
    for pat, label in [
        (r"sap-?password|SAP_PASSWORD", "SAP password"),
        (r"AKIA[0-9A-Z]{16}", "AWS access key id"),
    ]:
        check(f"no {label} in stream", not re.search(pat, raw), "")

    print(f"\n  session id (for CloudWatch / SM20 correlation): {sid}")
    print(f"  human identity to expect in SAP audit log: {human}")
    return summarize()


def summarize():
    print("\n" + "=" * 60)
    failed = [n for n, ok, _ in results if not ok]
    print(f"{len(results) - len(failed)}/{len(results)} checks passed")
    for n in failed:
        print(f"  FAILED: {n}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
