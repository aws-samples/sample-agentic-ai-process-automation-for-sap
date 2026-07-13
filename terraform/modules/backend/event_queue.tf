# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# =============================================================================
# Event-Driven Pipeline — Agent Invocation Queue + DLQ
# Maps to: backend-stack.ts createEventDrivenPipeline() — queue section
# =============================================================================

# -----------------------------------------------------------------------------
# SQS FIFO — Agent Invocation Queue + DLQ
# -----------------------------------------------------------------------------

# SQS FIFO Agent Invocation Queue + DLQ — mirrors backend-stack.ts

resource "aws_sqs_queue" "agent_dlq" {
  name                      = "${var.stack_name_base}-agent-dlq.fifo"
  fifo_queue                = true
  message_retention_seconds = 1209600 # 14 days
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "agent_queue" {
  name                        = "${var.stack_name_base}-agent-queue.fifo"
  fifo_queue                  = true
  content_based_deduplication = true
  visibility_timeout_seconds  = 600    # > agent invoker timeout
  message_retention_seconds   = 604800 # 7 days
  sqs_managed_sse_enabled     = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.agent_dlq.arn
    maxReceiveCount     = 3
  })
}

resource "aws_ssm_parameter" "agent_queue_url" {
  name  = "${local.ssm_parameter_prefix}/sqs/agent-queue-url"
  type  = "String"
  value = aws_sqs_queue.agent_queue.url
}

resource "aws_ssm_parameter" "agent_dlq_url" {
  name  = "${local.ssm_parameter_prefix}/sqs/agent-dlq-url"
  type  = "String"
  value = aws_sqs_queue.agent_dlq.url
}
