// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { SecretsManagerClient } from "@aws-sdk/client-secrets-manager"
import {
  mapExternalStackInfo,
  RawStackDescription,
  chooseStackRegion,
  validateInvocationUrl,
  assertSecretResolves,
} from "../lib/utils/cfn-outputs-resolver"

describe("chooseStackRegion", () => {
  test("prefers external_stack.region over the deploy region", () => {
    expect(chooseStackRegion({ stack_name: "s", region: "us-west-2" }, "us-east-1")).toBe("us-west-2")
  })
  test("falls back to the deploy region when region unset", () => {
    expect(chooseStackRegion({ stack_name: "s" }, "us-east-1")).toBe("us-east-1")
  })
  test("returns undefined when neither is set", () => {
    expect(chooseStackRegion({ stack_name: "s" }, undefined)).toBeUndefined()
  })
})

const RAW: RawStackDescription = {
  Outputs: [
    { OutputKey: "AwsForSAPMcpServerBedrockAgentCoreInvocationUrlOutput", OutputValue: "https://rt/invoke" },
    { OutputKey: "AwsForSAPMcpServerM2MUserPoolIdOutput", OutputValue: "us-east-1_ABC" },
    { OutputKey: "AwsForSAPMcpServerM2MUserPoolClientIdOutput", OutputValue: "client123" },
    { OutputKey: "AwsForSAPMcpServerM2MUserPoolTokenEndpointOutput", OutputValue: "https://cognito/token" },
  ],
  Parameters: [
    { ParameterKey: "InboundAuthProvider", ParameterValue: "Cognito" },
    { ParameterKey: "AuthFlow", ParameterValue: "M2M" },
  ],
}

describe("mapExternalStackInfo", () => {
  test("maps bifrost output keys to typed fields", () => {
    const info = mapExternalStackInfo(RAW, {})
    expect(info.invocationUrl).toBe("https://rt/invoke")
    expect(info.inboundCognito.poolId).toBe("us-east-1_ABC")
    expect(info.inboundCognito.clientId).toBe("client123")
    expect(info.inboundCognito.tokenEndpoint).toBe("https://cognito/token")
    expect(info.inboundAuthProvider).toBe("Cognito")
  })

  test("derives IdP-neutral inbound fields for the Cognito path", () => {
    const info = mapExternalStackInfo(RAW, {
      inbound_cognito: { client_secret_arn: "arn:aws:secretsmanager:us-east-1:111122223333:secret:cog-Ab12Cd" },
    })
    expect(info.inboundClientId).toBe("client123")
    expect(info.inboundDiscoveryUrl).toBe(
      "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_ABC/.well-known/openid-configuration"
    )
    expect(info.inboundClientSecretArn).toBe(
      "arn:aws:secretsmanager:us-east-1:111122223333:secret:cog-Ab12Cd"
    )
  })

  test("derives the Cognito discovery host region from the pool id prefix", () => {
    const euRaw: RawStackDescription = {
      Outputs: [
        { OutputKey: "AwsForSAPMcpServerBedrockAgentCoreInvocationUrlOutput", OutputValue: "https://rt/invoke" },
        { OutputKey: "AwsForSAPMcpServerM2MUserPoolIdOutput", OutputValue: "eu-west-1_XYZ" },
        { OutputKey: "AwsForSAPMcpServerM2MUserPoolClientIdOutput", OutputValue: "client456" },
        { OutputKey: "AwsForSAPMcpServerM2MUserPoolTokenEndpointOutput", OutputValue: "https://cognito-eu/token" },
      ],
      Parameters: [{ ParameterKey: "InboundAuthProvider", ParameterValue: "Cognito" }],
    }
    const info = mapExternalStackInfo(euRaw, {})
    expect(info.inboundDiscoveryUrl).toBe(
      "https://cognito-idp.eu-west-1.amazonaws.com/eu-west-1_XYZ/.well-known/openid-configuration"
    )
  })

  test("uses Entra overrides (not Cognito) when inbound_auth_provider is EntraId", () => {
    const info = mapExternalStackInfo(
      { Outputs: [], Parameters: [] },
      {
        invocation_url: "https://rt/invoke",
        inbound_auth_provider: "EntraId",
        entra_discovery_url:
          "https://login.microsoftonline.com/tenant/v2.0/.well-known/openid-configuration",
        entra_client_id: "entra-client",
        entra_client_secret_arn: "arn:aws:secretsmanager:us-east-1:111122223333:secret:entra-client-secret",
      }
    )
    expect(info.inboundAuthProvider).toBe("EntraId")
    expect(info.inboundDiscoveryUrl).toBe(
      "https://login.microsoftonline.com/tenant/v2.0/.well-known/openid-configuration"
    )
    expect(info.inboundClientId).toBe("entra-client")
    expect(info.inboundClientSecretArn).toBe(
      "arn:aws:secretsmanager:us-east-1:111122223333:secret:entra-client-secret"
    )
  })

  test("throws for EntraId when discovery URL / client id are missing", () => {
    expect(() =>
      mapExternalStackInfo(
        { Outputs: [], Parameters: [] },
        { invocation_url: "https://rt/invoke", inbound_auth_provider: "EntraId" }
      )
    ).toThrow(/EntraId/)
  })

  test("config overrides win over resolved outputs", () => {
    const info = mapExternalStackInfo(RAW, {
      invocation_url: "https://override/invoke",
      inbound_cognito: { client_id: "overrideClient" },
    })
    expect(info.invocationUrl).toBe("https://override/invoke")
    expect(info.inboundCognito.clientId).toBe("overrideClient")
    expect(info.inboundCognito.poolId).toBe("us-east-1_ABC") // not overridden
  })

  test("throws a clear error when a required output is missing", () => {
    const incomplete: RawStackDescription = { Outputs: [], Parameters: [] }
    expect(() => mapExternalStackInfo(incomplete, {})).toThrow(/InvocationUrl/)
  })

  test("throws naming the missing Cognito field when only that is absent", () => {
    const onlyInvocation: RawStackDescription = {
      Outputs: [
        { OutputKey: "AwsForSAPMcpServerBedrockAgentCoreInvocationUrlOutput", OutputValue: "https://rt/invoke" },
        { OutputKey: "AwsForSAPMcpServerM2MUserPoolIdOutput", OutputValue: "us-east-1_ABC" },
        { OutputKey: "AwsForSAPMcpServerM2MUserPoolClientIdOutput", OutputValue: "client123" },
        // token endpoint intentionally omitted
      ],
      Parameters: [],
    }
    expect(() => mapExternalStackInfo(onlyInvocation, {})).toThrow(/token_endpoint/)
  })

  test("rejects an invocation URL that matches no allowed pattern (T13)", () => {
    expect(() =>
      mapExternalStackInfo(RAW, { allowed_endpoint_patterns: ["^https://trusted\\.example\\.com/"] })
    ).toThrow(/allowed_endpoint_patterns/)
  })

  test("accepts an invocation URL that matches an allowed pattern (T13)", () => {
    const info = mapExternalStackInfo(RAW, { allowed_endpoint_patterns: ["^https://rt/"] })
    expect(info.invocationUrl).toBe("https://rt/invoke")
  })
})

