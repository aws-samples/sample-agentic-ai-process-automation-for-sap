// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from "aws-cdk-lib"
import * as apigateway from "aws-cdk-lib/aws-apigateway"
import * as iam from "aws-cdk-lib/aws-iam"
import * as lambda from "aws-cdk-lib/aws-lambda"
import * as s3 from "aws-cdk-lib/aws-s3"
import * as s3n from "aws-cdk-lib/aws-s3-notifications"
import * as ses from "aws-cdk-lib/aws-ses"
import * as ssm from "aws-cdk-lib/aws-ssm"
import { Construct } from "constructs"
import type { AppConfig } from "../utils/config-manager"

export type NotificationChannelType = "ses" | "servicenow" | "jira" | "tickets"

/**
 * Pluggable notification channel construct.
 *
 * Configures outbound notification infra and inbound webhook/trigger infra
 * based on `notification.channel` in config.yaml.
 *
 * Outbound: env vars set on the notification Gateway Lambda (channel + secret).
 * Inbound:  SES receipt rule (ses) or Lambda Function URL (servicenow/jira).
 *
 * Call `attachToOutboundLambda()` for the notification tool Lambda.
 * Call `attachToInboundLambda()` for the webhook processor Lambda.
 */
export class NotificationChannel extends Construct {
  public readonly channel: NotificationChannelType
  public readonly webhookUrl?: string
  private readonly stackNameBase: string
  private readonly secretArn?: string
  private readonly sesSender?: string
  private sesEmailBucket?: s3.Bucket

  constructor(scope: Construct, id: string, config: AppConfig) {
    super(scope, id)

    this.stackNameBase = config.stack_name_base
    this.channel = (config.notification?.channel as NotificationChannelType) || "ses"
    this.sesSender = config.notification?.ses_sender_email || config.sap?.ses_sender_email || undefined
    this.secretArn = config.notification?.secret_arn

    // Store channel in SSM for runtime discovery
    new ssm.StringParameter(this, "ChannelParam", {
      parameterName: `/${this.stackNameBase}/notification/channel`,
      stringValue: this.channel,
    })
  }

  /**
   * Set env vars on the outbound notification Gateway Lambda.
   */
  attachToOutboundLambda(fn: lambda.IFunction) {
    const cfnFn = fn.node.defaultChild as lambda.CfnFunction
    const env = (cfnFn.environment as any)?.variables || {}
    env.NOTIFICATION_CHANNEL = this.channel

    if (this.channel === "ses") {
      env.NOTIFICATION_SENDER = this.sesSender || ""
      // SES send permission
      fn.addToRolePolicy(new iam.PolicyStatement({
        actions: ["ses:SendEmail", "ses:SendRawEmail"],
        resources: ["*"],
      }))
    } else if (this.channel === "tickets") {
      // Tickets channel needs DynamoDB + SSM access
      env.TICKETS_TABLE_SSM_PARAM = `/${this.stackNameBase}/dynamodb/tickets-table`
      fn.addToRolePolicy(new iam.PolicyStatement({
        actions: ["ssm:GetParameter"],
        resources: [`arn:aws:ssm:${cdk.Stack.of(this).region}:${cdk.Stack.of(this).account}:parameter/${this.stackNameBase}/dynamodb/tickets-table`],
      }))
      fn.addToRolePolicy(new iam.PolicyStatement({
        actions: ["dynamodb:PutItem"],
        resources: [`arn:aws:dynamodb:${cdk.Stack.of(this).region}:${cdk.Stack.of(this).account}:table/${this.stackNameBase}-tickets`],
      }))
    } else {
      // Non-SES channels need Secrets Manager access for credentials
      if (this.secretArn) {
        env.NOTIFICATION_SECRET = this.secretArn
        fn.addToRolePolicy(new iam.PolicyStatement({
          actions: ["secretsmanager:GetSecretValue"],
          resources: [this.secretArn],
        }))
      }
    }

    cfnFn.addPropertyOverride("Environment", { Variables: env })
  }

  /**
   * Configure inbound trigger infra and attach to the webhook processor Lambda.
   *
   * - SES: creates S3 bucket + receipt rule
   * - Others: creates API Gateway POST /webhooks route with rate limiting (no auth —
   *   webhook sources authenticate via HMAC signature verified in the Lambda)
   */
  attachToInboundLambda(fn: lambda.Function, api?: apigateway.RestApi) {
    const cfnFn = fn.node.defaultChild as lambda.CfnFunction
    const env = (cfnFn.environment as any)?.variables || {}
    env.NOTIFICATION_CHANNEL = this.channel

    if (this.channel === "ses") {
      // SES inbound: S3 bucket + receipt rule → Lambda via S3 event
      this.sesEmailBucket = new s3.Bucket(this, "SesInboundBucket", {
        bucketName: `${this.stackNameBase}-ses-inbound-${cdk.Stack.of(this).account}`,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
        autoDeleteObjects: true,
        enforceSSL: true, // TLS-only; holds untrusted inbound email (T10)
        lifecycleRules: [{ expiration: cdk.Duration.days(30) }],
      })
      this.sesEmailBucket.addToResourcePolicy(new iam.PolicyStatement({
        principals: [new iam.ServicePrincipal("ses.amazonaws.com")],
        actions: ["s3:PutObject"],
        // T3: scope to the receipt-rule prefix and pin aws:SourceAccount so a
        // third party's SES rule can't drop forged "inbound email" here
        // (confused deputy) — same guard CDK's own ses.ReceiptRule S3 action adds.
        resources: [this.sesEmailBucket.arnForObjects("inbound/*")],
        conditions: {
          StringEquals: { "aws:SourceAccount": cdk.Stack.of(this).account },
        },
      }))
      this.sesEmailBucket.grantRead(fn)
      this.sesEmailBucket.addEventNotification(
        s3.EventType.OBJECT_CREATED,
        new s3n.LambdaDestination(fn),
        { prefix: "inbound/" },
      )
      env.SES_EMAIL_BUCKET = this.sesEmailBucket.bucketName
    } else if (this.channel !== "tickets") {
      // Webhook channels: API Gateway route with throttling
      if (api) {
        const webhooksResource = api.root.addResource("webhooks")
        webhooksResource.addMethod(
          "POST",
          new apigateway.LambdaIntegration(fn),
          { authorizationType: apigateway.AuthorizationType.NONE },
        )

        const webhookUrl = api.urlForPath("/webhooks")
        ;(this as any).webhookUrl = webhookUrl

        new ssm.StringParameter(this, "WebhookUrlParam", {
          parameterName: `/${this.stackNameBase}/notification/webhook-url`,
          stringValue: webhookUrl,
          description: "Webhook URL for inbound notifications (register in ServiceNow/Jira)",
        })

        new cdk.CfnOutput(this, "WebhookUrl", {
          value: webhookUrl,
          description: `Register this URL as a webhook in your ${this.channel} instance`,
        })
      }

      // Pass channel secret ARN so Lambda can read webhook_secret at cold start.
      // The same secret holds outbound channel creds + inbound webhook_secret.
      if (this.secretArn) {
        env.NOTIFICATION_SECRET = this.secretArn
        fn.addToRolePolicy(new iam.PolicyStatement({
          actions: ["secretsmanager:GetSecretValue"],
          resources: [this.secretArn],
        }))
      }
    }

    cfnFn.addPropertyOverride("Environment", { Variables: env })
  }
}
