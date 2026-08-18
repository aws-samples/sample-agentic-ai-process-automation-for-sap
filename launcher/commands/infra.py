# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""CDK bootstrap, diff, and deploy.

Wraps the existing CDK app rather than reimplementing it. The stacks are the
source of truth; this module's job is to invoke them with a consistent
toolchain and to turn the common failures into something actionable.
"""

from __future__ import annotations

from .. import shell, state, toolchain, ui
from ..context import Ctx
from ..errors import DeployError

PHASE_DEPENDENCIES = "cdk-dependencies"
PHASE_BOOTSTRAP = "cdk-bootstrap"
PHASE_DEPLOY = "cdk-deploy"

# Failure substrings mapped to guidance. The underlying output is always shown;
# this only adds the "what now" the raw error omits.
_DIAGNOSES = (
    (
        "need to perform AWS CDK bootstrap",
        "Run `python3 launch.py deploy` again — bootstrap runs first, or bootstrap manually with `cdk bootstrap`.",
    ),
    (
        "ExpiredToken",
        "Your AWS session expired. Re-authenticate (`aws sso login`) and re-run — completed stacks are skipped.",
    ),
    (
        "AccessDenied",
        "The deploying principal is missing permissions. CDK needs to create IAM roles, Lambda functions, and Bedrock resources.",
    ),
    (
        "Cannot find module",
        "CDK dependencies are incomplete. Delete cdk/node_modules and re-run.",
    ),
    (
        "Bundling asset",
        "A Lambda bundle failed. Check `pip` is on PATH; set backend.deployment_type to docker and start Docker/Finch as a fallback.",
    ),
    (
        "cannot change the physical resource ID",
        "A custom resource returned an inconsistent physical ID on delete — the PolicyEngine provider "
        "does this when it never created a policy store. Retry with "
        "`aws cloudformation delete-stack --stack-name <stack> --retain-resources PolicyEngine`; "
        "check for orphans first with `aws verifiedpermissions list-policy-stores`.",
    ),
    (
        "already has 5 trails",
        "CloudTrail allows only 5 trails per Region and it is a hard limit, not a raisable quota. "
        "Each deployment of this sample creates one. Free a slot, or remove the SsmTrail from "
        "cdk/lib/constructs/observability.ts if you do not need the autonomy-change alarm.",
    ),
    (
        "LimitExceeded",
        "An account or Region limit was reached. Check Service Quotas for the service named in the error — "
        "some limits are hard and cannot be raised.",
    ),
    (
        "ROLLBACK_FAILED",
        "The rollback failed, so the stack cannot be updated or resumed. Run `python3 launch.py status` "
        "for the cause, then delete the stack before retrying.",
    ),
    (
        "ROLLBACK_COMPLETE",
        "A stack is in ROLLBACK_COMPLETE and cannot be updated. Run `python3 launch.py status` to see the "
        "failure, then delete the stack before retrying.",
    ),
    (
        "ModuleNotFoundError: No module named 'yaml'",
        "run_emit.py needs PyYAML. Run `pip install pyyaml`.",
    ),
)


def _diagnose(output: str) -> str | None:
    for needle, guidance in _DIAGNOSES:
        if needle in output:
            return guidance
    return None


def install_dependencies(ctx: Ctx, *, force: bool = False) -> None:
    """Install cdk/ dependencies from the lockfile."""
    if not force and toolchain.cdk_dependencies_installed(ctx.cdk_dir):
        ui.ok("CDK dependencies already installed.")
        return
    lockfile = ctx.cdk_dir / "package-lock.json"
    command = ["npm", "ci"] if lockfile.exists() else ["npm", "install"]
    ui.info(f"Installing CDK dependencies (`{' '.join(command)}` in cdk/)...")
    state.mark(ctx, PHASE_DEPENDENCIES, state.RUNNING)
    result = shell.run(
        command,
        cwd=ctx.cdk_dir,
        check=False,
        timeout=None,
        verbose=ctx.verbose,
    )
    if not result.ok:
        state.mark(ctx, PHASE_DEPENDENCIES, state.FAILED)
        ui.tail_output(result.output, lines=20, label="npm")
        raise DeployError(
            "Installing CDK dependencies failed.",
            hint="Check network access to the npm registry, then retry.",
        )
    state.mark(ctx, PHASE_DEPENDENCIES, state.DONE)
    ui.ok("CDK dependencies installed.")


def bootstrap(ctx: Ctx) -> None:
    """Bootstrap the account/Region if it is not already bootstrapped."""
    toolkit = ctx.aws.describe_stack("CDKToolkit")
    if toolkit and str(toolkit.get("StackStatus", "")).endswith("_COMPLETE"):
        ui.ok(f"CDK already bootstrapped in {ctx.account}/{ctx.region}.")
        state.mark(ctx, PHASE_BOOTSTRAP, state.DONE, detail="already bootstrapped")
        return

    ui.info(f"Bootstrapping CDK in {ctx.account}/{ctx.region}...")
    state.mark(ctx, PHASE_BOOTSTRAP, state.RUNNING)
    argv = [
        *toolchain.cdk_command(ctx.cdk_dir),
        "bootstrap",
        f"aws://{ctx.account}/{ctx.region}",
    ]
    result = shell.run(
        argv,
        cwd=ctx.cdk_dir,
        env=ctx.aws.env(),
        check=False,
        timeout=None,
        verbose=ctx.verbose,
    )
    if not result.ok:
        state.mark(ctx, PHASE_BOOTSTRAP, state.FAILED)
        ui.tail_output(result.output, lines=25, label="cdk bootstrap")
        raise DeployError("CDK bootstrap failed.", hint=_diagnose(result.output))
    state.mark(ctx, PHASE_BOOTSTRAP, state.DONE)
    ui.ok("CDK bootstrapped.")


def diff(ctx: Ctx) -> int:
    """Show pending changes, including IAM. Read-only."""
    ui.heading("Pending changes")
    install_dependencies(ctx)
    argv = [*toolchain.cdk_command(ctx.cdk_dir), "diff", "--all"]
    result = shell.run(
        argv,
        cwd=ctx.cdk_dir,
        env=ctx.aws.env(),
        stream=True,
        check=False,
        timeout=None,
        verbose=ctx.verbose,
    )
    # `cdk diff` exits non-zero when differences exist, which is not an error.
    return 0 if result.code in (0, 1) else result.code


def synth(ctx: Ctx) -> int:
    """Synthesize without bundling — the fast validity check."""
    ui.heading("Synth check")
    install_dependencies(ctx)
    argv = [
        *toolchain.cdk_command(ctx.cdk_dir),
        "synth",
        "--no-staging",
        "--quiet",
        "--no-bundling",
    ]
    result = shell.run(
        argv,
        cwd=ctx.cdk_dir,
        env=ctx.aws.env(),
        check=False,
        timeout=None,
        verbose=ctx.verbose,
    )
    if not result.ok:
        ui.tail_output(result.output, lines=30, label="cdk synth")
        raise DeployError("CDK synth failed.", hint=_diagnose(result.output))
    ui.ok("Synth succeeded — the CDK app and configuration are valid.")
    return 0


def deploy(ctx: Ctx) -> None:
    """Deploy every stack this configuration defines."""
    ui.heading("Infrastructure")
    install_dependencies(ctx)
    bootstrap(ctx)

    ui.blank()
    ui.info(
        "Deploying stacks. CloudFormation events stream below; this usually takes 15-25 minutes."
    )
    state.mark(ctx, PHASE_DEPLOY, state.RUNNING)
    argv = [
        *toolchain.cdk_command(ctx.cdk_dir),
        "deploy",
        "--all",
        "--require-approval",
        "never",
        "--progress",
        "events",
    ]
    result = shell.run(
        argv,
        cwd=ctx.cdk_dir,
        env=ctx.aws.env(),
        stream=True,
        check=False,
        timeout=None,
        verbose=ctx.verbose,
    )
    if not result.ok:
        state.mark(ctx, PHASE_DEPLOY, state.FAILED, exit_code=result.code)
        raise DeployError(
            f"CDK deploy failed (exit {result.code}).",
            hint="Run `python3 launch.py status` for the failing resource, then `python3 launch.py resume`.",
        )
    state.mark(ctx, PHASE_DEPLOY, state.DONE)
    ui.blank()
    ui.ok("All stacks deployed.")
