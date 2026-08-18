#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Guided launcher for the Agentic ERP Automation sample.

    git clone <this repository>
    cd agentic-erp-automation-quick-start
    python3 launch.py

That is the whole first-run path. `python3 launch.py --help` lists the
individual commands.

This file is a deliberately tiny shim: it verifies the Python version, puts the
repository root on sys.path, and hands off. Keeping it standard-library-only
means the version check produces a clear message instead of a SyntaxError or an
ImportError on an old interpreter.
"""

from __future__ import annotations

import sys
from pathlib import Path

MINIMUM_PYTHON = (3, 10)
EXIT_PREREQ = 3


def _fail(message: str, hint: str = "") -> None:
    print(f"\n  Cannot start the launcher: {message}", file=sys.stderr)
    if hint:
        print(f"  -> {hint}", file=sys.stderr)
    print(file=sys.stderr)
    raise SystemExit(EXIT_PREREQ)


def main() -> None:
    if sys.version_info < MINIMUM_PYTHON:
        needed = ".".join(str(part) for part in MINIMUM_PYTHON)
        running = ".".join(str(part) for part in sys.version_info[:3])
        _fail(
            f"Python {needed} or newer is required (running {running}).",
            "Install a newer Python 3 and re-run, for example `python3.12 launch.py`.",
        )

    repo_root = Path(__file__).resolve().parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    try:
        from launcher.cli import main as run_cli
    except ImportError as exc:
        _fail(
            f"the launcher package could not be imported ({exc}).",
            f"Run this from a complete checkout — expected {repo_root / 'launcher'} to exist.",
        )

    raise SystemExit(run_cli(sys.argv[1:], repo_root=repo_root))


if __name__ == "__main__":
    main()
