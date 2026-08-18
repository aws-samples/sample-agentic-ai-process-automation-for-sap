# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Coverage for polling_engine branches the shipped finance_ap.json never exercises.

finance_ap.json only uses cast "sap_date"/"abs_decimal", skip_when op "blank", and
process_type "default" — so a regression in "float"/"decimal2" casts, the other
skip ops (including nested "and"), or conditional process_type "rules" would ship
silently until some future domain config needed that branch. See
docs/extending/ADDING_USE_CASES.md "Domain Config Reference" for the contract.
"""

import sys
from decimal import Decimal
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "lambdas" / "layers" / "shared_types"))
sys.path.insert(0, str(_ROOT / "lambdas" / "odata_poller"))

import polling_engine as pe  # noqa: E402

# ---------------------------------------------------------------------------
# _cast
# ---------------------------------------------------------------------------


def test_cast_float():
    assert pe._cast("12.5", "float") == 12.5
    assert isinstance(pe._cast("12.5", "float"), float)


def test_cast_float_defaults_falsy_to_zero():
    assert pe._cast(None, "float") == 0.0
    assert pe._cast("", "float") == 0.0


def test_cast_decimal2_rounds_to_two_places():
    assert pe._cast("12.345", "decimal2") == Decimal("12.35")
    assert isinstance(pe._cast("12.345", "decimal2"), Decimal)


def test_cast_decimal2_uses_round_half_to_even_via_float():
    # Cast goes through round(float(...), 2) before Decimal(str(...)) — banker's
    # rounding on the float, not Decimal's own rounding. 10.005 isn't exactly
    # representable in binary float (it's ~10.00499999999999...), so it rounds
    # down, not up per naive "round half away from zero" expectations.
    assert pe._cast("10.005", "decimal2") == Decimal("10.01")
    assert pe._cast("2.675", "decimal2") == Decimal("2.67")


# ---------------------------------------------------------------------------
# _eval_skip
# ---------------------------------------------------------------------------


def test_eval_skip_empty_true_for_missing_or_empty_list():
    assert pe._eval_skip({"field": "x", "op": "empty"}, None, {"x": []}) is True
    assert pe._eval_skip({"field": "x", "op": "empty"}, None, {}) is True


def test_eval_skip_empty_false_for_nonempty_value():
    assert pe._eval_skip({"field": "x", "op": "empty"}, None, {"x": [1]}) is False
    assert pe._eval_skip({"field": "x", "op": "empty"}, None, {"x": "val"}) is False


def test_eval_skip_present_true_when_field_has_content():
    assert pe._eval_skip({"field": "x", "op": "present"}, None, {"x": "val"}) is True


def test_eval_skip_present_false_when_blank():
    assert pe._eval_skip({"field": "x", "op": "present"}, None, {"x": ""}) is False


def test_eval_skip_lte_true_at_and_below_threshold():
    cond = {"field": "x", "op": "lte", "value": 5}
    assert pe._eval_skip(cond, None, {"x": 5}) is True
    assert pe._eval_skip(cond, None, {"x": 4.9}) is True


def test_eval_skip_lte_false_above_threshold():
    cond = {"field": "x", "op": "lte", "value": 5}
    assert pe._eval_skip(cond, None, {"x": 5.01}) is False


def test_eval_skip_lte_non_numeric_defaults_to_skip():
    # Unparseable value → except branch returns True, i.e. skip-on-error.
    cond = {"field": "x", "op": "lte", "value": 5}
    assert pe._eval_skip(cond, None, {"x": "not-a-number"}) is True


def test_eval_skip_and_true_only_when_every_sub_condition_matches():
    cond = {
        "op": "and",
        "conditions": [
            {"field": "a", "op": "blank"},
            {"field": "b", "op": "blank"},
        ],
    }
    assert pe._eval_skip(cond, None, {"a": "", "b": ""}) is True
    assert pe._eval_skip(cond, None, {"a": "x", "b": ""}) is False


# ---------------------------------------------------------------------------
# _resolve_process_type
# ---------------------------------------------------------------------------


def test_resolve_process_type_first_matching_rule_wins():
    cfg = {
        "process_type": {
            "rules": [
                {"when": {"field": "flag", "op": "present"}, "then": "special"},
            ],
            "default": "normal",
        }
    }
    assert pe._resolve_process_type(cfg, None, {"flag": "Y"}) == "special"


def test_resolve_process_type_falls_back_to_default_when_no_rule_matches():
    cfg = {
        "process_type": {
            "rules": [
                {"when": {"field": "flag", "op": "present"}, "then": "special"},
            ],
            "default": "normal",
        }
    }
    assert pe._resolve_process_type(cfg, None, {"flag": ""}) == "normal"
