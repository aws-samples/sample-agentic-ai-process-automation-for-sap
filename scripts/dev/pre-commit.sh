#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Git pre-commit hook. Install with: make install-hooks
#
# Calls the checks script directly rather than going through `make pre-commit`,
# so committing does not require GNU make to be installed.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"

echo "Running pre-commit checks..."
"$REPO_ROOT/scripts/dev/pre-commit-checks.sh"
echo "Pre-commit checks passed."
