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
  5. Writes {skill_id}/{process_type}_exemplars.md to EXEMPLAR_BUCKET, which no
     knowledge base ingests — see exemplar_s3_key

Scoring: human thumbs-up boosts a case, thumbs-down suppresses it, but an
unrated case with an exceptionally clean trace can still outrank a rated one.

The skill router loads these at agent start time — zero runtime cost.
"""

import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

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


# Not best-effort, unlike the validator above: the read side keys on the
# identical band, so a drifting local fallback would silently return no
# precedents. Path insert mirrors agent_knowledge/queries.py.
sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "layers" / "shared_types"),
)

from amount_band import amount_band  # noqa: E402

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
s3 = boto3.client("s3")
bedrock = boto3.client(
    "bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1")
)

TABLE_NAME = os.environ["CASES_TABLE"]
# Not the SOP bucket: everything there is ingested by the SOPs knowledge base, and
# these condensed traces must never come back as `search_sap_sops` results.
EXEMPLAR_BUCKET = os.environ["EXEMPLAR_BUCKET"]
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-sonnet-5")
MAX_EXEMPLARS = int(os.environ.get("MAX_EXEMPLARS", "3"))
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "30"))

# Scoring weights — tune via env vars
RATING_BONUS = float(os.environ.get("RATING_BONUS", "0.3"))  # boost for thumbs-up
RATING_PENALTY = float(
    os.environ.get("RATING_PENALTY", "0.8")
)  # multiplier for thumbs-down

# Set only when agent_knowledge.enabled — their presence IS the feature flag on
# this Lambda (see _agent_knowledge_enabled).
CLUSTER_ARN = os.environ.get("CLUSTER_ARN")
SECRET_ARN = os.environ.get("SECRET_ARN")
DATABASE_NAME = os.environ.get("DATABASE_NAME")

PRECEDENT_UPSERT = """
INSERT INTO agent_knowledge.precedent
  (case_id, process_type, supplier_number, amount_band, disposition,
   tool_sequence, sop_version, user_rating, resolved_at)
VALUES
  (:case_id, :process_type, :supplier_number, :amount_band, :disposition,
   CAST(:tool_sequence AS jsonb), :sop_version, :user_rating, now())
ON CONFLICT (case_id) DO UPDATE SET
  disposition   = EXCLUDED.disposition,
  tool_sequence = EXCLUDED.tool_sequence,
  sop_version   = EXCLUDED.sop_version,
  user_rating   = EXCLUDED.user_rating,
  resolved_at   = EXCLUDED.resolved_at
"""

CONDENSE_PROMPT = """Condense this agent trace into a numbered step sequence.
Each step should be ONE line: the tool/action name and what it accomplished.
Strip PO numbers, dollar amounts, and timestamps — keep only the pattern.
Output ONLY the numbered steps, nothing else.

