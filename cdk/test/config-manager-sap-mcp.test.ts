// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as fs from "fs"
import * as path from "path"
import { ConfigManager } from "../lib/utils/config-manager"

// Writes under cdk/ root, since ConfigManager resolves config paths relative to it.
function writeTempConfig(body: string): string {
  const cdkRoot = path.join(__dirname, "..")
  const name = `config.test.${process.pid}.${Math.floor(performance.now() * 1000)}.yaml`
  fs.writeFileSync(path.join(cdkRoot, name), body, "utf8")
  return name
}

function cleanup(name: string): void {
  const p = path.join(__dirname, "..", name)
  if (fs.existsSync(p)) fs.unlinkSync(p)
}

const BASE = `
stack_name_base: test-proj
backend:
  pattern: agent
  deployment_type: docker
`

describe("sap_mcp (external-only)", () => {
  let cfg: string
  afterEach(() => cfg && cleanup(cfg))

  test("accepts a valid external_stack with no deploy_mode field", () => {
    cfg = writeTempConfig(`${BASE}
sap_mcp:
  enabled: true
  external_stack:
    stack_name: sap-mcp-prod
    inbound_auth_provider: Cognito
  service:
    enabled: true
    auth_flow: M2M
`)
    const c = new ConfigManager(cfg).getProps()
    expect(c.sap_mcp?.external_stack?.stack_name).toBe("sap-mcp-prod")
  })

  test("carries external_stack.region when set", () => {
    cfg = writeTempConfig(`${BASE}
sap_mcp:
  enabled: true
  external_stack:
    stack_name: aws-for-sap-mcp-server
    region: us-west-2
    inbound_auth_provider: Cognito
  service:
    enabled: true
    auth_flow: M2M
`)
    const c = new ConfigManager(cfg).getProps()
    expect(c.sap_mcp?.external_stack?.region).toBe("us-west-2")
  })

  test("rejects sap_mcp.enabled without external_stack.stack_name", () => {
    cfg = writeTempConfig(`${BASE}
sap_mcp:
  enabled: true
  service:
    enabled: true
    auth_flow: M2M
`)
    expect(() => new ConfigManager(cfg).getProps()).toThrow(/external_stack\.stack_name/)
  })
})

describe("sap_mcp target variants (pure adapter — external owns SAP permissions)", () => {
  let cfg: string
  afterEach(() => cfg && cleanup(cfg))

  const EXT = `
sap_mcp:
  enabled: true
  external_stack:
    stack_name: sap-mcp-prod
    inbound_auth_provider: Cognito`

  test("ignores stray external-owned knobs without erroring (adapter is permissive)", () => {
    cfg = writeTempConfig(`${BASE}${EXT}
  service:
    enabled: true
    auth_flow: M2M
    write_enabled: true
    create_enabled: true
`)
    const c = new ConfigManager(cfg).getProps()
    expect(c.sap_mcp?.enabled).toBe(true)
  })
})

describe("callback URL hygiene (regression for the AgentCore /callback constraint)", () => {
  test("config.yaml.example does not teach the rejected /sap-callback suffix", () => {
    const example = fs.readFileSync(
      path.join(__dirname, "..", "config.yaml.example"),
      "utf8"
    )
    // AgentCore requires the path to end in /callback or /oauthcallback;
    // /auth/sap-callback was empirically REJECTED. Guard against reintroduction.
    expect(example).not.toMatch(/\/auth\/sap-callback/)
  })
})
