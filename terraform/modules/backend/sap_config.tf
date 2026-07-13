# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# =============================================================================
# Autonomy Controls, SAP Connectivity, Notification, Auth Provider SSM Params
# Maps to: backend-stack.ts autonomy SSM params + constructs/
# =============================================================================

# Autonomy, SAP connectivity, notification, and auth-provider SSM parameters.

resource "aws_ssm_parameter" "autonomy_trigger_mode" {
  name        = "${local.ssm_parameter_prefix}/autonomy/trigger-mode"
  type        = "String"
  value       = var.trigger_mode
  description = "auto = poller enqueues immediately, manual = human triggers from UI/CLI"
}

resource "aws_ssm_parameter" "sap_base_url" {
  name        = "${local.ssm_parameter_prefix}/connectivity/sap-base-url"
  type        = "String"
  value       = var.sap_base_url != null ? var.sap_base_url : "https://localhost"
  description = "SAP OData endpoint URL"
}

resource "aws_ssm_parameter" "notification_channel" {
  name        = "${local.ssm_parameter_prefix}/notification/channel"
  type        = "String"
  value       = var.notification_channel
  description = "Notification channel: ses, slack, jira, servicenow"
}

resource "aws_ssm_parameter" "auth_provider" {
  name        = "${local.ssm_parameter_prefix}/auth/provider"
  type        = "String"
  value       = var.auth_provider
  description = "Frontend auth provider: cognito, okta, custom-oidc"
}

resource "aws_ssm_parameter" "auth_issuer_url" {
  count = var.auth_issuer_url != null ? 1 : 0

  name  = "${local.ssm_parameter_prefix}/auth/issuer-url"
  type  = "String"
  value = var.auth_issuer_url
}

resource "aws_ssm_parameter" "auth_client_id" {
  count = var.auth_client_id != null ? 1 : 0

  name  = "${local.ssm_parameter_prefix}/auth/client-id"
  type  = "String"
  value = var.auth_client_id
}

resource "aws_ssm_parameter" "cedar_enforcement_mode" {
  name        = "${local.ssm_parameter_prefix}/cedar/enforcement-mode"
  type        = "String"
  value       = var.cedar_enforcement_mode
  description = "Cedar policy enforcement mode: LOG_ONLY or ENFORCE"
}
