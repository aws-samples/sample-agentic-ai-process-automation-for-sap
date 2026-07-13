# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Shared shell helpers. Source it:  source "$SCRIPT_DIR/lib/common.sh"
# (from scripts/dev/* use  "$SCRIPT_DIR/../lib/common.sh")

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}ℹ${NC}  $1"; }
success() { echo -e "${GREEN}✓${NC}  $1"; }
warn()    { echo -e "${YELLOW}⚠${NC}  $1"; }
fail()    { echo -e "${RED}✗${NC}  $1"; exit 1; }

# read_config_key <config.yaml> <top-level-key>  → prints value (strips quotes/comments)
read_config_key() {
  grep "^${2}:" "$1" | head -1 | sed "s/.*${2}:[[:space:]]*//" | sed 's/#.*//' | xargs
}

# write_aws_exports <out> <region> <pool_id> <client_id> <runtime_arn> <feedback_url> <pattern> <redirect_uri> [demo_url] [ticketing]
# demo_url present → testDataEnabled; ticketing non-empty → ticketingEnabled.
write_aws_exports() {
  local out="$1" region="$2" pool="$3" client="$4" runtime="$5" feedback="$6" pattern="$7" redirect="$8" demo="${9:-}" ticketing="${10:-}"
  cat > "$out" <<EOF
{
  "authority": "https://cognito-idp.${region}.amazonaws.com/${pool}",
  "client_id": "${client}",
  "redirect_uri": "${redirect}",
  "post_logout_redirect_uri": "${redirect}",
  "response_type": "code",
  "scope": "email openid profile",
  "automaticSilentRenew": true,
  "agentRuntimeArn": "${runtime}",
  "awsRegion": "${region}",
  "apiUrl": "${feedback%/}",
  "feedbackApiUrl": "${feedback}",
  "agentPattern": "${pattern}",
  "ticketingEnabled": $(if [[ -n "$ticketing" ]]; then echo true; else echo false; fi),
  "testDataEnabled": $(if [[ -n "$demo" ]]; then echo true; else echo false; fi)$(if [[ -n "$demo" ]]; then echo ",
  \"demoApiUrl\": \"${demo%/}\""; fi)
}
EOF
}
