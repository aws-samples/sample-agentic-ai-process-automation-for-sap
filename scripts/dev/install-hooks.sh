#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Installs the repository's pre-commit hook.
#
# Usage: ./scripts/dev/install-hooks.sh
# Called by: make install-hooks
#
# Resolves the hooks directory via `git rev-parse` rather than assuming
# `.git/hooks`. In a git worktree `.git` is a file, not a directory, so the
# hard-coded path this replaces failed outright there.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

GREEN='\033[0;32m'; NC='\033[0m'

# core.hooksPath wins over the default location when it is set, so honour it.
HOOKS_DIR="$(git config --get core.hooksPath || true)"
if [[ -z "$HOOKS_DIR" ]]; then
  # Hooks live in the common dir, shared across all worktrees.
  HOOKS_DIR="$(git rev-parse --git-common-dir)/hooks"
fi

mkdir -p "$HOOKS_DIR"
install -m 0755 scripts/dev/pre-commit.sh "$HOOKS_DIR/pre-commit"

echo -e "${GREEN}Pre-commit hook installed at ${HOOKS_DIR}/pre-commit${NC}"
