# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
SAP Exception Processing Agent

Multi-skill agent for processing SAP exceptions. The wired domain is finance_ap
(supplier-invoice three-way-match exceptions); the Skill Router is domain-agnostic and
loads domain expertise + SOP dynamically based on process_type, so additional domains
can be wired in without agent code changes.

Uses AgentCore Gateway Lambda tools instead of a direct MCP server connection.
"""

import asyncio
import json
import os
import re
import time
import traceback

import boto3

from bedrock_agentcore.identity.auth import requires_access_token
from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig
from bedrock_agentcore.memory.integrations.strands.session_manager import (
    AgentCoreMemorySessionManager,
)
from bedrock_agentcore.runtime import BedrockAgentCoreApp, RequestContext
from mcp.client.streamable_http import streamablehttp_client
from strands import Agent, ModelRetryStrategy
from strands.hooks import (
    AfterInvocationEvent,
    BeforeInvocationEvent,
    BeforeModelCallEvent,
    HookProvider,
    HookRegistry,
)
from strands.models import BedrockModel
from strands.models.bedrock import CacheConfig
from strands.tools.mcp import MCPClient

from strands_tools import calculator, current_time

from utils.agent_metrics import emit_agent_metrics, _estimate_cost
from utils.auth import extract_user_id_from_context, to_memory_actor_id
from utils.content_filter import sanitize_external_content, fence_data
from utils.skill_router import resolve_skill, list_skills, SopLoadError
from utils.specialist import create_specialist
from utils.segments import accumulate_segment
from utils.ssm import get_ssm_parameter
from utils.mcp_topology import build_direct_mcp_headers, resolve_outbound_topology
from utils.sap_auth_interrupt import wrap_sap_auth_tools

# When true, SAP MCP tools are wrapped so an `authentication_required` result pauses the
# agent with a real Strands interrupt (stop_reason="interrupt") that resumes on the same
# turn after the user signs in, instead of surfacing the auth_url as a plain tool result
# the user has to re-prompt against. Off by default: only the interactive USER_FEDERATION
# flow needs it.
_SAP_AUTH_INTERRUPT = os.environ.get("SAP_AUTH_INTERRUPT", "").lower() == "true"

app = BedrockAgentCoreApp()

# Fallback prompt when no process_type is provided (chat mode)
GENERAL_PROMPT = """You are an expert SAP exception handling specialist. You autonomously
investigate and resolve SAP exceptions across all domains.

Available skills: {skills_summary}

## AUTONOMOUS EXECUTION (CRITICAL)
When a user asks you to process a case:
1. IMMEDIATELY call get_case_state to retrieve the case details.
2. Identify the process_type from the case data.
3. Use find_sap_services and get_metadata to discover SAP OData services, entities, and fields.
4. Use search_sap_sops to find the relevant Standard Operating Procedure.
5. Follow the SOP step by step WITHOUT asking the user for permission.
6. NEVER present a menu of options or ask "What would you like me to do first?"
7. Only stop for explicit approval gates defined in the SOP.

