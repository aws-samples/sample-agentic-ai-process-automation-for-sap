// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from "aws-cdk-lib"
import * as cognito from "aws-cdk-lib/aws-cognito"
import { Template } from "aws-cdk-lib/assertions"
import * as fs from "fs"
import * as os from "os"
import * as path from "path"
import { BackendStack, shouldProvisionAutonomous } from "../lib/backend-stack"
import { AppConfig } from "../lib/utils/config-manager"
import { ModeProfileResult } from "../lib/utils/resolve-inbound-authorizer"

// Verifies the constructor's mode-axis gates and what each mode actually provisions.
// The resolveModeProfile reader itself is tested in resolve-inbound-authorizer.test.ts.
// Uses a private temp AUTH_PROFILE_ARTIFACT (not the shared repo-root file) to avoid
// racing sap-mcp-stack.test.ts under jest's parallel workers.

function minimalProps(): any {
  // Enough for the gate tests only: these assert on a throw raised at the top of the
  // constructor. Anything asserting on SYNTHESIZED RESOURCES must use synthProps() —
  // this shape crashes on config.backend long before provisioning happens.
  return {
    config: { stack_name_base: "test-proj" } as AppConfig,
    userPoolId: "us-east-1_ABC",
    userPoolClientId: "client123",
    userPoolDomain: undefined,
    frontendUrl: "http://localhost:3000",
    env: { account: "111122223333", region: "us-east-1" },
  }
}

/** An App with Lambda asset bundling disabled. These tests assert on resource
 *  wiring, never on bundle contents, and a real pip install per Lambda adds
 *  ~30s per synth. Any test calling synthProps() must use this. */
function newSynthApp(): cdk.App {
  return new cdk.App({ context: { "aws:cdk:bundling-stacks": [] } })
}

/** Props complete enough for the stack to synthesize end-to-end, so a test can
 *  assert on real resources rather than passing on an unrelated early crash. */
function synthProps(app: cdk.App, overrides: Partial<AppConfig> = {}): any {
  const host = new cdk.Stack(app, "Host", { env: { account: "111122223333", region: "us-east-1" } })
  const pool = new cognito.UserPool(host, "Pool")
  return {
    config: {
      stack_name_base: "test-proj",
      // deployment_type 'zip', not 'docker': the docker path stages a container
      // image asset over the whole repo root (~2 min per synth). The batch runner
      // and the pipeline it rides are identical either way.
      backend: { pattern: "agent", deployment_type: "zip", network_mode: "PUBLIC" },
      autonomy: { trigger_mode: "manual" },
      sap: { base_url: "https://mock-sap.example.com" },
      ...overrides,
    } as AppConfig,
    userPoolId: "us-east-1_ABC",
    userPoolClientId: "client123",
    userPoolDomain: pool.addDomain("D", { cognitoDomain: { domainPrefix: "test-proj-synth" } }),
    frontendUrl: "http://localhost:3000",
    env: { account: "111122223333", region: "us-east-1" },
  }
}

describe("shouldProvisionAutonomous pure decision helper", () => {
  test("returns true when modes is null (unknown / inert / no artifact)", () => {
    const result = shouldProvisionAutonomous({
      batchRunnerEnabled: false,
      modes: null,
      profile: null,
    })
    expect(result).toBe(true)
  })

  test("returns true when modes includes 'autonomous'", () => {
    const result = shouldProvisionAutonomous({
      batchRunnerEnabled: false,
      modes: ["autonomous", "live"],
      profile: "cognito-m2m",
    })
    expect(result).toBe(true)
  })

  test("returns false when modes explicitly omits 'autonomous'", () => {
    const result = shouldProvisionAutonomous({
      batchRunnerEnabled: false,
      modes: ["live"],
      profile: "entra-obo",
    })
    expect(result).toBe(false)
  })
})

