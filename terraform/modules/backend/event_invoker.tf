# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# =============================================================================
# Agent Invoker Lambda (SQS consumer → AgentCore Runtime)
# Maps to: backend-stack.ts createEventDrivenPipeline() — invoker section
# =============================================================================

# Agent Invoker Lambda (SQS consumer → AgentCore Runtime) — mirrors

# nosemgrep: aws-cloudwatch-log-group-unencrypted
resource "aws_cloudwatch_log_group" "agent_invoker" {
  name              = "/aws/lambda/${var.stack_name_base}-agent-invoker"
  retention_in_days = local.log_retention_days
}

resource "aws_iam_role" "agent_invoker" {
  name               = "${var.stack_name_base}-agent-invoker-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

data "aws_iam_policy_document" "agent_invoker_policy" {
  statement {
    sid       = "Logs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.agent_invoker.arn}:*"]
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
    sid       = "S3ReadSOPs"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.sops.arn, "${aws_s3_bucket.sops.arn}/*"]
  }
  statement {
    sid       = "SSM"
    effect    = "Allow"
    actions   = ["ssm:GetParameter", "ssm:GetParameters"]
    resources = ["arn:aws:ssm:${local.region}:${local.account_id}:parameter/${var.stack_name_base}/*"]
  }
  statement {
    sid     = "Secrets"
    effect  = "Allow"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_secretsmanager_secret.sap_credentials.arn,
      aws_secretsmanager_secret.machine_client_secret.arn
    ]
  }
  statement {
    sid    = "SQSConsume"
    effect = "Allow"
    actions = [
      "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"
    ]
    resources = [aws_sqs_queue.agent_queue.arn]
  }
  statement {
    sid       = "AgentCoreInvoke"
    effect    = "Allow"
    actions   = ["bedrock-agentcore:InvokeAgentRuntime"]
    resources = [aws_bedrockagentcore_agent_runtime.main.agent_runtime_arn]
  }
  statement {
    sid       = "CognitoAuth"
    effect    = "Allow"
    actions   = ["cognito-idp:InitiateAuth"]
    resources = [var.user_pool_arn]
  }
}

resource "aws_iam_role_policy" "agent_invoker" {
  name   = "${var.stack_name_base}-agent-invoker-policy"
  role   = aws_iam_role.agent_invoker.id
  policy = data.aws_iam_policy_document.agent_invoker_policy.json
}

resource "null_resource" "agent_invoker_build" {
  triggers = {
    source_hash = sha256(join("", [for f in fileset(local.agent_invoker_source_path, "*.py") : filesha256("${local.agent_invoker_source_path}/${f}")]))
    reqs_hash   = fileexists("${local.agent_invoker_source_path}/requirements.txt") ? filesha256("${local.agent_invoker_source_path}/requirements.txt") : ""
  }
  provisioner "local-exec" {
    command = <<-EOT
      set -e
      BUILD_DIR="${path.module}/artifacts/agent_invoker_build"
      rm -rf "$BUILD_DIR" && mkdir -p "$BUILD_DIR"
      cp ${local.agent_invoker_source_path}/*.py "$BUILD_DIR/"
      if [ -f "${local.agent_invoker_source_path}/requirements.txt" ]; then
        python3 -m pip install -r "${local.agent_invoker_source_path}/requirements.txt" -t "$BUILD_DIR/" --quiet --upgrade
      fi
    EOT
  }
}

data "archive_file" "agent_invoker" {
  type        = "zip"
  source_dir  = "${path.module}/artifacts/agent_invoker_build"
  output_path = "${path.module}/artifacts/agent_invoker.zip"
  excludes    = ["__pycache__", "*.pyc", "*.dist-info"]
  depends_on  = [null_resource.agent_invoker_build]
}

# nosemgrep: aws-lambda-x-ray-tracing-not-active
resource "aws_lambda_function" "agent_invoker" {
  function_name    = "${var.stack_name_base}-agent-invoker"
  role             = aws_iam_role.agent_invoker.arn
  handler          = "index.handler"
  runtime          = "python3.13"
  architectures    = ["arm64"]
  timeout          = 360
  memory_size      = 1024
  filename         = data.archive_file.agent_invoker.output_path
  source_code_hash = data.archive_file.agent_invoker.output_base64sha256

  # Needed for the case_key codec — every status write derives the DynamoDB key
  # from the message's case_id.
  layers = [aws_lambda_layer_version.shared_types.arn]

  environment {
    variables = {
      CASES_TABLE     = aws_dynamodb_table.cases.name
      STACK_NAME_BASE = var.stack_name_base
      SOP_BUCKET      = aws_s3_bucket.sops.bucket
    }
  }

  depends_on = [aws_cloudwatch_log_group.agent_invoker]
}

resource "aws_lambda_event_source_mapping" "agent_invoker" {
  event_source_arn        = aws_sqs_queue.agent_queue.arn
  function_name           = aws_lambda_function.agent_invoker.arn
  batch_size              = 1
  function_response_types = ["ReportBatchItemFailures"]
  enabled                 = true

  scaling_config {
    maximum_concurrency = var.agent_queue_max_concurrency
  }

  # CreateEventSourceMapping validates that the function role can call
  # sqs:ReceiveMessage at create time. Without this the mapping can be created
  # before the inline role policy attaches, failing with InvalidParameterValue
  # ("execution role does not have permissions to call ReceiveMessage on SQS").
  depends_on = [aws_iam_role_policy.agent_invoker]
}
