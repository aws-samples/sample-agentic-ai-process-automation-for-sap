// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Registers jest-dom's matcher types with vitest's `expect`.
 *
 * `src/test/setup.ts` already imports the matchers so they exist at runtime, but
 * `tsconfig.json` excludes `src/test`, so the compiler never sees that import and
 * every `toBeInTheDocument()` in an in-scope test file fails `npm run build`.
 * This file has to live under `src/` for that reason.
 */
import "@testing-library/jest-dom/vitest"
