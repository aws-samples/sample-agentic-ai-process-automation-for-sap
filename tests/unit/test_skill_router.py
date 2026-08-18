# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Skills with a pinned `sap_service` in config.json must get that service/entity
info injected into the prompt (so the agent skips find_sap_services discovery).
Skills without it must be left untouched (no stray {SAP_SERVICE_INFO} placeholder).
"""

import json
import re
from pathlib import Path

import pytest
import yaml
from utils import skill_router as sr

SKILLS_ROOT = Path(__file__).resolve().parent.parent.parent / "skills"


def _resolve(process_type, monkeypatch, demo_enabled="false"):
    sr._skills_index = None
    monkeypatch.setattr(sr, "_skills_dir", lambda: SKILLS_ROOT)
    monkeypatch.setenv("DEMO_ENABLED", demo_enabled)
    return sr.resolve_skill(process_type)


# Golden-file assembly: the whole point of the router is that real SOP text and
# real config constants reach the model. The tests below use only symbols that
# actually appear in a shipped SOP, so a broken substitution path fails here
# rather than in a deployment.


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_EXAMPLE_CONFIG = _REPO_ROOT / "cdk" / "config.yaml.example"
_CONTACT_PATTERN = re.compile(r"\{\{(CONTACT_[A-Z_]+)\}\}")


def _example_contact_keys() -> set[str]:
    raw = yaml.safe_load(_EXAMPLE_CONFIG.read_text(encoding="utf-8"))
    return {f"CONTACT_{k.upper()}" for k in (raw.get("contacts") or {})}


def test_assembled_prompt_contains_the_real_sop_and_substituted_constants(monkeypatch):
    contacts = {k: f"{k.lower()}@example.com" for k in _example_contact_keys()}
    monkeypatch.setattr(sr, "_contacts", None)
    monkeypatch.delenv("SOP_BUCKET", raising=False)
    monkeypatch.setenv(
        "CONTACTS_JSON",
        json.dumps({k[len("CONTACT_") :].lower(): v for k, v in contacts.items()}),
    )
    skill = _resolve("quantity_variance", monkeypatch)
    prompt = skill["system_prompt"]

    assert skill["sop_loaded"] is True
    # Verbatim from knowledge-base/sops/finance_ap/quantity_variance.txt.
    assert "QUANTITY VARIANCE — INVOICE EXCEPTION RESOLUTION" in prompt
    assert "<sop_document>" in prompt and "</sop_document>" in prompt

    # constants from skills/finance_ap/config.json land as values, not symbols.
    assert "qty_variance_pct > 5%" in prompt
    assert "qty_variance_units > 10 units" in prompt
    assert "{{QTY_VARIANCE_PCT}}" not in prompt
    assert "{{QTY_VARIANCE_UNITS}}" not in prompt

    assert "contact_ap_team@example.com" in prompt

    # No placeholder of any shape survives assembly.
    assert "{SOP_CONTENT}" not in prompt
    assert not re.search(r"\{\{[A-Z][A-Z0-9_]*\}\}", prompt)


def test_every_contact_the_corpus_cites_is_declared_in_the_example_config():
    # An undeclared {{CONTACT_X}} is left verbatim in the prompt, so the agent is
    # told to notify a literal placeholder. Nothing else catches this.
    corpus = sorted((_REPO_ROOT / "knowledge-base" / "sops").rglob("*.txt")) + sorted(
        (_REPO_ROOT / "skills").rglob("*.txt")
    )
    assert corpus, "no SOP or base_prompt files found — check the glob paths"
    used = set()
    for path in corpus:
        used |= set(_CONTACT_PATTERN.findall(path.read_text(encoding="utf-8")))
    undeclared = sorted(used - _example_contact_keys())
    assert not undeclared, (
        f"{undeclared} are cited by the SOP/prompt corpus but absent from "
        f"cdk/config.yaml.example's `contacts` block, so operators have no way "
        f"to supply them and the placeholder reaches the model verbatim."
    )


def test_every_symbol_a_skills_sops_cite_is_declared_in_its_constants():
    # Same failure mode as the contact test: an undeclared {{SYMBOL}} survives
    # assembly, so the agent is told to compare against a literal placeholder
    # instead of a threshold. Also catches the reverse — a constant nothing
    # reads, which is how AMOUNT_TOLERANCE_USD came to mean two things at once.
    pattern = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")
    checked = 0
    for config_path in sorted(SKILLS_ROOT.glob("*/config.json")):
        config = json.loads(config_path.read_text(encoding="utf-8"))
        declared = set(config.get("constants") or {})

        used = set()
        for sop_key in set((config.get("process_type_to_sop") or {}).values()):
            for candidate in sr._sop_key_candidates(sop_key):
                path = _REPO_ROOT / "knowledge-base" / "sops" / candidate
                if path.exists() and path.suffix == ".txt":
                    used |= set(pattern.findall(path.read_text(encoding="utf-8")))
        # The shared preamble reaches every skill, so a symbol it cites must be
        # declared by every skill — check it against each one, not once.
        for prompt in (
            config_path.parent / "base_prompt.txt",
            SKILLS_ROOT / sr._PLATFORM_PROMPT_NAME,
        ):
            if prompt.exists():
                used |= set(pattern.findall(prompt.read_text(encoding="utf-8")))

        # CONTACT_* comes from cdk config, not `constants` — covered separately.
        used = {s for s in used if not s.startswith("CONTACT_")}

        skill = config_path.parent.name
        assert not (used - declared), (
            f"{skill}'s SOPs cite {sorted(used - declared)}, which its "
            f"config.json `constants` block does not declare"
        )
        assert not (declared - used), (
            f"{skill} declares {sorted(declared - used)} in `constants`, which no "
            f"SOP or base_prompt reads — a threshold nobody can tune"
        )
        checked += 1
    assert checked, "no skill configs found — check the glob path"


# `sop_version` names the authority a run followed. Recorded per run because a
# precedent citing the case must survive the SOP being revised afterwards.


def test_resolved_skill_reports_its_sops_declared_version(monkeypatch):
    # Verbatim from the header of knowledge-base/sops/finance_ap/invoice_matching.txt,
    # the one SOP in the corpus that has been revised.
    assert _resolve("three_way_match", monkeypatch)["sop_version"] == "2.0"


def test_every_sop_in_the_corpus_declares_a_version():
    # An undeclared version writes "unversioned" into a NOT NULL column that exists
    # to make a precedent citation defensible — the row lands but cites nothing.
    corpus = sorted((_REPO_ROOT / "knowledge-base" / "sops").rglob("*.txt"))
    assert corpus, "no SOP files found — check the glob path"
    missing = [
        str(p.relative_to(_REPO_ROOT))
        for p in corpus
        if not sr.sop_version(p.read_text(encoding="utf-8"))
    ]
    assert not missing, f"{missing} declare no `Version N.N` header line"


def test_local_sop_fallback_resolves_from_repo_root():
    # The dev path (no SOP_BUCKET) reads knowledge-base/sops/ relative to
    # _PROJECT_ROOT. An off-by-one in that walk-up silently degrades every local
    # run to "no SOP loaded".
    assert (sr._PROJECT_ROOT / "knowledge-base" / "sops").is_dir()
    assert sr._fetch_sop_local("", "finance_ap/quantity_variance.txt")


def test_malformed_skill_config_disables_only_that_skill(monkeypatch, tmp_path):
    good = tmp_path / "finance_ap"
    good.mkdir()
    (good / "config.json").write_text(
        (SKILLS_ROOT / "finance_ap" / "config.json").read_text()
    )
    broken = tmp_path / "broken_skill"
    broken.mkdir()
    (broken / "config.json").write_text("{ not json")

    sr._skills_index = None
    monkeypatch.setattr(sr, "_skills_dir", lambda: tmp_path)
    monkeypatch.setenv("DEMO_ENABLED", "false")
    assert "quantity_variance" in sr._load_skills_index()


def test_pinned_sap_service_is_injected_and_discovery_not_instructed(monkeypatch):
    skill = _resolve("price_variance", monkeypatch)
    prompt = skill["system_prompt"]

    assert "API_SUPPLIERINVOICE_PROCESS_SRV" in prompt
    assert "A_SupplierInvoice" in prompt
    assert "{SAP_SERVICE_INFO}" not in prompt
    assert "do NOT call `find_sap_services`" in prompt


def test_skill_without_pinned_service_has_no_placeholder_leak(monkeypatch):
    skill = _resolve("po_accrual", monkeypatch, demo_enabled="true")
    assert "{SAP_SERVICE_INFO}" not in skill["system_prompt"]


def test_each_pinned_entity_is_rendered_under_its_own_service(monkeypatch):
    # Three-way matching reads the invoice, the PO and the material document, and
    # each lives in a different OData service. Listing an entity under a service
    # that does not expose it makes the agent 404 on a name the prompt calls
    # authoritative, then rediscover — which is what the pin exists to prevent.
    rendered = sr._sap_service_info(
        {
            "services": [
                {"service": "SVC_A", "entities": {"invoice": "A_SupplierInvoice"}},
                {"service": "SVC_B", "entities": {"po": "A_PurchaseOrder"}},
            ]
        }
    )
    assert "Service: `SVC_A`\nEntities:\n  - invoice: `A_SupplierInvoice`" in rendered
    assert "Service: `SVC_B`\nEntities:\n  - po: `A_PurchaseOrder`" in rendered
    assert rendered.index("A_SupplierInvoice") < rendered.index("Service: `SVC_B`")

    # The single-service shape still renders — accruals and any unmigrated skill.
    assert "Service: `SVC_A`" in sr._sap_service_info(
        {"service": "SVC_A", "entities": {"invoice": "A_SupplierInvoice"}}
    )


def test_finance_ap_pins_no_entity_under_a_service_that_lacks_it(monkeypatch):
    # Guards the specific regression: A_PurchaseOrderItem and
    # A_MaterialDocumentHeader were pinned under the invoice service, which does
    # not expose them.
    prompt = _resolve("invoice_matching", monkeypatch)["system_prompt"]
    block = prompt.split("## SAP SERVICE")[1].split("##")[0]
    po_service = block.index("API_PURCHASEORDER_PROCESS_SRV")
    material_service = block.index("API_MATERIAL_DOCUMENT_SRV")

    assert block.index("A_PurchaseOrderItem") > po_service
    assert block.index("A_MaterialDocumentHeader") > material_service
    assert block.index("A_SupplierInvoice") < po_service


def test_base_prompt_warns_against_postingdate_on_material_document_item(monkeypatch):
    # Guards the specific regression: PostingDate/DocumentDate 404d against
    # A_MaterialDocumentItem in 4 of 5 write-path live traces — the field pin
    # correctly excludes them (they live on A_MaterialDocumentHeader), but the
    # generic "the list is exhaustive" instruction wasn't enough to stop the model
    # reaching for a field name so common elsewhere in the same service. Naming the
    # specific trap directly is the next escalation.
    prompt = _resolve("invoice_matching", monkeypatch)["system_prompt"]
    assert "A_MaterialDocumentItem" in prompt and "A_MaterialDocumentHeader" in prompt
    assert "NOT on `A_MaterialDocumentItem`" in prompt


def test_entity_field_pin_renders_and_rejects_invented_fields(monkeypatch):
    # Guards the specific regression: with no field list pinned, the agent invented
    # plausible-but-nonexistent SAP field names (DocumentReferenceID, SupplierName,
    # PurchaseOrderNetAmount) and 404d hundreds of times across live runs. Pinning
    # each entity's real field list, and telling the agent it's exhaustive, is the
    # same fix already applied to entity names — one level deeper.
    prompt = _resolve("invoice_matching", monkeypatch)["system_prompt"]
    block = prompt.split("## SAP SERVICE")[1].split("##")[0]

    assert "Fields: SupplierInvoice, FiscalYear" in block
    assert "exhaustive for `select`" in prompt
    for invented in ("DocumentReferenceID", "SupplierName", "PurchaseOrderNetAmount"):
        assert invented not in block


def test_sap_service_info_renders_plain_string_entities_without_fields():
    # A skill that hasn't pinned fields yet (or never needs to) must still render —
    # the dict shape is additive, not a replacement for the plain-string shape.
    rendered = sr._sap_service_info(
        {"service": "SVC_A", "entities": {"invoice": "A_SupplierInvoice"}}
    )
    assert rendered == "Service: `SVC_A`\nEntities:\n  - invoice: `A_SupplierInvoice`"


def test_schedule_line_pin_uses_the_live_key_field_names(monkeypatch):
    # Guards the specific regression: the API doc corpus documented this entity's key
    # fields as PurchaseOrder/PurchaseOrderItem (matching the sibling PO entities),
    # and the pin was extracted verbatim from that corpus. Live SAP actually names
    # them PurchasingDocument/PurchasingDocumentItem — a genuine corpus error, not an
    # invented field, so it 404d even with the pin in place. Both the pin and the
    # corpus doc are fixed; this checks the pin only survives with the live names.
    prompt = _resolve("missing_goods_receipt", monkeypatch)["system_prompt"]
    block = prompt.split("## SAP SERVICE")[1].split("##")[0]
    assert "PurchasingDocument" in block and "PurchasingDocumentItem" in block
    assert "PurchaseOrderScheduleLine" in block
    # The old wrong names must not survive as a fragment of the right ones.
    schedule_line_fields = block.split("A_PurchaseOrderScheduleLine`")[1].split("\n")[1]
    assert "PurchaseOrder," not in schedule_line_fields
    assert "PurchaseOrderItem," not in schedule_line_fields


def test_function_import_pin_renders_params_and_skips_metadata_call(monkeypatch):
    # Guards the specific regression: get_metadata has no scoping parameter — a call
    # for one function import's params returns the ENTIRE service's metadata (every
    # entity, every field, every function import). Every write-requiring case called
    # it, roughly doubling cache-write tokens over a read-only case. Pinning the
    # function import's params (mechanically extracted from the API doc corpus, same
    # as the entity/field pins) lets the agent skip that call entirely.
    prompt = _resolve("invoice_matching", monkeypatch)["system_prompt"]
    block = prompt.split("## SAP SERVICE")[1].split("##")[0]

    assert "Function Imports:" in block
    assert "`Release`:" in block
    assert (
        "DiscountDaysHaveToBeShifted (Edm.Boolean, optional, default 'false')" in block
    )
    assert "Do NOT call `get_metadata` first" in prompt
    assert "the single most expensive call available to you" in prompt
    # Guards the specific regression: live traces show the agent inventing a "mode"
    # argument for get_metadata ("rich", then "core" on a later run) — never a real
    # parameter (AWS's own tool reference lists none), silently dropped by the
    # server rather than erroring, so it did nothing but cost tokens.
    assert "takes exactly one parameter, `service_name`" in prompt
    assert "do NOT invent a `mode`" in prompt


def test_sap_service_info_renders_function_imports_for_single_service_shape():
    rendered = sr._sap_service_info(
        {
            "service": "SVC_A",
            "entities": {"invoice": "A_SupplierInvoice"},
            "function_imports": {
                "Release": {
                    "params": [
                        {
                            "name": "SupplierInvoice",
                            "type": "Edm.String",
                            "required": True,
                        },
                        {
                            "name": "Force",
                            "type": "Edm.Boolean",
                            "required": False,
                            "default": "false",
                        },
                    ]
                }
            },
        }
    )
    assert "Function Imports:" in rendered
    assert "  - `Release`:" in rendered
    assert "    - SupplierInvoice (Edm.String, required)" in rendered
    assert "    - Force (Edm.Boolean, optional, default 'false')" in rendered


# The platform mechanics (tool names, OData parameters, write semantics, the ticket
# protocol) were copied into every base_prompt.txt. The copies drifted — accruals
# still instructed find_sap_services discovery long after finance_ap was pinned —
# so they are now injected from one file at assembly time.


@pytest.mark.parametrize("process_type", ["quantity_variance", "po_accrual"])
def test_every_skill_receives_the_shared_platform_mechanics(monkeypatch, process_type):
    prompt = _resolve(process_type, monkeypatch, demo_enabled="true")["system_prompt"]

    assert "{PLATFORM_MECHANICS}" not in prompt
    assert sr.platform_mechanics().splitlines()[0] in prompt
    # Sections that used to exist in one copy only.
    assert "## SOP COMPLIANCE (CRITICAL)" in prompt
    assert "## RESPONSE FORMAT" in prompt
    assert "Pass `select` on every `odata_read`" in prompt
    # Guards the specific regression: the AWS-published SAP MCP server does no OData
    # literal formatting at all — it stringifies whatever the agent sends, verbatim,
    # into the query string. A live Release call needed 6 attempts before it found
    # the right combination (Edm.String quoted AND Edm.Boolean lowercased); a fix
    # covering only the boolean is not sufficient by itself. We can't patch the
    # vendor container, so the agent must pre-format every parameter itself.
    assert "Edm.String" in prompt and "Edm.Boolean" in prompt
    assert 'lowercase string `"true"`/`"false"`' in prompt
    assert "Malformed URI literal syntax" in prompt
    # Guards the specific regression: a live case's Release call correctly failed
    # with "is not blocked" (the invoice was already released) — a live case's Post
    # correctly failed with "has been posted" — but the agent re-read the stale
    # entity and searched API docs before trusting either error message, burning 3
    # turns it didn't need on a case that then hit max_turns.
    assert "no longer applies" in prompt
    assert '"is not blocked"' in prompt and '"has been posted"' in prompt
    assert "Do NOT re-read the" in prompt


def test_no_base_prompt_re_states_the_shared_mechanics():
    # A skill that keeps its own copy is how the drift started: the router injects
    # the shared text either way, so the copy silently wins or contradicts it.
    duplicated = {
        "find_sap_services and get_metadata to discover",
        "## SOP COMPLIANCE",
        "## DATA INTEGRITY",
        "## SAP WRITES",
        "demo_create_ticket",
    }
    offenders = {
        path.parent.name: sorted(s for s in duplicated if s in text)
        for path in sorted(SKILLS_ROOT.glob("*/base_prompt.txt"))
        for text in [path.read_text(encoding="utf-8")]
        if any(s in text for s in duplicated)
    }
    assert not offenders, (
        f"{offenders} restate text that skills/{sr._PLATFORM_PROMPT_NAME} already "
        f"injects into every skill — delete the copy rather than maintaining two"
    )


# A real S3 fetch error must raise, not be injected as SOP text with
# sop_loaded=True — only a genuinely-absent SOP gets the placeholder.


class _Body:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data


class _FakeS3:
    class exceptions:
        class NoSuchKey(Exception):
            pass

    def __init__(self, mode):
        self._mode = mode  # "notfound" | "error" | <content str>

    def get_object(self, Bucket, Key):
        if self._mode == "notfound":
            raise self.exceptions.NoSuchKey("missing")
        if self._mode == "error":
            raise RuntimeError("S3 access denied")
        return {"Body": _Body(self._mode.encode("utf-8"))}


def _use_fake_s3(monkeypatch, mode):
    monkeypatch.setattr(sr, "_s3", _FakeS3(mode))


def test_fetch_sop_returns_none_when_absent(monkeypatch):
    _use_fake_s3(monkeypatch, "notfound")
    assert sr._fetch_sop_from_s3("bucket", "finance_ap/missing.txt") is None


def test_fetch_sop_raises_on_real_error(monkeypatch):
    _use_fake_s3(monkeypatch, "error")
    with pytest.raises(sr.SopLoadError):
        sr._fetch_sop_from_s3("bucket", "finance_ap/x.txt")


def test_resolve_skill_raises_on_sop_fetch_error(monkeypatch):
    sr._skills_index = None
    monkeypatch.setattr(sr, "_skills_dir", lambda: SKILLS_ROOT)
    monkeypatch.setenv("DEMO_ENABLED", "false")
    _use_fake_s3(monkeypatch, "error")
    with pytest.raises(sr.SopLoadError):
        sr.resolve_skill("price_variance", sop_bucket="test-bucket")


def test_resolve_skill_absent_sop_is_placeholder_not_loaded(monkeypatch):
    sr._skills_index = None
    monkeypatch.setattr(sr, "_skills_dir", lambda: SKILLS_ROOT)
    monkeypatch.setenv("DEMO_ENABLED", "false")
    _use_fake_s3(monkeypatch, "notfound")
    skill = sr.resolve_skill("price_variance", sop_bucket="test-bucket")
    assert skill["sop_loaded"] is False
    assert "No SOP loaded" in skill["system_prompt"]
    # The placeholder must not be named as the authority a precedent followed.
    assert skill["sop_version"] == ""


# Exemplars are the legacy continual-learning path. With agent knowledge
# deployed, precedent arrives through get_precedent instead — appending
# exemplars would duplicate it and vary the system prompt per invocation,
# breaking prompt caching.


@pytest.mark.parametrize(
    "flag,expect_exemplars", [("false", True), (None, True), ("true", False)]
)
def test_exemplar_injection_is_suppressed_by_agent_knowledge(
    monkeypatch, flag, expect_exemplars
):
    sr._skills_index = None
    monkeypatch.setattr(sr, "_skills_dir", lambda: SKILLS_ROOT)
    monkeypatch.setenv("DEMO_ENABLED", "false")
    if flag is None:
        monkeypatch.delenv("AGENT_KNOWLEDGE_ENABLED", raising=False)
    else:
        monkeypatch.setenv("AGENT_KNOWLEDGE_ENABLED", flag)
    _use_fake_s3(monkeypatch, "notfound")
    monkeypatch.setattr(sr, "_fetch_exemplars", lambda *_: "## EXEMPLAR_MARKER")

    prompt = sr.resolve_skill("price_variance", sop_bucket="test-bucket")[
        "system_prompt"
    ]
    assert ("EXEMPLAR_MARKER" in prompt) is expect_exemplars


# Tunable thresholds live in config.json's `constants` block and are substituted
# into {{SYMBOL}} placeholders at prompt-assembly time (mirrors {{CONTACT_*}}).


def test_substitute_replaces_declared_symbols(monkeypatch):
    monkeypatch.setattr(sr, "_contacts", {})
    config = {"constants": {"TIER_1_DOLLAR": 50000, "STALE_DISPUTE_DAYS": 14}}
    text = "Escalate at {{TIER_1_DOLLAR}} after {{STALE_DISPUTE_DAYS}} days."
    assert sr._substitute(text, config) == "Escalate at 50000 after 14 days."


def test_substitute_leaves_unknown_symbol_untouched(monkeypatch):
    monkeypatch.setattr(sr, "_contacts", {})
    config = {"constants": {"TIER_1_DOLLAR": 50000}}
    text = "Threshold {{TIER_1_DOLLAR}} but {{UNKNOWN_SYMBOL}} stays."
    assert (
        sr._substitute(text, config) == "Threshold 50000 but {{UNKNOWN_SYMBOL}} stays."
    )


def test_a_constants_block_cannot_redefine_a_contact(monkeypatch):
    # The contact directory is the authority for CONTACT_*: a skill config that
    # declared one would otherwise reroute a notification to its own address.
    monkeypatch.setattr(sr, "_contacts", {"CONTACT_AR_ANALYST": "real@example.com"})
    config = {"constants": {"CONTACT_AR_ANALYST": "should-not-win@example.com"}}
    assert sr._substitute("Notify {{CONTACT_AR_ANALYST}}.", config) == (
        "Notify real@example.com."
    )


def test_substitute_noop_without_constants_block(monkeypatch):
    monkeypatch.setattr(sr, "_contacts", {})
    text = "No {{TIER_1_DOLLAR}} here."
    assert sr._substitute(text, {}) == text
