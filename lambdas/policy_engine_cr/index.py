# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# This is sample code. Not for use in production.
# See NOTICE and LICENSE for more information.
"""
Custom Resource Lambda for AgentCore Policy Engine management.

Creates a policy engine, adds Cedar policies, and associates it with a Gateway.
Uses the bedrock-agentcore API directly since no CFN resource exists yet.
"""

import json
import logging

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    """CloudFormation Custom Resource handler."""
    request_type = event["RequestType"]
    props = event["ResourceProperties"]

    region = props["Region"]
    client = boto3.client("bedrock-agentcore", region_name=region)

    try:
        if request_type == "Create":
            return on_create(client, props)
        elif request_type == "Update":
            return on_update(client, props, event.get("PhysicalResourceId", ""))
        elif request_type == "Delete":
            return on_delete(client, props, event.get("PhysicalResourceId", ""))
    except Exception as e:
        logger.warning(f"Error: {e}")
        raise


def on_create(client, props):
    engine_name = props["EngineName"]
    gateway_id = props["GatewayId"]
    policies = json.loads(props["Policies"])

    logger.info(f"Creating policy engine: {engine_name}")
    if not hasattr(client, "create_policy_engine"):
        logger.warning(
            "create_policy_engine not available in this SDK version, skipping"
        )
        return {
            "PhysicalResourceId": "NOT_AVAILABLE",
            "Data": {"PolicyEngineId": "NOT_AVAILABLE"},
        }
    engine_resp = client.create_policy_engine(name=engine_name)
    engine_id = engine_resp["policyEngineId"]
    logger.info(f"Created policy engine: {engine_id}")

    for policy in policies:
        logger.info(f"Creating policy: {policy['name']}")
        client.create_policy(
            policyEngineId=engine_id,
            name=policy["name"],
            policyType="CEDAR",
            definition={"cedar": {"statement": policy["statement"]}},
        )

    logger.info(f"Associating engine {engine_id} with gateway {gateway_id}")
    client.update_gateway(
        gatewayIdentifier=gateway_id,
        policyConfig={
            "policyEngineConfig": {
                "policyEngineId": engine_id,
                "enforcementMode": props.get("EnforcementMode", "LOG_ONLY"),
            }
        },
    )

    return {
        "PhysicalResourceId": engine_id,
        "Data": {"PolicyEngineId": engine_id},
    }


def on_update(client, props, engine_id):
    if engine_id == "NOT_AVAILABLE" or not engine_id:
        return on_create(client, props)

    if not hasattr(client, "create_policy"):
        logger.warning("create_policy not available in this SDK version, skipping")
        return {
            "PhysicalResourceId": engine_id,
            "Data": {"PolicyEngineId": engine_id},
        }

    policies = json.loads(props["Policies"])

    try:
        existing = client.list_policies(policyEngineId=engine_id)
        for p in existing.get("policies", []):
            client.delete_policy(policyEngineId=engine_id, policyId=p["policyId"])
    except Exception as e:
        logger.warning(f"Error cleaning old policies: {e}")

    for policy in policies:
        client.create_policy(
            policyEngineId=engine_id,
            name=policy["name"],
            policyType="CEDAR",
            definition={"cedar": {"statement": policy["statement"]}},
        )

    gateway_id = props["GatewayId"]
    client.update_gateway(
        gatewayIdentifier=gateway_id,
        policyConfig={
            "policyEngineConfig": {
                "policyEngineId": engine_id,
                "enforcementMode": props.get("EnforcementMode", "LOG_ONLY"),
            }
        },
    )

    return {
        "PhysicalResourceId": engine_id,
        "Data": {"PolicyEngineId": engine_id},
    }


def on_delete(client, props, engine_id):
    if not engine_id or engine_id == "NOT_AVAILABLE":
        return {"PhysicalResourceId": "NONE"}

    if not hasattr(client, "delete_policy"):
        logger.warning("delete_policy not available in this SDK version, skipping")
        return {"PhysicalResourceId": engine_id}

    # Disassociate from gateway first
    try:
        gateway_id = props["GatewayId"]
        client.update_gateway(
            gatewayIdentifier=gateway_id,
            policyConfig={},
        )
    except Exception as e:
        logger.warning(f"Error disassociating policy engine: {e}")

    try:
        existing = client.list_policies(policyEngineId=engine_id)
        for p in existing.get("policies", []):
            client.delete_policy(policyEngineId=engine_id, policyId=p["policyId"])
        client.delete_policy_engine(policyEngineId=engine_id)
    except Exception as e:
        logger.warning(f"Error deleting policy engine: {e}")

    return {"PhysicalResourceId": engine_id}
