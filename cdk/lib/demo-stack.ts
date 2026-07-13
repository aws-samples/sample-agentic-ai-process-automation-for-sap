// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from "aws-cdk-lib"
import * as lambda from "aws-cdk-lib/aws-lambda"
import * as apigateway from "aws-cdk-lib/aws-apigateway"
import * as logs from "aws-cdk-lib/aws-logs"
import * as ssm from "aws-cdk-lib/aws-ssm"
import * as iam from "aws-cdk-lib/aws-iam"
import { pythonAssetCode } from "./utils/python-bundling"
import { Construct } from "constructs"
import { AppConfig } from "./utils/config-manager"
import { SapConnectivity } from "./constructs/sap-connectivity"
import * as path from "path"

export interface DemoStackProps extends cdk.StackProps {
  config: AppConfig
  frontendUrl: string
  /** SapConnectivity from backend stack — needed for test data Lambda's SAP access */
  sapConnectivity?: SapConnectivity
  /** SAP credentials secret ARN from backend stack */
  sapCredentialsSecretArn?: string
}

/**
 * Demo / test-infrastructure stack — opt-in via config.yaml `demo.test_data.enabled: true`
 * (or `demo.enabled: true` for both demo features).
 *
 * Creates:
 *   - Test Data Lambda for AP invoice-exception test scenarios
 *   - Own API Gateway with /demo/* routes
 *
 * Easy to remove: set `demo.test_data.enabled: false` or delete the stack.
 */
export class DemoStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: DemoStackProps) {
    super(scope, id, {
      ...props,
      description: "Demo / test data infrastructure — safe to delete. Enable via config.yaml demo.test_data.enabled.",
    })

    const { config, frontendUrl } = props
    const base = config.stack_name_base
    const corsOrigins = `${frontendUrl},http://localhost:3000`

    // Tag every resource in this stack for easy identification and cost tracking
    cdk.Tags.of(this).add("demo", "true")
    cdk.Tags.of(this).add("stack", `${base}-demo`)

    // ─── Test Data Lambda (AP invoice exceptions — moved from backend) ────────────
    const testDataLambda = new lambda.Function(this, "TestDataLambda", {
      functionName: `${base}-test-data`,
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64,
      code: pythonAssetCode(path.join(__dirname, "../../lambdas/demo_test_data")),
      handler: "index.handler",
      timeout: cdk.Duration.minutes(2),
      environment: {
        CORS_ALLOWED_ORIGINS: corsOrigins,
        STACK_NAME_BASE: base,
      },
      logGroup: new logs.LogGroup(this, "TestDataLogGroup", {
        logGroupName: `/aws/lambda/${base}-test-data`,
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }),
    })
    testDataLambda.addToRolePolicy(new iam.PolicyStatement({
      actions: ["ssm:GetParameter"],
      resources: [
        `arn:aws:ssm:${this.region}:${this.account}:parameter/${base}/*`,
      ],
    }))
    testDataLambda.addToRolePolicy(new iam.PolicyStatement({
      actions: ["secretsmanager:GetSecretValue"],
      resources: props.sapCredentialsSecretArn
        ? [props.sapCredentialsSecretArn]
        : [`arn:aws:secretsmanager:${this.region}:${this.account}:secret:${base}/sap-credentials*`],
    }))

    // ─── API Gateway ────────────────────────────────────────────────────
    const api = new apigateway.RestApi(this, "DemoApi", {
      restApiName: `${base}-demo-api`,
      description: "Demo / test data API — removable",
      defaultCorsPreflightOptions: {
        allowOrigins: corsOrigins.split(","),
        allowMethods: apigateway.Cors.ALL_METHODS,
        allowHeaders: ["Content-Type", "Authorization"],
      },
    })

    const demo = api.root.addResource("demo")

    // POST /demo/test-data/ap-cases  (AP three-way match test data)
    const testData = demo.addResource("test-data")
    testData.addResource("ap-cases")
      .addMethod("POST", new apigateway.LambdaIntegration(testDataLambda))

    // ─── Outputs ────────────────────────────────────────────────────────
    new ssm.StringParameter(this, "DemoApiUrlParam", {
      parameterName: `/${base}/demo/api-url`,
      stringValue: api.url,
    })

    new cdk.CfnOutput(this, "DemoApiUrl", {
      value: api.url,
      description: "Demo API Gateway URL",
    })
  }
}
