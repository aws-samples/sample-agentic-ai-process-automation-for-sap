# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# This is sample code. Not for use in production.
# See NOTICE and LICENSE for more information.
"""
Shared SAP machine-identity auth + error handling for the OData poller.

The OData poller is the only component that calls SAP directly (a scheduled
Lambda that cannot reach the Gateway/MCP tools). All interactive agent SAP
access goes through the external AWS-for-SAP MCP server instead.

Provides:
  - get_sap_credentials()  — cached Secrets Manager fetch
  - get_sap_session()      — requests.Session with service-account basic auth,
                             ready for GET (the poller's only verb)
  - sanitize_error()       — strip credentials from error messages
"""

import base64
import json
import logging
import os
import re

import boto3
import requests

logger = logging.getLogger(__name__)

_ssm = boto3.client("ssm")
_secretsmanager = boto3.client("secretsmanager")

_sap_creds: tuple[str, str, str] | None = None

# Callers append the OData service root themselves, so a base_url carrying it
# would yield a doubled path. config.yaml's sap.base_url is conventionally
# written in the OData-root form, so accept either and strip it here.
_ODATA_ROOT_RE = re.compile(r"/sap/opu/odata/sap/?$", re.IGNORECASE)


def normalize_base_url(url: str) -> str:
    """Return `url` reduced to the bare host root (no trailing OData path)."""
    return _ODATA_ROOT_RE.sub("", url.strip()).rstrip("/")


def get_sap_credentials() -> tuple[str, str, str]:
    """Return cached (base_url, username, password) from Secrets Manager."""
    global _sap_creds
    if _sap_creds is None:
        stack = os.environ["STACK_NAME_BASE"]
        arn = _ssm.get_parameter(Name=f"/{stack}/secrets/sap-credentials-arn")[
            "Parameter"
        ]["Value"]
        secret = json.loads(
            _secretsmanager.get_secret_value(SecretId=arn)["SecretString"]
        )
        _sap_creds = (
            normalize_base_url(secret["base_url"]),
            secret["username"],
            secret["password"],
        )
    return _sap_creds


_CRED_RE = re.compile(
    r"(password|token|key|secret|credential|authorization)[\s=:]+[^\s&,\)]+",
    re.IGNORECASE,
)
_BASIC_RE = re.compile(r"Basic\s+[A-Za-z0-9+/=]+")


def sanitize_error(msg: str) -> str:
    """Strip credentials/tokens from error messages."""
    if not msg:
        return "An error occurred"
    s = _BASIC_RE.sub("Basic ***", msg)
    return _CRED_RE.sub(r"\1=***", s)


def get_sap_session() -> tuple[requests.Session, str]:
    """
    Return a requests.Session with service-account basic auth pre-configured.

    Used by the OData poller for system-initiated GET polling — there is no
    user identity in this flow.

    Returns:
        (session, base_url) — session has Accept: application/json + basic auth.
    """
    base_url, username, password = get_sap_credentials()

    session = requests.Session()
    session.verify = True
    b64 = base64.b64encode(f"{username}:{password}".encode()).decode()
    session.headers.update(
        {
            "Accept": "application/json",
            "Authorization": f"Basic {b64}",
        }
    )
    return session, base_url
