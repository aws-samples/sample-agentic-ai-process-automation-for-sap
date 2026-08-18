# SPDX-License-Identifier: Apache-2.0

"""Contract tests for the demo ticket response path used by live finance AP cases."""

import ast
import importlib.util
import json
from pathlib import Path
from unittest import mock

from utils.content_filter import fence_data, sanitize_external_content

_ROOT = Path(__file__).resolve().parents[2]
_AGENT = _ROOT / "agentcore" / "agent" / "basic_agent.py"
_SKILL_DIR = _ROOT / "skills" / "finance_ap"
_DEMO_TICKETS = _ROOT / "lambdas" / "demo_tickets" / "index.py"


def _load_build_prompt():
    tree = ast.parse(_AGENT.read_text())
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_build_prompt"
    ]
    assert len(functions) == 1, "_build_prompt missing from basic_agent.py"
    namespace = {
        "fence_data": fence_data,
        "sanitize_external_content": sanitize_external_content,
    }
    exec(  # nosec B102 - trusted source (this repo's own basic_agent.py), test-only
        compile(ast.Module(body=functions, type_ignores=[]), str(_AGENT), "exec"),
        namespace,
    )
    return namespace["_build_prompt"]


_build_prompt = _load_build_prompt()


def _load_demo_tickets(monkeypatch):
    monkeypatch.setenv("TICKETS_TABLE_NAME", "tickets")
    monkeypatch.setenv("AGENT_QUEUE_URL", "https://sqs.test/queue.fifo")
    with mock.patch("boto3.resource"), mock.patch("boto3.client"):
        spec = importlib.util.spec_from_file_location(
            "demo_tickets_response_test", _DEMO_TICKETS
        )
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
    module.table = mock.MagicMock()
    module.sqs = mock.MagicMock()
    module.QUEUE_URL = "https://sqs.test/queue.fifo"
    return module


def _event(action: str, reviewer: str = "reviewer@example.com", **body):
    return {
        "body": json.dumps({"action": action, **body}),
        "headers": {},
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": "reviewer-subject",
                    "email": reviewer,
                    "cognito:username": "reviewer",
                }
            }
        },
    }


def test_live_finance_ap_skill_exposes_ticket_response_tools():
    config = json.loads((_SKILL_DIR / "config.json").read_text())

    assert {"demo_create_ticket", "demo_get_ticket"} <= set(config["gateway_tools"])


def test_live_finance_ap_prompt_defines_both_response_modes_with_exact_tool_names():
    # The ticket protocol lives in the shared platform preamble, so assert on the
    # assembled prompt — reading base_prompt.txt alone would no longer see it.
    from utils import skill_router as sr

    sr._skills_index = None
    prompt = sr.resolve_skill("quantity_variance")["system_prompt"]

    assert 'response_type "approval"' in prompt
    assert 'response_type "free_text"' in prompt
    assert "demo_create_ticket" in prompt
    assert "demo_get_ticket" in prompt


def test_manual_chat_prompt_wins_over_case_processing():
    # Interactive chat and the /cases/enqueue route share trigger="manual". A prompt
    # present means a human is talking to the agent, so it must win over the generic
    # SOP instruction even with a focused case_id in scope.
    prompt = _build_prompt(
        {
            "case_id": "5100001976#2026",
            "trigger": "manual",
            "prompt": "why did this fail?",
        }
    )
    assert prompt == "why did this fail?"


def test_manual_enqueue_without_a_prompt_falls_through_to_sop():
    # The invoker deliberately sends no prompt for an enqueued case; the same "manual"
    # trigger must then process the case per SOP, not echo an empty user message.
    prompt = _build_prompt({"case_id": "5100001976#2026", "trigger": "manual"})
    assert "Process case: 5100001976#2026" in prompt


def test_ticket_action_prompt_uses_the_registered_demo_get_tool():
    prompt = _build_prompt(
        {
            "case_id": "5100001976#2026",
            "trigger": "ticket-action",
            "payload": {
                "ticket_id": "TKT-1234",
                "ticket_decision": "approved",
            },
        }
    )

    assert "TKT-1234" in prompt
    assert "approved" in prompt
    assert "demo_get_ticket" in prompt
    assert "Call get_ticket" not in prompt


def test_free_text_ticket_action_is_fenced_and_preserved():
    prompt = _build_prompt(
        {
            "case_id": "5100001976#2026",
            "trigger": "ticket-action",
            "payload": {
                "ticket_id": "TKT-1234",
                "ticket_decision": "replied",
                "response_text": "Use PO 4500002664",
            },
        }
    )

    assert "Use PO 4500002664" in prompt
    assert '<external_data source="ticket-reply"' in prompt
    assert "demo_get_ticket" in prompt


def test_free_text_ticket_requires_a_nonempty_reply(monkeypatch):
    module = _load_demo_tickets(monkeypatch)
    module.table.get_item.return_value = {
        "Item": {
            "ticket_id": "TKT-1",
            "status": "open",
            "response_type": "free_text",
            "case_id": "5100001976#2026",
        }
    }

    response = module._action_ticket(
        "TKT-1", _event("replied", response_text="   "), ""
    )

    assert response["statusCode"] == 400
    module.table.update_item.assert_not_called()
    module.sqs.send_message.assert_not_called()


def test_ticket_action_must_match_the_requested_response_type(monkeypatch):
    module = _load_demo_tickets(monkeypatch)
    module.table.get_item.return_value = {
        "Item": {
            "ticket_id": "TKT-1",
            "status": "open",
            "response_type": "free_text",
            "case_id": "5100001976#2026",
        }
    }

    response = module._action_ticket("TKT-1", _event("approved"), "")

    assert response["statusCode"] == 400
    module.table.update_item.assert_not_called()
    module.sqs.send_message.assert_not_called()


