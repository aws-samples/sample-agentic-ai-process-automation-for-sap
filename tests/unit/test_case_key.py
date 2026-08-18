# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Contract tests for the canonical case identity codec.

These pin the two properties every layer depends on — that a canonical id needs
no escaping anywhere it travels, and that a single ``-`` split is lossless — plus
the legacy-form tolerance that lets already-stored records keep resolving.

Run with: pytest tests/unit/test_case_key.py -v
"""

import re
import sys
import urllib.parse
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "lambdas" / "layers" / "shared_types"))

from case_key import (  # noqa: E402
    CASE_ID_PATTERN,
    RUNTIME_SESSION_MIN_LENGTH,
    CaseKeyError,
    format_case_id,
    normalize_case_id,
    parse_case_id,
    to_case_key,
    to_runtime_session_id,
    try_normalize_case_id,
)

# The real AP shape: document_number=SupplierInvoice, item_id=FiscalYear.
REAL_CASE_ID = "5100001976-2026"


def test_format_round_trips_through_parse():
    assert format_case_id("5100001976", "2026") == REAL_CASE_ID
    assert parse_case_id(REAL_CASE_ID) == ("5100001976", "2026")


def test_format_preserves_leading_zeros_in_item_ids():
    """item_id is a string key ("0001" fallback, "00010" accrual line items)."""
    assert format_case_id("4500012345", "00010") == "4500012345-00010"
    assert parse_case_id("4500012345-00010") == ("4500012345", "00010")


def test_format_trims_surrounding_whitespace():
    assert format_case_id(" 5100001976 ", " 2026 ") == REAL_CASE_ID


@pytest.mark.parametrize(
    "doc,item",
    [
        ("", "2026"),
        ("5100001976", ""),
        (None, "2026"),
        ("5100001976", None),
    ],
)
def test_format_rejects_missing_segments(doc, item):
    with pytest.raises(CaseKeyError):
        format_case_id(doc, item)


@pytest.mark.parametrize(
    "doc,item,why",
    [
        ("5100-001976", "2026", "a separator inside a segment would not parse back"),
        ("5100001976", "20#26", "legacy separator inside a segment"),
        ("5100001976", "20/26", "path separator inside a segment"),
        ("510000 1976", "2026", "whitespace inside a segment"),
        ("5100001976", "../etc", "traversal characters"),
    ],
)
def test_format_refuses_to_mint_an_unparseable_id(doc, item, why):
    with pytest.raises(CaseKeyError):
        format_case_id(doc, item)


@pytest.mark.parametrize(
    "legacy",
    [
        "5100001976#2026",  # original SQS/ticket wire form
        "5100001976/2026",  # observability trace form
        "5100001976-2026",  # already canonical
        "  5100001976#2026  ",
    ],
)
def test_every_historical_form_normalizes_to_canonical(legacy):
    assert normalize_case_id(legacy) == REAL_CASE_ID


def test_legacy_forms_are_unambiguous_because_segments_cannot_hold_a_separator():
    """The old code guessed the separator; here both forms yield one answer."""
    assert parse_case_id("5100001976#2026") == parse_case_id("5100001976-2026")


@pytest.mark.parametrize(
    "bad,why",
    [
        ("", "empty"),
        ("   ", "blank"),
        (None, "absent"),
        ("5100001976", "single segment is not a case identity"),
        ("5100001976-2026-1", "three segments are ambiguous"),
        ("5100001976#2026#1", "three legacy segments are ambiguous"),
        ("5100001976-2026 OR 1=1", "injection payload"),
        ("../../5100001976-2026", "traversal prefix"),
    ],
)
def test_normalize_rejects_malformed_identities(bad, why):
    with pytest.raises(CaseKeyError):
        normalize_case_id(bad)


def test_try_normalize_returns_none_instead_of_raising():
    assert try_normalize_case_id("5100001976#2026") == REAL_CASE_ID
    assert try_normalize_case_id("not a case") is None
    assert try_normalize_case_id(None) is None


def test_to_case_key_builds_the_dynamodb_key():
    """`case_id` is the cases table's sole partition key, in either input form."""
    assert to_case_key("5100001976#2026") == {"case_id": REAL_CASE_ID}
    assert to_case_key(REAL_CASE_ID) == {"case_id": REAL_CASE_ID}
    with pytest.raises(CaseKeyError):
        to_case_key("not a case")


# ---------------------------------------------------------------------------
# The properties that motivated the format
# ---------------------------------------------------------------------------


def test_a_canonical_id_needs_no_url_encoding():
    """The `%23` hand-encoding in the old frontend link had no reason to exist."""
    assert urllib.parse.quote(REAL_CASE_ID, safe="") == REAL_CASE_ID


def test_a_canonical_id_survives_the_memory_actor_charset_filter():
    """AgentCore Memory ids allow only [a-zA-Z0-9-_/:] — `#` was collapsed to `_`."""
    assert not re.search(r"[^a-zA-Z0-9\-_/:]", REAL_CASE_ID)


def test_a_canonical_id_is_a_legal_sqs_message_group_id():
    """Producers can group on case_id directly, so one case is one FIFO group."""
    assert re.fullmatch(r"[A-Za-z0-9\-_]{1,128}", REAL_CASE_ID)


def test_the_exported_pattern_is_anchored_and_matches_real_ids():
    assert CASE_ID_PATTERN.startswith("^") and CASE_ID_PATTERN.endswith("$")
    assert re.match(CASE_ID_PATTERN, REAL_CASE_ID)
    assert not re.match(CASE_ID_PATTERN, "5100001976#2026")


# ---------------------------------------------------------------------------
# Session ids
# ---------------------------------------------------------------------------


def test_session_id_is_deterministic_for_a_case():
    assert to_runtime_session_id(REAL_CASE_ID) == to_runtime_session_id(
        "5100001976#2026"
    )


def test_session_id_clears_the_agentcore_runtime_minimum_length():
    """A bare `case-5100001976-2026` is 20 chars and the Runtime rejects it."""
    session_id = to_runtime_session_id(REAL_CASE_ID)
    assert len(session_id) >= RUNTIME_SESSION_MIN_LENGTH
    assert REAL_CASE_ID in session_id
    assert not re.search(r"[^a-zA-Z0-9\-_/:]", session_id)


def test_session_id_does_not_pad_an_already_long_case_id():
    long_id = to_runtime_session_id("510000197600000000-2026000000000")
    assert len(long_id) > RUNTIME_SESSION_MIN_LENGTH
    assert not long_id.endswith("0-0")


def test_session_ids_are_distinct_across_cases():
    assert to_runtime_session_id("5100001976-2026") != to_runtime_session_id(
        "5100001976-2027"
    )


def test_session_id_rejects_a_malformed_case_id():
    with pytest.raises(CaseKeyError):
        to_runtime_session_id("not a case")
