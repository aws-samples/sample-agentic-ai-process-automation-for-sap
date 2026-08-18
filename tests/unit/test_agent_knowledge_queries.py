# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""
The precedent query must be keyed, ordered and bounded; the vendor-risk
traversal must terminate on cycles and respect the depth bound. traverse() is
the pure reference for the recursive CTE, so those semantics are testable
without a database.
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(
    0, str(_REPO_ROOT / "agentcore" / "gateway" / "tools" / "agent_knowledge")
)

import queries as q  # noqa: E402


def test_precedent_sql_is_keyed_bounded_and_suppresses_thumbs_down():
    sql = q.PRECEDENT_SQL
    assert ":process_type" in sql
    assert ":amount_band" in sql
    assert "LIMIT 3" in sql
    # A thumbs-down precedent must never be returned as guidance.
    assert "user_rating, 0) >= 0" in sql


def test_vendor_risk_sql_guards_cycles_and_bounds_depth():
    sql = q.VENDOR_RISK_SQL
    assert "WITH RECURSIVE" in sql
    assert "= ANY(r.path)" in sql, "missing cycle guard"
    assert "r.depth < 3" in sql, "missing depth bound"


def test_amount_band_buckets_are_stable_and_joinable():
    assert q.amount_band(50) == q.amount_band(99)
    assert q.amount_band(50) != q.amount_band(5000)
    assert q.amount_band(0) == q.amount_band(1)
    # Negative amounts (credit memos) must not crash or collide with large debits.
    assert q.amount_band(-5000) == q.amount_band(5000)


def test_amount_band_boundary_at_100():
    # 100 must land in lt_1000, not lt_100
    assert q.amount_band(100) == q.amount_band(999)


def test_traverse_terminates_on_a_cycle():
    edges = [("A", "B", "shares_bank_account"), ("B", "A", "shares_bank_account")]
    rows = q.traverse(edges, "A")
    assert [r["vendor"] for r in rows] == ["B"]
    assert rows[0]["path"] == ["A", "B"]


def test_traverse_respects_the_depth_bound():
    edges = [
        ("A", "B", "shares_address"),
        ("B", "C", "shares_address"),
        ("C", "D", "shares_address"),
        ("D", "E", "shares_address"),
    ]
    reached = {r["vendor"] for r in q.traverse(edges, "A", max_depth=3)}
    assert reached == {"B", "C", "D"}
    assert "E" not in reached


def test_traverse_returns_empty_for_an_unconnected_vendor():
    assert q.traverse([("A", "B", "shares_tax_id")], "Z") == []


def test_traverse_emits_one_row_per_vendor_diamond():
    # Diamond A→B, A→C, B→D, C→D must emit D once, not per-path
    edges = [("A", "B", "e"), ("A", "C", "e"), ("B", "D", "e"), ("C", "D", "e")]
    rows = q.traverse(edges, "A")
    vendor_list = [r["vendor"] for r in rows]
    assert vendor_list.count("D") == 1, "D should appear exactly once, not per path"
    assert set(vendor_list) == {"B", "C", "D"}, "all reachable vendors must be present"


def test_shape_precedent_parses_tool_sequence_json():
    records = [
        {
            "case_id": "INV-1",
            "disposition": "rejected_duplicate",
            "tool_sequence": '["get_case_state", "odata_read"]',
            "sop_version": "v3",
            "user_rating": 1,
        }
    ]
    shaped = q.shape_precedent(records)
    assert shaped[0]["tool_sequence"] == ["get_case_state", "odata_read"]
    assert shaped[0]["sop_version"] == "v3"


def test_shape_vendor_risk_preserves_the_path_as_evidence():
    records = [
        {
            "vendor": "V2",
            "path": ["V1", "V2"],
            "depth": 1,
            "edge_types": "shares_bank_account",
        }
    ]
    shaped = q.shape_vendor_risk(records)
    assert shaped[0]["path"] == ["V1", "V2"]
    assert shaped[0]["depth"] == 1


def test_schema_ddl_is_rerunnable():
    joined = "\n".join(q.SCHEMA_DDL)
    assert joined.count("IF NOT EXISTS") >= 5
    assert "agent_knowledge.precedent" in joined
    assert "agent_knowledge.vendor_edge" in joined
