# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# =============================================================================
# ZIP Deployment Resources (conditional on deployment_type = "zip")
# Maps to: backend-stack.ts ZIP DEPLOYMENT section
# =============================================================================

# -----------------------------------------------------------------------------
# S3 Bucket for Agent Code
# -----------------------------------------------------------------------------

# Resources for the zip deployment path (deployment_type = "zip"); all conditional on local.is_zip.

# nosemgrep: aws-s3-bucket-versioning-not-enabled — build artifact bucket
resource "aws_s3_bucket" "agent_code" {
  count = local.is_zip ? 1 : 0

  bucket        = "${var.stack_name_base}-agent-code-${local.account_id}"
  force_destroy = true

}

resource "aws_s3_bucket_versioning" "agent_code" {
  count = local.is_zip ? 1 : 0

  bucket = aws_s3_bucket.agent_code[0].id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "agent_code" {
  count = local.is_zip ? 1 : 0

  bucket = aws_s3_bucket.agent_code[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "agent_code" {
  count = local.is_zip ? 1 : 0

  bucket = aws_s3_bucket.agent_code[0].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
# -----------------------------------------------------------------------------
# IAM Role for Packager Lambda
# -----------------------------------------------------------------------------


data "aws_iam_policy_document" "zip_packager_assume_role" {
  count = local.is_zip ? 1 : 0

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "zip_packager" {
  count = local.is_zip ? 1 : 0

  name               = "${var.stack_name_base}-zip-packager-cr-role"
  assume_role_policy = data.aws_iam_policy_document.zip_packager_assume_role[0].json

}

data "aws_iam_policy_document" "zip_packager_policy" {
  count = local.is_zip ? 1 : 0

  # CloudWatch Logs
  statement {
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]
    resources = ["arn:aws:logs:${local.region}:${local.account_id}:log-group:/aws/lambda/${var.stack_name_base}-zip-packager-cr:*"]
  }

  # S3 access to agent code bucket
  statement {
    effect = "Allow"
    actions = [
      "s3:PutObject",
      "s3:GetObject",
      "s3:ListBucket"
    ]
    resources = [
      aws_s3_bucket.agent_code[0].arn,
      "${aws_s3_bucket.agent_code[0].arn}/*"
    ]
  }
}

resource "aws_iam_role_policy" "zip_packager" {
  count = local.is_zip ? 1 : 0

  name   = "${var.stack_name_base}-zip-packager-cr-policy"
  role   = aws_iam_role.zip_packager[0].id
  policy = data.aws_iam_policy_document.zip_packager_policy[0].json
}

# -----------------------------------------------------------------------------
# CloudWatch Log Group for Packager Lambda
# -----------------------------------------------------------------------------

# nosemgrep: aws-cloudwatch-log-group-unencrypted, missing-cloudwatch-log-group-kms-key — quick-start uses AWS-managed keys
resource "aws_cloudwatch_log_group" "zip_packager" {
  count = local.is_zip ? 1 : 0

  name              = "/aws/lambda/${var.stack_name_base}-zip-packager-cr"
  retention_in_days = local.log_retention_days

}
# -----------------------------------------------------------------------------
# Packager Lambda Function
# -----------------------------------------------------------------------------


data "archive_file" "zip_packager" {
  count = local.is_zip ? 1 : 0

  type        = "zip"
  source_file = "${local.zip_packager_lambda_source_path}/index.py"
  output_path = "${path.module}/artifacts/zip_packager_lambda.zip"
}

# nosemgrep: aws-lambda-x-ray-tracing-not-active — production hardening step
resource "aws_lambda_function" "zip_packager" {
  count = local.is_zip ? 1 : 0

  function_name = "${var.stack_name_base}-zip-packager-cr"
  role          = aws_iam_role.zip_packager[0].arn
  handler       = "index.handler"
  runtime       = "python3.12"
  architectures = ["arm64"]
  timeout       = 600
  memory_size   = 1024

  filename         = data.archive_file.zip_packager[0].output_path
  source_code_hash = data.archive_file.zip_packager[0].output_base64sha256

  ephemeral_storage {
    size = 2048
  }


  depends_on = [
    aws_cloudwatch_log_group.zip_packager[0],
    aws_iam_role_policy.zip_packager[0]
  ]
}

# -----------------------------------------------------------------------------
# Invoke Packager Lambda via null_resource
# Constructs payload locally (reads .py files, base64 encodes, parses requirements)
# then invokes the Lambda to package and upload to S3
# -----------------------------------------------------------------------------

# Always created (no count) so replace_triggered_by can reference it in both modes;
# the docker-mode value is static ("docker"), so it never triggers a replacement.
resource "terraform_data" "agent_code_hash" {
  input = local.is_zip ? sha256(join("", concat(
    [for f in fileset(local.pattern_dir, "**/*.py") : filesha256("${local.pattern_dir}/${f}")],
    [filesha256("${local.pattern_dir}/requirements.txt")],
    [for f in fileset("${local.project_root}/tools", "**/*.py") : filesha256("${local.project_root}/tools/${f}")],
    [for f in fileset("${local.pattern_dir}/utils", "**/*.py") : filesha256("${local.pattern_dir}/utils/${f}")],
  ))) : "docker"
}

resource "null_resource" "invoke_zip_packager" {
  count = local.is_zip ? 1 : 0

  triggers = {
    content_hash = terraform_data.agent_code_hash.output
    lambda_arn   = aws_lambda_function.zip_packager[0].arn
    bucket_name  = aws_s3_bucket.agent_code[0].id
  }

  provisioner "local-exec" {
    interpreter = ["bash", "-c"]
    command     = <<-EOT
      set -e

      PATTERN_DIR="${local.pattern_dir}"
      PROJECT_ROOT="${local.project_root}"
      BUCKET_NAME="${aws_s3_bucket.agent_code[0].id}"
      FUNCTION_NAME="${aws_lambda_function.zip_packager[0].function_name}"
      REGION="${local.region}"

      AGENT_CODE="{"

      FIRST=true
      for f in "$PATTERN_DIR"/*.py; do
        [ -f "$f" ] || continue
        BASENAME=$(basename "$f")
        B64=$(base64 < "$f" | tr -d '\n')
        if [ "$FIRST" = true ]; then FIRST=false; else AGENT_CODE+=","; fi
        AGENT_CODE+="\"$BASENAME\":\"$B64\""
      done

      if [ -d "$PATTERN_DIR/tools" ]; then
        for f in $(find "$PATTERN_DIR/tools" -name "*.py" -type f); do
          REL=$(python3 -c "import os; print(os.path.relpath('$f', '$PATTERN_DIR'))")
          B64=$(base64 < "$f" | tr -d '\n')
          AGENT_CODE+=",\"$REL\":\"$B64\""
        done
      fi

      if [ -d "$PROJECT_ROOT/tools" ]; then
        for f in $(find "$PROJECT_ROOT/tools" -name "*.py" -type f); do
          REL=$(python3 -c "import os; print(os.path.relpath('$f', '$PROJECT_ROOT'))")
          B64=$(base64 < "$f" | tr -d '\n')
          AGENT_CODE+=",\"$REL\":\"$B64\""
        done
      fi

      # Packaged as utils/ to match the Docker layout (COPY agentcore/agent/utils/ utils/)
      if [ -d "$PATTERN_DIR/utils" ]; then
        for f in $(find "$PATTERN_DIR/utils" -name "*.py" -type f); do
          REL=$(python3 -c "import os; print(os.path.relpath('$f', '$PATTERN_DIR'))")
          B64=$(base64 < "$f" | tr -d '\n')
          AGENT_CODE+=",\"$REL\":\"$B64\""
        done
      fi

      AGENT_CODE+="}"

      REQUIREMENTS=$(python3 -c "
import json
reqs = []
with open('$PATTERN_DIR/requirements.txt') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#'):
            reqs.append(line)
print(json.dumps(reqs))
      ")

      PAYLOAD=$(python3 -c "
import json, sys
agent_code = json.loads(sys.argv[1])
requirements = json.loads(sys.argv[2])
payload = {
    'bucket_name': sys.argv[3],
    'object_key': 'deployment_package.zip',
    'requirements': requirements,
    'agent_code': agent_code,
}
print(json.dumps(payload))
      " "$AGENT_CODE" "$REQUIREMENTS" "$BUCKET_NAME")

      # Write payload to temp file (avoids CLI length limits)
      PAYLOAD_FILE=$(mktemp)
      echo "$PAYLOAD" > "$PAYLOAD_FILE"

      echo "Invoking zip packager Lambda: $FUNCTION_NAME"
      RESPONSE_FILE=$(mktemp)
      aws lambda invoke \
        --function-name "$FUNCTION_NAME" \
        --region "$REGION" \
        --payload "fileb://$PAYLOAD_FILE" \
        --cli-read-timeout 600 \
        "$RESPONSE_FILE" > /dev/null

      STATUS=$(python3 -c "import json; r=json.load(open('$RESPONSE_FILE')); print(r.get('status','UNKNOWN'))")
      if [ "$STATUS" != "SUCCESS" ]; then
        ERROR=$(python3 -c "import json; r=json.load(open('$RESPONSE_FILE')); print(r.get('error','Unknown error'))")
        echo "ERROR: Zip packager failed: $ERROR" >&2
        rm -f "$PAYLOAD_FILE" "$RESPONSE_FILE"
        exit 1
      fi

      S3_URI=$(python3 -c "import json; r=json.load(open('$RESPONSE_FILE')); print(r.get('s3_uri',''))")
      echo "SUCCESS: Agent code packaged and uploaded to $S3_URI"

      rm -f "$PAYLOAD_FILE" "$RESPONSE_FILE"
    EOT
  }

  depends_on = [
    aws_lambda_function.zip_packager[0],
    aws_s3_bucket.agent_code[0],
    aws_iam_role_policy.zip_packager[0]
  ]
}
