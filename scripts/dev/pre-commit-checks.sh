#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Regenerates types, auto-fixes lint, and stages any regenerated type files so a
# commit never lands with types that disagree with the schemas.
#
# Usage: ./scripts/dev/pre-commit-checks.sh
# Called by: make pre-commit, and the installed git hook (scripts/dev/pre-commit.sh)
#
# Lives in a script rather than the Makefile so committing does not require GNU
# make — the hook used to shell out to `make pre-commit`, which meant no make,
# no commits.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

YELLOW='\033[1;33m'; NC='\033[0m'

./scripts/dev/generate-types.sh
./scripts/dev/lint.sh --fix

# Portable read loop rather than `mapfile`, which needs bash 4+ (macOS ships 3.2).
GENERATED=""
while IFS= read -r generated_path; do
  [[ -n "$generated_path" ]] && GENERATED="${GENERATED:+$GENERATED }$generated_path"
done < <(./scripts/dev/generate-types.sh --list)

# shellcheck disable=SC2086 - deliberate word splitting over the path list
if ! git diff --quiet -- $GENERATED; then
  # shellcheck disable=SC2086
  git add -- $GENERATED
  echo -e "${YELLOW}Auto-staged regenerated types.${NC}"
fi
