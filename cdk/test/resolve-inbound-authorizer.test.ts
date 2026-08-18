// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { execFileSync } from "child_process"
import * as fs from "fs"
import * as os from "os"
import * as path from "path"
import {
  resolveInboundAuthorizer,
  resolveModeProfile,
  resolveOutboundProfile,
} from "../lib/utils/resolve-inbound-authorizer"

const COGNITO_URL =
  "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_ABC123/.well-known/openid-configuration"

describe("resolveInboundAuthorizer", () => {
  it("falls back to Cognito values when the artifact is absent", () => {
    const out = resolveInboundAuthorizer({
      cognitoDiscoveryUrl: COGNITO_URL,
      fallbackClients: ["webclient123"],
      artifactPath: path.join(os.tmpdir(), "does-not-exist-xyz.json"),
    })
    expect(out).toEqual({ discoveryUrl: COGNITO_URL, allowedClients: ["webclient123"] })
  })

  it("reads discovery_url and allowed_clients from the artifact when present", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "authprof-"))
    const artifactPath = path.join(dir, ".auth-profile-resolved.json")
    fs.writeFileSync(
      artifactPath,
      JSON.stringify({
        profile: "entra-preview-fixture",
        inbound: {
          issuer_type: "entra",
          discovery_url: "https://login.microsoftonline.com/T/v2.0/.well-known/openid-configuration",
          allowed_clients: ["entra-app-id"],
        },
      }),
    )
    const out = resolveInboundAuthorizer({
      cognitoDiscoveryUrl: COGNITO_URL,
      fallbackClients: ["webclient123"],
      artifactPath,
    })
    expect(out).toEqual({
      discoveryUrl: "https://login.microsoftonline.com/T/v2.0/.well-known/openid-configuration",
      allowedClients: ["entra-app-id"],
    })
  })

  it("falls back to Cognito values when the artifact has no inbound block (cognito-m2m)", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "authprof-noinbound-"))
    const artifactPath = path.join(dir, ".auth-profile-resolved.json")
    // Shape emitted by run_emit for cognito-m2m: outbound block, NO inbound key.
    fs.writeFileSync(
      artifactPath,
      JSON.stringify({
        profile: "cognito-m2m",
        maturity: "ga",
        outbound: { flow: "M2M", service_enabled: true, user_enabled: false, issuer_type: "sap" },
      }),
    )
    const out = resolveInboundAuthorizer({
      cognitoDiscoveryUrl: COGNITO_URL,
      fallbackClients: ["webclient123"],
      artifactPath,
    })
    expect(out).toEqual({ discoveryUrl: COGNITO_URL, allowedClients: ["webclient123"] })
  })
})

describe("entra inbound producer↔consumer contract (run_emit → resolveInboundAuthorizer)", () => {
  it("run_emit('entra-obo') emits an inbound block the TS resolver reads as Entra values", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "entra-contract-"))
    const artifactPath = path.join(dir, ".auth-profile-resolved.json")
    const repoRoot = path.join(__dirname, "..", "..")
    // Drive the real Python emitter into a temp artifact (hermetic: no AWS, no network).
    const py = `
import sys
sys.path.insert(0, r"${path.join(repoRoot, "scripts", "deploy")}")
from run_emit import run_emit
run_emit(
    "entra-obo",
    overrides={
        "discovery_url": "https://login.microsoftonline.com/T/v2.0/.well-known/openid-configuration",
        "allowed_clients": ["entra-app-id"],
    },
    out_path=r"${artifactPath}",
)
`
    execFileSync(process.env.PYTHON ?? "python3", ["-c", py], { cwd: repoRoot, stdio: "pipe" })
    const out = resolveInboundAuthorizer({
      cognitoDiscoveryUrl: COGNITO_URL,
      fallbackClients: ["webclient123"],
      artifactPath,
    })
    expect(out).toEqual({
      discoveryUrl:
        "https://login.microsoftonline.com/T/v2.0/.well-known/openid-configuration",
      allowedClients: ["entra-app-id"],
    })
  })

  // Both the Runtime and Gateway authorizers call the same resolver; one Entra
  // artifact must flip both to Entra values regardless of fallback shape.
  it("the Entra inbound block drives both authorizer call-site shapes to Entra values", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "entra-contract-"))
    const artifactPath = path.join(dir, ".auth-profile-resolved.json")
    const repoRoot = path.join(__dirname, "..", "..")
    const py = `
import sys
sys.path.insert(0, r"${path.join(repoRoot, "scripts", "deploy")}")
from run_emit import run_emit
run_emit(
    "entra-obo",
    overrides={
        "discovery_url": "https://login.microsoftonline.com/T/v2.0/.well-known/openid-configuration",
        "allowed_clients": ["entra-app-id"],
    },
    out_path=r"${artifactPath}",
)
`
    execFileSync(process.env.PYTHON ?? "python3", ["-c", py], { cwd: repoRoot, stdio: "pipe" })
    const entra = {
      discoveryUrl:
        "https://login.microsoftonline.com/T/v2.0/.well-known/openid-configuration",
      allowedClients: ["entra-app-id"],
    }
    // Runtime call site: fallback [webClient, machineClient].
    expect(
      resolveInboundAuthorizer({
        cognitoDiscoveryUrl: COGNITO_URL,
        fallbackClients: ["webclient123", "machineclient456"],
        artifactPath,
      }),
    ).toEqual(entra)
    // Gateway call site: fallback [machineClient].
    expect(
      resolveInboundAuthorizer({
        cognitoDiscoveryUrl: COGNITO_URL,
        fallbackClients: ["machineclient456"],
        artifactPath,
      }),
    ).toEqual(entra)
  })
})

