# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Config-driven OData polling engine.

Reads domain JSON configs from domains/ and executes the common
fetch → iterate → skip → map → dedupe → create → enqueue pipeline.
"""

import ast
import glob
import json
import operator
import os
import re
from datetime import datetime
from decimal import Decimal

import requests

# Canonical case identity codec — ships in the shared_types layer alongside the
# models. Imported unconditionally: a case cannot be created without an id.
from case_key import CaseKeyError, format_case_id

# WorkItem model + validator ship in the shared_types Lambda layer. Import is
# best-effort: the layer (and pydantic) aren't present in local dev/test, where
# validation simply no-ops. In the deployed Lambda both are on the path.
try:
    from generated_cases import WorkItem
    from validate import validate_or_log
except ImportError:
    WorkItem = None

    def validate_or_log(model, data, *, context=""):
        return data


_DOMAINS_DIR = os.path.join(os.path.dirname(__file__), "domains")
_INITIAL_STATUS = "detected"  # Must be in CaseStatus enum (types/cases.schema.json)
# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def load_domain_configs() -> list[dict]:
    """Load all *.json files from the domains/ directory, validate against schema.

    Demo gate: example_*.json domains drive polling for the demo skills. They are
    skipped unless DEMO_ENABLED=true, so a production poller doesn't scan SAP for
    demo exception types.
    """
    demo_enabled = os.environ.get("DEMO_ENABLED", "false").lower() == "true"
    configs = []
    for path in sorted(glob.glob(os.path.join(_DOMAINS_DIR, "*.json"))):
        if not demo_enabled and os.path.basename(path).startswith("example_"):
            continue
        with open(path) as f:
            cfg = json.load(f)
        configs.append(cfg)

    # Runtime validation — load schema if available
    schema_path = os.path.join(
        os.path.dirname(__file__), "../../types/cases.schema.json"
    )
    if os.path.exists(schema_path):
        with open(schema_path) as f:
            schema = json.load(f)
        valid_domains = set(schema["definitions"]["Domain"]["enum"])
        valid_fields = set(schema["properties"].keys())
        valid_statuses = set(schema["definitions"]["CaseStatus"]["enum"])
        if _INITIAL_STATUS not in valid_statuses:
            print(
                f"WARNING: INITIAL_STATUS '{_INITIAL_STATUS}' not in schema CaseStatus enum"
            )
        for cfg in configs:
            d = cfg.get("domain")
            if d not in valid_domains:
                print(f"WARNING: domain '{d}' not in schema Domain enum")
            for key in cfg.get("field_map", {}):
                if key not in valid_fields:
                    print(
                        f"WARNING: field_map key '{key}' in {d} not in schema properties"
                    )

    return configs


# ---------------------------------------------------------------------------
# SAP value helpers
# ---------------------------------------------------------------------------


def parse_sap_date(val) -> str | None:
    """Parse SAP /Date(ms)/ format → ISO string."""
    if not val or val == "null":
        return None
    s = str(val)
    if "/Date(" in s:
        try:
            ms = int(s.split("(")[1].split(")")[0].split("+")[0])
            return datetime.fromtimestamp(ms / 1000).isoformat()
        except Exception:
            return s
    return s


def _cast(val, cast_type: str):
    """Apply a cast to a raw SAP value."""
    if cast_type == "sap_date":
        return parse_sap_date(val)
    if cast_type == "float":
        return float(val or 0)
    if cast_type == "decimal2":
        return Decimal(str(round(float(val or 0), 2)))
    if cast_type == "abs_decimal":
        return Decimal(str(abs(float(val or 0))))
    return val


# ---------------------------------------------------------------------------
# Path resolution — navigate dotted paths like "to_AccountAssignment.results[0].GLAccount"
# ---------------------------------------------------------------------------

# Navigates dotted paths like "to_AccountAssignment.results[0].GLAccount"
_IDX_RE = re.compile(r"^(.+)\[(\d+)]$")


def _resolve_path(obj: dict, dotted: str):
    """Walk a dotted path with optional [N] indexing. Returns None on miss."""
    cur = obj
    for seg in dotted.split("."):
        if cur is None:
            return None
        m = _IDX_RE.match(seg)
        if m:
            cur = cur.get(m.group(1)) or {}
            if isinstance(cur, list):
                idx = int(m.group(2))
                cur = cur[idx] if idx < len(cur) else None
            elif isinstance(cur, dict) and "results" not in str(type(cur)):
                cur = None
        else:
            if isinstance(cur, dict):
                cur = cur.get(seg)
            else:
                return None
    return cur


def _resolve_scoped(parent: dict | None, child: dict | None, path: str):
    """Resolve a path prefixed with parent./child./self. against the right dict."""
    if path.startswith("parent."):
        return _resolve_path(parent or {}, path[7:])
    if path.startswith("child."):
        return _resolve_path(child or {}, path[6:])
    if path.startswith("self."):
        return _resolve_path(child or parent or {}, path[5:])
    # No prefix — try child first, then parent
    return _resolve_path(child or {}, path) or _resolve_path(parent or {}, path)


# ---------------------------------------------------------------------------
# Skip-condition evaluator
# ---------------------------------------------------------------------------


def _eval_skip(condition: dict, parent: dict | None, child: dict | None) -> bool:
    """Return True if this record should be skipped."""
    op = condition["op"]

    if op == "and":
        return all(_eval_skip(c, parent, child) for c in condition["conditions"])

    # Determine which dict to read from
    scope = condition.get("scope")
    if scope == "parent":
        target = parent or {}
    elif scope == "child":
        target = child or {}
    else:
        target = child or parent or {}

    raw = _resolve_path(target, condition["field"])

    if op == "blank":
        return not str(raw or "").strip()
    if op == "empty":
        return not raw or (isinstance(raw, list) and len(raw) == 0)
    if op == "present":
        return bool(str(raw or "").strip())
    if op == "lte":
        try:
            return float(raw or 0) <= condition["value"]
        except (ValueError, TypeError):
            return True

    return False


# ---------------------------------------------------------------------------
# Process-type resolver
# ---------------------------------------------------------------------------


def _resolve_process_type(cfg: dict, parent: dict | None, child: dict | None) -> str:
    """Evaluate process_type rules, return first match or default."""
    pt = cfg.get("process_type", {})
    for rule in pt.get("rules", []):
        when = rule["when"]
        # Reuse skip evaluator — "present" means the condition is met
        if _eval_skip(when, parent, child):
            return rule["then"]
    return pt.get("default", "unknown")


# ---------------------------------------------------------------------------
# Title interpolation
# ---------------------------------------------------------------------------


_TITLE_RE = re.compile(r"\{([^}]+)}")


def _render_title(
    template: str, parent: dict | None, child: dict | None, extra: dict
) -> str:
    """Interpolate {parent.Field}, {child.Field}, {self.Field}, {abs_amount} etc."""

    def _replace(m):
        key = m.group(1)
        # Check extra computed values first
        if key in extra:
            return str(extra[key])
        # Handle pipe-separated fallbacks: {parent.A|parent.B}
        for alt in key.split("|"):
            val = _resolve_scoped(parent, child, alt.strip())
            if val and str(val).strip():
                return str(val).strip()
        return ""

    return _TITLE_RE.sub(_replace, template)


# ---------------------------------------------------------------------------
# Field mapping
# ---------------------------------------------------------------------------


def _map_fields(field_map: dict, parent: dict | None, child: dict | None) -> dict:
    """Apply field_map config to produce case fields."""
    result = {}
    for case_field, spec in field_map.items():
        val = None

        if "expr" in spec:
            # Simple expression evaluation — only supports float(x) * float(y)
            val = _eval_expr(spec["expr"], parent, child)
        elif "path" in spec:
            val = _resolve_scoped(parent, child, spec["path"])
            if val is None and "fallback" in spec:
                val = _resolve_scoped(parent, child, spec["fallback"])

        if spec.get("strip") and isinstance(val, str):
            val = val.strip()

        if "cast" in spec and val is not None:
            val = _cast(val, spec["cast"])

        if spec.get("omit_blank") and not str(val or "").strip():
            continue

        result[case_field] = val

    return result


# Arithmetic operators permitted in config-defined `expr` field maps. Anything
# outside this set (calls, attribute access, names, etc.) is rejected, so the
# expression evaluator can never execute arbitrary code.
_ARITH_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_arith(node):
    """Evaluate a numeric arithmetic AST node, rejecting anything non-arithmetic."""
    if isinstance(node, ast.Expression):
        return _safe_arith(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _ARITH_OPS:
        return _ARITH_OPS[type(node.op)](
            _safe_arith(node.left), _safe_arith(node.right)
        )
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ARITH_OPS:
        return _ARITH_OPS[type(node.op)](_safe_arith(node.operand))
    raise ValueError(f"Unsupported expression element: {ast.dump(node)}")


def _eval_expr(expr: str, parent: dict | None, child: dict | None):
    """Evaluate simple arithmetic expressions like 'float(child.X) * float(child.Y)'."""

    def _resolve_ref(m):
        ref = m.group(1)
        val = _resolve_scoped(parent, child, ref)
        return str(float(val or 0))

    # Replace scoped references with their resolved float literals, leaving a
    # pure arithmetic string (e.g. "12.0 * 3.5").
    resolved = re.sub(r"(?:float\()?([a-zA-Z_.0-9\[\]]+)\)?", _resolve_ref, expr)
    try:
        return _safe_arith(ast.parse(resolved, mode="eval"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Key resolution (document_number / item_id)
# ---------------------------------------------------------------------------


def _resolve_key(
    spec: dict, parent: dict | None, child: dict | None, child_idx: int
) -> str:
    """Resolve a document_number or item_id from config."""
    source = spec.get("source", "self")
    if source == "parent":
        obj = parent or {}
    elif source == "child":
        obj = child or {}
    else:
        obj = child or parent or {}

    val = obj.get(spec["field"])

    if spec.get("strip") and isinstance(val, str):
        val = val.strip()

    if not val and spec.get("fallback"):
        val = spec["fallback"]

    if not val and spec.get("fallback_index"):
        val = str(child_idx + 1).zfill(4)

    return str(val or "")


# ---------------------------------------------------------------------------
# Core polling pipeline
# ---------------------------------------------------------------------------


def poll_domain(
    config: dict,
    sap_base_url: str,
    sap_session: requests.Session,
    table,
    case_exists_fn,
    put_case_fn,
    enqueue_fn,
) -> tuple[int, int]:
    """
    Execute the polling pipeline for a single domain config.

    Returns (created, skipped) counts.
    """
    url = f"{sap_base_url}/sap/opu/odata/sap/{config['service']}/{config['entity']}"
    params = {"$format": "json"}
    if config.get("filter"):
        params["$filter"] = config["filter"]
    if config.get("expand"):
        params["$expand"] = config["expand"]
    if config.get("select"):
        params["$select"] = config["select"]

    domain = config["domain"]
    label = config.get("label", domain)
    iterate_cfg = config["iterate"]
    field_map = config.get("field_map", {})
    skip_conditions = config.get("skip_when", [])

    print(f"Polling SAP for {label}...")
    try:
        resp = sap_session.get(
            url,
            params=params,
            headers={"Accept": "application/json"},
            timeout=30,
        )
    except requests.RequestException as e:
        print(f"{label} poll error: {e}")
        return 0, 0

    if resp.status_code != 200:
        print(f"{label} poll error: HTTP {resp.status_code}")
        return 0, 0

    entities = resp.json().get("d", {}).get("results", [])
    created = skipped = 0
    nav_path = iterate_cfg.get("path")

    for entity in entities:
        if nav_path:
            children = (entity.get(nav_path) or {}).get("results", [])
            if not children and iterate_cfg.get("allow_empty_children"):
                children = [{}]  # Synthetic empty child
            parent = entity
        else:
            children = [entity]
            parent = None

        for child_idx, child in enumerate(children):
            p = parent
            c = child if nav_path else None
            entity_for_skip = child

            should_skip = False
            for cond in skip_conditions:
                if _eval_skip(cond, p, c or entity_for_skip):
                    should_skip = True
                    break
            if should_skip:
                skipped += 1
                continue

            doc_number = _resolve_key(
                iterate_cfg["document_number"], p, c or entity, child_idx
            )
            item_id = _resolve_key(iterate_cfg["item_id"], p, c or entity, child_idx)

            if not doc_number:
                skipped += 1
                continue

            try:
                case_id = format_case_id(doc_number, item_id)
            except CaseKeyError as e:
                # An id we cannot represent canonically has no partition key and
                # would be unroutable downstream (SQS group, ticket correlation,
                # URL), so skip the case loudly instead of minting a broken one.
                print(f"Skipping {label} case with unusable key: {e}")
                skipped += 1
                continue

            if case_exists_fn(table, case_id):
                skipped += 1
                continue

            process_type = _resolve_process_type(config, p, c or entity)
            mapped = _map_fields(field_map, p, c or entity)

            abs_amount_val = mapped.get("amount")
            title_extra = {}
            if abs_amount_val is not None:
                title_extra["abs_amount"] = f"{float(abs_amount_val):,.2f}"

            title = _render_title(config.get("title", ""), p, c or entity, title_extra)

            now = datetime.utcnow().isoformat()
            case_item = {
                "case_id": case_id,
                "document_number": doc_number,
                "item_id": item_id,
                "domain": domain,
                "process_type": process_type,
                "title": title,
                "status": _INITIAL_STATUS,
                "agent_traces": [],
                "created_at": now,
                "updated_at": now,
                **mapped,
            }

            validate_or_log(WorkItem, case_item, context="odata_poller")

            try:
                if put_case_fn(table, case_item):
                    created += 1
                    print(f"Created {label} case: {case_id}")
                    enqueue_fn(case_id, domain, process_type)
                else:
                    skipped += 1
            except Exception as e:
                print(f"Error creating {label} case {case_id}: {e}")

    return created, skipped
