# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Drift guard: the cases table is keyed on ``case_id`` alone, in both IaC backends.

The key schema is the one thing the ``case_key`` codec cannot enforce at runtime — a
mismatch between the codec's key shape and the deployed table surfaces only as a
``ValidationException`` on every read and write. So it is asserted statically here,
against the CDK and Terraform sources and against the codec itself.

Note also *why* it is a single key: nothing queries the table by document_number, so
the previous composite key bought only a per-document Query no caller issues. If that
pattern ever appears it belongs in a GSI (PK document_number, SK item_id), which is a
pure addition — reintroducing a table sort key would be another replacement.
"""

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "lambdas" / "layers" / "shared_types"))

from case_key import to_case_key  # noqa: E402

_CDK = (_REPO_ROOT / "cdk" / "lib" / "backend-stack.ts").read_text()
_TERRAFORM = (
    _REPO_ROOT / "terraform" / "modules" / "backend" / "sap_data.tf"
).read_text()


def _cdk_cases_table() -> str:
    """The CDK CasesTable construct, including its index declarations.

    Bounded by the next table declaration rather than a character count, so a table
    added nearby cannot silently shrink or stretch what this file is asserting over.
    That also makes it a layout constraint: the cases table's GSIs must sit with it.
    """
    start = _CDK.find('new dynamodb.Table(this, "CasesTable"')
    assert start != -1, "could not locate the CasesTable construct in backend-stack.ts"
    end = _CDK.find("new dynamodb.Table(this,", start + 1)
    return _CDK[start : end if end != -1 else len(_CDK)]


def _cdk_cases_key_schema() -> str:
    """Only the table's own key declaration — indexes declare their own sort keys."""
    table = _cdk_cases_table()
    end = table.find("addGlobalSecondaryIndex")
    assert end != -1, "could not locate the cases table indexes"
    return table[:end]


def _terraform_cases_table() -> str:
    """The body of the Terraform aws_dynamodb_table.cases resource."""
    start = _TERRAFORM.find('resource "aws_dynamodb_table" "cases"')
    assert start != -1, "could not locate aws_dynamodb_table.cases in sap_data.tf"
    end = _TERRAFORM.find("\nresource ", start + 1)
    return _TERRAFORM[start : end if end != -1 else len(_TERRAFORM)]


def _terraform_cases_key_schema() -> str:
    """Only the table's own key declaration, not the GSI blocks."""
    table = _terraform_cases_table()
    end = table.find("global_secondary_index")
    assert end != -1, "could not locate the cases table indexes"
    return table[:end]


def test_the_codec_produces_a_single_attribute_key():
    key = to_case_key("5100001976-2026")
    assert key == {"case_id": "5100001976-2026"}, (
        "to_case_key must produce exactly the deployed key schema"
    )


def test_cdk_keys_the_cases_table_on_case_id_only():
    schema = _cdk_cases_key_schema()
    assert re.search(r'partitionKey:\s*\{\s*name:\s*"case_id"', schema), (
        "the CDK cases table must partition on case_id"
    )
    assert "sortKey" not in schema, (
        "the cases table must have no sort key — a composite key reintroduces the "
        "two-representations problem the case_key codec exists to remove"
    )


def test_terraform_keys_the_cases_table_on_case_id_only():
    schema = _terraform_cases_key_schema()
    assert re.search(r'hash_key\s*=\s*"case_id"', schema), (
        "the Terraform cases table must partition on case_id"
    )
    assert not re.search(r"^\s*range_key\s*=", schema, re.MULTILINE), (
        "the cases table must have no range key in Terraform either"
    )


def test_the_status_and_domain_indexes_survive_the_single_key():
    """The GSIs are keyed on their own attributes, so the key change is invisible."""
    for source, name in ((_cdk_cases_table(), "CDK"), (_terraform_cases_table(), "TF")):
        assert "status-index" in source, f"{name} lost the status index"
        assert "domain-status-index" in source, f"{name} lost the domain-status index"
