# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""`/config` — the write path for the values SOPs cite.

This API is a trust boundary: every value it stores is substituted into a SOP
before the agent reads it, so an unchecked write is an instruction defect rather
than a bad row. A tolerance of 500% silently auto-posts every invoice; a contact
that is not an address makes the agent notify a literal string. The tests below
pin the checks that stop that, plus the two seams the overrides model rests on —
a partially-applied edit must be impossible, and a missing symbol must fall back
to the deployed default rather than to nothing.
"""

import importlib
import json
import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent

_CONTACTS = {"ap_team": "ap@example.com", "procurement": "buy@example.com"}
_CONSTANTS = {
    "finance_ap": {
        "QTY_VARIANCE_PCT": 5,
        "PRICE_VARIANCE_ABS_USD": 0.5,
        "MISSING_GR_ESCALATION_DAYS": 5,
    }
}


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("CONFIG_TABLE", "cfg-table")
    monkeypatch.setenv("CONTACTS_JSON", json.dumps(_CONTACTS))
    monkeypatch.setenv("CONSTANTS_JSON", json.dumps(_CONSTANTS))
    sys.path.insert(0, str(_ROOT / "lambdas" / "config_api"))
    with patch("boto3.resource"):
        import index as mod

        importlib.reload(mod)
    mod.table = MagicMock()
    mod.table.scan.return_value = {"Items": []}
    return mod


def _put(api, body, actor="ops@example.com"):
    return api.handler(
        {
            "httpMethod": "PUT",
            "body": json.dumps(body),
            "requestContext": {"authorizer": {"claims": {"email": actor}}},
        },
        None,
    )


def _body(resp):
    return json.loads(resp["body"])


def test_get_separates_deployed_defaults_from_operator_overrides(api):
    api.table.scan.return_value = {
        "Items": [
            {"namespace": "contact", "config_key": "ap_team", "value": "new@x.com"},
            {
                "namespace": "constant#finance_ap",
                "config_key": "QTY_VARIANCE_PCT",
                "value": Decimal("7"),
            },
        ]
    }
    body = _body(api.handler({"httpMethod": "GET"}, None))
    # Merging the two would destroy the UI's ability to say "this differs from
    # what was deployed", which is the only way an operator sees their own edits.
    assert body["defaults"]["contacts"]["ap_team"] == "ap@example.com"
    assert body["overrides"]["contacts"]["ap_team"] == "new@x.com"
    assert body["overrides"]["constants"]["finance_ap"]["QTY_VARIANCE_PCT"] == 7


def test_get_on_a_fresh_deploy_reports_no_overrides(api):
    body = _body(api.handler({"httpMethod": "GET"}, None))
    assert body["overrides"] == {"contacts": {}, "constants": {}}
    assert body["defaults"]["constants"] == _CONSTANTS


def test_bounds_ship_with_the_defaults_so_the_form_cannot_offer_a_rejected_value(api):
    bounds = _body(api.handler({"httpMethod": "GET"}, None))["bounds"]
    assert bounds["QTY_VARIANCE_PCT"] == [0, 100]
    assert bounds["MISSING_GR_ESCALATION_DAYS"] == [0, 365]
    # No suffix rule matches — the conservative fallback applies rather than
    # leaving the symbol unchecked.
    assert bounds["PRICE_VARIANCE_ABS_USD"][0] == 0


def test_a_symbol_no_skill_declares_is_refused(api):
    resp = _put(api, {"constants": {"finance_ap": {"MADE_UP_LIMIT": 1}}})
    assert resp["statusCode"] == 400
    api.table.put_item.assert_not_called()


def test_an_unknown_skill_is_refused(api):
    resp = _put(api, {"constants": {"not_a_skill": {"QTY_VARIANCE_PCT": 5}}})
    assert resp["statusCode"] == 400
    api.table.put_item.assert_not_called()


@pytest.mark.parametrize("value", [101, -1, "5", True, [5], {"v": 5}])
def test_out_of_range_and_non_numeric_tolerances_are_refused(api, value):
    resp = _put(api, {"constants": {"finance_ap": {"QTY_VARIANCE_PCT": value}}})
    assert resp["statusCode"] == 400, f"{value!r} was accepted"
    api.table.put_item.assert_not_called()


def test_a_contact_that_is_not_an_address_is_refused(api):
    resp = _put(api, {"contacts": {"ap_team": "not-an-email"}})
    assert resp["statusCode"] == 400
    api.table.put_item.assert_not_called()


def test_an_undeclared_contact_is_refused(api):
    resp = _put(api, {"contacts": {"cfo": "cfo@example.com"}})
    assert resp["statusCode"] == 400
    api.table.put_item.assert_not_called()


def test_one_invalid_field_rejects_the_whole_request(api):
    # The all-or-nothing rule. A partial apply would leave the corpus in a state
    # no operator chose and no default describes — half the form saved, half not,
    # with a 200 that says it worked.
    resp = _put(
        api,
        {
            "contacts": {"ap_team": "good@example.com"},
            "constants": {"finance_ap": {"QTY_VARIANCE_PCT": 999}},
        },
    )
    assert resp["statusCode"] == 400
    api.table.put_item.assert_not_called()


def test_every_error_comes_back_at_once(api):
    resp = _put(
        api,
        {
            "contacts": {"ap_team": "bad", "cfo": "cfo@example.com"},
            "constants": {"finance_ap": {"QTY_VARIANCE_PCT": 999}},
        },
    )
    assert len(_body(resp)["details"]) == 3


def test_a_valid_edit_is_stored_with_the_authenticated_actor(api):
    resp = _put(api, {"contacts": {"ap_team": "  new@example.com  "}})
    assert resp["statusCode"] == 200
    item = api.table.put_item.call_args.kwargs["Item"]
    assert item == {
        "namespace": "contact",
        "config_key": "ap_team",
        "value": "new@example.com",
        "updated_by": "ops@example.com",
        "updated_at": item["updated_at"],
    }


def test_the_actor_cannot_be_asserted_from_the_body(api):
    # Attribution is the only audit trail on a write that changes agent behaviour.
    resp = api.handler(
        {
            "httpMethod": "PUT",
            "body": json.dumps(
                {"updated_by": "someone-else", "contacts": {"ap_team": "a@b.com"}}
            ),
            "requestContext": {"authorizer": {"claims": {"email": "real@example.com"}}},
        },
        None,
    )
    assert _body(resp)["updated_by"] == "real@example.com"
    assert (
        api.table.put_item.call_args.kwargs["Item"]["updated_by"] == "real@example.com"
    )


def test_a_float_tolerance_survives_the_round_trip_exactly(api):
    _put(api, {"constants": {"finance_ap": {"PRICE_VARIANCE_ABS_USD": 0.75}}})
    stored = api.table.put_item.call_args.kwargs["Item"]["value"]
    # Decimal(str(x)), not Decimal(x): the float constructor stores
    # 0.750000000000000055511151231257827 and DynamoDB rejects it outright.
    assert stored == Decimal("0.75")
    assert str(stored) == "0.75"


def test_null_deletes_the_override_rather_than_storing_a_blank(api):
    # Reverting to the deployed default has to be expressible, and a stored empty
    # string would substitute a blank threshold into the SOP.
    resp = _put(api, {"constants": {"finance_ap": {"QTY_VARIANCE_PCT": None}}})
    assert resp["statusCode"] == 200
    api.table.put_item.assert_not_called()
    assert api.table.delete_item.call_args.kwargs["Key"] == {
        "namespace": "constant#finance_ap",
        "config_key": "QTY_VARIANCE_PCT",
    }


def test_an_empty_edit_is_rejected_not_reported_as_saved(api):
    assert _put(api, {})["statusCode"] == 400


def test_malformed_json_is_rejected(api):
    resp = api.handler({"httpMethod": "PUT", "body": "{ not json"}, None)
    assert resp["statusCode"] == 400


def test_delete_and_other_methods_are_not_allowed(api):
    assert api.handler({"httpMethod": "DELETE"}, None)["statusCode"] == 405


def test_the_allowlist_is_derived_from_the_skill_configs_not_hand_written():
    # The Lambda validates against CONSTANTS_JSON. If CDK ever stopped deriving
    # it from sopIndex, the allowlist and the SOPs' actual symbols would drift
    # apart and an operator could write a symbol nothing reads.
    stack = (_ROOT / "cdk" / "lib" / "backend-stack.ts").read_text(encoding="utf-8")
    assert "CONSTANTS_JSON: JSON.stringify(this.skillConstants(config))" in stack
    assert "Object.entries(this.sopIndex(config))" in stack


def test_every_shipped_constant_falls_under_a_bounds_rule(api):
    # A symbol with no rule would be stored unchecked. The fallback covers that,
    # but a negative or absurd value must still be impossible.
    config = json.loads(
        (_ROOT / "skills" / "finance_ap" / "config.json").read_text(encoding="utf-8")
    )
    assert config["constants"], "finance_ap declares no constants — test is vacuous"
    for symbol in config["constants"]:
        low, high = api._bounds(symbol)
        assert low == 0 and high > 0, f"{symbol} has no usable bounds"
