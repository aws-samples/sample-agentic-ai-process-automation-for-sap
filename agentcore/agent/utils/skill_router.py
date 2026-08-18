# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Skill Router — maps process_type to a domain skill and loads the SOP from S3.

Architecture:
  Case payload contains process_type (e.g. "invoice_matching", "price_variance")
  Router:
    1. Scans skills/*/config.json to find which skill handles that process_type
    2. Loads the skill's base_prompt.txt (domain expertise)
    3. Injects the shared platform-mechanics preamble at {PLATFORM_MECHANICS}
    4. Fetches the matching SOP from S3 (or local fallback for dev)
    5. Injects SOP content into the base prompt at {SOP_CONTENT} placeholder
    6. Returns the assembled system prompt + skill config
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

import boto3
import yaml

from . import config_overrides

logger = logging.getLogger(__name__)

# agentcore/agent/utils/skill_router.py → repo root. Only the dev fallbacks below
# use it; in Lambda and the container the packaged absolute paths win.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class SopLoadError(Exception):
    """Raised when a SOP that should exist could not be fetched/parsed (S3 error,
    decode failure). Distinct from a SOP simply not being present, which is an
    expected 'operate on domain expertise' case — see resolve_skill."""

# Cache: loaded once per Lambda cold start
_skills_index: Optional[dict] = None
_contacts: Optional[dict] = None
_s3 = None


def _get_s3():
    global _s3
    if _s3 is None:
        region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
        _s3 = boto3.client("s3", region_name=region)
    return _s3


def _load_contacts() -> dict:
    """Deploy-time contact directory: {CONTACT_<KEY>: email}.

    Operator overrides from the /config table are layered on at substitution time,
    not here — this map is cached for the process lifetime, and an edit must not
    wait for a cold start to take effect."""
    global _contacts
    if _contacts is not None:
        return _contacts

    _contacts = {}

    # Environment override (Lambda receives contacts as JSON env var)
    env_contacts = os.environ.get("CONTACTS_JSON")
    if env_contacts:
        raw = json.loads(env_contacts)
    else:
        # Dev fallback: read from config.yaml
        for candidate in [
            Path("/var/task/config.yaml"),
            Path("/app/config.yaml"),
            _PROJECT_ROOT / "cdk" / "config.yaml",
        ]:
            if candidate.exists():
                raw = yaml.safe_load(candidate.read_text()).get("contacts", {})
                break
        else:
            raw = {}

    _contacts = {f"CONTACT_{k.upper()}": v for k, v in raw.items()}
    logger.info(f"Loaded {len(_contacts)} contact entries")
    return _contacts


def _substitute(text: str, config: dict) -> str:
    """Resolve {{CONTACT_*}} from the contact directory and {{SYMBOL}} from the
    skill's `constants` block, operator overrides winning over both.

    Tunable thresholds live in config.json rather than baked into SOP prose, so a
    finance team can retune one without editing and re-syncing the SOP document.

    The rules themselves live in config_overrides.substitute so the `load_sop`
    Gateway tool applies the identical ones — the prompt and a mid-case SOP
    reload must never state different tolerances.
    """
    return config_overrides.substitute(
        text,
        _load_contacts(),
        config.get("constants") or {},
        config.get("skill_id", ""),
    )


# Every authored SOP carries "Version N.N" in its header block. Anchored to the
# line so a version cited in body prose cannot be read as the document's own.
_SOP_VERSION_RE = re.compile(r"^Version\s+(\S+)", re.MULTILINE)


def sop_version(text: str) -> str:
    """The SOP's own declared version, or "" if it declares none.

    A precedent row cites the authority that drove the outcome, so the string has
    to come from the document the run actually read — not from the SOP as it
    stands whenever the precedent is written. The `NOT NULL` fallback lives at that
    write, so an unversioned SOP reads as absent here rather than as a version.
    """
    match = _SOP_VERSION_RE.search(text or "")
    return match.group(1) if match else ""


# Not a skill directory, so `*/config.json` never picks it up. It ships wherever
# skills/ ships — backend-stack's sharedModules and the agent Dockerfile both copy
# the whole tree — so no packaging change is needed to reach the runtime.
_PLATFORM_PROMPT_NAME = "_platform_prompt.txt"


def _skills_dir() -> Path:
    """Resolve skills/ directory relative to project root."""
    # In Lambda, skills are packaged at /var/task/skills/
    lambda_path = Path("/var/task/skills")
    if lambda_path.exists():
        return lambda_path
    # In Docker container (WORKDIR /app), skills/ is copied alongside agent code
    docker_path = Path("/app/skills")
    if docker_path.exists():
        return docker_path
    # In dev, relative to this file's project root
    return _PROJECT_ROOT / "skills"


def platform_mechanics() -> str:
    """The platform-mechanics preamble shared by every skill.

    Tool names, OData query parameters, write semantics and the ticket protocol are
    properties of the deployment, not of a domain — so they live in one file that
    resolve_skill injects, rather than being copied into each base_prompt.txt. The
    copies drifted: accruals still told the agent to discover services with
    `find_sap_services` on every run, months after finance_ap was pinned to one.
    """
    path = _skills_dir() / _PLATFORM_PROMPT_NAME
    if not path.exists():
        raise ValueError(f"{_PLATFORM_PROMPT_NAME} not found in {path.parent}")
    return path.read_text(encoding="utf-8").strip()


_NO_PINNED_SERVICE = (
    "No pinned service for this skill — use find_sap_services/get_metadata to discover."
)


def _sap_service_info(sap_service: dict | None) -> str:
    """Render a skill's pinned SAP service(s) for {SAP_SERVICE_INFO}.

    Two shapes are accepted. A single `service` with a flat `entities` map, and a
    `services` list of {service, entities} for domains whose entities are spread
    across several OData services — three-way matching reads the invoice, the PO and
    the material document, and each lives in its own service. The single-service
    shape cannot express that: naming one service forces the other entities to be
    listed under it, and the prompt declares the pinned names authoritative, so the
    agent 404s on them and falls back to the discovery this pin exists to avoid.

    An entity's value is either a plain name string, or a dict `{"name": ...,
    "fields": [...]}` when the skill also pins that entity's field set — without
    it the agent invents plausible-but-nonexistent field names from general SAP
    knowledge (e.g. `DocumentReferenceID`, `SupplierName`) and 404s on every one.

    A group's optional `function_imports` map pins Release/Post/Cancel-style
    function imports the same way: name -> {"params": [{"name", "type", "required",
    ...}]}. `get_metadata` has no scoping parameter — a call for one function
    import's params returns the entire service's metadata (every entity, every
    field, every function import), so pinning here lets the agent skip that call
    for anything already listed rather than paying for it on every write.
    """
    if not sap_service:
        return _NO_PINNED_SERVICE

    groups = sap_service.get("services") or [sap_service]
    lines = []
    for group in groups:
        entities = group.get("entities", {})
        lines.append(f"Service: `{group['service']}`")
        lines.append("Entities:")
        for label, entity in entities.items():
            if isinstance(entity, dict):
                lines.append(f"  - {label}: `{entity['name']}`")
                fields = entity.get("fields")
                if fields:
                    lines.append(f"    Fields: {', '.join(fields)}")
            else:
                lines.append(f"  - {label}: `{entity}`")

        function_imports = group.get("function_imports", {})
        if function_imports:
            lines.append("Function Imports:")
            for name, spec in function_imports.items():
                lines.append(f"  - `{name}`:")
                for param in spec.get("params", []):
                    bits = [param["type"], "required" if param.get("required") else "optional"]
                    if "default" in param:
                        bits.append(f"default {param['default']!r}")
                    if "note" in param:
                        bits.append(param["note"])
                    lines.append(f"    - {param['name']} ({', '.join(bits)})")
    return "\n".join(lines)


def _load_skills_index() -> dict:
    """Build index: process_type → (skill_id, sop_s3_key, skill_dir)."""
    global _skills_index
    if _skills_index is not None:
        return _skills_index

    _skills_index = {}
    skills_root = _skills_dir()

    if not skills_root.exists():
        logger.warning(f"Skills directory not found: {skills_root}")
        return _skills_index

    # Demo gate: example_* skills reference demo-only Gateway tools (ticket
    # management). Skip them unless demo is enabled, so a production deployment
    # doesn't surface skills whose tools weren't deployed.
    demo_enabled = os.environ.get("DEMO_ENABLED", "false").lower() == "true"

    for config_path in skills_root.glob("*/config.json"):
        if not demo_enabled and config_path.parent.name.startswith("example_"):
            continue
        # Per-skill isolation: one malformed config.json must disable only its own
        # skill. Unguarded, a parse error here empties the whole index on cold
        # start and every process_type raises "Unknown process_type".
        try:
            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)
            skill_id = config["skill_id"]
        except (OSError, json.JSONDecodeError, KeyError) as e:
            logger.error(f"Skipping unloadable skill config {config_path}: {e}")
            continue

        skill_dir = config_path.parent
        mapping = config.get("process_type_to_sop", {})

        for process_type, sop_key in mapping.items():
            _skills_index[process_type] = {
                "skill_id": skill_id,
                "sop_s3_key": sop_key,
                "skill_dir": str(skill_dir),
                "config": config,
            }

    logger.info(f"Loaded {len(_skills_index)} process_type mappings across {len(set(e['skill_id'] for e in _skills_index.values()))} skills")
    return _skills_index


def _fetch_sop_from_s3(bucket: str, key: str) -> Optional[str]:
    """Fetch SOP document from S3. Tries the exact key first, then falls back
    to alternate extensions (.pdf↔.txt) so config.json doesn't need to match
    the exact file format on disk.

    Returns None if no candidate key exists (expected — caller treats as "no SOP").
    Raises SopLoadError on a genuine fetch/parse failure (S3 down, access denied,
    corrupt PDF) — a failure to load a SOP that should be there must fail the case,
    not silently authorize freelancing."""
    for candidate_key in _sop_key_candidates(key):
        try:
            resp = _get_s3().get_object(Bucket=bucket, Key=candidate_key)
            content = resp["Body"].read()

            if candidate_key.endswith(".pdf"):
                try:
                    import io
                    from PyPDF2 import PdfReader
                    reader = PdfReader(io.BytesIO(content))
                    return "\n".join(page.extract_text() or "" for page in reader.pages)
                except ImportError:
                    logger.warning("PyPDF2 not available — returning raw PDF note")
                    return f"[SOP document at s3://{bucket}/{candidate_key} — PDF parsing requires PyPDF2 or Textract]"
            else:
                return content.decode("utf-8")
        except _get_s3().exceptions.NoSuchKey:
            continue
        except Exception as e:
            logger.error(f"Failed to fetch SOP from s3://{bucket}/{candidate_key}: {e}")
            raise SopLoadError(f"Could not load SOP from s3://{bucket}/{candidate_key}: {e}") from e

    logger.warning(f"SOP not found in s3://{bucket}/ for any candidate of '{key}'")
    return None


def _sop_key_candidates(key: str) -> list[str]:
    """Return the key itself plus alternate extensions to try."""
    candidates = [key]
    stem, ext = os.path.splitext(key)
    alternates = {".pdf": [".txt", ".md"], ".txt": [".pdf", ".md"], ".md": [".txt", ".pdf"]}
    for alt in alternates.get(ext, [".txt", ".pdf", ".md"]):
        candidates.append(stem + alt)
    return candidates


def exemplar_s3_key(skill_id: str, process_type: str) -> str:
    """S3 key for a process_type's machine-generated exemplar file.

    Public because lambdas/exemplar_builder must produce the byte-identical key —
    the two drifted once and _fetch_exemplars swallowed the resulting 404, so the
    continual-learning loop was dead with no error anywhere. Pinned by
    tests/unit/test_exemplar_key_parity.py; the agent container does not mount the
    shared_types layer, so one copy on each side is the best available.

    Read from EXEMPLAR_BUCKET, never the SOP bucket: a Bedrock S3 data source
    ingests a whole bucket, and its `inclusionPrefixes` allowlist holds at most one
    entry, so no prefix inside the SOP bucket can keep these LLM-condensed traces
    out of the vector index. Sharing the bucket would surface them as
    `search_sap_sops` results indistinguishable from an authored SOP.
    """
    return f"{skill_id}/{process_type}_exemplars.md"


def _fetch_exemplars(bucket: Optional[str], key: str) -> Optional[str]:
    """Load exemplar file from S3. Returns None silently if not found."""
    if not bucket:
        return None
    try:
        resp = _get_s3().get_object(Bucket=bucket, Key=key)
        return resp["Body"].read().decode("utf-8")
    except Exception:
        return None  # Exemplars are optional — missing is fine


def _fetch_sop_local(skill_dir: str, sop_key: str) -> Optional[str]:
    """Dev fallback: load SOP from local knowledge-base/sops/ directory."""
    for candidate in _sop_key_candidates(sop_key):
        local_path = _PROJECT_ROOT / "knowledge-base" / "sops" / candidate
        if local_path.exists():
            return local_path.read_text()
    return None


def resolve_skill(process_type: str, sop_bucket: Optional[str] = None) -> dict:
    """
    Resolve a process_type to a fully assembled skill.

    Returns:
        {
            "skill_id": "finance_ap",
            "system_prompt": "You are an expert... {SOP injected}",
            "config": { full config.json },
            "sop_loaded": True/False,
        }

    Raises ValueError if process_type is not mapped to any skill.
    """
    index = _load_skills_index()

    if process_type not in index:
        available = sorted(index.keys())
        raise ValueError(
            f"Unknown process_type '{process_type}'. "
            f"Available: {available}"
        )

    entry = index[process_type]
    skill_dir = entry["skill_dir"]
    config = entry["config"]
    sop_key = entry["sop_s3_key"]

    # Load base prompt
    base_prompt_path = Path(skill_dir) / "base_prompt.txt"
    if not base_prompt_path.exists():
        raise ValueError(f"base_prompt.txt not found in {skill_dir}")
    base_prompt = base_prompt_path.read_text()

    # Shared mechanics first: the preamble itself carries {SAP_SERVICE_INFO}, so it
    # has to be in place before that substitution runs.
    base_prompt = base_prompt.replace("{PLATFORM_MECHANICS}", platform_mechanics())

    # Load SOP: try S3 first, then local fallback
    sop_content = None
    bucket = sop_bucket or os.environ.get("SOP_BUCKET")

    if bucket:
        sop_content = _fetch_sop_from_s3(bucket, sop_key)
    else:
        sop_content = _fetch_sop_local(skill_dir, sop_key)

    if not sop_content:
        sop_content = f"[No SOP loaded for {sop_key} — operating on domain expertise only]"
        sop_loaded = False
    else:
        sop_loaded = True

    # Read off the SOP text, not the assembled prompt: the version has to name the
    # document, not the wrapper.
    version = sop_version(sop_content)

    # Inject pinned SAP service/entity names, if this skill declares them, so the
    # agent can call odata_read/odata_count directly instead of discovering via
    # find_sap_services/get_metadata on every run.
    sap_service_info = _sap_service_info(config.get("sap_service"))
    base_prompt = base_prompt.replace("{SAP_SERVICE_INFO}", sap_service_info)

    # Inject SOP into base prompt (wrapped in delimiters for prompt separation)
    system_prompt = base_prompt.replace("{SOP_CONTENT}", f"<sop_document>\n{sop_content}\n</sop_document>")

    system_prompt = _substitute(system_prompt, config)

    # Load exemplars (generated by exemplar_builder Lambda) — optional, silent fail.
    # Exemplars are the legacy continual-learning path. When agent knowledge is
    # deployed, precedent arrives through the keyed get_precedent tool instead,
    # and appending exemplars here would both duplicate it and break prompt
    # caching by varying the system prompt per invocation.
    if os.environ.get("AGENT_KNOWLEDGE_ENABLED", "false").lower() != "true":
        # Its own bucket, not a prefix in the SOP bucket — see exemplar_s3_key.
        exemplar_bucket = os.environ.get("EXEMPLAR_BUCKET")
        exemplar_key = exemplar_s3_key(config["skill_id"], process_type)
        exemplars = _fetch_exemplars(exemplar_bucket, exemplar_key)
        if exemplars:
            system_prompt += f"\n\n{exemplars}"

    return {
        "skill_id": entry["skill_id"],
        "system_prompt": system_prompt,
        "config": config,
        "sop_loaded": sop_loaded,
        "sop_version": version,
        "model_tier": config.get("model_tier", "sonnet"),
        "max_turns": config.get("max_turns", 15),
    }


def _skill_name(process_type: str) -> str:
    """process_type -> an AgentSkills.io-legal skill name.

    The spec allows lowercase alphanumerics and hyphens only, and `Skill.from_content`
    raises on anything else under strict=True. Our process types use underscores, so
    they are hyphenated here rather than renamed at the source: `process_type` is a
    persisted case field and the key into `process_type_to_sop`, `SOP_INDEX_JSON` and
    the Cedar policies. Inverse is _process_type_from_skill_name."""
    return process_type.replace("_", "-")


def _process_type_from_skill_name(skill_name: str) -> str:
    """Inverse of _skill_name. Round-trips because no process_type contains a hyphen —
    asserted by tests/unit/test_agent_skills_discovery.py."""
    return skill_name.replace("-", "_")


def discovery_skills(sop_bucket: Optional[str] = None) -> list:
    """Build one `Skill` per process_type for the chat path, where the agent has to
    work out which exception it is looking at.

    Returns pre-substituted in-process `Skill` instances, NOT filesystem SKILL.md
    paths. That is deliberate and load-bearing: `AgentSkills` returns
    `skill.instructions` verbatim, with no substitution seam, so a filesystem skill
    would hand the model raw `{{QTY_VARIANCE_PCT}}` / `{{CONTACT_*}}` placeholders and
    silently discard both the config.json constants and the operator overrides from
    the /config table. Tolerances decide whether money moves, so they must be resolved
    before the text is ever offered to the model.

    Instructions are the same assembled prompt `resolve_skill` produces, so the
    queued path (deterministic injection) and the chat path (model-selected) cannot
    disagree about what a SOP says.

    A skill whose SOP cannot be loaded is omitted rather than offered empty: an
    activatable skill with no procedure behind it is worse than an absent one.
    Requires strands>=1.50; returns [] if the plugin is unavailable.
    """
    try:
        from strands.vended_plugins.skills import Skill
    except ImportError:
        logger.warning("strands.vended_plugins.skills unavailable — no discovery skills")
        return []

    skills = []
    for process_type in sorted(_load_skills_index()):
        try:
            resolved = resolve_skill(process_type, sop_bucket=sop_bucket)
        except (SopLoadError, ValueError) as e:
            logger.warning(f"Skipping discovery skill for {process_type}: {e}")
            continue
        if not resolved["sop_loaded"]:
            logger.warning(f"Skipping discovery skill for {process_type}: no SOP loaded")
            continue

        config = resolved["config"]
        skills.append(
            Skill(
                name=_skill_name(process_type),
                description=(
                    f"{config.get('display_name', resolved['skill_id'])} — "
                    f"{process_type.replace('_', ' ')}. "
                    f"Activate once the exception is classified as this type."
                ),
                instructions=resolved["system_prompt"],
                # Advisory in strands 1.50 (documented "not yet enforced"), but it
                # records the same grant `gateway_tools` already declares.
                allowed_tools=config.get("gateway_tools"),
            )
        )

    logger.info(f"Built {len(skills)} discovery skills")
    return skills


def list_skills() -> list[dict]:
    """Return summary of all registered skills and their process types."""
    index = _load_skills_index()
    skills = {}
    for pt, entry in index.items():
        sid = entry["skill_id"]
        if sid not in skills:
            skills[sid] = {
                "skill_id": sid,
                "display_name": entry["config"].get("display_name", sid),
                "description": entry["config"].get("description", ""),
                "process_types": [],
            }
        skills[sid]["process_types"].append(pt)
    return list(skills.values())
