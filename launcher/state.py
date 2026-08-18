# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Local, non-secret run state at `.launcher/state.json`.

Records what completed so `status` and `resume` have something to start from.
It is a hint, not an authority: AWS is always re-queried before acting on it,
because a state file can be stale, copied between machines, or edited.

Nothing secret is ever written here. See `_FORBIDDEN_KEYS`.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from . import configfile
from .context import Ctx

STATE_FILENAME = "state.json"
SCHEMA_VERSION = 1

# Defence in depth: a future caller adding one of these to a state update is a
# bug, and should fail loudly rather than quietly persist a credential.
_FORBIDDEN_KEYS = frozenset(
    {
        "password",
        "secret",
        "secret_string",
        "token",
        "access_key",
        "secret_access_key",
        "session_token",
        "credentials",
        "client_secret",
    }
)

RUNNING = "running"
DONE = "done"
FAILED = "failed"
SKIPPED = "skipped"


def _path(ctx: Ctx) -> Path:
    return ctx.state_dir / STATE_FILENAME


def load(ctx: Ctx) -> dict[str, Any]:
    path = _path(ctx)
    if not path.exists():
        return {"schema": SCHEMA_VERSION, "phases": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema": SCHEMA_VERSION, "phases": {}}
    if not isinstance(data, dict):
        return {"schema": SCHEMA_VERSION, "phases": {}}
    data.setdefault("schema", SCHEMA_VERSION)
    data.setdefault("phases", {})
    return data


def _assert_no_secrets(payload: dict[str, Any]) -> None:
    for key in payload:
        if key.lower() in _FORBIDDEN_KEYS:
            raise ValueError(
                f"Refusing to write '{key}' to launcher state — it may be a secret."
            )


def save(ctx: Ctx, **updates: Any) -> dict[str, Any]:
    _assert_no_secrets(updates)
    data = load(ctx)
    data.update(updates)
    data["updated_at"] = _now()
    _write(ctx, data)
    return data


def record_target(ctx: Ctx) -> dict[str, Any]:
    """Snapshot what this run is pointed at, so drift is visible later."""
    return save(
        ctx,
        launcher_version=ctx.version,
        repo_commit=ctx.commit(),
        account=ctx.account,
        region=ctx.region,
        stack_base=ctx.stack_base,
        config_digest=configfile.digest(ctx.config_path),
    )


def mark(ctx: Ctx, phase: str, status: str, **extra: Any) -> None:
    _assert_no_secrets(extra)
    data = load(ctx)
    entry = data["phases"].get(phase, {})
    entry.update({"status": status, "at": _now(), **extra})
    data["phases"][phase] = entry
    data["updated_at"] = _now()
    _write(ctx, data)


def drifted(ctx: Ctx) -> list[str]:
    """Ways the current target differs from the recorded one."""
    data = load(ctx)
    if not data.get("account"):
        return []
    differences: list[str] = []
    for label, recorded, current in (
        ("account", data.get("account"), ctx.account),
        ("region", data.get("region"), ctx.region),
        ("stack name", data.get("stack_base"), ctx.stack_base),
        ("config", data.get("config_digest"), configfile.digest(ctx.config_path)),
    ):
        if recorded and current and recorded != current:
            differences.append(f"{label}: was {recorded}, now {current}")
    return differences


def _write(ctx: Ctx, data: dict[str, Any]) -> None:
    ctx.state_dir.mkdir(parents=True, exist_ok=True)
    path = _path(ctx)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
