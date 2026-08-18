# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Sampling kwargs for BedrockModel, gated on what the target model accepts.

Sonnet 5 and the Opus 4.7+ line reject `temperature`/`top_p`/`top_k` outright —
Bedrock returns ValidationException "`temperature` is deprecated for this model",
so a model swap alone turns every agent call into a 400. Strands forwards
whatever `temperature` it is constructed with and omits the field entirely when
unset, so the guard belongs at construction time, here, rather than in each
caller.

Older tiers (Sonnet 4.5, Haiku 4.5) still accept it, and the low value is a
deliberate determinism nudge for financial reasoning, so it is kept where it
still works. Note it never guaranteed identical outputs on those models either.
"""

# Substrings of model IDs that reject sampling params. Matched on the ID rather
# than enumerated in full because Bedrock IDs carry region prefixes
# (`us.`/`global.`) and, for the newer models, no date suffix to pin.
_NO_SAMPLING_PARAMS = ("sonnet-5", "opus-5", "opus-4-7", "opus-4-8", "fable-5")


def sampling_kwargs(model_id: str, temperature: float) -> dict:
    """`{"temperature": ...}` when the model accepts it, else `{}`."""
    if any(marker in model_id for marker in _NO_SAMPLING_PARAMS):
        return {}
    return {"temperature": temperature}
