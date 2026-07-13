# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Validate domain polling configs against the cases JSON schema.

Ensures the poller configs stay in sync with the single source of truth
(types/cases.schema.json). Run via: make generate-types (or directly).

Checks:
  1. domain value is in Domain enum
  2. field_map keys are valid schema properties
  3. No unknown top-level keys in the config (catches typos)
"""

import glob
import json
import os
import sys

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "../../types/cases.schema.json")
DOMAINS_DIR = os.path.join(
    os.path.dirname(__file__), "../../lambdas/odata_poller/domains"
)

VALID_CONFIG_KEYS = {
    "domain",
    "label",
    "service",
    "entity",
    "filter",
    "expand",
    "select",
    "iterate",
    "skip_when",
    "process_type",
    "title",
    "field_map",
}


def validate():
    with open(SCHEMA_PATH) as f:
        schema = json.load(f)

    valid_domains = set(schema["definitions"]["Domain"]["enum"])
    valid_fields = set(schema["properties"].keys())

    errors = []

    for path in sorted(glob.glob(os.path.join(DOMAINS_DIR, "*.json"))):
        name = os.path.basename(path)
        with open(path) as f:
            cfg = json.load(f)

        # 1. Domain value
        if cfg.get("domain") not in valid_domains:
            errors.append(
                f"{name}: domain '{cfg.get('domain')}' not in schema Domain enum {sorted(valid_domains)}"
            )

        # 2. Field map keys
        for key in cfg.get("field_map", {}):
            if key not in valid_fields:
                errors.append(f"{name}: field_map key '{key}' not in schema properties")

        # 3. Unknown top-level keys
        unknown = set(cfg.keys()) - VALID_CONFIG_KEYS
        if unknown:
            errors.append(f"{name}: unknown config keys {sorted(unknown)}")

    if errors:
        print("❌ Domain config validation failed:", file=sys.stderr)
        for e in errors:
            print(f"   {e}", file=sys.stderr)
        sys.exit(1)

    configs = list(glob.glob(os.path.join(DOMAINS_DIR, "*.json")))
    print(f"✅ Validated {len(configs)} domain configs against schema")


if __name__ == "__main__":
    validate()
