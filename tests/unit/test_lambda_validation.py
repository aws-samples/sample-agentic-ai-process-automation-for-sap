# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Integration tests: schema validation wired into the lambda handlers.

These assert that the handlers actually call the shared_types validator on their
read/write paths, that a valid record produces no warning, and that a bad record
is logged but never blocks the operation (validation is a safety net, not a gate).

The shared_types layer is put on sys.path so the handlers import the *real*
models + validator (as they do in the deployed Lambda), not the no-op fallback.
"""

import importlib
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent

# Real layer modules (generated_tickets, generated_cases, validate) must resolve.
sys.path.insert(0, str(_ROOT / "lambdas" / "layers" / "shared_types"))


@pytest.fixture
def ticket_mgmt(monkeypatch):
    """Import the gateway ticket-management handler with boto3 mocked."""
    monkeypatch.setenv("TICKETS_TABLE_SSM_PARAM", "/test/tickets")
    sys.path.insert(
        0, str(_ROOT / "agentcore" / "gateway" / "tools" / "demo_ticket_management")
    )
    with patch("boto3.resource"), patch("boto3.client"):
        import ticket_management_lambda as tm

        importlib.reload(tm)
    # Stub the table so put_item is a no-op we can inspect.
    tm._table = MagicMock()
    return tm


class TestTicketManagementWritePath:
    def test_uses_real_validator_not_fallback(self, ticket_mgmt):
        # If the layer failed to import, Ticket would be None (the fallback).
        assert ticket_mgmt.Ticket is not None
        assert ticket_mgmt.validate_or_log.__module__ == "validate"

    def test_valid_ticket_creates_without_warning(self, ticket_mgmt, caplog):
        with caplog.at_level(logging.WARNING):
            result = ticket_mgmt._create_ticket(
                {"title": "Approve me", "priority": "high", "case_id": ""}
            )
        # Gateway tools return an MCP content envelope, not the raw ticket.
        assert "content" in result
        ticket_mgmt._table.put_item.assert_called_once()
        # The item actually written is a schema-valid Ticket → no warning.
        written = ticket_mgmt._table.put_item.call_args.kwargs["Item"]
        assert written["ticket_id"].startswith("TKT-")
        assert not any("validation failed" in r.message for r in caplog.records)

    def test_write_still_happens_when_validation_fails(self, ticket_mgmt, caplog):
        # An incompatible model must still let the write happen — validation warns,
        # it never blocks.
        from pydantic import BaseModel

        class StricterTicket(BaseModel):
            model_config = {"extra": "forbid"}
            ticket_id: str
            nonexistent_required_field: str  # the built ticket lacks this

        with patch.object(ticket_mgmt, "Ticket", StricterTicket):
            with caplog.at_level(logging.WARNING):
                ticket_mgmt._create_ticket({"title": "x", "priority": "high"})

        ticket_mgmt._table.put_item.assert_called_once()  # write not blocked
        assert any("validation failed" in r.message for r in caplog.records)


@pytest.fixture
def poller_engine():
    sys.path.insert(0, str(_ROOT / "lambdas" / "odata_poller"))
    import polling_engine as pe

    importlib.reload(pe)
    return pe


class TestPollerValidation:
    def test_engine_imports_real_workitem(self, poller_engine):
        # In the test env the layer is on sys.path, so the poller should bind the
        # real WorkItem model and the shared validator (not the no-op fallback).
        assert poller_engine.WorkItem is not None
        assert poller_engine.validate_or_log.__module__ == "validate"

    def test_valid_case_item_no_warning(self, poller_engine, caplog):
        from decimal import Decimal

        case_item = {
            "document_number": "D1",
            "item_id": "1",
            "domain": "finance_ap",
            "process_type": "invoice_matching",
            "status": "detected",
            "created_at": "t",
            "updated_at": "t",
            "amount": Decimal("10.50"),  # DynamoDB-style number
            "agent_traces": [],
        }
        with caplog.at_level(logging.WARNING):
            poller_engine.validate_or_log(
                poller_engine.WorkItem, case_item, context="odata_poller"
            )
        assert not any("validation failed" in r.message for r in caplog.records)

    def test_drifted_case_item_logs(self, poller_engine, caplog):
        case_item = {
            "document_number": "D1",
            "item_id": "1",
            "domain": "finance_ap",
            "process_type": "invoice_matching",
            "status": "detected",
            "created_at": "t",
            "updated_at": "t",
            "rogue_field": "x",
        }
        with caplog.at_level(logging.WARNING):
            poller_engine.validate_or_log(
                poller_engine.WorkItem, case_item, context="odata_poller"
            )
        assert any("validation failed" in r.message for r in caplog.records)


@pytest.fixture
def cases_api(monkeypatch):
    monkeypatch.setenv("TABLE_NAME", "test-cases")
    sys.path.insert(0, str(_ROOT / "lambdas" / "cases_api"))
    with patch("boto3.resource"):
        import index as ca

        importlib.reload(ca)
    return ca


class TestCasesApiReadPath:
    def test_uses_real_validator(self, cases_api):
        assert cases_api.WorkItem is not None
        assert cases_api.validate_or_log.__module__ == "validate"

    def test_single_case_get_validates(self, cases_api, caplog):
        # Stub the table to return a valid WorkItem for the get_item read.
        cases_api.table = MagicMock()
        cases_api.table.get_item.return_value = {
            "Item": {
                "document_number": "5100001692",
                "item_id": "2026",
                "domain": "finance_ap",
                "process_type": "invoice_matching",
                "status": "detected",
                "created_at": "t",
                "updated_at": "t",
            }
        }
        event = {
            "httpMethod": "GET",
            "path": "/cases/5100001692/2026",
            "pathParameters": {"doc": "5100001692", "item": "2026"},
            "headers": {},
        }
        with caplog.at_level(logging.WARNING):
            resp = cases_api.handler(event, None)
        assert resp["statusCode"] == 200
        assert not any("validation failed" in r.message for r in caplog.records)
