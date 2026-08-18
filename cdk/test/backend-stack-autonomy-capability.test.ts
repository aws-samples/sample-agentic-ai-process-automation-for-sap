// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from "aws-cdk-lib"
import { Match, Template } from "aws-cdk-lib/assertions"
import * as fs from "fs"
import * as os from "os"
import * as path from "path"
import { BackendStack } from "../lib/backend-stack"
import { ConfigManager } from "../lib/utils/config-manager"

// The autonomy Lambda's AUTONOMOUS_CAPABLE flag and the PUT /autonomy method are driven
// by the same `this.agentQueue` predicate. Both are asserted per synth because the point
// is that they AGREE: the trigger-mode SSM parameter is seeded unconditionally, so a
// live-only deployment can store `auto` with no poller to honour it. If the flag said
// "capable" there, the UI would claim unattended SAP writes on a deployment incapable of
// one, and offer a disarm button whose endpoint does not exist.
//
// Separate file from backend-stack-mode-gate.test.ts on purpose: that suite asserts the
// constructor's loud-fail gates and never completes a synth, so it stays fast on
// deliberately minimal props. These tests need a fully synthesized template, which
// bundles Lambda assets and costs ~20s per case.
//
// Uses a private temp AUTH_PROFILE_ARTIFACT (not the shared repo-root file) to avoid
// racing sap-mcp-stack.test.ts under jest's parallel workers.

jest.setTimeout(120_000)

function synth(): Template {
  const config = new ConfigManager("config.yaml").getProps()
  const app = new cdk.App()
  const stack = new BackendStack(app, "test-proj-backend", {
    config,
    userPoolId: "us-east-1_ABC",
    userPoolClientId: "client123",
    // The stack only reads .domainName, and constructing a real UserPoolDomain would
    // require a second stack purely to satisfy a template string.
    userPoolDomain: { domainName: "test-domain" } as any,
    frontendUrl: "http://localhost:3000",
    env: { account: "111122223333", region: "us-east-1" },
  } as any)
  return Template.fromStack(stack)
}

/** PUT methods on the /autonomy resource only. Scoped deliberately: /config mounts its
 *  own PUT unconditionally, so counting every PUT in the template would never be zero. */
function autonomyPutCount(template: Template): number {
  const autonomyIds = Object.entries(template.findResources("AWS::ApiGateway::Resource"))
    .filter(([, r]: [string, any]) => r.Properties?.PathPart === "autonomy")
    .map(([id]) => id)
  expect(autonomyIds).toHaveLength(1)

  return Object.values(template.findResources("AWS::ApiGateway::Method")).filter(
    (m: any) =>
      m.Properties?.HttpMethod === "PUT" && m.Properties?.ResourceId?.Ref === autonomyIds[0],
  ).length
}

describe("autonomy capability flag tracks the provisioned pipeline", () => {
  let artifactPath: string
  const prevEnv = process.env.AUTH_PROFILE_ARTIFACT

  beforeEach(() => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "authprof-capable-"))
    artifactPath = path.join(dir, ".auth-profile-resolved.json")
    process.env.AUTH_PROFILE_ARTIFACT = artifactPath
  })

  afterEach(() => {
    if (prevEnv === undefined) delete process.env.AUTH_PROFILE_ARTIFACT
    else process.env.AUTH_PROFILE_ARTIFACT = prevEnv
    if (fs.existsSync(artifactPath)) fs.unlinkSync(artifactPath)
  })

  test("live-only profile reports AUTONOMOUS_CAPABLE=false and mounts no PUT /autonomy", () => {
    fs.writeFileSync(
      artifactPath,
      JSON.stringify({
        profile: "entra-obo",
        mode: { modes: ["live"], batch_runner_enabled: false },
      }),
    )
    const template = synth()

    template.hasResourceProperties("AWS::Lambda::Function", {
      Environment: { Variables: Match.objectLike({ AUTONOMOUS_CAPABLE: "false" }) },
    })
    expect(autonomyPutCount(template)).toBe(0)
  })

  test("autonomous profile reports AUTONOMOUS_CAPABLE=true and mounts PUT /autonomy", () => {
    fs.writeFileSync(
      artifactPath,
      JSON.stringify({
        profile: "cognito-m2m",
        mode: { modes: ["autonomous", "live"], batch_runner_enabled: false },
      }),
    )
    const template = synth()

    template.hasResourceProperties("AWS::Lambda::Function", {
      Environment: { Variables: Match.objectLike({ AUTONOMOUS_CAPABLE: "true" }) },
    })
    expect(autonomyPutCount(template)).toBe(1)
  })

  test("no artifact (the default deploy) is capable — absent modes is UNKNOWN, not forbidden", () => {
    const template = synth()

    template.hasResourceProperties("AWS::Lambda::Function", {
      Environment: { Variables: Match.objectLike({ AUTONOMOUS_CAPABLE: "true" }) },
    })
    expect(autonomyPutCount(template)).toBe(1)
  })
})
