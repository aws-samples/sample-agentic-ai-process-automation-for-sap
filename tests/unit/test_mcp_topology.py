# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for utils/mcp_topology.py — OBO direct-MCP topology selection + headers."""

from utils.mcp_topology import build_direct_mcp_headers, resolve_outbound_topology


def test_obo_token_exchange_flow_selects_direct():
    # resolve_outbound_topology keys on the mcp_oauth_flow token, not the profile's
    # axis-value name — both "entra-obo" and "obo-okta" resolve to this token.
    assert resolve_outbound_topology("ON_BEHALF_OF_TOKEN_EXCHANGE") == "direct"


def test_non_obo_flows_select_gateway():
    assert resolve_outbound_topology("BASIC") == "gateway"
    assert resolve_outbound_topology("M2M") == "gateway"
    assert resolve_outbound_topology("USER_FEDERATION") == "gateway"
    assert resolve_outbound_topology(None) == "gateway"
    # The axis-value key ("obo") must not be mistaken for the flow token.
    assert resolve_outbound_topology("obo") == "gateway"


def test_direct_headers_promote_user_jwt_to_primary_authorization():
    h = build_direct_mcp_headers("USERJWT")
    assert h["Authorization"] == "Bearer USERJWT"
    # The direct-MCP path must not forward a secondary user-token header or M2M token.
    assert "x-user-token" not in h


def test_direct_headers_carry_audit_baggage_identically():
    h = build_direct_mcp_headers(
        "USERJWT",
        audit_context={
            "correlation_id": "sess-1",
            "initiator": "user@example.com",
            "trigger": "manual",
        },
    )
    assert h["x-audit-correlation-id"] == "sess-1"
    assert h["x-audit-initiator"] == "user@example.com"
    assert h["x-audit-trigger"] == "manual"


def test_direct_headers_omit_empty_audit_fields():
    h = build_direct_mcp_headers("USERJWT", audit_context={"correlation_id": "sess-1"})
    assert "x-audit-initiator" not in h
    assert "x-audit-trigger" not in h
