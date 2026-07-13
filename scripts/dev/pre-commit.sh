#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Git pre-commit hook — runs make pre-commit before every commit.
# Install with: make install-hooks
set -euo pipefail

echo "🔍 Running pre-commit checks..."
make pre-commit
echo "✅ Pre-commit checks passed."
