#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Syncs local knowledge-base/ content to S3 and triggers Bedrock KB re-ingestion.
#
# Usage:
#   ./scripts/sync-knowledge-base.sh              # sync SOPs + API docs
#   ./scripts/sync-knowledge-base.sh --sops-only   # sync SOPs only
#   ./scripts/sync-knowledge-base.sh --docs-only   # sync API docs only

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR/.."
CONFIG_FILE="$PROJECT_ROOT/cdk/config.yaml"
source "$SCRIPT_DIR/lib/common.sh"

STACK_NAME=$(read_config_key "$CONFIG_FILE" stack_name_base)
[[ -z "$STACK_NAME" ]] && fail "Could not read stack_name_base from $CONFIG_FILE"

# Honor the standard AWS region env vars first (so deploys to a non-default
# region work without editing `aws configure`), then fall back to the profile.
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-$(aws configure get region 2>/dev/null || echo "us-east-1")}}"
MODE="${1:-all}"

ssm_get() {
  aws ssm get-parameter --name "$1" --query Parameter.Value --output text --region "$REGION" 2>/dev/null \
    || fail "SSM parameter $1 not found. Deploy infrastructure first."
}

# Assume the sop-admin role (bucket policy denies writes from all other principals)
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text --region "$REGION")
SOP_ADMIN_ROLE="arn:aws:iam::${ACCOUNT_ID}:role/${STACK_NAME}-sop-admin"
info "Assuming SOP admin role: $SOP_ADMIN_ROLE"
CREDS=$(aws sts assume-role --role-arn "$SOP_ADMIN_ROLE" --role-session-name "kb-sync" --region "$REGION" \
  --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' --output text) \
  || fail "Could not assume ${STACK_NAME}-sop-admin role. Check IAM permissions."
SOP_KEY=$(echo "$CREDS" | awk '{print $1}')
SOP_SECRET=$(echo "$CREDS" | awk '{print $2}')
SOP_TOKEN=$(echo "$CREDS" | awk '{print $3}')

sync_and_ingest() {
  local label="$1" local_dir="$2" bucket="$3" kb_id="$4"

  info "Syncing $label to s3://$bucket/ ..."
  AWS_ACCESS_KEY_ID="$SOP_KEY" AWS_SECRET_ACCESS_KEY="$SOP_SECRET" AWS_SESSION_TOKEN="$SOP_TOKEN" \
    aws s3 sync "$local_dir" "s3://$bucket/" --delete --region "$REGION"
  success "$label synced to S3"

  if [[ -n "$kb_id" ]]; then
    info "Starting Bedrock KB ingestion for $label ..."
    local ds_id
    ds_id=$(aws bedrock-agent list-data-sources --knowledge-base-id "$kb_id" \
      --query "dataSourceSummaries[0].dataSourceId" --output text --region "$REGION" 2>/dev/null) \
      || fail "Could not find data source for KB $kb_id"

    aws bedrock-agent start-ingestion-job \
      --knowledge-base-id "$kb_id" --data-source-id "$ds_id" --region "$REGION" > /dev/null
    success "$label KB ingestion started (KB: $kb_id)"
  fi
}

info "Stack: $STACK_NAME  Region: $REGION"
echo ""

if [[ "$MODE" != "--docs-only" ]]; then
  SOPS_BUCKET=$(ssm_get "/${STACK_NAME}/s3/sops-bucket")
  SOPS_KB_ID=$(ssm_get "/${STACK_NAME}/bedrock/sops-kb-id")
  sync_and_ingest "SOPs" "$PROJECT_ROOT/knowledge-base/sops" "$SOPS_BUCKET" "$SOPS_KB_ID"
fi

if [[ "$MODE" != "--sops-only" ]]; then
  DOCS_BUCKET=$(ssm_get "/${STACK_NAME}/s3/api-docs-bucket")
  DOCS_KB_ID=$(ssm_get "/${STACK_NAME}/bedrock/api-docs-kb-id")
  sync_and_ingest "API docs" "$PROJECT_ROOT/knowledge-base/sap-api-docs" "$DOCS_BUCKET" "$DOCS_KB_ID"
fi

echo ""
success "Knowledge base sync complete!"
