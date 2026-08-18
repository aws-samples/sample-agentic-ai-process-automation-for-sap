#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Sets up SES domain identity with DKIM + MX for inbound email.
#
# Usage:
#   ./scripts/ops/setup-ses-domain.sh <domain>
#   ./scripts/ops/setup-ses-domain.sh example.com
#
# Prerequisites:
#   - AWS CLI configured with credentials
#   - Route 53 hosted zone for the domain
#   - config.yaml exists at cdk/config.yaml

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/../../cdk/config.yaml"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}ℹ${NC}  $1"; }
success() { echo -e "${GREEN}✓${NC}  $1"; }
warn()    { echo -e "${YELLOW}⚠${NC}  $1"; }
fail()    { echo -e "${RED}✗${NC}  $1"; exit 1; }

DOMAIN="${1:-}"
if [[ -z "$DOMAIN" ]]; then
  echo "Usage: $0 <domain>"
  echo "Example: $0 mail.example.com"
  echo ""
  echo "Prerequisites:"
  echo "  1. Register the domain and create a Route 53 hosted zone for it"
  echo "  2. Verify DNS is live: dig <domain> NS +short (should return 4 nameservers)"
  echo "  3. Have AWS CLI configured with credentials for the account hosting the domain"
  exit 1
fi

REGION=$(aws configure get region 2>/dev/null || echo "us-east-1")
info "Domain: $DOMAIN"
info "Region: $REGION"
echo ""

info "Checking Route 53 hosted zone for $DOMAIN..."
HOSTED_ZONE_ID=$(aws route53 list-hosted-zones-by-name \
  --dns-name "$DOMAIN" \
  --query "HostedZones[?Name=='${DOMAIN}.'].Id" \
  --output text 2>/dev/null | sed 's|/hostedzone/||')

if [[ -z "$HOSTED_ZONE_ID" ]]; then
  echo ""
  fail "No Route 53 hosted zone found for $DOMAIN.

  You need to register your domain first before running this script.

  Quick checklist:
    1. Register your domain with your DNS provider
    2. Configure NS records for your domain
    3. Wait 60 minutes for DNS propagation
    4. Verify with: dig $DOMAIN NS +short (should return 4 nameservers)
    5. Then re-run: $0 $DOMAIN"
fi
success "Hosted zone: $HOSTED_ZONE_ID"

info "Verifying DNS propagation..."
NS_COUNT=$(dig "$DOMAIN" NS +short 2>/dev/null | wc -l | tr -d ' ')
if [[ "$NS_COUNT" -lt 2 ]]; then
  warn "DNS may not be fully propagated yet (found $NS_COUNT nameservers, expected 4)."
  warn "If this was just registered, wait 60 minutes and try again."
  read -rp "  Continue anyway? (y/N): " cont
  if [[ "$cont" != "y" && "$cont" != "Y" ]]; then
    exit 0
  fi
else
  success "DNS propagated ($NS_COUNT nameservers found)"
fi

info "Creating SES domain identity..."
EXISTING=$(aws sesv2 get-email-identity --email-identity "$DOMAIN" --region "$REGION" \
  --query 'DkimAttributes.Status' --output text 2>/dev/null || echo "NONE")

if [[ "$EXISTING" == "SUCCESS" ]]; then
  success "Domain already verified in SES — skipping."
  TOKENS=$(aws sesv2 get-email-identity --email-identity "$DOMAIN" --region "$REGION" \
    --query 'DkimAttributes.Tokens' --output json)
else
  RESULT=$(aws sesv2 create-email-identity --email-identity "$DOMAIN" --region "$REGION" 2>&1 || true)
  if echo "$RESULT" | grep -q "AlreadyExistsException"; then
    info "Domain identity already exists, fetching tokens..."
  fi
  TOKENS=$(aws sesv2 get-email-identity --email-identity "$DOMAIN" --region "$REGION" \
    --query 'DkimAttributes.Tokens' --output json)
  success "SES domain identity created"
fi

TOKEN1=$(echo "$TOKENS" | python3 -c "import sys,json; print(json.load(sys.stdin)[0])")
TOKEN2=$(echo "$TOKENS" | python3 -c "import sys,json; print(json.load(sys.stdin)[1])")
TOKEN3=$(echo "$TOKENS" | python3 -c "import sys,json; print(json.load(sys.stdin)[2])")

info "Adding DKIM CNAME records + MX record to Route 53..."

CHANGE_BATCH=$(cat <<EOF
{
  "Changes": [
    {
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "${TOKEN1}._domainkey.${DOMAIN}",
        "Type": "CNAME",
        "TTL": 300,
        "ResourceRecords": [{"Value": "${TOKEN1}.dkim.amazonses.com"}]
      }
    },
    {
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "${TOKEN2}._domainkey.${DOMAIN}",
        "Type": "CNAME",
        "TTL": 300,
        "ResourceRecords": [{"Value": "${TOKEN2}.dkim.amazonses.com"}]
      }
    },
    {
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "${TOKEN3}._domainkey.${DOMAIN}",
        "Type": "CNAME",
        "TTL": 300,
        "ResourceRecords": [{"Value": "${TOKEN3}.dkim.amazonses.com"}]
      }
    },
    {
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "${DOMAIN}",
        "Type": "MX",
        "TTL": 300,
        "ResourceRecords": [{"Value": "10 inbound-smtp.${REGION}.amazonaws.com"}]
      }
    }
  ]
}
EOF
)

