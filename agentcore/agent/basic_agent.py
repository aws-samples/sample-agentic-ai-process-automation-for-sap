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
from ag_ui.core import (
    EventType,
    RunAgentInput,
    RunErrorEvent,
    RunStartedEvent,
    UserMessage,
)
from ag_ui.encoder import EventEncoder
from ag_ui_strands import StrandsAgent, StrandsAgentConfig, add_ping
from bedrock_agentcore.identity.auth import requires_access_token
from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig
from bedrock_agentcore.memory.integrations.strands.session_manager import (
    AgentCoreMemorySessionManager,
)
from bedrock_agentcore.runtime import BedrockAgentCoreContext
from bedrock_agentcore.runtime.models import ACCESS_TOKEN_HEADER
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from mcp.client.streamable_http import streamablehttp_client
from strands import Agent, ModelRetryStrategy
from strands.hooks import (
    AfterInvocationEvent,
    AfterToolCallEvent,
    BeforeInvocationEvent,
    BeforeModelCallEvent,
    HookProvider,
    HookRegistry,
)
from strands.models import BedrockModel
from strands.models.bedrock import CacheConfig
from strands.tools.mcp import MCPClient
from strands.vended_plugins.skills import AgentSkills
from strands_tools import calculator, current_time
from utils.agent_metrics import _estimate_cost, emit_agent_metrics
from utils.auth import (
    extract_user_id_from_headers,
    is_user_bearer_token,
    to_memory_actor_id,
)
from utils.case_key import (
    CaseKeyError,
    format_case_id,
    to_case_key,
    to_runtime_session_id,
    try_normalize_case_id,
)
from utils.content_filter import fence_data, sanitize_external_content
from utils.conversation import MemorySafeSlidingWindow
from utils.evidence import (
    MAX_TRACES,
    cap_traces,
    extract_evidence,
    merge_evidence,
    result_text,
    sop_text_in,
)
from utils.mcp_topology import build_direct_mcp_headers, resolve_outbound_topology
from utils.model_config import sampling_kwargs
from utils.sap_auth_interrupt import wrap_sap_auth_tools
from utils.segments import accumulate_segment
from utils.skill_router import (
    SopLoadError,
    discovery_skills,
    list_skills,
    resolve_skill,
)
from utils.specialist import create_specialist
from utils.ssm import get_ssm_parameter

# When true, SAP MCP tools are wrapped so an `authentication_required` result pauses the
# Strands agent. The AG-UI adapter currently has no interrupt/resume mapping; queued runs
# therefore reject direct OBO topology rather than persisting or forwarding a browser JWT.
_SAP_AUTH_INTERRUPT = os.environ.get("SAP_AUTH_INTERRUPT", "").lower() == "true"

app = FastAPI(title="Agentic ERP Automation Runtime")
add_ping(app, "/ping")

# Fallback prompt when no process_type is provided (chat mode)
GENERAL_PROMPT = """You are an expert SAP exception handling specialist. You autonomously
investigate and resolve SAP exceptions across all domains.

Available skills: {skills_summary}

## AUTONOMOUS EXECUTION (CRITICAL)
When a user asks you to process a case:
1. IMMEDIATELY call get_case_state to retrieve the case details.
2. Identify the process_type from the case data.
3. If an <available_skills> block lists a skill matching that process_type, activate it
   with the skills tool — it returns the full Standard Operating Procedure along with the
   service and entity names to use. Otherwise use search_sap_sops to find the SOP, and
   discover the service once with find_sap_services and get_metadata.
4. Follow the SOP step by step WITHOUT asking the user for permission.
5. NEVER present a menu of options or ask "What would you like me to do first?"
6. Only stop for explicit approval gates defined in the SOP.

Use odata_read/odata_count for SAP reads and odata_create/odata_update/odata_function_import for SAP writes.
Pass `select` on every odata_read, naming only the fields you need — an unselected read returns
every field of the entity and is re-read on every later turn.
Use update_case_state to update case fields (status, amounts, dates).
"""


# When running locally (outside AgentCore Runtime), the @requires_access_token
# decorator cannot obtain a workload identity token. Instead, we fetch an M2M
# token directly from Cognito using client credentials stored in SSM/Secrets Manager.
_LOCAL_MODE = os.environ.get("LOCAL_MODE", "").lower() == "true"


def _bind_agentcore_workload_token(request: Request) -> None:
    """Bind Runtime's reserved workload token for AgentCore Identity decorators."""
    if _LOCAL_MODE:
        return

    workload_token = request.headers.get(ACCESS_TOKEN_HEADER)
    if not workload_token:
        raise ValueError("AgentCore Runtime request is missing its workload access token.")

    BedrockAgentCoreContext.set_workload_access_token(workload_token)


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
    import urllib.parse
    import urllib.request

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
        case_id = try_normalize_case_id(payload.get("case_id"))
        if not case_id:
            # Try document_number + item_id from payload or inner payload
            doc = payload.get("document_number") or inner.get("document_number")
            item = payload.get("item_id") or inner.get("item_id")
            if doc and item:
                try:
                    case_id = format_case_id(doc, item)
                except CaseKeyError:
                    case_id = None
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

    # General mode — the process type is unknown, so the agent has to classify before
    # it can follow a procedure. AgentSkills advertises one skill per process_type and
    # serves the full SOP on activation; the skills_summary below is the fallback for
    # when no skill has a loadable SOP (see _discovery_plugin).
    skills = list_skills()
    summary = "\n".join(
        f"- {s['display_name']} ({', '.join(s['process_types'])}): {s['description']}"
        for s in skills
    )
    return {
        "system_prompt": GENERAL_PROMPT.format(skills_summary=summary),
        "model_tier": "sonnet",
        "max_turns": 15,
        "discovery": True,
    }


