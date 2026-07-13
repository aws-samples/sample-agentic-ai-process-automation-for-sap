# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# This is sample code. Not for use in production.
# See NOTICE and LICENSE for more information.
"""
Authentication utilities for agent patterns.

Provides secure inbound identity extraction from JWT tokens in the AgentCore
Runtime RequestContext (prevents impersonation via prompt injection).
"""

import logging
import re
from dataclasses import dataclass, field

import jwt
from bedrock_agentcore.runtime import RequestContext

logger = logging.getLogger(__name__)

# AgentCore Memory actorId only accepts [a-zA-Z0-9-_/] (with optional `:` segments).
# Okta/Entra subjects are emails (user@example.com) whose `@`/`.` violate it, so any
# non-conforming char is collapsed to `_`. Cognito UUID subjects pass through unchanged.
_ACTOR_ID_DISALLOWED = re.compile(r"[^a-zA-Z0-9\-_/:]")


def to_memory_actor_id(subject: str) -> str:
    """Map an inbound subject to a Memory-safe actorId (deterministic, so the same
    user hits the same memory partition across turns)."""
    return _ACTOR_ID_DISALLOWED.sub("_", subject)


@dataclass
class InboundIdentity:
    """Normalized identity extracted from the validated inbound JWT."""

    subject: str
    email: str | None = None
    issuer: str | None = None
    claims: dict = field(default_factory=dict)


def _decode_claims(context: RequestContext) -> dict:
    request_headers = context.request_headers
    if not request_headers:
        raise ValueError(
            "No request headers found in context. "
            "Ensure the AgentCore Runtime is configured with a request header allowlist "
            "that includes the Authorization header."
        )

    auth_header = request_headers.get("Authorization")
    if not auth_header:
        raise ValueError(
            "No Authorization header found in request context. "
            "Ensure the AgentCore Runtime is configured with JWT inbound auth "
            "and the Authorization header is in the request header allowlist."
        )

    token = (
        auth_header.replace("Bearer ", "")
        if auth_header.startswith("Bearer ")
        else auth_header
    )

    # Decode without signature verification — AgentCore Runtime already validated the token
    # upstream. Re-verification here is unnecessary and would require fetching JWKS keys.
    return jwt.decode(  # nosec  # nosemgrep: unverified-jwt-decode — token pre-validated by AgentCore Runtime
        jwt=token,
        options={"verify_signature": False},  # noqa: S603
        algorithms=["RS256"],
    )


def get_inbound_identity(context: RequestContext) -> InboundIdentity:
    """
    Extract a normalized identity from the validated inbound JWT.

    Issuer-agnostic: reads ``sub`` as the subject, ``email`` when present (the
    join key for IAS/Okta federation), and ``iss`` as the issuer. Downstream
    code selects claims by these normalized fields rather than branching on IdP.
    """
    claims = _decode_claims(context)

    subject = claims.get("sub")
    if not subject:
        raise ValueError(
            "JWT token does not contain a 'sub' claim. Cannot determine user identity."
        )

    ident = InboundIdentity(
        subject=subject,
        email=claims.get("email"),
        issuer=claims.get("iss"),
        claims=claims,
    )
    logger.info("Inbound identity: subject=%s issuer=%s", ident.subject, ident.issuer)
    return ident


def extract_user_id_from_context(context: RequestContext) -> str:
    """Backwards-compatible wrapper returning the subject (``sub``) claim."""
    return get_inbound_identity(context).subject


if __name__ == "__main__":
    # ponytail: offline self-check for the Memory actorId sanitizer — the part that
    # silently 400s CreateEvent if it lets an illegal char through.
    assert to_memory_actor_id("user@example.com") == "user_example_com"
    assert to_memory_actor_id("11c8...-uuid-4XIj") == "11c8...-uuid-4XIj".replace(".", "_")
    _uuid = "8a7b6c5d-1234-5678-9abc-def012345678"
    assert to_memory_actor_id(_uuid) == _uuid  # Cognito UUID untouched
    assert not re.search(r"[^a-zA-Z0-9\-_/:]", to_memory_actor_id("user+tag@corp.example.com"))
    print("auth actorId self-check OK")
