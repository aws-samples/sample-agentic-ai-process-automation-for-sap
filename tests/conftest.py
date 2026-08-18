# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Pytest configuration file for the test suite.

Puts agentcore/agent on sys.path so tests can `from utils.auth import ...`, and the
shared_types layer so they can `from case_key import ...` / `from generated_cases
import ...` the way a deployed Lambda does (the layer is on the Lambda path, so
handlers import those modules unconditionally).
Lambda handler dirs are NOT added here — several export a module named `index`
and would collide, so those tests insert their own dir right before importing.
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(_REPO_ROOT / "agentcore" / "agent"))
sys.path.insert(0, str(_REPO_ROOT / "lambdas" / "layers" / "shared_types"))
