// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

"use client"

import { createCognitoAuthConfig, cognitoAuthConfig, type CognitoAuthConfig } from "@/lib/auth"
import { useEffect, useState, PropsWithChildren } from "react"
import { AuthProvider as OidcAuthProvider } from "react-oidc-context"
import { AutoSignin } from "./AutoSignin"

const AuthProvider = ({ children }: PropsWithChildren) => {
  const [authConfig, setAuthConfig] = useState<CognitoAuthConfig | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function loadConfig() {
      try {
        const config = await createCognitoAuthConfig()
        setAuthConfig(config)
      } catch (error) {
        console.error("Failed to load auth configuration:", error)
        console.error("Falling back to environment variables")
        setAuthConfig(cognitoAuthConfig)
      } finally {
        setLoading(false)
      }
    }

    loadConfig()
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen text-xl">
        Loading authentication configuration...
      </div>
    )
  }

  if (!authConfig) {
    return (
      <div className="flex items-center justify-center min-h-screen text-xl">
        Failed to load authentication configuration
      </div>
    )
  }

  return (
    <OidcAuthProvider
      {...authConfig}
      // This callback removes the `?code=` from the URL, which will break page refreshes
      onSigninCallback={() => {
        window.history.replaceState({}, document.title, window.location.pathname)
      }}
    >
      <AutoSignin>{children}</AutoSignin>
    </OidcAuthProvider>
  )
}

export { AuthProvider }
