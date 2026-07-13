# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
# =============================================================================
# =============================================================================

data "aws_iam_policy_document" "memory_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "memory_execution" {
  name               = "${var.stack_name_base}-memory-execution-role"
  assume_role_policy = data.aws_iam_policy_document.memory_assume_role.json
  description        = "Execution role for AgentCore Memory"
}

# Required even though only short-term memory is configured below — long-term
# memory strategies added later reuse this role for model processing.
resource "aws_iam_role_policy_attachment" "memory_bedrock_policy" {
  role       = aws_iam_role.memory_execution.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonBedrockAgentCoreMemoryBedrockModelInferenceExecutionRolePolicy"
}

resource "aws_bedrockagentcore_memory" "main" {
  name                  = local.memory_name
  event_expiry_duration = local.memory_event_expiry_days
  description           = "Short-term memory for ${var.stack_name_base} agent"

  memory_execution_role_arn = aws_iam_role.memory_execution.arn

  tags = {
    Name = "${var.stack_name_base}_Memory"
  }
}
