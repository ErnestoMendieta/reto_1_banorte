"""Retry con backoff para 429/rate-limit de OpenRouter — usado por orchestrator.py (live) y evaluation/run_eval.py (batch)."""

from __future__ import annotations

import time
from collections.abc import Callable


def is_rate_limit_error(exc: Exception) -> bool:
    msg = str(exc)
    return "429" in msg or "rate limit" in msg.lower() or "RateLimit" in type(exc).__name__


def call_with_rate_limit_retry(
    fn: Callable,
    *,
    max_retries: int = 3,
    base_delay: float = 3.0,
    max_delay: float = 20.0,
    on_retry: Callable[[int, float], None] | None = None,
):
    """Llama fn(), reintentando con backoff exponencial solo ante errores de rate limit.

    Cualquier otra excepción se propaga de inmediato.
    """
    delay = base_delay
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as exc:
            if not is_rate_limit_error(exc) or attempt == max_retries:
                raise
            if on_retry:
                on_retry(attempt + 1, delay)
            time.sleep(delay)
            delay = min(delay * 2, max_delay)
