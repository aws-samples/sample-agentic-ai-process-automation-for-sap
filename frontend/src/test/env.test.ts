// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest"
import { readFileSync } from "fs"
import { resolve } from "path"

describe("Environment Variable Tests", () => {
  describe("Environment Variable Type Definitions", () => {
    it("should have vite-env.d.ts with environment variable types", () => {
      const viteEnvPath = resolve(__dirname, "../vite-env.d.ts")
      const viteEnvContent = readFileSync(viteEnvPath, "utf-8")

      expect(viteEnvContent).toContain('/// <reference types="vite/client" />')
    })

    it("should define ImportMetaEnv interface", () => {
      const viteEnvPath = resolve(__dirname, "../vite-env.d.ts")
      const viteEnvContent = readFileSync(viteEnvPath, "utf-8")

      expect(viteEnvContent).toContain("interface ImportMetaEnv")
    })

    it("should define Cognito environment variable types", () => {
      const viteEnvPath = resolve(__dirname, "../vite-env.d.ts")
      const viteEnvContent = readFileSync(viteEnvPath, "utf-8")

      expect(viteEnvContent).toContain("VITE_COGNITO_USER_POOL_ID")
      expect(viteEnvContent).toContain("VITE_COGNITO_CLIENT_ID")
      expect(viteEnvContent).toContain("VITE_COGNITO_REGION")
    })
  })
})
