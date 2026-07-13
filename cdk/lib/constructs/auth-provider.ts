// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from "aws-cdk-lib"
import * as ssm from "aws-cdk-lib/aws-ssm"
import { Construct } from "constructs"
import type { AppConfig, AuthProvider } from "../utils/config-manager"

/**
 * Modular auth provider construct.
 *
 * Provisions identity configuration based on `sap.auth_provider` in config.yaml.
 * The frontend reads OIDC config from SSM/aws-exports.json — swapping providers
 * requires only a config change, no code changes.
 *
 * Modes:
 *   cognito     – Uses the Cognito User Pool created by the Cognito stack (default)
 *   okta        – External Okta OIDC provider
 *   custom-oidc – Any OIDC-compliant provider
 */
export class AuthProviderConstruct extends Construct {
  public readonly provider: AuthProvider

  constructor(scope: Construct, id: string, config: AppConfig) {
    super(scope, id)

    this.provider = config.sap?.auth_provider || "cognito"
    const auth = config.sap?.auth || {}

    const stackNameBase = config.stack_name_base

    // Store provider type so frontend/backend can branch if needed
    new ssm.StringParameter(this, "AuthProviderParam", {
      parameterName: `/${stackNameBase}/auth/provider`,
      stringValue: this.provider,
    })

    switch (this.provider) {
      case "cognito":
        // Cognito is already provisioned by the Cognito stack's machine-authentication setup.
        // Nothing extra needed — SSM params already exist.
        break

      case "okta":
      case "custom-oidc":
        if (!auth.issuer_url || !auth.client_id) {
          throw new Error(
            `sap.auth.issuer_url and sap.auth.client_id are required for auth_provider '${this.provider}'.`
          )
        }
        new ssm.StringParameter(this, "OidcIssuerParam", {
          parameterName: `/${stackNameBase}/auth/issuer-url`,
          stringValue: auth.issuer_url,
        })
        new ssm.StringParameter(this, "OidcClientIdParam", {
          parameterName: `/${stackNameBase}/auth/client-id`,
          stringValue: auth.client_id,
        })
        if (auth.scopes) {
          new ssm.StringParameter(this, "OidcScopesParam", {
            parameterName: `/${stackNameBase}/auth/scopes`,
            stringValue: auth.scopes,
          })
        }
        break
    }
  }
}
