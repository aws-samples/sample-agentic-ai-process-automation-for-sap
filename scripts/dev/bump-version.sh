#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Bump the project version across all tracked files.
#
# The VERSION file is the single source of truth. This script:
#   1. Updates VERSION
#   2. Syncs frontend/package.json and cdk/package.json
#   3. Regenerates lock files
#   4. Adds a stub entry to CHANGELOG.md
#
# pyproject.toml reads VERSION dynamically via setuptools — no update needed.
# terraform/VERSION is independent (tracks TF compatibility) — not touched.
#
# Usage:
#   ./scripts/dev/bump-version.sh 0.7.0
#   make bump-version VERSION=0.7.0

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

NEW_VERSION="${1:-}"

if [[ -z "$NEW_VERSION" ]]; then
  echo -e "${RED}Usage: $0 <version>${NC}"
  echo "  Example: $0 0.7.0"
  exit 1
fi

# Validate semver format
if [[ ! "$NEW_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo -e "${RED}Error: Version must be semver (e.g. 0.7.0), got: $NEW_VERSION${NC}"
  exit 1
fi

OLD_VERSION=$(cat "$ROOT_DIR/VERSION" | tr -d '[:space:]')
echo "Bumping version: $OLD_VERSION → $NEW_VERSION"

# 1. Update VERSION file
echo "$NEW_VERSION" > "$ROOT_DIR/VERSION"
echo -e "${GREEN}✓${NC} VERSION"

# 2. Update package.json files
for pkg in frontend/package.json cdk/package.json; do
  if [[ -f "$ROOT_DIR/$pkg" ]]; then
    # Use node for reliable JSON manipulation
    node -e "
      const fs = require('fs');
      const path = '$ROOT_DIR/$pkg';
      const pkg = JSON.parse(fs.readFileSync(path, 'utf8'));
      pkg.version = '$NEW_VERSION';
      fs.writeFileSync(path, JSON.stringify(pkg, null, 2) + '\n');
    "
    echo -e "${GREEN}✓${NC} $pkg"
  fi
done

# 3. Regenerate lock files
for dir in frontend cdk; do
  if [[ -f "$ROOT_DIR/$dir/package.json" ]]; then
    (cd "$ROOT_DIR/$dir" && npm install --package-lock-only --silent 2>/dev/null)
    echo -e "${GREEN}✓${NC} $dir/package-lock.json"
  fi
done

# 4. Add CHANGELOG stub (only if version not already present)
if ! grep -q "## \[$NEW_VERSION\]" "$ROOT_DIR/CHANGELOG.md" 2>/dev/null; then
  TODAY=$(date +%Y-%m-%d)
  # Insert a stub entry after [Unreleased], before the first versioned entry
  awk -v ver="$NEW_VERSION" -v date="$TODAY" '
    /^## \[[0-9]/ && !done {
      printf "## [%s] — %s\n\n### Added\n\n### Changed\n\n### Fixed\n\n", ver, date
      done=1
    }
    {print}
  ' "$ROOT_DIR/CHANGELOG.md" > "$ROOT_DIR/CHANGELOG.md.tmp"
  mv "$ROOT_DIR/CHANGELOG.md.tmp" "$ROOT_DIR/CHANGELOG.md"
  echo -e "${GREEN}✓${NC} CHANGELOG.md (stub added — fill in before committing)"
else
  echo -e "${YELLOW}⚠${NC} CHANGELOG.md already has [$NEW_VERSION]"
fi

echo ""
echo -e "${GREEN}Version bumped to $NEW_VERSION${NC}"
echo -e "  pyproject.toml reads VERSION dynamically — no update needed."
echo -e "  terraform/VERSION is independent — update manually if TF is verified compatible."
echo ""
echo "Next steps:"
echo "  1. Fill in CHANGELOG.md"
echo "  2. git add -A && git commit -m \"chore: Bump version to $NEW_VERSION\""
