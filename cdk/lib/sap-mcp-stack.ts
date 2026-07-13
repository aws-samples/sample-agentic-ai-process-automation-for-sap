// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from "aws-cdk-lib"
import * as cr from "aws-cdk-lib/custom-resources"
import * as iam from "aws-cdk-lib/aws-iam"
import * as lambda from "aws-cdk-lib/aws-lambda"
import * as logs from "aws-cdk-lib/aws-logs"
import * as bedrockagentcore from "aws-cdk-lib/aws-bedrockagentcore"
import * as ssm from "aws-cdk-lib/aws-ssm"
import * as path from "path"
import { Construct } from "constructs"
import { AppConfig } from "./utils/config-manager"
import { ExternalSapMcpStackInfo, mapExternalStackInfo } from "./utils/cfn-outputs-resolver"
import { resolveOutboundProfile } from "./utils/resolve-inbound-authorizer"

/**
 * Props for {@link SapMcpStack}.
 *
 * The stack depends on BackendStack for the existing Gateway, Gateway role, Cognito
 * pool, and SAP credentials secret — passed in as props for cross-stack wiring.
 */
export interface SapMcpStackProps extends cdk.StackProps {
  config: AppConfig
  /** Existing AgentCore Gateway (MCP) to add the SAP MCP target to. */
  gateway: bedrockagentcore.CfnGateway
  /** Existing Gateway service role — augmented with the outbound-OAuth token-vault grants. */
  gatewayRole: iam.Role
  /**
   * Resolved external AWS SAP MCP stack info (from bin/app.ts →
   * resolveExternalStack). Optional: when absent, the constructor falls back to
   * the overrides in config.sap_mcp.external_stack. One of the two must supply
   * the external stack's invocation URL + inbound IdP, or the constructor throws.
   */
  externalStack?: ExternalSapMcpStackInfo
  /**
   * Optional suffix appended to globally-unique physical resource names
   * (Gateway target name, OAuth2 provider name, provider log group) so a
   * parallel external-mode stack can coexist with the primary SAP MCP stack
   * on the same Gateway/account. Default "" (no suffix). Does NOT affect
   * CloudFormation logical IDs.
   */
  nameSuffix?: string
}

/**
 * AWS for SAP MCP Server adapter (external-only).
 *
 * IMPORTANT: this stack is NOT the SAP MCP server. The AWS-published SAP MCP
 * CloudFormation stack — deployed and owned OUTSIDE this project — owns the
 * AgentCore Runtime, its inbound Cognito pool, and the outbound SAP OAuth
 * provider. This stack is a thin adapter that wires our Gateway to that
 * external runtime; it attaches, on the existing Gateway:
 *  - a Gateway MCP server target pointing at the external runtime's invocation URL
 *  - a Gateway OAuth2 credential provider pointed at the EXTERNAL stack's
 *    inbound IdP (so the Bearer token the Gateway presents is accepted by that
 *    stack's inbound authorizer)
 * plus the Gateway-role IAM grants needed to fetch the outbound token at
 * tools/call time (_grantGatewayOutboundOAuthPermissions).
 *
 * See ADR-012 and docs/sap/SAP_MCP_INTEGRATION.md.
 */
export class SapMcpStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: SapMcpStackProps) {
    super(scope, id, props)

    const { config } = props
    const sapMcp = config.sap_mcp

    if (!sapMcp || sapMcp.enabled !== true) {
      throw new Error(
        "SapMcpStack was instantiated but sap_mcp is not enabled in config.yaml. " +
          "Check main-stack.ts — this stack should only be created when sap_mcp.enabled is true."
      )
    }

    // Grant once, before any target — see _grantGatewayOutboundOAuthPermissions
    // for what this unlocks and why it's easy to miss.
    this._grantGatewayOutboundOAuthPermissions(props.gatewayRole)

    // The AWS-published SAP MCP CFN stack owns the runtime + inbound pool +
    // outbound OAuth provider. We resolve its outputs (bin/app.ts →
    // resolveExternalStack) and attach Gateway targets only.
    let externalStack = props.externalStack
    if (!externalStack && sapMcp.external_stack) {
      const { stack_name, ...overrides } = sapMcp.external_stack
      externalStack = mapExternalStackInfo({}, overrides)
    }
    if (!externalStack) {
      throw new Error(
        "SapMcpStack: externalStack info was not provided. " +
          "Check main-stack.ts resolveExternalStack wiring."
      )
    }
    // Outbound axis (auth profile) is the source of truth for which SAP MCP target
    // variant deploys.
    const { serviceEnabled, userEnabled, flow, oboDirectMcp } =
      resolveOutboundProfile()