Use odata_read/odata_count for SAP reads and odata_create/odata_update/odata_function_import for SAP writes.
Use update_case_state to update case fields (status, amounts, dates).
"""


# When running locally (outside AgentCore Runtime), the @requires_access_token
# decorator cannot obtain a workload identity token. Instead, we fetch an M2M
# token directly from Cognito using client credentials stored in SSM/Secrets Manager.
_LOCAL_MODE = os.environ.get("LOCAL_MODE", "").lower() == "true"


@requires_access_token(
    provider_name=os.environ["GATEWAY_CREDENTIAL_PROVIDER_NAME"],
    auth_flow="M2M",
    scopes=[],
)
def _fetch_gateway_token(access_token: str) -> str:
    """Fetch Gateway token via AgentCore Identity (cloud only)."""
    return access_token


def _fetch_gateway_token_local() -> str:
    """Fetch Gateway M2M token directly from Cognito (local dev only)."""
    import base64
    import urllib.request
    import urllib.parse

    import boto3

    stack_name = os.environ.get("STACK_NAME", "")
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

    client_id = get_ssm_parameter(f"/{stack_name}/machine_client_id")

    # Machine client secret is in Secrets Manager, not SSM
    sm = boto3.client("secretsmanager", region_name=region)
    client_secret = sm.get_secret_value(
        SecretId=f"/{stack_name}/machine_client_secret"
    )["SecretString"]

    # Build Cognito domain from stack name + account + region (matches CDK)
    account = boto3.client("sts", region_name=region).get_caller_identity()["Account"]
    domain = f"{stack_name.lower()}-{account}-{region}"

    token_url = f"https://{domain}.auth.{region}.amazoncognito.com/oauth2/token"
    creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()

    req = urllib.request.Request(
        token_url,
        data=data,
        headers={
            "Authorization": f"Basic {creds}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req) as resp:  # nosec B310  # nosemgrep: dynamic-urllib-use-detected
        return json.loads(resp.read())["access_token"]


def _get_gateway_token() -> str:
    """Return a Gateway bearer token using the appropriate method for the environment."""
    if _LOCAL_MODE:
        return _fetch_gateway_token_local()
    return _fetch_gateway_token()


def _create_gateway_client(allowed_tools: list[str] | None = None, user_token: str | None = None, audit_context: dict | None = None) -> MCPClient:
    stack_name = os.environ.get("STACK_NAME")
    if not stack_name:
        raise ValueError("STACK_NAME environment variable is required")

    gateway_url = get_ssm_parameter(f"/{stack_name}/gateway_url")
    print(f"[AGENT] Gateway URL: {gateway_url}")

    # Gateway returns tools as "target-name___tool_name" — filter on suffix
    tool_filters = None
    if allowed_tools:
        allowed_set = set(allowed_tools)
        tool_filters = {"allowed": [
            lambda tool: tool.mcp_tool.name.split("___")[-1] in allowed_set
        ]}
        print(f"[AGENT] Tool filter: {allowed_tools}")

    def _headers() -> dict[str, str]:
        h = {"Authorization": f"Bearer {_get_gateway_token()}"}
        # Forward user JWT for identity propagation (oidc-passthrough / principal-propagation)
        if user_token:
            h["x-user-token"] = f"Bearer {user_token}"
        # Audit baggage — propagated to SAP via interceptor/tool Lambda
        if audit_context:
            if audit_context.get("correlation_id"):
                h["x-audit-correlation-id"] = audit_context["correlation_id"]
            if audit_context.get("initiator"):
                h["x-audit-initiator"] = audit_context["initiator"]
            if audit_context.get("trigger"):
                h["x-audit-trigger"] = audit_context["trigger"]
        return h

    return MCPClient(
        lambda: streamablehttp_client(
            url=gateway_url,
            headers=_headers(),
        ),
        tool_filters=tool_filters,
    )


def _create_direct_mcp_client(user_token: str, allowed_tools: list[str] | None = None, audit_context: dict | None = None) -> MCPClient:
    """OBO topology: connect DIRECTLY to the external MCP with the user's Entra JWT
    as the primary Authorization bearer, bypassing our Gateway (no M2M token). Used
    when the resolved outbound flow is OBO. See mcp_topology.build_direct_mcp_headers.
    """
    stack_name = os.environ.get("STACK_NAME")
    if not stack_name:
        raise ValueError("STACK_NAME environment variable is required")

    invocation_url = get_ssm_parameter(f"/{stack_name}/mcp_invocation_url")
    print(f"[AGENT] Direct MCP (OBO) URL: {invocation_url}")

    # Same suffix filter as the Gateway path — tool names may be "target___tool"
    tool_filters = None
    if allowed_tools:
        allowed_set = set(allowed_tools)
        tool_filters = {"allowed": [
            lambda tool: tool.mcp_tool.name.split("___")[-1] in allowed_set
        ]}
        print(f"[AGENT] Tool filter: {allowed_tools}")

    def _headers() -> dict[str, str]:
        return build_direct_mcp_headers(user_token, audit_context=audit_context)

    return MCPClient(
        lambda: streamablehttp_client(
            url=invocation_url,
            headers=_headers(),
        ),
        tool_filters=tool_filters,
    )


def _resolve_system_prompt(payload: dict) -> dict:
    """Resolve skill config: skill-routed if process_type present, general defaults otherwise."""
    process_type = payload.get("process_type")
    inner = payload.get("payload", {})

    # If no process_type, try to extract case_id and look it up in DynamoDB
    if not process_type:
        case_id = payload.get("case_id")
        if not case_id:
            # Try document_number + item_id from payload or inner payload
            doc = payload.get("document_number") or inner.get("document_number")
            item = payload.get("item_id") or inner.get("item_id")
            if doc and item:
                case_id = f"{doc}#{item}"
        if not case_id:
            user_prompt = payload.get("user_prompt") or payload.get("prompt") or inner.get("user_prompt") or ""
            case_id = _extract_case_id(user_prompt)
        if case_id:
            process_type = _lookup_process_type(case_id)
            if process_type:
                print(f"[ROUTING] Resolved process_type={process_type} from case_id={case_id}")

    if process_type:
        sop_bucket = os.environ.get("SOP_BUCKET")
        skill = resolve_skill(process_type, sop_bucket=sop_bucket)
        print(f"[SKILL] Routed to skill={skill['skill_id']}, sop_loaded={skill['sop_loaded']}")
        return skill

    # General mode — list available skills for the user
    skills = list_skills()
    summary = "\n".join(f"- {s['display_name']}: {', '.join(s['process_types'])}" for s in skills)
    return {
        "system_prompt": GENERAL_PROMPT.format(skills_summary=summary),
        "model_tier": "sonnet",
        "max_turns": 15,
    }


def _extract_case_id(text: str) -> str | None:
    """Extract a case_id from free-text prompt."""
    # "document_number=141, item_id=1" or "document_number=141 item_id=1"
    m = re.search(r'document_number[=:\s]+(\w+)[,\s]+item_id[=:\s]+(\w+)', text)
    if m:
        return f"{m.group(1)}#{m.group(2)}"
    # "case 141-1" or "case 141#1"
    m = re.search(r'(?i)case[:\s]+(\d[\w#-]+)', text)
    return m.group(1) if m else None


def _lookup_process_type(case_id: str) -> str | None:
    """Look up process_type from DynamoDB cases table."""
    table_name = os.environ.get("CASES_TABLE")
    if not table_name:
        return None
    try:
        # case_id can be "doc-item" or "doc#item"
        sep = "#" if "#" in case_id else "-"
        doc, item = case_id.split(sep, 1)
        table = boto3.resource("dynamodb").Table(table_name)
        resp = table.get_item(Key={"document_number": doc, "item_id": item}, ProjectionExpression="process_type")
        return resp.get("Item", {}).get("process_type")
    except Exception as e:
        print(f"[ROUTING] Case lookup failed for {case_id}: {e}")
        return None


# Model tier → Bedrock model ID mapping (override via env vars)
MODEL_TIERS = {
    "haiku": os.environ.get("MODEL_ID_HAIKU", "us.anthropic.claude-haiku-3-5-20250929-v1:0"),
    "sonnet": os.environ.get("MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"),
}


def _guardrail_kwargs() -> dict:
    """Bedrock Guardrail kwargs for BedrockModel, or {} when not configured.

    The guardrail (threats T2/T15) is provisioned by CDK only when
    security.guardrail_enabled is set; the runtime then receives
    BEDROCK_GUARDRAIL_ID / BEDROCK_GUARDRAIL_VERSION env vars. When absent, the
    agent runs without a guardrail (sample default) and relies on input
    sanitization + Cedar as before.
    """
    guardrail_id = os.environ.get("BEDROCK_GUARDRAIL_ID")
    if not guardrail_id:
        return {}
    return {
        "guardrail_id": guardrail_id,
        "guardrail_version": os.environ.get("BEDROCK_GUARDRAIL_VERSION", "DRAFT"),
        "guardrail_trace": "enabled",
    }


class MaxTurnsHook:
    """Cancels the agent after max_turns model calls to prevent runaway costs."""

    def __init__(self, max_turns: int):
        self._max_turns = max_turns
        self.turn_count = 0
        self.cancelled = False

    def reset(self, event: BeforeInvocationEvent) -> None:
        self.turn_count = 0
        self.cancelled = False

    def check(self, event: BeforeModelCallEvent) -> None:
        self.turn_count += 1
        if self.turn_count > self._max_turns:
            self.cancelled = True
            print(f"[COST] Max turns ({self._max_turns}) reached — cancelling agent")
            event.agent.cancel()


class MetricsHook:
    """Emits CloudWatch metrics after every invocation (success or failure).

    Uses Strands' accumulated_usage from event_loop_metrics for accurate
    cumulative token counts across all turns (not just the last message).

    In multi-agent mode, also reads the specialist agent's accumulated_usage
    and estimates its cost separately (different model tier / pricing).
    """

    def __init__(self, process_type: str, model_tier: str, max_turns_hook: MaxTurnsHook,
                 specialist: Agent | None = None, specialist_tier: str = "sonnet"):
        self._process_type = process_type
        self._model_tier = model_tier
        self._max_turns_hook = max_turns_hook
        self._specialist = specialist
        self._specialist_tier = specialist_tier
        self._start_time = 0.0
        # Last-run metrics — populated by on_end, read by agent_stream
        self.last_latency_ms: float = 0.0
        self.last_input_tokens: int = 0
        self.last_output_tokens: int = 0
        self.last_cache_read_tokens: int = 0
        self.last_cache_write_tokens: int = 0
        self.last_estimated_cost_usd: float = 0.0

    def on_start(self, event: BeforeInvocationEvent) -> None:
        self._start_time = time.time()

    def trace_metrics(self) -> dict:
        """Metrics dict for _save_trace_to_ddb, populated by on_end."""
        return {
            "latency_ms": self.last_latency_ms,
            "input_tokens": self.last_input_tokens,
            "output_tokens": self.last_output_tokens,
            "cache_read_tokens": self.last_cache_read_tokens,
            "cache_write_tokens": self.last_cache_write_tokens,
            "estimated_cost_usd": self.last_estimated_cost_usd,
        }

    @staticmethod
    def _get_invocation_usage(agent: Agent) -> dict:
        """Extract cumulative usage from the agent's latest invocation."""
        try:
            inv = agent.event_loop_metrics.latest_agent_invocation
            if inv and inv.usage:
                return inv.usage
        except Exception:
            pass
        try:
            if agent.messages:
                return agent.messages[-1].get("usage", {})
        except Exception:
            pass
        return {}

    def on_end(self, event: AfterInvocationEvent) -> None:
        latency_ms = (time.time() - self._start_time) * 1000
        success = not getattr(event, "exception", None)

        # Orchestrator usage (cumulative across all turns)
        usage = self._get_invocation_usage(event.agent)
        input_tokens = usage.get("inputTokens", 0)
        output_tokens = usage.get("outputTokens", 0)
        cache_read_tokens = usage.get("cacheReadInputTokens", 0)
        cache_write_tokens = usage.get("cacheWriteInputTokens", 0)

        cost = _estimate_cost(self._model_tier, input_tokens, output_tokens,
                              cache_read_tokens, cache_write_tokens)

        # Specialist usage (separate agent, separate model, separate pricing)
        if self._specialist:
            sp_usage = self._get_invocation_usage(self._specialist)
            sp_in = sp_usage.get("inputTokens", 0)
            sp_out = sp_usage.get("outputTokens", 0)
            sp_cache_r = sp_usage.get("cacheReadInputTokens", 0)
            sp_cache_w = sp_usage.get("cacheWriteInputTokens", 0)
            cost += _estimate_cost(self._specialist_tier, sp_in, sp_out, sp_cache_r, sp_cache_w)
            # Roll specialist tokens into totals for reporting
            input_tokens += sp_in
            output_tokens += sp_out
            cache_read_tokens += sp_cache_r
            cache_write_tokens += sp_cache_w

        # Store for trace enrichment
        self.last_latency_ms = latency_ms
        self.last_input_tokens = input_tokens
        self.last_output_tokens = output_tokens
        self.last_cache_read_tokens = cache_read_tokens
        self.last_cache_write_tokens = cache_write_tokens
        self.last_estimated_cost_usd = cost

        emit_agent_metrics(
            process_type=self._process_type,
            model_tier=self._model_tier,
            turns=self._max_turns_hook.turn_count,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            latency_ms=latency_ms,
            success=success,
        )


