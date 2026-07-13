# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# =============================================================================
# Gateway Tool Lambdas (Part 1: Core tools)
#
# SAP OData read/write/discovery is provided by the external AWS-for-SAP MCP
# server (attached as a Gateway MCP target), not by a homegrown Lambda.
# =============================================================================

# ── Case Management Lambda ───────────────────────────────────────────────────

# nosemgrep: aws-cloudwatch-log-group-unencrypted
resource "aws_cloudwatch_log_group" "case_management" {
  name              = "/aws/lambda/${var.stack_name_base}-case-mgmt"
  retention_in_days = local.log_retention_days
}

resource "aws_iam_role" "case_management" {
  name               = "${var.stack_name_base}-case-mgmt-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

data "aws_iam_policy_document" "case_management_policy" {
  statement {
    sid       = "Logs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.case_management.arn}:*"]
  }
  statement {
    sid    = "DynamoDB"
    effect = "Allow"
    actions = [
      "dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem",
      "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:Scan"
    ]
    resources = [aws_dynamodb_table.cases.arn, "${aws_dynamodb_table.cases.arn}/index/*"]
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

resource "aws_iam_role_policy" "case_management" {
  name   = "${var.stack_name_base}-case-mgmt-policy"
  role   = aws_iam_role.case_management.id
  policy = data.aws_iam_policy_document.case_management_policy.json
}

data "archive_file" "case_management" {
  type        = "zip"
  source_dir  = local.case_management_source_path
  output_path = "${path.module}/artifacts/case_management.zip"
  excludes    = ["__pycache__", "*.pyc", "tool_spec.json"]
}

# nosemgrep: aws-lambda-x-ray-tracing-not-active
resource "aws_lambda_function" "case_management" {
  function_name    = "${var.stack_name_base}-case-mgmt"
  role             = aws_iam_role.case_management.arn
  handler          = "case_management_lambda.handler"
  runtime          = "python3.13"
  timeout          = 30
  filename         = data.archive_file.case_management.output_path
  source_code_hash = data.archive_file.case_management.output_base64sha256
  layers           = [aws_lambda_layer_version.shared_types.arn]

  environment {
    variables = { STACK_NAME_BASE = var.stack_name_base }
  }

  depends_on = [aws_cloudwatch_log_group.case_management]
}

# ── Notification Lambda ──────────────────────────────────────────────────────

# nosemgrep: aws-cloudwatch-log-group-unencrypted
resource "aws_cloudwatch_log_group" "notification" {
  name              = "/aws/lambda/${var.stack_name_base}-notification"
  retention_in_days = local.log_retention_days
}

resource "aws_iam_role" "notification" {
  name               = "${var.stack_name_base}-notification-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

data "aws_iam_policy_document" "notification_policy" {
  statement {
    sid       = "Logs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.notification.arn}:*"]
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
  statement {
    sid       = "SES"
    effect    = "Allow"
    actions   = ["ses:SendEmail", "ses:SendRawEmail"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "notification" {
  name   = "${var.stack_name_base}-notification-policy"
  role   = aws_iam_role.notification.id
  policy = data.aws_iam_policy_document.notification_policy.json
}

data "archive_file" "notification" {
  type        = "zip"
  source_dir  = local.notification_source_path
  output_path = "${path.module}/artifacts/notification.zip"
  excludes    = ["__pycache__", "*.pyc", "tool_spec.json"]
}

# nosemgrep: aws-lambda-x-ray-tracing-not-active
resource "aws_lambda_function" "notification" {
  function_name    = "${var.stack_name_base}-notification"
  role             = aws_iam_role.notification.arn
  handler          = "notification_lambda.handler"
  runtime          = "python3.13"
  timeout          = 30
  filename         = data.archive_file.notification.output_path
  source_code_hash = data.archive_file.notification.output_base64sha256
  layers           = [aws_lambda_layer_version.shared_types.arn]

  depends_on = [aws_cloudwatch_log_group.notification]
}

# ── Knowledge Base Lambda ────────────────────────────────────────────────────

# nosemgrep: aws-cloudwatch-log-group-unencrypted
resource "aws_cloudwatch_log_group" "knowledge_base" {
  name              = "/aws/lambda/${var.stack_name_base}-kb-search"
  retention_in_days = local.log_retention_days
}

resource "aws_iam_role" "knowledge_base" {
  name               = "${var.stack_name_base}-kb-search-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

data "aws_iam_policy_document" "knowledge_base_policy" {
  statement {
    sid       = "Logs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.knowledge_base.arn}:*"]
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
  statement {
    sid       = "BedrockRetrieve"
    effect    = "Allow"
    actions   = ["bedrock:Retrieve"]
    resources = ["arn:aws:bedrock:${local.region}:${local.account_id}:knowledge-base/*"]
  }
  statement {
    sid     = "S3Read"
    effect  = "Allow"
    actions = ["s3:GetObject", "s3:ListBucket"]
    resources = [
      aws_s3_bucket.sops.arn, "${aws_s3_bucket.sops.arn}/*",
      aws_s3_bucket.api_docs.arn, "${aws_s3_bucket.api_docs.arn}/*"
    ]
  }
}

resource "aws_iam_role_policy" "knowledge_base" {
  name   = "${var.stack_name_base}-kb-search-policy"
  role   = aws_iam_role.knowledge_base.id
  policy = data.aws_iam_policy_document.knowledge_base_policy.json
}

data "archive_file" "knowledge_base" {
  type        = "zip"
  source_dir  = local.knowledge_base_source_path
  output_path = "${path.module}/artifacts/knowledge_base.zip"
  excludes    = ["__pycache__", "*.pyc", "tool_spec.json"]
}

# nosemgrep: aws-lambda-x-ray-tracing-not-active
resource "aws_lambda_function" "knowledge_base" {
  function_name    = "${var.stack_name_base}-kb-search"
  role             = aws_iam_role.knowledge_base.arn
  handler          = "knowledge_base_lambda.handler"
  runtime          = "python3.13"
  timeout          = 30
  filename         = data.archive_file.knowledge_base.output_path
  source_code_hash = data.archive_file.knowledge_base.output_base64sha256

  environment {
    variables = merge(
      { STACK_NAME_BASE = var.stack_name_base },
      length(var.contacts) > 0 ? { CONTACTS_JSON = jsonencode(var.contacts) } : {}
    )
  }

  depends_on = [aws_cloudwatch_log_group.knowledge_base]
}