def _extract_case_id(text: str) -> str | None:
    """Extract a canonical case_id from free-text prompt."""
    # "document_number=141, item_id=1" or "document_number=141 item_id=1"
    m = re.search(r'document_number[=:\s]+(\w+)[,\s]+item_id[=:\s]+(\w+)', text)
    if m:
        try:
            return format_case_id(m.group(1), m.group(2))
        except CaseKeyError:
            return None
    # "case 141-1", or the legacy "case 141#1" quoted by older notifications
    m = re.search(r'(?i)case[:\s]+(\d[\w#/-]+)', text)
    return try_normalize_case_id(m.group(1)) if m else None


def _safe_session_id(thread_id: str | None) -> str | None:
    """Collapse a caller-supplied thread id to the charset Memory session ids allow.

    Same shape of control as ``to_memory_actor_id`` applies to actor ids: the value
    reaches AgentCore Memory, so an out-of-charset character (historically `#`) has
    to be replaced rather than forwarded.
    """
    if not thread_id:
        return None
    return re.sub(r"[^a-zA-Z0-9\-_/:]", "-", str(thread_id))


def _case_session_id(payload: dict) -> str | None:
    """Derive a stable Memory session id from the payload's case identity, if any."""
    case_id = try_normalize_case_id(payload.get("case_id"))
    return to_runtime_session_id(case_id) if case_id else None


def _lookup_process_type(case_id: str) -> str | None:
    """Look up process_type from DynamoDB cases table."""
    table_name = os.environ.get("CASES_TABLE")
    if not table_name:
        return None
    try:
        table = boto3.resource("dynamodb").Table(table_name)
        resp = table.get_item(Key=to_case_key(case_id), ProjectionExpression="process_type")
        return resp.get("Item", {}).get("process_type")
    except Exception as e:
        print(f"[ROUTING] Case lookup failed for {case_id}: {e}")
        return None


