# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""The evidence model migration, asserted on the generated pydantic models.

Three things have to hold at once: a trace stored BEFORE this change still
validates (no backfill, so absence-tolerance is load-bearing), a trace stored
after it validates with the full evidence shape, and the two keys the agent
already writes but the closed root previously forbade — `cost_summary` and
`traces_dropped` — stop logging a validation warning on every case read.
"""

from generated_cases import AgentTrace, TraceSegment, WorkItem

LEGACY_SEGMENT = {"type": "tool", "tool_name": "odata_read", "tool_input": "{}"}

EVIDENCE_SEGMENT = {
    "type": "tool",
    "tool_call_id": "toolu_01ABC",
    "tool_name": "odata_read",
    "tool_input": '{"service_name":"API_PURCHASEORDER_PROCESS_SRV"}',
    "tool_result": '{"NetPriceAmount":"12.50"}',
    "status": "success",
    "evidence": {
        "kind": "sap_read",
        "at": "2026-07-30T09:14:02Z",
        "source": {
            "service": "API_PURCHASEORDER_PROCESS_SRV",
            "entity": "A_PurchaseOrderItem",
            "key": "4500000123/10",
        },
        "fields": [
            {"name": "NetPriceAmount", "value": "12.50"},
            {"name": "OrderQuantity", "value": "100"},
        ],
        "authz": {"mode": "ENFORCE", "via_gateway": True, "outcome": "permitted"},
        "truncated": True,
    },
}


def _case(**extra) -> dict:
    return {
        "case_id": "4500000123-10",
        "document_number": "4500000123",
        "item_id": "10",
        "domain": "finance_ap",
        "process_type": "price_variance",
        "status": "complete",
        "created_at": "2026-07-30T09:00:00Z",
        "updated_at": "2026-07-30T09:15:00Z",
        **extra,
    }


def test_a_pre_migration_segment_still_validates():
    # No backfill: every trace already in DynamoDB is on this path.
    segment = TraceSegment.model_validate(LEGACY_SEGMENT)
    assert segment.evidence is None
    assert segment.status is None
    assert segment.tool_call_id is None


def test_an_evidence_segment_validates_and_round_trips():
    segment = TraceSegment.model_validate(EVIDENCE_SEGMENT)
    assert segment.tool_call_id == "toolu_01ABC"
    assert segment.status == "success"
    assert segment.evidence.kind == "sap_read"
    assert segment.evidence.source.entity == "A_PurchaseOrderItem"
    assert [f.name for f in segment.evidence.fields] == [
        "NetPriceAmount",
        "OrderQuantity",
    ]
    assert segment.evidence.authz.mode == "ENFORCE"
    assert segment.evidence.authz.via_gateway is True
    assert segment.evidence.truncated is True


def test_sap_write_carries_the_op_discriminator():
    # Declared here so the schema change is one migration; consumed by proposed_write.
    segment = TraceSegment.model_validate(
        {
            "type": "tool",
            "tool_name": "odata_update",
            "status": "success",
            "evidence": {"kind": "sap_write", "op": "function_import"},
        }
    )
    assert segment.evidence.op == "function_import"


def test_sop_lookup_carries_retrieved_clauses():
    segment = TraceSegment.model_validate(
        {
            "type": "tool",
            "tool_name": "search_sap_sops",
            "status": "success",
            "evidence": {"kind": "sop_lookup", "clauses_retrieved": ["1.1", "1.2"]},
        }
    )
    assert segment.evidence.clauses_retrieved == ["1.1", "1.2"]


def test_a_trace_records_the_sop_version_it_followed():
    # The trace root is closed, so this needs its own declared key — without it the
    # write is dropped and a precedent citing the case names no authority.
    trace = AgentTrace.model_validate(
        {
            "trace_id": "t-1",
            "timestamp": "2026-07-30T09:14:00Z",
            "trigger": "poller",
            "sop_version": "2.0",
            "segments": [EVIDENCE_SEGMENT],
        }
    )
    assert trace.sop_version == "2.0"


def test_a_retired_clauses_available_still_validates():
    # Traces written before citation-by-quotation carry the key. The root forbids
    # extras, so dropping the declaration would log a warning on every read of an
    # already-persisted trace — hence declared-but-unproduced.
    trace = AgentTrace.model_validate(
        {
            "trace_id": "t-2",
            "timestamp": "2026-07-30T09:20:00Z",
            "trigger": "manual",
            "clauses_available": ["1.1", "3.2"],
            "segments": [],
        }
    )
    assert trace.clauses_available == ["1.1", "3.2"]


def test_cost_summary_no_longer_violates_the_closed_root():
    # basic_agent.py:792-824 already writes this; the root forbade it, so every
    # GET /cases/{id} logged a validation warning while returning the field anyway.
    item = WorkItem.model_validate(
        _case(
            cost_summary={
                "total_cost_usd": 0.1234,
                "total_input_tokens": 5000,
                "total_output_tokens": 900,
                "total_cache_read_tokens": 100,
                "invocation_count": 2,
            }
        )
    )
    assert item.cost_summary.invocation_count == 2
    assert item.cost_summary.total_cost_usd == 0.1234


def test_traces_dropped_is_declared():
    assert WorkItem.model_validate(_case(traces_dropped=3)).traces_dropped == 3


def test_a_whole_case_with_evidence_traces_validates():
    item = WorkItem.model_validate(
        _case(
            agent_traces=[
                {
                    "trace_id": "t-1",
                    "timestamp": "2026-07-30T09:14:00Z",
                    "trigger": "poller",
                    "segments": [LEGACY_SEGMENT, EVIDENCE_SEGMENT],
                }
            ]
        )
    )
    assert item.agent_traces[0].segments[1].evidence.kind == "sap_read"
