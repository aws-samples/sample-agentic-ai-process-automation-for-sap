#!/usr/bin/env node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { execFileSync } from "child_process"
import * as fs from "fs"
import * as path from "path"
import * as cdk from "aws-cdk-lib"
import { createStacks } from "../lib/main-stack"
import { ConfigManager } from "../lib/utils/config-manager"
import { resolveExternalStack, ExternalSapMcpStackInfo } from "../lib/utils/cfn-outputs-resolver"

/**
 * Emit .auth-profile-resolved.json BEFORE synth so the inbound/outbound/frontend
 * resolvers (resolve-inbound-authorizer.ts) read the selected profile instead of
 * silently falling back to Cognito. The artifact is git-ignored and written only
 * by run_emit — without this hook a bare `cdk deploy` (make deploy / setup.py)
 * synthesizes a Cognito authorizer for a non-cognito profile, 401ing every token.
 *
 * Runs on the SAME env-or-config inputs run_emit uses in CodeBuild, so all deploy
 * paths (make deploy, setup.py, CodeBuild, cdk synth) are now consistent. A resolve
 * or override error fails synth loud rather than deploying the wrong issuer.
 */
function emitResolvedProfile(): void {
  const repoRoot = path.join(__dirname, "..", "..")
  const script = path.join(repoRoot, "scripts", "deploy", "run_emit.py")
  // Clear any stale artifact first so it is a pure function of the current config.
  // cognito-basic writes nothing only when sap_mcp is disabled; with sap_mcp
  // enabled it emits the BASIC outbound Service-target block.
  fs.rmSync(path.join(repoRoot, ".auth-profile-resolved.json"), { force: true })
  try {
    execFileSync(process.env.PYTHON ?? "python3", [script, "--backend", "cdk"], {
      cwd: repoRoot,
      stdio: ["inherit", "inherit", "pipe"],
    })
  } catch (e: unknown) {
    // In CI synth-check mode (no Python/PyYAML), fall back to cognito-basic (no
    // artifact needed). But ONLY for the default profile: cognito-basic is the
    // one topology whose synth is correct with no artifact. For any other
    // selected profile a silent fallback would synth a Cognito authorizer for a
    // non-cognito issuer and 401 every token — so fail loud instead.
    const stderr = (e as { stderr?: Buffer | string }).stderr?.toString() ?? ""
    if (stderr) process.stderr.write(stderr)
    const msg = (e instanceof Error ? e.message : String(e)) + "\n" + stderr
    const missingPython =
      msg.includes("ENOENT") || msg.includes("MODULE_NOT_FOUND") || msg.includes("No module named")
    const selected = (process.env.AUTH_PROFILE ?? readConfigAuthProfile(repoRoot) ?? "cognito-basic").trim()
    if (missingPython && selected === "cognito-basic") {
      console.warn("run_emit.py unavailable (missing Python or deps) — defaulting to cognito-basic")
      return
    }
    if (missingPython) {
      throw new Error(
        `run_emit.py unavailable (missing Python or deps) but auth_profile is '${selected}' — ` +
          `cannot resolve its issuer, refusing to synth a Cognito fallback that would 401. ` +
          `Install Python + PyYAML, or set auth_profile: cognito-basic.`,
      )
    }
    throw e
  }
}

/** Read the raw `auth_profile:` value from cdk/config.yaml without loading ConfigManager (runs pre-synth). */
function readConfigAuthProfile(repoRoot: string): string | undefined {
  try {
    const cfg = fs.readFileSync(path.join(repoRoot, "cdk", "config.yaml"), "utf-8")
    return cfg.match(/^\s*auth_profile:\s*([^\s#]+)/m)?.[1]
  } catch {
    return undefined
  }
}

async function main() {
  // Resolve the auth profile into the git-ignored artifact the synth consumers read.
  emitResolvedProfile()

  // Load configuration using ConfigManager
  const configManager = new ConfigManager("config.yaml")
  const props = configManager.getProps()

  const app = new cdk.App()

  const env = {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION,
  }

  // The SAP MCP integration is external-only: resolve the AWS-published SAP MCP
  // CFN stack's outputs at synth time so the Gateway target can point at it.
  let externalSapMcp: ExternalSapMcpStackInfo | undefined
  if (props.sap_mcp?.enabled) {
    externalSapMcp = await resolveExternalStack(props.sap_mcp.external_stack!, env.region)
  }

  // Optional context flag to deploy a parallel external-mode SAP MCP stack
  // alongside the primary one (suffixes the stack id + globally-unique names).
  const sapMcpStackSuffix = app.node.tryGetContext("sapMcpStackSuffix") as string | undefined

  // Deploy independent stacks: frontend → cognito → backend.
  // Each is standalone; if backend fails, frontend and cognito remain intact.
  createStacks(app, props, env, externalSapMcp, sapMcpStackSuffix)

  app.synth()
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
