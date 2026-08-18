# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""`autonomy` — read and set the runtime trigger mode.

Ported from `scripts/ops/autonomy.sh`, which required a `STACK_NAME_BASE`
environment variable that `make autonomy` never exported, so the documented
command failed out of the box. The stack name is read from `cdk/config.yaml`
like every other command here.

Only `trigger-mode` exists. It governs whether the poller auto-enqueues work;
it is not a write kill-switch. SAP write gating lives in the Cedar policies at
the Gateway and in the external SAP MCP server.
"""

from __future__ import annotations

from .. import ui
from ..context import Ctx
from ..errors import LauncherError

TRIGGER_MODE = "trigger-mode"
VALID_MODES = ("auto", "manual")

_SSM_PATH = "/{stack}/autonomy/{name}"

_EXPLANATION = {
    "auto": "the OData poller enqueues exceptions as it finds them",
    "manual": "a human triggers each case from the UI or CLI",
}


def show(ctx: Ctx) -> int:
    ui.heading("Autonomy controls")
    path = _SSM_PATH.format(stack=ctx.stack_base, name=TRIGGER_MODE)
    value = ctx.aws.ssm_get(path)
    ui.kv(
        [
            ("stack", ctx.stack_base),
            ("region", ctx.region),
            ("parameter", path),
            (TRIGGER_MODE, value or "(not set — the deployed default applies)"),
        ]
    )
    if value in _EXPLANATION:
        ui.blank()
        ui.detail(f"{value}: {_EXPLANATION[value]}")
    ui.blank()
    ui.detail("This gates work initiation only. It is not a SAP write kill-switch.")
    return 0


def set_mode(ctx: Ctx, mode: str) -> int:
    if mode not in VALID_MODES:
        raise LauncherError(
            f"Invalid trigger mode '{mode}'.",
            hint=f"Choose one of: {', '.join(VALID_MODES)}.",
            exit_code=2,
        )
    ui.heading("Autonomy controls")
    path = _SSM_PATH.format(stack=ctx.stack_base, name=TRIGGER_MODE)
    previous = ctx.aws.ssm_get(path)

    if previous == mode:
        ui.ok(f"{TRIGGER_MODE} is already '{mode}'.")
        return 0

    if mode == "auto":
        ui.warn(
            "Switching to 'auto' lets the poller enqueue cases without a human trigger."
        )
        if not ctx.prompter.confirm(
            f"Set {TRIGGER_MODE} to auto for {ctx.stack_base}?", default=False
        ):
            from ..errors import Cancelled  # noqa: PLC0415 - local to keep imports tidy

            raise Cancelled()

    ctx.aws.ssm_put(path, mode)
    ui.ok(f"{TRIGGER_MODE}: {previous or '(unset)'} -> {mode}")
    ui.detail("Takes effect on the poller's next invocation. No redeployment needed.")
    return 0


def dispatch(ctx: Ctx, tokens: list[str]) -> int:
    """Route free-form autonomy arguments.

    Accepts both the short form and the parameter-named form that
    `scripts/ops/autonomy.sh` used, because `make autonomy CMD="set trigger-mode
    auto"` word-splits into three arguments and that spelling is documented in
    several places:

        (none)                     -> get
        get                        -> get
        set auto                   -> set trigger-mode to auto
        set trigger-mode auto      -> same
    """
    words = [token for token in tokens if token]
    if not words or words[0] == "get":
        remainder = words[1:]
        if remainder and remainder != [TRIGGER_MODE]:
            return _usage(f"unexpected argument(s) after 'get': {' '.join(remainder)}")
        return show(ctx)

    if words[0] != "set":
        return _usage(f"unknown action '{words[0]}'")

    values = [word for word in words[1:] if word != TRIGGER_MODE]
    if not values:
        return _usage("'set' needs a mode")
    if len(values) > 1:
        return _usage(f"expected one mode, got: {' '.join(values)}")
    return set_mode(ctx, values[0])


def _usage(problem: str) -> int:
    ui.err(f"autonomy: {problem}.")
    ui.hint(f"Usage: python3 launch.py autonomy [get | set {'|'.join(VALID_MODES)}]")
    return 2
