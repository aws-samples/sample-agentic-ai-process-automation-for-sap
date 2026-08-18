# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Frontend deployment.

Delegates to `scripts/deploy/deploy-frontend.py`, which already owns stack-output
discovery, aws-exports generation, the npm build, S3 upload, and Amplify job
polling. Reimplementing that would fork the auth-profile resolution it shares
with CDK synth, so the launcher wraps it and adds the preflight and diagnosis
the raw script does not have.
"""

from __future__ import annotations

import sys

from .. import shell, state, ui
from ..context import Ctx
from ..errors import DeployError

PHASE = "frontend"
SCRIPT_RELATIVE = "scripts/deploy/deploy-frontend.py"

_REQUIRED_OUTPUTS = ("AmplifyAppId", "StagingBucketName")


def _preflight(ctx: Ctx) -> None:
    """Fail before a long npm build if the stack outputs are not there yet."""
    outputs = ctx.aws.stack_outputs(ctx.stack_name("frontend"))
    if not outputs:
        outputs = ctx.aws.stack_outputs(ctx.stack_base)  # legacy single-stack layout
    missing = [key for key in _REQUIRED_OUTPUTS if key not in outputs]
    if missing:
        raise DeployError(
            f"Frontend stack outputs missing: {', '.join(missing)}.",
            hint="Deploy the infrastructure first (`python3 launch.py deploy`).",
        )


def run(ctx: Ctx) -> int:
    ui.heading("Frontend")
    script = ctx.repo_root / SCRIPT_RELATIVE
    if not script.exists():
        raise DeployError(f"{SCRIPT_RELATIVE} is missing from this checkout.")

    _preflight(ctx)
    ui.info("Building and deploying the frontend to Amplify Hosting...")
    ui.detail(
        "Generates aws-exports.json, runs the production build, uploads, then polls the Amplify job."
    )
    state.mark(ctx, PHASE, state.RUNNING)

    result = shell.run(
        [sys.executable, str(script), ctx.stack_base],
        cwd=ctx.repo_root,
        env=ctx.aws.env(),
        stream=True,
        check=False,
        timeout=None,
        verbose=ctx.verbose,
    )
    if not result.ok:
        state.mark(ctx, PHASE, state.FAILED, exit_code=result.code)
        raise DeployError(
            f"Frontend deployment failed (exit {result.code}).",
            hint="Re-run `python3 launch.py frontend` — it is safe to repeat and starts a fresh Amplify job.",
        )

    state.mark(ctx, PHASE, state.DONE)
    ui.ok("Frontend deployed.")
    return 0


def url(ctx: Ctx) -> str | None:
    outputs = ctx.aws.stack_outputs(ctx.stack_name("frontend"))
    return outputs.get("AmplifyUrl") or None
