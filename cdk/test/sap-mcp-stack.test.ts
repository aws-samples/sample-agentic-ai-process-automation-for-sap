// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from "aws-cdk-lib"
import { Template, Match } from "aws-cdk-lib/assertions"
import * as iam from "aws-cdk-lib/aws-iam"
import * as bedrockagentcore from "aws-cdk-lib/aws-bedrockagentcore"
import * as fs from "fs"
import * as path from "path"
import { SapMcpStack } from "../lib/sap-mcp-stack"
import { AppConfig } from "../lib/utils/config-manager"

// SapMcpStack derives its target variant from the outbound block of this artifact
// (resolveOutboundProfile's default path); tests must write fixtures here.
const ARTIFACT_PATH = path.join(__dirname, "..", "..", ".auth-profile-resolved.json")

function externalConfig(): AppConfig {
  return {
    stack_name_base: "test-proj",
    backend: { pattern: "agent", deployment_type: "docker", network_mode: "PUBLIC" },
    autonomy: { trigger_mode: "manual" },
    sap: { base_url: "https://mock-sap.example.com" },
    sap_mcp: {
      enabled: true,
      listing_mode: "DYNAMIC",
      external_stack: {
        stack_name: "sap-mcp-spike",
        inbound_auth_provider: "Cognito",
        inbound_cognito: {
          pool_id: "us-east-1_ABC",
          client_id: "client123",
          token_endpoint: "https://cognito/token",
          client_secret_arn:
            "arn:aws:secretsmanager:us-east-1:111122223333:secret:ext-cognito-abc",
        },
        invocation_url:
          "https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/x/invocations?qualifier=DEFAULT",
      },
      service: { enabled: true },
    },
  } as AppConfig
}

function harness(config: AppConfig): SapMcpStack {
  const app = new cdk.App()
  const host = new cdk.Stack(app, "Host", { env: { account: "111122223333", region: "us-east-1" } })
  const gateway = new bedrockagentcore.CfnGateway(host, "GW", {
    name: "gw", protocolType: "MCP", roleArn: "arn:aws:iam::111122223333:role/gw",
    authorizerType: "CUSTOM_JWT",
    authorizerConfiguration: { customJwtAuthorizer: { discoveryUrl: "https://idp/.well-known/openid-configuration" } },
  })
  const gatewayRole = new iam.Role(host, "GWRole", { assumedBy: new iam.ServicePrincipal("bedrock-agentcore.amazonaws.com") })
  return new SapMcpStack(app, "test-proj-sap-mcp", {
    config,
    gateway,
    gatewayRole,
    env: { account: "111122223333", region: "us-east-1" },
  })
}

// Which target variants deploy is driven by the outbound artifact block, not the
// config `service.enabled` / `user.enabled` flags. Tests write a fixture artifact
// and must remove it afterward so it doesn't leak into other tests.
function writeOutbound(
  outbound:
    | { service_enabled?: boolean; user_enabled?: boolean; flow?: string; obo_direct_mcp?: boolean; mcp_invocation_url?: string }
    | null,
): void {
  if (outbound === null) {
    if (fs.existsSync(ARTIFACT_PATH)) fs.unlinkSync(ARTIFACT_PATH)
    return
  }
  fs.writeFileSync(ARTIFACT_PATH, JSON.stringify({ outbound: { flow: "M2M", ...outbound } }))
}
function clearOutbound(): void {
  if (fs.existsSync(ARTIFACT_PATH)) fs.unlinkSync(ARTIFACT_PATH)
}

