// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

"use client"

import { useEffect } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { CheckCircle2, AlertTriangle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"

/**
 * Landing page for the SAP USER_FEDERATION (OBO) browser redirect.
 *
 * After a user opens the AgentCore `auth_url` and completes SAP sign-in, the
 * AgentCore callback redirects the browser here (route path must end in
 * `/callback` per the AgentCore validator constraint). The token exchange is
 * completed server-side by AgentCore + the runtime — this page only signals
 * completion and lets the user return to their conversation to retry.
 *
 * NOTE: this is SEPARATE from the app's own Cognito/OIDC login (useAuth).
 */
export default function SapAuthCallback() {
  const [params] = useSearchParams()

  const error = params.get("error")
  const errorDescription = params.get("error_description")

  // When opened as a popup (the "Sign in to SAP" button), tell the workspace tab
  // that auth is done so it can auto-resume, then close ourselves. Origin-pinned.
  // If this was a top-level navigation instead, window.opener is null and
  // window.close() is a no-op — the Card + "Return to workspace" link is the fallback.
  useEffect(() => {
    if (error) return
    window.opener?.postMessage({ type: "sap-auth-complete" }, window.location.origin)
    window.close()
  }, [error])

  return (
    <div className="flex items-center justify-center h-full p-6">
      <Card className="max-w-md w-full p-6 text-center space-y-4">
        {error ? (
          <>
            <AlertTriangle size={40} className="text-red-500 mx-auto" />
            <h1 className="text-lg font-semibold text-gray-900">SAP sign-in failed</h1>
            <p className="text-sm text-gray-600">
              {errorDescription || error || "An error occurred during SAP authentication."}
            </p>
            <p className="text-sm text-gray-500">
              Return to your conversation and try your request again to restart sign-in.
            </p>
          </>
        ) : (
          <>
            <CheckCircle2 size={40} className="text-green-500 mx-auto" />
            <h1 className="text-lg font-semibold text-gray-900">SAP sign-in complete</h1>
            <p className="text-sm text-gray-600">
              You can return to your conversation and retry your request.
            </p>
          </>
        )}
        <Button asChild className="w-full">
          <Link to="/">Return to workspace</Link>
        </Button>
      </Card>
    </div>
  )
}
