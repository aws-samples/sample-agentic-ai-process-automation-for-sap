#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Runs every linter and formatter across Python and the frontend.
#
# Usage: ./scripts/dev/lint.sh [--fix | --check]
#   --fix    (default) auto-fix what can be fixed
#   --check  report only, non-zero on any finding — the CI mode
#
# Called by: make lint, make lint-cicd, scripts/dev/pre-commit-checks.sh
#
# This logic previously lived inline in the Makefile as two near-duplicate
# copies, one per mode. Keeping it here means the fix and check paths cannot
# disagree about which tools run, or over which paths.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

MODE="${1:---fix}"
case "$MODE" in
  --fix|--check) ;;
  -h|--help) sed -n '6,11p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
  *) echo "ERROR: unknown option '$MODE' (expected --fix or --check)" >&2; exit 2 ;;
esac

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
FRONTEND_GLOB='src/**/*.{ts,tsx,js,jsx,css,json}'

# Plain counter and string rather than an array: empty-array expansion under
# `set -u` is unreliable on the bash 3.2 that ships with macOS.
FAILED_COUNT=0
FAILED_NAMES=""

# Run one tool, recording rather than aborting on failure so a single run
# reports every problem instead of only the first.
# Args: <label> <local-fix-hint> <command...>
run_tool() {
  local label="$1" hint="$2"
  shift 2
  if "$@"; then
    return 0
  fi
  echo -e "${RED}x ${label} failed.${NC}" >&2
  if [[ -n "$hint" ]]; then
    echo -e "${YELLOW}  Fix locally with: ${hint}${NC}" >&2
  fi
  FAILED_COUNT=$((FAILED_COUNT + 1))
  FAILED_NAMES="${FAILED_NAMES:+$FAILED_NAMES, }${label}"
  return 1
}

if [[ "$MODE" == "--fix" ]]; then
  run_tool "ruff check"  "" ruff check --fix
  run_tool "ruff format" "" ruff format
  run_tool "eslint"      "" bash -c 'cd frontend && npx eslint --fix src/'
  run_tool "prettier"    "" bash -c "cd frontend && npx prettier --write \"$FRONTEND_GLOB\""
else
  echo "Running code quality checks..."
  run_tool "Ruff lint"           "make ruff-lint" ruff check
  run_tool "Python formatting"   "make format"    ruff format --check
  run_tool "ESLint"              "make eslint"    bash -c 'cd frontend && npx eslint src/'
  run_tool "Prettier"            "make prettier"  bash -c "cd frontend && npx prettier --check \"$FRONTEND_GLOB\""
fi

if [[ "$FAILED_COUNT" -gt 0 ]]; then
  echo -e "\n${RED}${FAILED_COUNT} check(s) failed: ${FAILED_NAMES}${NC}" >&2
  exit 1
fi

if [[ "$MODE" == "--check" ]]; then
  echo -e "${GREEN}All code quality checks passed.${NC}"
fi
