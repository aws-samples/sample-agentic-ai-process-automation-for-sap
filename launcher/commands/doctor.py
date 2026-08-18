# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""`doctor` — check prerequisites without changing anything.

Read-only by contract. `check_prereqs()` in scripts/setup.py silently ran
`npm install -g aws-cdk`, so a "check" mutated the machine. Nothing here
installs, writes, or creates an AWS resource; remediation is printed for the
user to run.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .. import configfile, toolchain, ui
from ..context import Ctx
from ..errors import EXIT_PREREQ, LauncherError

PASS = "pass"
WARN = "warn"
FAIL = "fail"

_MARK = {PASS: ui.ok, WARN: ui.warn, FAIL: ui.err}


@dataclass
class Finding:
    status: str
    label: str
    detail: str = ""
    remedy: str = ""
    note: str = ""  # always printed, whatever the status


def _emit(finding: Finding) -> None:
    text = (
        finding.label if not finding.detail else f"{finding.label} — {finding.detail}"
    )
    _MARK[finding.status](text)
    if finding.note:
        ui.detail(finding.note)
    if finding.remedy and finding.status != PASS:
        ui.hint(finding.remedy)


def _check_runtimes() -> list[Finding]:
    findings: list[Finding] = []

    python = toolchain.python_version()
    if tuple(int(part) for part in python.split(".")[:2]) < toolchain.MIN_PYTHON:
        findings.append(
            Finding(
                FAIL,
                "Python",
                f"{python} (need {'.'.join(map(str, toolchain.MIN_PYTHON))}+)",
                "Install a newer Python 3 and re-run with it.",
            )
        )
    else:
        findings.append(Finding(PASS, "Python", python))

    node = toolchain.find("node")
    major = toolchain.node_major(node.version)
    if not node.present:
        findings.append(
            Finding(FAIL, "Node.js", "not found", "Install Node.js 20 or newer.")
        )
    elif major is not None and major < toolchain.MIN_NODE_MAJOR:
        findings.append(
            Finding(
                FAIL,
                "Node.js",
                f"{node.version} (need {toolchain.MIN_NODE_MAJOR}+)",
                "Upgrade Node.js — the CDK app and frontend build both require 20+.",
            )
        )
    else:
        findings.append(Finding(PASS, "Node.js", node.version or "present"))

    for name in ("npm", "aws", "git"):
        tool = toolchain.find(name)
        if tool.present:
            findings.append(
                Finding(PASS, name, (tool.version or "present").splitlines()[0])
            )
        else:
            findings.append(
                Finding(
                    FAIL,
                    name,
                    "not found",
                    f"Install {name} and make sure it is on PATH.",
                )
            )

    if toolchain.has_pyyaml():
        findings.append(Finding(PASS, "PyYAML", "importable"))
    else:
        findings.append(
            Finding(
                FAIL,
                "PyYAML",
                "not importable",
                "Run `pip install pyyaml` — cdk/bin/app.ts shells out to run_emit.py, which needs it.",
            )
        )
    return findings


def _check_cdk(ctx: Ctx) -> list[Finding]:
    findings: list[Finding] = []
    if toolchain.cdk_dependencies_installed(ctx.cdk_dir):
        findings.append(Finding(PASS, "cdk/node_modules", "installed"))
    else:
        findings.append(
            Finding(
                WARN,
                "cdk/node_modules",
                "not installed",
                "The launcher runs `npm ci` in cdk/ before deploying.",
            )
        )
    cdk = toolchain.cdk_available(ctx.cdk_dir)
    if cdk.present:
        status = PASS if "pinned" in cdk.name else WARN
        remedy = (
            ""
            if status == PASS
            else "A pinned local CDK is preferred — `npm ci` in cdk/ provides it."
        )
        findings.append(
            Finding(
                status, cdk.name, (cdk.version or "present").splitlines()[0], remedy
            )
        )
    else:
        findings.append(
            Finding(
                WARN,
                "cdk",
                "not resolved yet",
                "Provided by `npm ci` in cdk/; no global install needed.",
            )
        )
    return findings


def _check_container_runtime(ctx: Ctx) -> list[Finding]:
    deployment_type = str(configfile.get(ctx.config, "backend.deployment_type", "zip"))
    runtime = toolchain.container_runtime()
    if deployment_type != "docker":
        detail = f"not required (backend.deployment_type: {deployment_type})"
        return [Finding(PASS, "Container runtime", detail)]
    if runtime.present and runtime.version:
        return [Finding(PASS, f"Container runtime ({runtime.name})", runtime.version)]
    return [
        Finding(
            FAIL,
            "Container runtime",
            "required by backend.deployment_type: docker",
            "Start Docker or Finch, or set backend.deployment_type: zip in cdk/config.yaml.",
        )
    ]


