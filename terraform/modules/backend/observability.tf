# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
# =============================================================================
# =============================================================================

locals {
  metrics_namespace = "ERPAgent"
}

resource "aws_sns_topic" "alarms" {
  count = var.alarm_email != null ? 1 : 0

  name              = "${var.stack_name_base}-agent-alarms"
  display_name      = "ERP Agent Alarms"
  kms_master_key_id = "alias/aws/sns" # AWS-managed KMS key — server-side encryption
}

resource "aws_sns_topic_subscription" "alarm_email" {
  count = var.alarm_email != null ? 1 : 0

  topic_arn = aws_sns_topic.alarms[0].arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

resource "aws_cloudwatch_metric_alarm" "dlq_messages" {
  alarm_name          = "${var.stack_name_base}-dlq-messages"
  alarm_description   = "Agent invocation DLQ has messages — failed cases need attention"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.agent_dlq.name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = var.alarm_email != null ? [aws_sns_topic.alarms[0].arn] : []
}

resource "aws_cloudwatch_metric_alarm" "agent_failure_rate" {
  alarm_name          = "${var.stack_name_base}-agent-failure-rate"
  alarm_description   = "Agent success rate dropped below 90%"
  namespace           = local.metrics_namespace
  metric_name         = "AgentSuccess"
  statistic           = "Average"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 0.9
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = var.alarm_email != null ? [aws_sns_topic.alarms[0].arn] : []
}

resource "aws_cloudwatch_dashboard" "agent" {
  dashboard_name = "${var.stack_name_base}-agent-dashboard"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title = "Agent Invocations"
          metrics = [
            ["AWS/SQS", "NumberOfMessagesSent", "QueueName", aws_sqs_queue.agent_queue.name],
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", aws_sqs_queue.agent_dlq.name]
          ]
          period = 300
          stat   = "Sum"
          region = local.region
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title = "Agent Success Rate"
          metrics = [
            [local.metrics_namespace, "AgentSuccess", { stat = "Average" }],
            [local.metrics_namespace, "AgentLatency", { stat = "p90" }]
          ]
          period = 3600
          region = local.region
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          title = "Lambda Errors"
          metrics = [
            ["AWS/Lambda", "Errors", "FunctionName", "${var.stack_name_base}-agent-invoker"],
            ["AWS/Lambda", "Errors", "FunctionName", "${var.stack_name_base}-odata-poller"]
          ]
          period = 300
          stat   = "Sum"
          region = local.region
        }
      }
    ]
  })
}