def _create_agent(
    skill: dict, user_id: str, session_id: str, process_type: str,
    user_token: str | None = None, audit_context: dict | None = None,
) -> tuple[Agent, MetricsHook, MaxTurnsHook]:
    """Create agent with skill-resolved config, model routing, caching, hooks, and retry."""
    config = skill.get("config", {})
    use_multi_agent = config.get("multi_agent", False)

    # Orchestrator model tier (haiku in multi-agent, sonnet in single-agent)
    model_tier = (config.get("orchestrator_tier") if use_multi_agent else None) or skill.get("model_tier", "sonnet")
    model_id = MODEL_TIERS.get(model_tier, MODEL_TIERS["sonnet"])
    max_turns = skill.get("max_turns", 20)

    bedrock_model = BedrockModel(
        model_id=model_id,
        temperature=0.1,
        cache_config=CacheConfig(strategy="auto"),
        **_guardrail_kwargs(),
    )

    memory_id = os.environ.get("MEMORY_ID")
    if not memory_id:
        raise ValueError("MEMORY_ID environment variable is required")

    session_manager = AgentCoreMemorySessionManager(
        agentcore_memory_config=AgentCoreMemoryConfig(
            memory_id=memory_id, session_id=session_id, actor_id=to_memory_actor_id(user_id),
        ),
        region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
    )

    stack_name = os.environ.get("STACK_NAME")
    try:
        outbound_flow = get_ssm_parameter(f"/{stack_name}/outbound_flow") if stack_name else None
    except ValueError:
        outbound_flow = None  # param not published for non-OBO deploys -> Gateway path (unchanged)
    if resolve_outbound_topology(outbound_flow) == "direct":
        print(f"[AGENT] Outbound topology: direct-MCP (OBO), flow={outbound_flow}")
        mcp_client = _create_direct_mcp_client(user_token, config.get("gateway_tools"), audit_context=audit_context)
    else:
        print(f"[AGENT] Outbound topology: gateway, flow={outbound_flow}")
        mcp_client = _create_gateway_client(config.get("gateway_tools"), user_token=user_token, audit_context=audit_context)

    # Build tool list — add specialist as tool in multi-agent mode
    tools = [mcp_client, calculator, current_time]
    specialist = None
    specialist_tier = "sonnet"
    if use_multi_agent:
        specialist_tier = config.get("specialist_tier", "sonnet")
        specialist_model_id = MODEL_TIERS.get(specialist_tier, MODEL_TIERS["sonnet"])
        specialist = create_specialist(model_id=specialist_model_id)
        tools.append(specialist.as_tool())
        print(f"[MULTI-AGENT] orchestrator={model_tier}, specialist={specialist_tier}")
    else:
        print(f"[SINGLE-AGENT] model_tier={model_tier}")

    print(f"[COST] model_id={model_id}, max_turns={max_turns}, cache=auto")

    # Build hooks
    turns_hook = MaxTurnsHook(max_turns)
    metrics_hook = MetricsHook(process_type, model_tier, turns_hook,
                               specialist=specialist, specialist_tier=specialist_tier)

    class _Hooks:
        """HookProvider that registers turn-limit and metrics callbacks."""

        def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
            registry.add_callback(BeforeInvocationEvent, turns_hook.reset)
            registry.add_callback(BeforeModelCallEvent, turns_hook.check)
            registry.add_callback(BeforeInvocationEvent, metrics_hook.on_start)
            registry.add_callback(AfterInvocationEvent, metrics_hook.on_end)

    agent = Agent(
        name="SAPExceptionAgent",
        system_prompt=skill["system_prompt"],
        tools=tools,
        model=bedrock_model,
        session_manager=session_manager,
        trace_attributes={"user.id": user_id, "session.id": session_id},
        retry_strategy=ModelRetryStrategy(max_attempts=4, initial_delay=2),
        hooks=[_Hooks()],
    )

    registered = list(agent.tool_registry.registry.keys())
    print(f"[TOOLS] {len(registered)} tools registered: {registered}")

    # Strip Gateway "target___" prefix so tool names match SOP references
    renames = {}
    for name in list(agent.tool_registry.registry.keys()):
        if "___" in name:
            bare = name.split("___", 1)[1]
            renames[name] = bare
    for old, new in renames.items():
        tool = agent.tool_registry.registry.pop(old)
        tool._agent_tool_name = new
        agent.tool_registry.registry[new] = tool
    if renames:
        print(f"[TOOLS] Renamed {len(renames)} tools: {list(renames.values())}")

    # Wrap MCP tools so a SAP `authentication_required` result raises an interrupt
    # (resumable on the same turn) rather than surfacing as a plain tool result.
    if _SAP_AUTH_INTERRUPT:
        n = wrap_sap_auth_tools(agent)
        print(f"[AUTH] SAP auth-interrupt wrappers: {n} tool(s)")

    return agent, metrics_hook, turns_hook


