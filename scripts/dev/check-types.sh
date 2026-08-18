#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Verifies the generated types committed to the repository match what the
# schemas produce right now. Regenerates, then fails if anything changed.
#
# Usage: ./scripts/dev/check-types.sh
# Called by: make check-types (CI)
#
# The list of generated paths comes from `generate-types.sh --list` rather than
# a second copy here — the Makefile used to keep its own copy, with a comment
# admitting the two could drift.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'

./scripts/dev/generate-types.sh

# Portable read loop rather than `mapfile`, which needs bash 4+ (macOS ships 3.2).
GENERATED=""
while IFS= read -r generated_path; do
  [[ -n "$generated_path" ]] && GENERATED="${GENERATED:+$GENERATED }$generated_path"
done < <(./scripts/dev/generate-types.sh --list)

# shellcheck disable=SC2086 - deliberate word splitting over the path list
if ! git diff --quiet -- $GENERATED; then
  echo -e "${RED}ERROR: Generated types are stale.${NC}" >&2
  echo "Files that changed:" >&2
  # shellcheck disable=SC2086
  git diff --name-only -- $GENERATED >&2
  echo "Run 'make generate-types' and commit the result." >&2
  exit 1
fi

echo -e "${GREEN}Generated types are up-to-date.${NC}"
