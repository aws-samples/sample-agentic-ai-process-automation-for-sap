// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from "aws-cdk-lib"
import * as cognito from "aws-cdk-lib/aws-cognito"
import { Template } from "aws-cdk-lib/assertions"
import { BackendStack } from "../lib/backend-stack"
import { AppConfig } from "../lib/utils/config-manager"

// The shared-types layer bundles pydantic, whose pydantic_core is a compiled Rust
// extension. python-bundling.ts installs it with --platform manylinux2014_aarch64,
// so the layer contains an aarch64 .so and NOTHING else. An x86_64 Lambda cannot
// load it, and every consumer wraps the import in a best-effort try/except that
// nulls the model on failure — so the mismatch is silent: no error, no log, the
// validator and the CaseStatus enum guard just quietly stop existing.
//
// That is how an out-of-enum status ("analyzing") reached DynamoDB through
// case_management's `if CaseStatus is not None` guard on a live stack.
//
// Assert architecture from the synthesized template rather than trusting the
// construct code: the property is optional and CDK's default is X86_64, so a new
// layer consumer breaks this by omission, which is exactly how it happened.

function template(): Template {
  // Bundling disabled: this asserts on resource properties, never bundle contents,
  // and a real pip install per Lambda costs ~30s per synth.
  const app = new cdk.App({ context: { "aws:cdk:bundling-stacks": [] } })
  const host = new cdk.Stack(app, "Host", {
    env: { account: "111122223333", region: "us-east-1" },
  })
  const pool = new cognito.UserPool(host, "Pool")
  const stack = new BackendStack(app, "TestStack", {
    config: {
      stack_name_base: "test-proj",
      backend: { pattern: "agent", deployment_type: "zip", network_mode: "PUBLIC" },
      autonomy: { trigger_mode: "manual" },
      sap: { base_url: "https://mock-sap.example.com" },
      // Both gated consumers on, so the sweep covers them too.
      demo: { enabled: true, ticketing: { enabled: true } },
    } as AppConfig,
    userPoolId: "us-east-1_ABC",
    userPoolClientId: "client123",
    userPoolDomain: pool.addDomain("D", {
      cognitoDomain: { domainPrefix: "test-proj-arch" },
    }),
    frontendUrl: "http://localhost:3000",
    env: { account: "111122223333", region: "us-east-1" },
  } as any)
  return Template.fromStack(stack)
}

describe("every shared-types layer consumer matches the layer's binary arch", () => {
  test("no Lambda carries the layer on a non-ARM architecture", () => {
    const synthesized = template()
    const layers = synthesized.findResources("AWS::Lambda::LayerVersion")
    const layerIds = Object.keys(layers).filter((id) =>
      JSON.stringify(layers[id]).includes("shared-types")
    )
    expect(layerIds.length).toBeGreaterThan(0)

    const functions = synthesized.findResources("AWS::Lambda::Function")
    const consumers = Object.entries(functions).filter(([, fn]) =>
      layerIds.some((layerId) =>
        JSON.stringify(fn.Properties?.Layers ?? []).includes(layerId)
      )
    )
    // If this is 0 the filter is wrong, not the stack — fail loudly rather than
    // vacuously passing.
    expect(consumers.length).toBeGreaterThan(0)

    const mismatched = consumers
      .filter(([, fn]) => !(fn.Properties?.Architectures ?? []).includes("arm64"))
      .map(([id, fn]) => `${id} (${(fn.Properties?.Architectures ?? ["x86_64 — CDK default"]).join(",")})`)

    expect(mismatched).toEqual([])
  })
})
