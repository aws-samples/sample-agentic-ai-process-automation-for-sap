# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
# =============================================================================
# Provider Configuration
# =============================================================================


provider "aws" {
  default_tags {
    tags = local.common_tags
  }
}

# =============================================================================
# DEPLOYMENT ORDER:
# 1. Amplify Hosting - Creates app and gets predictable URL
# 2. Cognito - Uses Amplify URL for callback URLs
# 3. Backend Resources (Memory, Gateway, Runtime, Feedback API)
# =============================================================================

# =============================================================================
# Module: Amplify Hosting (Frontend)
# =============================================================================

# Amplify must deploy before Cognito (Cognito needs the Amplify URL for
# callback URLs), and both before the backend module.

module "amplify_hosting" {
  source = "./modules/amplify-hosting"

  stack_name_base = var.stack_name_base

  staging_bucket_expiry_days = local.staging_bucket_expiry_days
  access_logs_expiry_days    = local.access_logs_expiry_days
}

# =============================================================================
# Module: Cognito (Authentication)
# =============================================================================

module "cognito" {
  source = "./modules/cognito"

  stack_name_base  = var.stack_name_base
  admin_user_email = var.admin_user_email
  amplify_url      = module.amplify_hosting.app_url

  depends_on = [module.amplify_hosting]
}
# =============================================================================
# Module: Backend (AgentCore + Feedback API)
# =============================================================================

# =============================================================================
# Module: Backend (AgentCore + Feedback API + SAP Resources)
# =============================================================================


module "backend" {
  source = "./modules/backend"

  stack_name_base         = var.stack_name_base
  backend_pattern         = var.backend_pattern
  backend_deployment_type = var.backend_deployment_type
  backend_network_mode    = var.backend_network_mode

  backend_vpc_id                 = var.backend_vpc_id
  backend_vpc_subnet_ids         = var.backend_vpc_subnet_ids
  backend_vpc_security_group_ids = var.backend_vpc_security_group_ids

  user_pool_id       = module.cognito.user_pool_id
  user_pool_arn      = module.cognito.user_pool_arn
  web_client_id      = module.cognito.web_client_id
  cognito_domain_url = module.cognito.cognito_domain_url

  frontend_url            = module.amplify_hosting.app_url
  additional_cors_origins = []

  sap_base_url    = var.sap_base_url
  poller_schedule = var.poller_schedule
  embedding_model = var.embedding_model

  trigger_mode = var.trigger_mode

  notification_channel    = var.notification_channel
  ses_sender_email        = var.ses_sender_email
  notification_secret_arn = var.notification_secret_arn

  auth_provider   = var.auth_provider
  auth_issuer_url = var.auth_issuer_url
  auth_client_id  = var.auth_client_id

  # Empty → backend module falls back to Cognito-derived values.
  resolved_inbound_discovery_url   = local.emit_discovery_url
  resolved_inbound_allowed_clients = local.emit_allowed_clients

  cedar_enforcement_mode = var.cedar_enforcement_mode

  alarm_email = var.alarm_email

  contacts = var.contacts

  agent_queue_max_concurrency = var.agent_queue_max_concurrency

  demo_enabled = var.demo_enabled

  log_retention_days     = local.log_retention_days
  throttling_rate_limit  = local.api_throttling_rate_limit
  throttling_burst_limit = local.api_throttling_burst_limit

  depends_on = [module.cognito, module.amplify_hosting]
}
# =============================================================================
# Module: Knowledge Base (S3 Vectors + Bedrock KB)
# =============================================================================


module "knowledge_base" {
  source = "./modules/knowledge-base"

  stack_name_base     = var.stack_name_base
  sops_bucket_arn     = module.backend.sops_bucket_arn
  api_docs_bucket_arn = module.backend.api_docs_bucket_arn
  embedding_model     = var.embedding_model

  depends_on = [module.backend]
}
