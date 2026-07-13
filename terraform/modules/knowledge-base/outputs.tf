# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

output "sops_kb_id" {
  description = "Bedrock Knowledge Base ID for SOPs"
  value       = aws_bedrockagent_knowledge_base.kb["sops"].id
}

output "api_docs_kb_id" {
  description = "Bedrock Knowledge Base ID for API docs"
  value       = aws_bedrockagent_knowledge_base.kb["api_docs"].id
}
