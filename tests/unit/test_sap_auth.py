# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the shared sap_auth Lambda layer.

The layer provides only service-account (machine-identity) basic auth for the
OData poller plus error sanitization; SAP writes go through the external MCP
server instead.
"""

import base64
import importlib
import json
import os
import sys
from unittest.mock import patch

import pytest

# Make the sap_auth layer importable without installing it as a package.
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__), "..", "..", "lambdas", "layers", "sap_auth"
    ),
)

SAP_CREDS = {
    "base_url": "https://sap.example.com",
    "username": "SVC_AGENT",
    "password": "s3cret",
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Reset module-level caches and set required env vars."""
    monkeypatch.setenv("STACK_NAME_BASE", "test-stack")

    # Force reimport to reset module-level caches
    import sap_auth

    sap_auth._sap_creds = None
    importlib.reload(sap_auth)
    yield


@pytest.fixture
def mock_aws():
    """Mock SSM + Secrets Manager for credential fetching."""
    with patch("sap_auth._ssm") as ssm, patch("sap_auth._secretsmanager") as sm:
        ssm.get_parameter.return_value = {
            "Parameter": {"Value": "arn:aws:secretsmanager:us-east-1:123:secret:test"}
        }
        sm.get_secret_value.return_value = {"SecretString": json.dumps(SAP_CREDS)}
        yield {"ssm": ssm, "sm": sm}


def _b64_auth(user: str, pw: str) -> str:
    return f"Basic {base64.b64encode(f'{user}:{pw}'.encode()).decode()}"


class TestServiceAccount:
    def test_returns_basic_auth(self, mock_aws):
        import sap_auth

        sap_auth._sap_creds = None

        session, base_url = sap_auth.get_sap_session()

        assert base_url == "https://sap.example.com"
        assert session.headers["Authorization"] == _b64_auth("SVC_AGENT", "s3cret")
        assert session.headers["Accept"] == "application/json"
        assert session.cert is None

    def test_caches_credentials(self, mock_aws):
        import sap_auth

        sap_auth._sap_creds = None

        sap_auth.get_sap_session()
        sap_auth.get_sap_session()

        # Only one call to Secrets Manager despite two get_sap_session calls
        mock_aws["sm"].get_secret_value.assert_called_once()


class TestNormalizeBaseUrl:
    """Consumers append /sap/opu/odata/sap themselves; base_url must be bare."""

    HOST = "https://sap.example.com"

    @pytest.mark.parametrize(
        "raw",
        [
            "https://sap.example.com",
            "https://sap.example.com/",
            "https://sap.example.com/sap/opu/odata/sap/",
            "https://sap.example.com/sap/opu/odata/sap",
            "  https://sap.example.com/sap/opu/odata/sap/  ",
            "https://sap.example.com/SAP/OPU/ODATA/SAP/",
        ],
    )
    def test_strips_odata_root(self, raw):
        import sap_auth

        assert sap_auth.normalize_base_url(raw) == self.HOST

    def test_preserves_port_and_path_prefix(self):
        import sap_auth

        assert (
            sap_auth.normalize_base_url(
                "https://sap.example.com:44300/sap/opu/odata/sap/"
            )
            == "https://sap.example.com:44300"
        )

    def test_leaves_unrelated_path_alone(self):
        import sap_auth

        # Only the OData root is special — an unrelated suffix must survive.
        assert (
            sap_auth.normalize_base_url("https://sap.example.com/gateway")
            == "https://sap.example.com/gateway"
        )

    def test_applied_to_secret_value(self, mock_aws):
        """The doubled-path bug: an OData-root secret must still yield a bare host."""
        import sap_auth

        sap_auth._sap_creds = None
        mock_aws["sm"].get_secret_value.return_value = {
            "SecretString": json.dumps(
                {**SAP_CREDS, "base_url": f"{self.HOST}/sap/opu/odata/sap/"}
            )
        }

        _, base_url = sap_auth.get_sap_session()

        assert base_url == self.HOST
        # The poller's exact join must not double the service root.
        url = f"{base_url}/sap/opu/odata/sap/API_X/E"
        assert url == f"{self.HOST}/sap/opu/odata/sap/API_X/E"


class TestSanitizeError:
    def test_strips_password(self):
        import sap_auth

        assert "s3cret" not in sap_auth.sanitize_error("password=s3cret failed")

    def test_strips_basic_auth(self):
        import sap_auth

        result = sap_auth.sanitize_error("Authorization: Basic dXNlcjpwYXNz")
        assert "dXNlcjpwYXNz" not in result

    def test_empty_returns_default(self):
        import sap_auth

        assert sap_auth.sanitize_error("") == "An error occurred"
