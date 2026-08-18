// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from "aws-cdk-lib"
import * as cloudwatch from "aws-cdk-lib/aws-cloudwatch"
import * as sns from "aws-cdk-lib/aws-sns"
import * as actions from "aws-cdk-lib/aws-cloudwatch-actions"
import * as cloudtrail from "aws-cdk-lib/aws-cloudtrail"
import * as logs from "aws-cdk-lib/aws-logs"
import * as s3 from "aws-cdk-lib/aws-s3"
import { Construct } from "constructs"

export interface ObservabilityProps {
  stackNameBase: string
  metricsNamespace: string
  alarmEmail?: string
  /**
   * Create a CloudTrail trail to feed the autonomy-change alarm (M7).
   *
   * Off by default, matching `security.waf_enabled` and
   * `security.guardrail_enabled`. CloudTrail allows only **5 trails per
   * Region** and that is a hard limit, not a raisable quota — so an
   * unconditional trail here caps how many copies of this sample can coexist
   * in one Region, and fails the deploy outright once the account is at the
   * limit. Enable it in environments that need the alarm.
   */
  auditTrailEnabled?: boolean
}

/**
 * CloudWatch dashboard + alarms for agent observability.
 *
 * Metrics come from two sources:
 * 1. Custom metrics emitted by the agent (ERPAgent namespace) — turns, tokens, cost, latency
 * 2. AWS service metrics (Lambda, SQS, DynamoDB) — errors, throttles, queue depth
 *
 * OTEL traces flow automatically via aws-opentelemetry-distro → X-Ray (no CDK needed).
 */
export class ObservabilityConstruct extends Construct {
  public readonly dashboard: cloudwatch.Dashboard

