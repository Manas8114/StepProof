"""Model-404 fallback (AGENT_PROMPT rule 5: disclose substitutions).

Meta's Muse Spark endpoint serves `muse-spark-1.3` today, but a model can 404
(down, renamed, or behind a gateway that lacks it). Rather than hard-fail, the
agent/vision code retries the SAME call on the fallback model (default
`muse-spark-1.1`, env-overridable via MUSE_FALLBACK_MODEL) and records which model
actually answered so it can be DISCLOSED in /api/v2/health and run reports - never
silently swapped.
"""
from __future__ import annotations
from typing import Any, Optional


def responses_with_fallback(client, model: str, **kwargs) -> tuple[Any, str, bool]:
    """Call `client.responses.create(model, **kwargs)`. On a 404 (model not found),
    retry once with the configured fallback model.

    Returns (response, model_used, fell_back). A non-404 API error is re-raised
    unchanged (transient/permission errors are NOT silently downgraded - only a
    missing model is, and even that is reported to the caller)."""
    from openai import APIStatusError
    from . import config as cfg
    try:
        return client.responses.create(model=model, **kwargs), model, False
    except APIStatusError as e:
        fb = cfg.MUSE_FALLBACK_MODEL
        if e.status_code == 404 and fb and fb != model:
            r = client.responses.create(model=fb, **kwargs)
            return r, fb, True
        raise


def active_model(cfg_model: str) -> str:
    return cfg_model or "muse-spark-1.3"
