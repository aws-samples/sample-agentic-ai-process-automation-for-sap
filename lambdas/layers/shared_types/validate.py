# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Graceful schema validation for shared_types models.

Ships in the shared_types Lambda layer alongside the generated pydantic models.
Lambdas call ``validate_or_log(WorkItem, item)`` right before persisting or after
reading a record. It is a safety net, never a gate:

  * Returns the original ``data`` unchanged (callers keep DynamoDB ``Decimal``s etc.).
  * On a validation error it logs a warning and continues — a bad record must
    never take down a read or a write.
  * If pydantic/the model is unavailable (e.g. local dev without the layer), it
    no-ops silently.

The models use ``extra="forbid"``, so this also surfaces schema drift — code that
starts writing fields the schema doesn't know about.
"""

import logging

logger = logging.getLogger(__name__)


def validate_or_log(model, data, *, context=""):
    """Validate ``data`` against a pydantic ``model``; log and continue on failure.

    Args:
        model: A pydantic model class (e.g. WorkItem), or None to no-op.
        data: The dict to validate. Always returned unchanged.
        context: Optional label for the log line (e.g. "cases_api.get").

    Returns:
        ``data``, unchanged.
    """
    if model is None:
        return data
    try:
        model.model_validate(data)
    except Exception as e:  # pydantic ValidationError — log, never raise
        label = f" [{context}]" if context else ""
        logger.warning("schema validation failed%s: %s", label, e)
    return data
