# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# =============================================================================
# OAuth2 Credential Provider
# Maps to: backend-stack.ts createOAuth2CredentialProvider()
# =============================================================================

# -----------------------------------------------------------------------------
# CloudWatch Log Group for OAuth2 Provider Lambda
# -----------------------------------------------------------------------------

# AgentCore has no native Terraform/CloudFormation resource for OAuth2 Credential
# Provider, so this Lambda calls the bedrock-agentcore-control API directly to
# create/update/delete the provider, invoked as a CloudFormation Custom Resource via
# null_resource. The client secret is read from Secrets Manager at runtime rather than
# passed as a Lambda argument, so it never ends up in CloudWatch logs.

# nosemgrep: aws-cloudwatch-log-group-unencrypted, missing-cloudwatch-log-group-kms-key — quick-start uses AWS-managed keys
resource "aws_cloudwatch_log_group" "oauth2_provider" {
  name              = "/aws/lambda/${var.stack_name_base}-oauth2-provider-cr"
  retention_in_days = 7

}
# -----------------------------------------------------------------------------
# IAM Role for OAuth2 Provider Lambda
# -----------------------------------------------------------------------------


data "aws_iam_policy_document" "oauth2_provider_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "oauth2_provider" {
  name               = "${var.stack_name_base}-oauth2-provider-cr-role"
  assume_role_policy = data.aws_iam_policy_document.oauth2_provider_assume_role.json

}

data "aws_iam_policy_document" "oauth2_provider_policy" {
  statement {
    sid    = "CloudWatchLogsAccess"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]
    resources = ["${aws_cloudwatch_log_group.oauth2_provider.arn}:*"]
  }

  # Needed to read the machine client secret when registering the OAuth2 provider.
  statement {
    sid       = "ReadMachineClientSecret"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.machine_client_secret.arn]
  }

  # CreateOauth2CredentialProvider checks permission on both the vault itself
  # (token-vault/default) and the nested resource path — both ARNs are required.
  statement {
    sid    = "OAuth2CredentialProviderOperations"
    effect = "Allow"
    actions = [
      "bedrock-agentcore:CreateOauth2CredentialProvider",
      "bedrock-agentcore:GetOauth2CredentialProvider",
      "bedrock-agentcore:UpdateOauth2CredentialProvider",
      "bedrock-agentcore:DeleteOauth2CredentialProvider"
    ]
    resources = [
      "arn:aws:bedrock-agentcore:${local.region}:${local.account_id}:token-vault/default",
      "arn:aws:bedrock-agentcore:${local.region}:${local.account_id}:token-vault/default/oauth2credentialprovider/*"
    ]
  }

  # AWS checks permission on both the vault container itself (token-vault/default)
  # and resources inside it (token-vault/default/*) — both ARNs are required.
  statement {
    sid    = "TokenVaultOperations"
    effect = "Allow"
    actions = [
      "bedrock-agentcore:CreateTokenVault",
      "bedrock-agentcore:GetTokenVault",
      "bedrock-agentcore:DeleteTokenVault"
    ]
    resources = [
      "arn:aws:bedrock-agentcore:${local.region}:${local.account_id}:token-vault/default",
      "arn:aws:bedrock-agentcore:${local.region}:${local.account_id}:token-vault/default/*"
    ]
  }

  statement {
    sid    = "TokenVaultSecretManagement"
    effect = "Allow"
    actions = [
      "secretsmanager:CreateSecret",
      "secretsmanager:DeleteSecret",
      "secretsmanager:DescribeSecret",
      "secretsmanager:PutSecretValue"
    ]
    resources = [
      "arn:aws:secretsmanager:${local.region}:${local.account_id}:secret:bedrock-agentcore-identity!default/oauth2/*"
    ]
  }
}

resource "aws_iam_role_policy" "oauth2_provider" {
  name   = "${var.stack_name_base}-oauth2-provider-cr-policy"
  role   = aws_iam_role.oauth2_provider.id
  policy = data.aws_iam_policy_document.oauth2_provider_policy.json
}

# -----------------------------------------------------------------------------
# Lambda Function for OAuth2 Provider Lifecycle
# -----------------------------------------------------------------------------

