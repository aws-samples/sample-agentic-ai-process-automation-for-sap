# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Pytest configuration file for the test suite.

Puts agentcore/agent on sys.path so tests can `from utils.auth import ...`.
Lambda handler dirs are NOT added here — several export a module named `index`
and would collide, so those tests insert their own dir right before importing.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agentcore" / "agent"))
