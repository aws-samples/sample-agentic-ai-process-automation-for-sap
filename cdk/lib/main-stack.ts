// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from "aws-cdk-lib"
import { Construct } from "constructs"
import { AppConfig } from "./utils/config-manager"

import { BackendStack } from "./backend-stack"
import { FrontendStack } from "./frontend-stack"
import { CognitoStack } from "./cognito-stack"
import { DemoStack } from "./demo-stack"
import { SapMcpStack } from "./sap-mcp-stack"

export interface MainStackProps extends cdk.StackProps {
  config: AppConfig
}

/**
 * Orchestrates independent stacks with explicit dependency ordering:
 *   1. Frontend       (no dependencies — React frontend on Amplify)
 *   2. Cognito        (depends on Frontend for OAuth callback URLs)
 *   3. Backend        (depends on Cognito + Frontend; includes S3 Vectors Knowledge Bases)
 *
 * Each is a standalone CloudFormation stack; if one fails the others remain
 * intact. The React app is deployed to Amplify separately via
 * `scripts/deploy/deploy-frontend.py`.
 */
export function createStacks(
  app: Construct,
  config: AppConfig,
  env: cdk.Environment,
  externalSapMcp?: import("./utils/cfn-outputs-resolver").ExternalSapMcpStackInfo,
  sapMcpStackSuffix?: string
): {
  frontendStack: FrontendStack
  cognitoStack: CognitoStack
  backendStack: BackendStack
  demoStack?: DemoStack
  sapMcpStack?: SapMcpStack
} {
  const base = config.stack_name_base

  // 1. Frontend — no dependencies
  const frontendStack = new FrontendStack(app, `${base}-frontend`, {
    config,
    env,
  })

  // 2. Cognito — needs the frontend URL for OAuth callback
  const cognitoStack = new CognitoStack(app, `${base}-cognito`, {
    config,
    callbackUrls: ["http://localhost:3000", frontendStack.amplifyUrl],
    env,
  })
  cognitoStack.addDependency(frontendStack)

  // 3. Backend — needs Cognito IDs + frontend URL for CORS
  const backendStack = new BackendStack(app, `${base}-backend`, {
    config,
    userPoolId: cognitoStack.userPoolId,
    userPoolClientId: cognitoStack.userPoolClientId,
    userPoolDomain: cognitoStack.userPoolDomain,
    frontendUrl: frontendStack.amplifyUrl,
    additionalCorsOrigins: [],
    env,
  })
  backendStack.addDependency(cognitoStack)

  // 5. Demo — opt-in test-data infrastructure
  let demoStack: DemoStack | undefined
  if (config.demo?.test_data?.enabled) {
    demoStack = new DemoStack(app, `${base}-demo`, {
      config,
      frontendUrl: frontendStack.amplifyUrl,
      sapCredentialsSecretArn: backendStack.sapCredentialsSecretArn,
      env,
    })
    demoStack.addDependency(backendStack)
  }

  // 6. SAP MCP — attaches the external SAP MCP server as a Gateway target
  // (reads + writes + discovery). See ADR-012.
  let sapMcpStack: SapMcpStack | undefined
  if (config.sap_mcp?.enabled) {
    const sapMcpSuffix = sapMcpStackSuffix || ""
    sapMcpStack = new SapMcpStack(app, `${base}-sap-mcp${sapMcpSuffix}`, {
      config,
      gateway: backendStack.gateway,
      gatewayRole: backendStack.gatewayRole,
      externalStack: externalSapMcp,
      nameSuffix: sapMcpSuffix,
      env,
    })
    sapMcpStack.addDependency(backendStack)
  }

  // Tags for cost allocation and ownership tracking
  const allStacks = [frontendStack, cognitoStack, backendStack, ...(demoStack ? [demoStack] : []), ...(sapMcpStack ? [sapMcpStack] : [])]
  for (const s of allStacks) {
    cdk.Tags.of(s).add('project', base)
    cdk.Tags.of(s).add('managed-by', 'cdk')
  }

  // Stack-level architecture-component
  cdk.Tags.of(frontendStack).add('architecture-component', 'frontend')
  cdk.Tags.of(cognitoStack).add('architecture-component', 'auth')
  cdk.Tags.of(backendStack).add('exception-type', 'shared')

  if (demoStack) {
    cdk.Tags.of(demoStack).add('architecture-component', 'demo')
    cdk.Tags.of(demoStack).add('exception-type', 'shared')
    cdk.Tags.of(demoStack).add('demo', 'true')
  }

  if (sapMcpStack) {
    cdk.Tags.of(sapMcpStack).add('architecture-component', 'sap-mcp')
    cdk.Tags.of(sapMcpStack).add('exception-type', 'shared')
  }

  return { frontendStack, cognitoStack, backendStack, demoStack, sapMcpStack }
}
