# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""
SOPs and skill prompts instruct the agent to write case statuses as prose. Nothing
type-checks that prose against CaseStatus, so a status the schema does not define
reaches `_update_case`, is stored verbatim, and then renders as "Detected" in the
UI because `frontend/src/types/cases.ts` falls back on an unknown value. These
tests are the missing check: every status the corpus names must exist in the enum.
"""

import json
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SCHEMA = _REPO_ROOT / "types" / "cases.schema.json"
_SOP_DIR = _REPO_ROOT / "knowledge-base" / "sops"
_SKILLS_DIR = _REPO_ROOT / "skills"

# The corpus writes status assignments as prose, e.g. "update case state to
# 'error'" and 'update the case to "on_hold"'. Anchoring on the quoted value after
# a case/state phrase keeps this narrow: only quoted snake_case literals count, so
# ordinary prose about errors or escalation is not flagged.
_STATUS_PATTERN = re.compile(
    r"""(?:case|case\s+state|status)\s*(?:state\s*)?(?:to|=|:)\s*["']([a-z][a-z_]*)["']""",
    re.IGNORECASE,
)


def _valid_statuses() -> set[str]:
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    return set(schema["definitions"]["CaseStatus"]["enum"])


def _instruction_files() -> list[Path]:
    # Every .txt under skills/, not just base_prompt.txt: the shared
    # _platform_prompt.txt names case statuses too, and it reaches every skill.
    return sorted(_SOP_DIR.rglob("*.txt")) + sorted(_SKILLS_DIR.rglob("*.txt"))


def _cited_statuses(path: Path) -> set[str]:
    return {
        m.group(1).lower()
        for m in _STATUS_PATTERN.finditer(path.read_text(encoding="utf-8"))
    }


def test_corpus_has_instruction_files_to_check():
    # A glob that silently matches nothing would make every test below vacuous.
    files = _instruction_files()
    assert files, "no SOP or base_prompt files found — check the glob paths"
    assert any(p.name == "base_prompt.txt" for p in files)


@pytest.mark.parametrize("path", _instruction_files(), ids=lambda p: p.name)
def test_every_status_the_instructions_write_is_in_the_enum(path):
    valid = _valid_statuses()
    unknown = sorted(_cited_statuses(path) - valid)
    assert not unknown, (
        f"{path.relative_to(_REPO_ROOT)} instructs the agent to write "
        f"{unknown}, which is not in CaseStatus {sorted(valid)}. Either add the "
        f"status to types/cases.schema.json and regenerate types, or rewrite the "
        f"clause to use an existing one."
    )


def test_no_clause_mandates_a_function_import_the_service_lacks():
    # The finance_ap SOPs used to open STEP 4 with "MUST park the invoice", but
    # the pinned service exposes only Post/Release/Cancel. The agent burned turns
    # hunting a Park that does not exist. Guard the vocabulary against the spec.
    spec = (
        _REPO_ROOT
        / "knowledge-base"
        / "sap-api-docs"
        / "EXAMPLE_API_SUPPLIERINVOICE_PROCESS_SRV.yaml"
    ).read_text(encoding="utf-8")
    assert "\n  /Post:" in spec, "spec layout changed — this check is now vacuous"
    assert "\n  /Park:" not in spec

    offenders = [
        path.relative_to(_REPO_ROOT)
        for path in (_SOP_DIR / "finance_ap").glob("*.txt")
        if re.search(r"MUST park", path.read_text(encoding="utf-8"), re.IGNORECASE)
    ]
    assert not offenders, (
        f"{offenders} mandate a Park operation the pinned "
        f"API_SUPPLIERINVOICE_PROCESS_SRV spec does not expose"
    )


