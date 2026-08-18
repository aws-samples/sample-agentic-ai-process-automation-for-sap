# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Structured provenance for one tool call — the evidence model.

Pure stdlib on purpose. basic_agent.py pulls in strands/mcp and is not importable
in the hermetic test env, so every function here takes plain dicts reduced from a
ToolUse/ToolResult pair rather than SDK objects (same constraint as
utils/mcp_topology.py). That is what keeps tests/unit/ able to import it.

Nothing here depends on model cooperation: `kind`, `at`, `source` and `fields`
are deterministic functions of the tool name, its input, and its result.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

# Extraction runs BEFORE truncation, so the structured facts survive and the raw
# blob does not need to.
TOOL_RESULT_MAX_BYTES = 512
TOOL_INPUT_MAX_BYTES = 256

# Per-case trace cap, oldest dropped. Bounds both the DynamoDB item and the
# GET /cases payload the console aggregates client-side.
MAX_TRACES = 25

# A wide entity must not blow the item budget through `fields` alone.
MAX_FIELDS = 12

# A notification body is prose, not a field value: enough to carry the quoted
# citation and the gist, not the whole message. Citation verification runs on the
# raw argument, before this cut — a quote past char 240 would otherwise fail on a
# fragment of itself.
PROSE_MAX_CHARS = 240

# A quote shorter than this proves nothing: "must not" matches nearly any SOP.
# Measured on price_variance.txt — 8-word spans are unique (0% repeated), 5-word
# 1%, 2-word 10%.
QUOTE_MIN_WORDS = 6

# Without a ceiling, pasting the whole SOP "verifies" trivially. A citation has
# to be specific to be a citation. Both bounds earn their place: three terse
# sentences fit well under the char cap, and a page of headings and `====`
# dividers terminates twice or not at all.
QUOTE_MAX_SENTENCES = 2
QUOTE_MAX_CHARS = 320

# The prose-carrying arguments across the three tools mapped to `notification`.
# Ordered subject-then-body so the summary line reads first.
_NOTIFICATION_PROSE = (
    "subject",
    "title",
    "body",
    "description",
    "resolution",
    "comment",
)

# In-process tools — no Gateway, so no policy evaluation to report.
LOCAL_TOOLS = frozenset({"calculator", "current_time"})

_KIND_BY_TOOL = {
    "odata_read": "sap_read",
    "odata_count": "sap_read",
    "odata_update": "sap_write",
    "odata_create": "sap_write",
    "odata_function_import": "sap_write",
    "search_sap_sops": "sop_lookup",
    "search_sap_api_docs": "sop_lookup",
    "load_sop": "sop_lookup",
    # Activating a discovery skill returns the SOP, so it is a lookup — not the
    # sourceless `computation` fallthrough, which would skip clause extraction and
    # leave every discovery-path run unable to cite what it followed.
    "skills": "sop_lookup",
    "update_case_state": "case_update",
    "send_notification": "notification",
    # Ticket creation IS the escalation channel, so it is a notification.
    "demo_create_ticket": "notification",
}

_OP_BY_TOOL = {
    "odata_update": "update",
    "odata_create": "create",
    "odata_function_import": "function_import",
}

# Numbered SOP clauses: "1.1  The agent MUST ...". Not line-anchored: Bedrock
# Retrieve returns each chunk with newlines collapsed to spaces, so a `^` match
# found nothing in production even though the SOPs are numbered. The two-space
# gap and capital are what remain of the line break; the digit bounds keep
# decimals like "100.000" in the API docs from reading as clauses.
_CLAUSE_RE = re.compile(r"(?<![\w.])(\d{1,2}\.\d{1,2})\s{2,}[A-Z]")

# OData filters quote their key values: "PurchaseOrder eq '4500000123'".
_QUOTED_RE = re.compile(r"'([^']*)'")

# The SOP as injected by resolve_skill, which wraps it in these delimiters.
_SOP_DOCUMENT_RE = re.compile(r"<sop_document>\n(.*?)\n</sop_document>", re.DOTALL)

# A quoted citation span. Straight and curly doubles only — an apostrophe in
# "supplier's" would otherwise open a span, and single-quoted prose is rare
# enough that missing it costs a verdict, not a false one.
_QUOTED_SPAN_RE = re.compile(r"[\"“”]([^\"“”]{2,600})[\"“”]")

