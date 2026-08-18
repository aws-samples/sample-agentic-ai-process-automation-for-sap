# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""AWS access for the launcher.

Reads go through the AWS CLI, which is already a documented prerequisite and
needs no Python packages — so `doctor` works on a clean clone.

Secret *writes* never pass through a process argument list. `ps` and
/proc/<pid>/cmdline expose argv to other users on the host. Writes prefer
boto3 when it is importable and otherwise feed the CLI an owner-only file.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from . import shell
from .errors import AwsError

# CloudFormation states that mean "no usable stack of this name right now".
_MISSING_MARKERS = ("does not exist", "ValidationError")


class Aws:
    """Thin, explicit AWS façade. One region and profile per instance."""

    def __init__(
        self, *, region: str | None = None, profile: str | None = None
    ) -> None:
        self.region = region
        self.profile = profile

    # ── plumbing ─────────────────────────────────────────────────────────
    def _argv(self, args: Sequence[str]) -> list[str]:
        argv = ["aws"]
        if self.profile:
            argv += ["--profile", self.profile]
        if self.region:
            argv += ["--region", self.region]
        return argv + list(args)

    def env(self) -> dict[str, str]:
        """Environment describing this instance's target, for child processes."""
        out: dict[str, str] = {}
        if self.region:
            out["AWS_REGION"] = self.region
            out["AWS_DEFAULT_REGION"] = self.region
        if self.profile:
            out["AWS_PROFILE"] = self.profile
        return out

    def text(self, args: Sequence[str], *, timeout: int | None = 120) -> str | None:
        return shell.capture(self._argv(args), timeout=timeout)

    def json(
        self,
        args: Sequence[str],
        *,
        timeout: int | None = 120,
        default: Any = None,
    ) -> Any:
        raw = shell.capture(self._argv([*args, "--output", "json"]), timeout=timeout)
        if raw is None:
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default

    def require_json(
        self,
        args: Sequence[str],
        *,
        what: str,
        hint: str | None = None,
        timeout: int | None = 120,
    ) -> Any:
        result = shell.run(
            self._argv([*args, "--output", "json"]),
            timeout=timeout,
            check=False,
        )
        if not result.ok:
            raise AwsError(
                f"Could not {what}.", hint=hint or _first_line(result.output)
            )
        try:
            return json.loads(result.output)
        except json.JSONDecodeError as exc:
            raise AwsError(f"Unexpected response while trying to {what}.") from exc

    def _write_via_file(
        self, service: str, operation: str, payload: Mapping[str, Any]
    ) -> Any:
        """Call a mutating API with the payload in a file, never in argv.

        The payload goes through an owner-only temp file rather than
        `file:///dev/stdin`: aws-cli 2.36 rejects that path with
        "Invalid JSON received" for any input, which silently broke every
        mutating call routed through here.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            payload_path = Path(tmpdir) / "payload.json"
            payload_path.write_text(json.dumps(payload), encoding="utf-8")
            payload_path.chmod(0o600)
            result = shell.run(
                self._argv(
                    [service, operation, "--cli-input-json", f"file://{payload_path}"]
                ),
                check=False,
                tail=None,
                timeout=120,
            )
        if not result.ok:
            raise AwsError(
                f"{service} {operation} failed.",
                hint=_first_line(result.output),
            )
        try:
            return json.loads(result.output or "{}")
        except json.JSONDecodeError:
            return {}

    def _boto3(self, service: str) -> Any | None:
        try:
            import boto3  # noqa: PLC0415 - optional, probed at call time
        except ImportError:
            return None
        kwargs: dict[str, Any] = {}
        if self.region:
            kwargs["region_name"] = self.region
        session = (
            boto3.Session(profile_name=self.profile)
            if self.profile
            else boto3.Session()
        )
        return session.client(service, **kwargs)

    # ── identity ─────────────────────────────────────────────────────────
    def caller_identity(self) -> dict[str, str] | None:
        return self.json(["sts", "get-caller-identity"])

    def require_caller_identity(self) -> dict[str, str]:
        identity = self.caller_identity()
        if not identity:
            raise AwsError(
                "AWS credentials are not usable.",
                hint="Run `aws sso login`, `aws configure`, or set AWS_PROFILE, then retry.",
            )
        return identity

    def configured_region(self) -> str | None:
        return self.text(["configure", "get", "region"], timeout=15)

    def assume_role(
        self, role_arn: str, session_name: str, *, duration: int = 3600
    ) -> dict[str, str]:
        payload = self.require_json(
            [
                "sts",
                "assume-role",
                "--role-arn",
                role_arn,
                "--role-session-name",
                session_name,
                "--duration-seconds",
                str(duration),
            ],
            what=f"assume {role_arn}",
            hint="Your caller needs sts:AssumeRole on that role, and the role's trust policy must allow you.",
        )
        creds = payload["Credentials"]
        return {
            "AWS_ACCESS_KEY_ID": creds["AccessKeyId"],
            "AWS_SECRET_ACCESS_KEY": creds["SecretAccessKey"],
            "AWS_SESSION_TOKEN": creds["SessionToken"],
        }

    # ── CloudFormation ───────────────────────────────────────────────────
    def describe_stack(self, name: str) -> dict[str, Any] | None:
        """Return the stack description, or None when it does not exist."""
        result = shell.run(
            self._argv(
                [
                    "cloudformation",
                    "describe-stacks",
                    "--stack-name",
                    name,
                    "--output",
                    "json",
                ]
            ),
            check=False,
            tail=None,
            timeout=60,
        )
        if not result.ok:
            if any(marker in result.output for marker in _MISSING_MARKERS):
                return None
            raise AwsError(
                f"Could not describe stack {name}.", hint=_first_line(result.output)
            )
        try:
            stacks = json.loads(result.output).get("Stacks") or []
        except json.JSONDecodeError:
            return None
        return stacks[0] if stacks else None

    def stack_outputs(self, name: str) -> dict[str, str]:
        stack = self.describe_stack(name)
        if not stack:
            return {}
        return {
            item["OutputKey"]: item.get("OutputValue", "")
            for item in stack.get("Outputs") or []
            if "OutputKey" in item
        }

    def stack_failure_events(
        self, name: str, limit: int = 5
    ) -> list[tuple[str, str, str]]:
        """Root-cause failure events as (logical id, status, reason)."""
        payload = self.json(
            ["cloudformation", "describe-stack-events", "--stack-name", name],
            default={},
        )
        return root_cause_failures(payload.get("StackEvents") or [], limit=limit)

    # ── SSM ──────────────────────────────────────────────────────────────
    def ssm_get(self, name: str) -> str | None:
        return self.text(
            [
                "ssm",
                "get-parameter",
                "--name",
                name,
                "--query",
                "Parameter.Value",
                "--output",
                "text",
            ],
            timeout=30,
        )

    def ssm_require(self, name: str, *, hint: str | None = None) -> str:
        value = self.ssm_get(name)
        if not value:
            raise AwsError(
                f"SSM parameter {name} not found.",
                hint=hint or "Deploy the infrastructure first, then retry.",
            )
        return value

    def ssm_put(self, name: str, value: str) -> None:
        shell.run(
            self._argv(
                [
                    "ssm",
                    "put-parameter",
                    "--name",
                    name,
                    "--value",
                    value,
                    "--type",
                    "String",
                    "--overwrite",
                ]
            ),
            timeout=30,
            error_message=f"Could not write SSM parameter {name}.",
        )

    # ── Secrets Manager ──────────────────────────────────────────────────
    def secret_get_string(self, secret_id: str) -> str | None:
        return self.text(
            [
                "secretsmanager",
                "get-secret-value",
                "--secret-id",
                secret_id,
                "--query",
                "SecretString",
                "--output",
                "text",
            ],
            timeout=30,
        )

    def secret_put_string(self, secret_id: str, secret_string: str) -> None:
        """Store a new secret version without exposing the value in argv."""
        client = self._boto3("secretsmanager")
        if client is not None:
            try:
                client.put_secret_value(SecretId=secret_id, SecretString=secret_string)
                return
            except Exception as exc:  # noqa: BLE001 - surface the AWS message verbatim
                raise AwsError(
                    "Could not update the secret.", hint=str(exc).splitlines()[0]
                ) from exc
        self._write_via_file(
            "secretsmanager",
            "put-secret-value",
            {"SecretId": secret_id, "SecretString": secret_string},
        )

    # ── Lambda ───────────────────────────────────────────────────────────
    def lambda_names_with_prefix(self, prefix: str) -> list[str]:
        payload = self.json(
            [
                "lambda",
                "list-functions",
                "--query",
                f"Functions[?starts_with(FunctionName, '{prefix}')].FunctionName",
            ],
            default=[],
            timeout=180,
        )
        return sorted(payload or [])

    def lambda_names_with_layer(self, layer_fragment: str) -> list[str]:
        payload = self.json(["lambda", "list-functions"], default={}, timeout=180)
        names: list[str] = []
        for function in payload.get("Functions") or []:
            for layer in function.get("Layers") or []:
                if layer_fragment in layer.get("Arn", ""):
                    names.append(function["FunctionName"])
                    break
        return sorted(names)

    def lambda_environment(self, name: str) -> dict[str, str] | None:
        """Current env vars, or None when they cannot be read.

        None is distinct from {}: `update-function-configuration --environment`
        replaces the whole map, so a failed read must abort the update rather
        than be treated as "no variables" and wipe the function's config.
        """
        result = shell.run(
            self._argv(
                [
                    "lambda",
                    "get-function-configuration",
                    "--function-name",
                    name,
                    "--query",
                    "Environment.Variables",
                    "--output",
                    "json",
                ]
            ),
            check=False,
            tail=None,
            timeout=60,
        )
        if not result.ok:
            return None
        try:
            parsed = json.loads(result.output or "null")
        except json.JSONDecodeError:
            return None
        return parsed or {}

    def lambda_set_environment(self, name: str, variables: Mapping[str, str]) -> None:
        self._write_via_file(
            "lambda",
            "update-function-configuration",
            {"FunctionName": name, "Environment": {"Variables": dict(variables)}},
        )

    def lambda_wait_updated(self, name: str) -> bool:
        result = shell.run(
            self._argv(["lambda", "wait", "function-updated", "--function-name", name]),
            check=False,
            tail=None,
            timeout=300,
        )
        return result.ok

    # ── S3 ───────────────────────────────────────────────────────────────
    def s3_keys(self, bucket: str) -> list[str]:
        payload = self.json(
            [
                "s3api",
                "list-objects-v2",
                "--bucket",
                bucket,
                "--query",
                "Contents[].Key",
            ],
            default=[],
            timeout=180,
        )
        return sorted(payload or [])

    def s3_sync(
        self,
        local_dir: str,
        bucket: str,
        *,
        delete: bool,
        env: Mapping[str, str] | None = None,
        dry_run: bool = False,
    ) -> shell.Result:
        argv = self._argv(["s3", "sync", local_dir, f"s3://{bucket}/"])
        if delete:
            argv.append("--delete")
        if dry_run:
            argv.append("--dryrun")
        return shell.run(
            argv,
            env=dict(env) if env else None,
            stream=not dry_run,
            check=False,
            timeout=None,
        )

    # ── Bedrock knowledge bases ──────────────────────────────────────────
    def kb_data_source_ids(self, kb_id: str) -> list[str]:
        payload = self.json(
            ["bedrock-agent", "list-data-sources", "--knowledge-base-id", kb_id],
            default={},
            timeout=60,
        )
        return [
            item["dataSourceId"]
            for item in payload.get("dataSourceSummaries") or []
            if "dataSourceId" in item
        ]

    def kb_start_ingestion(self, kb_id: str, data_source_id: str) -> str | None:
        payload = self.json(
            [
                "bedrock-agent",
                "start-ingestion-job",
                "--knowledge-base-id",
                kb_id,
                "--data-source-id",
                data_source_id,
            ],
            default={},
            timeout=60,
        )
        return (payload.get("ingestionJob") or {}).get("ingestionJobId")

    # ── Bedrock model reachability ───────────────────────────────────────
    def bedrock_reachable(self) -> bool | None:
        """True/False if the Bedrock control plane answered, None if unknown.

        This proves the API is reachable in-region. It does not prove the
        account has been granted access to a specific model — only a real
        invocation does that, and the launcher will not make a billable call.
        """
        raw = self.text(
            [
                "bedrock",
                "list-foundation-models",
                "--by-provider",
                "anthropic",
                "--query",
                "modelSummaries[0].modelId",
                "--output",
                "text",
            ],
            timeout=45,
        )
        if raw:
            return True
        probe = shell.run(
            self._argv(
                [
                    "bedrock",
                    "list-foundation-models",
                    "--query",
                    "modelSummaries[0].modelId",
                    "--output",
                    "text",
                ]
            ),
            check=False,
            tail=None,
            timeout=45,
        )
        if probe.ok:
            return True
        if "AccessDenied" in probe.output or "UnrecognizedClient" in probe.output:
            return False
        return None


def _first_line(text: str) -> str | None:
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None


def region_from_environment() -> str | None:
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or None


# Reasons that describe a consequence rather than a cause. In a rollback these
# outnumber the real failure by an order of magnitude.
_KNOCK_ON_REASONS = (
    "resource creation cancelled",
    "resource update cancelled",
    "resource creation initiated",
)


def root_cause_failures(
    events: Sequence[Mapping[str, Any]],
    *,
    limit: int = 5,
) -> list[tuple[str, str, str]]:
    """Pick the failures worth reading, earliest first.

    DescribeStackEvents returns newest-first, but in a rollback the *first*
    failure is the cause and everything after it is fallout. Taking the newest
    events — as this did originally — reliably hid the one message that
    explained the failure behind a wall of "Resource creation cancelled".
    """
    failures: list[tuple[str, str, str, str]] = []
    for event in events:
        status = str(event.get("ResourceStatus", ""))
        if "FAILED" not in status:
            continue
        reason = str(event.get("ResourceStatusReason") or "").strip()
        lowered = reason.lower()
        if any(noise in lowered for noise in _KNOCK_ON_REASONS):
            continue
        if "cancelled" in lowered and "other resource" in lowered:
            continue
        failures.append(
            (
                str(event.get("Timestamp") or ""),
                str(event.get("LogicalResourceId", "?")),
                status,
                reason,
            )
        )
    failures.sort(key=lambda item: item[0])
    return [
        (logical, status, reason) for _, logical, status, reason in failures[:limit]
    ]
