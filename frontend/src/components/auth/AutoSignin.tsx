// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { ReactNode, useEffect, useRef, useState, PropsWithChildren } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { useAuth } from "react-oidc-context"
import { Sparkles, ArrowRight } from "lucide-react"
import { Button } from "@/components/ui/button"
import { clearOperatorContext } from "@/lib/signOut"

function AutoSigninContent({ children }: PropsWithChildren) {
  const auth = useAuth()
  const queryClient = useQueryClient()

  // Drop the previous operator's cases, transcript, and focused-case URL whenever the
  // session ends. Hung on the authenticated→unauthenticated edge rather than on the
  // sign-out button, so an expired or revoked session wipes the same residue — and so
  // a failed sign-out redirect cannot leave it on screen for whoever signs in next.
  const wasAuthenticated = useRef(false)
  useEffect(() => {
    if (auth.isLoading) return
    if (auth.isAuthenticated) {
      wasAuthenticated.current = true
      return
    }
    if (!wasAuthenticated.current) return
    wasAuthenticated.current = false
    clearOperatorContext(queryClient)
  }, [auth.isAuthenticated, auth.isLoading, queryClient])

  if (auth.isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-muted border-t-foreground" />
      </div>
    )
  }

  if (!auth.isAuthenticated) {
    return (
      <div className="flex min-h-screen items-center justify-center px-6">
        <div className="animate-rise-in w-full max-w-sm rounded-xl border bg-card p-8 shadow-sm">
          <span
            className="mb-6 inline-flex h-11 w-11 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm"
            aria-hidden
          >
            <Sparkles size={20} />
          </span>
          <h1 className="font-display text-2xl font-semibold tracking-tight text-foreground">
            Welcome back
          </h1>
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
            Sign in to triage SAP exceptions, watch the agent work in real time, and clear your
            queue faster.
          </p>
          <Button onClick={() => auth.signinRedirect()} className="group mt-6 h-10 w-full">
            Sign In
            <ArrowRight size={16} className="transition-transform group-hover:translate-x-0.5" />
          </Button>
        </div>
      </div>
    )
  }

  return <>{children}</>
}

export function AutoSignin({ children }: { children: ReactNode }) {
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    setMounted(true)
  }, [])

  if (!mounted) {
    return null
  }

  return <AutoSigninContent>{children}</AutoSigninContent>
}
