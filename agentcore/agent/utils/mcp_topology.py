# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# This is sample code. Not for use in production.
# See NOTICE and LICENSE for more information.
"""Outbound MCP topology selection for the agent runtime.

Two topologies, chosen by the resolved outbound flow:

* "gateway" (default, unchanged): agent -> OUR AgentCore Gateway with an M2M
  credential provider; the user JWT rides along as a secondary ``x-user-token``.
* "direct" (OBO): agent -> external MCP server DIRECTLY, with the user's Entra JWT
  promoted to the PRIMARY ``Authorization: Bearer`` header, bypassing the Gateway.
  See docs/sap/runbooks/soidc-entra-obo.md.

Pure stdlib so the unit suite can import it (basic_agent.py pulls in strands/mcp
and is not importable in the hermetic test env).
"""

from __future__ import annotations

# The mcp_oauth_flow TOKEN that uses the direct-to-MCP OBO topology. Both the
# `obo` and `obo-okta` outbound profiles resolve to this single token
# (auth-profiles.yaml: mcp_oauth_flow: ON_BEHALF_OF_TOKEN_EXCHANGE), and that token
# is exactly what CDK publishes to SSM /{stack}/outbound_flow and the agent reads
# back. It is NOT the axis-value key ("obo"/"obo-okta") — the runtime never sees those.
_OBO_FLOWS = {"ON_BEHALF_OF_TOKEN_EXCHANGE"}


def resolve_outbound_topology(flow: str | None) -> str:
    """Return "direct" for the OBO token-exchange flow, else "gateway"."""
    return "direct" if flow in _OBO_FLOWS else "gateway"


def build_direct_mcp_headers(
    user_token: str, audit_context: dict | None = None
) -> dict[str, str]:
    """Headers for the Gateway-less OBO MCP client.

    The user's Entra JWT is the PRIMARY Authorization bearer (no Gateway M2M, no
    secondary x-user-token). The x-audit-* baggage block is identical to the
    Gateway path so SAP-side audit stays consistent across topologies.
    """
    headers = {"Authorization": f"Bearer {user_token}"}
    if audit_context:
        if audit_context.get("correlation_id"):
            headers["x-audit-correlation-id"] = audit_context["correlation_id"]
        if audit_context.get("initiator"):
            headers["x-audit-initiator"] = audit_context["initiator"]
        if audit_context.get("trigger"):
            headers["x-audit-trigger"] = audit_context["trigger"]
    return headers
