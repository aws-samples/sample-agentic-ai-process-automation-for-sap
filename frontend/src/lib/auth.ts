// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { WebStorageStateStore } from "oidc-client-ts"
import { getConfig } from "./config"

/** Shape of the OIDC config produced by {@link createCognitoAuthConfig}. */
export interface CognitoAuthConfig {
  authority?: string
  metadataUrl?: string
  client_id?: string
  redirect_uri?: string
  post_logout_redirect_uri?: string
  response_type?: string
  scope?: string
  automaticSilentRenew?: boolean
  userStore?: WebStorageStateStore
}

/**
 * Creates OIDC auth config from aws-exports.json (via shared config loader).
 * Environment variables (VITE_COGNITO_*) override if set.
 */
export async function createCognitoAuthConfig() {
  const cfg = await getConfig()

  const redirectUri = import.meta.env.VITE_COGNITO_REDIRECT_URI
  const postLogoutRedirectUri = import.meta.env.VITE_COGNITO_POST_LOGOUT_REDIRECT_URI

  return {
    authority:
      import.meta.env.VITE_COGNITO_REGION && import.meta.env.VITE_COGNITO_USER_POOL_ID
        ? `https://cognito-idp.${import.meta.env.VITE_COGNITO_REGION}.amazonaws.com/${import.meta.env.VITE_COGNITO_USER_POOL_ID}`
        : cfg.authority,
    metadataUrl: cfg.metadataUrl,
    client_id: import.meta.env.VITE_COGNITO_CLIENT_ID || cfg.client_id,
    redirect_uri: redirectUri || cfg.redirect_uri,
    post_logout_redirect_uri: postLogoutRedirectUri || redirectUri || cfg.post_logout_redirect_uri,
    response_type: import.meta.env.VITE_COGNITO_RESPONSE_TYPE || cfg.response_type || "code",
    scope: import.meta.env.VITE_COGNITO_SCOPE || cfg.scope || "email openid profile",
    automaticSilentRenew:
      import.meta.env.VITE_COGNITO_AUTOMATIC_SILENT_RENEW === "false"
        ? false
        : import.meta.env.VITE_COGNITO_AUTOMATIC_SILENT_RENEW === "true"
          ? true
          : (cfg.automaticSilentRenew ?? true),
    userStore:
      typeof window !== "undefined"
        ? new WebStorageStateStore({ store: window.localStorage })
        : undefined,
  }
}

// Synchronous version for backwards compatibility (uses env vars as fallback)
export const cognitoAuthConfig = {
  authority: `https://cognito-idp.${import.meta.env.VITE_COGNITO_REGION}.amazonaws.com/${import.meta.env.VITE_COGNITO_USER_POOL_ID}`,
  client_id: import.meta.env.VITE_COGNITO_CLIENT_ID,
  redirect_uri: import.meta.env.VITE_COGNITO_REDIRECT_URI,
  post_logout_redirect_uri: import.meta.env.VITE_COGNITO_REDIRECT_URI,
  response_type: "code",
  scope: "email openid profile",
  automaticSilentRenew: true,
  userStore:
    typeof window !== "undefined"
      ? new WebStorageStateStore({ store: window.localStorage })
      : undefined,
}
