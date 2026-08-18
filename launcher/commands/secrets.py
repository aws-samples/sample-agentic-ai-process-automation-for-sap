# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Credential synchronisation for SAP and the notification channel.

Ported from `sync-sap-secret.sh` and `sync-channel-secret.sh`. The behavioural
change is the secret boundary. Those scripts passed plaintext secrets through
`python3 -c` argv and then through `aws ... --secret-string`, so the password
was visible in `ps` and /proc/<pid>/cmdline for the life of each call. Here a
secret is read with `getpass`, merged in memory, and written through a path
that never places it in an argument list.
"""

from __future__ import annotations

import json

from .. import configfile, state, ui
from ..commands import refresh
from ..context import Ctx
from ..errors import AwsError, Cancelled, ConfigError, LauncherError

PHASE_SAP = "sap-credentials"
PHASE_CHANNEL = "channel-secret"

PLACEHOLDER = "PLACEHOLDER"
_SSM_SAP_ARN = "/{stack}/secrets/sap-credentials-arn"

# Channels that authenticate outbound only and have no inbound webhook to sign.
_CHANNELS_WITHOUT_WEBHOOK = ("ses", "tickets")


def _load_secret(ctx: Ctx, secret_arn: str) -> dict[str, object]:
    raw = ctx.aws.secret_get_string(secret_arn)
    if raw is None:
        raise AwsError(
            "Could not read the existing secret.",
            hint="Check that your caller has secretsmanager:GetSecretValue on it.",
        )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AwsError(
            "The stored secret is not valid JSON, so it cannot be safely merged.",
            hint="Inspect it in the Secrets Manager console before overwriting.",
        ) from exc
    if not isinstance(parsed, dict):
        raise AwsError("The stored secret is not a JSON object.")
    return parsed


def _describe(value: object) -> str:
    """Show whether a value is set without revealing it."""
    if not value:
        return "(unset)"
    if value == PLACEHOLDER:
        return "PLACEHOLDER (not yet configured)"
    return f"(set, {len(str(value))} chars)"


# ── SAP service-account credentials ──────────────────────────────────────


def sync_sap(ctx: Ctx, *, force: bool = False, skip_refresh: bool = False) -> int:
    ui.heading("SAP credentials")

    base_url = configfile.get(ctx.require_config(), "sap.base_url")
    if not base_url:
        raise ConfigError(
            "sap.base_url is not set in cdk/config.yaml.",
            hint="Set it and redeploy before syncing SAP credentials. Skip this step for a non-SAP walkthrough.",
        )

    secret_arn = ctx.aws.ssm_require(
        _SSM_SAP_ARN.format(stack=ctx.stack_base),
        hint="Deploy the infrastructure first — CDK creates the secret and this parameter.",
    )
    current = _load_secret(ctx, secret_arn)
    current_user = str(current.get("username") or "")
    current_password = str(current.get("password") or "")

    ui.kv(
        [
            ("stack", ctx.stack_base),
            ("secret", secret_arn.split(":secret:")[-1]),
            ("config base_url", base_url),
            ("stored base_url", current.get("base_url") or "(unset)"),
            ("stored username", current_user or "(unset)"),
            ("stored password", _describe(current_password)),
        ]
    )

    unset = PLACEHOLDER in (current_user, current_password) or not current_password
    if not (unset or force):
        ui.blank()
        ui.ok("Credentials are already set.")
        ui.hint("Use `--force` to replace them.")
        state.mark(ctx, PHASE_SAP, state.SKIPPED, reason="already set")
        return 0

    ui.blank()
    ui.detail(
        "The password is read without echo and is never written to disk, logs, or arguments."
    )
    username = ctx.prompter.ask(
        "SAP username",
        default=current_user if current_user and current_user != PLACEHOLDER else None,
    )
    password = ctx.prompter.ask_secret("SAP password")
    if password == PLACEHOLDER:
        raise Cancelled("Refusing to store the literal placeholder as a password.")

    merged = {
        **current,
        "base_url": base_url,
        "username": username,
        "password": password,
    }
    changed = (
        current.get("base_url") != base_url
        or current_user != username
        or current_password != password
    )

    state.mark(ctx, PHASE_SAP, state.RUNNING)
    ctx.aws.secret_put_string(secret_arn, json.dumps(merged))
    ui.blank()
    ui.ok(f"Stored a new secret version — base_url={base_url}, username={username}")

    if skip_refresh:
        ui.info(
            "Skipping the Lambda refresh; cached credentials persist until the next cold start."
        )
        state.mark(ctx, PHASE_SAP, state.DONE, refreshed=False)
        return 0
    if not changed and not force:
        ui.info("Values are unchanged — skipping the Lambda refresh.")
        state.mark(ctx, PHASE_SAP, state.DONE, refreshed=False)
        return 0

    ui.blank()
    outcome = refresh.bounce_sap_auth_consumers(ctx)
    state.mark(ctx, PHASE_SAP, state.DONE, refreshed=len(outcome.updated))
    if not outcome.clean:
        ui.warn(
            "Some functions did not refresh; they will pick up the new credentials on their next cold start."
        )
    return 0


# ── Notification channel webhook secret ──────────────────────────────────


def sync_channel(ctx: Ctx, *, force: bool = False) -> int:
    ui.heading("Notification channel secret")

    config = ctx.require_config()
    channel = str(configfile.get(config, "notification.channel") or "")
    if not channel:
        raise ConfigError(
            "notification.channel is not set in cdk/config.yaml.",
            hint="Set it to ses, jira, or servicenow.",
        )
    if channel in _CHANNELS_WITHOUT_WEBHOOK:
        ui.ok(f"Channel '{channel}' has no inbound webhook — nothing to sign.")
        state.mark(ctx, PHASE_CHANNEL, state.SKIPPED, reason=f"channel={channel}")
        return 0

    secret_arn = configfile.get(config, "notification.secret_arn")
    if not secret_arn:
        raise ConfigError(
            "notification.secret_arn is not set in cdk/config.yaml.",
            hint="Create the Secrets Manager secret holding the channel credentials, then set its ARN.",
        )

    current = _load_secret(ctx, str(secret_arn))
    existing = current.get("webhook_secret")
    ui.kv(
        [
            ("channel", channel),
            ("secret", str(secret_arn).split(":secret:")[-1]),
            ("webhook secret", _describe(existing)),
        ]
    )

    if existing and not force:
        ui.blank()
        ui.ok("A webhook signing secret is already stored.")
        ui.hint("Use `--force` to replace it.")
        state.mark(ctx, PHASE_CHANNEL, state.SKIPPED, reason="already set")
        return 0

    ui.blank()
    if channel == "jira":
        ui.detail(
            "Jira: the secret configured on the outgoing webhook in Jira settings."
        )
    elif channel == "servicenow":
        ui.detail(
            "ServiceNow: the shared secret configured on the business rule or REST message."
        )

    value = ctx.prompter.ask_secret("Webhook signing secret")
    merged = {**current, "webhook_secret": value}

    state.mark(ctx, PHASE_CHANNEL, state.RUNNING)
    ctx.aws.secret_put_string(str(secret_arn), json.dumps(merged))
    ui.ok("Stored a new secret version with the webhook signing secret.")
    state.mark(ctx, PHASE_CHANNEL, state.DONE)
    return 0


def sap_configured(ctx: Ctx) -> bool:
    """Whether the SAP credential step is applicable at all."""
    try:
        return bool(configfile.get(ctx.config, "sap.base_url"))
    except LauncherError:
        return False
