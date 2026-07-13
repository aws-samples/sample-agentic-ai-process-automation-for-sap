# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared Secrets Manager access for notification adapters."""

import json
import os

import boto3

secrets = boto3.client("secretsmanager")
_creds = None


def get_creds() -> dict:
    """Load and cache the notification credentials JSON from Secrets Manager."""
    global _creds
    if _creds is None:
        secret = secrets.get_secret_value(SecretId=os.environ["NOTIFICATION_SECRET"])
        _creds = json.loads(secret["SecretString"])
    return _creds
