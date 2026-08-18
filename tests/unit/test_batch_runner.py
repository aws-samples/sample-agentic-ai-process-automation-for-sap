# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""The batch sweeper's guards: what it refuses to enqueue, and what it survives.

The sweeper's whole job is to enqueue cases the poller missed, so the risk is the
opposite failure — enqueueing something twice, or enqueueing at all when a human
is supposed to be driving. Those two guards (the age floor and the trigger-mode
switch) are pinned here, along with the batch envelope the invoker consumes.
"""

import importlib.util
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUNNER = _REPO_ROOT / "lambdas" / "batch_runner" / "index.py"


class _Table:
    """A query() that records its kwargs and replays canned pages."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def query(self, **kwargs):
        self.calls.append(kwargs)
        return self.pages.pop(0) if self.pages else {"Items": []}


def load(env=None, pages=None):
    """Import the handler with stubbed AWS clients. Returns (module, table, sqs).

    The module reads its env into constants at import time, so each test imports a
    fresh copy under a throwaway module name rather than reloading a shared one.
    """
    base = {
        "STACK_NAME_BASE": "test-stack",
        "CASES_TABLE": "cases",
        "AGENT_QUEUE_URL": "https://sqs.example/q.fifo",
        "AWS_REGION": "us-east-1",
    }
    base.update(env or {})
    table = _Table(pages if pages is not None else [{"Items": []}])
    with (
        mock.patch.dict(os.environ, base, clear=False),
        mock.patch("boto3.client"),
        mock.patch("boto3.resource") as resource,
    ):
        resource.return_value.Table.return_value = table
        spec = importlib.util.spec_from_file_location(
            "batch_runner_under_test", _RUNNER
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    # ssm and sqs come from separate boto3.client() calls but are the same Mock
    # here; the tests only assert on send_message, so the aliasing is harmless.
    module.ssm.get_parameter.return_value = {"Parameter": {"Value": "auto"}}
    return module, table, module.sqs


def _case(case_id="INV-1", created_at="2020-01-01T00:00:00+00:00", **extra):
    return {
        "case_id": case_id,
        "domain": "finance",
        "process_type": "invoice_matching",
        "created_at": created_at,
        **extra,
    }


def test_manual_trigger_mode_enqueues_nothing():
    # The autonomy switch governs every unattended enqueue path. If a human is
    # driving, a sweeper that enqueues anyway would resurrect work they parked.
    module, _table, sqs = load(pages=[{"Items": [_case()]}])
    module.ssm.get_parameter.return_value = {"Parameter": {"Value": "manual"}}
    assert module.handler({}, None) == {"swept": 0, "enqueued": 0, "skipped": "manual"}
    sqs.send_message.assert_not_called()


def test_unreadable_trigger_mode_fails_closed_to_manual():
    module, _table, sqs = load(pages=[{"Items": [_case()]}])
    module.ssm.get_parameter.side_effect = Exception("no such parameter")
    assert module.handler({}, None)["skipped"] == "manual"
    sqs.send_message.assert_not_called()


def test_missing_queue_is_a_no_op_not_a_crash():
    # Provisioned only alongside the autonomous pipeline, but a direct invoke
    # with no queue must report rather than raise.
    module, _table, sqs = load(env={"AGENT_QUEUE_URL": ""})
    assert module.handler({}, None) == {
        "swept": 0,
        "enqueued": 0,
        "skipped": "no-queue",
    }
    sqs.send_message.assert_not_called()


def test_age_floor_stays_above_the_poller_schedule():
    # This floor IS the double-invocation guard: content-based SQS dedup cannot
    # help because the batch body differs from the poller's (trigger field). A
    # floor at or below the 5-minute poller rate would race a fresh enqueue.
    module, _table, _sqs = load()
    assert module.MIN_AGE_MINUTES > 5


def test_the_cutoff_is_the_age_floor_in_the_past():
    module, table, _sqs = load()
    before = datetime.now(timezone.utc)
    module.handler({}, None)
    cutoff = datetime.fromisoformat(
        table.calls[0]["ExpressionAttributeValues"][":cutoff"]
    )
    # Only cases older than the floor are swept, so the cutoff trails "now".
    assert cutoff <= before - timedelta(minutes=module.MIN_AGE_MINUTES - 1)
    assert table.calls[0]["FilterExpression"] == "created_at <= :cutoff"


def test_only_detected_cases_are_swept():
    # A case already handed to the agent must never be re-enqueued.
    module, table, _sqs = load()
    module.handler({}, None)
    assert table.calls[0]["IndexName"] == "status-index"
    key, value = table.calls[0]["KeyConditionExpression"].get_expression()["values"]
    assert (key.name, value) == ("status", "detected")


def test_the_envelope_carries_the_batch_trigger():
    # `trigger: batch` is in the Trigger enum (types/cases.schema.json) so the
    # invoker's validate_or_log does not flag these traces.
    module, _table, sqs = load(pages=[{"Items": [_case("INV-9")]}])
    assert module.handler({}, None) == {"swept": 1, "enqueued": 1}
    body = json.loads(sqs.send_message.call_args.kwargs["MessageBody"])
    assert body["trigger"] == "batch"
    assert body["case_id"] == "INV-9"
    # FIFO ordering is per case, so one case's retries cannot block another's.
    assert sqs.send_message.call_args.kwargs["MessageGroupId"] == "INV-9"


def test_an_unusable_case_id_is_skipped_not_raised():
    module, _table, sqs = load(pages=[{"Items": [_case(case_id=None)]}])
    assert module.handler({}, None) == {"swept": 1, "enqueued": 0}
    sqs.send_message.assert_not_called()


def test_one_failed_enqueue_does_not_abandon_the_backlog():
    module, _table, sqs = load(
        pages=[{"Items": [_case("INV-1"), _case("INV-2"), _case("INV-3")]}]
    )
    sqs.send_message.side_effect = [Exception("throttled"), None, None]
    assert module.handler({}, None) == {"swept": 3, "enqueued": 2}


def test_the_sweep_is_capped_and_stops_paginating():
    # An unbounded sweep could bury the queue; the next schedule takes the rest.
    module, table, sqs = load(
        env={"BATCH_MAX_CASES": "2"},
        pages=[
            {
                "Items": [_case("INV-1"), _case("INV-2")],
                "LastEvaluatedKey": {"case_id": "INV-2"},
            },
            {"Items": [_case("INV-3")]},
        ],
    )
    assert module.handler({}, None) == {"swept": 2, "enqueued": 2}
    assert len(table.calls) == 1  # cap reached, so no second page fetched
    assert sqs.send_message.call_count == 2


def test_the_cap_truncates_an_oversized_page():
    # DynamoDB returns whole pages, so a single page can overshoot the cap. The
    # pagination break alone does not enforce it — the truncation does.
    module, _table, sqs = load(
        env={"BATCH_MAX_CASES": "2"},
        pages=[{"Items": [_case("INV-1"), _case("INV-2"), _case("INV-3")]}],
    )
    assert module.handler({}, None) == {"swept": 2, "enqueued": 2}
    assert sqs.send_message.call_count == 2


def test_pagination_continues_until_the_cap_is_reached():
    module, table, _sqs = load(
        env={"BATCH_MAX_CASES": "10"},
        pages=[
            {"Items": [_case("INV-1")], "LastEvaluatedKey": {"case_id": "INV-1"}},
            {"Items": [_case("INV-2")]},
        ],
    )
    assert module.handler({}, None)["swept"] == 2
    assert len(table.calls) == 2
    assert table.calls[1]["ExclusiveStartKey"] == {"case_id": "INV-1"}
