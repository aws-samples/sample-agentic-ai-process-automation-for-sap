# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# This is sample code. Not for use in production.
# See NOTICE and LICENSE for more information.
"""
SSM Parameter Store utilities for agent patterns.

Shared helper for fetching config values (e.g. Gateway URLs) set during deployment.
"""

import logging
import os

import boto3

logger = logging.getLogger(__name__)


def get_ssm_parameter(parameter_name: str) -> str:
    """
    Fetch a parameter value from AWS SSM Parameter Store.

    Args:
        parameter_name (str): The full SSM parameter name/path
            (e.g. '/my-stack/gateway_url').

    Returns:
        str: The parameter value.

    Raises:
        ValueError: If the parameter is not found or cannot be retrieved.
    """
    region = os.environ.get(
        "AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    )
    ssm = boto3.client("ssm", region_name=region)
    try:
        response = ssm.get_parameter(Name=parameter_name)
        return response["Parameter"]["Value"]
    except ssm.exceptions.ParameterNotFound:
        raise ValueError(f"SSM parameter not found: {parameter_name}")
    except Exception as e:
        raise ValueError(f"Failed to retrieve SSM parameter {parameter_name}: {e}")