describe("BackendStack mode-axis batch gate", () => {
  let artifactPath: string
  const prevEnv = process.env.AUTH_PROFILE_ARTIFACT

  beforeEach(() => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "authprof-gate-"))
    artifactPath = path.join(dir, ".auth-profile-resolved.json")
    process.env.AUTH_PROFILE_ARTIFACT = artifactPath
  })

  afterEach(() => {
    if (prevEnv === undefined) delete process.env.AUTH_PROFILE_ARTIFACT
    else process.env.AUTH_PROFILE_ARTIFACT = prevEnv
    if (fs.existsSync(artifactPath)) fs.unlinkSync(artifactPath)
  })

  test("throws when batch is selected without autonomous (no queue to enqueue into)", () => {
    // The batch runner reuses the autonomous pipeline's queue + invoker rather than
    // standing up a second runtime, so batch-without-autonomous is a sweeper with
    // nothing to sweep into. That combination must fail at synth, not deploy.
    fs.writeFileSync(
      artifactPath,
      JSON.stringify({
        profile: "entra-userfed",
        mode: { modes: ["live", "batch"], batch_runner_enabled: true },
      }),
    )
    const app = new cdk.App()
    expect(() => new BackendStack(app, "test-proj-backend", minimalProps())).toThrow(
      /mode 'batch' requires 'autonomous'/,
    )
  })

  test("provisions the batch runner when autonomous accompanies batch", () => {
    fs.writeFileSync(
      artifactPath,
      JSON.stringify({
        profile: "cognito-m2m-batch",
        mode: { modes: ["autonomous", "live", "batch"], batch_runner_enabled: true },
      }),
    )
    const app = newSynthApp()
    const stack = new BackendStack(app, "test-proj-backend", synthProps(app))
    const t = Template.fromStack(stack)
    t.hasResourceProperties("AWS::Lambda::Function", { FunctionName: "test-proj-batch-runner" })
    t.hasResourceProperties("AWS::Events::Rule", { Name: "test-proj-batch-runner" })
  })

  test("omits the batch runner when batch is not selected", () => {
    // Guards against the runner leaking onto the default autonomous deployment.
    fs.writeFileSync(
      artifactPath,
      JSON.stringify({
        profile: "cognito-m2m",
        mode: { modes: ["autonomous", "live"], batch_runner_enabled: false },
      }),
    )
    const app = newSynthApp()
    const stack = new BackendStack(app, "test-proj-backend", synthProps(app))
    const names = Object.values(
      Template.fromStack(stack).findResources("AWS::Lambda::Function"),
    ).map((r: any) => r.Properties?.FunctionName)
    expect(names).toContain("test-proj-agent-invoker") // autonomous path still wired
    expect(names).not.toContain("test-proj-batch-runner")
  })

  test("does NOT throw when the resolved mode omits 'autonomous' (live-only synthesizes)", () => {
    // Live-only profiles (e.g. entra-obo) now synthesize successfully — the
    // autonomous pipeline is simply omitted rather than the stack crashing.
    fs.writeFileSync(
      artifactPath,
      JSON.stringify({
        profile: "entra-obo",
        mode: { modes: ["live"], batch_runner_enabled: false },
      }),
    )
    const app = new cdk.App()
    let threw = false
    try {
      new BackendStack(app, "test-proj-backend", minimalProps())
    } catch (error) {
      const msg = (error as Error).message
      // batch gate may still fire for unrelated reasons in this minimal harness,
      // but the autonomous gate must NOT fire.
      if (/omits 'autonomous'/.test(msg)) threw = true
    }
    expect(threw).toBe(false)
  })

  test("live-only synthesizes NO unattended caller", () => {
    // The gate-does-not-throw test above says nothing about what got built. This one
    // asserts absence: a live-only profile must contain no poller, no invoker, no
    // queue, and no schedule, so there is nothing that could fire without a human.
    fs.writeFileSync(
      artifactPath,
      JSON.stringify({
        profile: "entra-obo",
        mode: { modes: ["live"], batch_runner_enabled: false },
      }),
    )
    const app = newSynthApp()
    const t = Template.fromStack(new BackendStack(app, "test-proj-backend", synthProps(app)))

    const fnNames = Object.values(t.findResources("AWS::Lambda::Function")).map(
      (r: any) => r.Properties?.FunctionName,
    )
    expect(fnNames).not.toContain("test-proj-odata-poller")
    expect(fnNames).not.toContain("test-proj-agent-invoker")
    expect(fnNames).not.toContain("test-proj-webhook-processor")
    expect(fnNames).not.toContain("test-proj-batch-runner")

    // No queue to enqueue onto, no schedule to fire, and no event source that could
    // drive a Lambda from the queue even if one of the above were reintroduced.
    expect(Object.keys(t.findResources("AWS::SQS::Queue"))).toHaveLength(0)
    expect(Object.keys(t.findResources("AWS::Events::Rule"))).toHaveLength(0)
    expect(Object.keys(t.findResources("AWS::Lambda::EventSourceMapping"))).toHaveLength(0)
  })

  test("autonomous profiles retain the full queue path", () => {
    // The other half of the same claim: omitting the pipeline for live-only must not
    // have made it conditional on anything else.
    fs.writeFileSync(
      artifactPath,
      JSON.stringify({
        profile: "cognito-basic",
        mode: { modes: ["autonomous", "live"], batch_runner_enabled: false },
      }),
    )
    const app = newSynthApp()
    const t = Template.fromStack(new BackendStack(app, "test-proj-backend", synthProps(app)))

    const fnNames = Object.values(t.findResources("AWS::Lambda::Function")).map(
      (r: any) => r.Properties?.FunctionName,
    )
    expect(fnNames).toContain("test-proj-odata-poller")
    expect(fnNames).toContain("test-proj-agent-invoker")

    t.hasResourceProperties("AWS::SQS::Queue", { QueueName: "test-proj-agent-queue.fifo" })
    t.hasResourceProperties("AWS::Events::Rule", { Name: "test-proj-odata-poller" })
    // The invoker must actually be wired to the queue, not merely coexist with it.
    expect(
      Object.keys(t.findResources("AWS::Lambda::EventSourceMapping")).length,
    ).toBeGreaterThan(0)
  })

  test("does NOT fire the autonomous gate when no artifact exists", () => {
    // run_emit writes nothing for the all-no-op cognito-basic default, and cdk/bin/app.ts
    // deletes any stale artifact pre-synth. Absent modes means UNKNOWN, not "forbidden";
    // treating it as forbidden would refuse the autonomous path on the DEFAULT deploy.
    const app = new cdk.App()
    let message = ""
    try {
      new BackendStack(app, "test-proj-backend", minimalProps())
    } catch (error) {
      message = (error as Error).message
    }
    expect(message).not.toMatch(/omits 'autonomous'/)
  })

  test("does NOT fire the autonomous gate when the mode declares autonomous", () => {
    fs.writeFileSync(
      artifactPath,
      JSON.stringify({
        profile: "cognito-m2m",
        mode: { modes: ["autonomous", "live"], batch_runner_enabled: false },
      }),
    )
    const app = new cdk.App()
    let message = ""
    try {
      new BackendStack(app, "test-proj-backend", minimalProps())
    } catch (error) {
      message = (error as Error).message
    }
    expect(message).not.toMatch(/omits 'autonomous'/)
  })
})
