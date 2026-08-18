# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Agent Knowledge schema custom resource.

Applies agent_knowledge DDL on stack Create/Update. The DDL lives in
queries.SCHEMA_DDL — the same module the tool Lambda reads — so schema and
queries cannot drift. Every statement is IF NOT EXISTS, so re-running is safe.

Delete is a no-op: dropping the schema on stack delete would take precedent
history with it, and the cluster's own removal policy already governs teardown.
"""

import logging
import os

import boto3
import queries

logger = logging.getLogger()
logger.setLevel(logging.INFO)

rds_data = boto3.client("rds-data")

CLUSTER_ARN = os.environ["CLUSTER_ARN"]
SECRET_ARN = os.environ["SECRET_ARN"]
DATABASE_NAME = os.environ["DATABASE_NAME"]


def handler(event, context):
    request_type = event.get("RequestType")
    logger.info(f"RequestType={request_type}")

    if request_type == "Delete":
        return {"PhysicalResourceId": "agent-knowledge-schema"}

    for statement in queries.SCHEMA_DDL:
        sql = statement.strip()
        logger.info(f"Applying: {sql.splitlines()[0][:80]}")
        rds_data.execute_statement(
            resourceArn=CLUSTER_ARN,
            secretArn=SECRET_ARN,
            database=DATABASE_NAME,
            sql=sql,
        )

    return {
        "PhysicalResourceId": "agent-knowledge-schema",
        "Data": {"StatementsApplied": str(len(queries.SCHEMA_DDL))},
    }
