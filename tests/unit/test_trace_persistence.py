# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""The merge seam between the hook and the persisted trace.

merge_evidence is the join that makes the evidence model work: the hook keys
evidence by toolUseId, segments.py records the same id as tool_call_id, and this
pairs them. A silent mismatch loses all provenance with no error, so the join is
tested directly rather than through DynamoDB (there is no moto in this repo).
"""

from utils.evidence import MAX_TRACES, cap_traces, merge_evidence

EVIDENCE_BY_ID = {
    "toolu_A": {
        "evidence": {"kind": "sap_read", "at": "2026-07-30T09:14:02Z"},
        "status": "success",
    },
    "toolu_B": {
        "evidence": {"kind": "sap_write", "op": "update"},
        "status": "error",
    },
}


def test_evidence_merges_onto_the_matching_segment():
    segments = [
        {"type": "text", "content": "Checking the PO."},
        {"type": "tool", "tool_call_id": "toolu_A", "tool_name": "odata_read"},
        {"type": "tool", "tool_call_id": "toolu_B", "tool_name": "odata_update"},
    ]
    merged = merge_evidence(segments, EVIDENCE_BY_ID)
    assert merged[0] == {"type": "text", "content": "Checking the PO."}
    assert merged[1]["evidence"]["kind"] == "sap_read"
    assert merged[1]["status"] == "success"
    assert merged[2]["evidence"]["op"] == "update"
    assert merged[2]["status"] == "error"


def test_a_segment_with_no_matching_evidence_is_left_alone():
    # The stream can fold a tool segment the hook never saw (e.g. the run was
    # cancelled mid-call). It must persist as today's shape, not crash.
    segments = [{"type": "tool", "tool_call_id": "toolu_UNKNOWN", "tool_name": "x"}]
    merged = merge_evidence(segments, EVIDENCE_BY_ID)
    assert "evidence" not in merged[0]
    assert "status" not in merged[0]


def test_a_segment_with_no_tool_call_id_is_left_alone():
    segments = [{"type": "tool", "tool_name": "legacy"}]
    assert merge_evidence(segments, EVIDENCE_BY_ID) == [
        {"type": "tool", "tool_name": "legacy"}
    ]


def test_no_evidence_at_all_is_a_no_op():
    segments = [{"type": "tool", "tool_call_id": "toolu_A"}]
    assert merge_evidence(segments, {}) == [{"type": "tool", "tool_call_id": "toolu_A"}]
    assert merge_evidence(segments, None) == [
        {"type": "tool", "tool_call_id": "toolu_A"}
    ]


def test_merge_applies_the_truncation_budgets():
    segments = [
        {
            "type": "tool",
            "tool_call_id": "toolu_A",
            "tool_result": "x" * 5000,
            "tool_input": "y" * 5000,
        }
    ]
    merged = merge_evidence(segments, EVIDENCE_BY_ID)
    assert len(merged[0]["tool_result"].encode()) <= 512
    assert len(merged[0]["tool_input"].encode()) <= 256
    assert merged[0]["evidence"]["truncated"] is True


def test_the_cap_drops_oldest_first_and_counts_what_went():
    traces = [{"trace_id": str(i)} for i in range(MAX_TRACES + 2)]
    kept, dropped = cap_traces(traces)
    assert dropped == 2
    assert kept[0]["trace_id"] == "2"
    assert len(kept) == MAX_TRACES
