# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""The deployment-target gate shown before anything is written to AWS.

One screen that answers "what is about to change, and where". It defaults to
no, and it is the only place that explains what `--require-approval never`
suppresses — `cdk deploy` would otherwise create IAM roles and policies with
no summary at all.
"""

from __future__ import annotations

from .. import configfile, state, ui
from ..context import Ctx
from ..errors import Cancelled

# What a default deployment creates, in terms a reviewer can sanity-check.
RESOURCE_CLASSES = (
    "Bedrock AgentCore runtime, Gateway, and Memory",
    "Bedrock Knowledge Bases with S3 Vectors storage (SOPs, SAP API docs)",
    "Lambda functions, SQS FIFO queues, and an EventBridge schedule",
    "DynamoDB tables for case state",
    "Cognito user pool, app client, and hosted domain",
    "Amplify Hosting app plus S3 buckets for content and staging",
    "IAM roles and policies for each of the above",
    "CloudWatch log groups, metrics, and alarms",
)


def summary(ctx: Ctx) -> None:
    """Print the target and the change surface. Read-only."""
    ui.heading("Deployment target")
    ui.kv(
        [
            ("account", ctx.account),
            ("region", f"{ctx.region}  (from {ctx.region_source})"),
            ("caller", ctx.caller_arn),
            ("credentials", ctx.profile_source),
            ("stack prefix", ctx.stack_base),
        ]
    )

    ui.blank()
    print("  Stacks to deploy")
    ui.bullets(ctx.expected_stacks())

    config = ctx.config
    notes: list[str] = []
    if configfile.get(config, "sap.base_url"):
        notes.append(f"SAP endpoint: {configfile.get(config, 'sap.base_url')}")
    else:
        notes.append(
            "SAP endpoint: not configured — the OData poller will have nothing to poll"
        )
    notes.append(
        f"Cedar enforcement: {configfile.get(config, 'cedar_enforcement_mode', 'LOG_ONLY')}"
    )
    notes.append(
        f"Autonomy trigger mode: {configfile.get(config, 'autonomy.trigger_mode', 'manual')}"
    )
    notes.append(
        f"Backend packaging: {configfile.get(config, 'backend.deployment_type', 'zip')}"
    )
    notes.append(
        f"Network mode: {configfile.get(config, 'backend.network_mode', 'PUBLIC')}"
    )
    ui.blank()
    print("  Configuration")
    ui.bullets(notes)

    ui.blank()
    print("  Resource classes created")
    ui.bullets(RESOURCE_CLASSES)

    ui.blank()
    ui.warn("This creates billable AWS resources and IAM roles.")
    ui.detail(
        "IAM changes are applied without a per-resource prompt. Run "
        "`python3 launch.py diff` first if you need to review them."
    )
    ui.detail(
        "This sample is educational. Review and harden it before any production use."
    )

    differences = state.drifted(ctx)
    if differences:
        ui.blank()
        ui.warn("This target differs from the last recorded run:")
        ui.bullets(differences)


def confirm(ctx: Ctx) -> None:
    """Show the target and require an explicit yes. Raises Cancelled on no."""
    summary(ctx)
    ui.blank()
    if not ctx.prompter.confirm(
        f"Deploy {ctx.stack_base} to account {ctx.account} in {ctx.region}?",
        default=False,
    ):
        raise Cancelled("Deployment cancelled — no changes made.")
    state.record_target(ctx)
