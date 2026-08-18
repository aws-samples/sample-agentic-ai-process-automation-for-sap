# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for agentcore/agent/utils/auth.py."""

import jwt as pyjwt
import pytest
from utils.auth import (
    _TRUSTED_IDENTITY_HEADER,
    extract_user_id_from_headers,
    is_user_bearer,
    is_user_bearer_token,
)


def _token(claims):
    return "Bearer " + pyjwt.encode(claims, key="x", algorithm="HS256")


def test_extract_user_id_from_headers_returns_subject():
    headers = {"Authorization": _token({"sub": "u1", "email": "a@b.com"})}
    assert extract_user_id_from_headers(headers) == "u1"


def test_missing_headers_raises():
    with pytest.raises(ValueError, match="Authorization"):
        extract_user_id_from_headers({})


def test_missing_sub_raises():
    headers = {"Authorization": _token({"email": "a@b.com"})}
    with pytest.raises(ValueError, match="sub"):
        extract_user_id_from_headers(headers)


def test_delegated_identity_header_returns_subject():
    # Guards the delegated-identity branch (only reachable on a Runtime that
    # allowlists this header) against InboundIdentity being constructed with a
    # kwarg the dataclass doesn't accept.
    headers = {_TRUSTED_IDENTITY_HEADER: "delegated-user"}
    assert extract_user_id_from_headers(headers) == "delegated-user"


# ── Token-type backstop ──────────────────────────────────────────────────────────
# The direct/OBO outbound topology exchanges the caller's bearer as the acting user.
# A queued run's bearer is the invoker's Cognito client_credentials token, so the
# guard must test token TYPE, not merely presence — the earlier presence-only check
# was inert because RUNTIME_EXECUTION_MODE was never set by any deployment.


def _raw(claims):
    return pyjwt.encode(claims, key="x", algorithm="HS256")


def test_cognito_client_credentials_token_is_not_a_user_bearer():
    # Cognito M2M: sub IS the app client id, and no user-identifying claim exists.
    assert (
        is_user_bearer(
            {
                "sub": "1ex4mpl3cl13nt1d",
                "client_id": "1ex4mpl3cl13nt1d",
                "token_use": "access",
                "scope": "erp/invoke",
            }
        )
        is False
    )


def test_cognito_user_token_is_a_user_bearer():
    assert (
        is_user_bearer(
            {
                "sub": "8a7b6c5d-1234-5678-9abc-def012345678",
                "client_id": "1ex4mpl3cl13nt1d",
                "cognito:username": "zach",
                "token_use": "access",
            }
        )
        is True
    )


def test_entra_app_token_is_not_a_user_bearer():
    # Entra client_credentials: idtyp app, and sub == appid.
    assert (
        is_user_bearer(
            {
                "sub": "sp-guid",
                "appid": "sp-guid",
                "idtyp": "app",
                "roles": ["Sap.Write"],
            }
        )
        is False
    )


def test_entra_user_token_is_a_user_bearer():
    assert (
        is_user_bearer(
            {
                "sub": "user-oid",
                "appid": "app-guid",
                "upn": "zach@example.com",
                "scp": "Sap.Read",
            }
        )
        is True
    )


def test_unknown_issuer_shape_fails_closed():
    # No user-identifying claim: treated as a service caller rather than waved through.
    assert is_user_bearer({"sub": "whoever", "iss": "https://unfamiliar"}) is False


def test_missing_sub_is_not_a_user_bearer():
    assert is_user_bearer({"email": "a@b.com"}) is False


def test_is_user_bearer_token_decodes_a_raw_bearer():
    assert is_user_bearer_token(_raw({"sub": "u", "email": "a@b.com"})) is True
    assert is_user_bearer_token(_raw({"sub": "c", "client_id": "c"})) is False


def test_is_user_bearer_token_rejects_unusable_input():
    # Malformed/opaque/absent tokens yield no evidence of a user, so they are refused.
    assert is_user_bearer_token("") is False
    assert is_user_bearer_token("   ") is False
    assert is_user_bearer_token("not-a-jwt") is False
