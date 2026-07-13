#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Local development launcher — starts the agent container and frontend dev server.
# Requires: deployed CDK stacks, Docker, npm, valid AWS credentials.
#
# Usage:
#   ./scripts/dev/local-dev.sh          # starts agent + frontend
#   ./scripts/dev/local-dev.sh agent    # starts agent only
#   ./scripts/dev/local-dev.sh frontend # starts frontend only
#   ./scripts/dev/local-dev.sh config   # generate aws-exports.json only, then exit

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CONFIG="$ROOT/cdk/config.yaml"
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

STACK_NAME=$(read_config_key "$CONFIG" stack_name_base)
if [[ -z "$STACK_NAME" ]]; then
  echo "❌ stack_name_base not found in $CONFIG"
  exit 1
fi
echo "📦 Stack: $STACK_NAME"

if ! aws sts get-caller-identity &>/dev/null; then
  echo "❌ AWS credentials invalid or expired. Refresh and retry."
  exit 1
fi

export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-$(aws configure get aws_access_key_id 2>/dev/null || true)}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-$(aws configure get aws_secret_access_key 2>/dev/null || true)}"
export AWS_SESSION_TOKEN="${AWS_SESSION_TOKEN:-$(aws configure get aws_session_token 2>/dev/null || true)}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"

if [[ -z "$AWS_ACCESS_KEY_ID" ]]; then
  echo "❌ AWS_ACCESS_KEY_ID is empty. Export credentials or configure a profile."
  exit 1
fi

echo "🔍 Fetching stack outputs..."
get_output() {
  aws cloudformation describe-stacks \
    --stack-name "$1" \
    --region "$AWS_DEFAULT_REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue" \
    --output text 2>/dev/null
}

MEMORY_ARN=$(get_output "${STACK_NAME}-backend" "MemoryArn")
MEMORY_ID="${MEMORY_ARN##*/}"
RUNTIME_ARN=$(get_output "${STACK_NAME}-backend" "RuntimeArn")
FEEDBACK_URL=$(get_output "${STACK_NAME}-backend" "FeedbackApiUrl")
POOL_ID=$(get_output "${STACK_NAME}-cognito" "CognitoUserPoolId")
CLIENT_ID=$(get_output "${STACK_NAME}-cognito" "CognitoClientId")
DEMO_URL=$(get_output "${STACK_NAME}-demo" "DemoApiUrl" || true)
TICKETS_TABLE=$(get_output "${STACK_NAME}-backend" "TicketsTableName" || true)
PATTERN=$(read_config_key "$CONFIG" '\s*pattern')
PATTERN="${PATTERN:-agent}"

echo "  Memory ID:   $MEMORY_ID"
echo "  Runtime ARN: $RUNTIME_ARN"

write_aws_exports "$ROOT/frontend/public/aws-exports.json" "$AWS_DEFAULT_REGION" \
  "$POOL_ID" "$CLIENT_ID" "$RUNTIME_ARN" "$FEEDBACK_URL" "$PATTERN" "http://localhost:3000" "$DEMO_URL" "$TICKETS_TABLE"
echo "✅ aws-exports.json generated"

MODE="${1:-all}"

start_agent() {
  echo "🐳 Starting agent container..."
  cd "$ROOT/docker"
  MEMORY_ID="$MEMORY_ID" \
  STACK_NAME="${STACK_NAME}" \
  GATEWAY_CREDENTIAL_PROVIDER_NAME="${STACK_NAME}-runtime-gateway-auth" \
  AWS_DEFAULT_REGION="$AWS_DEFAULT_REGION" \
  AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
  AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
  AWS_SESSION_TOKEN="$AWS_SESSION_TOKEN" \
  docker compose up agent --build "$@"
}

start_frontend() {
  echo "🌐 Starting frontend dev server..."
  cd "$ROOT/frontend"
  npm run dev
}

case "$MODE" in
  config)
    # aws-exports.json already written above — nothing to start.
    echo "   Run: cd frontend && npm run dev"
    ;;
  agent)
    start_agent
    ;;
  frontend)
    start_frontend
    ;;
  all)
    start_agent -d
    echo "⏳ Waiting for agent health..."
    for i in $(seq 1 30); do
      if curl -sf http://localhost:8080/ping &>/dev/null; then
        echo "✅ Agent healthy"
        break
      fi
      sleep 2
    done
    start_frontend
    ;;
  *)
    echo "Usage: $0 [agent|frontend|all|config]"
    exit 1
    ;;
esac