describe("SapMcpStack external mode (M2M)", () => {
  beforeEach(() => writeOutbound({ service_enabled: true, user_enabled: false }))
  afterEach(clearOutbound)

  test("creates a Gateway target but NO runtime", () => {
    const t = Template.fromStack(harness(externalConfig()))
    t.resourceCountIs("AWS::BedrockAgentCore::Runtime", 0)
    t.resourceCountIs("AWS::BedrockAgentCore::GatewayTarget", 1)
  })

  test("target endpoint is the external stack's invocation URL", () => {
    const t = Template.fromStack(harness(externalConfig()))
    t.hasResourceProperties("AWS::BedrockAgentCore::GatewayTarget", {
      TargetConfiguration: {
        Mcp: {
          McpServer: {
            Endpoint: "https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/x/invocations?qualifier=DEFAULT",
          },
        },
      },
    })
  })

  test("OAuth2 provider custom resource points at the EXTERNAL Cognito client", () => {
    const t = Template.fromStack(harness(externalConfig()))
    t.hasResourceProperties("AWS::CloudFormation::CustomResource", {
      ClientId: "client123",
      DiscoveryUrl: Match.stringLikeRegexp("us-east-1_ABC"),
    })
  })

  // The grant needs a "*" suffix so it matches whether the configured ARN is
  // complete (with the 6-char random suffix) or partial. fromSecretPartialArn
  // instead appends "-??????", which fails AccessDenied against a complete ARN.
  test("grants GetSecretValue on the external client secret ARN with a wildcard suffix", () => {
    const t = Template.fromStack(harness(externalConfig()))
    t.hasResourceProperties("AWS::IAM::Policy", {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: Match.arrayWith(["secretsmanager:GetSecretValue"]),
            Resource:
              "arn:aws:secretsmanager:us-east-1:111122223333:secret:ext-cognito-abc*",
          }),
        ]),
      },
    })
  })

  // In external mode the inbound token is minted from the EXTERNAL pool, so the
  // Gateway provider scope must be the external resource server's scope, not ours —
  // a hardcoded gateway scope gets rejected by the external pool.
  test("uses external_stack.inbound_scopes for the Gateway provider when set", () => {
    const cfg = externalConfig()
    cfg.sap_mcp!.external_stack!.inbound_scopes = [
      "awsforsap-mcp-m2m-resource-server-dz321d23/read",
    ]
    const t = Template.fromStack(harness(cfg))
    t.hasResourceProperties("AWS::BedrockAgentCore::GatewayTarget", {
      CredentialProviderConfigurations: Match.arrayWith([
        Match.objectLike({
          CredentialProvider: {
            OauthCredentialProvider: Match.objectLike({
              Scopes: ["awsforsap-mcp-m2m-resource-server-dz321d23/read"],
            }),
          },
        }),
      ]),
    })
  })

  test("falls back to the gateway scope when inbound_scopes is unset", () => {
    const t = Template.fromStack(harness(externalConfig()))
    t.hasResourceProperties("AWS::BedrockAgentCore::GatewayTarget", {
      CredentialProviderConfigurations: Match.arrayWith([
        Match.objectLike({
          CredentialProvider: {
            OauthCredentialProvider: Match.objectLike({
              Scopes: ["test-proj-gateway/read"],
            }),
          },
        }),
      ]),
    })
  })

  test("no nameSuffix yields the base target name", () => {
    const t = Template.fromStack(harness(externalConfig()))
    t.hasResourceProperties("AWS::BedrockAgentCore::GatewayTarget", {
      Name: "test-proj-sap-mcp-service-target",
    })
  })

  test("nameSuffix isolates physical names for a parallel stack", () => {
    const app = new cdk.App()
    const host = new cdk.Stack(app, "Host", { env: { account: "111122223333", region: "us-east-1" } })
    const gateway = new bedrockagentcore.CfnGateway(host, "GW", {
      name: "gw", protocolType: "MCP", roleArn: "arn:aws:iam::111122223333:role/gw",
      authorizerType: "CUSTOM_JWT",
      authorizerConfiguration: { customJwtAuthorizer: { discoveryUrl: "https://idp/.well-known/openid-configuration" } },
    })
    const gatewayRole = new iam.Role(host, "GWRole", { assumedBy: new iam.ServicePrincipal("bedrock-agentcore.amazonaws.com") })
    const stack = new SapMcpStack(app, "test-proj-sap-mcp-ext", {
      config: externalConfig(),
      gateway, gatewayRole,
      nameSuffix: "-ext",
      env: { account: "111122223333", region: "us-east-1" },
    })
    const t = Template.fromStack(stack)
    t.hasResourceProperties("AWS::BedrockAgentCore::GatewayTarget", {
      Name: "test-proj-sap-mcp-service-target-ext",
    })
    t.hasResourceProperties("AWS::CloudFormation::CustomResource", Match.objectLike({
      ProviderName: "test-proj-sap-mcp-service-ext-auth-ext",
    }))
  })
})