def _build_prompt(payload: dict) -> str:
    """Build agent prompt by dispatching on trigger type.

    SQS-invoked payloads have: {case_id, trigger, payload: {...}}
    Chat/frontend payloads have: {case_id, user_prompt, process_type, ...}
    """
    case_id = payload.get("case_id", "")
    trigger = payload.get("trigger", "")
    ctx = payload.get("payload", {})

    # Ticket action — reviewer approved/denied/replied
    if trigger == "ticket-action":
        ticket_id = ctx.get("ticket_id", "")
        decision = ctx.get("ticket_decision", "")
        response_text = ctx.get("response_text", "")
        if decision == "replied" and response_text:
            fenced_response = fence_data(
                sanitize_external_content(response_text, source="ticket-reply"),
                source="ticket-reply", ticket_id=ticket_id,
            )
            return (
                f"Resume case: {case_id}\n"
                f"Ticket {ticket_id} received a free-text reply from a human reviewer.\n\n"
                f"{fenced_response}\n\n"
                f"Call get_ticket for full details, then incorporate this response and continue per SOP."
            )
        return (
            f"Resume case: {case_id}\n"
            f"Ticket {ticket_id} has been {decision} by a human reviewer.\n"
            f"Call get_ticket for full details, then continue per SOP.\n"
            f"If approved, proceed with next steps. If denied, update case status and close."
        )

    # Webhook — inbound message from SES/Slack/Jira/ServiceNow
    if trigger.startswith("webhook"):
        channel = ctx.get("source", trigger.removeprefix("webhook-") or "unknown")
        sender = ctx.get("sender", "")
        message = ctx.get("message", "")
        subject = ctx.get("subject", "")

        # Build fenced data block from untrusted webhook content
        data_parts = []
        if subject:
            data_parts.append(f"Subject: {sanitize_external_content(subject, source=channel)}")
        if sender:
            data_parts.append(f"From: {sanitize_external_content(sender, source=channel)}")
        if message:
            data_parts.append(f"\n{sanitize_external_content(message, source=channel)}")
        fenced = fence_data("\n".join(data_parts), source=channel) if data_parts else ""

        instruction = (
            f"Process case {case_id} per SOP. Retrieve case state, then follow each step."
            if case_id
            else "Identify the relevant case from the message content, then process per SOP."
        )
        return f"Inbound {channel} message received.\n\n{fenced}\n\n{instruction}"

    # Poller or generic SQS trigger with a case_id
    if case_id:
        return f"Process case: {case_id}\nRetrieve case state, follow SOP, update state at each step."

    # Chat/frontend — direct user prompt
    user_prompt = payload.get("user_prompt") or payload.get("prompt")
    if user_prompt:
        return user_prompt

    return "No case or prompt provided."


