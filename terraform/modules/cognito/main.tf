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

  # Cognito domain prefix (must be globally unique and lowercase)
  domain_prefix = "${lower(replace(var.stack_name_base, "_", "-"))}-${local.account_id}-${local.region}"

  # Callback URLs (hardcoded to match CDK cognito-stack.ts defaults)
  default_callback_urls = ["http://localhost:3000", "https://localhost:3000"]

  all_callback_urls = var.amplify_url != null ? concat(local.default_callback_urls, [var.amplify_url]) : local.default_callback_urls

  # Password minimum length (hardcoded to match CDK cognito-stack.ts)
  password_minimum_length = 8

  invitation_email_subject = "Welcome to ${var.stack_name_base}!"
  invitation_email_body    = <<-EOF
<p>Hello {username},</p>
<p>Welcome to ${var.stack_name_base}! Your username is <strong>{username}</strong> and your temporary password is: <strong>{####}</strong></p>
<p>Please use this temporary password to log in and set your permanent password.</p>
<p>The CloudFront URL to your application is stored as an output in the "${var.stack_name_base}" stack, and will be printed to your terminal once the deployment process completes.</p>
<p>Thanks,</p>
<p>Fullstack AgentCore Solution Template Team</p>
EOF
}

# =============================================================================
# =============================================================================
resource "aws_cognito_user_pool" "main" {
  name = "${var.stack_name_base}-user-pool"

  admin_create_user_config {
    allow_admin_create_user_only = true

    invite_message_template {
      email_subject = local.invitation_email_subject
      email_message = local.invitation_email_body
      sms_message   = "Your username is {username} and temporary password is {####}"
    }
  }

  username_attributes = ["email"]

  auto_verified_attributes = ["email"]

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  password_policy {
    minimum_length                   = local.password_minimum_length
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 7
  }

  schema {
    name                     = "email"
    attribute_data_type      = "String"
    required                 = true
    mutable                  = false
    developer_only_attribute = false

    string_attribute_constraints {
      min_length = 0
      max_length = 2048
    }
  }

  email_configuration {
    email_sending_account = "COGNITO_DEFAULT"
  }

  deletion_protection = "INACTIVE"
}
# =============================================================================
# =============================================================================

resource "aws_cognito_user_pool_domain" "main" {
  domain       = local.domain_prefix
  user_pool_id = aws_cognito_user_pool.main.id
}

# =============================================================================
# =============================================================================
# Required for the v2 managed login to display properly
resource "aws_cognito_managed_login_branding" "main" {
  user_pool_id = aws_cognito_user_pool.main.id
  client_id    = aws_cognito_user_pool_client.web.id

  use_cognito_provided_values = true

  depends_on = [aws_cognito_user_pool_domain.main]
}

# =============================================================================
# =============================================================================
resource "aws_cognito_user_pool_client" "web" {
  name         = "${var.stack_name_base}-client"
  user_pool_id = aws_cognito_user_pool.main.id

  generate_secret = false

  explicit_auth_flows = [
    "ALLOW_USER_PASSWORD_AUTH",
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH"
  ]

  allowed_oauth_flows                  = ["code"]
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_scopes                 = ["openid", "email", "profile"]

  callback_urls = local.all_callback_urls
  logout_urls   = local.all_callback_urls

  supported_identity_providers = ["COGNITO"]

  prevent_user_existence_errors = "ENABLED"

  access_token_validity  = 1
  id_token_validity      = 1
  refresh_token_validity = 30

  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }
}
# =============================================================================
# =============================================================================

resource "aws_cognito_user" "admin" {
  count = var.admin_user_email != null ? 1 : 0

  user_pool_id = aws_cognito_user_pool.main.id
  username     = var.admin_user_email

  attributes = {
    email          = var.admin_user_email
    email_verified = true
  }

  desired_delivery_mediums = ["EMAIL"]
}
