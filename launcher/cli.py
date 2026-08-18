# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Argument parsing and command dispatch.

`python3 launch.py` with no arguments runs the guided flow, which is the path a
first-time user should take. Every phase of that flow is also a standalone
subcommand, so nothing is only reachable through the wizard.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from . import ui
from .commands import (
    autonomy,
    configure,
    doctor,
    frontend,
    guided,
    infra,
    knowledge,
    refresh,
    secrets,
    status,
)
from .context import Ctx
from .errors import EXIT_ERROR, EXIT_USAGE, Cancelled, LauncherError

PROGRAM = "launch.py"

_EPILOG = """\
examples:
  python3 launch.py                     guided first-time launch
  python3 launch.py doctor              check prerequisites, change nothing
  python3 launch.py deploy              redeploy infrastructure, Lambdas, frontend
  python3 launch.py status              what is deployed and healthy
  python3 launch.py resume              continue an interrupted launch
  python3 launch.py autonomy set auto   let the poller enqueue work

This is sample code: educational, non-production, and unsupported. Review and
harden it before using it for anything real.
"""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description="Guided launcher for the Agentic ERP Automation sample.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--region", help="AWS Region to target. Overrides AWS_REGION and the profile."
    )
    parser.add_argument("--profile", help="AWS named profile to use.")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Accept ordinary confirmations. Destructive confirmations still require an answer.",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Never prompt. Uses defaults and fails where there is no safe default.",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Echo the commands being run."
    )

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    launch = sub.add_parser("launch", help="Guided first-time launch (the default).")
    launch.add_argument(
        "--skip-doctor", action="store_true", help="Skip the environment check."
    )

    sub.add_parser(
        "doctor", help="Check prerequisites and AWS access. Changes nothing."
    )

    configure_parser = sub.add_parser("configure", help="Generate cdk/config.yaml.")
    configure_parser.add_argument(
        "--force", action="store_true", help="Overwrite without asking."
    )

    sub.add_parser(
        "deploy", help="Deploy infrastructure, refresh Lambdas, deploy the frontend."
    )
    sub.add_parser("infra", help="Deploy the CDK stacks only.")
    sub.add_parser("frontend", help="Build and deploy the frontend only.")
    sub.add_parser("refresh", help="Force this stack's Lambdas to cold-start.")
    sub.add_parser("diff", help="Show pending CDK changes, including IAM.")
    sub.add_parser("synth", help="Validate the CDK app without deploying.")
    sub.add_parser("status", help="Report deployed stacks, endpoints, and failures.")
    sub.add_parser("resume", help="Continue an interrupted launch.")

    sap = sub.add_parser(
        "sync-sap", help="Sync SAP service-account credentials to Secrets Manager."
    )
    sap.add_argument(
        "--force", action="store_true", help="Replace credentials that are already set."
    )
    sap.add_argument(
        "--skip-refresh",
        action="store_true",
        help="Do not cold-start the consuming Lambdas.",
    )

    channel = sub.add_parser(
        "sync-channel", help="Store the notification webhook signing secret."
    )
    channel.add_argument(
        "--force", action="store_true", help="Replace a secret that is already set."
    )

    kb = sub.add_parser(
        "sync-kb", help="Publish SOPs and API docs, then start ingestion."
    )
    kb.add_argument(
        "--only",
        choices=[corpus.key for corpus in knowledge.CORPORA],
        help="Limit to one corpus.",
    )

    autonomy_parser = sub.add_parser(
        "autonomy",
        help="Read or set the runtime trigger mode.",
        description=(
            "Read or set the runtime trigger mode. Accepts `get`, `set <mode>`, and the "
            "longer `set trigger-mode <mode>` spelling that `make autonomy CMD=...` produces."
        ),
    )
    autonomy_parser.add_argument(
        "args",
        nargs="*",
        metavar="ARG",
        help=f"Default: get. Valid modes: {', '.join(autonomy.VALID_MODES)}.",
    )
    return parser


def _dispatch(ctx: Ctx, args: argparse.Namespace) -> int:
    command = args.command or "launch"

    if command == "launch":
        return guided.run(ctx, skip_doctor=getattr(args, "skip_doctor", False))
    if command == "resume":
        return guided.run(ctx, resume=True)
    if command == "doctor":
        return doctor.run(ctx)
    if command == "configure":
        return configure.run(ctx, force=args.force)
    if command == "deploy":
        return guided.redeploy(ctx)
    if command == "infra":
        infra.deploy(ctx)
        return 0
    if command == "frontend":
        return frontend.run(ctx)
    if command == "refresh":
        return refresh.run(ctx)
    if command == "diff":
        return infra.diff(ctx)
    if command == "synth":
        return infra.synth(ctx)
    if command == "status":
        return status.run(ctx)
    if command == "sync-sap":
        return secrets.sync_sap(ctx, force=args.force, skip_refresh=args.skip_refresh)
    if command == "sync-channel":
        return secrets.sync_channel(ctx, force=args.force)
    if command == "sync-kb":
        return knowledge.run(ctx, only=args.only)
    if command == "autonomy":
        return autonomy.dispatch(ctx, args.args)

    ui.err(f"Unknown command: {command}")
    return EXIT_USAGE


def main(argv: Sequence[str], *, repo_root: Path) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv))

    prompter = ui.Prompter(
        interactive=False if args.non_interactive else None,
        assume_yes=args.yes,
    )
    ctx = Ctx(
        repo_root=repo_root,
        prompter=prompter,
        region_override=args.region,
        profile=args.profile,
        verbose=args.verbose,
    )

    try:
        return _dispatch(ctx, args)
    except Cancelled as exc:
        ui.blank()
        ui.warn(exc.message)
        return exc.exit_code
    except LauncherError as exc:
        ui.blank()
        ui.err(exc.message)
        if exc.hint:
            ui.hint(exc.hint)
        return exc.exit_code
    except KeyboardInterrupt:
        ui.blank()
        ui.warn("Interrupted. Run `python3 launch.py status` to see what completed.")
        return Cancelled().exit_code
    except BrokenPipeError:
        return EXIT_ERROR