describe("SapMcpStack Gateway role outbound-OAuth grant (regression)", () => {
  // Without GetWorkloadAccessToken + GetResourceOauth2Token + read on the
  // bedrock-agentcore-identity managed secret, the Gateway returns a generic
  // "An internal error occurred" on tools/call (tools/list still works). The
  // grant must land on the gateway role, which lives in the host stack.
  beforeEach(() => writeOutbound({ service_enabled: true, user_enabled: false }))
  afterEach(clearOutbound)

  function hostWithSapMcp(config: AppConfig): cdk.Stack {
    const app = new cdk.App()
    const host = new cdk.Stack(app, "Host", { env: { account: "111122223333", region: "us-east-1" } })
    const gateway = new bedrockagentcore.CfnGateway(host, "GW", {
      name: "gw", protocolType: "MCP", roleArn: "arn:aws:iam::111122223333:role/gw",
      authorizerType: "CUSTOM_JWT",
      authorizerConfiguration: { customJwtAuthorizer: { discoveryUrl: "https://idp/.well-known/openid-configuration" } },
    })
    const gatewayRole = new iam.Role(host, "GWRole", { assumedBy: new iam.ServicePrincipal("bedrock-agentcore.amazonaws.com") })
    new SapMcpStack(app, "test-proj-sap-mcp", {
      config, gateway, gatewayRole,
      env: { account: "111122223333", region: "us-east-1" },
    })
    return host
  }

  test("external mode grants GetWorkloadAccessToken + GetResourceOauth2Token to the gateway role", () => {
    const t = Template.fromStack(hostWithSapMcp(externalConfig()))
    t.hasResourceProperties("AWS::IAM::Policy", {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: Match.arrayWith(["bedrock-agentcore:GetWorkloadAccessToken"]),
          }),
          Match.objectLike({
            Action: Match.arrayWith(["bedrock-agentcore:GetResourceOauth2Token"]),
          }),
        ]),
      },
    })
  })

  test("grants read on the bedrock-agentcore-identity managed secret", () => {
    const t = Template.fromStack(hostWithSapMcp(externalConfig()))
    t.hasResourceProperties("AWS::IAM::Policy", {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: Match.arrayWith(["secretsmanager:GetSecretValue"]),
            // CDK renders the ARN as an Fn::Join (region/account are tokens);
            // assert the managed-secret suffix is present in the joined parts.
            Resource: {
              "Fn::Join": [
                "",
                Match.arrayWith([
                  Match.stringLikeRegexp(":secret:bedrock-agentcore-identity\\*"),
                ]),
              ],
            },
          }),
        ]),
      },
    })
  })
})

describe("SapMcpStack external mode (USER_FEDERATION)", () => {
  afterEach(clearOutbound)

  test("creates a second Gateway target for the user runtime when outbound.user_enabled", () => {
    writeOutbound({ service_enabled: true, user_enabled: true })
    const t = Template.fromStack(harness(externalConfig()))
    t.resourceCountIs("AWS::BedrockAgentCore::GatewayTarget", 2)
    t.hasResourceProperties("AWS::BedrockAgentCore::GatewayTarget", {
      Name: "test-proj-sap-mcp-user-target",
    })
  })

  test("creates only the service target when user is absent", () => {
    writeOutbound({ service_enabled: true, user_enabled: false })
    const t = Template.fromStack(harness(externalConfig()))
    t.resourceCountIs("AWS::BedrockAgentCore::GatewayTarget", 1)
  })
})