    // Synth-time coherence guard: our resolved outbound flow must agree with the
    // external stack's declared inbound. A mismatch here would only surface at
    // runtime as a generic "An internal error occurred" — fail loud now.
    const externalIsEntra = externalStack.inboundAuthProvider === "EntraId"
    const externalIsObo = externalStack.authFlow === "OBO" || externalIsEntra
    // OUR side is OBO iff the artifact carries the purpose-built obo_direct_mcp
    // boolean. Do NOT key on flow === "OBO" — the emitted flow token is
    // "ON_BEHALF_OF_TOKEN_EXCHANGE" (mcp_oauth_flow), never the literal "OBO".
    const weAreObo = oboDirectMcp === true
    if (weAreObo && !externalIsObo) {
      throw new Error(
        `Outbound flow resolves to OBO (direct-to-MCP) but the external SAP MCP stack declares ` +
          `AuthFlow='${externalStack.authFlow}' / InboundAuthProvider='${externalStack.inboundAuthProvider}'. ` +
          `OBO requires the external stack to accept the user's Entra JWT inbound (EntraId provider / OBO flow). ` +
          `Redeploy the external stack with Entra inbound, or select a non-OBO outbound profile.`
      )
    }
    if (!weAreObo && externalIsObo) {
      throw new Error(
        `Outbound flow resolves to '${flow ?? "none"}' (M2M through our Gateway) but the external SAP MCP ` +
          `stack declares AuthFlow='${externalStack.authFlow}' / InboundAuthProvider='${externalStack.inboundAuthProvider}' ` +
          `(OBO / EntraId inbound). A machine token will be rejected by that inbound authorizer. ` +
          `Select the OBO outbound profile, or point external_stack at an M2M/Cognito inbound.`
      )
    }

    // OBO topology: the agent bypasses our Gateway and dials the external MCP directly
    // with the user's Entra JWT. So skip BOTH Gateway targets and publish the
    // invocation URL + resolved flow to SSM for the agent runtime to read (same
    // /{stack}/… convention as gateway_url).
    if (weAreObo) {
      // The published URL is the external stack's real invocation URL resolved at
      // synth (the emitted artifact carries only a placeholder).
      new ssm.StringParameter(this, "SapMcpOboInvocationUrlParam", {
        parameterName: `/${config.stack_name_base}/mcp_invocation_url`,
        stringValue: externalStack.invocationUrl,
      })
      new ssm.StringParameter(this, "SapMcpOboOutboundFlowParam", {
        parameterName: `/${config.stack_name_base}/outbound_flow`,
        // Publish the RESOLVED flow token verbatim — this is what the agent's
        // resolve_outbound_topology matches against. `flow` is always set on
        // this path; the fallback is just for type safety.
        stringValue: flow ?? "ON_BEHALF_OF_TOKEN_EXCHANGE",
      })
      return
    }

