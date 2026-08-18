# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# This is sample code. Not for use in production.
# See NOTICE and LICENSE for more information.
"""
Custom Resource Lambda for managing OAuth2 Credential Provider lifecycle.

This Lambda is invoked by CloudFormation during stack deployment to manage
an OAuth2 Credential Provider in Bedrock AgentCore Identity. It retrieves the Cognito
client secret from Secrets Manager at runtime to avoid logging sensitive data.

CloudFormation Events:
- Create: Creates OAuth2 provider with credentials from Secrets Manager
- Update: Updates OAuth2 provider properties (clientId, clientSecret, discovery config)
- Delete: Deletes OAuth2 provider by name
"""

import logging

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

bedrock_client = boto3.client("bedrock-agentcore-control")
secrets_client = boto3.client("secretsmanager")


def _get_secret_value(secret_arn: str) -> str:
    """Read the client secret.

    An AccessDenied here is worth reading literally before suspecting IAM: Secrets
    Manager returns it — not ResourceNotFoundException — for an identifier that
    resolves to nothing, to avoid telling an unauthorized caller a secret exists.
    A truncated ARN (missing the 6-char suffix) is the usual culprit, which
    assertSecretResolves in cdk/lib/utils/cfn-outputs-resolver.ts now catches at
    synth for the external-stack path."""
    return secrets_client.get_secret_value(SecretId=secret_arn)["SecretString"]


def handler(event: dict, context: dict) -> dict:
    """
    CloudFormation Custom Resource handler for OAuth2 Credential Provider.

    Args:
        event: CloudFormation event containing RequestType and ResourceProperties
        context: Lambda context object

    Returns:
        Response dict with PhysicalResourceId and optional Data attributes
    """
    request_type = event["RequestType"]
    props = event["ResourceProperties"]

    logger.info(f"Request type: {request_type}")
    logger.info(f"Provider name: {props['ProviderName']}")

    try:
        if request_type == "Create":
            return handle_create(props)
        elif request_type == "Delete":
            return handle_delete(event, props)
        elif request_type == "Update":
            return handle_update(event, props)
        else:
            raise ValueError(f"Unknown request type: {request_type}")

    except Exception as e:
        logger.warning(f"Error handling {request_type}: {str(e)}", exc_info=True)
        raise


def build_oauth_discovery(props: dict) -> dict:
    """
    Build the Oauth2Discovery union for the provider config.

    AWS's Oauth2Discovery requires EXACTLY ONE of:
    - authorizationServerMetadata (explicit endpoints), or
    - discoveryUrl (must point at a /.well-known/... document).

    When the props supply AuthorizationEndpoint + TokenEndpoint (SAP/XSUAA path),
    use authorizationServerMetadata. Otherwise fall back to the discoveryUrl
    (Cognito/Gateway path). Endpoints are safe to log; secrets are not.
    """
    authorization_endpoint = props.get("AuthorizationEndpoint")
    token_endpoint = props.get("TokenEndpoint")
    if authorization_endpoint and token_endpoint:
        logger.info(
            f"Using authorizationServerMetadata (auth={authorization_endpoint}, "
            f"token={token_endpoint})"
        )
        return {
            "authorizationServerMetadata": {
                "authorizationEndpoint": authorization_endpoint,
                "tokenEndpoint": token_endpoint,
                "issuer": props["Issuer"],
            }
        }

    discovery_url = props["DiscoveryUrl"]
    logger.info(f"Using discoveryUrl: {discovery_url}")
    return {"discoveryUrl": discovery_url}


def handle_create(props: dict) -> dict:
    """Create OAuth2 Credential Provider."""
    secret_arn = props["ClientSecretArn"]
    logger.info(f"Retrieving secret from: {secret_arn}")

    raw_secret = _get_secret_value(secret_arn)

    # Support two formats:
    #  - plain string  -> the client secret itself (Cognito client secret)
    #  - JSON {clientId, clientSecret} -> SAP OAuth provider credentials
    client_id = props.get("ClientId") or ""
    try:
        import json

        parsed = json.loads(raw_secret)
        client_secret = parsed.get("clientSecret", raw_secret)
        client_id = client_id or parsed.get("clientId", "")
    except (ValueError, TypeError):
        client_secret = raw_secret

    logger.info(f"Creating OAuth2 provider: {props['ProviderName']}")

    oauth_discovery = build_oauth_discovery(props)

    response = bedrock_client.create_oauth2_credential_provider(
        name=props["ProviderName"],
        credentialProviderVendor="CustomOauth2",
        oauth2ProviderConfigInput={
            "customOauth2ProviderConfig": {
                "clientId": client_id,
                "clientSecret": client_secret,
                "oauthDiscovery": oauth_discovery,
            }
        },
    )

    provider_arn = response["credentialProviderArn"]
    logger.info(f"Created provider with ARN: {provider_arn}")

    return {
        "PhysicalResourceId": props["ProviderName"],
        "Data": {"ProviderArn": provider_arn},
    }


def handle_update(event: dict, props: dict) -> dict:
    """Update OAuth2 Credential Provider."""
    provider_name = event["PhysicalResourceId"]
    logger.info(f"Updating OAuth2 provider: {provider_name}")

    secret_arn = props["ClientSecretArn"]
    logger.info(f"Retrieving secret from: {secret_arn}")

    raw_secret = _get_secret_value(secret_arn)

    # Support two formats:
    #  - plain string  -> the client secret itself (Cognito client secret)
    #  - JSON {clientId, clientSecret} -> SAP OAuth provider credentials
    client_id = props.get("ClientId") or ""
    try:
        import json

        parsed = json.loads(raw_secret)
        client_secret = parsed.get("clientSecret", raw_secret)
        client_id = client_id or parsed.get("clientId", "")
    except (ValueError, TypeError):
        client_secret = raw_secret

    oauth_discovery = build_oauth_discovery(props)

    response = bedrock_client.update_oauth2_credential_provider(
        name=provider_name,
        credentialProviderVendor="CustomOauth2",
        oauth2ProviderConfigInput={
            "customOauth2ProviderConfig": {
                "clientId": client_id,
                "clientSecret": client_secret,
                "oauthDiscovery": oauth_discovery,
            }
        },
    )

    provider_arn = response["credentialProviderArn"]
    logger.info(f"Updated provider with ARN: {provider_arn}")

    return {
        "PhysicalResourceId": provider_name,
        "Data": {"ProviderArn": provider_arn},
    }


def handle_delete(event: dict, props: dict) -> dict:
    """Delete OAuth2 Credential Provider."""
    provider_name = event["PhysicalResourceId"]
    logger.info(f"Deleting OAuth2 provider: {provider_name}")

    try:
        bedrock_client.delete_oauth2_credential_provider(name=provider_name)
        logger.info(f"Deleted provider: {provider_name}")
    except bedrock_client.exceptions.ResourceNotFoundException:
        logger.warning(f"Provider not found (already deleted): {provider_name}")
    except Exception as e:
        logger.error(f"Error deleting provider: {str(e)}")
        raise

    return {"PhysicalResourceId": provider_name}