def _check_config(ctx: Ctx) -> list[Finding]:
    relative = ctx.config_path.relative_to(ctx.repo_root)
    if not ctx.config_path.exists():
        return [
            Finding(
                WARN,
                str(relative),
                "not created yet",
                "Run `python3 launch.py configure` to generate it.",
            )
        ]
    findings: list[Finding] = []
    try:
        config = ctx.reload_config()
    except LauncherError as exc:
        return [Finding(FAIL, str(relative), exc.message, exc.hint or "")]

    stack_name = configfile.get(config, "stack_name_base")
    if not stack_name:
        findings.append(
            Finding(
                FAIL,
                "stack_name_base",
                "missing",
                "Re-run `configure` to regenerate config.yaml.",
            )
        )
    else:
        problem = configfile.validate_stack_name(str(stack_name))
        if problem:
            findings.append(
                Finding(FAIL, "stack_name_base", f"{stack_name} — {problem}", "")
            )
        else:
            findings.append(Finding(PASS, "stack_name_base", str(stack_name)))

    for key in ("admin_user_email", "notification.ses_sender_email"):
        value = configfile.get(config, key)
        if value:
            problem = configfile.validate_email(str(value))
            if problem:
                findings.append(Finding(FAIL, key, f"{value} — {problem}", ""))

    if not configfile.get(config, "sap.base_url"):
        findings.append(
            Finding(
                WARN,
                "sap.base_url",
                "not set",
                "SAP polling and credential sync stay disabled until this is set. Fine for a first look.",
            )
        )
    return findings


def _check_aws(ctx: Ctx) -> list[Finding]:
    findings: list[Finding] = []
    try:
        region = ctx.region
    except LauncherError as exc:
        return [Finding(FAIL, "AWS Region", exc.message, exc.hint or "")]
    findings.append(Finding(PASS, "AWS Region", f"{region} (from {ctx.region_source})"))

    identity = ctx.aws.caller_identity()
    if not identity:
        return [
            *findings,
            Finding(
                FAIL,
                "AWS credentials",
                "not usable",
                "Run `aws sso login`, `aws configure`, or set AWS_PROFILE. Expired sessions look like this too.",
            ),
        ]
    findings.append(Finding(PASS, "AWS account", identity.get("Account", "?")))
    findings.append(Finding(PASS, "Caller", identity.get("Arn", "?")))
    findings.append(Finding(PASS, "Credential source", ctx.profile_source))

    reachable = ctx.aws.bedrock_reachable()
    if reachable is True:
        findings.append(
            Finding(
                PASS,
                "Bedrock API",
                f"reachable in {region}",
                note=(
                    "Reachability is not model access. Confirm the Claude models are enabled under "
                    "Bedrock -> Model access; the launcher will not make a billable call to prove it."
                ),
            )
        )
    elif reachable is False:
        findings.append(
            Finding(
                FAIL,
                "Bedrock API",
                "access denied",
                "Grant bedrock:ListFoundationModels, and enable Claude model access in the Bedrock console.",
            )
        )
    else:
        findings.append(
            Finding(
                WARN,
                "Bedrock API",
                "could not be verified",
                f"Check that Bedrock and AgentCore are available in {region}.",
            )
        )
    return findings


def run(ctx: Ctx, *, quiet: bool = False) -> int:
    """Report readiness. Returns an exit code; 3 when something must be fixed."""
    if not quiet:
        ui.heading("Environment check")

    groups: list[tuple[str, Callable[[], list[Finding]]]] = [
        ("Runtimes", _check_runtimes),
        ("CDK toolchain", lambda: _check_cdk(ctx)),
        ("Configuration", lambda: _check_config(ctx)),
        ("Container runtime", lambda: _check_container_runtime(ctx)),
        ("AWS access", lambda: _check_aws(ctx)),
    ]

    failures = 0
    warnings = 0
    # Evaluated one group at a time so output appears while the AWS probes run,
    # rather than after several seconds of apparent hang.
    for title, check in groups:
        findings = check()
        if not findings:
            continue
        print()
        print(f"  {title}")
        for finding in findings:
            _emit(finding)
            failures += finding.status == FAIL
            warnings += finding.status == WARN

    ui.blank()
    if failures:
        ui.err(f"{failures} blocking issue(s), {warnings} warning(s).")
        ui.hint("Fix the items marked above, then re-run `python3 launch.py doctor`.")
        return EXIT_PREREQ
    if warnings:
        ui.ok(f"Ready to deploy, with {warnings} warning(s) worth reading.")
    else:
        ui.ok("Ready to deploy.")
    return 0
