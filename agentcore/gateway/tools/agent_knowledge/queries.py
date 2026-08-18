# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
SQL and row shaping for the agent knowledge tools.

Kept separate from the handler so the traversal semantics — cycle guard and
depth bound — are testable without a database. `traverse` is the pure reference
for VENDOR_RISK_SQL; if you change one, change both.
"""

import json
import sys
from pathlib import Path

# Add shared_types to path so `amount_band` resolves both in tests (via conftest)
# and when this module is run directly (not deployed).
sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent.parent.parent.parent
        / "lambdas"
        / "layers"
        / "shared_types"
    ),
)

# Re-export the shared definition so both write and read sides use one copy.
from amount_band import amount_band  # noqa: F401

MAX_DEPTH = 3
MAX_PRECEDENTS = 3

SCHEMA_DDL = [
    "CREATE SCHEMA IF NOT EXISTS agent_knowledge",
    """
    CREATE TABLE IF NOT EXISTS agent_knowledge.precedent (
      case_id           text PRIMARY KEY,
      process_type      text NOT NULL,
      supplier_number   text,
      amount_band       text NOT NULL,
      disposition       text NOT NULL,
      tool_sequence     jsonb NOT NULL,
      sop_version       text NOT NULL,
      user_rating       smallint,
      resolved_at       timestamptz NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS precedent_lookup_idx
      ON agent_knowledge.precedent (process_type, supplier_number, resolved_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_knowledge.lesson (
      lesson_id     bigserial PRIMARY KEY,
      process_type  text NOT NULL,
      scope_vendor  text,
      lesson        text NOT NULL,
      authored_by   text NOT NULL,
      created_at    timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_knowledge.vendor (
      supplier_number text PRIMARY KEY,
      name            text,
      country         text
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_knowledge.vendor_edge (
      from_vendor  text NOT NULL REFERENCES agent_knowledge.vendor,
      to_vendor    text NOT NULL REFERENCES agent_knowledge.vendor,
      edge_type    text NOT NULL,
      evidence     text NOT NULL,
      PRIMARY KEY (from_vendor, to_vendor, edge_type)
    )
    """,
]

# Keyed, ordered, bounded. coalesce(...) >= 0 drops thumbs-down precedents:
# a disposition a human rejected must never come back as guidance.
PRECEDENT_SQL = f"""
SELECT case_id, disposition, tool_sequence::text AS tool_sequence,
       sop_version, user_rating
FROM agent_knowledge.precedent
WHERE process_type = :process_type
  AND (:supplier_number = '' OR supplier_number = :supplier_number)
  AND amount_band = :amount_band
  AND coalesce(user_rating, 0) >= 0
ORDER BY user_rating DESC NULLS LAST, resolved_at DESC
LIMIT {MAX_PRECEDENTS}
"""

LESSON_SQL = """
SELECT lesson_id, lesson, authored_by, scope_vendor
FROM agent_knowledge.lesson
WHERE process_type = :process_type
  AND (scope_vendor IS NULL OR scope_vendor = :supplier_number)
ORDER BY created_at DESC
LIMIT 5
"""

# `path` is returned as evidence: the agent cites the chain rather than
# asserting a relationship. The ANY(r.path) test is the cycle guard and must
# stay in the recursive term — as a post-filter it would not terminate.
VENDOR_RISK_SQL = f"""
WITH RECURSIVE ring(vendor, path, depth, edge_type) AS (
  SELECT :supplier_number, ARRAY[:supplier_number], 0, NULL::text
  UNION ALL
  SELECT e.to_vendor, r.path || e.to_vendor, r.depth + 1, e.edge_type
  FROM ring r
  JOIN agent_knowledge.vendor_edge e ON e.from_vendor = r.vendor
  WHERE r.depth < {MAX_DEPTH}
    AND NOT e.to_vendor = ANY(r.path)
)
SELECT vendor, path, depth, edge_types
FROM (
  SELECT DISTINCT ON (vendor) vendor, path, depth, edge_type AS edge_types
  FROM ring
  WHERE depth > 0
  ORDER BY vendor, depth
) shortest
ORDER BY depth, vendor
"""


def shape_precedent(records: list[dict]) -> list[dict]:
    """Data API rows → precedent evidence. tool_sequence arrives as jsonb::text."""
    shaped = []
    for row in records:
        raw = row.get("tool_sequence")
        try:
            tool_sequence = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except json.JSONDecodeError:
            tool_sequence = []
        shaped.append(
            {
                "case_id": row.get("case_id"),
                "disposition": row.get("disposition"),
                "tool_sequence": tool_sequence,
                "sop_version": row.get("sop_version"),
                "user_rating": row.get("user_rating"),
            }
        )
    return shaped


def shape_vendor_risk(records: list[dict]) -> list[dict]:
    return [
        {
            "vendor": row.get("vendor"),
            "path": row.get("path") or [],
            "depth": row.get("depth"),
            "edge_types": row.get("edge_types"),
        }
        for row in records
    ]


def traverse(
    edges: list[tuple[str, str, str]], start: str, max_depth: int = MAX_DEPTH
) -> list[dict]:
    """Pure reference for VENDOR_RISK_SQL — breadth-first, cycle-guarded.

    Exists so the traversal semantics have a runnable check without a database.
    Keep in step with VENDOR_RISK_SQL.
    """
    adjacency: dict[str, list[tuple[str, str]]] = {}
    for src, dst, edge_type in edges:
        adjacency.setdefault(src, []).append((dst, edge_type))

    out: list[dict] = []
    seen: set[str] = {start}
    frontier = [(start, [start], 0)]
    while frontier:
        vendor, path, depth = frontier.pop(0)
        if depth >= max_depth:
            continue
        for neighbour, edge_type in adjacency.get(vendor, []):
            if neighbour in seen:  # cycle guard
                continue
            seen.add(neighbour)
            next_path = path + [neighbour]
            out.append(
                {
                    "vendor": neighbour,
                    "path": next_path,
                    "depth": depth + 1,
                    "edge_types": edge_type,
                }
            )
            frontier.append((neighbour, next_path, depth + 1))
    return out


def demo() -> None:
    """Self-check for the non-trivial logic: cycle guard, depth bound, banding."""
    assert traverse([("A", "B", "e"), ("B", "A", "e")], "A") == [
        {"vendor": "B", "path": ["A", "B"], "depth": 1, "edge_types": "e"}
    ], "cycle guard failed"

    chain = [("A", "B", "e"), ("B", "C", "e"), ("C", "D", "e"), ("D", "E", "e")]
    assert {r["vendor"] for r in traverse(chain, "A", max_depth=3)} == {
        "B",
        "C",
        "D",
    }, "depth bound failed"

    assert traverse(chain, "Z") == [], "unconnected vendor should return nothing"
    assert amount_band(-5000) == amount_band(5000), "banding must ignore sign"
    assert amount_band(99) != amount_band(101), "banding must separate at 100"

    assert "= ANY(r.path)" in VENDOR_RISK_SQL, "SQL lost its cycle guard"
    assert f"r.depth < {MAX_DEPTH}" in VENDOR_RISK_SQL, "SQL lost its depth bound"
    assert "DISTINCT ON (vendor)" in VENDOR_RISK_SQL, "SQL lost its per-vendor dedup"

    print("queries.demo: ok")


if __name__ == "__main__":
    demo()
