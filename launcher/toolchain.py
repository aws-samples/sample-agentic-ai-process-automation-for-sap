# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Local toolchain discovery: Node, npm, the AWS CLI, CDK, container runtime.

CDK resolution is the important part. The existing paths disagree — `setup.py`
installs and uses a *global* `aws-cdk`, while `make cdk-synth` uses the version
pinned in `cdk/package.json`. Those can be different versions against the same
stacks. Everything here prefers the pinned local binary, so the CDK version is
a property of the checkout rather than of the machine.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from . import shell
from .errors import EXIT_PREREQ, LauncherError

MIN_NODE_MAJOR = 20
MIN_PYTHON = (3, 10)


@dataclass(frozen=True)
class Tool:
    name: str
    path: str | None
    version: str | None = None

    @property
    def present(self) -> bool:
        return self.path is not None


def find(name: str, version_args: tuple[str, ...] = ("--version",)) -> Tool:
    path = shell.which(name)
    if not path:
        return Tool(name, None)
    return Tool(name, path, shell.capture([path, *version_args], timeout=30))


def node_major(version: str | None) -> int | None:
    if not version:
        return None
    match = re.search(r"(\d+)", version)
    return int(match.group(1)) if match else None


def python_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def has_pyyaml() -> bool:
    """PyYAML is required by `scripts/deploy/run_emit.py`, which `cdk/bin/app.ts`
    shells out to before synth. Without it, any non-default auth profile fails
    at synth rather than at a helpful moment."""
    try:
        import yaml  # noqa: F401, PLC0415 - presence probe
    except ImportError:
        return False
    return True


def cdk_command(cdk_dir: Path) -> list[str]:
    """The CDK invocation to use, preferring the version pinned in cdk/package.json."""
    local = cdk_dir / "node_modules" / ".bin" / "cdk"
    if local.exists():
        return [str(local)]
    if shell.which("npx"):
        return ["npx", "--no-install", "cdk"]
    globally = shell.which("cdk")
    if globally:
        return [globally]
    raise LauncherError(
        "No CDK binary available.",
        hint="Run `npm ci` in cdk/ to install the pinned version (preferred over a global install).",
        exit_code=EXIT_PREREQ,
    )


def cdk_available(cdk_dir: Path) -> Tool:
    """Probe CDK without raising, for `doctor`."""
    local = cdk_dir / "node_modules" / ".bin" / "cdk"
    if local.exists():
        return Tool(
            "cdk (pinned)",
            str(local),
            shell.capture([str(local), "--version"], timeout=60),
        )
    globally = shell.which("cdk")
    if globally:
        return Tool(
            "cdk (global)", globally, shell.capture([globally, "--version"], timeout=60)
        )
    return Tool("cdk", None)


def cdk_dependencies_installed(cdk_dir: Path) -> bool:
    return (cdk_dir / "node_modules").is_dir()


def container_runtime() -> Tool:
    """Docker or Finch. Only required when backend.deployment_type is `docker`."""
    for name in ("docker", "finch"):
        path = shell.which(name)
        if not path:
            continue
        # Presence on PATH is not enough — the daemon has to answer.
        probe = shell.capture(
            [path, "info", "--format", "{{.ServerVersion}}"], timeout=30
        )
        if probe:
            return Tool(name, path, probe)
        return Tool(f"{name} (not running)", path, None)
    return Tool("docker/finch", None)
