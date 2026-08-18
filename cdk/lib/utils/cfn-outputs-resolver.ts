// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import {
  CloudFormationClient,
  DescribeStacksCommand,
} from "@aws-sdk/client-cloudformation"
import {
  DescribeSecretCommand,
  SecretsManagerClient,
} from "@aws-sdk/client-secrets-manager"
import { SapMcpExternalStackConfig } from "./config-manager"

/** Minimal shape of a describe-stacks result we depend on (testable without SDK types). */
export interface RawStackDescription {
  Outputs?: { OutputKey?: string; OutputValue?: string }[]
  Parameters?: { ParameterKey?: string; ParameterValue?: string }[]
}

/** Typed view of the external AWS SAP MCP stack, consumed by SapMcpStack. */
export interface ExternalSapMcpStackInfo {
  invocationUrl: string
  inboundAuthProvider: string
  authFlow: string
  inboundCognito: {
    poolId: string
    clientId: string
    tokenEndpoint: string
    /** Optional — Cognito client secret ARN if provided via config override. */
    clientSecretArn?: string
  }
  /** IdP-neutral inbound auth, used to build the Gateway OAuth2 provider. */
  inboundDiscoveryUrl: string
  inboundClientId: string
  inboundClientSecretArn?: string
  /**
   * OAuth scopes the Gateway requests for the inbound token. Empty when not
   * configured — SapMcpStack falls back to its own gateway scope in that case.
   * For the AWS-published stack, set external_stack.inbound_scopes to its M2M
   * resource-server scope (e.g. awsforsap-mcp-m2m-resource-server-<UniqueId>/read).
   */
  inboundScopes: string[]
}

// Output keys of the AWS-published SAP MCP CloudFormation stack (verified against a live template).
const KEY_INVOCATION_URL = "AwsForSAPMcpServerBedrockAgentCoreInvocationUrlOutput"
const KEY_POOL_ID = "AwsForSAPMcpServerM2MUserPoolIdOutput"
const KEY_CLIENT_ID = "AwsForSAPMcpServerM2MUserPoolClientIdOutput"
const KEY_TOKEN_ENDPOINT = "AwsForSAPMcpServerM2MUserPoolTokenEndpointOutput"

function out(raw: RawStackDescription, key: string): string | undefined {
  return raw.Outputs?.find((o) => o.OutputKey === key)?.OutputValue
}
function param(raw: RawStackDescription, key: string): string | undefined {
  return raw.Parameters?.find((p) => p.ParameterKey === key)?.ParameterValue
}

/**
 * Validate the external SAP MCP invocation URL before the Gateway target is
 * pointed at it (threat T13 — malicious/misconfigured external MCP server).
 *
 * Baseline: the endpoint MUST be https. When the deployer supplies
 * `allowed_endpoint_patterns`, the URL must also match at least one pattern —
 * an explicit allowlist guarding against a tampered external_stack reference
 * sending agent traffic (and SAP writes) to an attacker-controlled host.
 * Pure function — no network — so it is unit-testable.
 */
export function validateInvocationUrl(
  invocationUrl: string,
  allowedPatterns?: string[]
): void {
  if (!invocationUrl.startsWith("https://")) {
    throw new Error(
      `External SAP MCP stack: invocation URL must use https (got '${invocationUrl}').`
    )
  }
  if (allowedPatterns && allowedPatterns.length > 0) {
    const matches = allowedPatterns.some((p) => {
      try {
        // Pattern is deployer-supplied synth-time config (cdk/config.yaml), not request input.
        return new RegExp(p).test(invocationUrl) // nosemgrep: detect-non-literal-regexp
      } catch {
        throw new Error(
          `Invalid regex in sap_mcp.external_stack.allowed_endpoint_patterns: '${p}'.`
        )
      }
    })
    if (!matches) {
      throw new Error(
        `External SAP MCP stack: invocation URL '${invocationUrl}' does not match any ` +
          `sap_mcp.external_stack.allowed_endpoint_patterns. Refusing to point the Gateway ` +
          `at an unapproved endpoint (threat T13).`
      )
    }
  }
}

/**
 * Map a raw describe-stacks result + config overrides into a typed struct.
 * Pure function — no network — so it is unit-testable.
 */