data "archive_file" "oauth2_provider" {
  type        = "zip"
  source_file = "${path.module}/../../../lambdas/oauth2_provider_cr/index.py"
  output_path = "${path.module}/artifacts/oauth2-provider.zip"
}

# nosemgrep: aws-lambda-x-ray-tracing-not-active — production hardening step
resource "aws_lambda_function" "oauth2_provider" {
  filename         = data.archive_file.oauth2_provider.output_path
  function_name    = "${var.stack_name_base}-oauth2-provider-cr"
  role             = aws_iam_role.oauth2_provider.arn
  handler          = "index.handler"
  source_code_hash = data.archive_file.oauth2_provider.output_base64sha256
  runtime          = "python3.13"
  timeout          = 300 # 5 minutes


  depends_on = [
    aws_cloudwatch_log_group.oauth2_provider,
    aws_iam_role_policy.oauth2_provider
  ]
}

# -----------------------------------------------------------------------------
# Custom Resource Invocation via null_resource
# Simulates CloudFormation Custom Resource by invoking Lambda directly
# -----------------------------------------------------------------------------

resource "null_resource" "invoke_oauth2_provider" {
  triggers = {
    provider_name = "${var.stack_name_base}-runtime-gateway-auth"
    client_id     = aws_cognito_user_pool_client.machine.id
    client_secret = aws_secretsmanager_secret_version.machine_client_secret.version_id
    discovery_url = local.oidc_discovery_url
    function_name = aws_lambda_function.oauth2_provider.function_name
    region        = local.region
  }

  provisioner "local-exec" {
    interpreter = ["bash", "-c"]
    command     = <<-EOT
      set -e

      PAYLOAD=$(cat <<'PAYLOAD_EOF'
{
  "RequestType": "Create",
  "ResourceProperties": {
    "ProviderName": "${self.triggers.provider_name}",
    "ClientSecretArn": "${aws_secretsmanager_secret.machine_client_secret.arn}",
    "DiscoveryUrl": "${self.triggers.discovery_url}",
    "ClientId": "${self.triggers.client_id}"
  }
}
PAYLOAD_EOF
)

      echo "Invoking OAuth2 provider Lambda: ${self.triggers.function_name}"

      # --cli-binary-format raw-in-base64-out is required for the JSON payload to be accepted.
      aws lambda invoke \
        --function-name ${self.triggers.function_name} \
        --cli-binary-format raw-in-base64-out \
        --payload "$PAYLOAD" \
        --region ${self.triggers.region} \
        /tmp/oauth2_provider_response.json

      if grep -q "FunctionError" /tmp/oauth2_provider_response.json; then
        echo "ERROR: OAuth2 provider creation failed"
        cat /tmp/oauth2_provider_response.json
        exit 1
      fi

      echo "OAuth2 provider created successfully"
      cat /tmp/oauth2_provider_response.json
    EOT
  }

  provisioner "local-exec" {
    when        = destroy
    interpreter = ["bash", "-c"]
    command     = <<-EOT
      PAYLOAD=$(cat <<'PAYLOAD_EOF'
{
  "RequestType": "Delete",
  "PhysicalResourceId": "${self.triggers.provider_name}",
  "ResourceProperties": {
    "ProviderName": "${self.triggers.provider_name}"
  }
}
PAYLOAD_EOF
)

      echo "Deleting OAuth2 provider: ${self.triggers.provider_name}"

      # Invoke Lambda for deletion (ignore errors if already deleted)
      aws lambda invoke \
        --function-name ${self.triggers.function_name} \
        --cli-binary-format raw-in-base64-out \
        --payload "$PAYLOAD" \
        --region ${self.triggers.region} \
        /tmp/oauth2_provider_delete.json || true

      echo "OAuth2 provider deletion completed"
      cat /tmp/oauth2_provider_delete.json || true
    EOT
  }

  depends_on = [
    aws_lambda_function.oauth2_provider,
    aws_cognito_user_pool_client.machine,
    aws_secretsmanager_secret_version.machine_client_secret
  ]
}
