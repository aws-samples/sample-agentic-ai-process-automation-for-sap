# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# =============================================================================
# Bedrock Knowledge Bases backed by Amazon S3 Vectors
# Maps to: CDK backend-stack.ts createKnowledgeBases()
# =============================================================================

# Mirrors CDK's backend-stack.ts createKnowledgeBases(); keep both in sync.

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.id

  index_name = "bedrock-knowledge-base-default-index"

  kb_definitions = {
    sops = {
      name        = "sops"
      bucket_arn  = var.sops_bucket_arn
      description = "ERP exception SOPs and procedures"
    }
    api_docs = {
      name        = "api-docs"
      bucket_arn  = var.api_docs_bucket_arn
      description = "SAP OData API documentation"
    }
  }
}
# -----------------------------------------------------------------------------
# Shared IAM Role for both Knowledge Bases
# -----------------------------------------------------------------------------


data "aws_iam_policy_document" "kb_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "kb" {
  name               = "${var.stack_name_base}-knowledge-base-role"
  assume_role_policy = data.aws_iam_policy_document.kb_assume_role.json
  description        = "Execution role for Bedrock Knowledge Bases"
}

data "aws_iam_policy_document" "kb_policy" {
  statement {
    sid     = "BedrockInvokeModel"
    effect  = "Allow"
    actions = ["bedrock:InvokeModel"]
    resources = [
      "arn:aws:bedrock:${local.region}::foundation-model/${var.embedding_model}"
    ]
  }

  statement {
    sid    = "S3VectorsAccess"
    effect = "Allow"
    actions = [
      "s3vectors:PutVectors",
      "s3vectors:GetVectors",
      "s3vectors:DeleteVectors",
      "s3vectors:QueryVectors",
      "s3vectors:GetIndex"
    ]
    resources = [for k, v in local.kb_definitions : aws_s3vectors_index.kb[k].index_arn]
  }

  statement {
    sid    = "S3ReadAccess"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:ListBucket"
    ]
    resources = flatten([
      for kb in local.kb_definitions : [kb.bucket_arn, "${kb.bucket_arn}/*"]
    ])
  }
}

resource "aws_iam_role_policy" "kb" {
  name   = "${var.stack_name_base}-knowledge-base-policy"
  role   = aws_iam_role.kb.id
  policy = data.aws_iam_policy_document.kb_policy.json
}
# -----------------------------------------------------------------------------
# Per-KB Resources (S3 vector bucket + index, Bedrock KB, data source)
# -----------------------------------------------------------------------------


# S3 vector bucket: 3-63 chars, lowercase letters/numbers/hyphens
resource "aws_s3vectors_vector_bucket" "kb" {
  for_each = local.kb_definitions

  vector_bucket_name = lower("${var.stack_name_base}-${each.value.name}-vec-${local.account_id}")
}

resource "aws_s3vectors_index" "kb" {
  for_each = local.kb_definitions

  index_name         = local.index_name
  vector_bucket_name = aws_s3vectors_vector_bucket.kb[each.key].vector_bucket_name
  data_type          = "float32"
  dimension          = 1024
  distance_metric    = "cosine"

  # Bedrock-managed metadata keys must be non-filterable.
  metadata_configuration {
    non_filterable_metadata_keys = ["AMAZON_BEDROCK_METADATA", "AMAZON_BEDROCK_TEXT"]
  }
}

resource "aws_bedrockagent_knowledge_base" "kb" {
  for_each = local.kb_definitions

  name     = "${var.stack_name_base}-${each.value.name}-kb"
  role_arn = aws_iam_role.kb.arn

  knowledge_base_configuration {
    type = "VECTOR"
    vector_knowledge_base_configuration {
      embedding_model_arn = "arn:aws:bedrock:${local.region}::foundation-model/${var.embedding_model}"
    }
  }

  storage_configuration {
    type = "S3_VECTORS"
    s3_vectors_configuration {
      index_arn = aws_s3vectors_index.kb[each.key].index_arn
    }
  }

  depends_on = [
    aws_s3vectors_index.kb,
    aws_iam_role_policy.kb
  ]

  lifecycle {
    ignore_changes = [knowledge_base_configuration]
  }
}

resource "aws_bedrockagent_data_source" "kb" {
  for_each = local.kb_definitions

  name                 = "${var.stack_name_base}-${each.value.name}-s3"
  knowledge_base_id    = aws_bedrockagent_knowledge_base.kb[each.key].id
  data_deletion_policy = "RETAIN"

  data_source_configuration {
    type = "S3"
    s3_configuration {
      bucket_arn = each.value.bucket_arn
    }
  }
}

resource "aws_ssm_parameter" "kb_id" {
  for_each = local.kb_definitions

  name  = "/${var.stack_name_base}/bedrock/${each.value.name}-kb-id"
  type  = "String"
  value = aws_bedrockagent_knowledge_base.kb[each.key].id
}
