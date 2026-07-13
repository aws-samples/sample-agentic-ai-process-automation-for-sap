// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from "aws-cdk-lib"
import * as amplify from "@aws-cdk/aws-amplify-alpha"
import * as s3 from "aws-cdk-lib/aws-s3"
import * as iam from "aws-cdk-lib/aws-iam"
import { Construct } from "constructs"
import { AppConfig } from "./utils/config-manager"

export interface FrontendStackProps extends cdk.StackProps {
  config: AppConfig
}

/**
 * Hosts the React frontend on AWS Amplify (plus its deployment staging bucket).
 * This is the only frontend host; the React app is deployed separately via
 * `scripts/deploy/deploy-frontend.py`.
 */
export class FrontendStack extends cdk.Stack {
  public readonly amplifyApp: amplify.App
  public readonly amplifyUrl: string
  public readonly stagingBucket: s3.Bucket

  constructor(scope: Construct, id: string, props: FrontendStackProps) {
    const description = "ERP Accrual Agent - React Frontend (Amplify Hosting)"
    super(scope, id, { ...props, description })

    const accessLogsBucket = new s3.Bucket(this, "StagingBucketAccessLogs", {
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      publicReadAccess: false,
      enforceSSL: true, // TLS-only, uniform with StagingBucket (T10)
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      lifecycleRules: [
        {
          id: "DeleteOldAccessLogs",
          enabled: true,
          expiration: cdk.Duration.days(90),
        },
      ],
    })

    this.stagingBucket = new s3.Bucket(this, "StagingBucket", {
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      versioned: true,
      publicReadAccess: false,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      serverAccessLogsBucket: accessLogsBucket,
      serverAccessLogsPrefix: "staging-bucket-access-logs/",
      lifecycleRules: [
        {
          id: "DeleteOldDeployments",
          enabled: true,
          expiration: cdk.Duration.days(30),
        },
      ],
    })

    this.stagingBucket.addToResourcePolicy(
      new iam.PolicyStatement({
        sid: "AmplifyAccess",
        effect: iam.Effect.ALLOW,
        principals: [new iam.ServicePrincipal("amplify.amazonaws.com")],
        actions: ["s3:GetObject", "s3:GetObjectVersion"],
        resources: [this.stagingBucket.arnForObjects("*")],
      })
    )

    this.stagingBucket.addToResourcePolicy(
      new iam.PolicyStatement({
        sid: "DenyInsecureConnections",
        effect: iam.Effect.DENY,
        principals: [new iam.AnyPrincipal()],
        actions: ["s3:*"],
        resources: [
          this.stagingBucket.bucketArn,
          this.stagingBucket.arnForObjects("*"),
        ],
        conditions: {
          Bool: {
            "aws:SecureTransport": "false",
          },
        },
      })
    )

    this.amplifyApp = new amplify.App(this, "AmplifyApp", {
      appName: `${props.config.stack_name_base}-frontend`,
      description: `${props.config.stack_name_base} - React Frontend`,
      platform: amplify.Platform.WEB,
      customRules: [
        // SPA rewrite: serve index.html for all routes that aren't static files.
        // Without this, direct navigation to /observability, /test-data, etc. returns 404.
        new amplify.CustomRule({
          source: "</^[^.]+$|\\.(?!(css|gif|ico|jpg|js|png|txt|svg|woff|woff2|ttf|map|json|webp)$)([^.]+$)/>",
          target: "/index.html",
          status: amplify.RedirectStatus.REWRITE,
        }),
      ],
    })

    this.amplifyApp.addBranch("main", {
      stage: "PRODUCTION",
      branchName: "main",
    })

    this.amplifyUrl = `https://main.${this.amplifyApp.appId}.amplifyapp.com`

    // Cross-stack exports
    new cdk.CfnOutput(this, "AmplifyAppId", {
      value: this.amplifyApp.appId,
      description: "Amplify App ID - use this for manual deployment",
      exportName: `${props.config.stack_name_base}-AmplifyAppId`,
    })

    new cdk.CfnOutput(this, "AmplifyUrl", {
      value: this.amplifyUrl,
      description: "Amplify Frontend URL (available after deployment)",
      exportName: `${props.config.stack_name_base}-AmplifyUrl`,
    })

    new cdk.CfnOutput(this, "StagingBucketName", {
      value: this.stagingBucket.bucketName,
      description: "S3 bucket for Amplify deployment staging",
      exportName: `${props.config.stack_name_base}-StagingBucket`,
    })

    new cdk.CfnOutput(this, "AmplifyConsoleUrl", {
      value: `https://console.aws.amazon.com/amplify/apps/${this.amplifyApp.appId}`,
      description: "Amplify Console URL for monitoring deployments",
    })
  }
}
