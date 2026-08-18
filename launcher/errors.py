# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Error types and the launcher's stable exit-code contract.

Exit codes are part of the launcher's public interface: scripts and CI can
branch on them. Do not renumber existing codes.
"""

from __future__ import annotations

EXIT_OK = 0
EXIT_ERROR = 1  # unclassified failure
EXIT_USAGE = 2  # bad arguments / bad invocation
EXIT_PREREQ = 3  # a required tool or runtime is missing or too old
EXIT_CONFIG = 4  # cdk/config.yaml missing or invalid
EXIT_AWS = 5  # credentials, region, or an AWS API call failed
EXIT_DEPLOY = 6  # bootstrap / synth / deploy failed
EXIT_CANCELLED = 130  # user declined or pressed Ctrl-C


class LauncherError(Exception):
    """A failure the launcher understands well enough to explain.

    `hint` is printed after the message as the suggested next action. Raise this
    instead of letting a subprocess traceback escape: an unhandled traceback
    tells the user nothing actionable.
    """

    def __init__(
        self,
        message: str,
        *,
        hint: str | None = None,
        exit_code: int = EXIT_ERROR,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.exit_code = exit_code


class Cancelled(LauncherError):
    """The user declined a confirmation or interrupted the run."""

    def __init__(self, message: str = "Cancelled — no changes made.") -> None:
        super().__init__(message, exit_code=EXIT_CANCELLED)


class ConfigError(LauncherError):
    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message, hint=hint, exit_code=EXIT_CONFIG)


class AwsError(LauncherError):
    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message, hint=hint, exit_code=EXIT_AWS)


class DeployError(LauncherError):
    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message, hint=hint, exit_code=EXIT_DEPLOY)
