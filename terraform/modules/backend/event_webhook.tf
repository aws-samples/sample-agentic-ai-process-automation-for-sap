# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# =============================================================================
# Maps to: backend-stack.ts createEventDrivenPipeline() — webhook section
# =============================================================================

# nosemgrep: aws-cloudwatch-log-group-unencrypted
resource "aws_cloudwatch_log_group" "webhook_processor" {
  name              = "/aws/lambda/${var.stack_name_base}-webhook-processor"
  retention_in_days = local.log_retention_days
}

resource "aws_iam_role" "webhook_processor" {
  name               = "${var.stack_name_base}-webhook-processor-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

data "aws_iam_policy_document" "webhook_processor_policy" {
  statement {
    sid       = "Logs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.webhook_processor.arn}:*"]
  }
  statement {
    sid    = "DynamoDB"
    effect = "Allow"
    actions = [
      "dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem",
      "dynamodb:Query", "dynamodb:Scan"
    ]
    resources = [
      aws_dynamodb_table.cases.arn,
      "${aws_dynamodb_table.cases.arn}/index/*"
    ]
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
    sid       = "SQSSend"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.agent_queue.arn]
  }
}

resource "aws_iam_role_policy" "webhook_processor" {
  name   = "${var.stack_name_base}-webhook-processor-policy"
  role   = aws_iam_role.webhook_processor.id
  policy = data.aws_iam_policy_document.webhook_processor_policy.json
}

resource "null_resource" "webhook_processor_build" {
  triggers = {
    source_hash = sha256(join("", [for f in fileset(local.webhook_processor_source_path, "*.py") : filesha256("${local.webhook_processor_source_path}/${f}")]))
    reqs_hash   = fileexists("${local.webhook_processor_source_path}/requirements.txt") ? filesha256("${local.webhook_processor_source_path}/requirements.txt") : ""
  }
  provisioner "local-exec" {
    command = <<-EOT
      set -e
      BUILD_DIR="${path.module}/artifacts/webhook_processor_build"
      rm -rf "$BUILD_DIR" && mkdir -p "$BUILD_DIR"
      cp ${local.webhook_processor_source_path}/*.py "$BUILD_DIR/"
      if [ -f "${local.webhook_processor_source_path}/requirements.txt" ]; then
        python3 -m pip install -r "${local.webhook_processor_source_path}/requirements.txt" -t "$BUILD_DIR/" --quiet --upgrade
      fi
    EOT
  }
}

data "archive_file" "webhook_processor" {
  type        = "zip"
  source_dir  = "${path.module}/artifacts/webhook_processor_build"
  output_path = "${path.module}/artifacts/webhook_processor.zip"
  excludes    = ["__pycache__", "*.pyc", "*.dist-info"]
  depends_on  = [null_resource.webhook_processor_build]
}

# nosemgrep: aws-lambda-x-ray-tracing-not-active
resource "aws_lambda_function" "webhook_processor" {
  function_name    = "${var.stack_name_base}-webhook-processor"
  role             = aws_iam_role.webhook_processor.arn
  handler          = "index.handler"
  runtime          = "python3.13"
  architectures    = ["arm64"]
  timeout          = 300
  filename         = data.archive_file.webhook_processor.output_path
  source_code_hash = data.archive_file.webhook_processor.output_base64sha256

  environment {
    variables = {
      AGENT_QUEUE_URL = aws_sqs_queue.agent_queue.url
      CASES_TABLE     = aws_dynamodb_table.cases.name
      STACK_NAME_BASE = var.stack_name_base
    }
  }

  depends_on = [aws_cloudwatch_log_group.webhook_processor]
}

resource "aws_lambda_function_url" "webhook_processor" {
  function_name      = aws_lambda_function.webhook_processor.function_name
  authorization_type = "NONE"
}
