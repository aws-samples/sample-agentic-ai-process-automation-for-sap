#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Test OAuth2 authentication for Terraform-deployed infrastructure.

Verifies the OAuth2 Credential Provider by running client-credentials
machine-to-machine auth against Cognito, then calling the Gateway with the
resulting token. Run from the terraform/ root after `terraform apply`:

    python test-scripts/test-oauth2-auth.py
"""

import subprocess  # nosec B404
import sys

import boto3
import requests


def run_command(cmd):
    """Run shell command and return output."""
    import shlex

    args = shlex.split(cmd) if isinstance(cmd, str) else cmd
    result = subprocess.run(args, shell=False, capture_output=True, text=True)  # nosec B603  # nosemgrep: dangerous-subprocess-use-audit
    return result.stdout.strip(), result.returncode


def get_terraform_output(key):
    """Get Terraform output value."""
    output, code = run_command(["terraform", "output", "-raw", key])
    if code != 0:
        print(f"[FAIL] Failed to get Terraform output for '{key}'")
        sys.exit(1)
    return output


def get_secret(secret_name, region):
    """Get secret from AWS Secrets Manager."""
    client = boto3.client("secretsmanager", region_name=region)
    try:
        response = client.get_secret_value(SecretId=secret_name)
        return response["SecretString"]
    except Exception as e:
        print(f"[FAIL] Failed to get secret '{secret_name}': {e}")
        sys.exit(1)


def test_oauth2_authentication():
    """
    Test OAuth2 authentication flow.

    This is the main test function that orchestrates the full authentication test:
    1. Get configuration from Terraform outputs
    2. Fetch machine client secret from AWS Secrets Manager
    3. Request OAuth2 token from Cognito (client credentials flow)
    4. Test Gateway with the OAuth2 token (MCP tools/list request)
    """
    print("=" * 60)
    print("OAuth2 Authentication Integration Test")
    print("=" * 60)
    print()

    # === PHASE 1: Get Configuration from Terraform ===
    print("Getting configuration from Terraform...")
    stack_name = get_terraform_output("ssm_parameter_prefix").lstrip("/")
    region = "us-east-1"
    cognito_domain = get_terraform_output("cognito_domain_url")
    machine_client_id = get_terraform_output("cognito_machine_client_id")
    gateway_url = get_terraform_output("gateway_url")

    print(f"   Stack: {stack_name}")
    print(f"   Region: {region}")
    print(f"   Gateway URL: {gateway_url}")
    print()

    # === PHASE 2: Retrieve Machine Client Secret ===
    print("Fetching machine client secret from Secrets Manager...")
    secret_name = f"/{stack_name}/machine_client_secret"
    machine_client_secret = get_secret(secret_name, region)
    print(f"   Secret retrieved: {secret_name}")
    print()

    # === PHASE 3: OAuth2 Token Exchange with Cognito ===
    print("Step 1: Requesting OAuth2 token from Cognito...")
    token_url = f"https://{cognito_domain}/oauth2/token"

    token_response = requests.post(
        token_url,
        data={
            "grant_type": "client_credentials",
            "client_id": machine_client_id,
            "client_secret": machine_client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )

    if token_response.status_code != 200:
        print(f"[FAIL] Failed to get OAuth2 token: {token_response.status_code}")
        print(f"   Response: {token_response.text}")
        sys.exit(1)

    token_data = token_response.json()
    access_token = token_data.get("access_token")

    if not access_token:
        print("[FAIL] No access token in response")
        print(f"   Response: {token_data}")
        sys.exit(1)

    print("[PASS] OAuth2 token received successfully")
    print(f"   Token type: {token_data.get('token_type')}")
    print(f"   Expires in: {token_data.get('expires_in')} seconds")
    print()

    # === PHASE 4: Test Gateway Authentication ===
    print("Step 2: Testing Gateway with OAuth2 token...")

    mcp_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
    }

    gateway_response = requests.post(
        gateway_url,
        json=mcp_request,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )

    if gateway_response.status_code != 200:
        print(f"[FAIL] Gateway request failed: {gateway_response.status_code}")
        print(f"   Response: {gateway_response.text}")
        sys.exit(1)

    gateway_data = gateway_response.json()

    if "error" in gateway_data:
        print(f"[FAIL] Gateway returned error: {gateway_data['error']}")
        sys.exit(1)

    print("[PASS] Gateway authentication successful")
    print(f"   Available tools: {len(gateway_data.get('result', {}).get('tools', []))}")

    tools = gateway_data.get("result", {}).get("tools", [])
    if tools:
        print("   Tools:")
        for tool in tools:
            print(f"      - {tool.get('name')}: {tool.get('description', 'N/A')}")
    print()

    print("=" * 60)
    print("[PASS] OAuth2 Authentication Test PASSED")
    print("=" * 60)
    print()
    print("[x] OAuth2 token retrieved from Cognito")
    print("[x] Gateway authenticated successfully with token")
    print("[x] OAuth2 Credential Provider working correctly")
    print()


if __name__ == "__main__":
    try:
        test_oauth2_authentication()
    except KeyboardInterrupt:
        print("\n\n[FAIL] Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n[FAIL] Test failed with error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
