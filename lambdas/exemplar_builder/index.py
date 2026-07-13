# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# This is sample code. Not for use in production.
# See NOTICE and LICENSE for more information.
"""
Exemplar Builder — generates condensed resolution examples from successful cases.

Runs daily via EventBridge. For each process_type with completed cases:
  1. Queries DDB status-index for status=complete cases from last 30 days
  2. Scores each case: trace efficiency (fewer steps = better) + human rating bonus/penalty
  3. Picks the top N by composite score
  4. Uses Bedrock to condense agent traces into clean step sequences
  5. Writes {process_type}_exemplars.md to S3 alongside the SOPs

Scoring: human thumbs-up boosts a case, thumbs-down suppresses it, but an
unrated case with an exceptionally clean trace can still outrank a rated one.

The skill router loads these at agent start time — zero runtime cost.
"""

import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key

# WorkItem model + validator ship in the shared_types Lambda layer. Best-effort
# import: absent in local dev/test (validation no-ops), present in the Lambda.
try:
    from generated_cases import WorkItem
    from validate import validate_or_log
except ImportError:
    WorkItem = None

    def validate_or_log(model, data, *, context=""):
        return data


logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
s3 = boto3.client("s3")
bedrock = boto3.client(
    "bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1")
)

TABLE_NAME = os.environ["CASES_TABLE"]
SOP_BUCKET = os.environ["SOP_BUCKET"]
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")
MAX_EXEMPLARS = int(os.environ.get("MAX_EXEMPLARS", "3"))
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "30"))

# Scoring weights — tune via env vars
RATING_BONUS = float(os.environ.get("RATING_BONUS", "0.3"))  # boost for thumbs-up
RATING_PENALTY = float(
    os.environ.get("RATING_PENALTY", "0.8")
)  # multiplier for thumbs-down

CONDENSE_PROMPT = """Condense this agent trace into a numbered step sequence.
Each step should be ONE line: the tool/action name and what it accomplished.
Strip PO numbers, dollar amounts, and timestamps — keep only the pattern.
Output ONLY the numbered steps, nothing else.

Agent trace:
{history}"""


def _query_successful_cases() -> list[dict]:
    """Query all completed cases from the last N days."""
    table = dynamodb.Table(TABLE_NAME)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).isoformat()

    resp = table.query(
        IndexName="status-index",
        KeyConditionExpression=Key("status").eq("complete"),
        FilterExpression="updated_at >= :cutoff",
        ExpressionAttributeValues={":cutoff": cutoff},
    )
    items = resp.get("Items", [])
    for case in items:
        validate_or_log(WorkItem, case, context="exemplar_builder.query")
    return items


def _group_by_process_type(cases: list[dict]) -> dict[str, list[dict]]:
    """Group cases by process_type, filtering to those with agent traces."""
    grouped = defaultdict(list)
    for case in cases:
        pt = case.get("process_type")
        if pt and case.get("agent_traces"):
            grouped[pt].append(case)
    return grouped


def _score_case(case: dict) -> float:
    """Score a case for exemplar quality. Lower is better.

    Combines trace efficiency (fewer segments = lower base score) with
    human feedback as a weight modifier:
      - positive rating:  score *= (1 - RATING_BONUS)  → pulls score down (better)
      - negative rating:  score *= (1 + RATING_PENALTY) → pushes score up (worse)
      - no rating:        score unchanged
    """
    segments = sum(len(t.get("segments", [])) for t in case.get("agent_traces", []))
    score = float(segments)

    rating = case.get("user_rating")
    if rating == "positive":
        score *= 1 - RATING_BONUS
    elif rating == "negative":
        score *= 1 + RATING_PENALTY

    return score


def _pick_best(cases: list[dict], n: int) -> list[dict]:
    """Pick the N best exemplar candidates by composite score."""
    scored = sorted(cases, key=_score_case)
    return scored[:n]


def _condense_trace(traces: list[dict]) -> str:
    """Use Bedrock to condense agent traces into clean steps."""
    lines = []
    for trace in traces:
        for seg in trace.get("segments", []):
            if seg.get("type") == "tool" and seg.get("tool_name"):
                result_preview = (seg.get("tool_result") or "")[:200]
                lines.append(f"- {seg['tool_name']}: {result_preview}")
            elif seg.get("type") == "text" and seg.get("content"):
                lines.append(f"- thought: {seg['content'][:200]}")

    history_text = "\n".join(lines)

    resp = bedrock.invoke_model(
        modelId=MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 500,
                "temperature": 0,
                "messages": [
                    {
                        "role": "user",
                        "content": CONDENSE_PROMPT.format(history=history_text),
                    }
                ],
            }
        ),
    )
    result = json.loads(resp["body"].read())
    return result["content"][0]["text"].strip()


def _build_exemplar_doc(process_type: str, condensed: list[str]) -> str:
    """Build the exemplar markdown document."""
    lines = [f"## Recent Successful Resolutions: {process_type}\n"]
    for i, steps in enumerate(condensed, 1):
        lines.append(f"### Example {i}\n{steps}\n")
    lines.append(
        f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d')} "
        f"from {len(condensed)} successful case(s)._\n"
    )
    return "\n".join(lines)


def handler(event: dict, context: object) -> dict:
    """Lambda handler — generates exemplar documents from successful cases."""
    logger.info("Exemplar builder started")

    cases = _query_successful_cases()
    logger.info(f"Found {len(cases)} completed cases in last {LOOKBACK_DAYS} days")

    if not cases:
        logger.info("No completed cases — nothing to generate")
        return {"status": "no_cases"}

    grouped = _group_by_process_type(cases)
    generated = []

    for process_type, pt_cases in grouped.items():
        best = _pick_best(pt_cases, MAX_EXEMPLARS)
        scores = [
            (
                c.get("document_number"),
                f"{_score_case(c):.1f}",
                c.get("user_rating", "none"),
            )
            for c in best
        ]
        logger.info(
            f"{process_type}: {len(pt_cases)} candidates, picked {len(best)} — {scores}"
        )

        condensed = []
        for case in best:
            try:
                steps = _condense_trace(case["agent_traces"])
                condensed.append(steps)
            except Exception as e:
                logger.warning(
                    f"Failed to condense case {case.get('document_number')}: {e}"
                )

        if condensed:
            doc = _build_exemplar_doc(process_type, condensed)
            key = f"{process_type}/{process_type}_exemplars.md"
            s3.put_object(Bucket=SOP_BUCKET, Key=key, Body=doc.encode())
            logger.info(f"Wrote {key} to {SOP_BUCKET}")
            generated.append(process_type)

    return {"status": "ok", "generated": generated}