def _save_trace_to_ddb(case_id: str, trigger: str, prompt: str, segments: list, outcome: str,
                       metrics: dict | None = None, audit_context: dict | None = None):
    """Save agent trace directly to DynamoDB cases table.

    Args:
        metrics: Optional dict with latency_ms, input_tokens, output_tokens,
                 cache_read_tokens, cache_write_tokens, estimated_cost_usd.
                 Added to the trace record when available.
        audit_context: Optional {initiator, correlation_id} persisted into the
                 trace so a SAP write is user-attributable from the case (T12).
    """
    import uuid
    from datetime import datetime, timezone
    from decimal import Decimal

    table_name = os.environ.get("CASES_TABLE")
    if not table_name or "#" not in case_id:
        return
    doc, item = case_id.split("#", 1)
    trace = {
        "trace_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trigger": trigger,
        "prompt": prompt,
        "outcome": outcome,
        "segments": segments,
    }
    # T12: persist initiator so writes are user-attributable (additive)
    if audit_context:
        trace["initiator"] = audit_context.get("initiator")
        trace["correlation_id"] = audit_context.get("correlation_id")
    # Enrich with metrics when available (additive — old traces without these fields still work)
    if metrics:
        trace["latency_ms"] = Decimal(str(round(metrics.get("latency_ms", 0), 1)))
        trace["input_tokens"] = metrics.get("input_tokens", 0)
        trace["output_tokens"] = metrics.get("output_tokens", 0)
        trace["cache_read_tokens"] = metrics.get("cache_read_tokens", 0)
        trace["cache_write_tokens"] = metrics.get("cache_write_tokens", 0)
        trace["estimated_cost_usd"] = Decimal(str(round(metrics.get("estimated_cost_usd", 0), 6)))
    # Per-case cost accumulator — sums across all invocations (initial + escalation resumptions)
    cost_delta = Decimal(str(round(metrics.get("estimated_cost_usd", 0), 6))) if metrics else Decimal("0")
    inp_delta = metrics.get("input_tokens", 0) if metrics else 0
    out_delta = metrics.get("output_tokens", 0) if metrics else 0
    cache_delta = metrics.get("cache_read_tokens", 0) if metrics else 0

    try:
        region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
        table = boto3.resource("dynamodb", region_name=region).Table(table_name)

        # Ensure cost_summary map exists (no-op if already present)
        try:
            table.update_item(
                Key={"document_number": doc, "item_id": item},
                UpdateExpression="SET cost_summary = if_not_exists(cost_summary, :init)",
                ExpressionAttributeValues={":init": {
                    "total_cost_usd": 0, "total_input_tokens": 0,
                    "total_output_tokens": 0, "total_cache_read_tokens": 0,
                    "invocation_count": 0,
                }},
                ConditionExpression="attribute_exists(document_number)",
            )
        except Exception:
            pass  # nosec B110 — best-effort init, ADD below will fail visibly if needed

        # Append trace + increment cost counters
        table.update_item(
            Key={"document_number": doc, "item_id": item},
            UpdateExpression=(
                "SET agent_traces = list_append(if_not_exists(agent_traces, :empty), :trace)"
                " ADD cost_summary.total_cost_usd :cost,"
                " cost_summary.total_input_tokens :inp,"
                " cost_summary.total_output_tokens :out,"
                " cost_summary.total_cache_read_tokens :cache,"
                " cost_summary.invocation_count :one"
            ),
            ExpressionAttributeValues={
                ":empty": [], ":trace": [trace],
                ":cost": cost_delta, ":inp": inp_delta,
                ":out": out_delta, ":cache": cache_delta, ":one": 1,
            },
            ConditionExpression="attribute_exists(document_number)",
        )
        print(f"[TRACE] Saved {trace['trace_id']} for {case_id} ({len(segments)} segments, outcome={outcome}, cost=${cost_delta:.4f})")
    except Exception as e:
        print(f"[TRACE] Failed to save for {case_id}: {e}")


