# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""The guard standing between a service token and SAP on the direct/OBO topology.

The direct topology promotes the caller's bearer to the PRIMARY Authorization header
on the external MCP server, so that bearer must belong to the acting human. On the
queued path it is the invoker's Cognito client_credentials token.

The predecessor of this guard tested token PRESENCE and keyed off
RUNTIME_EXECUTION_MODE, an env var no deployment ever set — so it could never fire and
a queued run would have sailed into OBO with a machine token. These tests pin the
replacement: token TYPE, using the real `is_user_bearer_token` predicate.

`_assert_direct_topology_bearer` is lifted out of basic_agent.py, which pulls in
strands/mcp and is not importable in the hermetic test environment (same approach as
test_stream_keepalive.py).
"""

import ast
import pathlib

import pytest
from utils.auth import is_user_bearer_token

_AGENT = (
    pathlib.Path(__file__).resolve().parents[2]
    / "agentcore"
    / "agent"
    / "basic_agent.py"
)


def _load_guard():
    """Exec just the guard from basic_agent.py, with the real predicate injected."""
    tree = ast.parse(_AGENT.read_text())
    wanted = "_assert_direct_topology_bearer"
    kept = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == wanted
    ]
    assert kept, f"{wanted} missing from basic_agent.py"
    namespace: dict = {"is_user_bearer_token": is_user_bearer_token}
    exec(  # nosec B102 - trusted source (this repo's own basic_agent.py), test-only
        compile(ast.Module(body=kept, type_ignores=[]), str(_AGENT), "exec"), namespace
    )
    return namespace[wanted]


_assert_direct_topology_bearer = _load_guard()


def _token(claims):
    import jwt as pyjwt

    return pyjwt.encode(
        claims, key="unit-test-signing-key-not-verified", algorithm="HS256"
    )


_MACHINE = {
    "sub": "1ex4mpl3cl13nt1d",
    "client_id": "1ex4mpl3cl13nt1d",
    "scope": "erp/invoke",
}
_USER = {
    "sub": "8a7b6c5d-1234-5678-9abc-def012345678",
    "client_id": "1ex4mpl3cl13nt1d",
    "cognito:username": "zach",
}


def test_cognito_client_credentials_bearer_is_refused():
    # The queued path's bearer. This is the case the old presence-only guard let through.
    with pytest.raises(ValueError, match="client_credentials"):
        _assert_direct_topology_bearer(_token(_MACHINE))


def test_entra_app_bearer_is_refused():
    with pytest.raises(ValueError, match="interactive user token"):
        _assert_direct_topology_bearer(
            _token({"sub": "sp-guid", "appid": "sp-guid", "idtyp": "app"})
        )


def test_user_bearer_is_allowed():
    assert _assert_direct_topology_bearer(_token(_USER)) is None


def test_absent_bearer_is_refused():
    with pytest.raises(ValueError, match="interactive user token"):
        _assert_direct_topology_bearer(None)
    with pytest.raises(ValueError, match="interactive user token"):
        _assert_direct_topology_bearer("")


def test_unreadable_bearer_is_refused():
    # Opaque/malformed tokens carry no evidence of a user, so they fail closed rather
    # than being treated as a user token because they are merely non-empty.
    with pytest.raises(ValueError, match="interactive user token"):
        _assert_direct_topology_bearer("not-a-jwt")
