// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from "aws-cdk-lib"
import { Template, Match } from "aws-cdk-lib/assertions"
import { CognitoStack } from "../lib/cognito-stack"
import { AppConfig } from "../lib/utils/config-manager"

function baseConfig(): AppConfig {
  return {
    stack_name_base: "test-proj",
    backend: { pattern: "agent", deployment_type: "docker", network_mode: "PUBLIC" },
    autonomy: { trigger_mode: "manual" },
  } as AppConfig
}

function federationConfig(): AppConfig {
  const c = baseConfig()
  c.sap = {
    base_url: "https://sap.example.com",
    identity: {
      federation: {
        enabled: true,
        ias_redirect_uri: "https://tenant.accounts.ondemand.com/oauth2/callback",
        mapping_claim: "email",
      },
    },
  } as any
  return c
}

function synth(config: AppConfig): Template {
  const app = new cdk.App()
  const stack = new CognitoStack(app, "test-proj-cognito", {
    config,
    callbackUrls: ["http://localhost:3000"],
    env: { account: "111122223333", region: "us-east-1" },
  })
  return Template.fromStack(stack)
}

describe("CognitoStack same-sub federation client", () => {
  test("creates exactly two user pool clients when federation is enabled", () => {
    // The base user-facing client + the IAS-facing federation client.
    synth(federationConfig()).resourceCountIs("AWS::Cognito::UserPoolClient", 2)
  })

  test("creates only the base client when federation is disabled", () => {
    synth(baseConfig()).resourceCountIs("AWS::Cognito::UserPoolClient", 1)
  })

  test("federation client registers the IAS redirect URI and a generated secret", () => {
    synth(federationConfig()).hasResourceProperties("AWS::Cognito::UserPoolClient", {
      GenerateSecret: true,
      PreventUserExistenceErrors: "ENABLED",
      CallbackURLs: Match.arrayWith([
        "https://tenant.accounts.ondemand.com/oauth2/callback",
      ]),
      AllowedOAuthFlows: Match.arrayWith(["code"]),
      AllowedOAuthScopes: Match.arrayWith(["openid", "email", "profile"]),
    })
  })

  test("emits the OIDC discovery URL and app client id outputs", () => {
    const t = synth(federationConfig())
    const outputs = t.findOutputs("*")
    const keys = Object.keys(outputs)
    expect(keys.some((k) => k.includes("FederationDiscoveryUrl"))).toBe(true)
    expect(keys.some((k) => k.includes("FederationClientId"))).toBe(true)
  })
})
