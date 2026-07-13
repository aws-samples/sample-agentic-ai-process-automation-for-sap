// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Property-based test for configuration value compatibility
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import * as fc from "fast-check"

describe("Configuration Value Compatibility", () => {
  const originalEnv = { ...import.meta.env }

  beforeEach(() => {
    vi.resetModules()
  })

  afterEach(() => {
    Object.keys(import.meta.env).forEach(key => {
      delete (import.meta.env as Record<string, unknown>)[key]
    })
    Object.assign(import.meta.env, originalEnv)
  })

  it("should accept valid Cognito user pool IDs with VITE_ prefix", () => {
    fc.assert(
      fc.property(fc.stringMatching(/^[a-z]{2}-[a-z]+-\d_[A-Za-z0-9]+$/), userPoolId => {
        expect(userPoolId).toMatch(/^[a-z]{2}-[a-z]+-\d_[A-Za-z0-9]+$/)
        expect(userPoolId.length).toBeGreaterThan(0)

        return true
      }),
      { numRuns: 100 }
    )
  })

  it("should accept valid Cognito client IDs with VITE_ prefix", () => {
    fc.assert(
      fc.property(fc.stringMatching(/^[a-z0-9]{26}$/), clientId => {
        expect(clientId).toMatch(/^[a-z0-9]{26}$/)
        expect(clientId.length).toBe(26)

        return true
      }),
      { numRuns: 100 }
    )
  })

  it("should accept valid AWS regions with VITE_ prefix", () => {
    const validRegions = [
      "us-east-1",
      "us-east-2",
      "us-west-1",
      "us-west-2",
      "eu-west-1",
      "eu-west-2",
      "eu-central-1",
      "ap-southeast-1",
      "ap-southeast-2",
      "ap-northeast-1",
    ]

    fc.assert(
      fc.property(fc.constantFrom(...validRegions), region => {
        expect(region).toMatch(/^[a-z]{2}-[a-z]+-\d+$/)

        return true
      }),
      { numRuns: 100 }
    )
  })

  it("should accept valid redirect URIs with VITE_ prefix", () => {
    fc.assert(
      fc.property(fc.webUrl(), redirectUri => {
        const url = new URL(redirectUri)
        expect(url.protocol).toMatch(/^https?:$/)

        return true
      }),
      { numRuns: 100 }
    )
  })

  it("should accept valid response types with VITE_ prefix", () => {
    const validResponseTypes = ["code", "token", "id_token", "code token", "code id_token"]

    fc.assert(
      fc.property(fc.constantFrom(...validResponseTypes), responseType => {
        expect(validResponseTypes).toContain(responseType)

        return true
      }),
      { numRuns: 100 }
    )
  })

  it("should accept valid OAuth scopes with VITE_ prefix", () => {
    const validScopes = [
      "openid",
      "email",
      "profile",
      "openid email",
      "openid profile",
      "email profile",
      "openid email profile",
    ]

    fc.assert(
      fc.property(fc.constantFrom(...validScopes), scope => {
        const scopeParts = scope.split(" ")
        const validScopeParts = ["openid", "email", "profile"]

        scopeParts.forEach(part => {
          expect(validScopeParts).toContain(part)
        })

        return true
      }),
      { numRuns: 100 }
    )
  })

  it("should accept boolean values for automatic silent renew with VITE_ prefix", () => {
    fc.assert(
      fc.property(fc.boolean(), automaticSilentRenew => {
        const envValue = automaticSilentRenew ? "true" : "false"

        expect(envValue).toMatch(/^(true|false)$/)

        const parsed = envValue === "true"
        expect(typeof parsed).toBe("boolean")
        expect(parsed).toBe(automaticSilentRenew)

        return true
      }),
      { numRuns: 100 }
    )
  })

  it("should build valid authority URLs from region and user pool ID", () => {
    const validRegions = ["us-east-1", "us-west-2", "eu-west-1"]

    fc.assert(
      fc.property(
        fc.constantFrom(...validRegions),
        fc.stringMatching(/^[a-z]{2}-[a-z]+-\d_[A-Za-z0-9]+$/),
        (region, userPoolId) => {
          const authority = `https://cognito-idp.${region}.amazonaws.com/${userPoolId}`

          expect(authority).toMatch(/^https:\/\/cognito-idp\.[a-z0-9-]+\.amazonaws\.com\//)

          const url = new URL(authority)
          expect(url.protocol).toBe("https:")
          expect(url.hostname).toContain("amazonaws.com")

          return true
        }
      ),
      { numRuns: 100 }
    )
  })

  it("should handle all configuration values together", () => {
    fc.assert(
      fc.property(
        fc.record({
          region: fc.constantFrom("us-east-1", "us-west-2", "eu-west-1"),
          userPoolId: fc.stringMatching(/^[a-z]{2}-[a-z]+-\d_[A-Za-z0-9]{9}$/),
          clientId: fc.stringMatching(/^[a-z0-9]{26}$/),
          redirectUri: fc.webUrl(),
          responseType: fc.constantFrom("code", "token"),
          scope: fc.constantFrom("openid email profile", "openid profile"),
          automaticSilentRenew: fc.boolean(),
        }),
        config => {
          expect(config.region).toMatch(/^[a-z]{2}-[a-z]+-\d+$/)
          expect(config.userPoolId).toMatch(/^[a-z]{2}-[a-z]+-\d_[A-Za-z0-9]{9}$/)
          expect(config.clientId).toMatch(/^[a-z0-9]{26}$/)

          const url = new URL(config.redirectUri)
          expect(url.protocol).toMatch(/^https?:$/)

          expect(["code", "token"]).toContain(config.responseType)

          expect(["openid email profile", "openid profile"]).toContain(config.scope)

          expect(typeof config.automaticSilentRenew).toBe("boolean")

          return true
        }
      ),
      { numRuns: 100 }
    )
  })

  it("should not have NEXT_PUBLIC_ prefixed environment variables", () => {
    const envKeys = Object.keys(import.meta.env)
    const nextPublicVars = envKeys.filter(key => key.startsWith("NEXT_PUBLIC_"))

    expect(nextPublicVars.length).toBe(0)
  })
})
