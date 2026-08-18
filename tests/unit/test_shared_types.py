# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the shared_types Lambda layer.

Covers the generated pydantic models (WorkItem, Ticket) and the graceful
`validate_or_log` helper that lambdas call on read/write paths.

Run with: pytest tests/unit/test_shared_types.py -v
"""

import logging
import os
import sys
from decimal import Decimal

import pytest

# Make the shared_types layer importable without installing it as a package.
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__), "..", "..", "lambdas", "layers", "shared_types"
    ),
)

from generated_cases import CaseStatus, Domain, WorkItem  # noqa: E402
from generated_tickets import ResponseType, Ticket, TicketStatus  # noqa: E402
from validate import validate_or_log  # noqa: E402

VALID_WORKITEM = {
    "case_id": "5100001692-2026",
    "document_number": "5100001692",
    "item_id": "2026",
    "domain": "finance_ap",
    "process_type": "invoice_matching",
    "status": "detected",
    "created_at": "2026-06-30T00:00:00Z",
    "updated_at": "2026-06-30T00:00:00Z",
}

VALID_TICKET = {
    "ticket_id": "TKT-A1B2C3D4",
    "title": "Approval needed",
    "description": "Please approve invoice 5100001692",
    "status": "open",
    "priority": "high",
    "created_at": "2026-06-30T00:00:00Z",
    "updated_at": "2026-06-30T00:00:00Z",
}


class TestWorkItemModel:
    def test_valid_minimal(self):
        wi = WorkItem.model_validate(VALID_WORKITEM)
        assert wi.status is CaseStatus.detected
        assert wi.domain is Domain.finance_ap

    def test_missing_required_field_raises(self):
        bad = {k: v for k, v in VALID_WORKITEM.items() if k != "status"}
        with pytest.raises(Exception):
            WorkItem.model_validate(bad)

    def test_unknown_field_rejected(self):
        # extra="forbid" surfaces poller/config drift.
        with pytest.raises(Exception):
            WorkItem.model_validate({**VALID_WORKITEM, "surprise_column": "x"})

    def test_invalid_enum_value_raises(self):
        with pytest.raises(Exception):
            WorkItem.model_validate({**VALID_WORKITEM, "status": "not_a_status"})

    def test_decimal_amount_accepted(self):
        # DynamoDB hands back Decimal for numbers; the model must accept it.
        wi = WorkItem.model_validate({**VALID_WORKITEM, "amount": Decimal("1234.56")})
        assert float(wi.amount) == pytest.approx(1234.56)

    def test_optional_fields_default_none(self):
        wi = WorkItem.model_validate(VALID_WORKITEM)
        assert wi.amount is None
        assert wi.agent_traces is None


class TestTicketModel:
    def test_valid_minimal(self):
        t = Ticket.model_validate(VALID_TICKET)
        assert t.status is TicketStatus.open
        # The schema default is emitted as a bare string (datamodel-codegen does
        # not coerce defaults through the enum), so it reads back as "approval".
        assert t.response_type == "approval"

    def test_explicit_response_type_coerces_to_enum(self):
        t = Ticket.model_validate({**VALID_TICKET, "response_type": "free_text"})
        assert t.response_type is ResponseType.free_text

    def test_missing_required_field_raises(self):
        bad = {k: v for k, v in VALID_TICKET.items() if k != "description"}
        with pytest.raises(Exception):
            Ticket.model_validate(bad)

    def test_unknown_field_rejected(self):
        with pytest.raises(Exception):
            Ticket.model_validate({**VALID_TICKET, "extra": 1})


class TestValidateOrLog:
    def test_returns_data_unchanged_on_success(self):
        data = dict(VALID_WORKITEM)
        result = validate_or_log(WorkItem, data)
        assert result is data  # same object, not a re-serialized copy

    def test_preserves_decimal(self):
        # The helper must never mutate/coerce — Decimal survives for DynamoDB.
        data = {**VALID_WORKITEM, "amount": Decimal("99.99")}
        result = validate_or_log(WorkItem, data)
        assert isinstance(result["amount"], Decimal)

    def test_none_model_is_noop(self):
        # Simulates the layer/pydantic being absent (local dev/test fallback).
        data = {"anything": 1}
        assert validate_or_log(None, data) is data

    def test_invalid_data_logs_not_raises(self, caplog):
        data = {**VALID_WORKITEM, "bogus_field": "x"}
        with caplog.at_level(logging.WARNING):
            result = validate_or_log(WorkItem, data, context="unit-test")
        assert result is data  # returned unchanged despite failure
        assert any("validation failed" in r.message for r in caplog.records)
        assert any("unit-test" in r.getMessage() for r in caplog.records)

    def test_missing_required_logs_not_raises(self, caplog):
        bad = {k: v for k, v in VALID_WORKITEM.items() if k != "status"}
        with caplog.at_level(logging.WARNING):
            result = validate_or_log(WorkItem, bad)
        assert result is bad
        assert any("validation failed" in r.message for r in caplog.records)

    def test_valid_data_does_not_log(self, caplog):
        with caplog.at_level(logging.WARNING):
            validate_or_log(Ticket, dict(VALID_TICKET))
        assert not any("validation failed" in r.message for r in caplog.records)
