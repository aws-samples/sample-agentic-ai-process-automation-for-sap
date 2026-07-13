# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# =============================================================================
# Demo Infrastructure — mirror of cdk/lib/demo-stack.ts
#
# Single opt-in gate (var.demo_enabled). Creates:
#   - Test Data Lambda for PO accrual / AP three-way-match scenarios
#   - A dedicated /demo/* API Gateway
#
# Safe to delete: set demo_enabled = false (everything here is count-gated) and
# delete lambdas/demo_*, agentcore/gateway/tools/demo_*.
# =============================================================================

# ─── Test Data Lambda (PO accruals + AP three-way match) ────────────────────
# Needs `requests` — built via pip (mirror of the odata_poller build pattern).

resource "null_resource" "demo_test_data_build" {
  count = var.demo_enabled ? 1 : 0
  triggers = {
    source_hash = sha256(join("", [for f in fileset("${path.module}/../../../lambdas/demo_test_data", "*.py") : filesha256("${path.module}/../../../lambdas/demo_test_data/${f}")]))
    reqs_hash   = fileexists("${path.module}/../../../lambdas/demo_test_data/requirements.txt") ? filesha256("${path.module}/../../../lambdas/demo_test_data/requirements.txt") : ""
  }
  provisioner "local-exec" {
    command = <<-EOT
      set -e
      SRC="${path.module}/../../../lambdas/demo_test_data"
      BUILD_DIR="${path.module}/artifacts/demo_test_data_build"
      rm -rf "$BUILD_DIR" && mkdir -p "$BUILD_DIR"
      cp $SRC/*.py "$BUILD_DIR/"
      if [ -f "$SRC/requirements.txt" ]; then
        python3 -m pip install -r "$SRC/requirements.txt" -t "$BUILD_DIR/" --quiet --upgrade
      fi
    EOT
  }
}

data "archive_file" "demo_test_data" {
  count       = var.demo_enabled ? 1 : 0
  type        = "zip"
  source_dir  = "${path.module}/artifacts/demo_test_data_build"
  output_path = "${path.module}/artifacts/demo_test_data.zip"
  excludes    = ["__pycache__", "*.pyc", "*.dist-info"]
  depends_on  = [null_resource.demo_test_data_build]
}

# nosemgrep: aws-cloudwatch-log-group-unencrypted
resource "aws_cloudwatch_log_group" "demo_test_data" {
  count             = var.demo_enabled ? 1 : 0
  name              = "/aws/lambda/${var.stack_name_base}-test-data"
  retention_in_days = local.log_retention_days
}

resource "aws_iam_role" "demo_test_data" {
  count              = var.demo_enabled ? 1 : 0
  name               = "${var.stack_name_base}-test-data-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

data "aws_iam_policy_document" "demo_test_data_policy" {
  count = var.demo_enabled ? 1 : 0
  statement {
    sid       = "Logs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.demo_test_data[0].arn}:*"]
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

resource "aws_iam_role_policy" "demo_test_data" {
  count  = var.demo_enabled ? 1 : 0
  name   = "${var.stack_name_base}-test-data-policy"
  role   = aws_iam_role.demo_test_data[0].id
  policy = data.aws_iam_policy_document.demo_test_data_policy[0].json
}

# nosemgrep: aws-lambda-x-ray-tracing-not-active
resource "aws_lambda_function" "demo_test_data" {
  count            = var.demo_enabled ? 1 : 0
  function_name    = "${var.stack_name_base}-test-data"
  role             = aws_iam_role.demo_test_data[0].arn
  handler          = "index.handler"
  runtime          = "python3.13"
  architectures    = ["arm64"]
  timeout          = 120
  filename         = data.archive_file.demo_test_data[0].output_path
  source_code_hash = data.archive_file.demo_test_data[0].output_base64sha256

  environment {
    variables = {
      CORS_ALLOWED_ORIGINS = local.cors_origins
      STACK_NAME_BASE      = var.stack_name_base
    }
  }

  depends_on = [aws_cloudwatch_log_group.demo_test_data]
}

# ─── Demo API Gateway ────────────────────────────────────────────────────────
# Dedicated REST API with /demo/test-data/{cases,ap-cases}.

resource "aws_api_gateway_rest_api" "demo" {
  count       = var.demo_enabled ? 1 : 0
  name        = "${var.stack_name_base}-demo-api"
  description = "Demo / test data API — removable"
}

resource "aws_api_gateway_resource" "demo_root" {
  count       = var.demo_enabled ? 1 : 0
  rest_api_id = aws_api_gateway_rest_api.demo[0].id
  parent_id   = aws_api_gateway_rest_api.demo[0].root_resource_id
  path_part   = "demo"
}

resource "aws_api_gateway_resource" "demo_test_data" {
  count       = var.demo_enabled ? 1 : 0
  rest_api_id = aws_api_gateway_rest_api.demo[0].id
  parent_id   = aws_api_gateway_resource.demo_root[0].id
  path_part   = "test-data"
}

resource "aws_api_gateway_resource" "demo_test_data_cases" {
  count       = var.demo_enabled ? 1 : 0
  rest_api_id = aws_api_gateway_rest_api.demo[0].id
  parent_id   = aws_api_gateway_resource.demo_test_data[0].id
  path_part   = "cases"
}

resource "aws_api_gateway_resource" "demo_test_data_ap_cases" {
  count       = var.demo_enabled ? 1 : 0
  rest_api_id = aws_api_gateway_rest_api.demo[0].id
  parent_id   = aws_api_gateway_resource.demo_test_data[0].id
  path_part   = "ap-cases"
}

locals {
  # No Cognito auth on these routes — demo API only.
  demo_routes = var.demo_enabled ? {
    cases    = { resource_id = aws_api_gateway_resource.demo_test_data_cases[0].id, fn = aws_lambda_function.demo_test_data[0] }
    ap_cases = { resource_id = aws_api_gateway_resource.demo_test_data_ap_cases[0].id, fn = aws_lambda_function.demo_test_data[0] }
  } : {}
}

resource "aws_api_gateway_method" "demo" {
  for_each      = local.demo_routes
  rest_api_id   = aws_api_gateway_rest_api.demo[0].id
  resource_id   = each.value.resource_id
  http_method   = "POST"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "demo" {
  for_each                = local.demo_routes
  rest_api_id             = aws_api_gateway_rest_api.demo[0].id
  resource_id             = each.value.resource_id
  http_method             = aws_api_gateway_method.demo[each.key].http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = each.value.fn.invoke_arn
}

resource "aws_lambda_permission" "demo_test_data_api" {
  count         = var.demo_enabled ? 1 : 0
  statement_id  = "AllowDemoAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.demo_test_data[0].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.demo[0].execution_arn}/*/*"
}

resource "aws_api_gateway_deployment" "demo" {
  count       = var.demo_enabled ? 1 : 0
  rest_api_id = aws_api_gateway_rest_api.demo[0].id

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_resource.demo_test_data_cases[0].id,
      aws_api_gateway_resource.demo_test_data_ap_cases[0].id,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }

  depends_on = [aws_api_gateway_integration.demo]
}

resource "aws_api_gateway_stage" "demo" {
  count         = var.demo_enabled ? 1 : 0
  stage_name    = "prod"
  rest_api_id   = aws_api_gateway_rest_api.demo[0].id
  deployment_id = aws_api_gateway_deployment.demo[0].id
}

resource "aws_ssm_parameter" "demo_api_url" {
  count = var.demo_enabled ? 1 : 0
  name  = "${local.ssm_parameter_prefix}/demo/api-url"
  type  = "String"
  value = aws_api_gateway_stage.demo[0].invoke_url
}
