// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from "aws-cdk-lib"
import * as fs from "fs"
import * as os from "os"
import * as path from "path"
import { BackendStack } from "../lib/backend-stack"
import { AppConfig } from "../lib/utils/config-manager"

// Verifies the constructor's loud-fail gate for the unimplemented batch runner mode;
// the resolveModeProfile reader itself is tested in resolve-inbound-authorizer.test.ts.
// Uses a private temp AUTH_PROFILE_ARTIFACT (not the shared repo-root file) to avoid
// racing sap-mcp-stack.test.ts under jest's parallel workers.

function minimalProps(): any {
  // Props are irrelevant: the gate fires at the top of the constructor, before any
  // prop is dereferenced.
  return {
    config: { stack_name_base: "test-proj" } as AppConfig,
    userPoolId: "us-east-1_ABC",
    userPoolClientId: "client123",
    userPoolDomain: undefined,
    frontendUrl: "http://localhost:3000",
    env: { account: "111122223333", region: "us-east-1" },
  }
}

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

  test("throws when the mode block selects the (unimplemented) batch runner", () => {
    fs.writeFileSync(
      artifactPath,
      JSON.stringify({ mode: { modes: ["live", "batch"], batch_runner_enabled: true } }),
    )
    const app = new cdk.App()
    expect(() => new BackendStack(app, "test-proj-backend", minimalProps())).toThrow(
      /batch runner .* is not\s+implemented/,
    )
  })
})
