# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Skills with a pinned `sap_service` in config.json must get that service/entity
info injected into the prompt (so the agent skips find_sap_services discovery).
Skills without it must be left untouched (no stray {SAP_SERVICE_INFO} placeholder).
"""

from pathlib import Path

import pytest
from utils import skill_router as sr

SKILLS_ROOT = Path(__file__).resolve().parent.parent.parent / "skills"


def _resolve(process_type, monkeypatch, demo_enabled="false"):
    sr._skills_index = None
    monkeypatch.setattr(sr, "_skills_dir", lambda: SKILLS_ROOT)
    monkeypatch.setenv("DEMO_ENABLED", demo_enabled)
    return sr.resolve_skill(process_type)


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
