// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

"use client"

import { useState } from "react"
import {
  Wrench,
  Loader2,
  CheckCircle2,
  ChevronRight,
  ChevronDown,
  ShieldAlert,
  ExternalLink,
} from "lucide-react"
import type { ToolRenderProps } from "@/hooks/useToolRenderer"

/**
 * An "authentication_required" tool result is a NORMAL tool result (isError:false);
 * the `auth_url` is application-layer JSON inside the result text, not an HTTP redirect.
 */
interface AuthRequired {
  message?: string
  authUrl: string
}

/** Returns auth-required details if `result` is JSON signaling auth is needed, else null. */
export function parseAuthRequired(result: string | undefined): AuthRequired | null {
  if (!result) return null
  let parsed: unknown
  try {
    parsed = JSON.parse(result)
  } catch {
    return null
  }
  if (typeof parsed !== "object" || parsed === null) return null
  const data = (parsed as { data?: unknown }).data
  if (typeof data !== "object" || data === null) return null
  const d = data as { error_type?: unknown; requires_user_action?: unknown; auth_url?: unknown }
  // Only accept https URLs: this value comes from a semi-trusted external MCP server and
  // flows into window.open(), where a javascript:/data: URL would be a DOM-XSS sink.
  const authUrl =
    typeof d.auth_url === "string" && /^https:\/\//i.test(d.auth_url) ? d.auth_url : undefined
  const isAuthRequired =
    d.error_type === "authentication_required" || d.requires_user_action === true
  if (!isAuthRequired || !authUrl) return null
  const message = (parsed as { message?: unknown }).message
  return {
    authUrl,
    message: typeof message === "string" ? message : undefined,
  }
}

export function ToolCallDisplay({ name, args, status, result }: ToolRenderProps) {
  const [expanded, setExpanded] = useState(false)
  const authRequired = parseAuthRequired(result)

  return (
    <div className="my-1 text-sm">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1.5 px-2 py-1 rounded-md hover:bg-accent transition-colors w-full text-left"
      >
        {expanded ? (
          <ChevronDown size={12} className="text-muted-foreground" />
        ) : (
          <ChevronRight size={12} className="text-muted-foreground" />
        )}
        <Wrench size={12} className="text-muted-foreground" />
        <span className="text-foreground">{name}</span>
        {status === "streaming" && (
          <Loader2 size={12} className="animate-spin text-blue-500 ml-auto" />
        )}
        {status === "executing" && (
          <Loader2 size={12} className="animate-spin text-amber-500 ml-auto" />
        )}
        {status === "complete" && !authRequired && (
          <CheckCircle2 size={12} className="text-green-500 ml-auto" />
        )}
        {authRequired && <ShieldAlert size={12} className="text-amber-500 ml-auto" />}
      </button>

      {authRequired && (
        <div className="ml-6 mt-1 rounded-md border border-amber-200 bg-amber-50 p-3 space-y-2">
          <div className="flex items-center gap-1.5 text-amber-800 font-medium">
            <ShieldAlert size={14} />
            <span>Sign in to SAP required</span>
          </div>
          <p className="text-xs text-amber-700">
            {authRequired.message ||
              "Authentication required. Please authenticate using the link below. Retry once authenticated."}
          </p>
          <button
            type="button"
            onClick={() =>
              // Popup (not a new tab) so the workspace tab + chat state stay alive.
              // The callback page posts back to window.opener; WorkspacePage auto-resumes.
              window.open(
                authRequired.authUrl,
                "sapAuth",
                "width=480,height=700,menubar=no,toolbar=no"
              )
            }
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-amber-600 text-white text-xs font-medium hover:bg-amber-700 transition-colors"
          >
            <ExternalLink size={12} />
            Sign in to SAP
          </button>
          <p className="text-xs text-amber-600">
            After signing in, this window continues automatically.
          </p>
        </div>
      )}

      {expanded && !authRequired && (
        <div className="ml-6 mt-1 border-l-2 border-border pl-3 space-y-2">
          {args && (
            <div>
              <div className="text-xs text-muted-foreground">Input</div>
              <pre className="text-xs text-foreground whitespace-pre-wrap break-words mt-0.5">
                {args}
              </pre>
            </div>
          )}
          {result && (
            <div>
              <div className="text-xs text-muted-foreground">Result</div>
              <pre className="text-xs text-foreground whitespace-pre-wrap break-words mt-0.5">
                {result}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
