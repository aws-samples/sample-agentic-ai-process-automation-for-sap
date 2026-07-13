<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Tests

Automated pytest suite for the ERP Agent platform. Fast, hermetic unit tests
that exercise the security-sensitive Lambda code paths without touching AWS.

## Running

```bash
make test            # run the whole suite
python -m pytest tests/ -v
python -m pytest tests/unit/test_sap_auth.py -v   # a single module
```

Configuration lives in `pyproject.toml` under `[tool.pytest.ini_options]`
(`testpaths = ["tests"]`, plus the `unit` / `integration` markers).

## Layout

```
tests/
├── conftest.py     # puts agentcore/agent on sys.path
└── unit/           # hermetic unit tests (no AWS, no network)
    ├── test_content_filter.py    # prompt-injection fencing / sanitization
    ├── test_sap_auth.py          # SAP service-account basic auth + error sanitization
    └── test_webhook_signature.py # webhook HMAC signature verification
```

## Notes

- **Unit tests** import Lambda modules directly and mock external dependencies,
  so they run anywhere with no credentials.
- **Manual / operational** verification scripts (deployed-stack smoke tests that
  prompt for Cognito credentials) live in the top-level `test-scripts/`
  directory, not here.
