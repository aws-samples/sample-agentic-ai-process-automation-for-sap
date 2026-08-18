# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Reading and writing `cdk/config.yaml`.

Writes are text substitutions on `config.yaml.example`, not a YAML round-trip.
That is deliberate: the template's value is its commented documentation, and
serialising a parsed dict back out would delete every comment and every
commented-out optional block the user needs in order to discover the options.

Reads prefer PyYAML when it is importable and fall back to an
indentation-aware scanner, so `doctor` can inspect config before any Python
package is installed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .errors import ConfigError

DEFAULT_STACK_NAME = "my-erp-agent"
MAX_STACK_NAME = 35

# CloudFormation stack names: letter first, then letters/digits/hyphens.
_STACK_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# The commented `# demo:` block and its `#`-prefixed body, leaving the
# explanatory prose above it untouched.
_DEMO_BLOCK_RE = re.compile(r"(?m)^# demo:\n(?:^#.*\n)*")


# ── Validation ───────────────────────────────────────────────────────────


def validate_stack_name(name: str) -> str | None:
    if not name:
        return "Stack name is required."
    if len(name) > MAX_STACK_NAME:
        return f"Max {MAX_STACK_NAME} characters (got {len(name)})."
    if "_" in name:
        return "No underscores — use hyphens."
    if not _STACK_NAME_RE.match(name):
        return "Use letters, digits, and hyphens, starting with a letter."
    return None


def validate_email(value: str) -> str | None:
    if not value:
        return None  # optional everywhere it is asked for
    if not _EMAIL_RE.match(value):
        return "Enter a valid email address, or leave blank."
    return None


# ── Reading ──────────────────────────────────────────────────────────────


def load(path: Path) -> dict[str, Any]:
    """Parse the config file into a dict. Returns {} when it does not exist."""
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # noqa: PLC0415 - optional, probed at call time
    except ImportError:
        return _scan(text)
    try:
        parsed = yaml.safe_load(text)
    except Exception as exc:  # noqa: BLE001 - yaml raises several error types
        raise ConfigError(
            f"{path} is not valid YAML.",
            hint=str(exc).splitlines()[0],
        ) from exc
    return parsed or {}


def get(config: dict[str, Any], dotted: str, default: Any = None) -> Any:
    """Look up `a.b.c`, treating blank strings and None alike as absent."""
    node: Any = config
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    if node is None or node == "":
        return default
    return node


def _scan(text: str) -> dict[str, Any]:
    """Minimal indentation-aware YAML subset reader.

    Handles the scalar and nested-mapping shapes this config uses. Lists and
    multi-line scalars are skipped rather than guessed at — anything that needs
    them should require PyYAML instead of trusting this.
    """
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.lstrip().startswith("- "):
            continue
        match = re.match(r"^(\s*)([A-Za-z_][\w-]*):[ \t]*(.*)$", raw)
        if not match:
            continue
        indent, key, value = len(match.group(1)), match.group(2), match.group(3)
        value = value.split(" #", 1)[0].strip().strip("'\"")
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if not stack:
            stack = [(-1, root)]
        parent = stack[-1][1]
        if value:
            parent[key] = _coerce(value)
        else:
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
    return root


def _coerce(value: str) -> Any:
    lowered = value.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    if lowered in ("null", "~"):
        return None
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return value


# ── Writing ──────────────────────────────────────────────────────────────


def _set_line(text: str, key: str, value: str, indent: str = "") -> str:
    """Replace the first `key:` line at `indent`, keeping the indentation."""
    return re.sub(
        rf"(?m)^{re.escape(indent)}{re.escape(key)}:.*$",
        f"{indent}{key}: {value}",
        text,
        count=1,
    )


def _enable_ses(text: str, sender_email: str) -> str:
    """Uncomment the notification block and set the SES sender."""
    text = re.sub(r"(?m)^#\s*(notification:)\s*$", r"\1", text)
    text = re.sub(r"(?m)^#\s*(channel: ses).*$", r"  \1", text)
    return re.sub(
        r"(?m)^#\s*ses_sender_email:.*$",
        f"  ses_sender_email: {sender_email}",
        text,
        count=1,
    )


def _apply_demo(text: str, *, ticketing: bool, test_data: bool) -> str:
    """Activate the demo block. No-op when neither feature is selected, which
    leaves the block commented — the clean production default."""
    if not (ticketing or test_data):
        return text
    active = (
        "demo:\n"
        f"  ticketing:\n    enabled: {'true' if ticketing else 'false'}\n"
        f"  test_data:\n    enabled: {'true' if test_data else 'false'}\n"
    )
    return _DEMO_BLOCK_RE.sub(active, text, count=1)


def render(
    template_text: str,
    *,
    stack_name: str,
    admin_email: str = "",
    ses_sender_email: str = "",
    ticketing: bool = False,
    test_data: bool = False,
) -> str:
    """Produce config.yaml content from the template plus the answers given."""
    text = _set_line(template_text, "stack_name_base", stack_name)
    if admin_email:
        text = _set_line(text, "admin_user_email", admin_email)
    if ses_sender_email:
        text = _enable_ses(text, ses_sender_email)
    return _apply_demo(text, ticketing=ticketing, test_data=test_data)


def digest(path: Path) -> str | None:
    """Stable content hash, for detecting config drift between runs."""
    if not path.exists():
        return None
    import hashlib  # noqa: PLC0415 - only needed on this path

    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
