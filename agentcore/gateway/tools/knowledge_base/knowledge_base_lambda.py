# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Knowledge Base Gateway Tool Lambda

Searches Bedrock Knowledge Bases for SOPs and SAP API documentation.
"""

import json
import logging
import os
import re

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ssm = boto3.client("ssm")
bedrock_agent = boto3.client("bedrock-agent-runtime")

STACK_NAME = os.environ["STACK_NAME_BASE"]

_kb_ids = {}
_contacts = None


def _load_contacts() -> dict:
    """Load contact directory from CONTACTS_JSON env var."""
    global _contacts
    if _contacts is None:
        raw = json.loads(os.environ.get("CONTACTS_JSON", "{}"))
        _contacts = {f"CONTACT_{k.upper()}": v for k, v in raw.items()}
    return _contacts


def _substitute_contacts(text: str) -> str:
    contacts = _load_contacts()
    return re.sub(
        r"\{\{(CONTACT_[A-Z_]+)\}\}",
        lambda m: contacts.get(m.group(1), m.group(0)),
        text,
    )


def _get_kb_id(param_name: str) -> str:
    if param_name not in _kb_ids:
        _kb_ids[param_name] = ssm.get_parameter(Name=param_name)["Parameter"]["Value"]
    return _kb_ids[param_name]


def _search_kb(kb_id: str, query: str) -> str:
    resp = bedrock_agent.retrieve(knowledgeBaseId=kb_id, retrievalQuery={"text": query})
    results = [
        r.get("content", {}).get("text", "")
        for r in resp.get("retrievalResults", [])
        if r.get("content", {}).get("text")
    ]
    return "\n\n".join(results) if results else "No relevant results found."


def _resolve_tool_name(context) -> str:
    """Return the bare tool name, asserting the call came through the Gateway.

    The AgentCore Gateway sets ``bedrockAgentCoreToolName`` in the Lambda client
    context after evaluating Cedar authorization. A direct invocation that
    bypasses the Gateway won't carry this marker, so we reject it rather than
    executing unauthorized.
    """
    delimiter = "___"
    try:
        original = context.client_context.custom["bedrockAgentCoreToolName"]
    except (AttributeError, KeyError, TypeError):
        raise PermissionError(
            "Missing Gateway tool context — direct invocation is not permitted"
        )
    if delimiter not in original:
        raise PermissionError(f"Unexpected tool context format: {original!r}")
    return original[original.index(delimiter) + len(delimiter) :]


def handler(event, context):
    logger.info(f"Received event: {json.dumps(event)}")

    try:
        tool_name = _resolve_tool_name(context)

        query = event.get("query", "")
        if not query:
            return {"error": "Query is required"}

        if tool_name == "search_sap_sops":
            kb_id = _get_kb_id(f"/{STACK_NAME}/bedrock/sops-kb-id")
        elif tool_name == "search_sap_api_docs":
            kb_id = _get_kb_id(f"/{STACK_NAME}/bedrock/api-docs-kb-id")
        else:
            return {"error": f"Unknown tool: {tool_name}"}

        result = _search_kb(kb_id, query)
        return {"content": [{"type": "text", "text": _substitute_contacts(result)}]}

    except PermissionError as e:
        logger.warning(f"Rejected unauthorized invocation: {e}")
        return {
            "error": "Unauthorized: calls must originate from the AgentCore Gateway"
        }
    except Exception as e:
        logger.error(f"Error: {e}")
        return {"error": f"Knowledge base search failed: {type(e).__name__}"}
