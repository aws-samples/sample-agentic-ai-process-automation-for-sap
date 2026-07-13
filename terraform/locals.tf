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

  # Applied to all resources via provider default_tags, not per-resource.
  common_tags = {
    Project    = var.stack_name_base
    ManagedBy  = "Terraform"
    Repository = "agentic-erp-automation-quick-start"
  }

  ssm_parameter_prefix = "/${var.stack_name_base}"

  log_retention_days = 7

  staging_bucket_expiry_days = 30
  access_logs_expiry_days    = 90

  api_throttling_rate_limit  = 100
  api_throttling_burst_limit = 200
}
