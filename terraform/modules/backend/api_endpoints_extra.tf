# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# =============================================================================
# The /tickets/{id}/action route is served by the tickets_api Lambda
# (api_endpoints.tf) — path-dispatched in lambdas/demo_tickets/index.py.
# =============================================================================

# nosemgrep: aws-cloudwatch-log-group-unencrypted
resource "aws_cloudwatch_log_group" "observability_api" {
  name              = "/aws/lambda/${var.stack_name_base}-observability-api"
  retention_in_days = local.log_retention_days
}

resource "aws_iam_role" "observability_api" {
  name               = "${var.stack_name_base}-observability-api-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

data "aws_iam_policy_document" "observability_api_policy" {
  statement {
    sid       = "Logs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.observability_api.arn}:*"]
  }
  statement {
    sid       = "CloudWatch"
    effect    = "Allow"
    actions   = ["cloudwatch:GetMetricStatistics", "cloudwatch:DescribeAlarms"]
    resources = ["*"]
  }
  statement {
    sid       = "SQS"
    effect    = "Allow"
    actions   = ["sqs:GetQueueAttributes"]
    resources = ["arn:aws:sqs:${local.region}:${local.account_id}:${var.stack_name_base}-*"]
  }
  statement {
    sid       = "DynamoDBRead"
    effect    = "Allow"
    actions   = ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan"]
    resources = [aws_dynamodb_table.cases.arn, "${aws_dynamodb_table.cases.arn}/index/*"]
  }
}

resource "aws_iam_role_policy" "observability_api" {
  name   = "${var.stack_name_base}-observability-api-policy"
  role   = aws_iam_role.observability_api.id
  policy = data.aws_iam_policy_document.observability_api_policy.json
}

data "archive_file" "observability_api" {
  type        = "zip"
  source_dir  = "${path.module}/../../../lambdas/observability_api"
  output_path = "${path.module}/artifacts/observability_api.zip"
  excludes    = ["__pycache__", "*.pyc"]
}

resource "aws_lambda_function" "observability_api" {
  function_name    = "${var.stack_name_base}-observability-api"
  role             = aws_iam_role.observability_api.arn
  handler          = "index.handler"
  runtime          = "python3.13"
  timeout          = 30
  filename         = data.archive_file.observability_api.output_path
  source_code_hash = data.archive_file.observability_api.output_base64sha256

  # Needed for the case_key codec — trace records are labelled with a canonical
  # case identity the UI can link on.
  layers = [aws_lambda_layer_version.shared_types.arn]

  environment {
    variables = {
      METRICS_NAMESPACE    = "ERPAgent"
      STACK_NAME_BASE      = var.stack_name_base
      AGENT_QUEUE_URL      = aws_sqs_queue.agent_queue.url
      AGENT_DLQ_URL        = "https://sqs.${local.region}.amazonaws.com/${local.account_id}/${aws_sqs_queue.agent_dlq.name}"
      CORS_ALLOWED_ORIGINS = local.cors_origins
      TABLE_NAME           = aws_dynamodb_table.cases.name
    }
  }

  depends_on = [aws_cloudwatch_log_group.observability_api]
}
