# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Knowledge Base Gateway Tool Lambda

Searches Bedrock Knowledge Bases for SOPs and SAP API documentation, and loads a
focused SOP by process type (`load_sop`) when the exception is already classified
and semantic search would be the wrong instrument.
"""

import json
import logging
import os

import boto3
import config_overrides

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ssm = boto3.client("ssm")
bedrock_agent = boto3.client("bedrock-agent-runtime")
s3 = boto3.client("s3")

STACK_NAME = os.environ["STACK_NAME_BASE"]

# retrieve() defaults to 5 chunks. The SOPs KB is ingested with
# chunkingStrategy NONE (ADR-014), so one "chunk" is an entire SOP file —
# ~6-10K characters. Five of those is more SOP text than the injected prompt
# already carries, for a search that only needs to point at the right clause.
# The API-docs KB is chunked normally, so it keeps a wider window.
_MAX_RESULTS = {"search_sap_sops": 2, "search_sap_api_docs": 5}

_params = {}
_contacts = None
_sop_index = None


def _load_contacts() -> dict:
    """Load contact directory from CONTACTS_JSON env var."""
    global _contacts
    if _contacts is None:
        raw = json.loads(os.environ.get("CONTACTS_JSON", "{}"))
        _contacts = {f"CONTACT_{k.upper()}": v for k, v in raw.items()}
    return _contacts


def _load_sop_index() -> dict:
    """skill_id → {"constants": {...}, "sops": {process_type: s3_key}}.

    Rendered at synth time from the same skills/*/config.json the agent's
    skill_router reads, so the two cannot disagree about where a SOP lives.
    """
    global _sop_index
    if _sop_index is None:
        _sop_index = json.loads(os.environ.get("SOP_INDEX_JSON", "{}"))
    return _sop_index


def _get_bucket() -> str:
    return _get_param(f"/{STACK_NAME}/s3/sops-bucket")


def _get_param(param_name: str) -> str:
    if param_name not in _params:
        _params[param_name] = ssm.get_parameter(Name=param_name)["Parameter"]["Value"]
    return _params[param_name]


def _search_kb(kb_id: str, query: str, max_results: int) -> str:
    resp = bedrock_agent.retrieve(
        knowledgeBaseId=kb_id,
        retrievalQuery={"text": query},
        retrievalConfiguration={
            "vectorSearchConfiguration": {"numberOfResults": max_results}
        },
    )
    # The source URI travels with the chunk. Without it a quoted citation verifies
    # against retrieved text that names no document, so nobody can go read the rule.
    results = []
    for r in resp.get("retrievalResults", []):
        text = r.get("content", {}).get("text")
        if not text:
            continue
        uri = r.get("location", {}).get("s3Location", {}).get("uri")
        results.append(f"[{uri}]\n{text}" if uri else text)
    return "\n\n".join(results) if results else "No relevant results found."


def _sop_keys(key: str) -> list[str]:
    """Candidate object keys for one SOP.

    The extension fallback exists because a config.json may name a `.pdf` while
    the published corpus holds the `.txt` — the launcher only syncs
    `knowledge-base/sops/`. PDFs are unreachable from here (no parser in this
    bundle), so only text candidates are tried.
    ponytail: add PyPDF2 if a deployment ever publishes PDF SOPs.
    """
    stem = os.path.splitext(key)[0]
    return [k for k in (key, stem + ".txt", stem + ".md") if not k.endswith(".pdf")]


def _load_sop(process_type: str) -> dict:
    """Return the tool response for one focused SOP, resolved by process type."""
    index = _load_sop_index()
    skill_id, entry = next(
        ((s, e) for s, e in index.items() if process_type in (e.get("sops") or {})),
        (None, None),
    )
    if entry is None:
        known = sorted({pt for e in index.values() for pt in (e.get("sops") or {})})
        return {"error": f"Unknown process_type {process_type!r}. Known: {known}"}

    key = entry["sops"][process_type]
    constants = entry.get("constants") or {}

    bucket = _get_bucket()
    for candidate in _sop_keys(key):
        try:
            body = s3.get_object(Bucket=bucket, Key=candidate)["Body"].read()
        except s3.exceptions.NoSuchKey:
            continue
        text = config_overrides.substitute(
            body.decode("utf-8"), _load_contacts(), constants, skill_id
        )
        return {"content": [{"type": "text", "text": text}]}

    # Never answer "no SOP" with an empty success — that reads as permission to
    # improvise. A missing SOP is an error the agent must surface.
    return {"error": f"SOP for process_type {process_type!r} not found ({key})"}


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

        if tool_name == "load_sop":
            process_type = event.get("process_type", "")
            if not process_type:
                return {"error": "process_type is required"}
            return _load_sop(process_type)

        query = event.get("query", "")
        if not query:
            return {"error": "Query is required"}

        if tool_name == "search_sap_sops":
            kb_id = _get_param(f"/{STACK_NAME}/bedrock/sops-kb-id")
        elif tool_name == "search_sap_api_docs":
            kb_id = _get_param(f"/{STACK_NAME}/bedrock/api-docs-kb-id")
        else:
            return {"error": f"Unknown tool: {tool_name}"}

        result = _search_kb(kb_id, query, _MAX_RESULTS[tool_name])
        # A retrieved chunk carries no owning skill, so only contacts resolve;
        # a constant reaches the model verbatim and visibly unresolved.
        text = config_overrides.substitute(result, _load_contacts(), {})
        return {"content": [{"type": "text", "text": text}]}

    except PermissionError as e:
        logger.warning(f"Rejected unauthorized invocation: {e}")
        return {
            "error": "Unauthorized: calls must originate from the AgentCore Gateway"
        }
    except Exception as e:
        logger.error(f"Error: {e}")
        return {"error": f"Knowledge base lookup failed: {type(e).__name__}"}