aws route53 change-resource-record-sets \
  --hosted-zone-id "$HOSTED_ZONE_ID" \
  --change-batch "$CHANGE_BATCH" > /dev/null

success "DNS records added (3 DKIM CNAMEs + 1 MX)"

info "Waiting for DKIM verification (usually 1-5 minutes)..."
for i in $(seq 1 30); do
  STATUS=$(aws sesv2 get-email-identity --email-identity "$DOMAIN" --region "$REGION" \
    --query 'DkimAttributes.Status' --output text 2>/dev/null)
  if [[ "$STATUS" == "SUCCESS" ]]; then
    success "DKIM verified!"
    break
  fi
  if [[ "$STATUS" == "FAILED" ]]; then
    fail "DKIM verification failed. Check DNS records."
  fi
  printf "  Attempt %d/30 — status: %s\r" "$i" "$STATUS"
  sleep 10  # nosemgrep: arbitrary-sleep — polling for DNS propagation
done

FINAL_STATUS=$(aws sesv2 get-email-identity --email-identity "$DOMAIN" --region "$REGION" \
  --query 'DkimAttributes.Status' --output text)
if [[ "$FINAL_STATUS" != "SUCCESS" ]]; then
  warn "DKIM still pending after 5 minutes. It may take longer for DNS to propagate."
  warn "Check status with: aws sesv2 get-email-identity --email-identity $DOMAIN --region $REGION --query 'DkimAttributes.Status'"
fi

info "Setting up SES receipt rule for inbound email..."

STACK_NAME=$(grep '^stack_name_base:' "$CONFIG_FILE" 2>/dev/null | head -1 | sed 's/.*stack_name_base:\s*//' | sed 's/#.*//' | xargs)
if [[ -z "$STACK_NAME" ]]; then
  fail "Could not read stack_name_base from $CONFIG_FILE"
fi
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
INBOUND_BUCKET="${STACK_NAME}-ses-inbound-${ACCOUNT_ID}"

aws ses create-receipt-rule-set --rule-set-name default-rule-set --region "$REGION" 2>/dev/null || true
aws ses set-active-receipt-rule-set --rule-set-name default-rule-set --region "$REGION" 2>/dev/null || true

aws ses delete-receipt-rule --rule-set-name default-rule-set --rule-name "${DOMAIN}-inbound" --region "$REGION" 2>/dev/null || true

aws ses create-receipt-rule --rule-set-name default-rule-set --region "$REGION" --rule "{
  \"Name\": \"${DOMAIN}-inbound\",
  \"Enabled\": true,
  \"Recipients\": [\"${DOMAIN}\"],
  \"Actions\": [
    {
      \"S3Action\": {
        \"BucketName\": \"${INBOUND_BUCKET}\",
        \"ObjectKeyPrefix\": \"inbound/\"
      }
    }
  ]
}" 2>/dev/null && success "Receipt rule created: ${DOMAIN} → s3://${INBOUND_BUCKET}/inbound/" \
  || warn "Receipt rule creation failed. The S3 bucket ${INBOUND_BUCKET} may not exist yet — deploy infrastructure first (cdk deploy --all), then re-run this script."

info "Updating config.yaml with $DOMAIN addresses..."

if [[ ! -f "$CONFIG_FILE" ]]; then
  warn "config.yaml not found at $CONFIG_FILE — skipping config update."
else
  # Only update the sender email — contacts are user-specific (may point to a
  # personal inbox) and must not be overwritten.
  sed -i.bak "s|ses_sender_email:.*|ses_sender_email: agent@${DOMAIN}|" "$CONFIG_FILE"

  rm -f "$CONFIG_FILE.bak"
  success "config.yaml updated (ses_sender_email → agent@${DOMAIN})"
  info "Contact addresses were NOT changed. Update them manually in config.yaml if needed."
fi

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  SES domain setup complete: ${DOMAIN}${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo "  Sender:  agent@${DOMAIN}"
echo "  Inbound: *@${DOMAIN} → SES → S3 → webhook processor"
echo ""
echo "  Next steps:"
echo "    1. Redeploy:  cd cdk && npx cdk deploy --all --require-approval never"
echo "    2. Sync SOPs: ./scripts/sync-knowledge-base.sh"
echo ""
echo "  Note: SES sandbox mode still applies. To send to external addresses,"
echo "  request production access at:"
echo "    https://${REGION}.console.aws.amazon.com/ses/home#/account"
echo ""
echo "  For sandbox testing, verify your personal email as a recipient:"
echo "    aws sesv2 create-email-identity --email-identity you@example.com --region ${REGION}"
echo "    (then click the verification link in your inbox)"
echo ""

read -rp "  Verify a personal email for sandbox testing? (enter email or skip): " PERSONAL_EMAIL
if [[ -n "$PERSONAL_EMAIL" && "$PERSONAL_EMAIL" != "skip" ]]; then
  aws sesv2 create-email-identity --email-identity "$PERSONAL_EMAIL" --region "$REGION" > /dev/null 2>&1 || true
  success "Verification email sent to $PERSONAL_EMAIL — click the link in your inbox."
  echo ""
  echo "  After verifying, test with:"
  echo "    aws sesv2 send-email --from-email-address agent@${DOMAIN} \\"
  echo "      --destination '{\"ToAddresses\":[\"${PERSONAL_EMAIL}\"]}' \\"
  echo "      --content '{\"Simple\":{\"Subject\":{\"Data\":\"SES Test\"},\"Body\":{\"Text\":{\"Data\":\"It works!\"}}}}' \\"
  echo "      --region ${REGION}"
fi
