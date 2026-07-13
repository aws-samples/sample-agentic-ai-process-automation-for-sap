// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
//
// This is sample code. Not for use in production.
// See NOTICE and LICENSE for more information.
// ============================================================================
// SAP ERP Agent — Cedar Policies for AgentCore Gateway
// ============================================================================
// These policies enforce deterministic guardrails on agent-to-tool interactions.
// They are evaluated at the Gateway BEFORE tool execution — independent of
// the agent's reasoning, prompt, or SOP.
//
// Enforcement model:
//   - Default DENY (no policy match = blocked)
//   - Forbid wins over permit
//   - Policies evaluate independently
//
// Principal tags come from the JWT token (Cognito claims):
//   role, department, username, scope
// Context.input contains the tool call arguments.
//
// Action-name format is `<gatewayTargetName>___<toolName>`. SAP data flows
// through the EXTERNAL AWS-for-SAP MCP server, attached as a Gateway MCP target
// named `<stack>-sap-mcp-service-target`. `__STACK_NAME_BASE__` is substituted
// with the deployment's stack_name_base when the policies are loaded (CDK
// backend-stack.ts / Terraform). The SAP MCP write tools are
// odata_create / odata_update / odata_delete / odata_function_import; the read
// tools are find_sap_services / get_metadata / odata_read / odata_count /
// get_service_hints.
//
// There is no runtime `action-mode` write kill-switch in this sample. SAP write
// gating is expressed HERE (role-based permits on odata_create/update/
// function_import; odata_delete forbidden outright) and at the external
// AWS-for-SAP MCP server (MCP_SERVER_WRITE_ENABLED + per-op knobs). The
// `trigger-mode` control only governs whether the poller auto-enqueues cases —
// not writes. See threats T6/T15 for the accepted-risk rationale and the
// production guidance to add a Gateway request interceptor.
// ============================================================================


// ─── READ OPERATIONS: Broadly permitted ─────────────────────────────────────
// All authenticated users can search knowledge bases and read case state.
// These are non-destructive operations.

permit(
  principal is AgentCore::OAuthUser,
  action in [
    AgentCore::Action::"knowledge-base-target___search_sap_sops",
    AgentCore::Action::"knowledge-base-target___search_sap_api_docs",
    AgentCore::Action::"case-management-target___get_case_state"
  ],
  resource
);


// ─── SAP OData READS: Broadly permitted (non-destructive) ───────────────────
// SAP reads/discovery go through the external SAP MCP server.

permit(
  principal is AgentCore::OAuthUser,
  action in [
    AgentCore::Action::"__STACK_NAME_BASE__-sap-mcp-service-target___find_sap_services",
    AgentCore::Action::"__STACK_NAME_BASE__-sap-mcp-service-target___get_metadata",
    AgentCore::Action::"__STACK_NAME_BASE__-sap-mcp-service-target___get_service_hints",
    AgentCore::Action::"__STACK_NAME_BASE__-sap-mcp-service-target___odata_read",
    AgentCore::Action::"__STACK_NAME_BASE__-sap-mcp-service-target___odata_count"
  ],
  resource
);


// ─── SAP OData WRITES: require finance/procurement/admin role ───────────────
// create / update / function_import via the SAP MCP server are gated on role.
// (delete is forbidden outright below.)

permit(
  principal is AgentCore::OAuthUser,
  action in [
    AgentCore::Action::"__STACK_NAME_BASE__-sap-mcp-service-target___odata_create",
    AgentCore::Action::"__STACK_NAME_BASE__-sap-mcp-service-target___odata_update",
    AgentCore::Action::"__STACK_NAME_BASE__-sap-mcp-service-target___odata_function_import"
  ],
  resource
)
when {
  principal.hasTag("role") &&
  (principal.getTag("role") == "finance" ||
   principal.getTag("role") == "procurement" ||
   principal.getTag("role") == "admin")
};

// Block DELETE on SAP — never allowed through the agent. `odata_delete` is its
// own MCP tool, so this is a clean action-level forbid (forbid wins over permit).
forbid(
  principal is AgentCore::OAuthUser,
  action == AgentCore::Action::"__STACK_NAME_BASE__-sap-mcp-service-target___odata_delete",
  resource
);


