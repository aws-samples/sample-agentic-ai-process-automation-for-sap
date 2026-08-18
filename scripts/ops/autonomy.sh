#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Autonomy controls — flip trigger-mode without redeployment.
#
# Usage:
#   ./scripts/ops/autonomy.sh get                       # show current settings
#   ./scripts/ops/autonomy.sh set trigger-mode auto     # auto | manual
#
# Requires: aws cli configured with appropriate permissions.

set -euo pipefail

STACK="${STACK_NAME_BASE:?Set STACK_NAME_BASE env var (must match stack_name_base in config.yaml)}"
REGION="${AWS_REGION:-us-east-1}"

_get() {
  local param="$1"
  aws ssm get-parameter \
    --name "/${STACK}/autonomy/${param}" \
    --region "$REGION" \
    --query 'Parameter.Value' --output text 2>/dev/null || echo "(not set)"
}

_set() {
  local param="$1" value="$2"
  aws ssm put-parameter \
    --name "/${STACK}/autonomy/${param}" \
    --value "$value" \
    --type String \
    --overwrite \
    --region "$REGION" >/dev/null
  echo "✅ ${param} → ${value}"
}

case "${1:-get}" in
  get)
    echo "Stack: ${STACK} (${REGION})"
    echo "  trigger-mode: $(_get trigger-mode)"
    ;;
  set)
    param="${2:-}"
    value="${3:-}"
    case "$param" in
      trigger-mode)
        [[ "$value" =~ ^(auto|manual)$ ]] || { echo "❌ Must be: auto | manual"; exit 1; }
        _set "$param" "$value"
        ;;
      *) echo "❌ Unknown param: $param (use trigger-mode)"; exit 1 ;;
    esac
    ;;
  *) echo "Usage: $0 {get|set} [trigger-mode] [value]"; exit 1 ;;
esac