def test_valid_free_text_action_requeues_the_case_with_the_exact_reply(monkeypatch):
    module = _load_demo_tickets(monkeypatch)
    existing = {
        "ticket_id": "TKT-1",
        "status": "open",
        "response_type": "free_text",
        "case_id": "5100001976#2026",
    }
    module.table.get_item.return_value = {"Item": existing}
    module.table.update_item.return_value = {
        "Attributes": {
            **existing,
            "status": "replied",
            "resolution": "Use PO 4500002664",
        }
    }

    response = module._action_ticket(
        "TKT-1",
        _event(
            "replied",
            resolution="Use PO 4500002664",
            comment="Use PO 4500002664",
            response_text="Use PO 4500002664",
        ),
        "",
    )

    assert response["statusCode"] == 200
    message = json.loads(module.sqs.send_message.call_args.kwargs["MessageBody"])
    # The stored ticket carries the legacy `doc#item` form; the resume message must
    # come out canonical so it groups with every other producer for this case.
    assert message == {
        "case_id": "5100001976-2026",
        "trigger": "ticket-action",
        "payload": {
            "source": "ticket-action",
            "ticket_id": "TKT-1",
            "ticket_decision": "replied",
            "resolution": "Use PO 4500002664",
            "response_text": "Use PO 4500002664",
        },
    }
    assert (
        module.sqs.send_message.call_args.kwargs["MessageGroupId"] == "5100001976-2026"
    )


def test_approval_ticket_accepts_yes_or_no_decisions(monkeypatch):
    module = _load_demo_tickets(monkeypatch)
    existing = {
        "ticket_id": "TKT-1",
        "status": "open",
        "response_type": "approval",
        "case_id": "5100001976#2026",
    }
    module.table.get_item.return_value = {"Item": existing}

    for action in ("approved", "denied"):
        module.table.update_item.return_value = {
            "Attributes": {**existing, "status": action}
        }
        response = module._action_ticket("TKT-1", _event(action), "")
        assert response["statusCode"] == 200
        message = json.loads(module.sqs.send_message.call_args.kwargs["MessageBody"])
        assert message["payload"]["ticket_decision"] == action
        assert "response_text" not in message["payload"]


def test_demo_ticket_api_rejects_an_unknown_response_type(monkeypatch):
    module = _load_demo_tickets(monkeypatch)

    response = module._create_ticket(
        {"body": json.dumps({"title": "Question", "response_type": "yes_no_or_maybe"})},
        "",
    )

    assert response["statusCode"] == 400
    module.table.put_item.assert_not_called()


def test_reply_without_inline_text_reads_the_durable_ticket_without_approval_advice():
    prompt = _build_prompt(
        {
            "case_id": "5100001976#2026",
            "trigger": "ticket-action",
            "payload": {
                "ticket_id": "TKT-1234",
                "ticket_decision": "replied",
            },
        }
    )

    assert "demo_get_ticket" in prompt
    assert "durable response" in prompt
    assert "If approved" not in prompt


def test_decided_ticket_rejects_a_conflicting_later_decision(monkeypatch):
    module = _load_demo_tickets(monkeypatch)
    module.table.get_item.return_value = {
        "Item": {
            "ticket_id": "TKT-1",
            "status": "approved",
            "response_type": "approval",
            "case_id": "5100001976#2026",
        }
    }

    response = module._action_ticket("TKT-1", _event("denied"), "")

    assert response["statusCode"] == 409
    module.table.update_item.assert_not_called()
    module.sqs.send_message.assert_not_called()


def test_reviewer_identity_supports_cognito_and_flat_oidc_shapes(monkeypatch):
    module = _load_demo_tickets(monkeypatch)

    assert (
        module._reviewer_identity(
            {
                "requestContext": {
                    "authorizer": {"claims": {"email": "cognito@example.com"}}
                }
            }
        )
        == "cognito@example.com"
    )
    assert (
        module._reviewer_identity(
            {
                "requestContext": {
                    "authorizer": {
                        "sub": "entra-subject",
                        "preferred_username": "entra@example.com",
                    }
                }
            }
        )
        == "entra@example.com"
    )


def test_ticket_action_persists_authenticated_reviewer(monkeypatch):
    module = _load_demo_tickets(monkeypatch)
    current = {
        "ticket_id": "TKT-1",
        "status": "open",
        "response_type": "approval",
        "case_id": "5100001976#2026",
    }
    module.table.get_item.return_value = {"Item": current}
    module.table.update_item.return_value = {
        "Attributes": {**current, "status": "approved"}
    }

    response = module._action_ticket(
        "TKT-1", _event("approved", reviewer="reviewer@example.com"), ""
    )

    assert response["statusCode"] == 200
    comment = module.table.update_item.call_args.kwargs["ExpressionAttributeValues"][
        ":comment"
    ][0]
    assert comment["author"] == "reviewer@example.com"


def test_ticket_action_requires_authenticated_reviewer(monkeypatch):
    module = _load_demo_tickets(monkeypatch)
    event = {"body": json.dumps({"action": "approved"}), "headers": {}}

    response = module._action_ticket("TKT-1", event, "")

    assert response["statusCode"] == 401
    module.table.get_item.assert_not_called()
    module.table.update_item.assert_not_called()
    module.sqs.send_message.assert_not_called()
