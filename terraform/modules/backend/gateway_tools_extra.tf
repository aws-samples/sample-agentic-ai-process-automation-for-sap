# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# =============================================================================
# Gateway Tool Lambdas (Part 2: demo tools + policy engine)
#
# SAP OData entity specs are provided by the external AWS-for-SAP MCP server
# (get_metadata) — there is no homegrown odata_spec Lambda.
#
# The ticket-management tool Lambda is a DEMO resource, gated by
# var.demo_enabled (count). Its backing DynamoDB table lives in demo.tf.
# =============================================================================

# ── Ticket Management Lambda (demo) ─────────────────────────────────────────

# nosemgrep: aws-cloudwatch-log-group-unencrypted
resource "aws_cloudwatch_log_group" "ticket_management" {
  count             = var.demo_enabled ? 1 : 0
  name              = "/aws/lambda/${var.stack_name_base}-ticket-mgmt"
  retention_in_days = local.log_retention_days
}

resource "aws_iam_role" "ticket_management" {
  count              = var.demo_enabled ? 1 : 0
  name               = "${var.stack_name_base}-ticket-mgmt-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

data "aws_iam_policy_document" "ticket_management_policy" {
  count = var.demo_enabled ? 1 : 0
  statement {
    sid       = "Logs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.ticket_management[0].arn}:*"]
  }
  statement {
    sid    = "DynamoDB"
    effect = "Allow"
    actions = [
      "dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem",
      "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:Scan"
    ]
    resources = [aws_dynamodb_table.tickets[0].arn, "${aws_dynamodb_table.tickets[0].arn}/index/*"]
  }
  statement {
    sid       = "SSM"
    effect    = "Allow"
    actions   = ["ssm:GetParameter"]
    resources = ["arn:aws:ssm:${local.region}:${local.account_id}:parameter/${var.stack_name_base}/*"]
  }
  statement {
    sid       = "Secrets"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.sap_credentials.arn]
  }
}

resource "aws_iam_role_policy" "ticket_management" {
  count  = var.demo_enabled ? 1 : 0
  name   = "${var.stack_name_base}-ticket-mgmt-policy"
  role   = aws_iam_role.ticket_management[0].id
  policy = data.aws_iam_policy_document.ticket_management_policy[0].json
}

data "archive_file" "ticket_management" {
  count       = var.demo_enabled ? 1 : 0
  type        = "zip"
  source_dir  = local.ticket_management_source_path
  output_path = "${path.module}/artifacts/ticket_management.zip"
  excludes    = ["__pycache__", "*.pyc", "tool_spec.json"]
}

# nosemgrep: aws-lambda-x-ray-tracing-not-active
resource "aws_lambda_function" "ticket_management" {
  count            = var.demo_enabled ? 1 : 0
  function_name    = "${var.stack_name_base}-ticket-mgmt"
  role             = aws_iam_role.ticket_management[0].arn
  handler          = "ticket_management_lambda.handler"
  runtime          = "python3.13"
  timeout          = 30
  filename         = data.archive_file.ticket_management[0].output_path
  source_code_hash = data.archive_file.ticket_management[0].output_base64sha256
  layers           = [aws_lambda_layer_version.shared_types.arn]

  environment {
    variables = {
      TICKETS_TABLE_SSM_PARAM = "/${var.stack_name_base}/dynamodb/tickets-table"
    }
  }

  depends_on = [aws_cloudwatch_log_group.ticket_management]
}

# ── Cedar Policy Engine Lambda ───────────────────────────────────────────────

# nosemgrep: aws-cloudwatch-log-group-unencrypted
resource "aws_cloudwatch_log_group" "policy_engine" {
  name              = "/aws/lambda/${var.stack_name_base}-policy-engine-cr"
  retention_in_days = local.log_retention_days
}

resource "aws_iam_role" "policy_engine" {
  name               = "${var.stack_name_base}-policy-engine-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

data "aws_iam_policy_document" "policy_engine_policy" {
  statement {
    sid       = "Logs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.policy_engine.arn}:*"]
  }
  statement {
    sid    = "AgentCore"
    effect = "Allow"
    actions = [
      "bedrock-agentcore:CreatePolicyEngine", "bedrock-agentcore:DeletePolicyEngine",
      "bedrock-agentcore:GetPolicyEngine", "bedrock-agentcore:ListPolicyEngines",
      "bedrock-agentcore:CreatePolicy", "bedrock-agentcore:DeletePolicy",
      "bedrock-agentcore:ListPolicies", "bedrock-agentcore:UpdatePolicy",
      "bedrock-agentcore:UpdateGateway", "bedrock-agentcore:GetGateway"
    ]
    resources = [
      "arn:aws:bedrock-agentcore:${local.region}:${local.account_id}:policy-engine/*",
      "arn:aws:bedrock-agentcore:${local.region}:${local.account_id}:gateway/*"
    ]
  }
}

resource "aws_iam_role_policy" "policy_engine" {
  name   = "${var.stack_name_base}-policy-engine-policy"
  role   = aws_iam_role.policy_engine.id
  policy = data.aws_iam_policy_document.policy_engine_policy.json
}

data "archive_file" "policy_engine" {
  type        = "zip"
  source_dir  = local.policy_engine_source_path
  output_path = "${path.module}/artifacts/policy_engine.zip"
  excludes    = ["__pycache__", "*.pyc"]
}

# nosemgrep: aws-lambda-x-ray-tracing-not-active
resource "aws_lambda_function" "policy_engine" {
  function_name    = "${var.stack_name_base}-policy-engine-cr"
  role             = aws_iam_role.policy_engine.arn
  handler          = "index.handler"
  runtime          = "python3.13"
  architectures    = ["arm64"]
  timeout          = 120
  filename         = data.archive_file.policy_engine.output_path
  source_code_hash = data.archive_file.policy_engine.output_base64sha256

  depends_on = [aws_cloudwatch_log_group.policy_engine]
}
