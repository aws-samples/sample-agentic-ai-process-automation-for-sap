# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# =============================================================================
# Exemplar Builder Lambda (daily: cases → exemplar files)
#
# SAP $metadata discovery + OData specs come from the external AWS-for-SAP
# MCP server (get_metadata / find_sap_services) — no metadata scanner Lambda
# or OData-specs bucket needed here.
# =============================================================================

# ── Exemplar Builder ─────────────────────────────────────────────────────────

# nosemgrep: aws-cloudwatch-log-group-unencrypted
resource "aws_cloudwatch_log_group" "exemplar_builder" {
  name              = "/aws/lambda/${var.stack_name_base}-exemplar-builder"
  retention_in_days = local.log_retention_days
}

resource "aws_iam_role" "exemplar_builder" {
  name               = "${var.stack_name_base}-exemplar-builder-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

data "aws_iam_policy_document" "exemplar_builder_policy" {
  statement {
    sid       = "Logs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.exemplar_builder.arn}:*"]
  }
  statement {
    sid       = "DynamoDBRead"
    effect    = "Allow"
    actions   = ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan"]
    resources = [aws_dynamodb_table.cases.arn, "${aws_dynamodb_table.cases.arn}/index/*"]
  }
  statement {
    sid       = "S3Write"
    effect    = "Allow"
    actions   = ["s3:PutObject", "s3:GetObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.sops.arn, "${aws_s3_bucket.sops.arn}/*"]
  }
  statement {
    sid       = "BedrockInvoke"
    effect    = "Allow"
    actions   = ["bedrock:InvokeModel"]
    resources = ["arn:aws:bedrock:${local.region}::foundation-model/*"]
  }
}

resource "aws_iam_role_policy" "exemplar_builder" {
  name   = "${var.stack_name_base}-exemplar-builder-policy"
  role   = aws_iam_role.exemplar_builder.id
  policy = data.aws_iam_policy_document.exemplar_builder_policy.json
}

resource "null_resource" "exemplar_builder_build" {
  triggers = {
    source_hash = sha256(join("", [for f in fileset(local.exemplar_builder_source_path, "*.py") : filesha256("${local.exemplar_builder_source_path}/${f}")]))
    reqs_hash   = fileexists("${local.exemplar_builder_source_path}/requirements.txt") ? filesha256("${local.exemplar_builder_source_path}/requirements.txt") : ""
  }
  provisioner "local-exec" {
    command = <<-EOT
      set -e
      BUILD_DIR="${path.module}/artifacts/exemplar_builder_build"
      rm -rf "$BUILD_DIR" && mkdir -p "$BUILD_DIR"
      cp ${local.exemplar_builder_source_path}/*.py "$BUILD_DIR/"
      if [ -f "${local.exemplar_builder_source_path}/requirements.txt" ]; then
        python3 -m pip install -r "${local.exemplar_builder_source_path}/requirements.txt" -t "$BUILD_DIR/" --quiet --upgrade
      fi
    EOT
  }
}

data "archive_file" "exemplar_builder" {
  type        = "zip"
  source_dir  = "${path.module}/artifacts/exemplar_builder_build"
  output_path = "${path.module}/artifacts/exemplar_builder.zip"
  excludes    = ["__pycache__", "*.pyc", "*.dist-info"]
  depends_on  = [null_resource.exemplar_builder_build]
}

# nosemgrep: aws-lambda-x-ray-tracing-not-active
resource "aws_lambda_function" "exemplar_builder" {
  function_name    = "${var.stack_name_base}-exemplar-builder"
  role             = aws_iam_role.exemplar_builder.arn
  handler          = "index.handler"
  runtime          = "python3.13"
  architectures    = ["arm64"]
  timeout          = 300
  memory_size      = 512
  filename         = data.archive_file.exemplar_builder.output_path
  source_code_hash = data.archive_file.exemplar_builder.output_base64sha256
  layers           = [aws_lambda_layer_version.shared_types.arn]

  environment {
    variables = {
      CASES_TABLE            = aws_dynamodb_table.cases.name
      SOP_BUCKET             = aws_s3_bucket.sops.bucket
      PROCESS_TYPE_SKILL_MAP = jsonencode(local.process_type_skill_map)
    }
  }

  depends_on = [aws_cloudwatch_log_group.exemplar_builder]
}

resource "aws_cloudwatch_event_rule" "exemplar_builder" {
  name                = "${var.stack_name_base}-exemplar-builder"
  schedule_expression = "rate(1 day)"
  description         = "Daily: generate resolution exemplars from successful cases"
}

resource "aws_cloudwatch_event_target" "exemplar_builder" {
  rule = aws_cloudwatch_event_rule.exemplar_builder.name
  arn  = aws_lambda_function.exemplar_builder.arn
}

resource "aws_lambda_permission" "exemplar_builder_eventbridge" {
  statement_id  = "AllowEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.exemplar_builder.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.exemplar_builder.arn
}
