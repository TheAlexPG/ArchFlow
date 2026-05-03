"""Tests for app/agents/llm.py.

Coverage:
- ``acompletion`` happy path (mock_response).
- ``acompletion`` with tool calls (mock_tool_calls).
- ``acompletion`` ContextOverflow on context-length BadRequestError.
- ``astream`` emits tokens then a finish event with token counts.
- ``count_tokens`` returns positive int.
- ``context_window`` for known + unknown models.
- ``_build_langfuse_metadata`` consent / env-var matrix.
- Secret-bearing message doesn't crash the call (forward-compat for redaction
  in task 013).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from app.agents.errors import AgentError, ContextOverflow
from app.agents.llm import LLMCallMetadata, LLMClient, LLMResult
from app.services.agent_settings_service import ResolvedAgentSettings

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def settings() -> ResolvedAgentSettings:
    return ResolvedAgentSettings(workspace_id=uuid4(), agent_id="general")


@pytest.fixture()
def client(settings: ResolvedAgentSettings) -> LLMClient:
    return LLMClient(settings)


@pytest.fixture()
def call_meta() -> LLMCallMetadata:
    return LLMCallMetadata(
        workspace_id=uuid4(),
        agent_id="general",
        session_id=uuid4(),
        actor_id=uuid4(),
        analytics_consent="off",
        prompt_version="abc1234",
        node_name="planner",
        step_index=0,
        context_kind="diagram",
    )


# ---------------------------------------------------------------------------
# acompletion — non-streaming
# ---------------------------------------------------------------------------


async def test_acompletion_happy_path(
    client: LLMClient, call_meta: LLMCallMetadata, monkeypatch: pytest.MonkeyPatch
):
    """Patch litellm.acompletion to inject mock_response so we never touch the network."""
    import litellm

    real_acompletion = litellm.acompletion

    async def patched(**kwargs: Any):
        kwargs["mock_response"] = "Hi from mock"
        kwargs.setdefault("api_key", "sk-fake")
        return await real_acompletion(**kwargs)

    monkeypatch.setattr(litellm, "acompletion", patched)
    monkeypatch.setattr("app.agents.llm.litellm.acompletion", patched)

    result = await client.acompletion(
        messages=[{"role": "user", "content": "Hello"}],
        metadata=call_meta,
    )
    assert isinstance(result, LLMResult)
    assert result.text == "Hi from mock"
    assert result.tokens_in > 0
    assert result.tokens_out > 0
    assert result.finish_reason == "stop"
    assert result.cost_usd is None or isinstance(result.cost_usd, Decimal)
    assert result.tool_calls is None


async def test_acompletion_with_tools(
    client: LLMClient, call_meta: LLMCallMetadata, monkeypatch: pytest.MonkeyPatch
):
    """LiteLLM's mock_tool_calls returns a tool-call response."""
    import litellm

    real = litellm.acompletion

    async def patched(**kwargs: Any):
        kwargs.setdefault("api_key", "sk-fake")
        kwargs["mock_tool_calls"] = [
            {
                "id": "call_42",
                "type": "function",
                "function": {"name": "do_thing", "arguments": '{"x": 1}'},
            }
        ]
        return await real(**kwargs)

    monkeypatch.setattr("app.agents.llm.litellm.acompletion", patched)

    tool_def = {
        "type": "function",
        "function": {
            "name": "do_thing",
            "description": "Do a thing.",
            "parameters": {
                "type": "object",
                "properties": {"x": {"type": "integer"}},
            },
        },
    }
    result = await client.acompletion(
        messages=[{"role": "user", "content": "Trigger the tool."}],
        tools=[tool_def],
        tool_choice="auto",
        metadata=call_meta,
    )
    assert result.tool_calls is not None
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["id"] == "call_42"
    assert result.tool_calls[0]["name"] == "do_thing"
    assert result.tool_calls[0]["arguments"] == '{"x": 1}'