def _flag_case_for_review(case_id: str, reason: str):
    """Move a case to manual_review_required with a reason. Used when the agent
    cannot safely run (e.g. SOP failed to load) — mirrors the DLQ-exhaustion path
    in agent_invoker so the case doesn't sit in 'processing' and a human is cued.
    `status` is a DynamoDB reserved word, so it's aliased."""
    from datetime import datetime, timezone

    table_name = os.environ.get("CASES_TABLE")
    if not table_name or "#" not in case_id:
        return
    doc, item = case_id.split("#", 1)
    try:
        region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
        table = boto3.resource("dynamodb", region_name=region).Table(table_name)
        table.update_item(
            Key={"document_number": doc, "item_id": item},
            UpdateExpression="SET #s = :s, status_reason = :r, updated_at = :t",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":s": "manual_review_required",
                ":r": reason,
                ":t": datetime.now(timezone.utc).isoformat(),
            },
            ConditionExpression="attribute_exists(document_number)",
        )
        print(f"[CASE] Flagged {case_id} for manual review: {reason}")
    except Exception as e:
        print(f"[CASE] Failed to flag {case_id} for review: {e}")


async def _stream_with_keepalive(agent, prompt, interval=15):
    """Wrap agent.stream_async with periodic SSE keepalive events to prevent idle timeouts.

    Each keepalive carries a monotonic sequence number and wall-clock timestamp
    so the frontend's readSSEStream diagnostics can correlate a disconnect with
    exactly which heartbeat should have arrived. See
    frontend/src/lib/agentcore-client/utils/sse.ts for the receiving side.
    """
    queue: asyncio.Queue = asyncio.Queue()
    done = False

    async def _produce():
        nonlocal done
        try:
            async for event in agent.stream_async(prompt):
                await queue.put(event)
        finally:
            done = True
            await queue.put(None)

    async def _keepalive():
        seq = 0
        while not done:
            await asyncio.sleep(interval)
            if not done:
                seq += 1
                await queue.put({
                    "keepalive": True,
                    "seq": seq,
                    "ts": time.time(),
                })

    producer = asyncio.create_task(_produce())
    heartbeat = asyncio.create_task(_keepalive())
    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item
    finally:
        heartbeat.cancel()
        await producer


