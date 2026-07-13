// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Property-based test for environment variable access pattern
 */

import { describe, it } from "vitest"
import * as fc from "fast-check"
import * as fs from "fs"
import * as path from "path"

function getAllSourceFiles(dir: string, fileList: string[] = []): string[] {
  const files = fs.readdirSync(dir)

  files.forEach(file => {
    const filePath = path.join(dir, file)
    const stat = fs.statSync(filePath)

    if (stat.isDirectory()) {
      if (!file.startsWith(".") && file !== "node_modules" && file !== "build") {
        getAllSourceFiles(filePath, fileList)
      }
    } else if (file.match(/\.(ts|tsx|js|jsx)$/)) {
      fileList.push(filePath)
    }
  })

  return fileList
}

describe("Environment Variable Access Pattern", () => {
  const srcDir = path.resolve(__dirname, "..")
  const allSourceFiles = getAllSourceFiles(srcDir)

  it("should use import.meta.env.VITE_* pattern when accessing environment variables", () => {
    fc.assert(
      fc.property(fc.constantFrom(...allSourceFiles), filePath => {
        const content = fs.readFileSync(filePath, "utf-8")

        const hasEnvAccess = /env\./g.test(content)

        if (hasEnvAccess) {
          const hasVitePattern = /import\.meta\.env/g.test(content)
          const hasProcessEnv = /process\.env/g.test(content)

          return hasVitePattern || !hasProcessEnv
        }

        return true
      }),
      { numRuns: 100 }
    )
  })
})