def test_no_clause_polls_the_case_record_for_a_write_result():
    # po_accrual used to say "Poll get_case_state until last_sap_write_status is
    # SUCCESS or FAILED". No such field exists on the case record, and the SAP write
    # tools answer synchronously — so the agent looped until max_turns on a value
    # that never arrives. Anchor the corpus to the schema's actual field set.
    fields = set(json.loads(_SCHEMA.read_text(encoding="utf-8"))["properties"])
    assert "status" in fields, "schema layout changed — this check is now vacuous"
    assert not [f for f in fields if "write_status" in f or "write_response" in f]

    poll = re.compile(r"(?<!not )poll\s+get_case_state", re.IGNORECASE)
    offenders = [
        path.relative_to(_REPO_ROOT)
        for path in _instruction_files()
        if poll.search(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        f"{offenders} tell the agent to poll the case record for a write result. "
        f"SAP write tools return synchronously — read the tool's own response."
    )


def test_every_resolution_step_carries_a_citable_clause_anchor():
    # `evidence.clauses_retrieved` is populated by _CLAUSE_RE over the retrieved SOP
    # text, and the skill prompt tells the agent to cite `per §3.2`. A resolution step
    # written as unnumbered prose is therefore uncitable: the agent either omits the
    # citation or invents a number that verification cannot match. Import the
    # production regex so a change to it fails here rather than going unnoticed.
    from utils.evidence import _CLAUSE_RE

    unanchored = []
    for path in sorted((_SOP_DIR / "finance_ap").glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        start = text.index("STEP 3:")
        step = text[start : text.index("STEP 4:", start)]
        if not _CLAUSE_RE.search(step):
            unanchored.append(path.relative_to(_REPO_ROOT))
    assert not unanchored, (
        f"{unanchored} decide the case in STEP 3 with no numbered clause, so the "
        f"agent has nothing citable to name. Add `3.N  TEXT` anchors (two spaces)."
    )


def test_no_tolerance_predicate_leaves_the_binding_limit_ambiguous():
    # "exceeds X% OR Y units (whichever is greater)" is unreadable as a predicate:
    # OR fires on either limit, "whichever is greater" says the larger one binds,
    # and the two disagree on every case between the limits. Anchor on where a
    # percentage limit and its absolute counterpart co-occur — those spans are
    # the definitions — and require the conjunction there.
    pair = re.compile(
        r"\{\{\w*VARIANCE_PCT\}\}(?:.|\n){0,200}?"
        r"\{\{\w*(?:VARIANCE_UNITS|VARIANCE_ABS_USD)\}\}"
    )
    offenders, ambiguous = [], []
    for path in sorted((_SOP_DIR / "finance_ap").glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(_REPO_ROOT)
        if re.search(r"whichever is (greater|lesser|larger|smaller)", text, re.I):
            offenders.append(rel)
        # The TOLERANCES section lists symbols in a `| name | {{SYMBOL}} |` table.
        # Those rows declare; they don't decide. Only prose spans are predicates.
        for match in pair.finditer(text):
            span = match.group(0)
            if "|" in span:
                continue
            if not re.search(r"\bAND\b|\bBOTH\b", span):
                ambiguous.append((rel, " ".join(span.split())))
    assert not offenders, (
        f"{offenders} still say 'whichever is greater' — the predicate must name "
        f"one binding rule, not defer to a comparison between the two limits."
    )
    assert not ambiguous, (
        f"{ambiguous} join two tolerance limits without AND/BOTH, so whether one "
        f"breach or two is required to escalate is left to the model."
    )


def test_the_boundary_eval_case_matches_the_predicate_the_sop_states():
    # The AND reading is what makes 108-vs-100 (8%, 8 units) auto-release. If the
    # corpus is ever flipped to OR, this case must flip with it or the eval
    # silently asserts the opposite of what the SOP says.
    cases = json.loads(
        (_REPO_ROOT / "agentcore" / "evals" / "ground_truth.json").read_text(
            encoding="utf-8"
        )
    )
    case = next(
        c for c in cases if c["test_id"] == "ap_quantity_variance_at_unit_floor"
    )
    seed = case["seed"]["sap_params"]
    constants = json.loads(
        (_SKILLS_DIR / "finance_ap" / "config.json").read_text(encoding="utf-8")
    )["constants"]

    units = abs(seed["invoice_quantity"] - seed["gr_quantity"])
    pct = units / seed["gr_quantity"] * 100
    above_pct = pct > constants["QTY_VARIANCE_PCT"]
    above_units = units > constants["QTY_VARIANCE_UNITS"]
    assert above_pct and not above_units, (
        "the case no longer straddles the two limits, so it stops discriminating "
        "AND from OR — re-seed it between QTY_VARIANCE_PCT and QTY_VARIANCE_UNITS"
    )
    assert case["expected"]["outcome"] == "auto_release", (
        "the SOP requires BOTH limits breached to escalate; one breach must "
        "auto-release"
    )


def _assembled_prompt(process_type: str) -> str:
    # Assert on what the model receives, not on one file: the mechanics live in the
    # shared preamble now, so a per-file assertion would pass while a broken
    # {PLATFORM_MECHANICS} substitution shipped an empty prompt.
    from utils import skill_router as sr

    sr._skills_index = None
    return sr.resolve_skill(process_type)["system_prompt"]


def test_the_citation_convention_reaches_the_agent():
    # The verifier grades a quoted span against the SOP text. It has nothing to
    # grade unless the prompt asks for the sentence in quotes.
    prompt = _assembled_prompt("quantity_variance")
    assert "exactly as written" in prompt and "double quotes" in prompt, (
        "the assembled prompt must tell the agent to quote the SOP rule it acted "
        "on verbatim — a paraphrase cannot be verified"
    )
    assert "whether a number exists or not" in prompt, (
        "citing must not be conditional on a clause number: most real SOPs carry "
        "none, and the quote is the citation"
    )


def test_the_prompt_tells_the_agent_to_scope_its_reads():
    # A_SupplierInvoice has over a hundred fields. An unselected read lands the whole
    # row in the conversation, where every later turn re-reads it — so one sloppy read
    # is billed for the rest of the invocation. `select` is a tool parameter, so this
    # is platform mechanics and belongs in the prompt, not in SOP text.
    prompt = _assembled_prompt("quantity_variance")
    assert "select" in prompt, (
        "the assembled prompt must tell the agent to pass `select` on "
        "odata_read — the SAP MCP tool defaults to returning every field"
    )
    assert "odata_count" in prompt, (
        "the prompt must point at odata_count for existence/cardinality questions, "
        "or the agent reads rows to count them"
    )


def test_pattern_matches_the_forms_the_corpus_actually_uses():
    # Guards the regex itself: if it stops matching, the tests above pass by
    # finding nothing rather than by the corpus being clean.
    samples = [
        "the agent MUST update the case to 'error', notify",
        'the agent MUST update case state to "on_hold" with the reminder date',
        "- Update case state to 'waiting_for_response' with timestamp",
        "set status to 'complete'",
    ]
    assert [_STATUS_PATTERN.search(s).group(1) for s in samples] == [
        "error",
        "on_hold",
        "waiting_for_response",
        "complete",
    ]
    # Prose about errors must not be mistaken for a status assignment.
    assert not _STATUS_PATTERN.search("notify the team with the error detail")
