# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Canonical codec for case identity — the one place `case_id` is built or read.

A case is keyed in DynamoDB by ``case_id``, its sole partition key, and identified
the same way everywhere else: SQS message bodies and `MessageGroupId`, ticket
correlation, agent prompts, URLs, trace records, and AgentCore session ids.
Historically each layer invented its own (`doc#item`, `doc-item`, `doc/item`,
`doc%23item`) and re-parsed it inline, which made the id illegal in half the systems
it travelled through.

The canonical form is::

    {document_number}-{item_id}        e.g. 5100001976-2026

Two properties make that work everywhere, and both depend on the *segments*
being restricted to ``[A-Za-z0-9_]``:

  * **Unambiguous.** Because a segment can never contain the separator, a single
    ``-`` split is lossless. The old scheme allowed ``-`` inside the id *and* as a
    separator, so `doc-item` was not reliably parseable.
  * **Escaping-free.** The id is already safe in a URL path or query string, in
    an SQS ``MessageGroupId``, in an AgentCore Memory ``actor_id``/``session_id``
    charset, and inside a JSON string literal — so no layer needs to re-encode it.

Legacy separators (``#`` from the original wire format, ``/`` from trace records)
are still accepted on *read* via :func:`normalize_case_id`; only ``-`` is ever
emitted. Tolerating them is safe for exactly the same reason the format is
unambiguous: a segment cannot contain any separator.

Supported SAP domains resolve both segments from alphanumeric SAP keys (see
``lambdas/odata_poller/domains/*.json`` — ``SupplierInvoice`` and ``FiscalYear``),
so :func:`format_case_id` raises rather than silently minting an id it cannot
parse back.

Mirrored, by necessity, in three places — keep them in lockstep:

  * ``lambdas/layers/shared_types/case_key.py`` — canonical; ships in the layer.
  * ``agentcore/agent/utils/case_key.py`` — byte-identical mirror. The agent runs
    in a container that copies only ``agentcore/`` + ``skills/``, so it cannot
    import the layer. ``tests/unit/test_case_key_drift.py`` fails if they diverge.
  * ``frontend/src/lib/caseKey.ts`` — TypeScript twin for the UI.
"""

import re

#: The one separator between the two key segments.
SEPARATOR = "-"

#: Separators accepted on read from older records and trace payloads.
LEGACY_SEPARATORS = ("#", "/")

#: Character class a single key segment is allowed to use.
SEGMENT_CHARS = "A-Za-z0-9_"

#: Anchored pattern for a whole canonical case_id. Exported so the API Gateway
#: request model and its tests validate against this definition, not a copy.
CASE_ID_PATTERN = f"^[{SEGMENT_CHARS}]+{SEPARATOR}[{SEGMENT_CHARS}]+$"

_SEGMENT_RE = re.compile(f"^[{SEGMENT_CHARS}]+$")
_CASE_ID_RE = re.compile(CASE_ID_PATTERN)
_ANY_SEPARATOR_RE = re.compile(f"[{re.escape(SEPARATOR + ''.join(LEGACY_SEPARATORS))}]")

#: AgentCore Runtime rejects a session id shorter than this.
RUNTIME_SESSION_MIN_LENGTH = 33

_SESSION_PREFIX = "erp-case-"
_SESSION_PAD = "0"


class CaseKeyError(ValueError):
    """A case identity could not be built or parsed."""


def format_case_id(document_number: str, item_id: str) -> str:
    """Build the canonical ``case_id`` from the two DynamoDB key segments.

    Args:
        document_number: SAP document number (partition key).
        item_id: Item identifier within the document (sort key).

    Returns:
        The canonical ``{document_number}-{item_id}`` string.

    Raises:
        CaseKeyError: If either segment is empty or uses a character outside
            ``SEGMENT_CHARS`` — including the separator itself, which would make
            the result impossible to parse back.
    """
    doc = "" if document_number is None else str(document_number).strip()
    item = "" if item_id is None else str(item_id).strip()
    for label, value in (("document_number", doc), ("item_id", item)):
        if not value:
            raise CaseKeyError(f"{label} is required to build a case_id")
        if not _SEGMENT_RE.match(value):
            raise CaseKeyError(
                f"{label}={value!r} is not a valid case_id segment; "
                f"expected characters in [{SEGMENT_CHARS}]"
            )
    return f"{doc}{SEPARATOR}{item}"


def parse_case_id(case_id: str) -> tuple[str, str]:
    """Split a ``case_id`` back into ``(document_number, item_id)``.

    Needed where SAP wants the two segments and no case record is at hand; reads of a
    stored case should prefer its ``document_number`` / ``item_id`` attributes.
    Accepts the canonical form and the legacy ``#``/``/`` separators.

    Raises:
        CaseKeyError: If the value is not a well-formed case identity.
    """
    canonical = normalize_case_id(case_id)
    doc, item = canonical.split(SEPARATOR, 1)
    return doc, item


def to_case_key(case_id: str) -> dict[str, str]:
    """Return the DynamoDB ``Key`` dict for a ``case_id``.

    ``case_id`` is the cases table's sole partition key, so this is a one-attribute
    key. It stays a function rather than an inline dict so the attribute name lives
    in one place, and so callers that hold a legacy ``doc#item`` value are normalized
    on the way in.

    Raises:
        CaseKeyError: If the value is not a well-formed case identity.
    """
    return {"case_id": normalize_case_id(case_id)}


def normalize_case_id(case_id: str) -> str:
    """Coerce any accepted case identity form to the canonical one.

    Raises:
        CaseKeyError: If the value is empty, has the wrong number of segments, or
            uses characters outside ``SEGMENT_CHARS``.
    """
    value = "" if case_id is None else str(case_id).strip()
    if not value:
        raise CaseKeyError("case_id is required")
    if _CASE_ID_RE.match(value):
        return value
    segments = _ANY_SEPARATOR_RE.split(value)
    if len(segments) != 2:
        raise CaseKeyError(
            f"case_id={value!r} is not a document/item pair; "
            f"expected {{document_number}}{SEPARATOR}{{item_id}}"
        )
    return format_case_id(segments[0], segments[1])


def try_normalize_case_id(case_id) -> str | None:
    """Best-effort :func:`normalize_case_id` — ``None`` instead of raising.

    For untrusted edges (webhook bodies, free-text prompts) where an absent or
    malformed id is an expected outcome that downstream code resolves another way.
    """
    try:
        return normalize_case_id(case_id)
    except CaseKeyError:
        return None


def to_runtime_session_id(case_id: str) -> str:
    """Derive a stable AgentCore session id for a case.

    Deterministic, so every turn and every background resume for one case lands in
    the same AgentCore Memory session instead of a fresh random one. Right-padded
    because AgentCore Runtime rejects ids shorter than
    :data:`RUNTIME_SESSION_MIN_LENGTH` — a bare ``case-5100001976-2026`` is only 20
    characters and would be refused.

    Raises:
        CaseKeyError: If ``case_id`` is not a well-formed case identity.
    """
    base = f"{_SESSION_PREFIX}{normalize_case_id(case_id)}"
    if len(base) < RUNTIME_SESSION_MIN_LENGTH:
        base += SEPARATOR + _SESSION_PAD * (RUNTIME_SESSION_MIN_LENGTH - len(base) - 1)
    return base