# Sentence terminators, for the two-sentence ceiling. Counted after
# normalization, where the text is already lowercased and space-collapsed.
_SENTENCE_END_RE = re.compile(r"[.!?](?:\s|$)")

# Typographic variants a model round-trips text through. NFKC leaves all of these
# alone, so they are folded explicitly or a verbatim quote fails on punctuation.
_QUOTE_FOLD = str.maketrans(
    {"“": '"', "”": '"', "„": '"', "‘": "'", "’": "'", "–": "-", "—": "-", " ": " "}
)

# The only authorization-shaped rejection visible to the agent is the tool
# Lambdas' PermissionError on a missing Gateway tool context. Everything else
# that fails is a transport or SAP fault, and must not be reported as a denial.
_AUTHZ_DENIED_RE = re.compile(
    r"not permitted|permissionerror|access ?denied|unauthorized|forbidden|\b40[13]\b",
    re.IGNORECASE,
)


def result_text(result: dict | None) -> str:
    """Join a ToolResult's content blocks into one string.

    ToolResult.content is a list of {document|image|json|text} blocks, not a bare
    string, so a caller that treats it as one silently gets "[{'text': ...}]".
    """
    if not isinstance(result, dict):
        return ""
    parts = []
    for block in result.get("content") or []:
        if not isinstance(block, dict):
            continue
        if isinstance(block.get("text"), str):
            parts.append(block["text"])
        elif "json" in block:
            parts.append(json.dumps(block["json"], default=str))
    return "\n".join(parts)


def clauses_in(text: str) -> list[str]:
    """Numbered SOP clauses appearing in `text`, in order, deduplicated.

    Used on both sides of the citation question: against a tool result, for what
    the agent retrieved; against the injected SOP at resolve_skill time, for what
    it could legitimately cite. One extractor, so the two cannot disagree about
    whether "3.2" is a clause.
    """
    return list(dict.fromkeys(_CLAUSE_RE.findall(text or "")))


def sop_text_in(system_prompt: str) -> str:
    """The SOP as the model actually sees it, pulled back out of the assembled prompt.

    resolve_skill wraps the SOP in `<sop_document>` and *then* runs substitution
    over the whole prompt, so this is the only place the post-substitution text
    exists — the raw file still reads `{{PRICE_VARIANCE_PCT}}` where the model was
    shown `2`, and a quote of the substituted sentence would grade as invented
    against it.
    """
    return "\n".join(_SOP_DOCUMENT_RE.findall(system_prompt or ""))


def normalize_quote(text: str) -> str:
    """Fold the differences a copy-paste through a model introduces, and nothing else.

    NFKC, smart quotes and dashes to ASCII, casefold, whitespace collapsed. The
    last one matters most: Bedrock Retrieve returns chunks with newlines already
    collapsed to spaces, so a quote of a clause that spans a line break only
    matches a baseline normalized the same way.
    """
    folded = unicodedata.normalize("NFKC", text or "")
    folded = folded.translate(_QUOTE_FOLD)
    return " ".join(folded.casefold().split())


def _candidate_quotes(prose: str) -> list[str]:
    """Spans the agent marked as quotation, longest first.

    Quote marks are the signal — the prompt asks for the sentence in quotes. A
    citation the agent wrote without them is not treated as a quote at all, which
    is the same verdict as paraphrasing: unverified, never violated.
    """
    if not isinstance(prose, str) or not prose:
        return []
    spans = [m.group(1) for m in _QUOTED_SPAN_RE.finditer(prose)]
    return sorted({s.strip() for s in spans if s.strip()}, key=len, reverse=True)


