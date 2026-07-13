# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
# =============================================================================
# Core Configuration
# =============================================================================


variable "stack_name_base" {
  description = "Base name for all resources."
  type        = string
}

variable "backend_pattern" {
  description = "Agent pattern to deploy."
  type        = string
  default     = "agent"
}

variable "backend_deployment_type" {
  description = "Deployment type: 'docker' (container via ECR) or 'zip' (Python package via S3). Note: claude-agent-sdk patterns require 'docker'."
  type        = string
  default     = "docker"
}

variable "backend_network_mode" {
  description = "Network mode for AgentCore Runtime (PUBLIC or VPC)."
  type        = string
  default     = "PUBLIC"
}


# =============================================================================
# VPC Configuration (Required if backend_network_mode = VPC)
# =============================================================================

variable "backend_vpc_id" {
  description = "VPC ID for VPC network mode. Required when backend_network_mode is 'VPC'."
  type        = string
  default     = null
}

variable "backend_vpc_subnet_ids" {
  description = "List of subnet IDs for VPC network mode. Required when backend_network_mode is 'VPC'."
  type        = list(string)
  default     = []
}

variable "backend_vpc_security_group_ids" {
  description = "List of security group IDs for VPC network mode. Optional when backend_network_mode is 'VPC'. If omitted, a default security group is created."
  type        = list(string)
  default     = []
}

# =============================================================================
# Cognito Configuration (passed from cognito module)
# =============================================================================

# Values passed from the cognito module.

variable "user_pool_id" {
  description = "Cognito User Pool ID."
  type        = string
}

variable "user_pool_arn" {
  description = "Cognito User Pool ARN."
  type        = string
}

variable "web_client_id" {
  description = "Cognito Web Client ID (for frontend OAuth)."
  type        = string
}

# =============================================================================
# Amplify Configuration (passed from amplify module)
# =============================================================================

# Values passed from the amplify module.

variable "frontend_url" {
  description = "Frontend URL for CORS and callback configuration."
  type        = string
}

variable "cognito_domain_url" {
  description = "Cognito domain URL for OAuth token endpoint."
  type        = string
}
# =============================================================================
# Optional Configuration
# =============================================================================


variable "container_uri" {
  description = "Container image URI. If not provided, ECR repository will be created."
  type        = string
  default     = null
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days."
  type        = number
  default     = 7
}

variable "throttling_rate_limit" {
  description = "API Gateway throttling rate limit."
  type        = number
  default     = 100
}

variable "throttling_burst_limit" {
  description = "API Gateway throttling burst limit."
  type        = number
  default     = 200
}


# =============================================================================
# SAP Configuration
# =============================================================================

variable "sap_base_url" {
  description = "SAP OData endpoint URL."
  type        = string
  default     = null
}


variable "poller_schedule" {
  description = "EventBridge rate expression for OData poller."
  type        = string
  default     = "rate(5 minutes)"
}

variable "embedding_model" {
  description = "Bedrock embedding model for Knowledge Bases."
  type        = string
  default     = "amazon.titan-embed-text-v2:0"
}

# =============================================================================
# Autonomy Controls
# =============================================================================

variable "trigger_mode" {
  description = "auto = poller enqueues immediately, manual = human triggers from UI/CLI."
  type        = string
  default     = "manual"
}
# =============================================================================
# Notification Configuration
# =============================================================================


variable "notification_channel" {
  description = "Notification channel: ses, slack, jira, servicenow."
  type        = string
  default     = "ses"
}

variable "ses_sender_email" {
  description = "SES sender email (when notification_channel = ses)."
  type        = string
  default     = null
}

variable "notification_secret_arn" {
  description = "Secrets Manager ARN for notification credentials (slack/jira/servicenow)."
  type        = string
  default     = null
}

# =============================================================================
# Auth Provider Configuration
# =============================================================================

variable "auth_provider" {
  description = "Frontend auth provider: cognito, okta, custom-oidc."
  type        = string
  default     = "cognito"
}

variable "auth_issuer_url" {
  description = "OIDC issuer URL (for okta/custom-oidc)."
  type        = string
  default     = null
}

variable "auth_client_id" {
  description = "OIDC client ID (for okta/custom-oidc)."
  type        = string
  default     = null
}

# =============================================================================
# Cedar Policy Engine
# =============================================================================

variable "cedar_enforcement_mode" {
  description = "Cedar enforcement mode: LOG_ONLY or ENFORCE."
  type        = string
  default     = "LOG_ONLY"
}
# =============================================================================
# Observability
# =============================================================================


variable "alarm_email" {
  description = "Email for CloudWatch alarm notifications."
  type        = string
  default     = null
}

# =============================================================================
# Additional CORS Origins
# =============================================================================

variable "additional_cors_origins" {
  description = "Additional CORS origins (e.g. hosting CloudFront URL)."
  type        = list(string)
  default     = []
}
# =============================================================================
# Contacts Directory
# =============================================================================


variable "contacts" {
  description = "Contact directory for SOP placeholder substitution."
  type        = map(string)
  default     = {}
}

# =============================================================================
# Agent Queue
# =============================================================================

variable "agent_queue_max_concurrency" {
  description = "Max concurrent agent invocations."
  type        = number
  default     = 5
}
# =============================================================================
# Demo Infrastructure
# =============================================================================


variable "demo_enabled" {
  description = <<-EOT
    Single opt-in gate for ALL demo/sample resources. When true, creates the
    ticket-management demo (tickets table + API + approve/deny resume flow,
    demo_ticket_management Gateway tool) and the test-data Lambda + /demo/*
    API. Leave false for a clean production base.
  EOT
  type        = bool
  default     = false
}

variable "resolved_inbound_discovery_url" {
  description = "Resolved inbound OIDC discovery URL from the emit data source. Empty = Cognito fallback."
  type        = string
  default     = ""
}

variable "resolved_inbound_allowed_clients" {
  description = "Resolved inbound allowed client IDs from the emit data source. Empty = Cognito fallback."
  type        = list(string)
  default     = []
}
