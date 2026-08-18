# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Reasoning Specialist — Sonnet agent-as-tool for ambiguous interpretation tasks.

Called by the Haiku orchestrator when the SOP says "if ambiguous" or when
the orchestrator encounters data it can't interpret mechanically.

Stateless: receives a focused task description, returns a reasoned answer.
No tools — pure NLP/judgment. Keeps cost low by only using Sonnet when needed.
"""

import os

from strands import Agent
from strands.models import BedrockModel
from strands.models.bedrock import CacheConfig

from .model_config import sampling_kwargs

SPECIALIST_PROMPT = """\
You are a reasoning specialist for SAP financial exception processing.
You receive focused interpretation tasks from an orchestrator agent.

Your strengths:
- Parsing ambiguous dates from natural language ("mid-December" → December 15)
- Resolving conflicting data between systems (SAP vs Excel vs email)
- Interpreting vague stakeholder responses
- Making judgment calls when standard procedures don't cover the case
- Recommending escalation paths with justification

Rules:
- Be precise and decisive — the orchestrator needs a clear answer, not hedging
- When interpreting dates, state your reasoning and the exact date you chose
- When data conflicts, state which source you trust and why
- Always respond in a structured format the orchestrator can act on
"""


def _guardrail_kwargs() -> dict:
    """Bedrock Guardrail kwargs for the specialist's model, or {} when unset.

    Mirrors basic_agent._guardrail_kwargs (inlined to avoid a circular import:
    basic_agent imports create_specialist). The specialist processes untrusted,
    orchestrator-forwarded SAP/email text, so it gets the same T2/T15 guardrail
    as the orchestrator when security.guardrail_enabled provisions one. Absent
    the env vars (sample default) it contributes nothing.
    """
    guardrail_id = os.environ.get("BEDROCK_GUARDRAIL_ID")
    if not guardrail_id:
        return {}
    return {
        "guardrail_id": guardrail_id,
        "guardrail_version": os.environ.get("BEDROCK_GUARDRAIL_VERSION", "DRAFT"),
        "guardrail_trace": "enabled",
    }


def create_specialist(model_id: str | None = None) -> Agent:
    """Create the reasoning specialist agent (Sonnet, no tools)."""
    default_id = os.environ.get("MODEL_ID", "us.anthropic.claude-sonnet-5")
    resolved_id = model_id or default_id

    return Agent(
        name="ReasoningSpecialist",
        system_prompt=SPECIALIST_PROMPT,
        model=BedrockModel(
            model_id=resolved_id,
            cache_config=CacheConfig(strategy="auto"),
            **sampling_kwargs(resolved_id, 0.2),
            **_guardrail_kwargs(),
        ),
        tools=[],
    )
