# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""`load_sop` on the knowledge-base Gateway tool Lambda.

STEP 2.2 of the entry-point SOP mandates following the focused SOP for the
classified exception type. This tool is the only path that loads one, so its
failure modes matter: an empty success would read to the agent as permission to
improvise, and a placeholder left unresolved would hand it a threshold of
`{{PRICE_VARIANCE_PCT}}` to compare against.
"""

import importlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent

_INDEX = {
    "finance_ap": {
        "sops": {
            "price_variance": "finance_ap/price_variance.txt",
            "po_style": "finance_ap/legacy.pdf",
        },
        "constants": {"PRICE_VARIANCE_PCT": 2},
    }
}


class _NoSuchKey(Exception):
    pass


def _ctx(tool_name="knowledge-base-target___load_sop"):
    ctx = MagicMock()
    ctx.client_context.custom = (
        {"bedrockAgentCoreToolName": tool_name} if tool_name else {}
    )
    return ctx


@pytest.fixture
def kb(monkeypatch):
    monkeypatch.setenv("STACK_NAME_BASE", "test-stack")
    monkeypatch.setenv("SOP_INDEX_JSON", json.dumps(_INDEX))
    monkeypatch.setenv("CONTACTS_JSON", json.dumps({"procurement": "buy@example.com"}))
    sys.path.insert(
        0, str(_ROOT / "agentcore" / "gateway" / "tools" / "knowledge_base")
    )
    with patch("boto3.client"):
        import knowledge_base_lambda as mod

        importlib.reload(mod)
    mod._params = {"/test-stack/s3/sops-bucket": "sop-bucket"}
    mod.s3 = MagicMock()
    mod.s3.exceptions.NoSuchKey = _NoSuchKey
    return mod


def _serve(kb, bodies: dict):
    """Answer get_object from a {key: text} map, NoSuchKey for anything else."""

    def get_object(Bucket, Key):
        if Key not in bodies:
            raise _NoSuchKey(Key)
        return {"Body": MagicMock(read=lambda: bodies[Key].encode("utf-8"))}

    kb.s3.get_object.side_effect = get_object


def test_returns_the_sop_with_constants_and_contacts_resolved(kb):
    _serve(
        kb,
        {
            "finance_ap/price_variance.txt": (
                "Above {{PRICE_VARIANCE_PCT}}% escalate to {{CONTACT_PROCUREMENT}}."
            )
        },
    )
    result = kb.handler({"process_type": "price_variance"}, _ctx())
    assert result["content"][0]["text"] == "Above 2% escalate to buy@example.com."


def test_unknown_symbols_stay_verbatim(kb):
    # A silently-blank threshold is worse than a visible placeholder: the agent
    # would compare against nothing and report the comparison as done.
    _serve(kb, {"finance_ap/price_variance.txt": "Cap {{NOT_IN_CONFIG}} applies."})
    result = kb.handler({"process_type": "price_variance"}, _ctx())
    assert "{{NOT_IN_CONFIG}}" in result["content"][0]["text"]


def test_pdf_keys_fall_back_to_the_published_text(kb):
    # config.json may name a .pdf while the launcher only publishes the .txt.
    # This bundle has no PDF parser, so the .pdf candidate must not be tried.
    _serve(kb, {"finance_ap/legacy.txt": "TEXT SOP"})
    result = kb.handler({"process_type": "po_style"}, _ctx())
    assert result["content"][0]["text"] == "TEXT SOP"
    assert not [
        c for c in kb.s3.get_object.call_args_list if c.kwargs["Key"].endswith(".pdf")
    ]


def test_a_missing_sop_is_an_error_not_an_empty_success(kb):
    _serve(kb, {})
    result = kb.handler({"process_type": "price_variance"}, _ctx())
    assert "not found" in result["error"]
    assert "content" not in result


def test_unknown_process_type_names_the_known_ones(kb):
    result = kb.handler({"process_type": "nonsense"}, _ctx())
    assert "price_variance" in result["error"]


def test_missing_process_type_is_rejected(kb):
    assert "required" in kb.handler({}, _ctx())["error"]


def test_direct_invocation_without_gateway_context_is_refused(kb):
    _serve(kb, {"finance_ap/price_variance.txt": "SOP"})
    result = kb.handler({"process_type": "price_variance"}, _ctx(tool_name=None))
    assert result["error"].startswith("Unauthorized")
    kb.s3.get_object.assert_not_called()


def test_search_still_routes_to_the_knowledge_base(kb):
    # load_sop is an added branch, not a replacement — the search path that the
    # focused SOPs still rely on must be untouched.
    kb.ssm.get_parameter.return_value = {"Parameter": {"Value": "KB123"}}
    kb.bedrock_agent.retrieve.return_value = {
        "retrievalResults": [{"content": {"text": "ask {{CONTACT_PROCUREMENT}}"}}]
    }
    result = kb.handler(
        {"query": "tolerance"}, _ctx("knowledge-base-target___search_sap_sops")
    )
    assert result["content"][0]["text"] == "ask buy@example.com"
    assert kb.bedrock_agent.retrieve.call_args.kwargs["knowledgeBaseId"] == "KB123"


def test_a_retrieved_chunk_carries_the_document_it_came_from(kb):
    # A verified quote is only auditable if the operator can find the document. The
    # URI travels with the chunk; nothing downstream reconstructs it.
    kb.ssm.get_parameter.return_value = {"Parameter": {"Value": "KB123"}}
    kb.bedrock_agent.retrieve.return_value = {
        "retrievalResults": [
            {
                "content": {"text": "The agent MUST escalate."},
                "location": {
                    "s3Location": {"uri": "s3://sops/finance_ap/price_variance.txt"}
                },
            },
            # Bedrock omits `location` for some data-source types; the text still counts.
            {"content": {"text": "Second chunk, unattributed."}},
        ]
    }
    text = kb.handler(
        {"query": "tolerance"}, _ctx("knowledge-base-target___search_sap_sops")
    )["content"][0]["text"]
    assert "[s3://sops/finance_ap/price_variance.txt]" in text
    assert "Second chunk, unattributed." in text


def test_sop_search_asks_for_fewer_chunks_than_the_api_docs_search(kb):
    """The SOPs KB is ingested unchunked, so a result is a whole SOP file.

    Leaving numberOfResults unset takes the API default of 5, which returns more
    SOP text than the injected prompt already carries — for a search whose job is
    to point at one clause.
    """
    kb.ssm.get_parameter.return_value = {"Parameter": {"Value": "KB123"}}
    kb.bedrock_agent.retrieve.return_value = {"retrievalResults": []}

    def asked_for(tool):
        kb.handler({"query": "tolerance"}, _ctx(f"knowledge-base-target___{tool}"))
        config = kb.bedrock_agent.retrieve.call_args.kwargs["retrievalConfiguration"]
        return config["vectorSearchConfiguration"]["numberOfResults"]

    sops = asked_for("search_sap_sops")
    assert 1 <= sops <= 2, "an unchunked SOP hit is a whole file — keep the cap tight"
    assert asked_for("search_sap_api_docs") > sops


def test_the_cdk_env_var_and_the_lambda_agree_on_the_index_shape():
    # The index is rendered at synth time; a rename on either side would leave
    # load_sop resolving every process_type to "unknown" with no error anywhere.
    stack = (_ROOT / "cdk" / "lib" / "backend-stack.ts").read_text(encoding="utf-8")
    assert "SOP_INDEX_JSON: JSON.stringify(this.sopIndex(config))" in stack
    assert "sops: skill.process_type_to_sop ?? {}" in stack
    assert "constants: skill.constants ?? {}" in stack


def test_cedar_permits_the_tool():
    # validate_domain_configs accepts any tool_spec.json name, so nothing else
    # catches a load_sop that the Gateway would deny at runtime.
    cedar = (_ROOT / "agentcore" / "policies" / "sap_agent_policies.cedar").read_text(
        encoding="utf-8"
    )
    assert 'AgentCore::Action::"knowledge-base-target___load_sop"' in cedar
