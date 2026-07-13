# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
# =============================================================================
# Required Variables
# =============================================================================


variable "stack_name_base" {
  description = "Base name for all resources. Used as prefix for resource naming."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,34}$", var.stack_name_base))
    error_message = "Stack name must start with a lowercase letter, be 3-35 characters, and contain only lowercase alphanumeric characters and hyphens."
  }
}

# =============================================================================
# Optional Variables - Admin User
# =============================================================================

variable "admin_user_email" {
  description = "Email address for the admin user. If provided, creates an admin user and sends credentials via email. Set to null to skip admin user creation."
  type        = string
  default     = null

  validation {
    condition     = var.admin_user_email == null || can(regex("^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$", var.admin_user_email))
    error_message = "Must be a valid email address or null."
  }
}
# =============================================================================
# Backend Configuration
# =============================================================================


variable "backend_pattern" {
  description = "Agent pattern to deploy. The sample ships a single Strands agent at top-level 'agent/'."
  type        = string
  default     = "agent"

  validation {
    condition     = var.backend_pattern == "agent"
    error_message = "Backend pattern must be 'agent'."
  }
}

variable "backend_deployment_type" {
  description = "Deployment type for AgentCore Runtime. 'docker' uses ECR container image (requires Docker + separate build step). 'zip' uses S3 Python package (no Docker required, single-step deploy)."
  type        = string
  default     = "docker"

  validation {
    condition     = contains(["docker", "zip"], var.backend_deployment_type)
    error_message = "Deployment type must be 'docker' or 'zip'."
  }
}

variable "backend_network_mode" {
  description = "Network mode for AgentCore Runtime. PUBLIC (default) uses public internet. VPC deploys into a user-provided VPC for private network isolation."
  type        = string
  default     = "PUBLIC"

  validation {
    condition     = contains(["PUBLIC", "VPC"], var.backend_network_mode)
    error_message = "Network mode must be 'PUBLIC' or 'VPC'."
  }
}

# =============================================================================
# VPC Configuration (Required if backend_network_mode = VPC)
# =============================================================================

# VPC config below is required only when backend_network_mode = VPC
variable "backend_vpc_id" {
  description = "VPC ID for VPC network mode. Required when backend_network_mode is 'VPC'."
  type        = string
  default     = null
}

variable "backend_vpc_subnet_ids" {
  description = "List of subnet IDs for VPC network mode. Required when backend_network_mode is 'VPC'. Subnets should be in at least two Availability Zones."
  type        = list(string)
  default     = []
}

variable "backend_vpc_security_group_ids" {
  description = "List of security group IDs for VPC network mode. Optional when backend_network_mode is 'VPC'. If omitted, a default security group is created with HTTPS self-referencing ingress and all-traffic egress."
  type        = list(string)
  default     = []
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

variable "auth_profile" {
  description = "Inbound auth profile name from auth-profiles.yaml (default cognito-basic)."
  type        = string
  default     = "cognito-basic"
}

variable "auth_inbound_discovery_url" {
  description = "OIDC discovery URL for entra/okta inbound profiles. Empty for cognito (fallback)."
  type        = string
  default     = ""
}

variable "auth_inbound_allowed_clients" {
  description = "Allowed client IDs for entra/okta inbound profiles. Empty for cognito (fallback)."
  type        = list(string)
  default     = []
}

variable "sap_mcp_enabled" {
  description = "Whether the SAP MCP path is active. Gates the emit-time mcp_supported guard: a Gateway-mediated outbound marked mcp_supported:false aborts at plan time (the direct-to-MCP OBO path is exempt). Terraform does not wire the SAP MCP adapter itself (CDK-only) — this only arms the safety guard, so leave it false on the Terraform backend."
  type        = bool
  default     = false
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
  description = "Single opt-in gate for ALL demo/sample resources (ticket management demo, AR lockbox demo, test-data API). Leave false for a clean production base."
  type        = bool
  default     = false
}
