#!/bin/bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# =============================================================================
# Deploy Frontend to AWS Amplify
# =============================================================================
#
# Deploys the Next.js frontend to Amplify using Terraform outputs.
#
# Usage:
#   ./scripts/deploy-frontend.sh [options]
#
# Options:
#   -p, --pattern    Agent pattern (default: from terraform.tfvars or agent)
#   -h, --help       Show this help message
#
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

PATTERN=""
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TERRAFORM_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$TERRAFORM_DIR")"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
BRANCH_NAME="main"
BUILD_DIR="build"

usage() {
    echo "Usage: $0 [options]"
    echo ""
    echo "Options:"
    echo "  -p, --pattern    Agent pattern (default: from terraform.tfvars or agent)"
    echo "  -h, --help       Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0                                    # Use defaults from Terraform"
    echo "  $0 -p agent          # Use the Strands agent pattern"
}

while [[ $# -gt 0 ]]; do
    case $1 in
        -p|--pattern)
            PATTERN="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo -e "${RED}Error: Unknown option $1${NC}"
            usage
            exit 1
            ;;
    esac
done

log_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

log_success() {
    echo -e "${GREEN}✓${NC} $1"
}

log_error() {
    echo -e "${RED}✗${NC} $1" >&2
}

log_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

get_file_size() {
    local size=$(stat -f%z "$1" 2>/dev/null || stat --printf="%s" "$1" 2>/dev/null)
    if [[ $size -lt 1024 ]]; then
        echo "${size}B"
    elif [[ $size -lt 1048576 ]]; then
        echo "$(echo "scale=1; $size/1024" | bc)KB"
    else
        echo "$(echo "scale=1; $size/1048576" | bc)MB"
    fi
}

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Frontend Deployment (Terraform)      ${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

log_info "🚀 Starting frontend deployment process..."
echo ""

log_info "Validating prerequisites..."
for cmd in npm aws node terraform jq; do
    # shellcheck disable=SC2086 — loop variable is a single word
    if ! command -v $cmd &> /dev/null; then
        log_error "$cmd is not installed"
        exit 1
    fi
done
log_success "All prerequisites found"

log_info "Verifying AWS credentials..."
if ! aws sts get-caller-identity &> /dev/null; then
    log_error "AWS credentials not configured or invalid"
    log_info "Run 'aws configure' to set up your AWS credentials"
    exit 1
fi
log_success "AWS credentials configured"

cd "$TERRAFORM_DIR"

if [[ ! -f "terraform.tfstate" ]]; then
    log_error "Terraform state not found. Run 'terraform apply' first."
    exit 1
fi

log_info "Fetching configuration from Terraform outputs..."

AMPLIFY_APP_ID=$(terraform output -raw amplify_app_id 2>/dev/null)
STAGING_BUCKET=$(terraform output -raw amplify_staging_bucket 2>/dev/null)
COGNITO_CLIENT_ID=$(terraform output -raw cognito_web_client_id 2>/dev/null)
COGNITO_USER_POOL_ID=$(terraform output -raw cognito_user_pool_id 2>/dev/null)
AMPLIFY_URL=$(terraform output -raw amplify_app_url 2>/dev/null)
RUNTIME_ARN=$(terraform output -raw runtime_arn 2>/dev/null)
FEEDBACK_API_URL=$(terraform output -raw feedback_api_url 2>/dev/null)
AWS_REGION=$(terraform output -json deployment_summary 2>/dev/null | jq -r '.region')

if [[ -z "$AMPLIFY_APP_ID" ]]; then
    log_error "Could not find Amplify App ID in Terraform outputs"
    exit 1
fi
if [[ -z "$STAGING_BUCKET" ]]; then
    log_error "Could not find Staging Bucket in Terraform outputs"
    exit 1
fi
if [[ -z "$COGNITO_CLIENT_ID" ]]; then
    log_error "Could not find Cognito Client ID in Terraform outputs"
    exit 1
fi
if [[ -z "$RUNTIME_ARN" ]]; then
    log_error "Could not find Runtime ARN in Terraform outputs"
    exit 1
fi

log_success "App ID: $AMPLIFY_APP_ID"
log_success "Staging Bucket: $STAGING_BUCKET"
log_success "Region: $AWS_REGION"

if [[ -z "$PATTERN" ]]; then
    TFVARS_FILE="$TERRAFORM_DIR/terraform.tfvars"
    if [[ -f "$TFVARS_FILE" ]]; then
        PATTERN=$(grep -E '^backend_pattern\s*=' "$TFVARS_FILE" | awk -F'"' '{print $2}')
    fi
fi
PATTERN="${PATTERN:-agent}"
log_info "Agent pattern: $PATTERN"

log_info "Generating aws-exports.json..."

AWS_EXPORTS=$(cat <<EOF
{
  "authority": "https://cognito-idp.${AWS_REGION}.amazonaws.com/${COGNITO_USER_POOL_ID}",
  "client_id": "${COGNITO_CLIENT_ID}",
  "redirect_uri": "${AMPLIFY_URL}",
  "post_logout_redirect_uri": "${AMPLIFY_URL}",
  "response_type": "code",
  "scope": "email openid profile",
  "automaticSilentRenew": true,
  "agentRuntimeArn": "${RUNTIME_ARN}",
  "awsRegion": "${AWS_REGION}",
  "feedbackApiUrl": "${FEEDBACK_API_URL}",
  "agentPattern": "${PATTERN}"
}
EOF
)

mkdir -p "$FRONTEND_DIR/public"
echo "$AWS_EXPORTS" > "$FRONTEND_DIR/public/aws-exports.json"
log_success "Generated aws-exports.json at $FRONTEND_DIR/public/aws-exports.json"

cd "$FRONTEND_DIR"
log_info "Working directory: $FRONTEND_DIR"

if [[ ! -d "node_modules" ]] || [[ "package.json" -nt "node_modules" ]]; then
    log_info "Installing dependencies..."
    npm install
    log_success "Dependencies installed"
else
    log_success "Dependencies are up to date"
fi

log_info "Building Next.js app..."
npm run build
log_success "Build completed"

if [[ ! -d "$BUILD_DIR" ]]; then
    log_error "Build directory '$BUILD_DIR' not found"
    exit 1
fi

cp "$FRONTEND_DIR/public/aws-exports.json" "$FRONTEND_DIR/$BUILD_DIR/aws-exports.json"
log_success "Added aws-exports.json to build directory"

log_info "Creating deployment package..."
ZIP_FILE="$FRONTEND_DIR/amplify-deploy.zip"
cd "$FRONTEND_DIR/$BUILD_DIR"
zip -r "$ZIP_FILE" . -x "*.DS_Store" > /dev/null
cd "$FRONTEND_DIR"

ZIP_SIZE=$(get_file_size "$ZIP_FILE")
log_success "Package created ($ZIP_SIZE)"

S3_KEY="amplify-deploy-$(date +%s).zip"
log_info "Uploading to S3 (s3://${STAGING_BUCKET}/${S3_KEY})..."
aws s3 cp "$ZIP_FILE" "s3://${STAGING_BUCKET}/${S3_KEY}" --no-progress
log_success "Upload completed"

log_info "Starting Amplify deployment..."
DEPLOYMENT=$(aws amplify start-deployment \
    --app-id "$AMPLIFY_APP_ID" \
    --branch-name "$BRANCH_NAME" \
    --source-url "s3://${STAGING_BUCKET}/${S3_KEY}" \
    --output json)

JOB_ID=$(echo "$DEPLOYMENT" | jq -r '.jobSummary.jobId')
log_success "Deployment initiated (Job ID: $JOB_ID)"

log_info "Monitoring deployment status..."
while true; do
    STATUS=$(aws amplify get-job \
        --app-id "$AMPLIFY_APP_ID" \
        --branch-name "$BRANCH_NAME" \
        --job-id "$JOB_ID" \
        --query 'job.summary.status' \
        --output text)
    
    echo "  Status: $STATUS"
    
    if [[ "$STATUS" == "SUCCEED" ]]; then
        log_success "Deployment completed successfully!"
        break
    elif [[ "$STATUS" == "FAILED" ]] || [[ "$STATUS" == "CANCELLED" ]]; then
        log_error "Deployment ${STATUS,,}"
        exit 1
    fi
    
    sleep 10
done

rm -f "$ZIP_FILE"
log_info "Cleaned up temporary files"

echo ""
log_info "S3 Package: s3://${STAGING_BUCKET}/${S3_KEY}"
log_info "Console: https://console.aws.amazon.com/amplify/apps"

APP_DOMAIN=$(aws amplify get-app --app-id "$AMPLIFY_APP_ID" --query 'app.defaultDomain' --output text 2>/dev/null || echo "")
if [[ -n "$APP_DOMAIN" ]]; then
    log_info "App URL: https://${BRANCH_NAME}.${APP_DOMAIN}"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Frontend Deployment Complete!        ${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
