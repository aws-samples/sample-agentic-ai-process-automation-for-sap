# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""The evidence extractor's non-trivial logic: one extractor per tool family, the
unknown-tool fallthrough, the truncation boundary, and the trace cap.

utils/evidence.py is deliberately stdlib-only so this suite can import it —
basic_agent.py pulls in strands/mcp and is not importable here (same constraint
as utils/mcp_topology.py, test_direct_topology_bearer.py).
"""

import json

from utils.evidence import (
    MAX_TRACES,
    PROSE_MAX_CHARS,
    TOOL_INPUT_MAX_BYTES,
    TOOL_RESULT_MAX_BYTES,
    cap_traces,
    extract_evidence,
    result_text,
    truncate_segment,
)

AT = "2026-07-30T09:14:02Z"


def _ok(text: str) -> dict:
    return {"content": [{"text": text}], "status": "success", "toolUseId": "t1"}


def _err(text: str) -> dict:
    return {"content": [{"text": text}], "status": "error", "toolUseId": "t1"}


# ── result_text ──────────────────────────────────────────────────────────────


def test_result_text_joins_text_blocks():
    result = {"content": [{"text": "a"}, {"text": "b"}], "status": "success"}
    assert result_text(result) == "a\nb"


def test_result_text_serialises_a_json_block():
    result = {"content": [{"json": {"k": 1}}], "status": "success"}
    assert json.loads(result_text(result)) == {"k": 1}


def test_result_text_tolerates_a_missing_or_odd_result():
    assert result_text(None) == ""
    assert result_text({}) == ""
    assert result_text({"content": [None, "raw"]}) == ""


# ── sap_read ─────────────────────────────────────────────────────────────────


def test_odata_read_records_service_entity_and_fields():
    evidence = extract_evidence(
        "odata_read",
        {
            "service_name": "API_PURCHASEORDER_PROCESS_SRV",
            "entity_set": "A_PurchaseOrderItem",
            "filter": "PurchaseOrder eq '4500000123' and PurchaseOrderItem eq '10'",
        },
        _ok(json.dumps({"NetPriceAmount": "12.50", "OrderQuantity": "100"})),
        at=AT,
        mode="ENFORCE",
    )
    assert evidence["kind"] == "sap_read"
    assert evidence["at"] == AT
    assert evidence["source"] == {
        "service": "API_PURCHASEORDER_PROCESS_SRV",
        "entity": "A_PurchaseOrderItem",
        "key": "4500000123/10",
    }
    assert evidence["fields"] == [
        {"name": "NetPriceAmount", "value": "12.50"},
        {"name": "OrderQuantity", "value": "100"},
    ]
    assert evidence["authz"] == {
        "mode": "ENFORCE",
        "via_gateway": True,
        "outcome": "permitted",
    }


def test_odata_read_unwraps_an_odata_results_envelope():
    payload = {"d": {"results": [{"NetPriceAmount": "12.50"}]}}
    evidence = extract_evidence(
        "odata_read", {"entity_set": "X"}, _ok(json.dumps(payload)), at=AT
    )
    assert evidence["fields"] == [{"name": "NetPriceAmount", "value": "12.50"}]


def test_odata_read_unwraps_the_mcp_server_envelope():
    # The shape the SAP MCP server actually returns. Without the unwrap, `fields`
    # is absent entirely and every diff's before column renders empty.
    payload = {
        "result": {
            "success": True,
            "message": "Successfully fetched OData data for A_PurchaseOrder",
            "data": [
                {
                    "__metadata": {
                        "uri": "https://sap.example/A_PurchaseOrder('4500000001')"
                    },
                    "PurchaseOrder": "4500000001",
                    "CompanyCode": "1710",
                }
            ],
            "metadata": {"record_count": 1},
        }
    }
    evidence = extract_evidence(
        "odata_read", {"entity_set": "A_PurchaseOrder"}, _ok(json.dumps(payload)), at=AT
    )
    assert evidence["fields"] == [
        {"name": "PurchaseOrder", "value": "4500000001"},
        {"name": "CompanyCode", "value": "1710"},
    ]


def test_an_empty_result_set_yields_no_fields():
    # A read that found nothing must not look like a read that found an empty record.
    payload = {"result": {"success": True, "data": [], "metadata": {"record_count": 0}}}
    evidence = extract_evidence(
        "odata_read",
        {"service_name": "S", "entity_set": "E"},
        _ok(json.dumps(payload)),
        at=AT,
    )
    assert evidence["source"] == {"service": "S", "entity": "E"}
    assert "fields" not in evidence


def test_odata_read_with_unparseable_result_keeps_the_source_and_drops_fields():
    # Provenance must survive a result the extractor cannot read.
    evidence = extract_evidence(
        "odata_read",
        {"service_name": "S", "entity_set": "E"},
        _ok("<html>gateway timeout"),
        at=AT,
    )
    assert evidence["kind"] == "sap_read"
    assert evidence["source"] == {"service": "S", "entity": "E"}
    assert "fields" not in evidence


def test_field_count_is_bounded():
    wide = {f"F{i}": str(i) for i in range(40)}
    evidence = extract_evidence(
        "odata_read", {"entity_set": "E"}, _ok(json.dumps(wide)), at=AT
    )
    assert len(evidence["fields"]) == 12


def test_nested_values_are_skipped_not_stringified():
    payload = {"NetPriceAmount": "12.50", "to_Item": {"results": []}, "Nav": ["a"]}
    evidence = extract_evidence(
        "odata_read", {"entity_set": "E"}, _ok(json.dumps(payload)), at=AT
    )
    assert evidence["fields"] == [{"name": "NetPriceAmount", "value": "12.50"}]


# ── sap_write ────────────────────────────────────────────────────────────────


def test_odata_update_is_a_write_with_op_update():
    evidence = extract_evidence(
        "odata_update",
        {
            "service_name": "API_SUPPLIERINVOICE_PROCESS_SRV",
            "entity_set": "A_SupplierInvoice",
            "identifier_fields": {
                "SupplierInvoice": "5105600000",
                "FiscalYear": "2026",
            },
            "payload": {"PaymentBlockingReason": ""},
        },
        _ok("{}"),
        at=AT,
    )
    assert evidence["kind"] == "sap_write"
    assert evidence["op"] == "update"
    assert evidence["source"]["key"] == "5105600000/2026"
    assert evidence["fields"] == [{"name": "PaymentBlockingReason", "value": ""}]


def test_odata_create_is_a_write_with_op_create():
    evidence = extract_evidence(
        "odata_create",
        {"service_name": "S", "entity_set": "E", "payload": {"A": "1"}},
        _ok("{}"),
        at=AT,
    )
    assert evidence["op"] == "create"
    assert evidence["fields"] == [{"name": "A", "value": "1"}]


def test_function_import_records_the_function_as_the_entity():
    # Post and Release change no field; they move a document's lifecycle, so the
    # function name is the thing worth recording.
    evidence = extract_evidence(
        "odata_function_import",
        {
            "service_name": "API_SUPPLIERINVOICE_PROCESS_SRV",
            "function_name": "Post",
            "parameters": {"SupplierInvoice": "5105600000", "FiscalYear": "2026"},
        },
        _ok("{}"),
        at=AT,
    )
    assert evidence["kind"] == "sap_write"
    assert evidence["op"] == "function_import"
    assert evidence["source"]["entity"] == "Post"
    assert evidence["source"]["key"] == "5105600000/2026"
    assert {"name": "SupplierInvoice", "value": "5105600000"} in evidence["fields"]


# ── sop_lookup ───────────────────────────────────────────────────────────────


def test_sop_lookup_extracts_numbered_clauses_in_order_without_duplicates():
    sop = (
        "STEP 1: GATHER DATA\n"
        "1.1  The agent MUST retrieve the invoice line items with\n"
        "     NetAmount and Quantity.\n"
        "1.2  The agent MUST retrieve the matching PO item.\n"
        "1.2  (restated)\n"
        "2.1  The agent MUST compute the price variance.\n"
    )
    evidence = extract_evidence(
        "search_sap_sops", {"query": "price variance"}, _ok(sop), at=AT
    )
    assert evidence["kind"] == "sop_lookup"
    assert evidence["clauses_retrieved"] == ["1.1", "1.2", "2.1"]


def test_sop_lookup_extracts_clauses_when_bedrock_collapses_the_newlines():
    """Retrieve returns each chunk on one line, which a `^`-anchored pattern misses.

    This is the production shape — the first real run recorded zero clauses on
    every SOP lookup while the SOPs themselves were numbered 1.1-5.3.
    """
    collapsed = (
        "STEP 4: EXECUTE RESOLUTION   "
        "4.1  The agent MUST park the invoice first.   "
        "4.2  The agent MUST update case state at each step."
    )
    evidence = extract_evidence(
        "search_sap_sops", {"query": "release"}, _ok(collapsed), at=AT
    )
    assert evidence["clauses_retrieved"] == ["4.1", "4.2"]


def test_sop_lookup_ignores_decimal_values_that_are_not_clauses():
    """The API-docs corpus is searched by the same tool and quotes amounts."""
    evidence = extract_evidence(
        "search_sap_api_docs",
        {"query": "purchase order net amount"},
        _ok("NetPriceAmount: 100.000   Currency: USD"),
        at=AT,
    )
    assert "clauses_retrieved" not in evidence


def test_sop_lookup_with_no_results_records_no_clauses():
    evidence = extract_evidence(
        "search_sap_sops", {"query": "x"}, _ok("No relevant results found."), at=AT
    )
    assert evidence["kind"] == "sop_lookup"
    assert "clauses_retrieved" not in evidence


# ── case_update, notification ────────────────────────────────────────────────


def test_update_case_state_is_a_case_update_carrying_the_transition():
    evidence = extract_evidence(
        "update_case_state",
        {
            "case_id": "4500000123-10",
            "updates": {"status": "complete"},
            "action": "resolve",
        },
        _ok("{}"),
        at=AT,
    )
    assert evidence["kind"] == "case_update"
    assert evidence["source"]["key"] == "4500000123-10"
    assert {"name": "status", "value": "complete"} in evidence["fields"]


def test_update_case_state_reads_the_json_string_its_tool_spec_declares():
    # The wire shape: case_management/tool_spec.json types `updates` as a string, so
    # passing a dict here (as the test above does) never happens in production —
    # _scalar_fields returned [] for it and every real case_update recorded no fields.
    evidence = extract_evidence(
        "update_case_state",
        {
            "case_id": "4500000123-10",
            "updates": '{"status": "complete", "exception_type": "PRICE"}',
            "action": "resolve",
        },
        _ok("{}"),
        at=AT,
    )
    assert {"name": "status", "value": "complete"} in evidence["fields"]
    assert {"name": "exception_type", "value": "PRICE"} in evidence["fields"]


def test_an_unparseable_updates_string_records_no_fields():
    evidence = extract_evidence(
        "update_case_state",
        {"case_id": "4500000123-10", "updates": "status=complete", "action": "resolve"},
        _ok("{}"),
        at=AT,
    )
    assert "fields" not in evidence
    assert evidence["source"]["key"] == "4500000123-10"


def test_send_notification_records_the_recipient():
    evidence = extract_evidence(
        "send_notification",
        {
            "recipient": "ap-team@example.com",
            "subject": "Price variance",
            "body": "...",
        },
        _ok("{}"),
        at=AT,
    )
    assert evidence["kind"] == "notification"
    assert {"name": "recipient", "value": "ap-team@example.com"} in evidence["fields"]


def test_a_notification_keeps_the_clause_the_agent_cited():
    # _platform_prompt tells the agent to cite the clause it acted on in the
    # notification body. Recording only the recipient dropped it on the floor.
    evidence = extract_evidence(
        "send_notification",
        {
            "recipient": "ap-team@example.com",
            "subject": "Price variance per §3.3",
            "body": "Escalating to the buyer per §3.3.",
        },
        _ok("{}"),
        at=AT,
    )
    values = [f["value"] for f in evidence["fields"]]
    assert "Price variance per §3.3" in values
    assert "Escalating to the buyer per §3.3." in values


def test_a_notification_body_is_capped_rather_than_stored_whole():
    evidence = extract_evidence(
        "send_notification",
        {"recipient": "a@b.c", "body": "x" * 900},
        _ok("{}"),
        at=AT,
    )
    body = next(f for f in evidence["fields"] if f["name"] == "body")
    assert len(body["value"]) == PROSE_MAX_CHARS


def test_a_notification_with_an_empty_body_records_no_field_for_it():
    # An absent field is a different claim than an empty one, and FieldList would
    # render a blank row for it.
    evidence = extract_evidence(
        "send_notification",
        {"recipient": "a@b.c", "subject": "   ", "body": ""},
        _ok("{}"),
        at=AT,
    )
    assert [f["name"] for f in evidence["fields"]] == ["recipient"]


def test_ticket_creation_is_the_escalation_channel():
    # proposed_write hangs off this segment, so the kind must be notification.
    evidence = extract_evidence(
        "demo_create_ticket",
        {
            "title": "Approve price variance",
            "description": "...",
            "assigned_to": "ap-lead",
        },
        _ok('{"ticket_id":"TKT-1"}'),
        at=AT,
    )
    assert evidence["kind"] == "notification"


def test_a_ticket_carrying_a_proposed_write_records_it():
    evidence = extract_evidence(
        "demo_create_ticket",
        {
            "title": "Approve price variance",
            "description": "...",
            "proposed_write": {
                "op": "update",
                "service": "API_PURCHASEORDER_PROCESS_SRV",
                "entity": "A_PurchaseOrderItem",
                "key": "4500000123/10",
                "fields": [
                    {"name": "NetPriceAmount", "current": "12.00", "proposed": "12.50"},
                    {"name": "PriceUnit", "proposed": "1"},
                ],
            },
        },
        _ok('{"ticket_id":"TKT-1"}'),
        at=AT,
    )
    assert evidence["proposed_write"] == {
        "op": "update",
        "service": "API_PURCHASEORDER_PROCESS_SRV",
        "entity": "A_PurchaseOrderItem",
        "key": "4500000123/10",
        "fields": [
            {"name": "NetPriceAmount", "proposed": "12.50", "current": "12.00"},
            {"name": "PriceUnit", "proposed": "1"},
        ],
    }


def test_a_proposed_write_field_list_is_bounded():
    proposal = {
        "op": "create",
        "fields": [{"name": f"F{i}", "proposed": str(i)} for i in range(40)],
    }
    evidence = extract_evidence(
        "demo_create_ticket",
        {"title": "t", "description": "d", "proposed_write": proposal},
        _ok("{}"),
        at=AT,
    )
    assert len(evidence["proposed_write"]["fields"]) == 12


def test_a_proposed_write_the_model_malformed_is_dropped():
    # An unusable proposal must be absent, not an empty object the console would
    # render as a diff of nothing.
    for proposal in (
        "update A_PurchaseOrderItem",  # prose where an object was asked for
        {"fields": [{"name": "A", "proposed": "1"}]},  # no op
        {
            "op": "delete",
            "fields": [{"name": "A", "proposed": "1"}],
        },  # not a write we do
        {"op": "update", "fields": []},
        {"op": "update", "fields": [{"proposed": "1"}]},  # no field name
    ):
        evidence = extract_evidence(
            "demo_create_ticket",
            {"title": "t", "description": "d", "proposed_write": proposal},
            _ok("{}"),
            at=AT,
        )
        assert "proposed_write" not in evidence, proposal


# ── computation and the fallthrough ──────────────────────────────────────────


def test_calculator_is_a_computation_with_its_input_and_result():
    evidence = extract_evidence(
        "calculator", {"expression": "(12.50-12.00)/12.00*100"}, _ok("4.1667"), at=AT
    )
    assert evidence["kind"] == "computation"
    assert {"name": "expression", "value": "(12.50-12.00)/12.00*100"} in evidence[
        "fields"
    ]
    assert {"name": "result", "value": "4.1667"} in evidence["fields"]


def test_a_local_tool_carries_no_authz_because_no_gateway_was_traversed():
    evidence = extract_evidence("calculator", {"expression": "1+1"}, _ok("2"), at=AT)
    assert "authz" not in evidence


def test_an_unknown_tool_falls_through_to_computation_with_no_source():
    evidence = extract_evidence("some_future_tool", {"a": 1}, _ok("done"), at=AT)
    assert evidence["kind"] == "computation"
    assert "source" not in evidence


def test_the_gateway_target_prefix_is_stripped_before_classifying():
    # _create_agent renames tools, but a direct-MCP call can still arrive prefixed.
    evidence = extract_evidence(
        "sap-target___odata_read",
        {"service_name": "S", "entity_set": "E"},
        _ok("{}"),
        at=AT,
    )
    assert evidence["kind"] == "sap_read"


def test_a_non_dict_input_does_not_crash_the_extractor():
    evidence = extract_evidence("odata_read", "not-a-dict", _ok("{}"), at=AT)
    assert evidence["kind"] == "sap_read"
    assert "source" not in evidence


# ── authz ────────────────────────────────────────────────────────────────────


def test_mode_defaults_to_log_only():
    evidence = extract_evidence("odata_read", {"entity_set": "E"}, _ok("{}"), at=AT)
    assert evidence["authz"]["mode"] == "LOG_ONLY"


def test_the_direct_obo_topology_reports_no_gateway_traversal():
    evidence = extract_evidence(
        "odata_read", {"entity_set": "E"}, _ok("{}"), at=AT, via_gateway=False
    )
    assert evidence["authz"]["via_gateway"] is False


def test_an_authorization_failure_is_reported_as_rejected():
    evidence = extract_evidence(
        "odata_read",
        {"entity_set": "E"},
        _err(
            "PermissionError: Missing Gateway tool context — direct invocation is not permitted"
        ),
        at=AT,
    )
    assert evidence["authz"]["outcome"] == "rejected"


def test_a_non_authorization_failure_states_no_outcome():
    # Claiming "rejected" for a timeout would render a transport fault as a Cedar
    # denial. The segment's own status: "error" already says the call failed.
    evidence = extract_evidence(
        "odata_read", {"entity_set": "E"}, _err("504 Gateway Timeout after 30s"), at=AT
    )
    assert "outcome" not in evidence["authz"]
    assert evidence["authz"]["via_gateway"] is True


# ── truncation ───────────────────────────────────────────────────────────────


def test_truncation_leaves_a_small_segment_untouched():
    segment = {
        "type": "tool",
        "tool_input": "{}",
        "tool_result": "ok",
        "evidence": {"kind": "sap_read"},
    }
    assert truncate_segment(segment)["tool_result"] == "ok"
    assert "truncated" not in segment["evidence"]


def test_a_result_at_the_budget_is_not_marked_truncated():
    segment = {
        "type": "tool",
        "tool_result": "x" * TOOL_RESULT_MAX_BYTES,
        "evidence": {"kind": "sap_read"},
    }
    truncate_segment(segment)
    assert len(segment["tool_result"].encode()) == TOOL_RESULT_MAX_BYTES
    assert "truncated" not in segment["evidence"]


def test_one_byte_over_the_budget_truncates_and_marks_it():
    segment = {
        "type": "tool",
        "tool_result": "x" * (TOOL_RESULT_MAX_BYTES + 1),
        "evidence": {"kind": "sap_read"},
    }
    truncate_segment(segment)
    assert len(segment["tool_result"].encode()) <= TOOL_RESULT_MAX_BYTES
    assert segment["evidence"]["truncated"] is True


def test_the_input_budget_is_tighter_than_the_result_budget():
    segment = {
        "type": "tool",
        "tool_input": "y" * (TOOL_INPUT_MAX_BYTES + 1),
        "evidence": {"kind": "sap_read"},
    }
    truncate_segment(segment)
    assert len(segment["tool_input"].encode()) <= TOOL_INPUT_MAX_BYTES
    assert segment["evidence"]["truncated"] is True


def test_truncation_never_splits_a_multibyte_character():
    segment = {
        "type": "tool",
        "tool_result": "é" * TOOL_RESULT_MAX_BYTES,
        "evidence": {"kind": "sap_read"},
    }
    truncate_segment(segment)
    segment["tool_result"].encode("utf-8")  # would raise if a surrogate survived
    assert len(segment["tool_result"].encode()) <= TOOL_RESULT_MAX_BYTES


def test_truncation_works_on_a_segment_with_no_evidence():
    # Text segments and pre-migration tool segments both hit this path.
    segment = {"type": "text", "content": "hello"}
    assert truncate_segment(segment) == {"type": "text", "content": "hello"}


def test_an_oversized_result_on_a_segment_without_evidence_still_truncates():
    segment = {"type": "tool", "tool_result": "x" * 5000}
    truncate_segment(segment)
    assert len(segment["tool_result"].encode()) <= TOOL_RESULT_MAX_BYTES


# ── the trace cap ────────────────────────────────────────────────────────────


def test_under_the_cap_nothing_is_dropped():
    traces = [{"trace_id": str(i)} for i in range(MAX_TRACES)]
    kept, dropped = cap_traces(traces)
    assert dropped == 0
    assert kept == traces


def test_over_the_cap_the_oldest_go_first():
    traces = [{"trace_id": str(i)} for i in range(MAX_TRACES + 3)]
    kept, dropped = cap_traces(traces)
    assert dropped == 3
    assert len(kept) == MAX_TRACES
    assert kept[0]["trace_id"] == "3"
    assert kept[-1]["trace_id"] == str(MAX_TRACES + 2)


def test_the_cap_is_configurable_for_the_test_and_the_caller():
    kept, dropped = cap_traces([{"trace_id": str(i)} for i in range(5)], max_traces=2)
    assert dropped == 3
    assert [t["trace_id"] for t in kept] == ["3", "4"]


def test_the_cap_tolerates_a_missing_list():
    assert cap_traces(None) == ([], 0)
    assert cap_traces([]) == ([], 0)