describe("okta inbound producer↔consumer contract (run_emit → resolveInboundAuthorizer)", () => {
  const OKTA_URL = "https://dev.okta.com/oauth2/default/.well-known/openid-configuration"

  it("run_emit('okta-userfed') emits an inbound block the TS resolver reads as Okta values", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "okta-contract-"))
    const artifactPath = path.join(dir, ".auth-profile-resolved.json")
    const repoRoot = path.join(__dirname, "..", "..")
    // Drive the real Python emitter into a temp artifact (hermetic: no AWS, no network).
    const py = `
import sys
sys.path.insert(0, r"${path.join(repoRoot, "scripts", "deploy")}")
from run_emit import run_emit
run_emit(
    "okta-userfed",
    overrides={
        "discovery_url": "${OKTA_URL}",
        "allowed_clients": ["okta-app-id"],
    },
    out_path=r"${artifactPath}",
)
`
    execFileSync(process.env.PYTHON ?? "python3", ["-c", py], { cwd: repoRoot, stdio: "pipe" })
    const out = resolveInboundAuthorizer({
      cognitoDiscoveryUrl: COGNITO_URL,
      fallbackClients: ["webclient123"],
      artifactPath,
    })
    expect(out).toEqual({ discoveryUrl: OKTA_URL, allowedClients: ["okta-app-id"] })
  })

  it("a custom Okta auth-server discovery URL round-trips verbatim through the seam", () => {
    // Okta org-level and custom auth-server (/oauth2/<id>/...) URLs differ in shape;
    // the authorizer must pass discovery_url through untouched either way.
    const CUSTOM_URL = "https://dev.okta.com/oauth2/aus1abc/.well-known/openid-configuration"
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "okta-custom-"))
    const artifactPath = path.join(dir, ".auth-profile-resolved.json")
    const repoRoot = path.join(__dirname, "..", "..")
    const py = `
import sys
sys.path.insert(0, r"${path.join(repoRoot, "scripts", "deploy")}")
from run_emit import run_emit
run_emit(
    "okta-userfed",
    overrides={
        "discovery_url": "${CUSTOM_URL}",
        "allowed_clients": ["okta-app-id"],
    },
    out_path=r"${artifactPath}",
)
`
    execFileSync(process.env.PYTHON ?? "python3", ["-c", py], { cwd: repoRoot, stdio: "pipe" })
    const out = resolveInboundAuthorizer({
      cognitoDiscoveryUrl: COGNITO_URL,
      fallbackClients: ["webclient123"],
      artifactPath,
    })
    expect(out.discoveryUrl).toBe(CUSTOM_URL)
  })
})

