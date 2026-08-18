# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Resolves the {{CONTACT_*}} / {{SYMBOL}} values SOPs cite, and the operator
overrides that win over the deployed defaults.

Both substitution paths live here — the agent's skill_router (prompt assembly)
and the `load_sop` Gateway tool (mid-case reload). If they held separate copies
of either the override read or the placeholder rules, the prompt could state one
tolerance and the reloaded SOP another, which is the exact drift SOP_INDEX_JSON
exists to prevent. Neither artifact can import the other, so this file is
mirrored byte-for-byte and tests/unit/test_config_overrides.py is what holds the
copies together.

Overrides layer over the deploy-time defaults; an absent table, an empty table,
or a failed read all mean "no overrides", so a fresh deploy and a throttled read
both resolve the deployed value rather than blanking a threshold.
"""

import logging
import os
import re

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger(__name__)

_CONTACT_NS = "contact"
_CONSTANT_NS_PREFIX = "constant#"

# One pattern for both symbol families: a contact placeholder is just a symbol
# whose name starts with CONTACT_. Two patterns drifted once — the narrower one
# excluded digits, so {{CONTACT_TIER1_OWNER}} resolved on the load_sop path and
# reached the model verbatim in the injected prompt.
_PLACEHOLDER_RE = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")

_table = None


def _get_table():
    """None when CONFIG_TABLE is unset — local dev and pre-P3 deployments."""
    global _table
    if _table is None:
        name = os.environ.get("CONFIG_TABLE")
        if not name:
            return None
        _table = boto3.resource("dynamodb").Table(name)
    return _table


def _query(namespace: str) -> dict:
    """{config_key: value} for one namespace, or {} if anything goes wrong.

    Deliberately not cached: an operator who saves a tolerance expects the next
    case to use it, and the agent container outlives any sane TTL. One Query per
    case resolution is cheaper than a config edit that appears to do nothing.
    """
    table = _get_table()
    if table is None:
        return {}
    try:
        items = table.query(KeyConditionExpression=Key("namespace").eq(namespace)).get(
            "Items", []
        )
    except Exception as e:
        # Falling back to the deployed default is the safe direction: the SOP
        # still names a real threshold, just not the edited one.
        logger.warning(f"Config override read failed for {namespace!r}: {e}")
        return {}
    return {i["config_key"]: i["value"] for i in items if "value" in i}


def contact_overrides() -> dict:
    """{CONTACT_<KEY>: address} — keyed to match the placeholder, not the config."""
    return {f"CONTACT_{k.upper()}": v for k, v in _query(_CONTACT_NS).items()}


def constant_overrides(skill_id: str) -> dict:
    """{SYMBOL: value} for one skill. Values are Decimal from DynamoDB; str()
    renders them the same as the JSON ints/floats they came from."""
    if not skill_id:
        return {}
    return _query(_CONSTANT_NS_PREFIX + skill_id)


def substitute(text: str, contacts: dict, constants: dict, skill_id: str = "") -> str:
    """Resolve every {{SYMBOL}} in `text`, operator overrides winning.

    Args:
        text: SOP or prompt text.
        contacts: deploy-time directory, already keyed `CONTACT_<KEY>`.
        constants: the owning skill's declared `constants` block.
        skill_id: whose constant namespace to read overrides from. Empty means
            contacts only — the KB search path has no owning skill.

    A symbol neither map declares is left verbatim: a silently-blank threshold
    would have the agent compare against nothing and report the comparison as
    done, where a visible `{{...}}` is an obvious defect.
    """
    contacts = {**contacts, **contact_overrides()}
    # Keyed on the declared symbols only: an override for a symbol this skill
    # never declared cannot introduce one, and /config rejects writing it anyway.
    overrides = constant_overrides(skill_id)
    constants = {**constants, **{k: v for k, v in overrides.items() if k in constants}}

    def _replace(match):
        symbol = match.group(1)
        if symbol in contacts:
            return str(contacts[symbol])
        if symbol in constants:
            return str(constants[symbol])
        return match.group(0)

    return _PLACEHOLDER_RE.sub(_replace, text)