# Model tier → Bedrock model ID mapping (override via env vars)
MODEL_TIERS = {
    "haiku": os.environ.get("MODEL_ID_HAIKU", "us.anthropic.claude-haiku-4-5-20251001-v1:0"),
    "sonnet": os.environ.get("MODEL_ID", "us.anthropic.claude-sonnet-5"),
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


class EvidenceHook:
    """Collects structured evidence per tool call, keyed by toolUseId.

    AfterToolCallEvent is the right seam: `ToolUse.input` is still a real dict
    here, whereas segments.py only ever sees tool_input as concatenated AG-UI
    delta strings and would have to re-parse JSON that was already flattened.

    The hook is read-only — it never sets `event.retry` and never touches the
    result. (AfterToolCallEvent is not interruptible anyway; that is why SAP auth
    uses an AgentTool wrapper instead. See utils/sap_auth_interrupt.py.)
    """

    def __init__(self, via_gateway: bool, sop_baseline: str = ""):
        self._via_gateway = via_gateway
        self._mode = os.environ.get("CEDAR_ENFORCEMENT_MODE", "LOG_ONLY")
        self._by_tool_call_id: dict[str, dict] = {}
        # What a quoted citation is checked against: the SOP text the run was
        # given. Starts as the injected document and grows with each load_sop /
        # search_sap_sops result, which is what makes the discovery path — where
        # nothing is injected up front — gradeable on the same footing.
        self._injected_sop = sop_baseline
        self._sop_baseline = sop_baseline

    def on_start(self, event: BeforeInvocationEvent) -> None:
        # Containers are warm and reused; without this, one case's evidence
        # merges into the next case's trace.
        self._by_tool_call_id = {}
        self._sop_baseline = self._injected_sop

    def on_tool_call(self, event: AfterToolCallEvent) -> None:
        from datetime import datetime, timezone

        try:
            tool_use = event.tool_use or {}
            tool_call_id = tool_use.get("toolUseId")
            if not tool_call_id:
                return
            result = event.result if isinstance(event.result, dict) else None
            # A retried tool call fires this hook once per attempt with the same
            # toolUseId, so the last attempt — the one whose result is kept in
            # conversation history — wins. That is the correct record.
            evidence = extract_evidence(
                tool_use.get("name", ""),
                tool_use.get("input"),
                result,
                at=datetime.now(timezone.utc).isoformat(),
                mode=self._mode,
                via_gateway=self._via_gateway,
                sop_baseline=self._sop_baseline,
            )
            # A fetched SOP joins the baseline for every later call. Retrieved text
            # renders differently from the injected copy (the retrieval path leaves
            # `{{SYMBOL}}` constants unresolved by design), so both renderings have
            # to be present for a quote of either to verify.
            if evidence.get("kind") == "sop_lookup":
                self._sop_baseline = f"{self._sop_baseline}\n{result_text(result)}"
            self._by_tool_call_id[tool_call_id] = {
                "evidence": evidence,
                "status": (result or {}).get("status") or "error",
            }
        except Exception as error:  # never fail a tool call over telemetry
            print(f"[EVIDENCE] Extraction failed: {error}")

    def evidence_by_tool_call_id(self) -> dict[str, dict]:
        """Merge material for _save_trace_to_ddb, keyed by the same
        `tool_call_id` that segments.py already records."""
        return self._by_tool_call_id

    def status_for(self, tool_call_id: str | None) -> str | None:
        """ToolResult.status for a call, or None if this hook never saw it.

        The AG-UI protocol has no error field on TOOL_CALL_RESULT, so a failed tool
        streams as an ordinary result and renders green until the page is reloaded and
        the persisted `segment.status` takes over. This hook is the only place the
        SDK-native status exists mid-stream: Strands fires AfterToolCallEvent before
        re-emitting the ToolResultEvent the adapter turns into TOOL_CALL_RESULT.
        """
        return (self._by_tool_call_id.get(tool_call_id or "") or {}).get("status")


def _assert_direct_topology_bearer(user_token: str | None) -> None:
    """Refuse the direct/OBO outbound topology unless the bearer is a USER token.

    Token type, not merely presence. The direct topology promotes this bearer to the
    primary Authorization header on the external MCP server, so it must belong to the
    acting human. On the queued path the caller bearer is the invoker's Cognito
    client_credentials token, and forwarding that would let a service identity act as
    if it were a user against SAP.

    This is a backstop. The authoritative statement of whether an unattended path
    exists at all is the mode axis in auth-profiles.yaml, enforced at synth by
    resolveModeProfile in cdk/lib/backend-stack.ts. This catches a deployment that has
    drifted from its declared profile.
    """
    if not is_user_bearer_token(user_token or ""):
        raise ValueError(
            "Direct MCP OBO requires an interactive user token. The presented bearer is "
            "absent, unreadable, or a client_credentials service token, which must never "
            "be exchanged as though it were the acting user. Queued runs must use the "
            "Gateway machine-token topology."
        )


def _discovery_plugin(skill: dict) -> AgentSkills | None:
    """Build the AgentSkills plugin for the discovery path, or None on the queued path.

    Only the general/chat path gets skills. When `process_type` is known, resolve_skill
    has already injected the right SOP deterministically — swapping that for a model
    decision plus a tool round-trip would trade correctness for nothing.

    None when no SOP could be loaded for any process_type: the plugin would otherwise
    inject "No skills are currently available", contradicting the skills_summary the
    general prompt already carries.
    """
    if not skill.get("discovery"):
        return None
    skills = discovery_skills(sop_bucket=os.environ.get("SOP_BUCKET"))
    if not skills:
        return None
    print(f"[SKILL] Discovery mode: {len(skills)} activatable skills")
    return AgentSkills(skills=skills)


def _create_agent(
    skill: dict,
    user_id: str,
    session_id: str,
    process_type: str,
    user_token: str | None = None,
    audit_context: dict | None = None,
) -> tuple[
    Agent,
    MetricsHook,
    MaxTurnsHook,
    AgentCoreMemorySessionManager,
    HookProvider,
    EvidenceHook,
]:
    """Create the request-specific ERP agent template and adapter dependencies."""
    config = skill.get("config", {})
    use_multi_agent = config.get("multi_agent", False)

    model_tier = (
        (config.get("orchestrator_tier") if use_multi_agent else None)
        or skill.get("model_tier", "sonnet")
    )
    model_id = MODEL_TIERS.get(model_tier, MODEL_TIERS["sonnet"])
    max_turns = skill.get("max_turns", 15)

    bedrock_model = BedrockModel(
        model_id=model_id,
        cache_config=CacheConfig(strategy="auto"),
        **sampling_kwargs(model_id, 0.1),
        **_guardrail_kwargs(),
    )

    memory_id = os.environ.get("MEMORY_ID")
    if not memory_id:
        raise ValueError("MEMORY_ID environment variable is required")

    session_manager = AgentCoreMemorySessionManager(
        agentcore_memory_config=AgentCoreMemoryConfig(
            memory_id=memory_id,
            session_id=session_id,
            actor_id=to_memory_actor_id(user_id),
            # Historical toolUse/toolResult blocks (e.g. large SAP OData responses)
            # are dropped from restored history; only text turns are reloaded.
            filter_restored_tool_context=True,
        ),
        region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
    )

    stack_name = os.environ.get("STACK_NAME")
    try:
        outbound_flow = (
            get_ssm_parameter(f"/{stack_name}/outbound_flow")
            if stack_name
            else None
        )
    except ValueError:
        outbound_flow = None

    if resolve_outbound_topology(outbound_flow) == "direct":
        _assert_direct_topology_bearer(user_token)
        print(f"[AGENT] Outbound topology: direct-MCP (OBO), flow={outbound_flow}")
        mcp_client = _create_direct_mcp_client(
            user_token,
            config.get("gateway_tools"),
            audit_context=audit_context,
        )
    else:
        print(f"[AGENT] Outbound topology: gateway, flow={outbound_flow}")
        mcp_client = _create_gateway_client(
            config.get("gateway_tools"),
            user_token=user_token,
            audit_context=audit_context,
        )

    tools = [mcp_client, calculator, current_time]
    specialist = None
    specialist_tier = "sonnet"
    if use_multi_agent:
        specialist_tier = config.get("specialist_tier", "sonnet")
        specialist_model_id = MODEL_TIERS.get(
            specialist_tier, MODEL_TIERS["sonnet"]
        )
        specialist = create_specialist(model_id=specialist_model_id)
        tools.append(specialist.as_tool())
        print(
            f"[MULTI-AGENT] orchestrator={model_tier}, "
            f"specialist={specialist_tier}"
        )
    else:
        print(f"[SINGLE-AGENT] model_tier={model_tier}")

    print(f"[COST] model_id={model_id}, max_turns={max_turns}, cache=auto")

    turns_hook = MaxTurnsHook(max_turns)
    metrics_hook = MetricsHook(
        process_type,
        model_tier,
        turns_hook,
        specialist=specialist,
        specialist_tier=specialist_tier,
    )
    # via_gateway is False on the direct-MCP (OBO) topology, which bypasses our
    # Gateway and so traverses no Cedar policy evaluation.
    evidence_hook = EvidenceHook(
        via_gateway=resolve_outbound_topology(outbound_flow) == "gateway",
        sop_baseline=sop_text_in(skill.get("system_prompt", "")),
    )

    skills_plugin = _discovery_plugin(skill)
    if skills_plugin:
        # Passed as plain tools rather than via Agent(plugins=...): the plugin registry
        # lives on the template only, and the adapter copies the tool registry at init.
        tools.extend(skills_plugin.tools)

    class _Hooks(HookProvider):
        """Register turn-limit, metrics and evidence callbacks on the adapter's clone."""

        def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
            registry.add_callback(BeforeInvocationEvent, turns_hook.reset)
            registry.add_callback(BeforeModelCallEvent, turns_hook.check)
            registry.add_callback(BeforeInvocationEvent, metrics_hook.on_start)
            registry.add_callback(AfterInvocationEvent, metrics_hook.on_end)
            registry.add_callback(BeforeInvocationEvent, evidence_hook.on_start)
            registry.add_callback(AfterToolCallEvent, evidence_hook.on_tool_call)
            # Strands registers a plugin's @hook methods via its own plugin registry,
            # which only exists on the template. `plugins` is not among the params
            # ag_ui_strands._extract_agent_kwargs forwards (Agent keeps no `.plugins`
            # attribute), so without re-registering here the per-thread clone that
            # actually serves the turn would carry the `skills` tool but never inject
            # <available_skills> — the model would be told to activate skills it
            # cannot see. Verified by tests/unit/test_agent_skills_discovery.py.
            for callback in getattr(skills_plugin, "hooks", []):
                for event_type in getattr(callback, "_hook_event_types", []):
                    registry.add_callback(event_type, callback)

    hook_provider = _Hooks()

    # This is a template. ag-ui-strands creates the invocation agent and receives
    # the request-specific Memory session manager and hooks explicitly below.
    agent = Agent(
        name="SAPExceptionAgent",
        system_prompt=skill["system_prompt"],
        tools=tools,
        model=bedrock_model,
        trace_attributes={"user.id": user_id, "session.id": session_id},
        retry_strategy=ModelRetryStrategy(max_attempts=4, initial_delay=2),
        # Stated rather than defaulted: `conversation_manager` IS forwarded to the
        # adapter's per-thread clone, so leaving it unset silently ran window_size=40
        # there — below the message count a max_turns run produces, so mid-run
        # eviction was routine, and eviction is what triggers the restore-offset bug
        # MemorySafeSlidingWindow exists to defuse.
        #
        # A high window because eviction drops the OLDEST messages, the worst possible
        # edit for the CacheConfig(strategy="auto") prefix above: cache reads run
        # 11-14x input tokens (docs/evaluations/COST_BENCHMARK.md), and moving the
        # prefix converts those hits into writes. Oversized tool results are what
        # actually blow the window, and reduce_context truncates those (first/last
        # 200 chars) before it will evict anything.
        conversation_manager=MemorySafeSlidingWindow(
            window_size=120,
            should_truncate_results=True,
        ),
    )

    registered = list(agent.tool_registry.registry.keys())
    print(f"[TOOLS] {len(registered)} tools registered: {registered}")

    renames = {}
    for name in list(agent.tool_registry.registry.keys()):
        if "___" in name:
            renames[name] = name.split("___", 1)[1]
    for old, new in renames.items():
        tool = agent.tool_registry.registry.pop(old)
        tool._agent_tool_name = new
        agent.tool_registry.registry[new] = tool
    if renames:
        print(f"[TOOLS] Renamed {len(renames)} tools: {list(renames.values())}")

    if _SAP_AUTH_INTERRUPT:
        wrapped_count = wrap_sap_auth_tools(agent)
        print(f"[AUTH] SAP auth-interrupt wrappers: {wrapped_count} tool(s)")

    return agent, metrics_hook, turns_hook, session_manager, hook_provider, evidence_hook


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
        if decision == "replied":
            if response_text:
                fenced_response = fence_data(
                    sanitize_external_content(response_text, source="ticket-reply"),
                    source="ticket-reply", ticket_id=ticket_id,
                )
                return (
                    f"Resume case: {case_id}\n"
                    f"Ticket {ticket_id} received a free-text reply from a human reviewer.\n\n"
                    f"{fenced_response}\n\n"
                    f"Call demo_get_ticket for full details, then incorporate this response and continue per SOP."
                )
            return (
                f"Resume case: {case_id}\n"
                f"Ticket {ticket_id} received a free-text reply from a human reviewer.\n"
                f"Call demo_get_ticket to read the durable response, then continue per SOP."
            )
        return (
            f"Resume case: {case_id}\n"
            f"Ticket {ticket_id} has been {decision} by a human reviewer.\n"
            f"Call demo_get_ticket for full details, then continue per SOP.\n"
            f"If approved, proceed with next steps. If denied, update case status and close."
        )

    # Webhook — inbound message from SES/Jira/ServiceNow
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

    # An explicit UI prompt must win over the generic case-processing prompt.
    # The durable Runs API carries caseId separately for skill routing, audit, and
    # trace persistence; dropping the message here would turn focused-case chat
    # into an unintended autonomous "process case" request.
    #
    # Interactive chat and the /cases/enqueue route share trigger="manual" — both
    # are a human initiating work. The presence of a prompt is what separates them:
    # the invoker deliberately sends none so an enqueued case falls through to the
    # SOP instruction below.
    user_prompt = payload.get("user_prompt") or payload.get("prompt")
    if trigger == "manual" and user_prompt:
        return user_prompt

    # Poller or generic SQS trigger with a case_id
    if case_id:
        return f"Process case: {case_id}\nRetrieve case state, follow SOP, update state at each step."

    # Chat/frontend — direct user prompt
    if user_prompt:
        return user_prompt

    return "No case or prompt provided."


def _save_trace_to_ddb(case_id: str, trigger: str, prompt: str, segments: list, outcome: str,
                       metrics: dict | None = None, audit_context: dict | None = None,
                       evidence_by_id: dict | None = None,
                       sop_version: str | None = None):
    """Save agent trace directly to DynamoDB cases table.

    Args:
        metrics: Optional dict with latency_ms, input_tokens, output_tokens,
                 cache_read_tokens, cache_write_tokens, estimated_cost_usd.
                 Added to the trace record when available.
        audit_context: Optional {initiator, correlation_id} persisted into the
                 trace so a SAP write is user-attributable from the case (T12).
        evidence_by_id: Evidence keyed by tool_call_id, from EvidenceHook. Merged
                 onto matching segments; absent keys leave a segment in its
                 pre-migration shape.
        sop_version: Version that SOP declared, from resolve_skill. Recorded per run
                 so a precedent citing this case names the authority it followed,
                 not whichever revision is current when the precedent is written.
    """
    import uuid
    from datetime import datetime, timezone
    from decimal import Decimal

    table_name = os.environ.get("CASES_TABLE")
    if not table_name:
        return
    try:
        case_key = to_case_key(case_id)
    except CaseKeyError:
        return
    segments = merge_evidence(segments, evidence_by_id)
    trace = {
        "trace_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trigger": trigger,
        "prompt": prompt,
        "outcome": outcome,
        "segments": segments,
    }
    if sop_version:
        trace["sop_version"] = sop_version
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
                Key=case_key,
                UpdateExpression="SET cost_summary = if_not_exists(cost_summary, :init)",
                ExpressionAttributeValues={":init": {
                    "total_cost_usd": 0, "total_input_tokens": 0,
                    "total_output_tokens": 0, "total_cache_read_tokens": 0,
                    "invocation_count": 0,
                }},
                ConditionExpression="attribute_exists(case_id)",
            )
        except Exception:
            pass  # nosec B110 — best-effort init, ADD below will fail visibly if needed

        # Append trace + increment cost counters. ReturnValues gives back the new
        # list, which is the only way to trim: list_append has no drop-oldest form.
        response = table.update_item(
            Key=case_key,
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
            ConditionExpression="attribute_exists(case_id)",
            ReturnValues="UPDATED_NEW",
        )
        print(f"[TRACE] Saved {trace['trace_id']} for {case_id} ({len(segments)} segments, outcome={outcome}, cost=${cost_delta:.4f})")

        # ponytail: read-modify-write, safe because SQS FIFO serialises invocations
        # per case_id (MessageGroupId is the case id); gate on a version attribute
        # if a second writer is ever added.
        kept, dropped = cap_traces(response.get("Attributes", {}).get("agent_traces"), MAX_TRACES)
        if dropped:
            table.update_item(
                Key=case_key,
                UpdateExpression="SET agent_traces = :kept ADD traces_dropped :dropped",
                ExpressionAttributeValues={":kept": kept, ":dropped": dropped},
                ConditionExpression="attribute_exists(case_id)",
            )
            print(f"[TRACE] Capped {case_id} at {MAX_TRACES} traces ({dropped} dropped)")
    except Exception as e:
        print(f"[TRACE] Failed to save for {case_id}: {e}")


