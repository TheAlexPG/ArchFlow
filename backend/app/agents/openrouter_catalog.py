"""OpenRouter model catalog — fetched once per process and cached.

LiteLLM doesn't ship context-window numbers for OpenRouter-only models
(e.g. ``z-ai/glm-5v-turbo``, ``moonshotai/kimi-k2``, etc.) so
``LLMClient.context_window()`` falls back to a 8192-token default and the
context manager starts compacting prematurely. OpenRouter publishes the
authoritative metadata at ``GET /api/v1/models`` — we fetch once per
process and cache the resulting ``{model_id: context_length}`` map.

Usage from :mod:`app.services.agent_settings_service`::

    from app.agents import openrouter_catalog
    if settings.litellm_provider == "openrouter" and settings.litellm_context_window is None:
        settings.litellm_context_window = await openrouter_catalog.get_context_length(
            settings.litellm_model
        )

The fetcher is best-effort: if OpenRouter is unreachable or returns an
unexpected payload we just return ``None`` and the caller's existing
fallback (litellm.get_max_tokens → 8192) takes over. The cache TTL is
1 hour — model catalogue changes infrequently and any stale entry only
costs a context-window estimate.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)


_OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
_TTL_SECONDS = 60 * 60  # 1 hour

# {model_id: {"context_length": int, "name": str}}
_cache: dict[str, dict[str, Any]] = {}
_cache_loaded_at: float = 0.0
_cache_lock = asyncio.Lock()


def _is_fresh() -> bool:
    return _cache and (time.monotonic() - _cache_loaded_at) < _TTL_SECONDS


async def _refresh_cache(http: httpx.AsyncClient | None = None) -> None:
    """Fetch the OpenRouter models catalog and replace the in-memory cache.

    Best-effort: any error leaves the previous cache in place (or empty).
    """
    own_client = http is None
    client = http or httpx.AsyncClient(timeout=15.0)
    try:
        response = await client.get(_OPENROUTER_MODELS_URL)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        logger.warning("openrouter_catalog: fetch failed: %s", exc)
        return
    finally:
        if own_client:
            await client.aclose()

    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        logger.warning("openrouter_catalog: unexpected payload shape")
        return

    new_cache: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        ctx = item.get("context_length")
        if not isinstance(model_id, str) or not isinstance(ctx, int) or ctx <= 0:
            continue
        new_cache[model_id] = {
            "context_length": ctx,
            "name": item.get("name") or model_id,
        }

    global _cache, _cache_loaded_at
    _cache = new_cache
    _cache_loaded_at = time.monotonic()
    logger.info(
        "openrouter_catalog: cached %d models (ttl=%ds)",
        len(_cache),
        _TTL_SECONDS,
    )


async def _ensure_loaded() -> None:
    """Load the cache if empty or stale. Concurrent callers wait on a lock."""
    if _is_fresh():
        return
    async with _cache_lock:
        if _is_fresh():
            return
        await _refresh_cache()


async def get_context_length(model_id: str | None) -> int | None:
    """Return the context window for *model_id* per the OpenRouter catalog.

    Returns ``None`` when the cache is empty (fetch failed) or the model
    isn't known to OpenRouter. Caller falls back to whatever default they
    used before this helper landed.
    """
    if not model_id:
        return None
    await _ensure_loaded()
    info = _cache.get(model_id)
    if info is None:
        return None
    return info.get("context_length")


def _reset_for_tests() -> None:
    """Test helper — wipe the cache so monkeypatched HTTP responses re-fetch."""
    global _cache, _cache_loaded_at
    _cache = {}
    _cache_loaded_at = 0.0
