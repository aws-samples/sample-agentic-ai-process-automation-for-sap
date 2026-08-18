# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""The guided flow: clean clone to a working sample in one command.

Replaces the `make setup` recipe, which chained shell `read -p` prompts under
/bin/sh — those silently fail on any system where /bin/sh is dash. It also
folds in the Lambda refresh that `make setup` omitted but `make deploy-all`
needs, so a first deployment and a redeployment take the same path.

`resume` reuses this flow. Nothing is skipped on the strength of the state file
alone: CloudFormation is queried first, so a state file that is stale, copied
between machines, or hand-edited cannot cause a phase to be wrongly skipped.
"""

from __future__ import annotations

from .. import state, ui
from ..commands import (
    configure,
    doctor,
    frontend,
    infra,
    knowledge,
    refresh,
    secrets,
    status,
    target,
)
from ..context import Ctx
from ..errors import EXIT_PREREQ, Cancelled

CORE_STEPS = 5


def _preflight(ctx: Ctx, *, skip_doctor: bool) -> None:
    if skip_doctor:
        ui.info("Skipping the environment check (--skip-doctor).")
        return
    code = doctor.run(ctx)
    if code == EXIT_PREREQ:
        raise Cancelled("Environment check failed — fix the items above and re-run.")


def _summary(ctx: Ctx, *, optional_skipped: list[str]) -> None:
    ui.heading("Done")
    application_url = frontend.url(ctx)
    ui.kv(
        [
            ("account", ctx.account),
            ("region", ctx.region),
            ("stack prefix", ctx.stack_base),
            ("application", application_url or "(no AmplifyUrl output found)"),
        ]
    )

    if application_url:
        ui.blank()
        ui.hint(f"Open {application_url}")
        admin = ctx.config.get("admin_user_email")
        if admin:
            ui.detail(
                f"Sign in as {admin} — the temporary password was emailed by Cognito."
            )
        else:
            ui.detail(
                "No admin_user_email was configured, so create a Cognito user before signing in."
            )

    if optional_skipped:
        ui.blank()
        print("  Not run")
        ui.bullets(optional_skipped)

    ui.blank()
    print("  Next")
    ui.bullets(
        [
            "python3 launch.py status      — what is deployed and healthy",
            "python3 launch.py deploy      — redeploy after code changes",
            "python3 launch.py autonomy    — read or set the trigger mode",
            "python3 launch.py sync-kb     — republish SOPs and re-ingest",
        ]
    )
    ui.blank()
    ui.detail(
        "This sample is educational. Review and harden it before any production use."
    )


def _offer_optional_steps(ctx: Ctx) -> list[str]:
    """Offer the steps that are neither required nor safe to assume."""
    skipped: list[str] = []

    if secrets.sap_configured(ctx):
        ui.blank()
        if ctx.prompter.confirm(
            "Sync SAP credentials to Secrets Manager now?", default=True
        ):
            try:
                secrets.sync_sap(ctx)
            except Cancelled:
                skipped.append(
                    "SAP credentials — cancelled; run `python3 launch.py sync-sap` later"
                )
        else:
            skipped.append("SAP credentials — run `python3 launch.py sync-sap`")
    else:
        skipped.append(
            "SAP credentials — sap.base_url is not configured, so there is nothing to sync"
        )

    ui.blank()
    ui.detail(
        "Publishing the knowledge base uploads SOPs and API docs, and can delete bucket content."
    )
    if ctx.prompter.confirm(
        "Publish the knowledge base and start ingestion now?", default=True
    ):
        try:
            knowledge.run(ctx)
        except Cancelled:
            skipped.append(
                "Knowledge base — cancelled; run `python3 launch.py sync-kb` later"
            )
    else:
        skipped.append("Knowledge base — run `python3 launch.py sync-kb`")

    return skipped


def run(ctx: Ctx, *, skip_doctor: bool = False, resume: bool = False) -> int:
    """Run the guided flow. `resume` skips phases AWS confirms are complete."""
    ui.heading("Agentic ERP Automation — guided launch" if not resume else "Resuming")
    ui.detail(f"Repository {ctx.repo_root}")
    ui.detail(f"Version {ctx.version}" + (f" ({ctx.commit()})" if ctx.commit() else ""))
    if not resume:
        ui.blank()
        ui.detail(
            "Five required steps, then two optional ones. Nothing is written to AWS before you confirm."
        )

    ui.step(1, CORE_STEPS, "Environment check")
    _preflight(ctx, skip_doctor=skip_doctor)

    ui.step(2, CORE_STEPS, "Configuration")
    configure.ensure(ctx)

    ui.step(3, CORE_STEPS, "Confirm the deployment target")
    stacks = status.collect(ctx) if resume else []
    verdict = status.overall(stacks) if resume else "not started"

    if resume and verdict == "in progress":
        ui.warn("A deployment is already running against this stack.")
        ui.hint("Wait for it to finish, then re-run `python3 launch.py resume`.")
        return 0

    if resume and verdict == "complete":
        ui.ok("All stacks are already deployed.")
        ui.detail("Re-deploying is safe and picks up local code changes.")
        if not ctx.prompter.confirm("Deploy again anyway?", default=False):
            ui.step(4, CORE_STEPS, "Infrastructure")
            ui.info("Skipped — already complete.")
            ui.step(5, CORE_STEPS, "Frontend")
            skipped = []
            if ctx.prompter.confirm("Redeploy the frontend?", default=False):
                frontend.run(ctx)
            else:
                skipped.append("Frontend — run `python3 launch.py frontend`")
            _summary(ctx, optional_skipped=skipped)
            return 0
        target.summary(ctx)
        state.record_target(ctx)
    else:
        target.confirm(ctx)

    ui.step(4, CORE_STEPS, "Infrastructure")
    infra.deploy(ctx)
    ui.blank()
    refresh_code = refresh.run(ctx, quiet=True)

    ui.step(5, CORE_STEPS, "Frontend")
    frontend.run(ctx)

    ui.heading("Optional steps")
    ui.detail(
        "Both can be run later. Neither is required for the application to start."
    )
    skipped = _offer_optional_steps(ctx)

    _summary(ctx, optional_skipped=skipped)
    return refresh_code


def redeploy(ctx: Ctx) -> int:
    """Non-guided redeployment: infrastructure, Lambda refresh, frontend.

    The equivalent of `make deploy-all`, keeping the ordering contract that the
    Lambda refresh sits between the two so new SSM values are picked up.
    """
    target.confirm(ctx)
    infra.deploy(ctx)
    ui.blank()
    # The frontend still ships on a failed refresh — stale Lambda config is not a
    # reason to withhold the UI — but the exit code has to carry the failure, or
    # "Done" is the only thing a caller sees after 26 functions failed to update.
    refresh_code = refresh.run(ctx, quiet=True)
    frontend.run(ctx)
    _summary(ctx, optional_skipped=[])
    return refresh_code