async def test_acompletion_context_length_raises_overflow(
    client: LLMClient, call_meta: LLMCallMetadata, monkeypatch: pytest.MonkeyPatch
):
    """A BadRequestError carrying 'context_length_exceeded' → ContextOverflow."""
    from litellm.exceptions import BadRequestError

    async def patched(**kwargs: Any):
        raise BadRequestError(
            message="This model's maximum context length is 8192 tokens. "
            "context_length_exceeded.",
            model="openai/gpt-4o-mini",
            llm_provider="openai",
        )

    monkeypatch.setattr("app.agents.llm.litellm.acompletion", patched)

    with pytest.raises(ContextOverflow):
        await client.acompletion(
            messages=[{"role": "user", "content": "anything"}],
            metadata=call_meta,
        )


async def test_acompletion_other_bad_request_wraps_in_agent_error(
    client: LLMClient, call_meta: LLMCallMetadata, monkeypatch: pytest.MonkeyPatch
):
    """Non-context-length BadRequestError → wrapped in AgentError."""
    from litellm.exceptions import BadRequestError

    async def patched(**kwargs: Any):
        raise BadRequestError(
            message="Invalid tool schema: 'parameters' missing.",
            model="openai/gpt-4o-mini",
            llm_provider="openai",
        )

    monkeypatch.setattr("app.agents.llm.litellm.acompletion", patched)

    with pytest.raises(AgentError) as exc_info:
        await client.acompletion(
            messages=[{"role": "user", "content": "x"}],
            metadata=call_meta,
        )
    # ContextOverflow is an AgentError subclass — make sure we got the *base*
    # AgentError for non-overflow errors, not ContextOverflow.
    assert not isinstance(exc_info.value, ContextOverflow)


# ---------------------------------------------------------------------------
# astream
# ---------------------------------------------------------------------------


async def test_astream_emits_tokens_then_finish(
    client: LLMClient, call_meta: LLMCallMetadata, monkeypatch: pytest.MonkeyPatch
):
    """Stream a mock response → token events first, then a single finish event."""
    import litellm

    real = litellm.acompletion

    async def patched(**kwargs: Any):
        kwargs.setdefault("api_key", "sk-fake")
        kwargs["mock_response"] = "abc"
        return await real(**kwargs)

    monkeypatch.setattr("app.agents.llm.litellm.acompletion", patched)

    events: list[dict] = []
    async for ev in client.astream(
        messages=[{"role": "user", "content": "hi"}],
        metadata=call_meta,
    ):
        events.append(ev)

    # Token events all come before finish.
    finish_idx = next(i for i, e in enumerate(events) if e["kind"] == "finish")
    for ev in events[:finish_idx]:
        assert ev["kind"] in {"token", "tool_call_start", "tool_call_delta"}

    # Exactly one finish.
    assert sum(1 for e in events if e["kind"] == "finish") == 1
    finish = events[finish_idx]
    assert finish["reason"] == "stop"
    assert finish["tokens_in"] > 0
    assert finish["tokens_out"] > 0
    assert finish["tool_calls"] == []
    assert finish["cost_usd"] is None or isinstance(finish["cost_usd"], Decimal)

    # Concatenated token deltas reproduce the mock text.
    text = "".join(e["text"] for e in events if e["kind"] == "token")
    assert text == "abc"


# ---------------------------------------------------------------------------
# count_tokens / context_window
# ---------------------------------------------------------------------------


def test_count_tokens_returns_positive(client: LLMClient):
    n = client.count_tokens([{"role": "user", "content": "hello world"}])
    assert isinstance(n, int)
    assert n > 0


def test_context_window_known_model(client: LLMClient):
    window = client.context_window()
    # gpt-4o-mini is well-known; expect > 4096.
    assert window >= 4096


def test_context_window_unknown_model_falls_back(
    settings: ResolvedAgentSettings, monkeypatch: pytest.MonkeyPatch
):
    settings.litellm_model = "totally-fake-provider/totally-fake-model-xyz"
    c = LLMClient(settings)
    assert c.context_window() == 8192


# ---------------------------------------------------------------------------
# _build_langfuse_metadata
# ---------------------------------------------------------------------------


