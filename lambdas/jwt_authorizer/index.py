# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Generic OIDC JWT authorizer for the REST API (API Gateway TOKEN authorizer).

Issuer-agnostic: validates any external OIDC access token (Okta / Entra /
custom-oidc) against the issuer's JWKS. Used only for non-Cognito auth profiles;
cognito-* profiles keep the native COGNITO_USER_POOLS authorizer (see
backend-stack.ts). The switch is driven by the resolved auth profile, so adding a
new OIDC IdP needs no code change here — just its discovery_url + allowed_clients.

Env:
  DISCOVERY_URL    - issuer's .well-known/openid-configuration
  ALLOWED_CLIENTS  - CSV of accepted client IDs (matched against `aud` OR `cid`/`azp`)

Returns an IAM allow policy on success (deny/401 otherwise). The verified claims
are passed downstream in the authorizer context so lambdas + the enqueue VTL read
the caller identity the same way they did under Cognito.
"""

from __future__ import annotations

import json
import os
import urllib.request
from functools import lru_cache

import jwt
from jwt import PyJWKClient

# Tolerant read so the offline __main__ self-check can import the module. An unset
# URL fails naturally at first fetch (urlopen → deny); CDK always sets it in prod.
DISCOVERY_URL = os.environ.get("DISCOVERY_URL", "")
ALLOWED_CLIENTS = [c for c in os.environ.get("ALLOWED_CLIENTS", "").split(",") if c]


@lru_cache(maxsize=1)
def _oidc_metadata() -> dict:
    """Fetch + cache the issuer's OIDC metadata (jwks_uri, issuer). Cached for the
    life of the warm container — JWKS rotation is handled by PyJWKClient below."""
    with urllib.request.urlopen(DISCOVERY_URL, timeout=5) as resp:  # nosec B310 — trusted config URL  # nosemgrep: dynamic-urllib-use-detected
        return json.loads(resp.read())


@lru_cache(maxsize=1)
def _jwk_client() -> PyJWKClient:
    return PyJWKClient(_oidc_metadata()["jwks_uri"])


def _client_allowed(claims: dict, allowed: list[str]) -> bool:
    """True if the token names an allowed client. OIDC access tokens vary: some
    carry the client ID in `aud`, others in `cid`/`azp`/`client_id` — a match in
    any of them counts."""
    presented = set()
    aud = claims.get("aud")
    presented.update(aud if isinstance(aud, list) else [aud] if aud else [])
    for k in ("cid", "azp", "client_id"):
        if claims.get(k):
            presented.add(claims[k])
    return bool(presented.intersection(allowed))


def _verify(token: str) -> dict:
    """Verify signature (RS256 via JWKS), issuer, and expiry, then pin the client
    (aud/cid/azp) to ALLOWED_CLIENTS."""
    # Fail closed: an external issuer with no pinned clients would accept ANY
    # validly-signed token in the tenant. The emitter guarantees a non-empty list,
    # but the trust boundary must defend itself against a misconfigured deploy.
    if not ALLOWED_CLIENTS:
        raise jwt.InvalidTokenError("ALLOWED_CLIENTS empty — refusing to validate open")
    meta = _oidc_metadata()
    signing_key = _jwk_client().get_signing_key_from_jwt(token).key
    claims = jwt.decode(
        token,
        signing_key,
        algorithms=["RS256"],
        issuer=meta["issuer"],
        options={"verify_aud": False, "require": ["exp", "iss"]},
    )
    if not _client_allowed(claims, ALLOWED_CLIENTS):
        raise jwt.InvalidTokenError("no allowed client in token")
    return claims


def _policy(
    principal: str, effect: str, resource: str, context: dict | None = None
) -> dict:
    doc = {
        "principalId": principal,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {"Action": "execute-api:Invoke", "Effect": effect, "Resource": resource}
            ],
        },
    }
    if context:
        doc["context"] = context
    return doc


def handler(event: dict, _context) -> dict:
    """API Gateway TOKEN authorizer. `event.authorizationToken` is the raw
    `Authorization` header value ("Bearer <jwt>")."""
    token = event.get("authorizationToken", "")
    if token.startswith("Bearer "):
        token = token[7:]

    # Wildcard the resource so the cached policy applies to every method on the
    # API (API Gateway caches by token; a method-specific ARN would 403 sibling
    # routes on a cache hit).
    method_arn = event.get("methodArn", "*")
    api_arn = (
        method_arn.rsplit("/", 3)[0] + "/*/*" if method_arn.count("/") >= 3 else "*"
    )

    try:
        claims = _verify(token)
    except Exception as e:  # noqa: BLE001 — any failure = deny
        print(f"JWT authorizer deny: {type(e).__name__}: {e}")
        # Raising "Unauthorized" makes API Gateway return 401 (vs 403 for a Deny).
        raise Exception("Unauthorized")  # noqa: TRY002

    user = claims.get("sub") or claims.get("email") or "unknown"
    # Context values must be strings; expose the same identity fields the Cognito
    # authorizer put under `claims.*` so downstream readers are unchanged.
    context = {
        "sub": str(claims.get("sub", "")),
        "email": str(claims.get("email", "")),
        "preferred_username": str(
            claims.get("preferred_username", claims.get("sub", ""))
        ),
        "cognito:username": str(
            claims.get("preferred_username", claims.get("sub", ""))
        ),
        "iss": str(claims.get("iss", "")),
    }
    return _policy(user, "Allow", api_arn, context)


if __name__ == "__main__":
    # Offline self-check — no network, no real JWT. Exercises _client_allowed
    # (the part most likely to silently wave through a bad token or lock out a
    # good one) and the policy shape.
    _allowed = ["client-A"]
    assert _client_allowed({"aud": "client-A"}, _allowed)  # aud match
    assert _client_allowed({"aud": ["x", "client-A"]}, _allowed)  # aud list match
    assert _client_allowed({"aud": "api://default", "cid": "client-A"}, _allowed)  # cid
    assert not _client_allowed({"aud": "wrong", "cid": "wrong"}, _allowed)  # reject
    assert not _client_allowed({}, _allowed)  # no client claim → reject

    p = _policy("u", "Allow", "arn:*", {"sub": "u"})
    assert p["policyDocument"]["Statement"][0]["Effect"] == "Allow"
    assert p["context"]["sub"] == "u"
    print("jwt_authorizer self-check OK")
