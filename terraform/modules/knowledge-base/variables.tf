# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

variable "stack_name_base" {
  description = "Base name for all resources."
  type        = string
}

variable "sops_bucket_arn" {
  description = "ARN of the S3 bucket containing SOPs."
  type        = string
}

variable "api_docs_bucket_arn" {
  description = "ARN of the S3 bucket containing API docs."
  type        = string
}

variable "embedding_model" {
  description = "Bedrock embedding model ID."
  type        = string
  default     = "amazon.titan-embed-text-v2:0"
}
