# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Allows `python3 -m launcher` from the repository root."""

from __future__ import annotations

import sys
from pathlib import Path

from .cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], repo_root=Path(__file__).resolve().parent.parent))
