// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as fs from "fs"
import * as path from "path"
import * as cdk from "aws-cdk-lib"
import * as lambda from "aws-cdk-lib/aws-lambda"
import { Template, Match } from "aws-cdk-lib/assertions"
import { AgentKnowledge } from "../lib/constructs/agent-knowledge"
import { ConfigManager, AgentKnowledgeConfig } from "../lib/utils/config-manager"

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

describe("agent_knowledge config", () => {
  let cfg: string
  afterEach(() => cfg && cleanup(cfg))

  test("no block → undefined, so nothing is provisioned", () => {
    cfg = writeTempConfig(BASE)
    expect(new ConfigManager(cfg).getProps().agent_knowledge).toBeUndefined()
  })

  test("enabled: false → undefined, same as absent", () => {
    cfg = writeTempConfig(`${BASE}
agent_knowledge:
  enabled: false
`)
    expect(new ConfigManager(cfg).getProps().agent_knowledge).toBeUndefined()
  })

  test("enabled with no other knobs → documented defaults", () => {
    cfg = writeTempConfig(`${BASE}
agent_knowledge:
  enabled: true
`)
    const ak = new ConfigManager(cfg).getProps().agent_knowledge
    expect(ak?.enabled).toBe(true)
    expect(ak?.min_acu).toBe(0)
    expect(ak?.seconds_until_auto_pause).toBe(3600)
    expect(ak?.vendor_risk).toBe(true)
  })

  test("explicit knobs survive normalization", () => {
    cfg = writeTempConfig(`${BASE}
agent_knowledge:
  enabled: true
  min_acu: 0.5
  seconds_until_auto_pause: 900
  vendor_risk: false
`)
    const ak = new ConfigManager(cfg).getProps().agent_knowledge
    expect(ak?.min_acu).toBe(0.5)
    expect(ak?.seconds_until_auto_pause).toBe(900)
    expect(ak?.vendor_risk).toBe(false)
  })

  test("an auto-pause window RDS would reject is caught at synth", () => {
    cfg = writeTempConfig(`${BASE}
agent_knowledge:
  enabled: true
  seconds_until_auto_pause: 60
`)
    expect(() => new ConfigManager(cfg).getProps()).toThrow(/300/)
  })
})

describe("flag-off guarantee", () => {
  const OFF_SHAPES: Array<[string, string]> = [
    ["absent", ""],
    ["explicitly false", "agent_knowledge:\n  enabled: false\n"],
    ["knobs set but not enabled", "agent_knowledge:\n  min_acu: 0.5\n  vendor_risk: true\n"],
  ]

  let cfg: string
  afterEach(() => cfg && cleanup(cfg))

  test.each(OFF_SHAPES)("%s → the backend-stack gate is false", (_label, block) => {
    cfg = writeTempConfig(`${BASE}${block}`)
    const config = new ConfigManager(cfg).getProps()
    // The exact expression backend-stack.ts guards the construct with.
    expect(Boolean(config.agent_knowledge?.enabled)).toBe(false)
  })
})

describe("AgentKnowledge construct", () => {
  const synth = (agentKnowledge: AgentKnowledgeConfig) => {
    const app = new cdk.App()
    const stack = new cdk.Stack(app, "TestStack", { env: { account: "111122223333", region: "us-east-1" } })
    const layer = new lambda.LayerVersion(stack, "TestLayer", {
      code: lambda.Code.fromAsset(path.join(__dirname, "../lib/constructs")),
      compatibleRuntimes: [lambda.Runtime.PYTHON_3_13],
    })
    new AgentKnowledge(stack, "AgentKnowledge", {
      config: { stack_name_base: "test-stack", agent_knowledge: agentKnowledge } as never,
      sharedTypesLayer: layer,
    })
    return Template.fromStack(stack)
  }

  it("provisions an auto-pausing serverless cluster with the Data API on", () => {
    const template = synth({ enabled: true, min_acu: 0, seconds_until_auto_pause: 3600 })
    template.hasResourceProperties("AWS::RDS::DBCluster", {
      Engine: "aurora-postgresql",
      EnableHttpEndpoint: true,
      StorageEncrypted: true,
      ServerlessV2ScalingConfiguration: Match.objectLike({
        MinCapacity: 0,
        SecondsUntilAutoPause: 3600,
      }),
    })
  })

  it("creates no NAT gateway, so idle networking is free", () => {
    const template = synth({ enabled: true })
    template.resourceCountIs("AWS::EC2::NatGateway", 0)
  })

  it("gives the tool Lambda Data API access but no write permission", () => {
    const template = synth({ enabled: true })
    const policies = Object.values(
      template.findResources("AWS::IAM::Policy"),
    ) as Array<{ Properties: { PolicyDocument: { Statement: Array<{ Action: unknown }> } } }>
    const actions = policies
      .flatMap((p) => p.Properties.PolicyDocument.Statement)
      .flatMap((s) => (Array.isArray(s.Action) ? s.Action : [s.Action]))
      .filter((a): a is string => typeof a === "string")

    expect(actions).toContain("rds-data:ExecuteStatement")
    expect(actions).not.toContain("rds-data:BatchExecuteStatement")
  })

  it("keys the schema resource on the DDL source, so a queries.py edit re-applies it", () => {
    const props = Object.values(
      synth({ enabled: true }).findResources("AWS::CloudFormation::CustomResource"),
    )[0] as { Properties: Record<string, unknown> }
    const hash = props.Properties.SchemaHash

    const queriesPath = path.join(
      __dirname,
      "../../agentcore/gateway/tools/agent_knowledge/queries.py",
    )
    const original = fs.readFileSync(queriesPath)
    try {
      fs.appendFileSync(queriesPath, "\n# schema drift\n")
      const after = (
        Object.values(
          synth({ enabled: true }).findResources("AWS::CloudFormation::CustomResource"),
        )[0] as { Properties: Record<string, unknown> }
      ).Properties.SchemaHash
      expect(after).not.toEqual(hash)
    } finally {
      fs.writeFileSync(queriesPath, original)
    }
  })

  it("attaches the shared_types layer, without which queries.py cannot import amount_band", () => {
    const template = synth({ enabled: true })
    // Only our two Python Lambdas — the CR provider's framework function is Node
    // and imports nothing of ours.
    const ours = Object.entries(template.findResources("AWS::Lambda::Function"))
      .filter(([id]) => /SchemaLambda|ToolLambda/.test(id))
      .map(([id, r]) => [id, (r as { Properties: { Layers?: unknown[] } }).Properties.Layers] as const)

    expect(ours).toHaveLength(2)
    for (const [id, layers] of ours) {
      expect({ id, layerCount: Array.isArray(layers) ? layers.length : 0 }).toEqual({
        id,
        layerCount: 1,
      })
    }
  })
})