def _flag_case_for_review(case_id: str, reason: str):
    """Move a case to manual_review_required with a reason. Used when the agent
    cannot safely run (e.g. SOP failed to load) — mirrors the DLQ-exhaustion path
    in agent_invoker so the case doesn't sit in 'processing' and a human is cued.
    `status` is a DynamoDB reserved word, so it's aliased."""
    from datetime import datetime, timezone

    table_name = os.environ.get("CASES_TABLE")
    if not table_name:
        return
    try:
        case_key = to_case_key(case_id)
    except CaseKeyError:
        return
    try:
        region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
        table = boto3.resource("dynamodb", region_name=region).Table(table_name)
        table.update_item(
            Key=case_key,
            UpdateExpression="SET #s = :s, status_reason = :r, updated_at = :t",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":s": "manual_review_required",
                ":r": reason,
                ":t": datetime.now(timezone.utc).isoformat(),
            },
            ConditionExpression="attribute_exists(case_id)",
        )
        print(f"[CASE] Flagged {case_id} for manual review: {reason}")
    except Exception as e:
        print(f"[CASE] Failed to flag {case_id} for review: {e}")


def _event_name(event) -> str:
    value = getattr(event, "type", "")
    return value.value if hasattr(value, "value") else str(value)


def _canonical_event(event) -> dict:
    return event.model_dump(mode="json", by_alias=True)


