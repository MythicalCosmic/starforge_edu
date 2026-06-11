"""Anthropic Claude client wrapper.

Defaults:
- Model: `settings.ANTHROPIC_DEFAULT_MODEL` (one source of truth; `claude-sonnet-4-6`).
- Adaptive thinking with effort tunable per call.
- Top-level prompt caching (`cache_control: {"type": "ephemeral"}`)
  enabled by default — caches `tools` + `system` automatically.
- Streaming optional; use for any call with large `max_tokens`.

This wrapper is intentionally thin. Real prompts/tools/orchestration
belong in apps/ai/ (Celery-only — see TenantAIBudget enforcement).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from functools import lru_cache
from typing import Any

import anthropic
from django.conf import settings
from django.core.cache import cache

from core.utils import stable_hash


@lru_cache(maxsize=1)
def get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)


def _cache_key(
    *,
    model: str,
    system: str | None,
    messages: Iterable[dict[str, Any]],
    max_tokens: int,
    effort: str,
) -> str:
    # max_tokens and effort change the response, so they MUST be part of the
    # cache key — otherwise two calls that differ only in those parameters
    # would collide and serve a wrong cached response (TD-17).
    payload = json.dumps(
        {
            "model": model,
            "system": system,
            "messages": list(messages),
            "max_tokens": max_tokens,
            "effort": effort,
        },
        sort_keys=True,
    )
    return f"anthropic:resp:{stable_hash(payload)}"


def complete(
    *,
    messages: list[dict[str, Any]],
    system: str | None = None,
    model: str | None = None,
    max_tokens: int = 16000,
    effort: str = "high",
    use_cache: bool = True,
    use_response_cache: bool = True,
) -> dict[str, Any]:
    """Send a message to Claude and return `{text, usage, raw}`.

    - `use_cache`: enables Anthropic's prompt cache (cheap; cost is paid at write).
    - `use_response_cache`: short-circuits identical prompts via Redis. Default on.
      Disable when temperature-equivalent variation is desirable (rare for Edu).
    """

    model = model or settings.ANTHROPIC_DEFAULT_MODEL
    redis_key = _cache_key(
        model=model,
        system=system,
        messages=messages,
        max_tokens=max_tokens,
        effort=effort,
    )

    if use_response_cache:
        cached = cache.get(redis_key)
        if cached is not None:
            return cached

    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": effort},
    }
    if system is not None:
        kwargs["system"] = system
    if use_cache:
        kwargs["cache_control"] = {"type": "ephemeral"}

    response = get_client().messages.create(**kwargs)
    text = next((b.text for b in response.content if b.type == "text"), "")
    result = {
        "text": text,
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0),
            "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", 0),
        },
        "stop_reason": response.stop_reason,
        "raw_id": response.id,
    }
    if use_response_cache:
        cache.set(redis_key, result, timeout=settings.ANTHROPIC_PROMPT_CACHE_TTL_SECONDS)
    return result
