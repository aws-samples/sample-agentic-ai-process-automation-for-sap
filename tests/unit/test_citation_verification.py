# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Citation by quotation: the substring check that replaced grading `per §N.N`.

Grading a clause *number* against the numbers present in the SOP passes a
fabricated rule wearing a real number — a green check on an ungrounded decision.
These assert the replacement holds on the real corpus, including the two cases a
single-path test misses: the injected SOP has its `{{SYMBOL}}` constants
substituted and the retrieved copy does not, and most real SOPs carry no clause
numbers at all.
"""

from pathlib import Path

import pytest
from utils.evidence import (
    QUOTE_MIN_WORDS,
    extract_evidence,
    normalize_quote,
    sop_text_in,
    verify_citation,
)

_SOPS = Path(__file__).resolve().parents[2] / "knowledge-base" / "sops"
_CORPUS = sorted(_SOPS.rglob("*.txt"))

AT = "2026-08-03T09:14:02Z"


def _cite(quote: str) -> str:
    return f'Escalated for review. per SOP: "{quote}"'


def _first_long_sentence(text: str) -> str:
    """A verbatim span from the document, long enough to clear the word floor.

    Lines carrying their own double quotes are skipped: wrapping one in a citation
    nests quote marks, and the extractor then sees only the fragment ahead of the
    inner quote. That is a real (benign) limitation of quote-mark delimiting, and
    it has its own case below rather than being smuggled into every corpus run.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if '"' in stripped:
            continue
        if len(stripped.split()) >= QUOTE_MIN_WORDS + 2 and "MUST" in stripped:
            return stripped
    raise AssertionError("no quotable normative line found")


# ── the corpus verifies, and inventions do not ───────────────────────────────


def test_the_corpus_is_not_empty():
    # Every parametrised case below would vacuously pass on an empty glob.
    assert _CORPUS, f"no SOPs found under {_SOPS}"


@pytest.mark.parametrize("sop", _CORPUS, ids=lambda p: p.stem)
def test_a_verbatim_span_from_every_corpus_sop_verifies(sop):
    body = sop.read_text()
    quote = _first_long_sentence(body)
    assert verify_citation(_cite(quote), body) == {"quote": quote, "verified": True}


@pytest.mark.parametrize("sop", _CORPUS, ids=lambda p: p.stem)
def test_a_paraphrase_of_a_real_clause_does_not_verify(sop):
    body = sop.read_text()
    words = _first_long_sentence(body).split()
    # Same words, reordered — semantically close, textually absent. This is the one
    # new failure mode the design introduces, and it must read as unverified.
    paraphrase = " ".join(words[::-1])
    verdict = verify_citation(_cite(paraphrase), body)
    assert verdict is not None and verdict["verified"] is False


def test_a_fabricated_rule_under_a_real_clause_number_does_not_verify():
    # The exact case that grades PASS under `§N.N` set membership: §3.1 exists in
    # the document, and the rule attributed to it does not.
    body = (_SOPS / "finance_ap" / "price_variance.txt").read_text()
    assert "3.1" in body
    verdict = verify_citation(
        'Auto-approved per §3.1, "variances under $500 need no review"', body
    )
    assert verdict == {
        "quote": "variances under $500 need no review",
        "verified": False,
    }


# ── the span bounds ──────────────────────────────────────────────────────────


def test_a_span_below_the_word_floor_is_not_gradeable():
    # "must not" matches nearly any SOP and proves nothing.
    body = "2.1  The agent MUST NOT fabricate a PO price under any circumstance."
    assert verify_citation('per SOP: "MUST NOT"', body) is None


def test_the_whole_sop_is_rejected_as_too_long():
    body = (_SOPS / "finance_ap" / "price_variance.txt").read_text()
    # Verbatim and present, but a citation has to be specific to be a citation.
    assert verify_citation(f'per SOP: "{body}"', body) is None


def test_a_long_span_carrying_few_full_stops_is_still_rejected():
    # The sentence ceiling alone does not bite here: a heading block or a run-on
    # clause can be pages long and terminate twice or not at all.
    body = "The agent MUST " + "review each line of the purchase order carefully " * 12
    assert verify_citation(f'per SOP: "{body}"', body) is None


def test_a_clause_containing_its_own_quote_marks_is_not_gradeable():
    # Quote-mark delimiting cannot survive nested quote marks — the span ends at the
    # inner mark. The verdict is "nothing to grade", which is the safe direction:
    # a compliant citation is never reported as invented.
    body = (
        'The agent MUST treat "ABOVE tolerance" as requiring approval before posting.'
    )
    assert verify_citation(f'per SOP: "{body}"', body) is None


def test_two_sentences_are_still_a_citation():
    body = "The agent MUST post the invoice without further review. Escalation is not required here."
    verdict = verify_citation(f'per SOP: "{body}"', body)
    assert verdict == {"quote": body, "verified": True}


# ── the two renderings of one clause (the trap a single-path test misses) ────

_ASSEMBLED = """You are an AP specialist.

<sop_document>
2.2  Both limits MUST be breached for the variance to be ABOVE tolerance:
       ABOVE  tolerance = price_variance_pct > 2%
</sop_document>

Cite the rule you acted on.
"""

# What search_sap_sops returns for the same clause: contacts substituted, constants
# deliberately left visible, and newlines already collapsed to spaces by Retrieve.
_RETRIEVED = (
    "2.2  Both limits MUST be breached for the variance to be ABOVE tolerance: "
    "ABOVE  tolerance = price_variance_pct > {{PRICE_VARIANCE_PCT}}%"
)