    // Service (M2M/BASIC) target — points at the AWS-owned runtime.
    if (serviceEnabled) {
      this._createExternalGatewayTarget({
        variantId: "Service",
        targetName: `${config.stack_name_base}-sap-mcp-service-target${props.nameSuffix || ""}`,
        targetDescription:
          "AWS for SAP MCP Server (service-account, external). Machine-identity flows.",
        externalStack,
        listingMode: sapMcp.listing_mode || "DEFAULT",
        props,
      })
    }
    // User (USER_FEDERATION) target — interactive per-user 3LO (NOT the OBO
    // token-exchange flow; that is the direct-to-MCP path handled above). Inbound
    // auth is still M2M against the external Cognito; USER_FEDERATION governs the
    // runtime's OUTBOUND (to SAP) interactive flow.
    if (userEnabled) {
      this._createExternalGatewayTarget({
        variantId: "User",
        targetName: `${config.stack_name_base}-sap-mcp-user-target${props.nameSuffix || ""}`,
        targetDescription:
          "AWS for SAP MCP Server (user-federation, external). Interactive per-user 3LO.",
        externalStack,
        listingMode: sapMcp.listing_mode || "DEFAULT",
        props,
      })
    }
  }

  /**
   * Grant the Gateway service role the permissions it needs to fetch the
   * OUTBOUND OAuth token for an MCP-server target at tools/call time.
   *
   * The Gateway calls AgentCore Identity to exchange/fetch the credential
   * provider's token from the token vault before dialing the target runtime.
   * This requires:
   *  - GetWorkloadAccessToken* on the default workload-identity directory
   *  - GetResourceOauth2Token / GetResourceApiKey to retrieve the vaulted token
   *  - GetSecretValue on the bedrock-agentcore-identity!default/oauth2 managed
   *    secret that backs the credential provider
   *
   * Applies to the Gateway→runtime hop (which uses an OAuth2 credential
   * provider). Missing this grant surfaces as a
   * generic "An internal error occurred. Please retry later." on tools/call
   * while tools/list (served from the DEFAULT-mode cache, no token fetch) and
   * Lambda targets keep working — which is what makes the gap hard to spot.
   */
  private _grantGatewayOutboundOAuthPermissions(gatewayRole: iam.Role): void {
    gatewayRole.addToPolicy(new iam.PolicyStatement({
      sid: "AgentCoreWorkloadIdentity",
      effect: iam.Effect.ALLOW,
      actions: [
        "bedrock-agentcore:GetWorkloadAccessToken",
        "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
        "bedrock-agentcore:GetWorkloadAccessTokenForUserId",
      ],
      resources: [
        `arn:${this.partition}:bedrock-agentcore:${this.region}:${this.account}:workload-identity-directory/default`,
        `arn:${this.partition}:bedrock-agentcore:${this.region}:${this.account}:workload-identity-directory/default/workload-identity/*`,
      ],
    }))
    gatewayRole.addToPolicy(new iam.PolicyStatement({
      sid: "AgentCoreOutboundOAuthTokenFetch",
      effect: iam.Effect.ALLOW,
      actions: [
        "bedrock-agentcore:GetResourceOauth2Token",
        "bedrock-agentcore:GetResourceApiKey",
      ],
      // Resource "*": the token-vault credential-provider ARN is created by a
      // custom resource in this same synthesis, so it is not statically known
      // at synth time. The vault itself is access-controlled; this fetch action
      // is the minimum the Gateway needs to retrieve the outbound token.
      resources: ["*"],
    }))
    gatewayRole.addToPolicy(new iam.PolicyStatement({
      sid: "AgentCoreIdentityManagedSecretsRead",
      effect: iam.Effect.ALLOW,
      actions: ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"],
      resources: [
        `arn:${this.partition}:secretsmanager:${this.region}:${this.account}:secret:bedrock-agentcore-identity*`,
      ],
    }))
  }

  /** IAM permissions the OAuth2-provider custom-resource Lambda needs. Used by _createExternalGatewayTarget. */
  private _grantOAuth2ProviderPermissions(fn: lambda.Function): void {
    fn.addToRolePolicy(new iam.PolicyStatement({
      actions: [
        "bedrock-agentcore:CreateOauth2CredentialProvider",
        "bedrock-agentcore:DeleteOauth2CredentialProvider",
        "bedrock-agentcore:GetOauth2CredentialProvider",
        "bedrock-agentcore:UpdateOauth2CredentialProvider",
      ],
      resources: [
        `arn:${this.partition}:bedrock-agentcore:${this.region}:${this.account}:token-vault/default`,
        `arn:${this.partition}:bedrock-agentcore:${this.region}:${this.account}:token-vault/default/oauth2credentialprovider/*`,
      ],
    }))
    fn.addToRolePolicy(new iam.PolicyStatement({
      actions: ["bedrock-agentcore:CreateTokenVault", "bedrock-agentcore:GetTokenVault"],
      resources: [
        `arn:${this.partition}:bedrock-agentcore:${this.region}:${this.account}:token-vault/default`,
        `arn:${this.partition}:bedrock-agentcore:${this.region}:${this.account}:token-vault/default/*`,
      ],
    }))
    fn.addToRolePolicy(new iam.PolicyStatement({
      actions: [
        "secretsmanager:CreateSecret",
        "secretsmanager:DeleteSecret",
        "secretsmanager:DescribeSecret",
        "secretsmanager:PutSecretValue",
      ],
      resources: [
        `arn:${this.partition}:secretsmanager:${this.region}:${this.account}:secret:bedrock-agentcore-identity!default/oauth2/*`,
      ],
    }))
  }

  /**
   * External (hybrid) mode Gateway target.
   *
   * The AWS-published stack owns the runtime and its inbound Cognito pool. We
   * create a Gateway target pointing at the external invocation URL, plus a
   * Gateway OAuth2 credential provider whose client_credentials come from THAT
   * stack's Cognito (so the Bearer token is accepted by the external runtime's
   * inbound authorizer).
   */
  private _createExternalGatewayTarget(params: {
    variantId: "Service" | "User"
    targetName: string
    targetDescription: string
    externalStack: ExternalSapMcpStackInfo
    listingMode: "DYNAMIC" | "DEFAULT"
    props: SapMcpStackProps
  }): bedrockagentcore.CfnGatewayTarget {
    const { variantId, targetName, targetDescription, externalStack, listingMode, props } =
      params
    const config = props.config

    const clientSecretArn = externalStack.inboundClientSecretArn
    if (!clientSecretArn) {
      throw new Error(
        "External SAP MCP: inbound client_secret_arn is required to build the Gateway OAuth2 " +
          "provider. Set inbound_cognito.client_secret_arn (Cognito) or entra_client_secret_arn (EntraId)."
      )
    }

    const providerName = `${config.stack_name_base}-sap-mcp-${variantId.toLowerCase()}-ext-auth${props.nameSuffix || ""}`
    const discoveryUrl = externalStack.inboundDiscoveryUrl

    const oauth2Lambda = new lambda.Function(this, `${variantId}ExtOAuth2ProviderLambda`, {
      runtime: lambda.Runtime.PYTHON_3_13,
      handler: "index.handler",
      code: lambda.Code.fromAsset(path.join(__dirname, "../..", "lambdas", "oauth2_provider_cr")),
      timeout: cdk.Duration.minutes(5),
      logGroup: new logs.LogGroup(this, `${variantId}ExtOAuth2ProviderLogGroup`, {
        logGroupName: `/aws/lambda/${config.stack_name_base}-sap-mcp-ext-oauth2-provider-${variantId.toLowerCase()}${props.nameSuffix || ""}`,
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }),
    })

    // Explicit "${arn}*" match: the ARN from config may or may not include the
    // 6-char random suffix Secrets Manager appends. fromSecretPartialArn +
    // grantRead would append "-??????" and FAIL against a complete ARN
    // (AccessDenied at provider create); "*" matches both forms.
    oauth2Lambda.addToRolePolicy(new iam.PolicyStatement({
      sid: "ExternalCognitoClientSecretRead",
      effect: iam.Effect.ALLOW,
      actions: ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"],
      resources: [`${clientSecretArn}*`],
    }))

    this._grantOAuth2ProviderPermissions(oauth2Lambda)

    const oauth2Provider = new cr.Provider(this, `${variantId}ExtOAuth2Provider`, {
      onEventHandler: oauth2Lambda,
    })

    const credentialProvider = new cdk.CustomResource(this, `${variantId}ExtCredentialProvider`, {
      serviceToken: oauth2Provider.serviceToken,
      properties: {
        ProviderName: providerName,
        ClientSecretArn: clientSecretArn,
        DiscoveryUrl: discoveryUrl,
        ClientId: externalStack.inboundClientId,
      },
    })

    const target = new bedrockagentcore.CfnGatewayTarget(this, `${variantId}ExtTarget`, {
      gatewayIdentifier: props.gateway.attrGatewayIdentifier,
      name: targetName,
      description: targetDescription,
      targetConfiguration: {
        mcp: { mcpServer: { endpoint: externalStack.invocationUrl } },
      },
      credentialProviderConfigurations: [{ credentialProviderType: "OAUTH" }],
      metadataConfiguration: {
        allowedRequestHeaders: [
          "x-audit-correlation-id",
          "x-audit-initiator",
          "x-audit-trigger",
        ],
      },
    })

    target.addPropertyOverride("TargetConfiguration.Mcp.McpServer.ListingMode", listingMode)
    // The inbound token is minted from the EXTERNAL IdP's pool, so the requested
    // scope must be one the external resource server defines (e.g.
    // awsforsap-mcp-m2m-resource-server-<UniqueId>/read). Fall back to our gateway
    // scope only when none is configured (rarely correct for a foreign pool).
    const inboundScopes =
      externalStack.inboundScopes && externalStack.inboundScopes.length > 0
        ? externalStack.inboundScopes
        : [`${config.stack_name_base}-gateway/read`]
    target.addPropertyOverride(
      "CredentialProviderConfigurations.0.CredentialProvider.OauthCredentialProvider",
      {
        ProviderArn: credentialProvider.getAttString("ProviderArn"),
        Scopes: inboundScopes,
      }
    )

    target.addDependency(props.gateway)
    target.node.addDependency(credentialProvider)
    return target
  }
}
