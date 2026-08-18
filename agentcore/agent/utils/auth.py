# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# This is sample code. Not for use in production.
# See NOTICE and LICENSE for more information.
"""Authentication utilities for AgentCore Runtime requests."""

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass

import jwt

logger = logging.getLogger(__name__)

# AgentCore Memory actorId only accepts [a-zA-Z0-9-_/] (with optional `:` segments).
# Okta/Entra subjects are emails (user@example.com) whose `@`/`.` violate it, so any
# non-conforming char is collapsed to `_`. Cognito UUID subjects pass through unchanged.
_ACTOR_ID_DISALLOWED = re.compile(r"[^a-zA-Z0-9\-_/:]")
_TRUSTED_IDENTITY_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Custom-User-Identity"
_MAX_IDENTITY_LENGTH = 256

# Claims that positively identify a human subject. A client_credentials token carries
# none of them: Cognito M2M access tokens hold only sub/scope/client_id, and Entra app
# tokens hold appid/roles without upn or preferred_username.
_USER_IDENTITY_CLAIMS = (
    "cognito:username",
    "username",
    "preferred_username",
    "upn",
    "email",
)


def to_memory_actor_id(subject: str) -> str:
    """Map an inbound subject to a deterministic Memory-safe actorId."""
    return _ACTOR_ID_DISALLOWED.sub("_", subject)


@dataclass
class InboundIdentity:
    """Normalized identity extracted from trusted Runtime request metadata."""

    subject: str


def _get_header(headers: Mapping[str, str], name: str) -> str | None:
    """Read a header from plain dictionaries or Starlette's case-insensitive Headers."""
    direct = headers.get(name) or headers.get(name.lower()) or headers.get(name.title())
    if direct is not None:
        return direct
    lowered = name.lower()
    return next((value for key, value in headers.items() if key.lower() == lowered), None)


def _decode_claims_from_headers(headers: Mapping[str, str]) -> dict:
    auth_header = _get_header(headers, "Authorization")
    if not auth_header:
        raise ValueError(
            "No Authorization header found in request context. Ensure the AgentCore "
            "Runtime uses JWT inbound auth and allows the Authorization header."
        )

    token = auth_header[7:] if auth_header.lower().startswith("bearer ") else auth_header
    return decode_unverified_claims(token)


def decode_unverified_claims(token: str) -> dict:
    """Read the claims of a Runtime-validated bearer without re-verifying it.

    AgentCore Runtime has already validated this token. Re-verification here would
    require a second JWKS lookup and does not strengthen the Runtime trust boundary.
    """
    return jwt.decode(  # nosec  # nosemgrep: unverified-jwt-decode
        jwt=token,
        options={"verify_signature": False},
        algorithms=["RS256"],
    )


def is_user_bearer(claims: Mapping[str, object]) -> bool:
    """True when the claims positively identify a HUMAN subject.

    Deliberately fail-closed: this asks for evidence that a user is present rather
    than trying to recognise every machine-token shape, so a token from an unfamiliar
    issuer is treated as a service caller instead of being waved through.

    Two independent signals, both required:

    * ``sub`` must differ from the client/app identifier. A Cognito
      ``client_credentials`` token sets ``sub`` == ``client_id`` and an Entra app token
      sets ``sub`` == ``appid``/``azp``; an equal pair means the subject IS the
      application. Entra v2 app tokens also carry ``idtyp: "app"``.
    * at least one user-identifying claim must be present. A Cognito M2M access token
      carries only ``sub``/``scope``/``client_id`` and none of these.

    This is a BACKSTOP, not the primary control. The authoritative statement of whether
    an unattended path exists is the mode axis in auth-profiles.yaml, enforced at synth.
    This defends against a deployment drifting from its declared profile; it is not a
    substitute for that declaration.
    """
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        return False
    for holder_claim in ("client_id", "appid", "azp"):
        holder = claims.get(holder_claim)
        if isinstance(holder, str) and holder and holder == subject:
            return False
    if str(claims.get("idtyp") or "").lower() == "app":
        return False
    return any(claims.get(claim) for claim in _USER_IDENTITY_CLAIMS)


def is_user_bearer_token(token: str) -> bool:
    """``is_user_bearer`` over a raw bearer string; False if it cannot be decoded."""
    if not token or not token.strip():
        return False
    try:
        claims = decode_unverified_claims(token.strip())
    except Exception:  # malformed/opaque token — no evidence of a user
        return False
    return is_user_bearer(claims)


def _identity_from_claims(claims: dict) -> InboundIdentity:
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise ValueError(
            "JWT token does not contain a non-empty 'sub' claim. Cannot determine identity."
        )
    return InboundIdentity(subject=subject)


def get_inbound_identity_from_headers(
    headers: Mapping[str, str],
) -> InboundIdentity:
    """Resolve the acting identity from Runtime-validated request headers.

    The delegated identity header is an unauthenticated assertion of the acting
    subject. It is trusted here for one reason only: it is absent from the Runtime's
    ``requestHeaderConfiguration`` allowlist, so AgentCore strips it before the
    container ever sees it, and every caller therefore resolves to the subject of
    its own Runtime-validated JWT.

    That allowlist is the entire boundary. This deployment runs a SINGLE Runtime
    whose authorizer accepts both the browser user-pool client and the machine
    client, so allowlisting this header would let any authenticated browser caller
    assert an arbitrary subject — spoofing the audit initiator, the persisted trace,
    and the Memory ``actorId`` partition that separates users. Only allowlist it on
    a Runtime whose authorizer is restricted to the machine client.
    """
    delegated_subject = _get_header(headers, _TRUSTED_IDENTITY_HEADER)
    if delegated_subject is not None:
        delegated_subject = delegated_subject.strip()
        has_control_character = any(
            ord(character) < 32 or ord(character) == 127
            for character in delegated_subject
        )
        if (
            not delegated_subject
            or len(delegated_subject) > _MAX_IDENTITY_LENGTH
            or has_control_character
        ):
            raise ValueError("The trusted user identity header is invalid.")
        identity = InboundIdentity(subject=delegated_subject)
    else:
        identity = _identity_from_claims(_decode_claims_from_headers(headers))

    logger.info("Inbound identity: subject=%s", identity.subject)
    return identity


def extract_user_id_from_headers(headers: Mapping[str, str]) -> str:
    """Return the acting subject from FastAPI/ASGI request headers."""
    return get_inbound_identity_from_headers(headers).subject


if __name__ == "__main__":
    assert to_memory_actor_id("user@example.com") == "user_example_com"
    assert to_memory_actor_id("11c8...-uuid-4XIj") == "11c8___-uuid-4XIj"
    _uuid = "8a7b6c5d-1234-5678-9abc-def012345678"
    assert to_memory_actor_id(_uuid) == _uuid
    assert not re.search(
        r"[^a-zA-Z0-9\-_/:]", to_memory_actor_id("user+tag@corp.example.com")
    )
    print("auth actorId self-check OK")