@app.entrypoint
async def agent_stream(payload, context: RequestContext):
    """Main entrypoint — streams agent responses back to caller."""
    if payload is None:
        payload = {}

    session_id = (payload.get("runtimeSessionId") or payload.get("case_id") or "default-session").replace("#", "-")
    process_type = payload.get("process_type", "general")
    case_id = payload.get("case_id", "")
    trigger = payload.get("trigger", "manual")
    model_tier = "sonnet"
    agent_created = False
    segments: list = []
    prompt = ""
    outcome = "complete"

    try:
        user_id = extract_user_id_from_context(context)
        skill = _resolve_system_prompt(payload)
        model_tier = skill.get("model_tier", "sonnet")
        prompt = _build_prompt(payload)

        # Resume from a SAP-auth interrupt: after sign-in the frontend replays the
        # interrupt id. Feed Strands the interruptResponse list (not a text prompt) so
        # the paused tool re-runs on the SAME turn, its state restored from the session
        # by AgentCoreMemorySessionManager. `prompt` (text) is kept only for tracing.
        agent_input = prompt
        resume = payload.get("interrupt_response")
        if isinstance(resume, dict) and resume.get("interruptId"):
            agent_input = [{
                "interruptResponse": {
                    "interruptId": resume["interruptId"],
                    "response": resume.get("response", "authenticated"),
                }
            }]
            prompt = f"[resume after SAP sign-in: {resume['interruptId']}]"

        # Extract raw JWT for identity propagation to Gateway
        user_token = None
        if context.request_headers:
            auth_header = context.request_headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                user_token = auth_header[7:]

        # Build audit context for end-to-end traceability
        audit_context = {
            "correlation_id": session_id,
            "initiator": user_id,
            "trigger": trigger,
        }

        print(f"[STREAM] User: {user_id}, Session: {session_id}")
        print(f"[STREAM] process_type: {process_type}")
        print(f"[STREAM] Prompt preview: {prompt[:200]}...")

        agent, metrics_hook, turns_hook = _create_agent(skill, user_id, session_id, process_type, user_token=user_token, audit_context=audit_context)
        agent_created = True

        interrupted = False
        try:
            async for event in _stream_with_keepalive(agent, agent_input):
                # A tool raised a SAP-auth interrupt. Emit a clean signal the frontend
                # can act on (open the login, then resume this same turn). The generic
                # json.dumps(..., default=str) below stringifies the AgentResult via its
                # __str__ and would MASK stop_reason as text, so we special-case it here.
                result_obj = event.get("result") if isinstance(event, dict) else None
                if result_obj is not None and getattr(result_obj, "stop_reason", None) == "interrupt":
                    interrupted = True
                    outcome = "interrupted"
                    intrs = getattr(result_obj, "interrupts", None) or []
                    intr = intrs[0] if intrs else None
                    reason = getattr(intr, "reason", None) or {}
                    yield {"interrupt": {
                        "id": getattr(intr, "id", None),
                        "auth_url": reason.get("auth_url") if isinstance(reason, dict) else None,
                        "message": reason.get("message") if isinstance(reason, dict) else None,
                    }}
                    break

                evt = json.loads(json.dumps(dict(event), default=str))
                accumulate_segment(segments, evt)
                yield evt

            # Save trace immediately after the agent loop completes — before any
            # status yields. If the socket is dead, the finally block's yields will
            # fail silently, but the trace is already persisted.
            if segments and case_id:
                # Collect metrics from the hook (populated by on_end after agent completes)
                _save_trace_to_ddb(case_id, trigger, prompt, segments, outcome, metrics=metrics_hook.trace_metrics(), audit_context=audit_context)
        finally:
            if turns_hook.cancelled:
                outcome = "cancelled"
                # Update the already-saved trace with the cancelled outcome
                if segments and case_id:
                    _save_trace_to_ddb(case_id, trigger, prompt, segments, outcome, metrics=metrics_hook.trace_metrics(), audit_context=audit_context)
                yield {
                    "data": (
                        "\n\n⚠️ I reached the maximum processing limit "
                        f"({turns_hook.turn_count} turns) before I could summarize the results. "
                        "The actions above were completed successfully. "
                        "Please review the case state for details."
                    )
                }
                yield {"status": "cancelled", "reason": "max_turns", "turns": turns_hook.turn_count}
            elif interrupted:
                # Interrupt already yielded above; signal a non-terminal pause so the
                # frontend doesn't render a "completed" turn while awaiting sign-in.
                yield {"status": "interrupted"}
            else:
                yield {"status": "complete"}

    except SopLoadError as e:
        # The SOP that governs this case failed to load. Do NOT fall through to the
        # model — a missing mandatory SOP must fail the case, not authorize the agent
        # to freelance on general SAP knowledge. Flag for a human instead.
        print(f"[STREAM ERROR] SOP load failed: {e}")
        outcome = "error"
        _flag_case_for_review(case_id, f"SOP failed to load: {e}")
        emit_agent_metrics(
            process_type=process_type, model_tier=model_tier,
            turns=0, input_tokens=0, output_tokens=0,
            cache_read_tokens=0, cache_write_tokens=0,
            latency_ms=0, success=False,
        )
        yield {
            "data": (
                "\n\n❌ I couldn't load the Standard Operating Procedure for this case, "
                "so I've stopped rather than proceed without it. The case has been flagged "
                "for manual review."
            )
        }
        yield {"status": "error", "error": f"SOP load failed: {e}"}

    except Exception as e:
        print(f"[STREAM ERROR] {e}")
        traceback.print_exc()
        outcome = "error"
        if not agent_created:
            emit_agent_metrics(
                process_type=process_type, model_tier=model_tier,
                turns=0, input_tokens=0, output_tokens=0,
                cache_read_tokens=0, cache_write_tokens=0,
                latency_ms=0, success=False,
            )
        yield {"status": "error", "error": str(e)}

    # Trace already saved in the finally block above


if __name__ == "__main__":
    app.run()
