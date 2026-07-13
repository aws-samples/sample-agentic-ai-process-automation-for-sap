# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
# =============================================================================
# SAP Data Resources
# Maps to: backend-stack.ts createSapDataResources() + createODataSpecsInfra()
#          + createSapSecrets() + createTicketsTable()
# =============================================================================

# -----------------------------------------------------------------------------
# DynamoDB — Cases Table
# -----------------------------------------------------------------------------


# nosemgrep: aws-dynamodb-table-unencrypted
resource "aws_dynamodb_table" "cases" {
  name         = "${var.stack_name_base}-cases"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "document_number"
  range_key    = "item_id"

  attribute {
    name = "document_number"
    type = "S"
  }
  attribute {
    name = "item_id"
    type = "S"
  }
  attribute {
    name = "status"
    type = "S"
  }
  attribute {
    name = "domain"
    type = "S"
  }

  global_secondary_index {
    name            = "status-index"
    hash_key        = "status"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "domain-status-index"
    hash_key        = "domain"
    range_key       = "status"
    projection_type = "ALL"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  deletion_protection_enabled = false
}

# -----------------------------------------------------------------------------
# DynamoDB — Tickets Table (demo supervised-approval)
# -----------------------------------------------------------------------------

# nosemgrep: aws-dynamodb-table-unencrypted
resource "aws_dynamodb_table" "tickets" {
  count        = var.demo_enabled ? 1 : 0
  name         = "${var.stack_name_base}-tickets"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "ticket_id"

  attribute {
    name = "ticket_id"
    type = "S"
  }
  attribute {
    name = "status"
    type = "S"
  }
  attribute {
    name = "created_at"
    type = "S"
  }
  attribute {
    name = "case_id"
    type = "S"
  }

  global_secondary_index {
    name            = "status-created-index"
    hash_key        = "status"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "case-id-index"
    hash_key        = "case_id"
    projection_type = "ALL"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  deletion_protection_enabled = false
}

# -----------------------------------------------------------------------------
# S3 — SOPs Bucket (hardened)
# -----------------------------------------------------------------------------

resource "aws_s3_bucket" "sops" {
  bucket        = "${var.stack_name_base}-sops-${local.account_id}"
  force_destroy = true
}

resource "aws_s3_bucket_versioning" "sops" {
  bucket = aws_s3_bucket.sops.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "sops" {
  bucket                  = aws_s3_bucket.sops.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "sops" {
  bucket = aws_s3_bucket.sops.id

  rule {
    id     = "glacier-noncurrent"
    status = "Enabled"
    noncurrent_version_transition {
      noncurrent_days = 30
      storage_class   = "GLACIER"
    }
    noncurrent_version_expiration {
      noncurrent_days = 2555 # ~7 years
    }
  }
}

resource "aws_iam_role" "sop_admin" {
  name               = "${var.stack_name_base}-sop-admin"
  assume_role_policy = data.aws_iam_policy_document.sop_admin_assume.json
  description        = "Role for SOP administrators - only role allowed to write to SOP bucket"
}

data "aws_iam_policy_document" "sop_admin_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${local.account_id}:root"]
    }
  }
}

data "aws_iam_policy_document" "sop_admin_policy" {
  statement {
    effect = "Allow"
    actions = [
      "s3:GetObject", "s3:PutObject", "s3:DeleteObject",
      "s3:ListBucket", "s3:GetBucketLocation"
    ]
    resources = [
      aws_s3_bucket.sops.arn,
      "${aws_s3_bucket.sops.arn}/*",
      aws_s3_bucket.api_docs.arn,
      "${aws_s3_bucket.api_docs.arn}/*"
    ]
  }
}

resource "aws_iam_role_policy" "sop_admin" {
  name   = "${var.stack_name_base}-sop-admin-policy"
  role   = aws_iam_role.sop_admin.id
  policy = data.aws_iam_policy_document.sop_admin_policy.json
}

resource "aws_s3_bucket_policy" "sops" {
  bucket = aws_s3_bucket.sops.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyNonAdminWrites"
      Effect    = "Deny"
      Principal = "*"
      Action    = ["s3:PutObject", "s3:DeleteObject"]
      Resource  = "${aws_s3_bucket.sops.arn}/*"
      Condition = {
        StringNotLike = {
          "aws:PrincipalArn" = aws_iam_role.sop_admin.arn
        }
      }
    }]
  })
}

# -----------------------------------------------------------------------------
# S3 — API Docs Bucket
# -----------------------------------------------------------------------------

resource "aws_s3_bucket" "api_docs" {
  bucket        = "${var.stack_name_base}-api-docs-${local.account_id}"
  force_destroy = true
}

resource "aws_s3_bucket_versioning" "api_docs" {
  bucket = aws_s3_bucket.api_docs.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "api_docs" {
  bucket                  = aws_s3_bucket.api_docs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# -----------------------------------------------------------------------------
# Secrets Manager — SAP Credentials
# -----------------------------------------------------------------------------

# SAP writes and OData metadata go through the external AWS-for-SAP MCP server
# (odata_create/update/delete/function_import, get_metadata) — no SQS queue or
# OData-specs bucket is hosted in this stack.

# nosemgrep: aws-secretsmanager-secret-unencrypted
resource "aws_secretsmanager_secret" "sap_credentials" {
  name        = "${var.stack_name_base}/sap-credentials"
  description = "SAP system credentials (username, password, base_url)"
}

resource "aws_secretsmanager_secret_version" "sap_credentials" {
  secret_id = aws_secretsmanager_secret.sap_credentials.id
  secret_string = jsonencode({
    username = "PLACEHOLDER"
    password = "PLACEHOLDER"
    base_url = var.sap_base_url != null ? var.sap_base_url : "https://sap.example.com"
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}
# -----------------------------------------------------------------------------
# SSM Parameters for SAP Data Resources
# -----------------------------------------------------------------------------


resource "aws_ssm_parameter" "cases_table" {
  name        = "${local.ssm_parameter_prefix}/dynamodb/cases-table"
  type        = "String"
  value       = aws_dynamodb_table.cases.name
  description = "DynamoDB table for ERP exception cases"
}

resource "aws_ssm_parameter" "tickets_table" {
  count       = var.demo_enabled ? 1 : 0
  name        = "${local.ssm_parameter_prefix}/dynamodb/tickets-table"
  type        = "String"
  value       = aws_dynamodb_table.tickets[0].name
  description = "DynamoDB table for tickets (demo)"
}

resource "aws_ssm_parameter" "sops_bucket" {
  name  = "${local.ssm_parameter_prefix}/s3/sops-bucket"
  type  = "String"
  value = aws_s3_bucket.sops.bucket
}

resource "aws_ssm_parameter" "api_docs_bucket" {
  name  = "${local.ssm_parameter_prefix}/s3/api-docs-bucket"
  type  = "String"
  value = aws_s3_bucket.api_docs.bucket
}

resource "aws_ssm_parameter" "sap_credentials_arn" {
  name        = "${local.ssm_parameter_prefix}/secrets/sap-credentials-arn"
  type        = "String"
  value       = aws_secretsmanager_secret.sap_credentials.arn
  description = "SAP credentials secret ARN"
}