export function mapExternalStackInfo(
  raw: RawStackDescription,
  overrides: Omit<SapMcpExternalStackConfig, "stack_name">
): ExternalSapMcpStackInfo {
  const invocationUrl = overrides.invocation_url || out(raw, KEY_INVOCATION_URL)
  if (!invocationUrl) {
    throw new Error(
      `External SAP MCP stack: could not resolve InvocationUrl (output '${KEY_INVOCATION_URL}' ` +
        `missing and no sap_mcp.external_stack.invocation_url override set).`
    )
  }
  validateInvocationUrl(invocationUrl, overrides.allowed_endpoint_patterns)
  const isEntra =
    (overrides.inbound_auth_provider || param(raw, "InboundAuthProvider")) === "EntraId"

  const poolId = overrides.inbound_cognito?.pool_id || out(raw, KEY_POOL_ID)
  const clientId = overrides.inbound_cognito?.client_id || out(raw, KEY_CLIENT_ID)
  const tokenEndpoint =
    overrides.inbound_cognito?.token_endpoint || out(raw, KEY_TOKEN_ENDPOINT)

  // The Cognito outputs only exist when the external stack uses the Cognito IdP.
  // For EntraId there are no Cognito outputs, so this guard must NOT fire.
  if (!isEntra) {
    const missing = [
      !poolId && "pool_id",
      !clientId && "client_id",
      !tokenEndpoint && "token_endpoint",
    ].filter(Boolean)
    if (missing.length > 0) {
      throw new Error(
        `External SAP MCP stack: missing inbound Cognito ${missing.join(", ")}. ` +
          "Set under sap_mcp.external_stack.inbound_cognito (or verify the stack's Outputs: " +
          `${KEY_POOL_ID}, ${KEY_CLIENT_ID}, ${KEY_TOKEN_ENDPOINT}).`
      )
    }
  }

  // IdP-neutral inbound auth: the Gateway OAuth2 provider must present a token the
  // external runtime's inbound authorizer accepts — Entra discovery URL + client
  // for EntraId, or the Cognito pool-derived .well-known URL for Cognito.
  // The pool's region is encoded as the prefix of the pool id (e.g. "us-east-1_ABC"),
  // which authoritatively matches the cognito-idp.<region> discovery host.
  const poolRegion = poolId?.split("_")[0]
  const cognitoDiscovery = poolId && poolRegion
    ? `https://cognito-idp.${poolRegion}.amazonaws.com/${poolId}/.well-known/openid-configuration`
    : undefined
  const inboundDiscoveryUrl = isEntra ? overrides.entra_discovery_url : cognitoDiscovery
  const inboundClientId = isEntra ? overrides.entra_client_id : clientId
  const inboundClientSecretArn = isEntra
    ? overrides.entra_client_secret_arn
    : overrides.inbound_cognito?.client_secret_arn

  if (!inboundDiscoveryUrl || !inboundClientId) {
    throw new Error(
      "External SAP MCP stack: could not resolve inbound discovery URL / client id " +
        `for IdP '${isEntra ? "EntraId" : "Cognito"}'. ` +
        "For EntraId set entra_discovery_url + entra_client_id; for Cognito verify the stack Outputs."
    )
  }

  return {
    invocationUrl,
    inboundAuthProvider: overrides.inbound_auth_provider || param(raw, "InboundAuthProvider") || "Cognito",
    authFlow: param(raw, "AuthFlow") || "M2M",
    inboundCognito: {
      poolId: poolId || "",
      clientId: clientId || "",
      tokenEndpoint: tokenEndpoint || "",
      clientSecretArn: overrides.inbound_cognito?.client_secret_arn,
    },
    inboundDiscoveryUrl,
    inboundClientId,
    inboundClientSecretArn,
    inboundScopes: overrides.inbound_scopes || [],
  }
}

/**
 * Choose the region to describe the external stack in: the explicit
 * external_stack.region if set, else the deploy/fallback region.
 */
export function chooseStackRegion(
  cfg: Pick<SapMcpExternalStackConfig, "stack_name" | "region">,
  fallbackRegion?: string
): string | undefined {
  return cfg.region || fallbackRegion
}

/**
 * Fetch + map the external stack at synth time.
 * Region comes from external_stack.region if set, else the deploy/fallback
 * region (CDK_DEFAULT_REGION / AWS_REGION via the SDK default chain).
 */
export async function resolveExternalStack(
  cfg: SapMcpExternalStackConfig,
  region?: string
): Promise<ExternalSapMcpStackInfo> {
  const stackRegion = chooseStackRegion(cfg, region)
  const client = new CloudFormationClient(stackRegion ? { region: stackRegion } : {})
  const resp = await client.send(
    new DescribeStacksCommand({ StackName: cfg.stack_name })
  )
  const stack = resp.Stacks?.[0]
  if (!stack) {
    throw new Error(`External SAP MCP stack '${cfg.stack_name}' not found.`)
  }
  const { stack_name, ...overrides } = cfg
  const info = mapExternalStackInfo(
    { Outputs: stack.Outputs, Parameters: stack.Parameters },
    overrides
  )
  await assertSecretResolves(info.inboundClientSecretArn, stackRegion)
  return info
}

/**
 * Confirm the configured inbound client secret identifier actually resolves.
 *
 * Secrets Manager accepts a bare name or a COMPLETE ARN — one ending in the
 * 6-character suffix it appends at creation. An ARN truncated to just the name
 * is neither and matches nothing, but that failure is near-undiagnosable at
 * deploy time: GetSecretValue answers AccessDenied ("no identity-based policy
 * allows...") rather than ResourceNotFoundException, so as not to reveal to an
 * unauthorized caller whether the secret exists. Everything then points at IAM,
 * where nothing is wrong — the `${arn}*` grant in sap-mcp-stack.ts matches the
 * truncated string, and simulate-principal-policy reports "allowed" because it
 * only string-matches and never checks existence.
 *
 * This cannot be a string check: a truncated ARN is indistinguishable from a
 * complete one whenever the name's last segment is itself six alphanumerics
 * (`...-dzuf01` was exactly that). Only a real lookup tells them apart, and only
 * from the deployer's credentials — the Lambda's scoped role gets the same
 * ambiguous AccessDenied either way.
 */
export async function assertSecretResolves(arn?: string, region?: string): Promise<void> {
  if (!arn) return
  const client = new SecretsManagerClient(region ? { region } : {})
  try {
    await client.send(new DescribeSecretCommand({ SecretId: arn }))
  } catch (e: unknown) {
    // Anything other than not-found (AccessDenied on the deployer, throttling,
    // no credentials) is not evidence of a bad identifier — don't block synth.
    if ((e as { name?: string }).name !== "ResourceNotFoundException") return
    throw new Error(
      `External SAP MCP stack: client secret '${arn}' resolves to no secret in ` +
        `${region || "the deploy region"}. A hand-copied ARN is usually missing the ` +
        `6-character suffix Secrets Manager appends (e.g. '...-KRbD6g'); get the exact value ` +
        `with 'aws secretsmanager describe-secret --secret-id <name> --query ARN'. Left ` +
        `unfixed this surfaces at deploy as a misleading AccessDenied on GetSecretValue.`
    )
  }
}
