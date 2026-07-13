# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
# =============================================================================
# =============================================================================

resource "aws_iam_role" "autonomy_api" {
  name               = "${var.stack_name_base}-autonomy-api-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

data "aws_iam_policy_document" "autonomy_api_policy" {
  statement {
    sid       = "Logs"
    effect    = "Allow"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:${local.region}:${local.account_id}:log-group:/aws/lambda/${var.stack_name_base}-autonomy-api:*"]
  }
  statement {
    sid       = "SSM"
    effect    = "Allow"
    actions   = ["ssm:GetParameter", "ssm:PutParameter"]
    resources = ["arn:aws:ssm:${local.region}:${local.account_id}:parameter/${var.stack_name_base}/autonomy/*"]
  }
  statement {
    sid       = "SQSSend"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.agent_queue.arn]
  }
}

resource "aws_iam_role_policy" "autonomy_api" {
  name   = "${var.stack_name_base}-autonomy-api-policy"
  role   = aws_iam_role.autonomy_api.id
  policy = data.aws_iam_policy_document.autonomy_api_policy.json
}

data "archive_file" "autonomy_api" {
  type        = "zip"
  source_dir  = local.autonomy_api_source_path
  output_path = "${path.module}/artifacts/autonomy_api.zip"
  excludes    = ["__pycache__", "*.pyc"]
}

resource "aws_lambda_function" "autonomy_api" {
  function_name    = "${var.stack_name_base}-autonomy-api"
  role             = aws_iam_role.autonomy_api.arn
  handler          = "index.handler"
  runtime          = "python3.13"
  timeout          = 10
  filename         = data.archive_file.autonomy_api.output_path
  source_code_hash = data.archive_file.autonomy_api.output_base64sha256

  environment {
    variables = {
      STACK_NAME_BASE = var.stack_name_base
      AGENT_QUEUE_URL = aws_sqs_queue.agent_queue.url
    }
  }
}

resource "aws_iam_role" "cases_api" {
  name               = "${var.stack_name_base}-cases-api-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

data "aws_iam_policy_document" "cases_api_policy" {
  statement {
    sid       = "Logs"
    effect    = "Allow"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:${local.region}:${local.account_id}:log-group:/aws/lambda/${var.stack_name_base}-cases-api:*"]
  }
  statement {
    sid    = "DynamoDB"
    effect = "Allow"
    actions = [
      "dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem",
      "dynamodb:Query", "dynamodb:Scan"
    ]
    resources = [aws_dynamodb_table.cases.arn, "${aws_dynamodb_table.cases.arn}/index/*"]
  }
}

resource "aws_iam_role_policy" "cases_api" {
  name   = "${var.stack_name_base}-cases-api-policy"
  role   = aws_iam_role.cases_api.id
  policy = data.aws_iam_policy_document.cases_api_policy.json
}

data "archive_file" "cases_api" {
  type        = "zip"
  source_dir  = local.cases_api_source_path
  output_path = "${path.module}/artifacts/cases_api.zip"
  excludes    = ["__pycache__", "*.pyc"]
}

resource "aws_lambda_function" "cases_api" {
  function_name    = "${var.stack_name_base}-cases-api"
  role             = aws_iam_role.cases_api.arn
  handler          = "index.handler"
  runtime          = "python3.13"
  timeout          = 15
  filename         = data.archive_file.cases_api.output_path
  source_code_hash = data.archive_file.cases_api.output_base64sha256
  layers           = [aws_lambda_layer_version.shared_types.arn]

  environment {
    variables = {
      TABLE_NAME           = aws_dynamodb_table.cases.name
      CORS_ALLOWED_ORIGINS = local.cors_origins
    }
  }
}

resource "aws_iam_role" "tickets_api" {
  count              = var.demo_enabled ? 1 : 0
  name               = "${var.stack_name_base}-tickets-api-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

data "aws_iam_policy_document" "tickets_api_policy" {
  count = var.demo_enabled ? 1 : 0
  statement {
    sid       = "Logs"
    effect    = "Allow"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:${local.region}:${local.account_id}:log-group:/aws/lambda/${var.stack_name_base}-tickets:*"]
  }
  statement {
    sid    = "DynamoDB"
    effect = "Allow"
    actions = [
      "dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem",
      "dynamodb:Query", "dynamodb:Scan"
    ]
    resources = [aws_dynamodb_table.tickets[0].arn, "${aws_dynamodb_table.tickets[0].arn}/index/*"]
  }
  # The /tickets/{id}/action route enqueues the linked case to resume the agent.
  statement {
    sid       = "SQSSend"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.agent_queue.arn]
  }
}

resource "aws_iam_role_policy" "tickets_api" {
  count  = var.demo_enabled ? 1 : 0
  name   = "${var.stack_name_base}-tickets-api-policy"
  role   = aws_iam_role.tickets_api[0].id
  policy = data.aws_iam_policy_document.tickets_api_policy[0].json
}

data "archive_file" "tickets_api" {
  count       = var.demo_enabled ? 1 : 0
  type        = "zip"
  source_dir  = local.tickets_api_source_path
  output_path = "${path.module}/artifacts/tickets_api.zip"
  excludes    = ["__pycache__", "*.pyc"]
}

resource "aws_lambda_function" "tickets_api" {
  count            = var.demo_enabled ? 1 : 0
  function_name    = "${var.stack_name_base}-tickets"
  role             = aws_iam_role.tickets_api[0].arn
  handler          = "index.handler"
  runtime          = "python3.13"
  timeout          = 15
  filename         = data.archive_file.tickets_api[0].output_path
  source_code_hash = data.archive_file.tickets_api[0].output_base64sha256
  layers           = [aws_lambda_layer_version.shared_types.arn]

  environment {
    variables = {
      TICKETS_TABLE_NAME   = aws_dynamodb_table.tickets[0].name
      AGENT_QUEUE_URL      = aws_sqs_queue.agent_queue.url
      CORS_ALLOWED_ORIGINS = local.cors_origins
    }
  }
}
