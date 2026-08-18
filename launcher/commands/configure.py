# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""`configure` — generate `cdk/config.yaml` from the documented template.

Asks only the questions a first deployment actually needs. Everything else
keeps the template's default and stays visible as a commented option, so the
file remains the reference it was written to be.
"""

from __future__ import annotations

from .. import configfile, ui
from ..context import Ctx
from ..errors import Cancelled, ConfigError

DEMO_OPTIONS = (
    (
        "ticketing",
        "Ticketing — tickets table, /tickets API, approve/deny flow, Tickets tab (stands in for ServiceNow/Jira)",
    ),
    (
        "test_data",
        "Test data — sample SAP-case generator and Test Data tab",
    ),
)


def run(ctx: Ctx, *, force: bool = False) -> int:
    ui.heading("Configuration")

    if not ctx.config_template.exists():
        raise ConfigError(
            f"Template missing: {ctx.config_template.relative_to(ctx.repo_root)}",
            hint="This file ships with the repository — check out a clean copy.",
        )

    if ctx.config_path.exists() and not force:
        existing = configfile.get(ctx.reload_config(), "stack_name_base", "(unset)")
        ui.info(
            f"{ctx.config_path.relative_to(ctx.repo_root)} already exists (stack: {existing})."
        )
        if not ctx.prompter.confirm("Overwrite it?", default=False):
            ui.ok("Keeping the existing configuration.")
            return 0

    ui.blank()
    ui.detail("Two answers are required. The rest can stay at their defaults.")
    ui.blank()

    stack_name = ctx.prompter.ask(
        "Stack name — prefixes every AWS resource",
        default=configfile.DEFAULT_STACK_NAME,
        validate=configfile.validate_stack_name,
    )
    admin_email = ctx.prompter.ask(
        "Admin email — creates the first Cognito user (blank to skip)",
        default="",
        allow_empty=True,
        validate=configfile.validate_email,
    )
    ses_email = ctx.prompter.ask(
        "SES sender address — outbound agent email (blank to skip)",
        default="",
        allow_empty=True,
        validate=configfile.validate_email,
    )

    ui.blank()
    selected = ctx.prompter.select_many(
        "Optional demo features — leave blank for a clean production base",
        DEMO_OPTIONS,
    )

    text = configfile.render(
        ctx.config_template.read_text(encoding="utf-8"),
        stack_name=stack_name,
        admin_email=admin_email,
        ses_sender_email=ses_email,
        ticketing="ticketing" in selected,
        test_data="test_data" in selected,
    )

    ctx.config_path.write_text(text, encoding="utf-8")
    ctx.reload_config()

    ui.blank()
    ui.ok(f"Wrote {ctx.config_path.relative_to(ctx.repo_root)}")
    ui.kv(
        [
            ("stack name", stack_name),
            ("admin user", admin_email or "(none — create a Cognito user manually)"),
            ("SES sender", ses_email or "(none — email notifications stay off)"),
            ("demo features", ", ".join(selected) if selected else "(none)"),
        ],
        indent="    ",
    )
    ui.blank()
    ui.detail(
        "Everything else uses the template defaults. Open the file to see the options."
    )
    return 0


def ensure(ctx: Ctx) -> None:
    """Make sure a usable config exists, offering to create one if not."""
    if ctx.config_path.exists():
        try:
            _ = ctx.stack_base
        except ConfigError:
            pass
        else:
            return
    ui.warn(f"{ctx.config_path.relative_to(ctx.repo_root)} is missing or incomplete.")
    if not ctx.prompter.confirm("Create it now?", default=True):
        raise Cancelled("Configuration is required before deploying.")
    run(ctx, force=True)
