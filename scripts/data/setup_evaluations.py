# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Evaluation Setup — configures AgentCore online evaluations and custom evaluators.

Run once after deployment (or after changing eval config):
    python scripts/data/setup_evaluations.py --stack-name my-stack --region us-east-1

Creates:
  1. Custom evaluator: SAPActionAccuracy (validates agent's SAP tool calls)
  2. Online evaluation config: continuous sampling of live sessions
"""

import argparse
import sys

import boto3


def get_agent_id(stack_name: str, region: str) -> str:
    """Get agent runtime ID from SSM."""
    ssm = boto3.client("ssm", region_name=region)
    arn = ssm.get_parameter(Name=f"/{stack_name}/runtime-arn")["Parameter"]["Value"]
    # ARN format: arn:aws:bedrock-agentcore:REGION:ACCOUNT:runtime/AGENT_ID
    return arn.split("/")[-1]


def create_custom_evaluator(region: str) -> str:
    """Create the SAPActionAccuracy custom evaluator."""
    client = boto3.client("bedrock-agentcore-control", region_name=region)

    existing = client.list_evaluators()
    for ev in existing.get("evaluatorSummaries", []):
        if ev.get("evaluatorName") == "SAPActionAccuracy":
            print(f"  Custom evaluator already exists: {ev['evaluatorId']}")
            return ev["evaluatorId"]

    resp = client.create_evaluator(
        evaluatorName="SAPActionAccuracy",
        description=(
            "Evaluates whether the agent's actions against SAP systems were valid "
            "and appropriate for the given case. Checks: correct API endpoints called, "
            "reasonable parameter values, proper workflow selection based on materiality "
            "thresholds, and accurate accrual calculations."
        ),
        evaluationLevel="SESSION",
        inferenceConfig={
            "modelId": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
            "maxTokens": 1024,
            "temperature": 0.0,
        },
        instructions="""You are an expert SAP financial auditor evaluating an AI agent's actions.

Review the agent's complete session and evaluate whether its actions against SAP and
financial systems were correct and appropriate.

Check these criteria:
1. WORKFLOW SELECTION: Did the agent pick the right workflow based on outstanding balance?
   - >$300K → EMAIL_INQUIRY
   - >=$150K with WBS → PROJECT_MILESTONE
   - >=$150K without WBS → EMAIL_INQUIRY
   - <$150K → DELIVERY_DATE
2. SAP API CALLS: Were the correct OData endpoints called with valid parameters?
3. ACCRUAL CALCULATION: Is the math correct? Monthly Rate = Outstanding Balance / Duration.
   Accrual = Monthly Rate × Months Elapsed. Result must be <= Outstanding Balance.
4. DATA INTEGRITY: Did the agent use actual data from SAP responses, not hallucinated values?
5. PROCESS COMPLETENESS: Did the agent follow all required steps (data gathering, validation,
   calculation, approval request)?

Score 0.0 if the agent hallucinated SAP data or made a calculation error.
Score 0.5 if the agent followed the right process but made minor mistakes.
Score 1.0 if all actions were correct and well-reasoned.

{{input}} {{output}}""",
        ratingScale={
            "type": "NUMERIC",
            "min": 0.0,
            "max": 1.0,
            "description": "0=hallucinated data or wrong calculation, 0.5=right process with minor issues, 1=fully correct",
        },
    )

    evaluator_id = resp["evaluatorId"]
    print(f"  Created custom evaluator: {evaluator_id}")
    return evaluator_id


def create_online_config(
    agent_id: str, custom_evaluator_id: str, region: str, sampling_rate: float
):
    """Create online evaluation config for continuous monitoring."""
    try:
        from bedrock_agentcore_starter_toolkit import Evaluation
    except ImportError:
        print("  ERROR: pip install bedrock-agentcore-starter-toolkit")
        sys.exit(1)

    eval_client = Evaluation(region=region)

    configs = eval_client.list_online_configs()
    for cfg in configs.get("onlineEvaluationConfigs", []):
        if cfg.get("onlineEvaluationConfigName") == "sap_agent_eval":
            print(f"  Online config already exists: {cfg['onlineEvaluationConfigId']}")
            return cfg["onlineEvaluationConfigId"]

    resp = eval_client.create_online_config(
        agent_id=agent_id,
        config_name="sap_agent_eval",
        sampling_rate=sampling_rate,
        evaluator_list=[
            # Built-in: core quality
            "Builtin.Correctness",
            "Builtin.GoalSuccessRate",
            "Builtin.Faithfulness",
            # Built-in: tool usage
            "Builtin.ToolSelectionAccuracy",
            "Builtin.ToolParameterAccuracy",
            # Custom: SAP-specific
            custom_evaluator_id,
        ],
        config_description=(
            "Continuous evaluation of SAP exception processing agent. "
            "Monitors correctness, goal completion, tool usage accuracy, "
            "and SAP-specific action validity."
        ),
        auto_create_execution_role=True,
        enable_on_create=True,
    )

    config_id = resp["onlineEvaluationConfigId"]
    print(f"  Created online config: {config_id} (sampling={sampling_rate}%)")
    return config_id


def main():
    parser = argparse.ArgumentParser(description="Set up AgentCore evaluations")
    parser.add_argument("--stack-name", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument(
        "--sampling-rate",
        type=float,
        default=25.0,
        help="Percentage of sessions to evaluate (default: 25)",
    )
    args = parser.parse_args()

    print(f"Setting up evaluations for {args.stack_name} in {args.region}")

    print("\n1. Getting agent ID...")
    agent_id = get_agent_id(args.stack_name, args.region)
    print(f"  Agent ID: {agent_id}")

    print("\n2. Creating custom evaluator (SAPActionAccuracy)...")
    custom_id = create_custom_evaluator(args.region)

    print("\n3. Creating online evaluation config...")
    config_id = create_online_config(
        agent_id, custom_id, args.region, args.sampling_rate
    )

    print("\n✅ Evaluations configured!")
    print(f"   Online config: {config_id}")
    print(f"   Sampling rate: {args.sampling_rate}%")
    print(
        f"   Results: CloudWatch Logs → /aws/bedrock-agentcore/evaluations/results/{config_id}"
    )
    print(
        f"\n   View in console: https://{args.region}.console.aws.amazon.com/cloudwatch/home"
        f"?region={args.region}#logsV2:log-groups/log-group/"
        f"%2Faws%2Fbedrock-agentcore%2Fevaluations%2Fresults%2F{config_id}"
    )


if __name__ == "__main__":
    main()
