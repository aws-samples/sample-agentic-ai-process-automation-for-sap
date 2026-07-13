// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import * as fs from "fs"
import * as path from "path"

/**
 * Resolve the inbound JWT authorizer's discovery URL + allowed clients from the
 * deploy-time artifact emitted by scripts/deploy/emit_resolved_profile.py.
 *
 * When the artifact is absent (the zero-config cognito-basic default), fall back
 * to the caller-supplied Cognito discovery URL and that call site's client list.
 */

/** Default artifact location: the repo-root .auth-profile-resolved.json. The
 *  AUTH_PROFILE_ARTIFACT env var overrides it (used by tests to point each suite
 *  at its own temp file so the shared repo-root artifact isn't a parallel-run race). */
function defaultArtifactPath(): string {
  return (
    process.env.AUTH_PROFILE_ARTIFACT ??
    path.join(__dirname, "..", "..", "..", ".auth-profile-resolved.json") // nosemgrep: path-join-resolve-traversal
  )
}

export interface InboundAuthorizerResult {
  discoveryUrl: string
  allowedClients: string[]
}

export function resolveInboundAuthorizer(opts: {
  cognitoDiscoveryUrl: string
  fallbackClients: string[]
  artifactPath?: string
}): InboundAuthorizerResult {
  const artifactPath = opts.artifactPath ?? defaultArtifactPath()

  if (!fs.existsSync(artifactPath)) {
    return {
      discoveryUrl: opts.cognitoDiscoveryUrl,
      allowedClients: opts.fallbackClients,
    }
  }

  const artifact = JSON.parse(fs.readFileSync(artifactPath, "utf-8"))
  const ib = artifact.inbound
  if (!ib) {
    // Artifact present for a non-inbound reason (e.g. cognito-m2m emits only an
    // outbound block). No inbound override → use the caller's Cognito values,
    // same as the file-absent path.
    return { discoveryUrl: opts.cognitoDiscoveryUrl, allowedClients: opts.fallbackClients }
  }
  return {
    discoveryUrl: ib.discovery_url,
    allowedClients: ib.allowed_clients,
  }
}

export interface OutboundProfileResult {
  serviceEnabled: boolean
  userEnabled: boolean
  flow?: string
  oboDirectMcp: boolean
  mcpInvocationUrl?: string
}

/** Read the outbound-axis block from the deploy-time artifact. Absent artifact or
 *  absent `outbound` block → both variants disabled (no SAP MCP target). */
export function resolveOutboundProfile(opts?: { artifactPath?: string }): OutboundProfileResult {
  const artifactPath = opts?.artifactPath ?? defaultArtifactPath()
  if (!fs.existsSync(artifactPath)) {
    return { serviceEnabled: false, userEnabled: false, oboDirectMcp: false }
  }
  const artifact = JSON.parse(fs.readFileSync(artifactPath, "utf-8"))
  const ob = artifact.outbound
  if (!ob) {
    return { serviceEnabled: false, userEnabled: false, oboDirectMcp: false }
  }
  return {
    serviceEnabled: ob.service_enabled === true,
    userEnabled: ob.user_enabled === true,
    flow: ob.flow,
    oboDirectMcp: ob.obo_direct_mcp === true,
    mcpInvocationUrl: ob.mcp_invocation_url,
  }
}

export interface ModeProfileResult {
  batchRunnerEnabled: boolean
  modes: string[]
}

/** Read the mode-axis block from the deploy-time artifact. Absent artifact or
 *  absent `mode` block → batch runner disabled (autonomous/live topology). */
export function resolveModeProfile(opts?: { artifactPath?: string }): ModeProfileResult {
  const artifactPath = opts?.artifactPath ?? defaultArtifactPath()
  if (!fs.existsSync(artifactPath)) {
    return { batchRunnerEnabled: false, modes: [] }
  }
  const artifact = JSON.parse(fs.readFileSync(artifactPath, "utf-8"))
  const m = artifact.mode
  if (!m) {
    return { batchRunnerEnabled: false, modes: [] }
  }
  return { batchRunnerEnabled: m.batch_runner_enabled === true, modes: m.modes ?? [] }
}
