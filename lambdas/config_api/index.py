# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Runtime config API — GET/PUT for the contacts and tolerance constants SOPs cite.

Every value here is substituted into a SOP before the agent reads it, so a bad
write is an instruction defect: a mistyped contact makes the agent notify a
literal placeholder, and a fat-fingered tolerance changes which invoices
auto-post. Writes are allowlisted by symbol and range-checked, and a request
carrying any invalid field is rejected whole rather than written in part.

The deploy-time values stay authoritative as defaults (CONTACTS_JSON /
CONSTANTS_JSON, rendered by CDK from cdk/config.yaml and skills/*/config.json).
The table holds only overrides, so a fresh deploy with zero rows behaves exactly
as it did before this API existed.
"""

import json
import os
import re
from datetime import datetime, timezone
from decimal import Decimal

import boto3

table = boto3.resource("dynamodb").Table(os.environ["CONFIG_TABLE"])

CONTACT_NS = "contact"
CONSTANT_NS_PREFIX = "constant#"

# Contacts are notification targets, so a value that is not an address is a
# defect the agent cannot recover from. Deliberately loose on the local part and
# strict on the shape — this rejects typos, it is not an RFC 5322 parser.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")
_MAX_VALUE_LEN = 254

# Bounds by symbol suffix, covering every constant the shipped skills declare.
# A percentage over 100 or a negative tolerance is not a preference, it is a
# broken predicate. Symbols with no recognised suffix take the conservative
# fallback rather than going unchecked.
_BOUNDS_BY_SUFFIX = {
    "_PCT": (0, 100),
    "_DAYS": (0, 365),
}
_BOUNDS_FALLBACK = (0, 1_000_000_000)


def _bounds(symbol: str) -> tuple[float, float]:
    for suffix, limits in _BOUNDS_BY_SUFFIX.items():
        if symbol.endswith(suffix):
            return limits
    return _BOUNDS_FALLBACK


def _defaults() -> tuple[dict, dict]:
    """(contacts, {skill_id: {SYMBOL: value}}) as declared at deploy time."""
    return (
        json.loads(os.environ.get("CONTACTS_JSON", "{}")),
        json.loads(os.environ.get("CONSTANTS_JSON", "{}")),
    )


def _overrides() -> list[dict]:
    """Every override row. Small by construction — one row per edited symbol."""
    items, kwargs = [], {}
    while True:
        page = table.scan(**kwargs)
        items.extend(page.get("Items", []))
        key = page.get("LastEvaluatedKey")
        if not key:
            return items
        kwargs["ExclusiveStartKey"] = key


def _json_default(obj):
    if isinstance(obj, Decimal):
        return int(obj) if obj == int(obj) else float(obj)
    raise TypeError(f"Not JSON serializable: {type(obj).__name__}")


def _actor(event: dict) -> str:
    """Identity from the trusted authorizer context, never from the body."""
    authorizer = (event.get("requestContext") or {}).get("authorizer") or {}
    claims = authorizer.get("claims") or authorizer
    for key in (
        "email",
        "preferred_username",
        "cognito:username",
        "sub",
        "principalId",
    ):
        value = claims.get(key)
        if value:
            return str(value).strip()[:256]
    return "unknown"


def _validate_contact(key: str, value, allowed: dict) -> str | None:
    if key not in allowed:
        return f"Unknown contact {key!r}. Known: {sorted(allowed)}"
    if not isinstance(value, str) or not _EMAIL_RE.match(value.strip()):
        return f"Contact {key!r} must be an email address"
    if len(value.strip()) > _MAX_VALUE_LEN:
        return f"Contact {key!r} exceeds {_MAX_VALUE_LEN} characters"
    return None


def _validate_constant(skill: str, symbol: str, value, allowed: dict) -> str | None:
    if skill not in allowed:
        return f"Unknown skill {skill!r}. Known: {sorted(allowed)}"
    if symbol not in allowed[skill]:
        return f"Unknown constant {symbol!r} for {skill!r}. Known: {sorted(allowed[skill])}"
    # bool is an int subclass, and `True` would silently store as 1 in a
    # threshold the SOP compares numerically.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return f"Constant {symbol!r} must be a number"
    low, high = _bounds(symbol)
    if not low <= value <= high:
        return f"Constant {symbol!r} must be between {low} and {high}"
    return None


def _plan_writes(body: dict, contacts: dict, constants: dict) -> tuple[list, list]:
    """Return (writes, errors). A write is (namespace, key, value-or-None).

    Collects every error rather than failing on the first: an operator editing a
    form wants all of it back, not one field at a time.
    """
    writes, errors = [], []

    for key, value in (body.get("contacts") or {}).items():
        if value is None:
            writes.append((CONTACT_NS, key, None))
            continue
        error = _validate_contact(key, value, contacts)
        if error:
            errors.append(error)
        else:
            writes.append((CONTACT_NS, key, value.strip()))

    for skill, symbols in (body.get("constants") or {}).items():
        if not isinstance(symbols, dict):
            errors.append(f"constants[{skill!r}] must be an object")
            continue
        for symbol, value in symbols.items():
            if value is None:
                writes.append((CONSTANT_NS_PREFIX + skill, symbol, None))
                continue
            error = _validate_constant(skill, symbol, value, constants)
            if error:
                errors.append(error)
            else:
                writes.append((CONSTANT_NS_PREFIX + skill, symbol, value))

    return writes, errors


def handler(event, context):
    method = event.get("httpMethod", "GET")
    contacts, constants = _defaults()

    if method == "GET":
        # Defaults and overrides are returned separately, not pre-merged: the UI
        # has to be able to say "this differs from what was deployed", and a
        # merged map cannot. `bounds` ships too so the form cannot offer a value
        # this handler would reject.
        overrides = {"contacts": {}, "constants": {}}
        for item in _overrides():
            ns, key = item["namespace"], item["config_key"]
            if ns == CONTACT_NS:
                overrides["contacts"][key] = item["value"]
            elif ns.startswith(CONSTANT_NS_PREFIX):
                skill = ns[len(CONSTANT_NS_PREFIX) :]
                overrides["constants"].setdefault(skill, {})[key] = item["value"]
        return _resp(
            200,
            {
                "defaults": {"contacts": contacts, "constants": constants},
                "overrides": overrides,
                "bounds": {
                    symbol: _bounds(symbol)
                    for symbols in constants.values()
                    for symbol in symbols
                },
            },
        )

    if method == "PUT":
        try:
            body = json.loads(event.get("body") or "{}")
        except json.JSONDecodeError:
            return _resp(400, {"error": "Body is not valid JSON"})
        if not isinstance(body, dict):
            return _resp(400, {"error": "Body must be a JSON object"})

        writes, errors = _plan_writes(body, contacts, constants)
        # All-or-nothing. A partially applied edit leaves the corpus in a state
        # no operator chose and no default describes.
        if errors:
            return _resp(400, {"error": "Invalid fields", "details": errors})
        if not writes:
            return _resp(400, {"error": "No valid fields provided"})

        actor, now = _actor(event), datetime.now(timezone.utc).isoformat()
        for namespace, key, value in writes:
            if value is None:
                table.delete_item(Key={"namespace": namespace, "config_key": key})
                continue
            table.put_item(
                Item={
                    "namespace": namespace,
                    "config_key": key,
                    # DynamoDB has no float type; Decimal via str keeps 0.50 exact.
                    "value": Decimal(str(value)) if isinstance(value, float) else value,
                    "updated_by": actor,
                    "updated_at": now,
                }
            )
        return _resp(200, {"updated": len(writes), "updated_by": actor})

    return _resp(405, {"error": "Method not allowed"})


def _resp(code, body):
    return {
        "statusCode": code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=_json_default),
    }