// ─── SAP USER-FEDERATION TARGET: same gates as the service target ───────────
// When auth_profile's outbound axis is `user-federation`, the stack provisions
// a SECOND Gateway MCP target (`-sap-mcp-user-target`) that ALSO routes through
// the Gateway (unlike the T16 OBO direct-MCP bypass). It must be gated
// identically to the service target, or the role gate + delete forbid would not
// apply on that path (the T8 "Cedar gap"). Reads permitted; writes role-gated;
// delete forbidden.

permit(
  principal is AgentCore::OAuthUser,
  action in [
    AgentCore::Action::"__STACK_NAME_BASE__-sap-mcp-user-target___find_sap_services",
    AgentCore::Action::"__STACK_NAME_BASE__-sap-mcp-user-target___get_metadata",
    AgentCore::Action::"__STACK_NAME_BASE__-sap-mcp-user-target___get_service_hints",
    AgentCore::Action::"__STACK_NAME_BASE__-sap-mcp-user-target___odata_read",
    AgentCore::Action::"__STACK_NAME_BASE__-sap-mcp-user-target___odata_count"
  ],
  resource
);

// User-target writes: require finance/procurement/admin role (delete forbidden below).
permit(
  principal is AgentCore::OAuthUser,
  action in [
    AgentCore::Action::"__STACK_NAME_BASE__-sap-mcp-user-target___odata_create",
    AgentCore::Action::"__STACK_NAME_BASE__-sap-mcp-user-target___odata_update",
    AgentCore::Action::"__STACK_NAME_BASE__-sap-mcp-user-target___odata_function_import"
  ],
  resource
)
when {
  principal.hasTag("role") &&
  (principal.getTag("role") == "finance" ||
   principal.getTag("role") == "procurement" ||
   principal.getTag("role") == "admin")
};

// Block DELETE on the user-target too (forbid wins over permit).
forbid(
  principal is AgentCore::OAuthUser,
  action == AgentCore::Action::"__STACK_NAME_BASE__-sap-mcp-user-target___odata_delete",
  resource
);


// ─── CASE STATE UPDATES: Permitted for all authenticated users ──────────────
// Agents need to update case state as they work through SOPs.

permit(
  principal is AgentCore::OAuthUser,
  action == AgentCore::Action::"case-management-target___update_case_state",
  resource
);


// ─── NOTIFICATIONS: Permitted but high-priority requires finance role ───────

// Standard notifications (low/medium priority) — anyone
permit(
  principal is AgentCore::OAuthUser,
  action == AgentCore::Action::"notification-target___send_notification",
  resource
)
when {
  !(context.input has priority) ||
  context.input.priority == "low" ||
  context.input.priority == "medium"
};

// High/critical priority notifications — finance or admin only
permit(
  principal is AgentCore::OAuthUser,
  action == AgentCore::Action::"notification-target___send_notification",
  resource
)
when {
  context.input has priority &&
  (context.input.priority == "high" || context.input.priority == "critical") &&
  principal.hasTag("role") &&
  (principal.getTag("role") == "finance" || principal.getTag("role") == "admin")
};


// ─── PII GUARDRAIL: Suppress notification bodies exposing sensitive data ────
// Deterministic, agent-cannot-bypass check at the Gateway (see ADR-004,
// threats T2/T15) — separate from the model-level Bedrock Guardrail
// (security.guardrail_enabled, createAgentGuardrail in backend-stack.ts),
// which only sees the model's own turn, not composed tool-call payloads.
// Requires bedrock:InvokeGuardrailChecks on the Gateway execution role (see
// backend-stack.ts createAgentCoreGateway). Threshold 0.4 (default is 0.2) —
// SAP vendor data legitimately contains bank/tax numbers, so this targets
// only the categories that should never appear in a notification body
// (credentials, SSNs, card numbers) at a confidence high enough to avoid
// false-positive blocking of routine AP correspondence.
suppressOutput(
  principal is AgentCore::OAuthUser,
  action == AgentCore::Action::"notification-target___send_notification",
  resource
)
when guardrails {
  BedrockGuardrails::SensitiveInformation(
    ["US_SOCIAL_SECURITY_NUMBER", "CREDIT_DEBIT_CARD_NUMBER", "AWS_ACCESS_KEY", "AWS_SECRET_KEY", "PASSWORD"],
    [context.input.body, context.input.subject]
  ).maxConfidenceScore().greaterThan(decimal("0.4"))
};
