# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Subprocess execution.

Every command runs as an argument list with `shell=False`. The scripts this
replaces interpolated config values into shell strings, which meant a value in
`cdk/config.yaml` could become shell syntax. Nothing here can be reached by
that path.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from . import ui
from .errors import LauncherError


@dataclass(frozen=True)
class Result:
    code: int
    output: str  # combined stdout+stderr; empty when streamed

    @property
    def ok(self) -> bool:
        return self.code == 0


def which(name: str) -> str | None:
    return shutil.which(name)


def run(
    argv: Sequence[str],
    *,
    cwd: Path | str | None = None,
    env: Mapping[str, str] | None = None,
    stream: bool = False,
    tail: int | None = 25,
    timeout: int | None = None,
    check: bool = True,
    stdin_text: str | None = None,
    error_message: str | None = None,
    verbose: bool = False,
) -> Result:
    """Run `argv` and return the result.

    stream=True inherits the parent's stdout/stderr, so long operations such as
    `cdk deploy` show progress live. Streamed runs capture nothing, so `tail` is
    ignored for them.

    timeout=None means no limit. Deployments legitimately run for tens of
    minutes; a shared default timeout would kill them mid-flight.
    """
    argv = [str(token) for token in argv]
    if verbose:
        ui.detail(f"$ {' '.join(argv)}")

    merged_env = None
    if env is not None:
        merged_env = {**os.environ, **env}

    try:
        if stream:
            completed = subprocess.run(  # noqa: S603 - argv list, shell=False
                argv,
                cwd=str(cwd) if cwd else None,
                env=merged_env,
                input=stdin_text,
                text=True,
                timeout=timeout,
                check=False,
            )
            output = ""
        else:
            completed = subprocess.run(  # noqa: S603 - argv list, shell=False
                argv,
                cwd=str(cwd) if cwd else None,
                env=merged_env,
                input=stdin_text,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            output = (completed.stdout or "") + (completed.stderr or "")
    except FileNotFoundError as exc:
        raise LauncherError(
            f"Command not found: {argv[0]}",
            hint="Install it, or check that it is on PATH.",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise LauncherError(f"Timed out after {timeout}s: {' '.join(argv)}") from exc

    result = Result(completed.returncode, output)
    if check and not result.ok:
        if not stream and tail:
            ui.tail_output(result.output, lines=tail, label=Path(argv[0]).name)
        raise LauncherError(
            error_message or f"`{' '.join(argv[:3])}` failed (exit {result.code})."
        )
    return result


def capture(
    argv: Sequence[str],
    *,
    cwd: Path | str | None = None,
    timeout: int | None = 60,
) -> str | None:
    """Run a read-only command and return stripped stdout, or None on failure.

    Use for probes where failure is an expected answer ("is this installed?",
    "does this stack exist?") rather than an error to report.
    """
    argv = [str(token) for token in argv]
    try:
        completed = subprocess.run(  # noqa: S603 - argv list, shell=False
            argv,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if completed.returncode != 0:
        return None
    return (completed.stdout or "").strip() or None