def _prose_in(value: Any) -> str:
    """The model-written text in a parsed argument, for citation verification.

    A string passes through — that is an argument the tool_spec declares as prose,
    or one whose JSON would not parse. A mapping contributes its string leaves,
    which is where a case-update note lives.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "\n".join(v for v in value.values() if isinstance(v, str))
    return ""


def verify_citation(prose: str, baseline: str) -> dict | None:
    """Check a quoted SOP span in `prose` against the text the run was given.

    Args:
        prose: a model-written argument (notification body, case-update note).
        baseline: every SOP text this run saw, concatenated — the injected
            document plus anything fetched mid-run. A union, not a choice: the
            injected and retrieved renderings of one clause differ (the retrieval
            path leaves `{{SYMBOL}}` constants unsubstituted, deliberately), and
            holding both means either rendering verifies.

    Returns:
        `{"quote": ..., "verified": bool}` for the best candidate span, or None
        when the prose quotes nothing gradeable. A clause *number* is never
        required and never parsed for: most real SOPs are not numbered, so
        demanding one would overfit to a hand-anchored corpus.

    A False verdict means the quote is absent from what the agent was shown. It is
    never on its own proof the agent violated the SOP — a compliant agent that
    paraphrases lands here too.
    """
    candidates = _candidate_quotes(prose)
    if not candidates:
        return None
    haystack = normalize_quote(baseline)
    gradeable = None
    for candidate in candidates:
        normalized = normalize_quote(candidate)
        if len(normalized.split()) < QUOTE_MIN_WORDS:
            continue
        if len(_SENTENCE_END_RE.findall(normalized)) > QUOTE_MAX_SENTENCES:
            continue
        if len(normalized) > QUOTE_MAX_CHARS:
            continue
        # First span that verifies wins; otherwise keep the longest gradeable one
        # so the recorded quote is the claim actually being reported as unverified.
        if haystack and normalized in haystack:
            return {"quote": candidate, "verified": True}
        if gradeable is None:
            gradeable = candidate
    if gradeable is None:
        return None
    return {"quote": gradeable, "verified": False}


def _tool_key(tool_name: str) -> str:
    """Strip the Gateway's `target___` prefix. _create_agent renames tools before
    the model sees them, but a direct-MCP (OBO) call can still arrive prefixed."""
    return (tool_name or "").split("___")[-1]


def _scalar_fields(mapping: Any) -> list[dict]:
    """Flat name/value pairs, bounded. Nested navigation properties are skipped
    rather than stringified — a dumped `to_Item` envelope is not a field value."""
    if not isinstance(mapping, dict):
        return []
    fields = []
    for name, value in mapping.items():
        if isinstance(value, (dict, list)):
            continue
        fields.append({"name": str(name), "value": "" if value is None else str(value)})
        if len(fields) >= MAX_FIELDS:
            break
    return fields


def _maybe_json(value: Any) -> Any:
    """Parse a JSON-string argument, passing anything else through untouched.

    Some tool_specs declare an object-shaped argument as a string. Unparseable text
    is returned as-is so the caller decides what to do with it.
    """
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return value


def _record_from_result(text: str) -> dict | None:
    """First business record out of an OData response.

    Two envelopes, both three hops deep: OData v2 classic (`d` → `results` → [0])
    and the SAP MCP server's own wrapper (`result` → `data` → [0]), whose sibling
    `success`/`message`/`metadata` keys are transport, not SAP fields.
    """
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return None
    for _ in range(3):
        if isinstance(payload, dict) and "d" in payload:
            payload = payload["d"]
        elif isinstance(payload, dict) and "results" in payload:
            payload = payload["results"]
        elif isinstance(payload, dict) and "result" in payload:
            payload = payload["result"]
        elif isinstance(payload, dict) and "data" in payload:
            payload = payload["data"]
        elif isinstance(payload, list):
            payload = payload[0] if payload else None
        else:
            break
    return payload if isinstance(payload, dict) else None


def _proposed_write(proposal: Any) -> dict | None:
    """Narrow a model-declared write to the schema's shape, or drop it.

    Unlike everything else here this arrives from the model, so nothing is
    assumed: a non-dict, a missing op, or a field list with no usable entry all
    yield None rather than an empty object the console would render as a diff.
    """
    if not isinstance(proposal, dict):
        return None
    op = proposal.get("op")
    if op not in _OP_BY_TOOL.values():
        return None
    fields = []
    for field in proposal.get("fields") or []:
        if not isinstance(field, dict):
            continue
        name, proposed = field.get("name"), field.get("proposed")
        if not isinstance(name, str) or not name:
            continue
        if isinstance(proposed, (dict, list)):
            continue
        entry = {"name": name, "proposed": "" if proposed is None else str(proposed)}
        current = field.get("current")
        if current is not None and not isinstance(current, (dict, list)):
            entry["current"] = str(current)
        fields.append(entry)
        if len(fields) >= MAX_FIELDS:
            break
    if not fields:
        return None
    narrowed: dict = {"op": op, "fields": fields}
    for key in ("service", "entity", "key"):
        value = proposal.get(key)
        if isinstance(value, str) and value:
            narrowed[key] = value
    return narrowed


def _key_from(*candidates: Any) -> str:
    """Compact key: quoted filter values or identifier/parameter values, joined."""
    for candidate in candidates:
        if isinstance(candidate, dict):
            parts = [
                str(v) for v in candidate.values() if not isinstance(v, (dict, list))
            ]
            if parts:
                return "/".join(parts)
        elif isinstance(candidate, str) and candidate:
            quoted = _QUOTED_RE.findall(candidate)
            if quoted:
                return "/".join(quoted)
    return ""


def _source(service: Any, entity: Any, key: str) -> dict:
    source = {}
    if isinstance(service, str) and service:
        source["service"] = service
    if isinstance(entity, str) and entity:
        source["entity"] = entity
    if key:
        source["key"] = key
    return source


def _authz(
    tool_key: str, status: str, text: str, mode: str, via_gateway: bool
) -> dict | None:
    """The three authorization facts we can actually state. The matched Cedar
    policy id is not obtainable from the Gateway, so it is not claimed."""
    if tool_key in LOCAL_TOOLS:
        return None
    authz = {
        "mode": mode if mode in ("LOG_ONLY", "ENFORCE") else "LOG_ONLY",
        "via_gateway": bool(via_gateway),
    }
    if status == "success":
        authz["outcome"] = "permitted"
    elif _AUTHZ_DENIED_RE.search(text or ""):
        authz["outcome"] = "rejected"
    # else: the call failed for a non-authorization reason. The segment's own
    # status: "error" reports the failure; asserting "rejected" here would render
    # a timeout as a policy denial.
    return authz


def extract_evidence(
    tool_name: str,
    tool_input: Any,
    result: dict | None,
    *,
    at: str,
    mode: str = "LOG_ONLY",
    via_gateway: bool = True,
    sop_baseline: str = "",
) -> dict:
    """Build the evidence dict for one completed tool call.

    Args:
        tool_name: ToolUse["name"], with or without the `target___` prefix.
        tool_input: ToolUse["input"] — a real dict. This is why extraction lives
            in an AfterToolCallEvent hook and not in segments.py, which would
            have to re-parse tool_input from concatenated AG-UI delta strings.
        result: the ToolResult dict, or None when the tool raised.
        at: ISO timestamp of the call.
        mode: CEDAR_ENFORCEMENT_MODE — LOG_ONLY or ENFORCE.
        via_gateway: False on the direct-MCP (OBO) topology, which bypasses our
            Gateway entirely and so traverses no policy evaluation.
        sop_baseline: every SOP text the run has been given so far. Empty means
            no citation is graded, not that one failed.

    Returns:
        An evidence dict. `kind` is always present; every other key is optional,
        so an unknown tool renders as an unattributed step rather than crashing.
    """
    tool_key = _tool_key(tool_name)
    args = tool_input if isinstance(tool_input, dict) else {}
    status = (result or {}).get("status") or "error"
    text = result_text(result)

    kind = _KIND_BY_TOOL.get(tool_key, "computation")
    evidence: dict = {"kind": kind, "at": at}

    if kind == "sap_read":
        source = _source(
            args.get("service_name"),
            args.get("entity_set"),
            _key_from(args.get("filter"), args.get("identifier_fields")),
        )
        fields = _scalar_fields(_record_from_result(text))
    elif kind == "sap_write":
        evidence["op"] = _OP_BY_TOOL[tool_key]
        if evidence["op"] == "function_import":
            # Post/Release change no field — they move a document's lifecycle, so
            # the function name is the entity worth recording.
            source = _source(
                args.get("service_name"),
                args.get("function_name"),
                _key_from(args.get("parameters")),
            )
            fields = _scalar_fields(args.get("parameters"))
        else:
            source = _source(
                args.get("service_name"),
                args.get("entity_set"),
                _key_from(args.get("identifier_fields")),
            )
            fields = _scalar_fields(args.get("payload"))
    elif kind == "sop_lookup":
        source = {}
        fields = []
        clauses = clauses_in(text)
        if clauses:
            evidence["clauses_retrieved"] = clauses
    elif kind == "case_update":
        source = _source(None, None, str(args.get("case_id") or ""))
        # tool_spec declares `updates` as a JSON *string*, so the dict the tests fed
        # never arrives in production and every real call recorded zero fields.
        updates = _maybe_json(args.get("updates"))
        fields = _scalar_fields(updates)
        # Parse first: in the serialised form the note's quote marks arrive
        # backslash-escaped, and `\"` does not open a quoted span.
        citation = verify_citation(_prose_in(updates), sop_baseline)
        if citation:
            evidence["citation"] = citation
    elif kind == "notification":
        source = {}
        recipient = args.get("recipient") or args.get("assigned_to")
        fields = (
            [{"name": "recipient", "value": str(recipient)}]
            if isinstance(recipient, str) and recipient
            else []
        )
        # The outbound message itself. _platform_prompt tells the agent to cite the
        # SOP sentence it acted on here, so dropping these dropped the citation
        # with them. Verification reads the full value; only the preview is stored.
        prose = []
        for name in _NOTIFICATION_PROSE:
            value = args.get(name)
            if isinstance(value, str) and value.strip():
                prose.append(value)
                fields.append({"name": name, "value": value[:PROSE_MAX_CHARS]})
        citation = verify_citation("\n".join(prose), sop_baseline)
        if citation:
            evidence["citation"] = citation
        # The one model-supplied key in the model — everything else here is a
        # function of the tool call. The console verifies each `current` against
        # the run's own reads rather than trusting it.
        proposal = _proposed_write(args.get("proposed_write"))
        if proposal:
            evidence["proposed_write"] = proposal
    else:  # computation — also the unknown-tool fallthrough, deliberately sourceless
        source = {}
        fields = _scalar_fields(args)
        if text:
            fields = (fields + [{"name": "result", "value": text[:120]}])[:MAX_FIELDS]

    if source:
        evidence["source"] = source
    if fields:
        evidence["fields"] = fields

    authz = _authz(tool_key, status, text, mode, via_gateway)
    if authz:
        evidence["authz"] = authz

    return evidence


def _truncate_utf8(value: str, max_bytes: int) -> tuple[str, bool]:
    """Cut to a byte budget on a character boundary."""
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value, False
    return encoded[:max_bytes].decode("utf-8", errors="ignore"), True


def truncate_segment(segment: dict) -> dict:
    """Apply the preview budgets in place and mark the evidence when either bites.

    Runs after extract_evidence, so the structured facts are already recorded and
    the raw blob is only a preview by the time it is cut.
    """
    if not isinstance(segment, dict):
        return segment
    hit = False
    for key, budget in (
        ("tool_result", TOOL_RESULT_MAX_BYTES),
        ("tool_input", TOOL_INPUT_MAX_BYTES),
    ):
        value = segment.get(key)
        if isinstance(value, str):
            segment[key], cut = _truncate_utf8(value, budget)
            hit = hit or cut
    if hit and isinstance(segment.get("evidence"), dict):
        segment["evidence"]["truncated"] = True
    return segment


def merge_evidence(segments: list | None, evidence_by_id: dict | None) -> list:
    """Attach hook-collected evidence to stream-folded segments, then truncate.

    The join key is `tool_call_id`, which segments.py already records from
    TOOL_CALL_START. A segment the hook never saw — a run cancelled mid-call —
    keeps today's shape, which is exactly the pre-migration render path.
    """
    segments = segments or []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        collected = (evidence_by_id or {}).get(segment.get("tool_call_id"))
        if collected:
            segment["evidence"] = collected["evidence"]
            segment["status"] = collected["status"]
        truncate_segment(segment)
    return segments


def cap_traces(traces: list | None, max_traces: int = MAX_TRACES) -> tuple[list, int]:
    """Keep the newest `max_traces`, reporting how many were dropped.

    list_append has no drop-oldest form, so the caller slices client-side and
    writes the kept list back. Returning the count lets the UI state that history
    was thinned rather than thinning it silently.
    """
    if not traces:
        return [], 0
    dropped = max(0, len(traces) - max_traces)
    return (traces[dropped:], dropped) if dropped else (traces, 0)