def _runtime_payload(input_data: RunAgentInput) -> dict:
    """Extract the legacy ERP envelope carried inside canonical AG-UI input."""
    forwarded_props = input_data.forwarded_props
    if isinstance(forwarded_props, dict):
        candidate = forwarded_props.get("erpPayload")
        if isinstance(candidate, dict):
            payload = dict(candidate)
        else:
            payload = {
                key: value
                for key, value in forwarded_props.items()
                if key != "erpPayload"
            }
    else:
        payload = {}

    payload["runtimeSessionId"] = input_data.thread_id
    return payload


def _input_with_prompt(input_data: RunAgentInput, prompt: str) -> RunAgentInput:
    """Put the sanitized trigger-specific prompt into the AG-UI message history."""
    messages = list(input_data.messages or [])
    for index in range(len(messages) - 1, -1, -1):
        if getattr(messages[index], "role", None) == "user":
            messages[index] = messages[index].model_copy(update={"content": prompt})
            break
    else:
        messages.append(
            UserMessage(
                id=f"input-{input_data.run_id}",
                role="user",
                content=prompt,
            )
        )

    # Client-defined proxy tools are intentionally disabled. All ERP tools are selected
    # server-side by the skill router and enforced by Gateway/Cedar.
    return input_data.model_copy(update={"messages": messages, "tools": []})


