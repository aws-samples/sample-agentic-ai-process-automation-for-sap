# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""`status` — what is deployed right now, from AWS rather than from local state.

Local state records what the launcher believes; this command asks
CloudFormation. When they disagree, AWS wins, and the disagreement is shown.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import state, ui
from ..context import ALWAYS_DEPLOYED, STACK_SUFFIXES, Ctx

# Outputs worth surfacing, in the order a user would want them.
_HIGHLIGHTS = (
    ("AmplifyUrl", "application URL"),
    ("CognitoUserPoolId", "Cognito user pool"),
    ("AgentRuntimeArn", "agent runtime"),
    ("GatewayUrl", "gateway"),
    ("FeedbackApiUrl", "API"),
    ("PolicyEnforcementMode", "Cedar mode"),
)

NOT_DEPLOYED = "not deployed"

_HEALTHY = ("CREATE_COMPLETE", "UPDATE_COMPLETE", "IMPORT_COMPLETE")
_IN_PROGRESS_MARKER = "_IN_PROGRESS"
_BROKEN = (
    "ROLLBACK_COMPLETE",
    "ROLLBACK_FAILED",
    "CREATE_FAILED",
    "UPDATE_FAILED",
    "DELETE_FAILED",
)


@dataclass
class StackState:
    name: str
    status: str
    outputs: dict[str, str]

    @property
    def healthy(self) -> bool:
        return self.status in _HEALTHY

    @property
    def in_progress(self) -> bool:
        return _IN_PROGRESS_MARKER in self.status

    @property
    def broken(self) -> bool:
        return self.status in _BROKEN or self.status.endswith("_FAILED")

    @property
    def missing(self) -> bool:
        return self.status == NOT_DEPLOYED


def collect(ctx: Ctx) -> list[StackState]:
    """Describe every stack this project can create, deployed or not."""
    found: list[StackState] = []
    for suffix in STACK_SUFFIXES:
        name = ctx.stack_name(suffix)
        stack = ctx.aws.describe_stack(name)
        if stack is None:
            # Optional stacks that were never enabled are not interesting.
            if suffix in ALWAYS_DEPLOYED:
                found.append(StackState(name, NOT_DEPLOYED, {}))
            continue
        outputs = {
            item["OutputKey"]: item.get("OutputValue", "")
            for item in stack.get("Outputs") or []
            if "OutputKey" in item
        }
        found.append(
            StackState(name, str(stack.get("StackStatus", "UNKNOWN")), outputs)
        )
    return found


def overall(stacks: list[StackState]) -> str:
    """One-word verdict for the deployment as a whole."""
    if not stacks or all(stack.missing for stack in stacks):
        return "not started"
    if any(stack.in_progress for stack in stacks):
        return "in progress"
    if any(stack.broken for stack in stacks):
        return "failed"
    if any(stack.missing for stack in stacks):
        return "partial"
    return "complete"


def run(ctx: Ctx, *, quiet: bool = False) -> int:
    if not quiet:
        ui.heading("Deployment status")

    ui.kv(
        [
            ("account", ctx.account),
            ("region", ctx.region),
            ("stack prefix", ctx.stack_base),
        ]
    )

    stacks = collect(ctx)
    verdict = overall(stacks)

    ui.blank()
    print("  Stacks")
    for stack in stacks:
        label = f"{stack.name}  {stack.status}"
        if stack.healthy:
            ui.ok(label)
        elif stack.in_progress:
            ui.info(label)
        elif stack.missing:
            ui.warn(label)
        else:
            ui.err(label)

    merged: dict[str, str] = {}
    for stack in stacks:
        merged.update(stack.outputs)
    highlights = [(label, merged[key]) for key, label in _HIGHLIGHTS if merged.get(key)]
    if highlights:
        ui.blank()
        print("  Endpoints")
        ui.kv(highlights, indent="    ")

    broken = [stack for stack in stacks if stack.broken]
    for stack in broken:
        failures = ctx.aws.stack_failure_events(stack.name)
        if not failures:
            continue
        ui.blank()
        print(f"  Failures in {stack.name}")
        for logical_id, status, reason in failures:
            ui.err(f"{logical_id} — {status}")
            if reason:
                ui.detail(reason)

    differences = state.drifted(ctx)
    if differences:
        ui.blank()
        ui.warn("Local launcher state does not match the current target:")
        ui.bullets(differences)

    ui.blank()
    if verdict == "complete":
        ui.ok("Deployment is complete.")
        if merged.get("AmplifyUrl"):
            ui.hint(f"Open {merged['AmplifyUrl']} and sign in.")
    elif verdict == "not started":
        ui.info("Nothing is deployed for this stack name.")
        ui.hint("Run `python3 launch.py` to deploy.")
    elif verdict == "in progress":
        ui.info(
            "A deployment is currently running. Wait for it to finish before starting another."
        )
    elif verdict == "partial":
        ui.warn("Some stacks are missing.")
        ui.hint("Run `python3 launch.py resume` to continue.")
    else:
        ui.err("At least one stack is in a failed state.")
        _failure_guidance(broken)
    return 0


# A stack in either of these states cannot be updated, so `resume` is the wrong
# advice — it has to be deleted first. Deletion is not automated here.
_UNRECOVERABLE = {
    "ROLLBACK_COMPLETE": (
        "This stack failed on its first create and cannot be updated. Delete it, then redeploy."
    ),
    "ROLLBACK_FAILED": (
        "The rollback itself failed, so the stack cannot be updated or resumed. Fix the cause "
        "above, then delete the stack — resources stuck in a transitional state can be retained "
        "with `aws cloudformation delete-stack --retain-resources <LogicalId>`."
    ),
    "DELETE_FAILED": (
        "Deletion failed part-way. Retry the delete, retaining the resources that would not go."
    ),
}


def _failure_guidance(broken: list[StackState]) -> None:
    """Advise per state. Resuming an unrecoverable stack silently does nothing."""
    blocked = [stack for stack in broken if stack.status in _UNRECOVERABLE]
    for stack in blocked:
        ui.hint(f"{stack.name}: {_UNRECOVERABLE[stack.status]}")
    if blocked:
        ui.detail(
            "The launcher does not delete stacks. Review them in the CloudFormation console first — "
            "deletion can remove data."
        )
        return
    ui.hint("Fix the cause above, then run `python3 launch.py resume`.")
