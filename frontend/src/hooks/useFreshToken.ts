// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useCallback } from "react"
import { useAuth } from "react-oidc-context"

export interface FreshTokens {
  /** Identity token — send to our own REST API (Cognito/JWT authorizer validates it). */
  idToken?: string
  /** OAuth2 access token — send to the AgentCore Runtime (its JWT authorizer checks client_id/aud on this one). */
  accessToken?: string
}

/**
 * Returns a getter for fresh id/access tokens, silently refreshing if the current
 * ones are expired or about to expire. One `signinSilent()` call refreshes both,
 * since they come from the same OIDC session.
 *
 * `automaticSilentRenew` keeps tokens fresh in the background, but its timer can
 * be throttled while the tab is backgrounded — a user returning from an idle tab
 * and immediately triggering a request can still hit a stale token. Call this
 * right before any authenticated request rather than reading `auth.user?.id_token`
 * / `auth.user?.access_token` directly.
 */
export function useFreshToken() {
  const auth = useAuth()
  return useCallback(async (): Promise<FreshTokens> => {
    const user = auth.user
    if (!user) return {}
    if (user.expired || (user.expires_in !== undefined && user.expires_in < 60)) {
      try {
        const refreshed = await auth.signinSilent()
        return { idToken: refreshed?.id_token, accessToken: refreshed?.access_token }
      } catch {
        // Already expired and renewal failed: the old tokens are unusable, so
        // report no tokens rather than hand back ones that will just 401 downstream.
        // Still within the pre-expiry buffer: they remain valid for a few more
        // seconds, so keep using them until the background renew catches up.
        if (user.expired) return {}
        return { idToken: user.id_token, accessToken: user.access_token }
      }
    }
    return { idToken: user.id_token, accessToken: user.access_token }
  }, [auth])
}
