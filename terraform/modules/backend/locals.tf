# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# =============================================================================
# =============================================================================
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
# =============================================================================
# =============================================================================

locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.id

  stack_name_normalized = lower(replace(var.stack_name_base, "_", "-"))
  stack_name_underscore = replace(var.stack_name_base, "-", "_")

  agent_name = "FASTAgent"

  # Runtime name (underscores required by AgentCore)
  runtime_name = "${local.stack_name_underscore}_${local.agent_name}"

  # Memory name (unique within account/region)
  # Must match ^[a-zA-Z][a-zA-Z0-9_]{0,47}$ - no hyphens allowed
  memory_name = "${local.stack_name_underscore}_memory"

  oidc_discovery_url = "https://cognito-idp.${local.region}.amazonaws.com/${var.user_pool_id}/.well-known/openid-configuration"

  # Empty resolved_inbound_* vars fall back to Cognito-derived values, preserving the
  # zero-config default and each site's own client list.
  resolved_inbound_discovery_url = var.resolved_inbound_discovery_url != "" ? var.resolved_inbound_discovery_url : local.oidc_discovery_url

  resolved_inbound_runtime_clients = length(var.resolved_inbound_allowed_clients) > 0 ? var.resolved_inbound_allowed_clients : [var.web_client_id]
  resolved_inbound_gateway_clients = length(var.resolved_inbound_allowed_clients) > 0 ? var.resolved_inbound_allowed_clients : [aws_cognito_user_pool_client.machine.id]

  powertools_layer_arn = "arn:aws:lambda:${local.region}:017000801446:layer:AWSLambdaPowertoolsPythonV3-python313-arm64:18"

  is_docker = var.backend_deployment_type == "docker"
  is_zip    = var.backend_deployment_type == "zip"

  is_claude_agent_sdk = contains(["claude-agent-sdk-single-agent", "claude-agent-sdk-multi-agent"], var.backend_pattern)

  # Agent patterns live under agentcore/ (e.g. agentcore/agent/).
  project_root = "${path.module}/../../.."
  pattern_dir  = "${local.project_root}/agentcore/${var.backend_pattern}"

  zip_entry_point                 = ["opentelemetry-instrument", "basic_agent.py"]
  zip_packager_lambda_source_path = "${path.module}/../../../lambdas/zip_packager_cr"

  feedback_lambda_source_path = "${path.module}/../../../lambdas/feedback_api"

  # SAP OData is served by the external AWS-for-SAP MCP server, so no SAP-specific
  # Lambda handlers are needed here.
  case_management_source_path   = "${path.module}/../../../agentcore/gateway/tools/case_management"
  notification_source_path      = "${path.module}/../../../agentcore/gateway/tools/notification"
  knowledge_base_source_path    = "${path.module}/../../../agentcore/gateway/tools/knowledge_base"
  ticket_management_source_path = "${path.module}/../../../agentcore/gateway/tools/demo_ticket_management"
  policy_engine_source_path     = "${path.module}/../../../lambdas/policy_engine_cr"
  odata_poller_source_path      = "${path.module}/../../../lambdas/odata_poller"
  webhook_processor_source_path = "${path.module}/../../../lambdas/webhook_processor"
  agent_invoker_source_path     = "${path.module}/../../../lambdas/agent_invoker"
  exemplar_builder_source_path  = "${path.module}/../../../lambdas/exemplar_builder"
  cases_api_source_path         = "${path.module}/../../../lambdas/cases_api"
  autonomy_api_source_path      = "${path.module}/../../../lambdas/autonomy_api"
  tickets_api_source_path       = "${path.module}/../../../lambdas/demo_tickets"

  cors_origins = join(",", concat(
    [var.frontend_url, "http://localhost:3000"],
    var.additional_cors_origins
  ))

  ssm_parameter_prefix = "/${var.stack_name_base}"

  log_retention_days = var.log_retention_days

  api_throttling_rate_limit  = var.throttling_rate_limit
  api_throttling_burst_limit = var.throttling_burst_limit
  api_cache_ttl_seconds      = 300

  # Must stay in sync with the equivalent value in the CDK backend-stack.ts.
  memory_event_expiry_days = 30
}
# =============================================================================
# =============================================================================

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}
