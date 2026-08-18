# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Shared run context: paths, deployment target, and one region rule.

The scripts this replaces resolved the AWS Region five different ways, and
three of them silently defaulted to us-east-1. Silently choosing a Region is
how a sample gets deployed to the wrong one. There is one rule here, it is
explicit, and it never invents a default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

from . import awsx, configfile, ui
from .errors import AwsError, ConfigError

# Stack suffixes created by cdk/lib/main-stack.ts, in deploy order.
STACK_SUFFIXES = ("frontend", "cognito", "backend", "demo", "sap-mcp")
ALWAYS_DEPLOYED = ("frontend", "cognito", "backend")


@dataclass
class Ctx:
    """Everything a command needs that is not command-specific."""

    repo_root: Path
    prompter: ui.Prompter
    region_override: str | None = None
    profile: str | None = None
    verbose: bool = False
    region_source: str = field(default="unresolved", init=False)
    _region: str | None = field(default=None, init=False, repr=False)

    # ── paths ────────────────────────────────────────────────────────────
    @property
    def cdk_dir(self) -> Path:
        return self.repo_root / "cdk"

    @property
    def config_path(self) -> Path:
        return self.cdk_dir / "config.yaml"

    @property
    def config_template(self) -> Path:
        return self.cdk_dir / "config.yaml.example"

    @property
    def frontend_dir(self) -> Path:
        return self.repo_root / "frontend"

    @property
    def scripts_dir(self) -> Path:
        return self.repo_root / "scripts"

    @property
    def knowledge_base_dir(self) -> Path:
        return self.repo_root / "knowledge-base"

    @property
    def state_dir(self) -> Path:
        return self.repo_root / ".launcher"

    @property
    def version(self) -> str:
        path = self.repo_root / "VERSION"
        if path.exists():
            return path.read_text(encoding="utf-8").strip() or "unknown"
        return "unknown"

    def commit(self) -> str | None:
        from . import shell  # noqa: PLC0415 - avoid an import cycle at module load

        return shell.capture(
            ["git", "-C", str(self.repo_root), "rev-parse", "--short", "HEAD"],
            timeout=15,
        )

    # ── config ───────────────────────────────────────────────────────────
    @cached_property
    def config(self) -> dict[str, Any]:
        return configfile.load(self.config_path)

    def reload_config(self) -> dict[str, Any]:
        self.__dict__.pop("config", None)
        return self.config

    def require_config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            raise ConfigError(
                f"{self.config_path.relative_to(self.repo_root)} does not exist.",
                hint="Run `python3 launch.py configure` first.",
            )
        return self.config

    @property
    def stack_base(self) -> str:
        value = configfile.get(self.require_config(), "stack_name_base")
        if not value:
            raise ConfigError(
                "stack_name_base is not set in cdk/config.yaml.",
                hint="Run `python3 launch.py configure` to regenerate the file.",
            )
        return str(value)

    def stack_name(self, suffix: str) -> str:
        return f"{self.stack_base}-{suffix}"

    def expected_stacks(self) -> list[str]:
        """Stack names this configuration will actually create."""
        names = [self.stack_name(suffix) for suffix in ALWAYS_DEPLOYED]
        config = self.config
        demo_all = bool(configfile.get(config, "demo.enabled", False))
        if demo_all or configfile.get(config, "demo.test_data.enabled", False):
            names.append(self.stack_name("demo"))
        if configfile.get(config, "sap_mcp.enabled", False):
            names.append(self.stack_name("sap-mcp"))
        return names

    # ── deployment target ────────────────────────────────────────────────
    @property
    def region(self) -> str:
        """Resolve the Region once, explicitly, in a documented order.

        --region → AWS_REGION → AWS_DEFAULT_REGION → `aws configure get region`
        → ask. Never guessed.
        """
        if self._region:
            return self._region
        resolved = self.region_override or awsx.region_from_environment()
        source = "--region" if self.region_override else "environment"
        if not resolved:
            resolved = awsx.Aws(profile=self.profile).configured_region()
            source = "aws config"
        if not resolved:
            ui.warn("No AWS Region is configured.")
            hint = "Set AWS_REGION, run `aws configure`, or pass --region."
            ui.hint(hint)
            resolved = self.prompter.ask("Region to deploy to", default=None)
            source = "prompt"
        if not resolved:
            raise AwsError("No AWS Region resolved.", hint="Pass --region explicitly.")
        self._region = resolved
        self.region_source = source
        return resolved

    @cached_property
    def aws(self) -> awsx.Aws:
        return awsx.Aws(region=self.region, profile=self.profile)

    @cached_property
    def identity(self) -> dict[str, str]:
        return self.aws.require_caller_identity()

    @property
    def account(self) -> str:
        return self.identity.get("Account", "unknown")

    @property
    def caller_arn(self) -> str:
        return self.identity.get("Arn", "unknown")

    @property
    def profile_source(self) -> str:
        if self.profile:
            return f"--profile {self.profile}"
        import os  # noqa: PLC0415 - trivial, keeps module imports lean

        for name in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE"):
            if os.environ.get(name):
                return f"{name}={os.environ[name]}"
        if os.environ.get("AWS_ACCESS_KEY_ID"):
            return "AWS_ACCESS_KEY_ID (environment credentials)"
        return "default credential chain"
