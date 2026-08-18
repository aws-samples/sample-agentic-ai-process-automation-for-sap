# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""`refresh` — force Lambdas to cold-start so they re-read SSM and Secrets.

Ported from the inline `refresh-lambdas` recipe in the Makefile, which was the
only implementation and had no script equivalent. Four behaviours changed:

1. A failed read of a function's environment used to fall back to `{}`, and
   because `--environment` replaces the whole map, that silently wiped every
   variable on that function. Now a failed read skips the function.
2. Updates are awaited, so back-to-back calls stop racing into
   ResourceConflictException.
3. Failures are reported and returned, instead of being swallowed into a
   "(skipped)" line that always exited 0.
4. Prefix matching is shown before it is applied, because `startswith(stack)`
   also matches unrelated functions that happen to share the prefix.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .. import state, ui
from ..context import Ctx
from ..errors import EXIT_AWS, LauncherError

PHASE = "refresh-lambdas"
CACHE_BUST_KEY = "CACHE_BUST"


@dataclass
class Outcome:
    updated: list[str]
    skipped: list[tuple[str, str]]
    failed: list[tuple[str, str]]

    @property
    def clean(self) -> bool:
        return not self.failed


def _bounce(
    ctx: Ctx,
    names: list[str],
    *,
    env_key: str,
    stamp: str,
    wait: bool,
) -> Outcome:
    outcome = Outcome([], [], [])
    for name in names:
        current = ctx.aws.lambda_environment(name)
        if current is None:
            # Refusing to update is the safe branch: an update would replace the
            # entire environment map with only our stamp.
            outcome.skipped.append((name, "could not read current environment"))
            ui.warn(f"{name} — skipped, current environment unreadable")
            continue
        merged = {**current, env_key: stamp}
        try:
            ctx.aws.lambda_set_environment(name, merged)
        except LauncherError as exc:
            outcome.failed.append((name, exc.message))
            ui.err(f"{name} — {exc.message}")
            continue
        if wait and not ctx.aws.lambda_wait_updated(name):
            outcome.failed.append((name, "update did not settle"))
            ui.err(f"{name} — update did not reach a settled state")
            continue
        outcome.updated.append(name)
        ui.ok(name)
    return outcome


def run(ctx: Ctx, *, quiet: bool = False) -> int:
    """Cold-start every Lambda belonging to this stack."""
    if not quiet:
        ui.heading("Refreshing Lambdas")

    prefix = f"{ctx.stack_base}-"
    names = ctx.aws.lambda_names_with_prefix(prefix)
    if not names:
        ui.warn(f"No Lambda functions found with prefix '{prefix}'.")
        ui.hint("Deploy the infrastructure first, or check the account and Region.")
        state.mark(ctx, PHASE, state.SKIPPED, reason="no functions matched")
        return 0

    ui.info(f"{len(names)} function(s) match prefix '{prefix}':")
    ui.bullets(names)
    ui.detail(
        "Prefix matching is inclusive — anything sharing this prefix is included."
    )
    ui.blank()

    state.mark(ctx, PHASE, state.RUNNING, function_count=len(names))
    outcome = _bounce(
        ctx,
        names,
        env_key=CACHE_BUST_KEY,
        stamp=str(int(time.time())),
        wait=True,
    )

    ui.blank()
    if outcome.clean:
        ui.ok(f"{len(outcome.updated)} function(s) will cold-start on next invocation.")
        state.mark(ctx, PHASE, state.DONE, updated=len(outcome.updated))
        return 0

    ui.err(f"{len(outcome.failed)} function(s) failed to update.")
    ui.hint(
        "Re-run `python3 launch.py refresh`; already-updated functions are harmless to repeat."
    )
    state.mark(ctx, PHASE, state.FAILED, failed=len(outcome.failed))
    return EXIT_AWS


def bounce_sap_auth_consumers(ctx: Ctx) -> Outcome:
    """Cold-start only the Lambdas carrying the SAP auth layer.

    Narrower than `run()` on purpose: after a credential rotation, only the
    functions that read those credentials need to restart.
    """
    layer_fragment = f"{ctx.stack_base}-sap-auth:"
    names = ctx.aws.lambda_names_with_layer(layer_fragment)
    if not names:
        ui.warn(
            f"No Lambda uses the '{ctx.stack_base}-sap-auth' layer — nothing to refresh."
        )
        return Outcome([], [], [])
    ui.info(f"Refreshing {len(names)} SAP-credential consumer(s):")
    return _bounce(
        ctx,
        names,
        env_key="SAP_CREDS_VERSION",
        stamp=str(int(time.time())),
        wait=True,
    )
