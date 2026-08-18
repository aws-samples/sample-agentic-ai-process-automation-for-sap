# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""One currency-banding definition, shared across the write and read sides.

The exemplar builder (write) and the precedent query (read) must key on the
identical band or the join returns nothing. Keeping the function in the
shared_types layer; the Lambdas that use it must mount that layer.
"""


def amount_band(amount: object) -> str:
    """Bucket a currency amount so precedents join across differing totals.

    Absolute value: a -5000 credit memo raises the same review questions as a
    5000 debit, and banding on the signed value would split the pool for no gain.
    Tolerates None / non-numeric input (returns the lowest band) so a missing
    amount never crashes the tool.
    """
    try:
        value = abs(float(amount or 0))
    except (TypeError, ValueError):
        value = 0.0
    for ceiling in (100, 1_000, 10_000, 100_000):
        if value < ceiling:
            return f"lt_{ceiling}"
    return "gte_100000"