Agent trace:
{history}"""


def _process_type_skill_map() -> dict[str, str]:
    """process_type → skill_id.

    Built at synth into PROCESS_TYPE_SKILL_MAP because skills/ never ships with
    this Lambda's asset — a filesystem scan alone returns nothing in deployment
    and would skip every write. The scan is the local-test path only.
    """
    raw = os.environ.get("PROCESS_TYPE_SKILL_MAP")
    if raw:
        return json.loads(raw)

    skills_root = Path(__file__).resolve().parents[2] / "skills"
    if not skills_root.is_dir():
        return {}
    return {
        process_type: json.loads(cfg.read_text(encoding="utf-8"))["skill_id"]
        for cfg in skills_root.glob("*/config.json")
        for process_type in json.loads(cfg.read_text(encoding="utf-8")).get(
            "process_type_to_sop", {}
        )
    }


def exemplar_s3_key(process_type: str) -> Optional[str]:
    """Must match skill_router.exemplar_s3_key — see test_exemplar_key_parity.

    None when no skill claims the process_type: the reader derives the key from
    the owning skill's id, so a guessed one could never be read back.
    """
    skill_id = _process_type_skill_map().get(process_type)
    return f"{skill_id}/{process_type}_exemplars.md" if skill_id else None


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


def tool_sequence_from_traces(traces: list[dict]) -> list[str]:
    """Ordered tool names from a case's traces.

    Mechanical, not model-derived: the same case must always yield the same
    precedent row, which is what makes a precedent citation defensible.
    """
    return [
        seg["tool_name"]
        for trace in traces
        for seg in trace.get("segments", [])
        if seg.get("type") == "tool" and seg.get("tool_name")
    ]


def rating_to_smallint(rating: object) -> Optional[int]:
    """DynamoDB stores 'positive'/'negative'; the precedent column is smallint."""
    return {"positive": 1, "negative": -1}.get(rating)


def sop_version_from_traces(traces: list[dict]) -> str:
    """The SOP version the case's last invocation followed.

    Read off the trace, not the SOP as it stands now: revising a SOP must not
    restate what an already-resolved case was decided under. The last trace wins
    because that is the run that reached the disposition being recorded.

    "unversioned" where no trace carries one — traces stored before this field
    existed, the discovery path, and SOPs with no Version header all land here.
    The column is NOT NULL because a precedent citation without a SOP version is
    not defensible.
    """
    for trace in reversed(traces or []):
        version = (trace or {}).get("sop_version")
        if version:
            return str(version)
    return "unversioned"


def _agent_knowledge_enabled() -> bool:
    return bool(CLUSTER_ARN and SECRET_ARN and DATABASE_NAME)


def _write_precedent(case: dict, process_type: str) -> None:
    """Upsert one precedent row. Raises — the caller decides whether to continue."""
    rds_data = boto3.client("rds-data")
    traces = case.get("agent_traces", [])
    params = {
        "case_id": str(case.get("case_id") or case.get("document_number") or ""),
        "process_type": process_type,
        "supplier_number": str(case.get("supplier_number") or ""),
        "amount_band": amount_band(case.get("amount")),
        "disposition": str(case.get("disposition") or case.get("status") or "complete"),
        "tool_sequence": json.dumps(tool_sequence_from_traces(traces)),
        "sop_version": sop_version_from_traces(traces),
    }
    rating = rating_to_smallint(case.get("user_rating"))
    rds_data.execute_statement(
        resourceArn=CLUSTER_ARN,
        secretArn=SECRET_ARN,
        database=DATABASE_NAME,
        sql=PRECEDENT_UPSERT,
        parameters=[
            *({"name": k, "value": {"stringValue": v}} for k, v in params.items()),
            {
                "name": "user_rating",
                "value": {"isNull": True} if rating is None else {"longValue": rating},
            },
        ],
    )


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
                # Sonnet 5 rejects `temperature` (400) and runs adaptive thinking
                # unless told otherwise. Thinking tokens count against max_tokens,
                # so on a hard 500-token cap a long trace would truncate the
                # exemplar mid-list. This condense is mechanical — no reasoning to
                # buy — so spend the whole budget on output.
                "thinking": {"type": "disabled"},
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

        if _agent_knowledge_enabled():
            written = 0
            for case in best:
                try:
                    _write_precedent(case, process_type)
                    written += 1
                except Exception as e:
                    logger.warning(
                        f"Precedent write failed for {case.get('document_number')}: {e}"
                    )
            logger.info(f"{process_type}: wrote {written} precedent row(s)")
            if written:
                generated.append(process_type)
            continue

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
            key = exemplar_s3_key(process_type)
            if not key:
                logger.warning(
                    f"No skill owns process_type {process_type!r} — skipping "
                    f"exemplar write; nothing would ever read it back"
                )
                continue
            doc = _build_exemplar_doc(process_type, condensed)
            s3.put_object(Bucket=EXEMPLAR_BUCKET, Key=key, Body=doc.encode())
            logger.info(f"Wrote {key} to {EXEMPLAR_BUCKET}")
            generated.append(process_type)

    return {"status": "ok", "generated": generated}