def test_langfuse_metadata_off_returns_none(client: LLMClient):
    meta = LLMCallMetadata(
        workspace_id=uuid4(),
        agent_id="general",
        session_id=uuid4(),
        actor_id=uuid4(),
        analytics_consent="off",
    )
    assert client._build_langfuse_metadata(meta) is None


def test_langfuse_metadata_full_with_env_returns_dict(
    client: LLMClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test-deadbeef")
    trace_id = "11111111-1111-1111-1111-111111111111"
    meta = LLMCallMetadata(
        workspace_id=uuid4(),
        agent_id="general",
        session_id=uuid4(),
        actor_id=uuid4(),
        analytics_consent="full",
        prompt_version="abc1234",
        node_name="planner",
        context_kind="diagram",
        trace_id=trace_id,
    )
    out = client._build_langfuse_metadata(meta)
    assert out is not None
    # LiteLLM-Langfuse trace-grouping keys.
    assert out["trace_id"] == trace_id
    assert out["session_id"] == str(meta.session_id)
    assert out["trace_name"] == f"agent:{meta.agent_id}"
    assert out["generation_name"] == "planner"
    assert out["user_id"] == str(meta.actor_id)
    # Back-compat keys preserved.
    assert out["trace_user_id"] == str(meta.actor_id)
    assert out["trace_session_id"] == str(meta.session_id)
    tags = out["tags"]
    assert f"agent:{meta.agent_id}" in tags
    assert f"workspace:{meta.workspace_id}" in tags
    assert "context:diagram" in tags
    assert "analytics_mode:full" in tags
    assert f"model:{client.model}" in tags
    assert "prompt_version:abc1234" in tags
    assert "node:planner" in tags


def test_langfuse_metadata_full_without_trace_id_omits_key(
    client: LLMClient, monkeypatch: pytest.MonkeyPatch
):
    """When no trace_id is set, the key is omitted so LiteLLM auto-generates one."""
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test-deadbeef")
    meta = LLMCallMetadata(
        workspace_id=uuid4(),
        agent_id="general",
        session_id=uuid4(),
        actor_id=uuid4(),
        analytics_consent="full",
        node_name="explainer",
    )
    out = client._build_langfuse_metadata(meta)
    assert out is not None
    assert "trace_id" not in out
    assert out["generation_name"] == "explainer"


def test_langfuse_metadata_full_without_env_returns_none(
    client: LLMClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    meta = LLMCallMetadata(
        workspace_id=uuid4(),
        agent_id="general",
        session_id=uuid4(),
        actor_id=uuid4(),
        analytics_consent="full",
    )
    assert client._build_langfuse_metadata(meta) is None


def test_langfuse_metadata_errors_only_with_env_returns_dict(
    client: LLMClient, monkeypatch: pytest.MonkeyPatch
):
    """``errors_only`` still produces metadata; routing happens via failure_callback."""
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test-x")
    meta = LLMCallMetadata(
        workspace_id=uuid4(),
        agent_id="general",
        session_id=uuid4(),
        actor_id=uuid4(),
        analytics_consent="errors_only",
    )
    out = client._build_langfuse_metadata(meta)
    assert out is not None
    assert "analytics_mode:errors_only" in out["tags"]


# ---------------------------------------------------------------------------
# Secret scrubbing forward-compat
# ---------------------------------------------------------------------------


async def test_call_with_secret_in_message_does_not_crash(
    client: LLMClient, call_meta: LLMCallMetadata, monkeypatch: pytest.MonkeyPatch
):
    """A user message containing an api-key-shaped string must not crash the
    call path. Full redaction lands in task 013; this guards forward-compat.
    """
    import litellm

    real = litellm.acompletion

    async def patched(**kwargs: Any):
        kwargs.setdefault("api_key", "sk-fake")
        kwargs["mock_response"] = "ok"
        return await real(**kwargs)

    monkeypatch.setattr("app.agents.llm.litellm.acompletion", patched)

    result = await client.acompletion(
        messages=[
            {
                "role": "user",
                "content": "My API key is sk-abc123def456 — please ignore.",
            }
        ],
        metadata=call_meta,
    )
    assert result.text == "ok"
