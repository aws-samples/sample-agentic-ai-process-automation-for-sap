#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Syncs SAP connection settings from config.yaml into Secrets Manager, then
# bounces any Lambda attached to the sap-auth layer so it picks up the new
# credentials (the layer caches them at module import time).
#
# Usage:
#   ./scripts/sync-sap-secret.sh                    # interactive
#   ./scripts/sync-sap-secret.sh --force            # always prompt
#   ./scripts/sync-sap-secret.sh --refresh-lambdas  # bounce lambdas even if unchanged
#   ./scripts/sync-sap-secret.sh --skip-refresh     # write secret only, skip bounce

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/../cdk/config.yaml"
source "$SCRIPT_DIR/lib/common.sh"

STACK_NAME=$(read_config_key "$CONFIG_FILE" stack_name_base)
[[ -z "$STACK_NAME" ]] && fail "Could not read stack_name_base from $CONFIG_FILE"

# Honor the standard AWS region env vars first (so deploys to a non-default
# region work without editing `aws configure`), then fall back to the profile.
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-$(aws configure get region 2>/dev/null || echo "us-east-1")}}"

# Match base_url only under the sap: section, not other top-level keys
SAP_BASE_URL=$(awk '/^sap:/{found=1} found && /^[[:space:]]+base_url:/{gsub(/.*base_url:[[:space:]]*/, ""); gsub(/#.*/, ""); gsub(/^[[:space:]]+|[[:space:]]+$/, ""); print; exit}' "$CONFIG_FILE")
[[ -z "$SAP_BASE_URL" ]] && fail "No sap.base_url found in $CONFIG_FILE"

# Secret consumers append the OData service root themselves, so store the bare
# host: an OData-root base_url here silently doubles the path and every SAP call
# 404s. config.yaml conventionally carries the OData-root form, so strip it.
SAP_BASE_URL=$(printf '%s' "$SAP_BASE_URL" | sed -E 's#/sap/opu/odata/sap/?$##; s#/+$##')

SECRET_ARN=$(aws ssm get-parameter \
  --name "/${STACK_NAME}/secrets/sap-credentials-arn" \
  --query Parameter.Value --output text --region "$REGION" 2>/dev/null) \
  || fail "SSM parameter /${STACK_NAME}/secrets/sap-credentials-arn not found. Deploy infrastructure first."

CURRENT=$(aws secretsmanager get-secret-value \
  --secret-id "$SECRET_ARN" --query SecretString --output text --region "$REGION")

CURRENT_URL=$(echo "$CURRENT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('base_url',''))")
CURRENT_USER=$(echo "$CURRENT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('username',''))")
CURRENT_PASS=$(echo "$CURRENT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('password',''))")

FORCE=""
REFRESH_MODE="auto"  # auto | always | never
for arg in "$@"; do
  case "$arg" in
    --force)            FORCE="--force" ;;
    --refresh-lambdas)  REFRESH_MODE="always" ;;
    --skip-refresh)     REFRESH_MODE="never" ;;
    *) fail "Unknown argument: $arg" ;;
  esac
done

NEED_CREDS=false

if [[ "$CURRENT_USER" == "PLACEHOLDER" || "$CURRENT_PASS" == "PLACEHOLDER" || "$FORCE" == "--force" ]]; then
  NEED_CREDS=true
fi

info "Stack:        $STACK_NAME"
info "SAP base URL: $SAP_BASE_URL (from config.yaml)"
info "Current URL:  $CURRENT_URL (in Secrets Manager)"
echo ""

USERNAME="$CURRENT_USER"
PASSWORD="$CURRENT_PASS"

if [[ "$NEED_CREDS" == "true" ]]; then
  warn "SAP credentials need to be set."
  read -rp "  SAP username [$CURRENT_USER]: " input_user
  USERNAME="${input_user:-$CURRENT_USER}"
  read -rsp "  SAP password: " input_pass
  echo ""
  PASSWORD="${input_pass:-$CURRENT_PASS}"
fi

NEW_SECRET=$(python3 -c "
import json, sys
current = json.loads(sys.argv[1])
current['base_url'] = sys.argv[2]
current['username'] = sys.argv[3]
current['password'] = sys.argv[4]
print(json.dumps(current))
" "$CURRENT" "$SAP_BASE_URL" "$USERNAME" "$PASSWORD")

aws secretsmanager put-secret-value \
  --secret-id "$SECRET_ARN" \
  --secret-string "$NEW_SECRET" \
  --region "$REGION" > /dev/null

success "Updated secret: base_url=$SAP_BASE_URL, username=$USERNAME"

# Force cold start on SAP-consuming Lambdas: the sap_auth layer caches creds
# at module-import time, so already-running execution environments still
# hold the stale values until their env vars change.

CHANGED=false
[[ "$CURRENT_URL"  != "$SAP_BASE_URL" ]] && CHANGED=true
[[ "$CURRENT_USER" != "$USERNAME"     ]] && CHANGED=true
[[ "$CURRENT_PASS" != "$PASSWORD"     ]] && CHANGED=true

case "$REFRESH_MODE" in
  never)
    info "Skipping Lambda refresh (--skip-refresh)."
    exit 0
    ;;
  auto)
    if [[ "$CHANGED" != "true" ]]; then
      info "No secret values changed; Lambdas already have current creds."
      exit 0
    fi
    ;;
  always)
    info "Refreshing Lambdas unconditionally (--refresh-lambdas)."
    ;;
esac

LAYER_NAME="${STACK_NAME}-sap-auth"
info "Finding Lambdas attached to layer: $LAYER_NAME ..."

# List functions using the sap-auth layer in a single describe (paginated)
FN_NAMES=$(aws lambda list-functions --region "$REGION" \
  --query "Functions[?Layers != null] | [?not_null(Layers[?contains(Arn, '${LAYER_NAME}:')] | [0])].FunctionName" \
  --output text | tr '\t' '\n' | grep -v '^$' || true)

if [[ -z "$FN_NAMES" ]]; then
  warn "No Lambdas found with layer $LAYER_NAME — nothing to refresh."
  exit 0
fi

STAMP=$(date +%s)
REFRESHED=()

while IFS= read -r FN; do
  [[ -z "$FN" ]] && continue
  CUR_ENV=$(aws lambda get-function-configuration \
    --function-name "$FN" --region "$REGION" \
    --query 'Environment.Variables' --output json)
  NEW_ENV=$(python3 -c "
import json, sys
d = json.loads(sys.argv[1]) or {}
d['SAP_CREDS_VERSION'] = sys.argv[2]
print(json.dumps({'Variables': d}))
" "$CUR_ENV" "$STAMP")
  aws lambda update-function-configuration \
    --function-name "$FN" --region "$REGION" \
    --environment "$NEW_ENV" > /dev/null
  REFRESHED+=("$FN")
  info "  bumped $FN"
done <<< "$FN_NAMES"

for FN in "${REFRESHED[@]}"; do
  aws lambda wait function-updated --function-name "$FN" --region "$REGION"
done

success "Refreshed ${#REFRESHED[@]} Lambda(s); next invocation will pick up new creds."