def test_the_injected_sop_is_recovered_from_the_assembled_prompt():
    # resolve_skill substitutes AFTER wrapping, so this is the only place the text
    # the model actually saw exists — the raw file still reads {{PRICE_VARIANCE_PCT}}.
    extracted = sop_text_in(_ASSEMBLED)
    assert "price_variance_pct > 2%" in extracted
    assert "You are an AP specialist" not in extracted


def test_a_substituted_constant_verifies_against_the_assembled_prompt():
    quote = "ABOVE  tolerance = price_variance_pct > 2%"
    verdict = verify_citation(_cite(quote), sop_text_in(_ASSEMBLED))
    assert verdict == {"quote": quote, "verified": True}


def test_the_same_clause_verifies_against_the_retrieval_path_rendering():
    # The union baseline is what makes both renderings gradeable. Quoting the
    # unsubstituted form is correct on the discovery path and must not read as
    # invented just because the injected copy renders it differently.
    baseline = f"{sop_text_in(_ASSEMBLED)}\n{_RETRIEVED}"
    for quote in (
        "ABOVE  tolerance = price_variance_pct > 2%",
        "ABOVE  tolerance = price_variance_pct > {{PRICE_VARIANCE_PCT}}%",
    ):
        assert verify_citation(_cite(quote), baseline)["verified"] is True


# ── an unnumbered SOP, which our own corpus cannot exercise ──────────────────

_UNNUMBERED = """Invoice Handling Procedure

When the invoiced amount matches the purchase order, the agent must post the
invoice without further review. Anything else goes to a human.
"""


def test_a_quote_from_an_unnumbered_sop_verifies_at_full_strength():
    # Most real SOPs are not numbered. The clause anchors in this repo's corpus are
    # hand-authored for the convention this check retires, so a verdict that leaned
    # on a number would overfit to the sample and fail on an adopter's documents.
    quote = "the agent must post the invoice without further review"
    verdict = verify_citation(f'per SOP: "{quote}"', _UNNUMBERED)
    assert verdict == {"quote": quote, "verified": True}


def test_an_absent_number_never_weakens_the_verdict():
    quote = "the agent must post the invoice without further review"
    with_number = verify_citation(f'per §2.1, "{quote}"', _UNNUMBERED)
    without = verify_citation(f'per SOP: "{quote}"', _UNNUMBERED)
    assert with_number == without


# ── normalization ────────────────────────────────────────────────────────────


def test_normalization_folds_what_a_round_trip_through_a_model_changes():
    # Curly quotes, an em dash, a non-breaking space and a line break are all
    # things the model reintroduces; none of them is a citation error.
    original = "The agent MUST escalate — see the\ntolerance table."
    round_tripped = "the agent must escalate — see the tolerance table."
    assert normalize_quote(original) == normalize_quote(round_tripped)


def test_prose_with_no_quotation_marks_is_not_graded():
    # A paraphrase and an ungraded citation are both "unverified", never "violated" —
    # but only the absence of a *quote* means there is nothing to report at all.
    body = "2.1  The agent MUST compute the price variance using the calculator tool"
    assert verify_citation("Escalated per clause 2.1 as required.", body) is None


def test_an_empty_baseline_grades_nothing_rather_than_failing_everything():
    # A run with no SOP loaded must not report every citation as invented.
    verdict = verify_citation(_cite("the agent MUST post the invoice today"), "")
    assert verdict is not None and verdict["verified"] is False


# ── the extractor wiring ─────────────────────────────────────────────────────

_BASELINE = "3.2  The agent MUST notify the requester before closing the case."


def _ok(text: str = "sent") -> dict:
    return {"content": [{"text": text}], "status": "success", "toolUseId": "t1"}


def test_a_notification_records_the_verified_citation():
    evidence = extract_evidence(
        "send_notification",
        {
            "recipient": "ap-team@example.com",
            "body": _cite(
                "The agent MUST notify the requester before closing the case."
            ),
        },
        _ok(),
        at=AT,
        sop_baseline=_BASELINE,
    )
    assert evidence["citation"]["verified"] is True


def test_a_case_update_records_the_verified_citation():
    # tool_spec declares `updates` as a JSON string, so the citation arrives inside
    # a serialised note rather than as its own argument.
    evidence = extract_evidence(
        "update_case_state",
        {
            "case_id": "4500000123-10",
            "updates": '{"note": "Closed. per SOP: \\"The agent MUST notify the requester before closing the case.\\""}',
        },
        _ok(),
        at=AT,
        sop_baseline=_BASELINE,
    )
    assert evidence["citation"]["verified"] is True


def test_verification_runs_before_the_prose_preview_is_cut():
    # PROSE_MAX_CHARS caps the stored value at 240; a citation past that cut would
    # fail on a fragment of itself if the check ran on the preview.
    quote = "The agent MUST notify the requester before closing the case."
    body = "Context. " * 40 + _cite(quote)
    evidence = extract_evidence(
        "send_notification",
        {"recipient": "ap-team@example.com", "body": body},
        _ok(),
        at=AT,
        sop_baseline=_BASELINE,
    )
    assert len(body) > 240
    assert evidence["citation"] == {"quote": quote, "verified": True}


def test_a_notification_with_no_quote_carries_no_citation_key():
    evidence = extract_evidence(
        "send_notification",
        {"recipient": "ap-team@example.com", "body": "Escalated for review."},
        _ok(),
        at=AT,
        sop_baseline=_BASELINE,
    )
    assert "citation" not in evidence


def test_extraction_without_a_baseline_still_works():
    # The default keeps every existing caller — and the tests in test_evidence.py —
    # on the same path they were on before verification existed.
    evidence = extract_evidence(
        "send_notification",
        {"recipient": "ap-team@example.com", "body": "Escalated."},
        _ok(),
        at=AT,
    )
    assert evidence["kind"] == "notification"
    assert "citation" not in evidence
