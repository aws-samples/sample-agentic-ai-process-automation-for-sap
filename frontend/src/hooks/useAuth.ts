// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

"use client"
import { useAuth as useOidcAuth } from "react-oidc-context"
import { useEffect, useState } from "react"
import { createCognitoAuthConfig, type CognitoAuthConfig } from "@/lib/auth"

export function useAuth() {
  const auth = useOidcAuth()
  const [authConfig, setAuthConfig] = useState<CognitoAuthConfig | null>(null)

  useEffect(() => {
    async function loadConfig() {
      try {
        const config = await createCognitoAuthConfig()
        setAuthConfig(config)
      } catch (error) {
        console.error("Failed to load auth configuration for signOut:", error)
      }
    }

    loadConfig()
  }, [])

  // react-oidc-context returns undefined (not a throw) if called outside AuthProvider; fall back to an authenticated no-op state.
  if (!auth) {
    return {
      isAuthenticated: true,
      user: null,
      signIn: () => {},
      signOut: () => {},
      isLoading: false,
      error: null,
      token: null,
      profile: null,
    }
  }

  return {
    isAuthenticated: auth.isAuthenticated,
    user: auth.user,
    signIn: auth.signinRedirect,
    signOut: () => {
      const clientId = authConfig?.client_id || import.meta.env.VITE_COGNITO_CLIENT_ID || ""
      const logoutUri =
        authConfig?.redirect_uri ||
        import.meta.env.VITE_COGNITO_REDIRECT_URI ||
        "http://localhost:3000"

      auth.signoutRedirect({
        extraQueryParams: {
          client_id: clientId,
          logout_uri: logoutUri,
        },
      })
    },
    isLoading: auth.isLoading,
    error: auth.error,
    token: auth.user?.id_token,
    profile: auth.user?.profile ?? null,
  }
}
