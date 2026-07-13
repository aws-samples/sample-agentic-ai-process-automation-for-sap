#!/bin/bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# =============================================================================
# Build and Push Docker Image to ECR for AgentCore Runtime
# =============================================================================
#
# Optional: `terraform apply` in docker mode already builds and pushes the
# image. Use this script only to build separately (e.g. in CI/CD) or to
# rebuild the image without a full terraform apply. Run with -h for options.
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

PATTERN="agent"
REGION=""
STACK_NAME=""
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TERRAFORM_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$TERRAFORM_DIR")"

usage() {
    echo "Usage: $0 [options]"
    echo ""
    echo "Options:"
    echo "  -p, --pattern    Agent pattern to build (default: agent)"
    echo "  -r, --region     AWS region (default: from terraform.tfvars or us-east-1)"
    echo "  -s, --stack      Stack name (default: from terraform.tfvars)"
    echo "  -h, --help       Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0                                    # Use defaults from terraform.tfvars"
    echo "  $0 -p agent          # Build the Strands agent"
    echo "  $0 -s my-stack -r us-west-2           # Custom stack and region"
}

while [[ $# -gt 0 ]]; do
    case $1 in
        -p|--pattern)
            PATTERN="$2"
            shift 2
            ;;
        -r|--region)
            REGION="$2"
            shift 2
            ;;
        -s|--stack)
            STACK_NAME="$2"
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

if [[ -z "$STACK_NAME" || -z "$REGION" ]]; then
    TFVARS_FILE="$TERRAFORM_DIR/terraform.tfvars"
    if [[ -f "$TFVARS_FILE" ]]; then
        echo -e "${BLUE}Reading configuration from terraform.tfvars...${NC}"
        
        if [[ -z "$STACK_NAME" ]]; then
            STACK_NAME=$(grep -E '^stack_name_base\s*=' "$TFVARS_FILE" | awk -F'"' '{print $2}')
        fi
        
        # Region is resolved from AWS_REGION env var or AWS CLI profile (not in tfvars)
    fi
fi

# Check deployment type - this script is for docker mode only
TFVARS_FILE="$TERRAFORM_DIR/terraform.tfvars"
if [[ -f "$TFVARS_FILE" ]]; then
    DEPLOYMENT_TYPE=$(grep -E '^backend_deployment_type\s*=' "$TFVARS_FILE" | awk -F'"' '{print $2}')
    if [[ "$DEPLOYMENT_TYPE" == "zip" ]]; then
        echo -e "${YELLOW}===========================================${NC}"
        echo -e "${YELLOW}  backend_deployment_type is set to 'zip' ${NC}"
        echo -e "${YELLOW}===========================================${NC}"
        echo ""
        echo -e "This script is only needed for ${GREEN}docker${NC} deployment mode."
        echo -e "With ${GREEN}zip${NC} mode, agent code is packaged automatically during ${BLUE}terraform apply${NC}."
        echo ""
        exit 0
    fi
fi

# Resolve region: CLI flag > AWS_REGION env > AWS_DEFAULT_REGION env > AWS CLI config
if [[ -z "$REGION" ]]; then
    REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-$(aws configure get region 2>/dev/null || echo "")}}"
fi

if [[ -z "$STACK_NAME" ]]; then
    echo -e "${RED}Error: Stack name not found. Please specify with -s or set in terraform.tfvars${NC}"
    exit 1
fi

if [[ -z "$REGION" ]]; then
    echo -e "${RED}Error: AWS region not found. Set AWS_REGION environment variable or configure via 'aws configure'.${NC}"
    exit 1
fi

AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null)
if [[ -z "$AWS_ACCOUNT_ID" ]]; then
    echo -e "${RED}Error: Could not get AWS account ID. Check your AWS credentials.${NC}"
    exit 1
fi

ECR_REPO="${AWS_ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${STACK_NAME}-agent-runtime"
DOCKERFILE="${PATTERN}/Dockerfile"

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Docker Image Build & Push for ECR    ${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "  Stack Name:    ${GREEN}${STACK_NAME}${NC}"
echo -e "  AWS Account:   ${GREEN}${AWS_ACCOUNT_ID}${NC}"
echo -e "  Region:        ${GREEN}${REGION}${NC}"
echo -e "  Pattern:       ${GREEN}${PATTERN}${NC}"
echo -e "  ECR Repo:      ${GREEN}${ECR_REPO}${NC}"
echo ""

if [[ ! -f "$PROJECT_ROOT/$DOCKERFILE" ]]; then
    echo -e "${RED}Error: Dockerfile not found at $PROJECT_ROOT/$DOCKERFILE${NC}"
    echo -e "${YELLOW}Available patterns:${NC}"
    ls -1 "$PROJECT_ROOT/agent/" 2>/dev/null || echo "  No agent directory found"
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    echo -e "${RED}Error: Docker is not running. Please start Docker Desktop.${NC}"
    exit 1
fi

echo -e "${BLUE}Step 1/3: Logging into ECR...${NC}"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
if [[ $? -ne 0 ]]; then
    echo -e "${RED}Error: ECR login failed${NC}"
    exit 1
fi
echo -e "${GREEN}✓ ECR login successful${NC}"
echo ""

# ARM64 is required by AgentCore Runtime
echo -e "${BLUE}Step 2/3: Building Docker image (ARM64 architecture)...${NC}"
cd "$PROJECT_ROOT"
docker build \
    --platform linux/arm64 \
    -f "$DOCKERFILE" \
    -t "${ECR_REPO}:latest" \
    .

if [[ $? -ne 0 ]]; then
    echo -e "${RED}Error: Docker build failed${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Docker build successful${NC}"
echo ""

echo -e "${BLUE}Step 3/3: Pushing image to ECR...${NC}"
docker push "${ECR_REPO}:latest"

if [[ $? -ne 0 ]]; then
    echo -e "${RED}Error: Docker push failed${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Docker push successful${NC}"
echo ""

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Image successfully pushed to ECR!    ${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "Image URI: ${BLUE}${ECR_REPO}:latest${NC}"
echo ""
echo -e "${YELLOW}Next step:${NC} Run 'terraform apply' again to create the AgentCore Runtime"
echo ""
