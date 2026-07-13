#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Generates TypeScript and Python types from the JSON Schema source of truth.
# Usage: ./scripts/generate-types.sh
# Called by: make generate-types
set -euo pipefail

# Python models live in the shared_types Lambda layer (single home — imported by
# lambdas via the layer, no repo-root copy to drift). TS lives in the frontend.
CASES_SCHEMA="types/cases.schema.json"
CASES_TS_OUT="frontend/src/types/generated-cases.ts"
CASES_PY_OUT="lambdas/layers/shared_types/generated_cases.py"

TICKETS_SCHEMA="types/tickets.schema.json"
TICKETS_TS_OUT="frontend/src/types/generated-tickets.ts"
TICKETS_PY_OUT="lambdas/layers/shared_types/generated_tickets.py"

# Ensure quicktype is available
if ! command -v npx &>/dev/null; then
  echo "ERROR: npx not found" >&2; exit 1
fi

# Pin quicktype version for deterministic output across environments
QUICKTYPE="quicktype@23.0.170"

# Generate a Python module (pydantic v2 models) from a JSON Schema, then prepend
# our provenance header. Uses datamodel-code-generator via uvx (fallback: pipx).
# Args: <schema> <top-level class> <output path>
gen_python() {
  local schema="$1" top="$2" out="$3"
  echo "→ Generating Python from $schema"
  local runner
  if command -v uvx &>/dev/null; then
    runner=(uvx --from datamodel-code-generator datamodel-codegen)
  elif command -v pipx &>/dev/null; then
    runner=(pipx run datamodel-code-generator)
  else
    echo "ERROR: neither uvx nor pipx found (needed for datamodel-code-generator)" >&2; exit 1
  fi
  "${runner[@]}" \
    --input "$schema" \
    --input-file-type jsonschema \
    --output-model-type pydantic_v2.BaseModel \
    --class-name "$top" \
    --use-standard-collections \
    --use-schema-description \
    --target-python-version 3.13 \
    --formatters black \
    --disable-timestamp \
    --output "$out"

  local tmp
  tmp=$(mktemp)
  cat > "$tmp" <<EOF
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
# AUTO-GENERATED from $schema — do not edit manually.
# Regenerate with: make generate-types

EOF
  cat "$out" >> "$tmp"
  mv "$tmp" "$out"
}

echo "→ Generating TypeScript from $CASES_SCHEMA"
npx --yes "$QUICKTYPE" \
  --src "$CASES_SCHEMA" \
  --src-lang schema \
  --lang typescript \
  --top-level WorkItem \
  --just-types \
  --acronym-style original \
  -o "$CASES_TS_OUT"

# Prepend header
TMPFILE=$(mktemp)
cat > "$TMPFILE" <<'EOF'
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
// AUTO-GENERATED from types/cases.schema.json — do not edit manually.
// Regenerate with: make generate-types

EOF
cat "$CASES_TS_OUT" >> "$TMPFILE"
mv "$TMPFILE" "$CASES_TS_OUT"

gen_python "$CASES_SCHEMA" WorkItem "$CASES_PY_OUT"

echo "→ Generating TypeScript from $TICKETS_SCHEMA"
npx --yes "$QUICKTYPE" \
  --src "$TICKETS_SCHEMA" \
  --src-lang schema \
  --lang typescript \
  --top-level Ticket \
  --just-types \
  --acronym-style original \
  -o "$TICKETS_TS_OUT"

TMPFILE=$(mktemp)
cat > "$TMPFILE" <<'EOF'
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
// AUTO-GENERATED from types/tickets.schema.json — do not edit manually.
// Regenerate with: make generate-types

EOF
cat "$TICKETS_TS_OUT" >> "$TMPFILE"
mv "$TMPFILE" "$TICKETS_TS_OUT"

gen_python "$TICKETS_SCHEMA" Ticket "$TICKETS_PY_OUT"

# Normalize formatting so committed output is deterministic across environments.
if command -v ruff &>/dev/null; then
  ruff check --fix --quiet "$CASES_PY_OUT" "$TICKETS_PY_OUT" 2>/dev/null || true
  ruff format --quiet "$CASES_PY_OUT" "$TICKETS_PY_OUT" 2>/dev/null || true
fi

# Format the generated TypeScript with the frontend's prettier config so output
# matches the committed files (raw quicktype indentation differs from prettier's).
(cd frontend && npx --yes prettier --write \
  "src/types/$(basename "$CASES_TS_OUT")" \
  "src/types/$(basename "$TICKETS_TS_OUT")" >/dev/null 2>&1) || true

echo "✅ Types generated:"
echo "   Cases  TS:  $CASES_TS_OUT"
echo "   Cases  PY:  $CASES_PY_OUT"
echo "   Tickets TS: $TICKETS_TS_OUT"
echo "   Tickets PY: $TICKETS_PY_OUT"

# Validate domain polling configs against the schema
echo "→ Validating domain polling configs against schema"
python3 scripts/dev/validate_domain_configs.py
