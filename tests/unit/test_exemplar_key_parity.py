# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""
The exemplar S3 key is written by lambdas/exemplar_builder and read by the agent's
skill_router. They drifted — the writer keyed on process_type, the reader on
skill_id — and `_fetch_exemplars` swallows a missing key as "exemplars are
optional", so the continual-learning loop was dead with no error anywhere. Neither
side can import the other (the agent container does not mount the shared_types
layer, and the Lambda asset is one file), so the only thing holding the two copies
together is this test.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SKILLS_DIR = _REPO_ROOT / "skills"


@pytest.fixture
def builder(monkeypatch):
    """exemplar_builder's index module, loaded under a name that cannot collide
    with the other lambdas/*/index.py modules other tests import."""
    monkeypatch.setenv("CASES_TABLE", "test-cases")
    monkeypatch.setenv("EXEMPLAR_BUCKET", "test-exemplars")
    monkeypatch.delenv("PROCESS_TYPE_SKILL_MAP", raising=False)

    path = _REPO_ROOT / "lambdas" / "exemplar_builder" / "index.py"
    spec = importlib.util.spec_from_file_location("exemplar_builder_index", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(spec.name, None)


def _skill_process_types() -> list[tuple[str, str]]:
    return sorted(
        (json.loads(cfg.read_text(encoding="utf-8"))["skill_id"], process_type)
        for cfg in _SKILLS_DIR.glob("*/config.json")
        for process_type in json.loads(cfg.read_text(encoding="utf-8")).get(
            "process_type_to_sop", {}
        )
    )


def test_the_corpus_declares_process_types_to_check():
    # A glob that matches nothing would make the parametrized test vacuous.
    assert _skill_process_types()


@pytest.mark.parametrize(
    ("skill_id", "process_type"), _skill_process_types(), ids=lambda v: v
)
def test_writer_and_reader_agree_on_the_exemplar_key(builder, skill_id, process_type):
    from utils import skill_router

    written = builder.exemplar_s3_key(process_type)
    read = skill_router.exemplar_s3_key(skill_id, process_type)

    assert written == read, (
        f"exemplar_builder writes {written} but skill_router reads {read} — "
        f"_fetch_exemplars swallows the 404, so this drift is invisible at runtime"
    )


def test_exemplars_are_read_and_written_to_their_own_bucket():
    """The SOPs KB ingests the whole SOP bucket, and `inclusionPrefixes` holds at
    most one entry — so no in-bucket prefix can keep LLM-condensed traces out of
    the vector index. The bucket boundary is what does it; assert both sides use it.
    """
    source = (_REPO_ROOT / "lambdas" / "exemplar_builder" / "index.py").read_text(
        encoding="utf-8"
    )
    router_source = (
        _REPO_ROOT / "agentcore" / "agent" / "utils" / "skill_router.py"
    ).read_text(encoding="utf-8")

    assert 'os.environ["EXEMPLAR_BUCKET"]' in source
    assert 'os.environ.get("EXEMPLAR_BUCKET")' in router_source
    # The writer must not fall back to the indexed bucket.
    assert "SOP_BUCKET" not in source


def test_an_unowned_process_type_writes_nothing(builder):
    # The reader derives the key from the owning skill's id, so a guessed key
    # could never be read back — writing one would just accrue dead objects.
    assert builder.exemplar_s3_key("not_a_real_process_type") is None


def test_the_deployed_map_is_what_the_writer_keys_on(builder, monkeypatch):
    # skills/ never ships with the Lambda asset, so in deployment the map comes
    # only from PROCESS_TYPE_SKILL_MAP. If the env var were ignored, every
    # deployed write would be skipped while local tests stayed green.
    monkeypatch.setenv(
        "PROCESS_TYPE_SKILL_MAP", json.dumps({"synthetic_type": "synthetic_skill"})
    )
    assert (
        builder.exemplar_s3_key("synthetic_type")
        == "synthetic_skill/synthetic_type_exemplars.md"
    )
    assert builder.exemplar_s3_key("price_variance") is None
