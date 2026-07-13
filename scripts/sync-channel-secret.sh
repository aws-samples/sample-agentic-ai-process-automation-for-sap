#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Syncs the webhook signing secret into the notification channel's
# Secrets Manager secret (the same secret that holds outbound channel creds).
#
# Reads notification.secret_arn from config.yaml, prompts for the webhook
# signing secret, and merges it into the existing secret as the
# "webhook_secret" key.
#
# Usage:
#   ./scripts/sync-channel-secret.sh           # interactive
#   ./scripts/sync-channel-secret.sh --force   # always re-prompt

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/../cdk/config.yaml"
source "$SCRIPT_DIR/lib/common.sh"

CHANNEL=$(awk '/^notification:/{found=1} found && /^[[:space:]]+channel:/{gsub(/.*channel:[[:space:]]*/, ""); gsub(/#.*/, ""); gsub(/^[[:space:]]+|[[:space:]]+$/, ""); print; exit}' "$CONFIG_FILE")
[[ -z "$CHANNEL" ]] && fail "No notification.channel found in $CONFIG_FILE"

if [[ "$CHANNEL" == "ses" || "$CHANNEL" == "tickets" ]]; then
  info "Channel is '$CHANNEL' — webhook signing secret not applicable."
  exit 0
fi

SECRET_ARN=$(awk '/^notification:/{found=1} found && /^[[:space:]]+secret_arn:/{gsub(/.*secret_arn:[[:space:]]*/, ""); gsub(/#.*/, ""); gsub(/^[[:space:]]+|[[:space:]]+$/, ""); print; exit}' "$CONFIG_FILE")
[[ -z "$SECRET_ARN" ]] && fail "No notification.secret_arn found in $CONFIG_FILE. Create the secret first."

REGION=$(aws configure get region 2>/dev/null || echo "us-east-1")

CURRENT=$(aws secretsmanager get-secret-value \
  --secret-id "$SECRET_ARN" --query SecretString --output text --region "$REGION" 2>/dev/null) \
  || fail "Could not read secret $SECRET_ARN. Check the ARN and permissions."

CURRENT_WH=$(echo "$CURRENT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('webhook_secret',''))" 2>/dev/null || echo "")

FORCE="${1:-}"

info "Channel:        $CHANNEL"
info "Secret ARN:     $SECRET_ARN"
if [[ -n "$CURRENT_WH" ]]; then
  info "Current secret: (set, ${#CURRENT_WH} chars)"
else
  info "Current secret: (not set)"
fi
echo ""

if [[ -n "$CURRENT_WH" && "$FORCE" != "--force" ]]; then
  info "Webhook secret already configured. Use --force to update."
  exit 0
fi

case "$CHANNEL" in
  slack)       info "Slack: paste the Signing Secret from App admin → Basic Information." ;;
  jira)        info "Jira: paste the secret you set when creating the webhook." ;;
  servicenow)  info "ServiceNow: paste the shared auth token from your outbound REST config." ;;
esac

read -rsp "  Webhook signing secret: " input_secret
echo ""
[[ -z "$input_secret" ]] && fail "No secret provided."

NEW_SECRET=$(python3 -c "
import json, sys
current = json.loads(sys.argv[1])
current['webhook_secret'] = sys.argv[2]
print(json.dumps(current))
" "$CURRENT" "$input_secret")

aws secretsmanager put-secret-value \
  --secret-id "$SECRET_ARN" \
  --secret-string "$NEW_SECRET" \
  --region "$REGION" > /dev/null

success "Updated webhook_secret in $SECRET_ARN"
