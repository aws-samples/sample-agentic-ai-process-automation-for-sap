#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Package the project as a clean zip archive for external sharing.
# Uses git archive (only tracked files) then removes files that are
# only relevant to the internal development workflow.

set -euo pipefail

VERSION=$(cat VERSION 2>/dev/null || echo "0.0.0")
NAME="agentic-erp-automation-quickstart-v${VERSION}"
OUT_DIR="scripts/zip-artifact"
OUT_FILE="${OUT_DIR}/${NAME}.zip"

mkdir -p "$OUT_DIR"
rm -f "$OUT_FILE"

# ── Exclusions ────────────────────────────────────────────────────────────────
# Removed from the partner-facing archive: development-only, not needed to
# build, deploy, or extend the project.

EXCLUDES=(
  # Security scanner state file — no secrets, just tooling noise
  .secrets.baseline

  # ASH (Automated Security Helper) — references upstream awslabs repo
  .github/workflows/ash-full-repository-scan.yml
  .github/workflows/ash-security-scan.yml
  .github/workflows/ash-security-comment.yml

  # GitHub label automation — tied to a label taxonomy forks won't have
  .github/labeler.yml
  .github/workflows/label.yml

  # Dependabot policy is specific to this repo, not to downstream forks
  .github/workflows/dependabot.yml
)

# ── Package ───────────────────────────────────────────────────────────────────

echo "Packaging ${NAME}..."

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

git archive HEAD --format=tar | tar -x -C "$TMPDIR"

for f in "${EXCLUDES[@]}"; do
  rm -f "$TMPDIR/$f"
done

# ── Leak gate ─────────────────────────────────────────────────────────────────
# Fails the build if the export tree still references internal-only paths or
# internal-planning jargon. Runs against the post-export-ignore tree, so it
# catches anything the .gitattributes rules missed. Does not match the shipped
# threat-model taxonomy (T1-T17).

echo "Scanning export tree for internal references..."
LEAK_PATTERNS='\.docs-internal|docs/superpowers|\.threatmodel/|(^|[^a-zA-Z])MEMORY [a-z-]|spike-confirmed|fork.?2[ab]\b|design item #|spec §|Risk #[0-9]|\bP[0-8]-(deferred|slice)'
if LEAKS=$(grep -rInE "$LEAK_PATTERNS" "$TMPDIR" --include='*.py' --include='*.ts' --include='*.tsx' --include='*.js' --include='*.tf' --include='*.yaml' --include='*.yml' --include='*.md' --include='*.sh' --exclude='package-release.sh' 2>/dev/null); then
  echo ""
  echo "  ✗ Internal references found in the export tree — clean these before publishing:"
  echo "$LEAKS" | sed "s|$TMPDIR/|    |"
  echo ""
  echo "  (dead links to export-ignored paths, or internal planning codes.)"
  exit 1
fi
echo "  ✓ no internal references"

# ── Identifier gate ─────────────────────────────────────────────────────────
# Catches internal identifiers that look innocuous but leak real infra: AWS
# account IDs, Okta app/tenant IDs, internal demo/SAP hosts, non-public
# @amazon.com contacts. IDENT_ALLOW lists values that legitimately ship; those
# are stripped before the re-match, so a line with both an allowed and a
# leaked value still fails.

IDENT_PATTERNS='\b[0-9]{12}\b|\b0oa[0-9a-zA-Z]{17}\b|trial-[0-9]{5,}\.okta\.com|demos\.sap\.aws\.dev|\bdielom|[a-zA-Z0-9._%+-]+@amazon\.com'
IDENT_ALLOW='(017000801446|111122223333|(opensource-codeofconduct|aws-security)@amazon\.com)'
echo "Scanning export tree for internal identifiers..."
if IDENT_LEAKS=$(grep -rInE "$IDENT_PATTERNS" "$TMPDIR" --include='*.py' --include='*.ts' --include='*.tsx' --include='*.js' --include='*.tf' --include='*.yaml' --include='*.yml' --include='*.md' --include='*.sh' --exclude='package-release.sh' 2>/dev/null \
    | sed -E "s/$IDENT_ALLOW//g" \
    | grep -E "$IDENT_PATTERNS"); then
  echo ""
  echo "  ✗ Internal identifiers found in the export tree — scrub these before publishing:"
  echo "$IDENT_LEAKS" | sed "s|$TMPDIR/|    |"
  echo ""
  echo "  (real AWS account IDs, Okta app/tenant IDs, internal demo/SAP hosts, or"
  echo "   non-public @amazon.com contacts. Genericize or export-ignore the source file.)"
  exit 1
fi
echo "  ✓ no internal identifiers"

(cd "$TMPDIR" && zip -r -q "$OLDPWD/$OUT_FILE" .)

FILE_COUNT=$(zipinfo -1 "$OUT_FILE" | wc -l | tr -d ' ')
FILE_SIZE=$(du -h "$OUT_FILE" | cut -f1 | tr -d ' ')

echo ""
echo "  ✓ ${OUT_FILE}"
echo "    ${FILE_COUNT} files, ${FILE_SIZE}"
echo ""
echo "  Excluded from archive:"
for f in "${EXCLUDES[@]}"; do
  echo "    - ${f}"
done
echo ""
