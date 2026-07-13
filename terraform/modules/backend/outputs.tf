# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
# =============================================================================
# =============================================================================

output "memory_arn" {
  description = "AgentCore Memory ARN"
  value       = aws_bedrockagentcore_memory.main.arn
}
# =============================================================================
# =============================================================================

output "gateway_id" {
  description = "AgentCore Gateway ID"
  value       = aws_bedrockagentcore_gateway.main.gateway_id
}

output "gateway_arn" {
  description = "AgentCore Gateway ARN"
  value       = aws_bedrockagentcore_gateway.main.gateway_arn
}

output "gateway_url" {
  description = "AgentCore Gateway URL"
  value       = aws_bedrockagentcore_gateway.main.gateway_url
}

# =============================================================================
# =============================================================================
output "runtime_id" {
  description = "AgentCore Runtime ID"
  value       = aws_bedrockagentcore_agent_runtime.main.agent_runtime_id
}

output "runtime_arn" {
  description = "AgentCore Runtime ARN"
  value       = aws_bedrockagentcore_agent_runtime.main.agent_runtime_arn
}

output "runtime_role_arn" {
  description = "AgentCore Runtime execution role ARN"
  value       = aws_iam_role.runtime.arn
}

# =============================================================================
# =============================================================================
output "feedback_api_url" {
  description = "Feedback API endpoint URL"
  value       = "${aws_api_gateway_stage.prod.invoke_url}/feedback"
}

# =============================================================================
# =============================================================================
output "machine_client_id" {
  description = "Cognito Machine Client ID (for M2M authentication)"
  value       = aws_cognito_user_pool_client.machine.id
}
# =============================================================================
# =============================================================================

output "sops_bucket_arn" {
  description = "SOPs S3 bucket ARN"
  value       = aws_s3_bucket.sops.arn
}

output "api_docs_bucket_arn" {
  description = "API docs S3 bucket ARN"
  value       = aws_s3_bucket.api_docs.arn
}

output "sap_credentials_secret_arn" {
  description = "SAP credentials Secrets Manager ARN"
  value       = aws_secretsmanager_secret.sap_credentials.arn
}

output "cases_table_name" {
  description = "Cases DynamoDB table name"
  value       = aws_dynamodb_table.cases.name
}

output "tickets_table_name" {
  description = "Tickets DynamoDB table name (demo — null when demo_enabled is false)"
  value       = var.demo_enabled ? aws_dynamodb_table.tickets[0].name : null
}

output "demo_api_url" {
  description = "Demo API Gateway invoke URL (null when demo_enabled is false)"
  value       = var.demo_enabled ? aws_api_gateway_stage.demo[0].invoke_url : null
}
