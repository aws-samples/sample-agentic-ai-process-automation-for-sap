// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from "aws-cdk-lib"
import * as cognito from "aws-cdk-lib/aws-cognito"
import { Construct } from "constructs"
import { SapFederationConfig } from "../utils/config-manager"

export interface SapFederationClientProps {
  /** The product user-facing pool (NOT the SAP MCP inbound pool). */
  userPool: cognito.IUserPool
  /**
   * Normalized federation config (enabled, ias_redirect_uri, mapping_claim).
   * Note: mapping_claim is consumed on the SAP IAS side (the IAS identity mapper),
   * not by this construct — it is carried in config for the runbook/operator only.
   */
  federation: SapFederationConfig
  /** Used to name/export outputs consistently with the rest of the stack. */
  stackNameBase: string
}

/**
 * Provisions the IAS-facing Cognito app client for "same sub" OBO federation.
 *
 * IAS consumes this pool as an OIDC corporate IdP: it needs a confidential
 * authorization_code client whose callback list includes the IAS redirect URI.
 * The SAP admin registers the emitted discovery URL + client id (and the
 * generated secret, fetched out-of-band) in IAS. See
 * docs/sap/SAP_MCP_SAME_SUB_FEDERATION.md.
 */
export class SapFederationClient extends Construct {
  public readonly clientId: string

  constructor(scope: Construct, id: string, props: SapFederationClientProps) {
    super(scope, id)

    const stack = cdk.Stack.of(this)
    const iasRedirectUri = props.federation.ias_redirect_uri
    if (!iasRedirectUri) {
      throw new Error(
        "SapFederationClient requires federation.ias_redirect_uri to be set. " +
          "ConfigManager normally enforces this when federation.enabled is true."
      )
    }

    const client = new cognito.UserPoolClient(this, "IasFederationClient", {
      userPool: props.userPool,
      userPoolClientName: `${props.stackNameBase}-ias-federation-client`,
      generateSecret: true,
      oAuth: {
        flows: { authorizationCodeGrant: true },
        scopes: [
          cognito.OAuthScope.OPENID,
          cognito.OAuthScope.EMAIL,
          cognito.OAuthScope.PROFILE,
        ],
        callbackUrls: [iasRedirectUri],
        // No logoutUrls: IAS consumes this client programmatically as an OIDC
        // corporate IdP — there is no human logout redirect through this leg.
      },
      preventUserExistenceErrors: true,
    })

    this.clientId = client.userPoolClientId

    new cdk.CfnOutput(this, "FederationDiscoveryUrl", {
      value: `https://cognito-idp.${stack.region}.amazonaws.com/${props.userPool.userPoolId}/.well-known/openid-configuration`,
      description: "OIDC discovery URL to register Cognito as a corporate IdP in SAP IAS",
      exportName: `${props.stackNameBase}-FederationDiscoveryUrl`,
    })

    new cdk.CfnOutput(this, "FederationClientId", {
      value: this.clientId,
      description: "Cognito app client id for IAS to consume (same-sub federation)",
      exportName: `${props.stackNameBase}-FederationClientId`,
    })
  }
}