def _interactive_user_token(request: Request) -> str | None:
    """Return the Runtime-validated caller bearer.

    Named for the interactive path but reached by every caller. This deployment runs a
    SINGLE Runtime with one authorizer, and nothing in-process distinguishes a browser
    caller from the invoker's machine client, so this cannot decide which path it is on.

    Whether an unattended path exists at all is declared elsewhere: the mode axis in
    auth-profiles.yaml, enforced at synth (see resolveModeProfile in
    cdk/lib/backend-stack.ts). The direct-OBO path additionally asserts the bearer is a
    user token rather than client_credentials.
    """
    authorization = request.headers.get("authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token.strip():
        raise ValueError("Interactive Runtime request is missing a bearer token.")
    return token.strip()


_KEEPALIVE_INTERVAL_SECONDS = 15.0

# RUN_ERROR codes this module constructs itself. Their messages are written for the
# user and are safe to forward; anything else came out of the adapter or the model
# and may carry internal detail.
_OWN_ERROR_CODES = frozenset(
    {
        "MAX_TURNS_REACHED",
        "MAX_TOKENS_REACHED",
        "AGENT_STREAM_INCOMPLETE",
        "SOP_LOAD_ERROR",
        "ERP_AGENT_ERROR",
    }
)


def _sanitized_run_error(event, canonical: dict, *, run_id: str):
    """Replace an adapter-generated RUN_ERROR message with a fixed one.

    The browser renders ``RUN_ERROR.message`` directly into the chat. A failure
    raised inside the agent loop reaches here formatted by whichever library
    raised it, which can carry ARNs, endpoint hostnames, or SAP response
    fragments. Errors this module builds are already written for the user and
    pass through unchanged; everything else is replaced and the detail is logged
    server-side instead.

    ag-ui-strands 0.2.3 converts Strands' typed ``MaxTokensReachedException``
    into a generic ``STRANDS_ERROR``. Recognize only that pinned, fixed prefix so
    queued callers can stop safely without treating unrelated adapter failures as
    non-retryable.
    """
    code = canonical.get("code")
    if code in _OWN_ERROR_CODES:
        return event

    detail = canonical.get("message") or ""
    if code == "STRANDS_ERROR" and detail.startswith(
        "Model stopped generating due to maximum token limit."
    ):
        return RunErrorEvent(
            type=EventType.RUN_ERROR,
            message=(
                "The agent reached its configured output limit. "
                "Review the case state for actions completed before it stopped."
            ),
            code="MAX_TOKENS_REACHED",
        )

    print(f"[AG-UI] Suppressed adapter error detail for run {run_id}: {detail!r}")
    return RunErrorEvent(
        type=EventType.RUN_ERROR,
        message=(
            "The agent stopped on an internal error. "
            "Review the case state for actions completed before it stopped."
        ),
        code="AGENT_INTERNAL_ERROR",
    )


def _keepalive_frame(seq: int, started_at: float) -> str:
    """An SSE comment heartbeat.

    A comment is bytes on the wire that no conformant SSE client reads as an
    event, so it keeps the connection warm without adding anything the AG-UI
    reducer has to know about. The sequence and elapsed milliseconds make a
    disconnect correlatable to the heartbeat that should have followed.
    """
    elapsed_ms = int((time.monotonic() - started_at) * 1000)
    return f": keepalive {seq} {elapsed_ms}\n\n"


async def _with_keepalive(source, interval: float = _KEEPALIVE_INTERVAL_SECONDS):
    """Interleave heartbeat ticks into an AG-UI event stream.

    A single SAP OData call can leave the stream idle for minutes, and an
    intermediate hop will drop an idle connection — the failure this whole
    migration sits on top of. The pre-AG-UI entrypoint solved it with
    ``_stream_with_keepalive``; the adapter owns the event loop now, so the
    heartbeat has to be interleaved from outside it.

    Yields ``("event", event)`` for a source event and ``("keepalive", seq)``
    for a tick, so the caller encodes each appropriately.
    """
    queue: asyncio.Queue = asyncio.Queue()
    done = False

    async def _produce():
        nonlocal done
        try:
            async for event in source:
                await queue.put(("event", event))
        finally:
            # Signal completion even on failure; the exception stays on the task
            # and is re-raised by the consumer's `await producer` below.
            done = True
            await queue.put(None)

    async def _beat():
        seq = 0
        while not done:
            await asyncio.sleep(interval)
            if done:
                break
            seq += 1
            await queue.put(("keepalive", seq))

    producer = asyncio.create_task(_produce())
    heartbeat = asyncio.create_task(_beat())
    completed = False
    try:
        while True:
            item = await queue.get()
            if item is None:
                completed = True
                break
            yield item
    finally:
        heartbeat.cancel()
        if completed:
            # Re-raise a source failure so the caller's error handling still runs.
            await producer
        else:
            # Consumer closed early (client disconnected) — stop the source.
            producer.cancel()


@app.post("/invocations")
async def agent_stream(
    input_data: RunAgentInput,
    request: Request,
) -> StreamingResponse:
    """Run the request-specific ERP agent and emit the native AG-UI SSE contract."""
    encoder = EventEncoder(accept=request.headers.get("accept"))

    async def event_generator():
        payload = _runtime_payload(input_data)
        # The AG-UI thread id is authoritative when the caller supplies one, but it is
        # caller-controlled, so it is collapsed to the charset AgentCore Memory ids
        # allow. Falling back to the case identity gives a stable, Memory-legal
        # session id — the codec also clears the Runtime's minimum id length, which a
        # bare case_id does not.
        session_id = (
            _safe_session_id(input_data.thread_id)
            or _case_session_id(payload)
            or "default-session"
        )
        process_type = payload.get("process_type", "general")
        case_id = payload.get("case_id", "")
        trigger = payload.get("trigger", "manual")
        model_tier = "sonnet"
        agent_created = False
        started_emitted = False
        terminal_emitted = False
        metrics_hook = None
        turns_hook = None
        evidence_hook = None
        segments: list = []
        prompt = ""
        outcome = "unknown"
        audit_context: dict = {}
        # Captured out of `skill` here because the trace is written from the
        # finally: below, where resolution may have raised and `skill` be unbound.
        sop_version = ""

        try:
            _bind_agentcore_workload_token(request)
            user_id = extract_user_id_from_headers(request.headers)
            user_token = _interactive_user_token(request)
            skill = _resolve_system_prompt(payload)
            model_tier = skill.get("model_tier", "sonnet")
            sop_version = skill.get("sop_version") or ""
            prompt = _build_prompt(payload)
            runtime_input = _input_with_prompt(input_data, prompt)

            audit_context = {
                # `initiator` is the subject of the Runtime-validated bearer, so it is
                # authoritative for interactive turns ONLY. On the queued path the bearer
                # is the invoker's Cognito client_credentials token, so a case a human
                # enqueued from the UI attributes to the machine subject here, in the
                # x-audit-initiator header, and in the persisted trace. The invoker does
                # send x-user-identity, but that header is absent from the Runtime's
                # allowlist and cannot be opened on a Runtime whose authorizer also
                # accepts the browser client — see the boundary note in
                # utils/auth.get_inbound_identity_from_headers. Closing this needs a
                # machine-only Runtime; until then do not read `initiator` as the
                # acting human for runs whose trigger is not interactive chat.
                "correlation_id": input_data.run_id,
                "initiator": user_id,
                "trigger": trigger,
            }

            print(f"[AG-UI] User: {user_id}, Thread: {session_id}")
            print(f"[AG-UI] Run: {input_data.run_id}, process_type: {process_type}")
            print(f"[AG-UI] Prompt preview: {prompt[:200]}...")

            (
                template_agent,
                metrics_hook,
                turns_hook,
                session_manager,
                hook_provider,
                evidence_hook,
            ) = _create_agent(
                skill,
                user_id,
                session_id,
                process_type,
                user_token=user_token,
                audit_context=audit_context,
            )
            agent_created = True

            agui_agent = StrandsAgent(
                # Constructed AFTER _create_agent, which is load-bearing: StrandsAgent
                # captures the tool registry at init, and _create_agent is what pops and
                # re-registers the SAP tools with the `target___` prefix stripped.
                # Building the adapter first would expose prefixed tool names that no
                # longer match the names SOPs reference. Verified against
                # ag-ui-strands 0.2.3; see tests/unit/test_adapter_version_pin.py.
                agent=template_agent,
                name="SAPExceptionAgent",
                description="Skill-routed SAP exception processing agent",
                config=StrandsAgentConfig(
                    session_manager_provider=lambda _: session_manager,
                    emit_messages_snapshot=True,
                    replay_history_into_strands=False,
                ),
                hooks=[hook_provider],
            )

            # An immediate heartbeat confirms the stream opened before the model has
            # produced anything, and starts the cadence for the idle gaps that follow.
            keepalive_started_at = time.monotonic()
            yield _keepalive_frame(0, keepalive_started_at)

            async for kind, item in _with_keepalive(agui_agent.run(runtime_input)):
                if kind == "keepalive":
                    yield _keepalive_frame(item, keepalive_started_at)
                    continue
                event = item
                event_name = _event_name(event)
                if (
                    event_name == "RUN_FINISHED"
                    and turns_hook is not None
                    and turns_hook.cancelled
                ):
                    event = RunErrorEvent(
                        type=EventType.RUN_ERROR,
                        message=(
                            "The agent reached its configured processing limit. "
                            "Review the case state for actions completed before it stopped."
                        ),
                        code="MAX_TURNS_REACHED",
                    )
                    event_name = "RUN_ERROR"

                canonical = _canonical_event(event)
                accumulate_segment(segments, canonical)
                started_emitted = started_emitted or event_name == "RUN_STARTED"
                if event_name == "RUN_FINISHED":
                    outcome = "complete"
                    terminal_emitted = True
                elif event_name == "RUN_ERROR":
                    outcome = (
                        "cancelled"
                        if turns_hook is not None and turns_hook.cancelled
                        else "error"
                    )
                    terminal_emitted = True
                    event = _sanitized_run_error(event, canonical, run_id=input_data.run_id)
                elif event_name == "TOOL_CALL_RESULT" and evidence_hook is not None:
                    # AG-UI defines no failure field on this event, so the reducer would
                    # render a failed call as complete until a reload picks up the
                    # persisted segment.status. ag_ui's models allow extras, so the
                    # SDK-native status rides along on the same event.
                    if evidence_hook.status_for(canonical.get("toolCallId")) == "error":
                        event = event.model_copy(update={"status": "error"})
                yield encoder.encode(event)

            if not terminal_emitted:
                outcome = "error"
                error_event = RunErrorEvent(
                    type=EventType.RUN_ERROR,
                    message="The agent stream ended without a terminal event.",
                    code="AGENT_STREAM_INCOMPLETE",
                )
                terminal_emitted = True
                yield encoder.encode(error_event)

        except SopLoadError as error:
            print(f"[AG-UI ERROR] SOP load failed: {error}")
            outcome = "error"
            _flag_case_for_review(case_id, f"SOP failed to load: {error}")
            emit_agent_metrics(
                process_type=process_type,
                model_tier=model_tier,
                turns=0,
                input_tokens=0,
                output_tokens=0,
                cache_read_tokens=0,
                cache_write_tokens=0,
                latency_ms=0,
                success=False,
            )
            if not started_emitted:
                yield encoder.encode(
                    RunStartedEvent(
                        type=EventType.RUN_STARTED,
                        thread_id=input_data.thread_id,
                        run_id=input_data.run_id,
                    )
                )
                started_emitted = True
            if not terminal_emitted:
                yield encoder.encode(
                    RunErrorEvent(
                        type=EventType.RUN_ERROR,
                        message=(
                            "The Standard Operating Procedure could not be loaded. "
                            "The case was flagged for manual review."
                        ),
                        code="SOP_LOAD_ERROR",
                    )
                )
                terminal_emitted = True

        except Exception as error:
            print(f"[AG-UI ERROR] {error}")
            traceback.print_exc()
            outcome = "error"
            if not agent_created:
                emit_agent_metrics(
                    process_type=process_type,
                    model_tier=model_tier,
                    turns=0,
                    input_tokens=0,
                    output_tokens=0,
                    cache_read_tokens=0,
                    cache_write_tokens=0,
                    latency_ms=0,
                    success=False,
                )
            if not started_emitted:
                yield encoder.encode(
                    RunStartedEvent(
                        type=EventType.RUN_STARTED,
                        thread_id=input_data.thread_id,
                        run_id=input_data.run_id,
                    )
                )
                started_emitted = True
            if not terminal_emitted:
                yield encoder.encode(
                    RunErrorEvent(
                        type=EventType.RUN_ERROR,
                        message="The agent run failed.",
                        code="ERP_AGENT_ERROR",
                    )
                )
                terminal_emitted = True

        finally:
            if segments and case_id:
                metrics = metrics_hook.trace_metrics() if metrics_hook else None
                _save_trace_to_ddb(
                    case_id,
                    trigger,
                    prompt,
                    segments,
                    outcome,
                    metrics=metrics,
                    audit_context=audit_context,
                    evidence_by_id=(
                        evidence_hook.evidence_by_tool_call_id() if evidence_hook else None
                    ),
                    sop_version=sop_version,
                )

    return StreamingResponse(
        event_generator(),
        media_type=encoder.get_content_type(),
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("AGENTCORE_HOST", "0.0.0.0"),  # nosec B104 - container entrypoint, must be reachable from outside
        port=int(os.environ.get("AGENTCORE_PORT", "8080")),
    )
