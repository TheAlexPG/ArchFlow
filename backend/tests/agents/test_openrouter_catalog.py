"""Unit tests for the OpenRouter context-length catalog fetcher."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents import openrouter_catalog


@pytest.fixture(autouse=True)
def _reset_cache():
    openrouter_catalog._reset_for_tests()
    yield
    openrouter_catalog._reset_for_tests()


def _make_response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=payload)
    return resp


@pytest.mark.asyncio
async def test_get_context_length_returns_value_from_catalog(monkeypatch):
    fake_payload = {
        "data": [
            {"id": "z-ai/glm-5v-turbo", "name": "GLM 5V Turbo", "context_length": 131072},
            {"id": "anthropic/claude-haiku-4.5", "name": "Claude Haiku 4.5", "context_length": 200000},
        ]
    }
    fake_client = MagicMock()
    fake_client.get = AsyncMock(return_value=_make_response(fake_payload))
    fake_client.aclose = AsyncMock()

    monkeypatch.setattr(
        "app.agents.openrouter_catalog.httpx.AsyncClient",
        lambda *a, **kw: fake_client,
    )

    ctx = await openrouter_catalog.get_context_length("z-ai/glm-5v-turbo")
    assert ctx == 131072

    # Second call hits cache, no extra HTTP request.
    fake_client.get.reset_mock()
    ctx2 = await openrouter_catalog.get_context_length("anthropic/claude-haiku-4.5")
    assert ctx2 == 200000
    fake_client.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_context_length_unknown_model_returns_none(monkeypatch):
    fake_payload = {"data": [{"id": "openai/gpt-4o-mini", "context_length": 128000}]}
    fake_client = MagicMock()
    fake_client.get = AsyncMock(return_value=_make_response(fake_payload))
    fake_client.aclose = AsyncMock()
    monkeypatch.setattr(
        "app.agents.openrouter_catalog.httpx.AsyncClient",
        lambda *a, **kw: fake_client,
    )

    ctx = await openrouter_catalog.get_context_length("totally/not-a-model")
    assert ctx is None


@pytest.mark.asyncio
async def test_get_context_length_fetch_failure_returns_none(monkeypatch):
    fake_client = MagicMock()
    fake_client.get = AsyncMock(side_effect=RuntimeError("network down"))
    fake_client.aclose = AsyncMock()
    monkeypatch.setattr(
        "app.agents.openrouter_catalog.httpx.AsyncClient",
        lambda *a, **kw: fake_client,
    )

    ctx = await openrouter_catalog.get_context_length("z-ai/glm-5v-turbo")
    assert ctx is None


@pytest.mark.asyncio
async def test_get_context_length_handles_missing_or_invalid_fields(monkeypatch):
    fake_payload = {
        "data": [
            {"id": "no-ctx-model"},  # missing context_length
            {"id": "bad-ctx", "context_length": "not an int"},
            {"id": "zero-ctx", "context_length": 0},
            {"context_length": 8192},  # missing id
            {"id": "valid-model", "context_length": 32768},
        ]
    }
    fake_client = MagicMock()
    fake_client.get = AsyncMock(return_value=_make_response(fake_payload))
    fake_client.aclose = AsyncMock()
    monkeypatch.setattr(
        "app.agents.openrouter_catalog.httpx.AsyncClient",
        lambda *a, **kw: fake_client,
    )

    assert await openrouter_catalog.get_context_length("no-ctx-model") is None
    assert await openrouter_catalog.get_context_length("bad-ctx") is None
    assert await openrouter_catalog.get_context_length("zero-ctx") is None
    assert await openrouter_catalog.get_context_length("valid-model") == 32768


@pytest.mark.asyncio
async def test_get_context_length_no_model_id_returns_none():
    assert await openrouter_catalog.get_context_length(None) is None
    assert await openrouter_catalog.get_context_length("") is None
