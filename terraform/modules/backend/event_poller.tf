# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# =============================================================================
# OData Poller Lambda + EventBridge Schedule
# Maps to: backend-stack.ts createEventDrivenPipeline() — poller section
# =============================================================================

# OData Poller Lambda + EventBridge Schedule — mirrors backend-stack.ts

# nosemgrep: aws-cloudwatch-log-group-unencrypted
resource "aws_cloudwatch_log_group" "odata_poller" {
  name              = "/aws/lambda/${var.stack_name_base}-odata-poller"
  retention_in_days = local.log_retention_days
}

resource "aws_iam_role" "odata_poller" {
  name               = "${var.stack_name_base}-odata-poller-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

data "aws_iam_policy_document" "odata_poller_policy" {
  statement {
    sid       = "Logs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.odata_poller.arn}:*"]
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
  # Lambda-in-VPC needs ENI permissions to attach to your subnets. No-op in
  # PUBLIC mode (the vpc_config block below is not emitted).
  dynamic "statement" {
    for_each = var.backend_network_mode == "VPC" ? [1] : []
    content {
      sid    = "VPCNetworkInterfaces"
      effect = "Allow"
      actions = [
        "ec2:CreateNetworkInterface",
        "ec2:DescribeNetworkInterfaces",
        "ec2:DeleteNetworkInterface",
        "ec2:AssignPrivateIpAddresses",
        "ec2:UnassignPrivateIpAddresses",
      ]
      resources = ["*"]
    }
  }
}

resource "aws_iam_role_policy" "odata_poller" {
  name   = "${var.stack_name_base}-odata-poller-policy"
  role   = aws_iam_role.odata_poller.id
  policy = data.aws_iam_policy_document.odata_poller_policy.json
}

resource "null_resource" "odata_poller_build" {
  triggers = {
    source_hash = sha256(join("", [for f in fileset(local.odata_poller_source_path, "*.py") : filesha256("${local.odata_poller_source_path}/${f}")]))
    reqs_hash   = fileexists("${local.odata_poller_source_path}/requirements.txt") ? filesha256("${local.odata_poller_source_path}/requirements.txt") : ""
  }
  provisioner "local-exec" {
    command = <<-EOT
      set -e
      BUILD_DIR="${path.module}/artifacts/odata_poller_build"
      rm -rf "$BUILD_DIR" && mkdir -p "$BUILD_DIR"
      cp ${local.odata_poller_source_path}/*.py "$BUILD_DIR/"
      if [ -f "${local.odata_poller_source_path}/requirements.txt" ]; then
        python3 -m pip install -r "${local.odata_poller_source_path}/requirements.txt" -t "$BUILD_DIR/" --quiet --upgrade
      fi
    EOT
  }
}

data "archive_file" "odata_poller" {
  type        = "zip"
  source_dir  = "${path.module}/artifacts/odata_poller_build"
  output_path = "${path.module}/artifacts/odata_poller.zip"
  excludes    = ["__pycache__", "*.pyc", "*.dist-info"]
  depends_on  = [null_resource.odata_poller_build]
}

# nosemgrep: aws-lambda-x-ray-tracing-not-active
resource "aws_lambda_function" "odata_poller" {
  function_name    = "${var.stack_name_base}-odata-poller"
  role             = aws_iam_role.odata_poller.arn
  handler          = "index.lambda_handler"
  runtime          = "python3.13"
  architectures    = ["arm64"]
  timeout          = 300
  filename         = data.archive_file.odata_poller.output_path
  source_code_hash = data.archive_file.odata_poller.output_base64sha256
  layers           = [aws_lambda_layer_version.sap_auth.arn, aws_lambda_layer_version.shared_types.arn]

  environment {
    variables = {
      AGENT_QUEUE_URL    = aws_sqs_queue.agent_queue.url
      STACK_NAME_BASE    = var.stack_name_base
      CASES_TABLE        = aws_dynamodb_table.cases.name
      SAP_BASE_URL_PARAM = "/${var.stack_name_base}/connectivity/sap-base-url"
      # Demo gate: poller skips example_*.json domains unless demo is enabled.
      DEMO_ENABLED = var.demo_enabled ? "true" : "false"
    }
  }

  # Places the SAP-facing poller in the customer VPC so it can reach a
  # private/on-prem SAP OData endpoint. Not emitted in PUBLIC mode.
  dynamic "vpc_config" {
    for_each = var.backend_network_mode == "VPC" ? [1] : []
    content {
      subnet_ids         = var.backend_vpc_subnet_ids
      security_group_ids = local.effective_security_group_ids
    }
  }

  depends_on = [aws_cloudwatch_log_group.odata_poller]
}

resource "aws_cloudwatch_event_rule" "odata_poller" {
  name                = "${var.stack_name_base}-odata-poller"
  schedule_expression = var.poller_schedule
  description         = "Polls SAP OData for new ERP exceptions"
}

resource "aws_cloudwatch_event_target" "odata_poller" {
  rule = aws_cloudwatch_event_rule.odata_poller.name
  arn  = aws_lambda_function.odata_poller.arn
}

resource "aws_lambda_permission" "odata_poller_eventbridge" {
  statement_id  = "AllowEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.odata_poller.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.odata_poller.arn
}
