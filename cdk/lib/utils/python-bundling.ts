// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as lambda from "aws-cdk-lib/aws-lambda"
import * as cdk from "aws-cdk-lib"
import { execSync } from "child_process"
import * as fs from "fs"
import * as path from "path"

/**
 * Creates a Code.fromAsset bundle for a Python Lambda using local pip install.
 * Falls back to Docker only if local bundling fails (e.g. native C extensions).
 *
 * This eliminates the Docker/Finch requirement for pure-Python Lambdas.
 */
export function pythonAssetCode(entry: string, runtime: lambda.Runtime = lambda.Runtime.PYTHON_3_13): lambda.Code {
  const hasRequirements = fs.existsSync(path.join(entry, "requirements.txt")) // nosemgrep: detect-non-literal-fs-filename

  if (!hasRequirements) {
    // No dependencies — just zip the source directory
    return lambda.Code.fromAsset(entry)
  }

  return lambda.Code.fromAsset(entry, {
    bundling: {
      image: runtime.bundlingImage,
      command: [
        "bash", "-c",
        "pip install -r requirements.txt -t /asset-output -q && cp -r . /asset-output",
      ],
      local: {
        tryBundle(outputDir: string): boolean {
          try {
            const pipCmd = execSync("which pip3 || which pip", { stdio: "pipe" }).toString().trim()
            execSync(
              `"${pipCmd}" install -r requirements.txt -t "${outputDir}" --platform manylinux2014_aarch64 --python-version 3.13 --only-binary=:all: -q`,
              { cwd: entry, stdio: "pipe" },
            )
            // Copy source files (exclude __pycache__, .pyc)
            execSync(
              `rsync -a --exclude='__pycache__' --exclude='*.pyc' . "${outputDir}"`,
              { cwd: entry, stdio: "pipe" },
            )
            return true
          } catch {
            return false // fall back to Docker
          }
        },
      },
    },
  })
}

/**
 * Creates Code for a Python Lambda *layer*: installs requirements.txt and copies
 * the layer's .py modules into the layer's required `python/` root directory.
 * Same local-first, Docker-fallback strategy as pythonAssetCode.
 */
export function pythonLayerCode(entry: string, runtime: lambda.Runtime = lambda.Runtime.PYTHON_3_13): lambda.Code {
  const hasRequirements = fs.existsSync(path.join(entry, "requirements.txt")) // nosemgrep: detect-non-literal-fs-filename
  const pipInstall = hasRequirements
    ? "pip install -r requirements.txt -t /asset-output/python -q && "
    : ""

  return lambda.Code.fromAsset(entry, {
    bundling: {
      image: runtime.bundlingImage,
      command: ["bash", "-c", `${pipInstall}cp *.py /asset-output/python/`],
      local: {
        tryBundle(outputDir: string): boolean {
          try {
            const pythonDir = path.join(outputDir, "python")
            execSync(`mkdir -p "${pythonDir}"`, { stdio: "pipe" })
            if (hasRequirements) {
              const pipCmd = execSync("which pip3 || which pip", { stdio: "pipe" }).toString().trim()
              execSync(
                `"${pipCmd}" install -r requirements.txt -t "${pythonDir}" --platform manylinux2014_aarch64 --python-version 3.13 --only-binary=:all: -q`,
                { cwd: entry, stdio: "pipe" },
              )
            }
            execSync(`cp ${entry}/*.py "${pythonDir}"`, { stdio: "pipe" })
            return true
          } catch {
            return false // fall back to Docker
          }
        },
      },
    },
  })
}
