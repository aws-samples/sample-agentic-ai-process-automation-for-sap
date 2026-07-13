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

describe("demo flag decoupling", () => {
  let cfg: string
  afterEach(() => cfg && cleanup(cfg))

  test("legacy demo.enabled: true enables both ticketing and test_data", () => {
    cfg = writeTempConfig(`${BASE}
demo:
  enabled: true
`)
    const c = new ConfigManager(cfg).getProps()
    expect(c.demo?.ticketing?.enabled).toBe(true)
    expect(c.demo?.test_data?.enabled).toBe(true)
    expect(c.demo?.enabled).toBe(true) // both on → legacy sugar stays true
  })

  test("ticketing on, test_data off — independent", () => {
    cfg = writeTempConfig(`${BASE}
demo:
  ticketing:
    enabled: true
  test_data:
    enabled: false
`)
    const c = new ConfigManager(cfg).getProps()
    expect(c.demo?.ticketing?.enabled).toBe(true)
    expect(c.demo?.test_data?.enabled).toBe(false)
    expect(c.demo?.enabled).toBe(false) // not both → example_* skills stay off
  })

  test("test_data on, ticketing off — independent", () => {
    cfg = writeTempConfig(`${BASE}
demo:
  test_data:
    enabled: true
`)
    const c = new ConfigManager(cfg).getProps()
    expect(c.demo?.ticketing?.enabled).toBe(false)
    expect(c.demo?.test_data?.enabled).toBe(true)
  })

  test("no demo block → undefined", () => {
    cfg = writeTempConfig(BASE)
    expect(new ConfigManager(cfg).getProps().demo).toBeUndefined()
  })

  test("all-off demo block → undefined", () => {
    cfg = writeTempConfig(`${BASE}
demo:
  ticketing:
    enabled: false
  test_data:
    enabled: false
`)
    expect(new ConfigManager(cfg).getProps().demo).toBeUndefined()
  })
})
