// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as fs from "fs"
import * as path from "path"
import { ConfigManager } from "../lib/utils/config-manager"

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

describe("sap.identity.federation", () => {
  let cfg: string
  afterEach(() => cfg && cleanup(cfg))

  test("defaults mapping_claim to 'email' when federation is enabled", () => {
    cfg = writeTempConfig(`${BASE}
sap:
  base_url: https://sap.example.com
  identity:
    federation:
      enabled: true
      ias_redirect_uri: "https://tenant.accounts.ondemand.com/oauth2/callback"
`)
    const c = new ConfigManager(cfg).getProps()
    expect(c.sap?.identity?.federation?.enabled).toBe(true)
    expect(c.sap?.identity?.federation?.mapping_claim).toBe("email")
  })

  test("requires ias_redirect_uri when federation is enabled", () => {
    cfg = writeTempConfig(`${BASE}
sap:
  base_url: https://sap.example.com
  identity:
    federation:
      enabled: true
`)
    expect(() => new ConfigManager(cfg).getProps()).toThrow(/ias_redirect_uri/)
  })

  test("preserves an explicit mapping_claim", () => {
    cfg = writeTempConfig(`${BASE}
sap:
  base_url: https://sap.example.com
  identity:
    federation:
      enabled: true
      ias_redirect_uri: "https://tenant.accounts.ondemand.com/oauth2/callback"
      mapping_claim: upn
`)
    const c = new ConfigManager(cfg).getProps()
    expect(c.sap?.identity?.federation?.mapping_claim).toBe("upn")
  })

  test("federation disabled does not require ias_redirect_uri", () => {
    cfg = writeTempConfig(`${BASE}
sap:
  base_url: https://sap.example.com
  identity:
    federation:
      enabled: false
`)
    const c = new ConfigManager(cfg).getProps()
    expect(c.sap?.identity?.federation?.enabled).toBe(false)
  })

  test("absent identity block leaves federation undefined", () => {
    cfg = writeTempConfig(`${BASE}
sap:
  base_url: https://sap.example.com
`)
    const c = new ConfigManager(cfg).getProps()
    expect(c.sap?.identity?.federation).toBeUndefined()
  })
})
