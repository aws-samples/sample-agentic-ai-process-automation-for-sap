# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Sonnet 5 and Opus 4.7+ reject `temperature` with a Bedrock ValidationException,
and Strands forwards whatever it is constructed with — so passing the sample's
determinism nudge to a current model 400s every agent call. The tier map in
basic_agent.py must stay in step with what sampling_kwargs suppresses: a model
bump that lands in MODEL_TIERS without a matching marker here is exactly the
regression this file exists to catch.
"""

import ast
import pathlib

import pytest
from utils.model_config import sampling_kwargs

_AGENT = (
    pathlib.Path(__file__).resolve().parents[2]
    / "agentcore"
    / "agent"
    / "basic_agent.py"
)

REJECTS_SAMPLING = [
    "us.anthropic.claude-sonnet-5",
    "global.anthropic.claude-sonnet-5",
    "us.anthropic.claude-opus-5",
    "us.anthropic.claude-opus-4-7",
    "us.anthropic.claude-opus-4-8",
]

ACCEPTS_SAMPLING = [
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
]


def _shipped_tier_defaults() -> list[str]:
    """MODEL_TIERS' env-var fallbacks, read without importing basic_agent.

    Importing it pulls in the whole runtime (Gateway env vars, boto clients), so
    this reads the literal defaults out of the AST the way the other agent tests
    do — the fallback is what actually ships, since CDK sets no MODEL_ID.
    """
    tree = ast.parse(_AGENT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == "MODEL_TIERS":
            return [
                call.args[1].value
                for call in node.value.values
                if isinstance(call, ast.Call) and len(call.args) == 2
            ]
    return []


@pytest.mark.parametrize("model_id", REJECTS_SAMPLING)
def test_temperature_omitted_for_models_that_reject_it(model_id):
    assert sampling_kwargs(model_id, 0.1) == {}


@pytest.mark.parametrize("model_id", ACCEPTS_SAMPLING)
def test_temperature_kept_where_still_accepted(model_id):
    assert sampling_kwargs(model_id, 0.1) == {"temperature": 0.1}


def test_every_shipped_tier_default_is_explicitly_classified():
    """A tier bump must be classified here, since only Bedrock is the real oracle.

    Whether a model rejects sampling params is not derivable from the ID — it is
    a per-model API fact. Pinning the shipped defaults to the lists above forces
    anyone bumping MODEL_TIERS to confirm the new model's behaviour rather than
    discovering it as a 400 in deployment.
    """
    defaults = _shipped_tier_defaults()
    assert defaults, "MODEL_TIERS defaults not found in basic_agent.py"

    classified = set(REJECTS_SAMPLING) | set(ACCEPTS_SAMPLING)
    for model_id in defaults:
        assert model_id in classified, (
            f"tier default {model_id!r} is unclassified — verify against Bedrock "
            f"whether it accepts `temperature`, then add it to the list in this test"
        )