describe("validateInvocationUrl (T13)", () => {
  test("accepts https with no patterns", () => {
    expect(() => validateInvocationUrl("https://rt/invoke")).not.toThrow()
  })
  test("rejects non-https endpoints", () => {
    expect(() => validateInvocationUrl("http://rt/invoke")).toThrow(/https/)
  })
  test("enforces the allowlist when provided", () => {
    expect(() =>
      validateInvocationUrl("https://evil.example/invoke", ["^https://rt/"])
    ).toThrow(/allowed_endpoint_patterns/)
    expect(() =>
      validateInvocationUrl("https://rt/invoke", ["^https://rt/"])
    ).not.toThrow()
  })
  test("throws a clear error on an invalid regex pattern", () => {
    expect(() => validateInvocationUrl("https://rt/invoke", ["(unclosed"])).toThrow(/Invalid regex/)
  })
})

describe("assertSecretResolves", () => {
  // Cast: send()'s overloads resolve its arg type to `never` under spyOn.
  const sendSpy = jest.spyOn(
    SecretsManagerClient.prototype,
    "send"
  ) as unknown as jest.SpyInstance
  afterEach(() => sendSpy.mockReset())
  afterAll(() => sendSpy.mockRestore())

  const notFound = Object.assign(new Error("Secrets Manager can't find the specified secret."), {
    name: "ResourceNotFoundException",
  })

  // Regression: this exact truncated ARN shipped in config.yaml and cost a deploy.
  // A string check can't catch it — "dzuf01" is itself six alphanumerics, so the
  // truncated ARN is indistinguishable from a complete one.
  test("rejects an identifier that resolves to no secret", async () => {
    sendSpy.mockRejectedValue(notFound)
    await expect(
      assertSecretResolves(
        "arn:aws:secretsmanager:us-east-1:111122223333:secret:entra-obo-exchange-client-secret-dzuf01",
        "us-east-1"
      )
    ).rejects.toThrow(/resolves to no secret/)
  })

  test("accepts an identifier that resolves", async () => {
    sendSpy.mockResolvedValue({} as never)
    await expect(
      assertSecretResolves(
        "arn:aws:secretsmanager:us-east-1:111122223333:secret:entra-obo-exchange-client-secret-dzuf01-KRbD6g"
      )
    ).resolves.toBeUndefined()
  })

  // The deployer may legitimately lack DescribeSecret; that says nothing about
  // whether the identifier is valid, so synth must not fail on it.
  test("does not block synth on a non-not-found error", async () => {
    sendSpy.mockRejectedValue(
      Object.assign(new Error("denied"), { name: "AccessDeniedException" })
    )
    await expect(assertSecretResolves("some-secret")).resolves.toBeUndefined()
  })

  test("skips the lookup entirely when no ARN is configured", async () => {
    await expect(assertSecretResolves(undefined)).resolves.toBeUndefined()
    expect(sendSpy).not.toHaveBeenCalled()
  })
})