describe("outbound axis drives target variants", () => {
  afterEach(clearOutbound)

  function synthWithOutbound(
    outbound: { service_enabled?: boolean; user_enabled?: boolean } | null,
  ): SapMcpStack {
    writeOutbound(outbound)
    return harness(externalConfig())
  }

  it("creates only the Service target when outbound.service_enabled", () => {
    const template = Template.fromStack(synthWithOutbound({ service_enabled: true, user_enabled: false }))
    const targets = template.findResources("AWS::BedrockAgentCore::GatewayTarget")
    const names = Object.values(targets).map((t: any) => t.Properties.Name)
    expect(names.some((n: string) => n.includes("sap-mcp-service-target"))).toBe(true)
    expect(names.some((n: string) => n.includes("sap-mcp-user-target"))).toBe(false)
  })

  it("creates neither external target when no outbound block", () => {
    const template = Template.fromStack(synthWithOutbound(null))
    const targets = template.findResources("AWS::BedrockAgentCore::GatewayTarget")
    const names = Object.values(targets).map((t: any) => t.Properties.Name)
    expect(names.some((n: string) => n.includes("sap-mcp-service-target"))).toBe(false)
    expect(names.some((n: string) => n.includes("sap-mcp-user-target"))).toBe(false)
  })
})

describe("SapMcpStack OBO (direct-to-MCP) topology", () => {
  afterEach(clearOutbound)

  function entraExternalConfig(): AppConfig {
    const cfg = externalConfig()
    cfg.sap_mcp!.external_stack!.inbound_auth_provider = "EntraId"
    cfg.sap_mcp!.external_stack!.inbound_cognito = undefined as any
    ;(cfg.sap_mcp!.external_stack as any).entra_discovery_url =
      "https://login.microsoftonline.com/<tenant>/v2.0/.well-known/openid-configuration"
    ;(cfg.sap_mcp!.external_stack as any).entra_client_id = "spa-client-id"
    ;(cfg.sap_mcp!.external_stack as any).entra_client_secret_arn =
      "arn:aws:secretsmanager:us-east-1:111122223333:secret:entra"
    return cfg
  }

  test("OBO artifact + Entra external stack: no Gateway target, writes both SSM params", () => {
    // Must use the flow token the emitter actually produces for OBO
    // ("ON_BEHALF_OF_TOKEN_EXCHANGE"), not the literal string "OBO".
    writeOutbound({
      flow: "ON_BEHALF_OF_TOKEN_EXCHANGE",
      service_enabled: false,
      user_enabled: true,
      obo_direct_mcp: true,
      mcp_invocation_url: "https://example-mcp.invalid/mcp",
    })
    const t = Template.fromStack(harness(entraExternalConfig()))
    // OBO bypasses our Gateway entirely — neither Service nor User target.
    t.resourceCountIs("AWS::BedrockAgentCore::GatewayTarget", 0)
    t.resourceCountIs("AWS::SSM::Parameter", 2)
    t.hasResourceProperties("AWS::SSM::Parameter", {
      Name: "/test-proj/mcp_invocation_url",
      Value:
        "https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/x/invocations?qualifier=DEFAULT",
    })
    // outbound_flow must carry the resolved token, since that's what the
    // agent's resolve_outbound_topology matches on — not the literal "OBO".
    t.hasResourceProperties("AWS::SSM::Parameter", {
      Name: "/test-proj/outbound_flow",
      Value: "ON_BEHALF_OF_TOKEN_EXCHANGE",
    })
  })

  test("mismatch: OBO artifact against a Cognito/M2M external stack throws the guard message", () => {
    writeOutbound({
      flow: "ON_BEHALF_OF_TOKEN_EXCHANGE",
      service_enabled: false,
      user_enabled: true,
      obo_direct_mcp: true,
      mcp_invocation_url: "https://example-mcp.invalid/mcp",
    })
    // externalConfig() default is Cognito / AuthFlow M2M — not OBO-capable.
    expect(() => harness(externalConfig())).toThrow(
      /OBO requires the external stack to accept the user's Entra JWT inbound/,
    )
  })

  test("mismatch: M2M artifact against an Entra/OBO external stack throws the guard message", () => {
    writeOutbound({ flow: "M2M", service_enabled: true, user_enabled: false })
    expect(() => harness(entraExternalConfig())).toThrow(
      /A machine token will be rejected by that inbound authorizer/,
    )
  })

  test("non-OBO profile against a matching M2M external stack is unchanged (Service target, no SSM param)", () => {
    writeOutbound({ flow: "M2M", service_enabled: true, user_enabled: false })
    const t = Template.fromStack(harness(externalConfig()))
    t.resourceCountIs("AWS::BedrockAgentCore::GatewayTarget", 1)
    t.resourceCountIs("AWS::SSM::Parameter", 0)
  })
})
