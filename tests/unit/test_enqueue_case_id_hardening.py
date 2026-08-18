# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""POST /cases/enqueue assembles an SQS message body as a JSON string literal by hand.

Every value interpolated into it must be incapable of closing that literal. Two
layers do this: a request model rejects a malformed ``case_id`` with a 400, and the
mapping template collapses both interpolated values to a safe charset so it holds
even if validation is bypassed or the regex engine behaves differently.

The patterns are read out of the CDK source so loosening either one fails here.
Python's ``re`` approximates API Gateway's Java engine; the patterns are simple
enough that they agree, except where noted.
"""

import re
from pathlib import Path

import pytest
from case_key import normalize_case_id

_STACK = Path(__file__).resolve().parents[2] / "cdk" / "lib" / "backend-stack.ts"
_SOURCE = _STACK.read_text()

# A double-quoted TS string literal, tolerating escaped quotes. Extracting these
# shape-agnostically matters: a regex that assumed the current shape would fail to
# match a loosened pattern and report "not found" instead of failing the assertion
# that actually cares.
_TS_STRING = r'"((?:[^"\\]|\\.)*)"'


def _unescape(literal: str) -> str:
    return literal.replace('\\"', '"').replace("\\\\", "\\")


def _extract(label: str, prefix: str) -> str:
    match = re.search(prefix + r"\s*" + _TS_STRING, _SOURCE)
    assert match, f"could not locate the {label} in backend-stack.ts — was it renamed?"
    return _unescape(match.group(1))


def _extract_after(label: str, marker: str, prefix: str) -> str:
    start = _SOURCE.find(marker)
    assert start != -1, f"could not locate {marker!r} in backend-stack.ts"
    match = re.search(prefix + r"\s*" + _TS_STRING, _SOURCE[start:])
    assert match, f"could not locate the {label} after {marker!r}"
    return _unescape(match.group(1))


CASE_ID_SCHEMA_PATTERN = _extract_after(
    "request-model case_id pattern", 'addModel("EnqueueCaseModel"', r"pattern:"
)
CASE_ID_STRIP_CLASS = _extract(
    "template case_id sanitizer", r"safeCaseId = \$body\.case_id\.replaceAll\("
)
USERNAME_STRIP_CLASS = _extract(
    "template username sanitizer", r"safeUsername = \$username\.replaceAll\("
)


def _strip(char_class: str, value: str, replacement: str = "") -> str:
    return re.sub(char_class, replacement, value)


# --------------------------------------------------------------- layer 1: the model


@pytest.mark.parametrize(
    "case_id",
    [
        "5100001922-2026",  # every one of the 250 rows in the deployed cases table
        "4500012345-00010",
        "AB_123x-item_1",  # other domains need not be numeric
    ],
)
def test_the_model_accepts_real_case_ids(case_id):
    assert re.match(CASE_ID_SCHEMA_PATTERN, case_id), f"{case_id!r} is a legitimate id"


def test_the_model_agrees_with_the_case_key_codec():
    """The API pattern must not drift from the codec that mints the ids.

    A looser API than the codec would admit an id no consumer can parse; a
    stricter one would 400 on ids the poller legitimately created.
    """
    for case_id in ("5100001922-2026", "4500012345-00010", "AB_123x-item_1"):
        assert normalize_case_id(case_id) == case_id
        assert re.match(CASE_ID_SCHEMA_PATTERN, case_id)

    for rejected in ("5100001922#2026", "5100001922/2026", "5100001922", "a-b-c"):
        assert not re.match(CASE_ID_SCHEMA_PATTERN, rejected), (
            f"{rejected!r} is not canonical and must not reach the template"
        )


@pytest.mark.parametrize(
    "payload,why",
    [
        (
            'X","payload":{"foo":1},"z":"',
            "quote breakout adding a key the invoker reads",
        ),
        ('X"', "bare quote"),
        ("X\\", "trailing backslash"),
        ("X\nY", "embedded newline"),
        ("X-Y-Z", "a second separator"),
        ("X#Y", "legacy separator — the UI now sends canonical only"),
        ("X Y-1", "whitespace"),
        ("{}-1", "braces"),
        ("noseparator", "no separator at all"),
        ("", "empty"),
        ("-1", "empty document part"),
        ("X-", "empty item part"),
    ],
)
def test_the_model_rejects_breakout_payloads(payload, why):
    assert not re.match(CASE_ID_SCHEMA_PATTERN, payload), f"should be rejected: {why}"


def test_the_schema_pattern_is_anchored():
    # JSON Schema `pattern` is a search, not a full match, so without anchors a valid
    # prefix would carry arbitrary trailing content.
    assert CASE_ID_SCHEMA_PATTERN.startswith("^")
    assert CASE_ID_SCHEMA_PATTERN.endswith("$")


# ------------------------------------------------------ layer 2: the mapping template


@pytest.mark.parametrize(
    "hostile",
    [
        'X","payload":{"foo":1},"z":"',
        'X"',
        "X\\",
        "X\nY",
        "5100001922-2026\n",  # Java's `$` matches before one trailing newline
        "{}",
    ],
)
def test_the_template_sanitizer_defangs_case_id_regardless_of_validation(hostile):
    safe = _strip(CASE_ID_STRIP_CLASS, hostile)

    for forbidden in ('"', "\\", "\n", "{", "}", " "):
        assert forbidden not in safe, (
            f"{forbidden!r} survived sanitizing of {hostile!r}"
        )


def test_the_template_sanitizer_preserves_a_real_case_id():
    assert _strip(CASE_ID_STRIP_CLASS, "5100001922-2026") == "5100001922-2026"


def test_the_template_groups_the_message_on_the_case_id_itself():
    """One case must be one FIFO group across every producer.

    The poller and the ticket-resume path both send `MessageGroupId=case_id`. This
    route used to rewrite the separator for its group id, which put a UI-triggered
    run in a *different* group from a background run for the same case — so FIFO
    serialized nothing and both could process concurrently.
    """
    integration = _SOURCE[_SOURCE.find("Action=SendMessage") :]
    group_id = re.search(r"MessageGroupId=\$util\.urlEncode\(\$(\w+)\)", integration)
    assert group_id, "could not locate the MessageGroupId in the SQS integration"
    assert group_id.group(1) == "safeCaseId", (
        "the FIFO group must be the sanitized case_id verbatim, with no separator "
        "rewriting — otherwise producers disagree about a case's group"
    )


@pytest.mark.parametrize(
    "claim",
    ['a","x":"b', 'o"brien@example.com', "back\\slash@example.com", "with\nnewline"],
)
def test_the_template_sanitizer_defangs_the_identity_claim(claim):
    # The claim is not covered by the request model, so this is its only control.
    safe = _strip(USERNAME_STRIP_CLASS, claim, "_")

    for forbidden in ('"', "\\", "\n"):
        assert forbidden not in safe, f"{forbidden!r} survived sanitizing of {claim!r}"


@pytest.mark.parametrize(
    "address",
    [
        "alice@example.com",
        "alice.smith+tag@example.com",
        "5b7f1e2c-0a3d-4f6b-8c9e-1a2b3c4d5e6f",
    ],
)
def test_the_template_sanitizer_preserves_ordinary_identities(address):
    # An email address and a UUID subject must survive intact, or audit attribution
    # silently degrades to a mangled value.
    assert _strip(USERNAME_STRIP_CLASS, address, "_") == address