  constructor(scope: Construct, id: string, props: ObservabilityProps) {
    super(scope, id)

    const ns = props.metricsNamespace

    // SNS topic for alarms (optional — only if email provided)
    let alarmTopic: sns.Topic | undefined
    if (props.alarmEmail) {
      alarmTopic = new sns.Topic(this, "AlarmTopic", {
        topicName: `${props.stackNameBase}-agent-alarms`,
        displayName: "ERP Agent Alarms",
      })
      new sns.Subscription(this, "AlarmEmailSub", {
        topic: alarmTopic,
        protocol: sns.SubscriptionProtocol.EMAIL,
        endpoint: props.alarmEmail,
      })
    }

    // --- Alarms ---

    // DLQ messages > 0
    const dlqAlarm = new cloudwatch.Alarm(this, "DlqAlarm", {
      alarmName: `${props.stackNameBase}-dlq-messages`,
      alarmDescription: "Agent invocation DLQ has messages — failed cases need attention",
      metric: new cloudwatch.Metric({
        namespace: "AWS/SQS",
        metricName: "ApproximateNumberOfMessagesVisible",
        dimensionsMap: { QueueName: `${props.stackNameBase}-agent-queue-dlq.fifo` },
        statistic: "Maximum",
        period: cdk.Duration.minutes(5),
      }),
      threshold: 0,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      evaluationPeriods: 1,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    })

    // Agent success rate < 90% (over 1 hour)
    const failureAlarm = new cloudwatch.Alarm(this, "AgentFailureAlarm", {
      alarmName: `${props.stackNameBase}-agent-failure-rate`,
      alarmDescription: "Agent success rate dropped below 90%",
      metric: new cloudwatch.Metric({
        namespace: ns,
        metricName: "AgentSuccess",
        statistic: "Average",
        period: cdk.Duration.hours(1),
      }),
      threshold: 0.9,
      comparisonOperator: cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD,
      evaluationPeriods: 1,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    })

    // Cost per case > $0.50 (p90 over 1 hour)
    const costAlarm = new cloudwatch.Alarm(this, "AgentCostAlarm", {
      alarmName: `${props.stackNameBase}-agent-cost-high`,
      alarmDescription: "Agent estimated cost per case exceeds $0.50 (p90)",
      metric: new cloudwatch.Metric({
        namespace: ns,
        metricName: "AgentEstimatedCostUSD",
        statistic: "p90",
        period: cdk.Duration.hours(1),
      }),
      threshold: 0.5,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      evaluationPeriods: 1,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    })

    // --- CloudTrail → autonomy change alarm (M7) ---
    // Opt-in: see ObservabilityProps.auditTrailEnabled for why.

    let autonomyChangeAlarm: cloudwatch.Alarm | undefined
    if (props.auditTrailEnabled) {
      const trailLogGroup = new logs.LogGroup(this, "TrailLogGroup", {
        logGroupName: `/${props.stackNameBase}/cloudtrail`,
        retention: logs.RetentionDays.THREE_MONTHS,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      })

      const trailBucket = new s3.Bucket(this, "TrailBucket", {
        bucketName: `${props.stackNameBase}-cloudtrail-${cdk.Aws.ACCOUNT_ID}`,
        enforceSSL: true,
        autoDeleteObjects: true,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
        lifecycleRules: [{ expiration: cdk.Duration.days(90) }],
      })

      new cloudtrail.Trail(this, "SsmTrail", {
        trailName: `${props.stackNameBase}-ssm-trail`,
        bucket: trailBucket,
        cloudWatchLogGroup: trailLogGroup,
        sendToCloudWatchLogs: true,
        managementEvents: cloudtrail.ReadWriteType.WRITE_ONLY,
      })

      // Metric filter: count PutParameter calls targeting autonomy params
      const autonomyPrefix = `/${props.stackNameBase}/autonomy/`
      const autonomyMetricFilter = new logs.MetricFilter(this, "AutonomyChangeFilter", {
        logGroup: trailLogGroup,
        filterPattern: logs.FilterPattern.all(
          logs.FilterPattern.stringValue("$.eventName", "=", "PutParameter"),
          logs.FilterPattern.stringValue("$.requestParameters.name", "=", `${autonomyPrefix}*`),
        ),
        metricNamespace: ns,
        metricName: "AutonomyParameterChange",
        metricValue: "1",
        defaultValue: 0,
      })

      autonomyChangeAlarm = new cloudwatch.Alarm(this, "AutonomyChangeAlarm", {
        alarmName: `${props.stackNameBase}-autonomy-change`,
        alarmDescription:
          "Autonomy control parameter was modified — verify the change was authorized",
        metric: autonomyMetricFilter.metric({
          statistic: "Sum",
          period: cdk.Duration.minutes(5),
        }),
        threshold: 0,
        comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        evaluationPeriods: 1,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      })
    }

    if (alarmTopic) {
      dlqAlarm.addAlarmAction(new actions.SnsAction(alarmTopic))
      failureAlarm.addAlarmAction(new actions.SnsAction(alarmTopic))
      costAlarm.addAlarmAction(new actions.SnsAction(alarmTopic))
      autonomyChangeAlarm?.addAlarmAction(new actions.SnsAction(alarmTopic))
    }

    // --- Dashboard ---

    this.dashboard = new cloudwatch.Dashboard(this, "Dashboard", {
      dashboardName: `${props.stackNameBase}-agent-dashboard`,
      defaultInterval: cdk.Duration.hours(6),
    })

    // Row 1: Agent health overview
    this.dashboard.addWidgets(
      new cloudwatch.SingleValueWidget({
        title: "Cases Processed (24h)",
        metrics: [new cloudwatch.Metric({ namespace: ns, metricName: "AgentSuccess", statistic: "SampleCount", period: cdk.Duration.days(1) })],
        width: 6,
        height: 4,
      }),
      new cloudwatch.SingleValueWidget({
        title: "Success Rate (24h)",
        metrics: [new cloudwatch.Metric({ namespace: ns, metricName: "AgentSuccess", statistic: "Average", period: cdk.Duration.days(1) })],
        width: 6,
        height: 4,
      }),
      new cloudwatch.SingleValueWidget({
        title: "Avg Cost/Case (24h)",
        metrics: [new cloudwatch.Metric({ namespace: ns, metricName: "AgentEstimatedCostUSD", statistic: "Average", period: cdk.Duration.days(1) })],
        width: 6,
        height: 4,
      }),
      new cloudwatch.SingleValueWidget({
        title: "Avg Turns/Case (24h)",
        metrics: [new cloudwatch.Metric({ namespace: ns, metricName: "AgentTurns", statistic: "Average", period: cdk.Duration.days(1) })],
        width: 6,
        height: 4,
      }),
    )

    // Row 2: Token usage over time
    this.dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "Token Usage Over Time",
        left: [
          new cloudwatch.Metric({ namespace: ns, metricName: "AgentInputTokens", statistic: "Sum", period: cdk.Duration.hours(1), label: "Input" }),
          new cloudwatch.Metric({ namespace: ns, metricName: "AgentOutputTokens", statistic: "Sum", period: cdk.Duration.hours(1), label: "Output" }),
          new cloudwatch.Metric({ namespace: ns, metricName: "AgentCacheReadTokens", statistic: "Sum", period: cdk.Duration.hours(1), label: "Cache Read" }),
        ],
        width: 12,
        height: 6,
      }),
      new cloudwatch.GraphWidget({
        title: "Cost & Latency Over Time",
        left: [
          new cloudwatch.Metric({ namespace: ns, metricName: "AgentEstimatedCostUSD", statistic: "Average", period: cdk.Duration.hours(1), label: "Avg Cost ($)" }),
        ],
        right: [
          new cloudwatch.Metric({ namespace: ns, metricName: "AgentLatencyMs", statistic: "p50", period: cdk.Duration.hours(1), label: "p50 Latency" }),
          new cloudwatch.Metric({ namespace: ns, metricName: "AgentLatencyMs", statistic: "p90", period: cdk.Duration.hours(1), label: "p90 Latency" }),
        ],
        width: 12,
        height: 6,
      }),
    )

    // Row 3: Turns distribution + cache effectiveness
    this.dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "Turns Per Case",
        left: [
          new cloudwatch.Metric({ namespace: ns, metricName: "AgentTurns", statistic: "Average", period: cdk.Duration.hours(1), label: "Avg" }),
          new cloudwatch.Metric({ namespace: ns, metricName: "AgentTurns", statistic: "Maximum", period: cdk.Duration.hours(1), label: "Max" }),
        ],
        width: 8,
        height: 6,
      }),
      new cloudwatch.GraphWidget({
        title: "Cache Effectiveness",
        left: [
          new cloudwatch.Metric({ namespace: ns, metricName: "AgentCacheReadTokens", statistic: "Sum", period: cdk.Duration.hours(1), label: "Cache Reads" }),
          new cloudwatch.Metric({ namespace: ns, metricName: "AgentCacheWriteTokens", statistic: "Sum", period: cdk.Duration.hours(1), label: "Cache Writes" }),
        ],
        width: 8,
        height: 6,
      }),
      new cloudwatch.AlarmStatusWidget({
        title: "Alarm Status",
        // autonomyChangeAlarm only exists when the audit trail is enabled.
        alarms: [dlqAlarm, failureAlarm, costAlarm, autonomyChangeAlarm].filter(
          (alarm): alarm is cloudwatch.Alarm => alarm !== undefined,
        ),
        width: 8,
        height: 6,
      }),
    )

    // Row 4: Lambda errors + SQS queue depth
    const lambdaNames = ["odata-poller", "webhook-processor", "agent-invoker", "exemplar-builder"]
    this.dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "Lambda Errors",
        left: lambdaNames.map(
          (name) =>
            new cloudwatch.Metric({
              namespace: "AWS/Lambda",
              metricName: "Errors",
              dimensionsMap: { FunctionName: `${props.stackNameBase}-${name}` },
              statistic: "Sum",
              period: cdk.Duration.minutes(5),
              label: name,
            })
        ),
        width: 12,
        height: 6,
      }),
      new cloudwatch.GraphWidget({
        title: "SQS Queue Depth",
        left: [
          new cloudwatch.Metric({
            namespace: "AWS/SQS",
            metricName: "ApproximateNumberOfMessagesVisible",
            dimensionsMap: { QueueName: `${props.stackNameBase}-agent-queue.fifo` },
            statistic: "Maximum",
            period: cdk.Duration.minutes(1),
            label: "Main Queue",
          }),
          new cloudwatch.Metric({
            namespace: "AWS/SQS",
            metricName: "ApproximateNumberOfMessagesVisible",
            dimensionsMap: { QueueName: `${props.stackNameBase}-agent-queue-dlq.fifo` },
            statistic: "Maximum",
            period: cdk.Duration.minutes(1),
            label: "DLQ",
          }),
        ],
        width: 12,
        height: 6,
      }),
    )
  }
}
