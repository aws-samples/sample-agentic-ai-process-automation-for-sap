# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Skill Router — maps process_type to a domain skill and loads the SOP from S3.

Architecture:
  Case payload contains process_type (e.g. "invoice_matching", "price_variance")
  Router:
    1. Scans skills/*/config.json to find which skill handles that process_type
    2. Loads the skill's base_prompt.txt (domain expertise)
    3. Fetches the matching SOP from S3 (or local fallback for dev)
    4. Injects SOP content into the base prompt at {SOP_CONTENT} placeholder
    5. Returns the assembled system prompt + skill config
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

import boto3
import yaml

logger = logging.getLogger(__name__)


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
    """Load contact directory from config.yaml. Returns {CONTACT_<KEY>: email} map."""
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
            Path(__file__).resolve().parent.parent.parent / "cdk" / "config.yaml",
        ]:
            if candidate.exists():
                raw = yaml.safe_load(candidate.read_text()).get("contacts", {})
                break
        else:
            raw = {}

    _contacts = {f"CONTACT_{k.upper()}": v for k, v in raw.items()}
    logger.info(f"Loaded {len(_contacts)} contact entries")
    return _contacts


def _substitute_contacts(text: str) -> str:
    """Replace {{CONTACT_*}} placeholders with values from the contact directory."""
    contacts = _load_contacts()
    def _replace(m):
        key = m.group(1)
        return contacts.get(key, m.group(0))  # leave unresolved if missing
    return re.sub(r"\{\{(CONTACT_[A-Z_]+)\}\}", _replace, text)


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
    return Path(__file__).resolve().parent.parent.parent / "skills"


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
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)

        skill_id = config["skill_id"]
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
    project_root = Path(__file__).resolve().parent.parent.parent
    for candidate in _sop_key_candidates(sop_key):
        local_path = project_root / "knowledge-base" / "sops" / candidate
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

    # Inject pinned SAP service/entity names, if this skill declares them, so the
    # agent can call odata_read/odata_count directly instead of discovering via
    # find_sap_services/get_metadata on every run.
    sap_service = config.get("sap_service")
    if sap_service:
        entities = "\n".join(f"  - {label}: `{name}`" for label, name in sap_service.get("entities", {}).items())
        sap_service_info = f"Service: `{sap_service['service']}`\nEntities:\n{entities}"
    else:
        sap_service_info = "No pinned service for this skill — use find_sap_services/get_metadata to discover."
    base_prompt = base_prompt.replace("{SAP_SERVICE_INFO}", sap_service_info)

    # Inject SOP into base prompt (wrapped in delimiters for prompt separation)
    system_prompt = base_prompt.replace("{SOP_CONTENT}", f"<sop_document>\n{sop_content}\n</sop_document>")

    # Substitute contact placeholders
    system_prompt = _substitute_contacts(system_prompt)

    # Load exemplars (generated by exemplar_builder Lambda) — optional, silent fail
    exemplar_key = f"{config['skill_id']}/{process_type}_exemplars.md"
    exemplars = _fetch_exemplars(bucket, exemplar_key) if bucket else None
    if exemplars:
        system_prompt += f"\n\n{exemplars}"

    return {
        "skill_id": entry["skill_id"],
        "system_prompt": system_prompt,
        "config": config,
        "sop_loaded": sop_loaded,
        "model_tier": config.get("model_tier", "sonnet"),
        "max_turns": config.get("max_turns", 20),
    }


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
                "process_types": [],
            }
        skills[sid]["process_types"].append(pt)
    return list(skills.values())