describe("resolveOutboundProfile", () => {
  it("both variants disabled when the artifact is absent", () => {
    const out = resolveOutboundProfile({ artifactPath: path.join(os.tmpdir(), "no-such-ob.json") })
    expect(out).toEqual({ serviceEnabled: false, userEnabled: false, oboDirectMcp: false })
  })

  it("reads service_enabled/user_enabled from the outbound block", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "authprof-ob-"))
    const artifactPath = path.join(dir, ".auth-profile-resolved.json")
    fs.writeFileSync(
      artifactPath,
      JSON.stringify({ outbound: { flow: "M2M", service_enabled: true, user_enabled: false } }),
    )
    expect(resolveOutboundProfile({ artifactPath })).toEqual({
      serviceEnabled: true,
      userEnabled: false,
      flow: "M2M",
      oboDirectMcp: false,
    })
  })

  it("surfaces obo_direct_mcp and mcp_invocation_url for an OBO outbound block", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "authprof-obo-"))
    const artifactPath = path.join(dir, ".auth-profile-resolved.json")
    fs.writeFileSync(
      artifactPath,
      JSON.stringify({
        outbound: {
          // Real emitted token (mcp_oauth_flow), not the literal "OBO".
          flow: "ON_BEHALF_OF_TOKEN_EXCHANGE",
          service_enabled: false,
          user_enabled: true,
          issuer_type: "entra",
          obo_direct_mcp: true,
          mcp_invocation_url: "https://example-mcp.invalid/mcp",
        },
      }),
    )
    const r = resolveOutboundProfile({ artifactPath })
    expect(r.flow).toBe("ON_BEHALF_OF_TOKEN_EXCHANGE")
    expect(r.oboDirectMcp).toBe(true)
    expect(r.mcpInvocationUrl).toBe("https://example-mcp.invalid/mcp")
  })

  it("defaults oboDirectMcp to false for a non-OBO outbound block", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "authprof-noobo-"))
    const artifactPath = path.join(dir, ".auth-profile-resolved.json")
    fs.writeFileSync(
      artifactPath,
      JSON.stringify({ outbound: { flow: "M2M", service_enabled: true, user_enabled: false } }),
    )
    const r = resolveOutboundProfile({ artifactPath })
    expect(r.oboDirectMcp).toBe(false)
    expect(r.mcpInvocationUrl).toBeUndefined()
  })
})

describe("resolveModeProfile", () => {
  it("modes UNKNOWN (null) when the artifact is absent", () => {
    // null, not [] — the absent artifact is the all-no-op cognito-basic default, which
    // DOES declare autonomous. An empty list would read as "autonomous not declared"
    // and refuse the autonomous path on the default deployment.
    const out = resolveModeProfile({ artifactPath: path.join(os.tmpdir(), "no-such-mode.json") })
    expect(out).toEqual({ batchRunnerEnabled: false, modes: null, profile: null })
  })

  it("modes UNKNOWN (null) when there is no mode block", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "authprof-mode-"))
    const artifactPath = path.join(dir, ".auth-profile-resolved.json")
    fs.writeFileSync(
      artifactPath,
      JSON.stringify({ profile: "cognito-m2m", outbound: { flow: "M2M" } }),
    )
    expect(resolveModeProfile({ artifactPath })).toEqual({
      batchRunnerEnabled: false,
      modes: null,
      profile: "cognito-m2m",
    })
  })

  it("reads batch_runner_enabled, modes and profile from the mode block", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "authprof-mode-"))
    const artifactPath = path.join(dir, ".auth-profile-resolved.json")
    fs.writeFileSync(
      artifactPath,
      JSON.stringify({
        profile: "entra-userfed",
        mode: { modes: ["live", "batch"], batch_runner_enabled: true, requires_refresh: true },
      }),
    )
    expect(resolveModeProfile({ artifactPath })).toEqual({
      batchRunnerEnabled: true,
      modes: ["live", "batch"],
      profile: "entra-userfed",
    })
  })

  it("carries a live-only mode list so the autonomous gate can see it", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "authprof-mode-"))
    const artifactPath = path.join(dir, ".auth-profile-resolved.json")
    fs.writeFileSync(
      artifactPath,
      JSON.stringify({
        profile: "entra-obo",
        mode: { modes: ["live"], batch_runner_enabled: false, requires_refresh: false },
      }),
    )
    expect(resolveModeProfile({ artifactPath })).toEqual({
      batchRunnerEnabled: false,
      modes: ["live"],
      profile: "entra-obo",
    })
  })
})
