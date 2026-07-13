# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for agentcore/agent/utils/auth.py."""

import jwt as pyjwt
import pytest
from utils.auth import extract_user_id_from_context, get_inbound_identity


class _Ctx:
    def __init__(self, headers):
        self.request_headers = headers


def _token(claims):
    return "Bearer " + pyjwt.encode(claims, key="x", algorithm="HS256")


def test_get_inbound_identity_extracts_sub_email_issuer():
    ctx = _Ctx(
        {
            "Authorization": _token(
                {"sub": "u1", "email": "a@b.com", "iss": "https://cognito"}
            )
        }
    )
    ident = get_inbound_identity(ctx)
    assert ident.subject == "u1"
    assert ident.email == "a@b.com"
    assert ident.issuer == "https://cognito"


def test_email_absent_is_none():
    ctx = _Ctx({"Authorization": _token({"sub": "u2", "iss": "x"})})
    assert get_inbound_identity(ctx).email is None


def test_wrapper_returns_subject():
    ctx = _Ctx({"Authorization": _token({"sub": "u3"})})
    assert extract_user_id_from_context(ctx) == "u3"


def test_missing_headers_raises():
    with pytest.raises(ValueError, match="request headers"):
        get_inbound_identity(_Ctx(None))


def test_missing_sub_raises():
    ctx = _Ctx({"Authorization": _token({"email": "a@b.com"})})
    with pytest.raises(ValueError, match="sub"):
        get_inbound_identity(ctx)
