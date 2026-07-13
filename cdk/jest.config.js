// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

module.exports = {
  testEnvironment: 'node',
  roots: ['<rootDir>/test'],
  testMatch: ['**/*.test.ts'],
  // Resolve TypeScript source before any co-located compiled .js artifact.
  // The repo gitignores *.js (build output of tsc / the pre-commit codegen),
  // and Node's default extension order puts 'js' before 'ts' — so a stale
  // compiled config-manager.js next to the .ts would silently shadow the
  // source and make tests run against stale code. Listing 'ts' first prevents that.
  moduleFileExtensions: ['ts', 'tsx', 'js', 'jsx', 'json', 'node'],
  transform: {
    '^.+\\.tsx?$': 'ts-jest'
  }
};
