# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Shared helpers for the deploy scripts. Stdlib-only by design — the deploy
scripts must run with nothing but Python 3.8+, AWS CLI, and git installed
(no boto3/PyYAML), so this cannot import scripts/utils.py.
"""

import json
import re
import subprocess  # nosec B404 - subprocess used securely with explicit parameters
import sys
from pathlib import Path
from typing import Dict, Optional


def log_info(message: str) -> None:
    """Print an info message."""
    print(f"ℹ {message}")


def log_success(message: str) -> None:
    """Print a success message."""
    print(f"✓ {message}")


def log_error(message: str) -> None:
    """Print an error message to stderr."""
    print(f"✗ {message}", file=sys.stderr)


def run_command(
    command: list,
    capture_output: bool = True,
    check: bool = True,
    cwd: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """Execute a command securely via subprocess (shell=False, 300s timeout)."""
    return subprocess.run(  # nosec B603  # nosemgrep: dangerous-subprocess-use-audit
        command,
        capture_output=capture_output,
        text=True,
        check=check,
        shell=False,
        timeout=300,
        cwd=cwd,
    )


def parse_config_yaml(config_path: Path) -> Dict[str, str]:
    """
    Parse config.yaml using regex (no PyYAML dependency).

    Returns a dict with stack_name_base and pattern.
    """
    config = {"stack_name_base": "", "pattern": "strands-single-agent"}
    if not config_path.exists():
        return config

    content = config_path.read_text()

    match = re.search(r"^stack_name_base:\s*(\S+)", content, re.MULTILINE)
    if match:
        config["stack_name_base"] = match.group(1).strip("\"'")

    match = re.search(r"pattern:\s*(\S+)", content)
    if match:
        config["pattern"] = match.group(1).split("#")[0].strip().strip("\"'")

    return config


def get_stack_outputs(stack_name: str) -> Dict[str, str]:
    """Fetch CloudFormation stack outputs via AWS CLI."""
    result = run_command(
        [
            "aws",
            "cloudformation",
            "describe-stacks",
            "--stack-name",
            stack_name,
            "--output",
            "json",
        ]
    )
    stacks = json.loads(result.stdout).get("Stacks", [])
    if not stacks:
        raise ValueError(f"Stack '{stack_name}' not found")
    outputs = stacks[0].get("Outputs", [])
    return {o["OutputKey"]: o["OutputValue"] for o in outputs}
