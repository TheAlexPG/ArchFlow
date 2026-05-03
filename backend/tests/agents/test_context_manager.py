"""Tests for app/agents/context_manager.py.

Coverage:
- Each strategy in isolation:
  * TrimLargeToolResults — replaces oversized tool replies, idempotent.
  * DropOldestToolMessages — keeps tool replies for the last 4 turn-pairs only.
  * SummarizeOldestHalf — replaces older half with a single ``## Earlier in
    this session`` system message (LLM mocked).
  * HardTruncateKeepRecent — keeps system + last 10 messages.
- ContextManager:
  * No-op below threshold (stage_applied == 0).
  * First-hit applies stage 1.
  * Escalation: current_stage=2 → stage_applied=3.
  * Cap at last stage when current_stage exceeds ladder length.
  * Invalid strategy name in init raises ValueError listing valid keys.
  * tokens_after < tokens_before in a normal smoke test.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.agents.context_manager import (
    DROPPED_TOOL_RESULT_PLACEHOLDER,
    STRATEGY_REGISTRY,
    CompactionResult,
    ContextManager,
    DropOldestToolMessages,
    HardTruncateKeepRecent,
    SummarizeOldestHalf,
    TrimLargeToolResults,
)
from app.agents.llm import LLMCallMetadata, LLMClient
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
    )


# ---------------------------------------------------------------------------
# TrimLargeToolResults
# ---------------------------------------------------------------------------


async def test_trim_large_tool_results_replaces_oversized(
    client: LLMClient, call_meta: LLMCallMetadata
):
    """A 30k-character tool result should be replaced with a placeholder."""
    big_text = "x" * 30_000  # at ~4 chars/token, ~7500 tokens — well above 2000.
    messages: list[dict] = [
        {"role": "system", "content": "You are an agent."},
        {"role": "user", "content": "Run the tool."},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "big_tool", "arguments": "{}"},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "name": "big_tool",
            "content": big_text,
        },
        {"role": "assistant", "content": "Done."},
    ]

    strategy = TrimLargeToolResults()
    out = await strategy.apply(
        messages,
        llm=client,
        call_metadata=call_meta,
        tool_result_trim_threshold_tokens=2000,
    )

    # Same length, only the tool reply mutated.
    assert len(out) == len(messages)
    assert out[0] == messages[0]
    assert out[1] == messages[1]
    assert out[2] == messages[2]
    assert out[4] == messages[4]

    truncated = out[3]
    assert truncated["role"] == "tool"
    assert isinstance(truncated["content"], str)
    assert truncated["content"].startswith("<truncated: big_tool(...),")
    assert truncated["content"].endswith("tokens>")


async def test_trim_large_tool_results_is_idempotent(
    client: LLMClient, call_meta: LLMCallMetadata
):
    """Running the strategy twice produces identical output the second time."""
    messages: list[dict] = [
        {"role": "user", "content": "Run."},
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "name": "big_tool",
            "content": "y" * 30_000,
        },
    ]
    strategy = TrimLargeToolResults()
    once = await strategy.apply(
        messages,
        llm=client,
        call_metadata=call_meta,
        tool_result_trim_threshold_tokens=2000,
    )
    twice = await strategy.apply(
        once,
        llm=client,
        call_metadata=call_meta,
        tool_result_trim_threshold_tokens=2000,
    )
    assert once == twice
    # Final placeholder must still be the Stage-1 sentinel.
    assert twice[1]["content"].startswith("<truncated:")


async def test_trim_large_tool_results_leaves_small_replies_alone(
    client: LLMClient, call_meta: LLMCallMetadata
):
    messages: list[dict] = [
        {"role": "user", "content": "Run."},
        {
            "role": "tool",
            "tool_call_id": "c1",
            "name": "small_tool",
            "content": "ok",
        },
    ]
    strategy = TrimLargeToolResults()
    out = await strategy.apply(
        messages,
        llm=client,
        call_metadata=call_meta,
        tool_result_trim_threshold_tokens=2000,
    )
    assert out == messages


# ---------------------------------------------------------------------------
# DropOldestToolMessages
# ---------------------------------------------------------------------------


def _build_turn_pairs(n_pairs: int) -> list[dict]:
    """Build ``n_pairs`` (user, assistant + tool_call, tool_reply) sequences."""
    msgs: list[dict] = [{"role": "system", "content": "sys prompt"}]
    for i in range(n_pairs):
        msgs.append({"role": "user", "content": f"user msg {i}"})
        msgs.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"call_{i}",
                        "type": "function",
                        "function": {"name": "t", "arguments": "{}"},
                    }
                ],
            }
        )
        msgs.append(
            {
                "role": "tool",
                "tool_call_id": f"call_{i}",
                "name": "t",
                "content": f"verbose tool result {i}",
            }
        )
    return msgs


async def test_drop_oldest_tool_messages_keeps_last_4_pairs(
    client: LLMClient, call_meta: LLMCallMetadata
):
    """8 turn-pairs → last 4 retain tool content; first 4 are placeholders."""
    messages = _build_turn_pairs(8)
    strategy = DropOldestToolMessages()
    out = await strategy.apply(
        messages,
        llm=client,
        call_metadata=call_meta,
        tool_result_trim_threshold_tokens=2000,
    )

    # Same length and structure — we only rewrite tool message *content*.
    assert len(out) == len(messages)
    for original, new in zip(messages, out, strict=True):
        assert original.get("role") == new.get("role")

    # Collect tool-message contents in pair order.
    tool_contents = [m["content"] for m in out if m.get("role") == "tool"]
    assert len(tool_contents) == 8

    # First 4 pairs (oldest) → placeholder.
    for content in tool_contents[:4]:
        assert content == DROPPED_TOOL_RESULT_PLACEHOLDER
    # Last 4 pairs → original verbose content.
    for i, content in enumerate(tool_contents[4:], start=4):
        assert content == f"verbose tool result {i}"


async def test_drop_oldest_tool_messages_preserves_assistant_tool_calls(
    client: LLMClient, call_meta: LLMCallMetadata
):
    """The assistant ``tool_calls`` announcements must remain intact."""
    messages = _build_turn_pairs(8)
    strategy = DropOldestToolMessages()
    out = await strategy.apply(
        messages,
        llm=client,
        call_metadata=call_meta,
        tool_result_trim_threshold_tokens=2000,
    )
    assistant_msgs = [m for m in out if m.get("role") == "assistant"]
    # All 8 assistant messages still carry their tool_calls payload.
    assert len(assistant_msgs) == 8
    for m in assistant_msgs:
        assert m.get("tool_calls") is not None
        assert len(m["tool_calls"]) == 1


# ---------------------------------------------------------------------------
# SummarizeOldestHalf
# ---------------------------------------------------------------------------


async def test_summarize_oldest_half_replaces_older_half(
    client: LLMClient,
    call_meta: LLMCallMetadata,
    monkeypatch: pytest.MonkeyPatch,
):
    """LLM call mocked: assert old half collapses to one summary system message."""
    import litellm

    real_acompletion = litellm.acompletion
    canned_summary = "Created diagram d1 and object o1; chose REST over gRPC."

    async def patched(**kwargs: Any):
        kwargs.setdefault("api_key", "sk-fake")
        kwargs["mock_response"] = canned_summary
        return await real_acompletion(**kwargs)

    monkeypatch.setattr("app.agents.llm.litellm.acompletion", patched)

    # Build 12 non-system messages: 6 older (to be summarized) + 4 to keep
    # (SUMMARIZE_KEEP_TAIL=4) + 2 in the middle that fall in "keep_body".
    # Layout: body = first 8 non-system, summarize = first 4, keep_body = next 4,
    # tail = last 4. Total non-system = 12.
    messages: list[dict] = [{"role": "system", "content": "sys prompt"}]
    for i in range(12):
        role = "user" if i % 2 == 0 else "assistant"
        messages.append({"role": role, "content": f"message {i}"})

    strategy = SummarizeOldestHalf()
    out = await strategy.apply(
        messages,
        llm=client,
        call_metadata=call_meta,
        tool_result_trim_threshold_tokens=2000,
        model_override="openai/gpt-4o-mini",
    )

    # Expected: original system + summary system + (12 - 4 - 4) = 4 kept body + 4 tail
    # → 1 + 1 + 4 + 4 = 10 messages.
    assert len(out) == 10
    assert out[0] == messages[0]

    summary_msg = out[1]
    assert summary_msg["role"] == "system"
    assert summary_msg["content"].startswith("## Earlier in this session\n")
    assert canned_summary in summary_msg["content"]

    # Tail untouched (last 4 of original ⇒ "message 8".."message 11").
    tail = out[-4:]
    assert tail[-1]["content"] == "message 11"
    assert tail[0]["content"] == "message 8"


async def test_summarize_oldest_half_short_history_is_noop(
    client: LLMClient, call_meta: LLMCallMetadata
):
    """Fewer non-system messages than SUMMARIZE_KEEP_TAIL → return as-is."""
    messages: list[dict] = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    out = await SummarizeOldestHalf().apply(
        messages,
        llm=client,
        call_metadata=call_meta,
        tool_result_trim_threshold_tokens=2000,
        model_override="openai/gpt-4o-mini",
    )
    assert out == messages


# ---------------------------------------------------------------------------
# HardTruncateKeepRecent
# ---------------------------------------------------------------------------


async def test_hard_truncate_keeps_system_plus_last_10(
    client: LLMClient, call_meta: LLMCallMetadata
):
    messages: list[dict] = [
        {"role": "system", "content": "primary system"},
        {"role": "system", "content": "second system"},
    ]
    for i in range(30):
        role = "user" if i % 2 == 0 else "assistant"
        messages.append({"role": role, "content": f"m{i}"})

    out = await HardTruncateKeepRecent().apply(
        messages,
        llm=client,
        call_metadata=call_meta,
        tool_result_trim_threshold_tokens=2000,
    )

    # 2 systems + 10 most recent = 12.
    assert len(out) == 12
    assert out[0] == messages[0]
    assert out[1] == messages[1]
    # Tail should match indices 22..31 of original (== last 10 non-system).
    assert out[2]["content"] == "m20"
    assert out[-1]["content"] == "m29"


# ---------------------------------------------------------------------------
# ContextManager
# ---------------------------------------------------------------------------


def test_strategy_registry_has_all_four_keys():
    assert set(STRATEGY_REGISTRY) == {
        "trim_large_tool_results",
        "drop_oldest_tool_messages",
        "summarize_oldest_half",
        "hard_truncate_keep_recent",
    }


def test_invalid_strategy_name_raises_with_valid_keys_listed():
    with pytest.raises(ValueError) as exc_info:
        ContextManager(ladder_strategy_names=["nope"])
    msg = str(exc_info.value)
    assert "nope" in msg
    for key in STRATEGY_REGISTRY:
        assert key in msg


def test_invalid_threshold_raises():
    with pytest.raises(ValueError):
        ContextManager(threshold=0.0)
    with pytest.raises(ValueError):
        ContextManager(threshold=1.5)


def test_empty_ladder_raises():
    with pytest.raises(ValueError):
        ContextManager(ladder_strategy_names=[])


async def test_maybe_compact_noop_below_threshold(
    client: LLMClient, call_meta: LLMCallMetadata, monkeypatch: pytest.MonkeyPatch
):
    """ratio < threshold ⇒ stage_applied == 0 and messages unchanged."""
    monkeypatch.setattr(client, "count_tokens", lambda messages, **kw: 100)
    monkeypatch.setattr(client, "context_window", lambda **kw: 10_000)

    cm = ContextManager(threshold=0.5)
    messages = [{"role": "user", "content": "hi"}]

    result = await cm.maybe_compact(
        messages,
        llm=client,
        current_stage=0,
        call_metadata=call_meta,
    )
    assert isinstance(result, CompactionResult)
    assert result.stage_applied == 0
    assert result.strategy_name is None
    assert result.compacted_messages is messages
    assert result.tokens_before == 100
    assert result.tokens_after == 100


async def test_maybe_compact_applies_stage_1_on_first_hit(
    client: LLMClient, call_meta: LLMCallMetadata, monkeypatch: pytest.MonkeyPatch
):
    """current_stage=0, ratio>=threshold ⇒ stage_applied=1 (first ladder entry)."""
    # First call (tokens_before) returns big number; second call (tokens_after) smaller.
    counts = iter([8000, 4000])
    monkeypatch.setattr(client, "count_tokens", lambda messages, **kw: next(counts))
    monkeypatch.setattr(client, "context_window", lambda **kw: 10_000)

    cm = ContextManager(threshold=0.5)
    messages: list[dict] = [
        {"role": "user", "content": "x"},
        {
            "role": "tool",
            "tool_call_id": "c1",
            "name": "t",
            "content": "y" * 30_000,
        },
    ]

    result = await cm.maybe_compact(
        messages,
        llm=client,
        current_stage=0,
        call_metadata=call_meta,
    )
    assert result.stage_applied == 1
    assert result.strategy_name == "trim_large_tool_results"
    assert result.tokens_before == 8000
    assert result.tokens_after == 4000


async def test_maybe_compact_escalates_from_stage_2_to_stage_3(
    client: LLMClient,
    call_meta: LLMCallMetadata,
    monkeypatch: pytest.MonkeyPatch,
):
    """current_stage=2 → next stage applied is 3 (summarize_oldest_half)."""
    import litellm

    real_acompletion = litellm.acompletion

    async def patched(**kwargs: Any):
        kwargs.setdefault("api_key", "sk-fake")
        kwargs["mock_response"] = "summary text"
        return await real_acompletion(**kwargs)

    monkeypatch.setattr("app.agents.llm.litellm.acompletion", patched)

    counts = iter([9000, 5000])
    monkeypatch.setattr(client, "count_tokens", lambda messages, **kw: next(counts))
    monkeypatch.setattr(client, "context_window", lambda **kw: 10_000)

    cm = ContextManager(threshold=0.5, summarizer_model_override="openai/gpt-4o-mini")
    messages: list[dict] = [{"role": "system", "content": "sys"}]
    for i in range(12):
        role = "user" if i % 2 == 0 else "assistant"
        messages.append({"role": role, "content": f"m{i}"})

    result = await cm.maybe_compact(
        messages,
        llm=client,
        current_stage=2,
        call_metadata=call_meta,
    )
    assert result.stage_applied == 3
    assert result.strategy_name == "summarize_oldest_half"


async def test_maybe_compact_caps_at_last_stage(
    client: LLMClient, call_meta: LLMCallMetadata, monkeypatch: pytest.MonkeyPatch
):
    """current_stage=4 (already at last stage) ⇒ stage_applied=4 (re-applied)."""
    counts = iter([9500, 1000])
    monkeypatch.setattr(client, "count_tokens", lambda messages, **kw: next(counts))
    monkeypatch.setattr(client, "context_window", lambda **kw: 10_000)

    cm = ContextManager(threshold=0.5)
    messages: list[dict] = [{"role": "system", "content": "sys"}]
    for i in range(30):
        role = "user" if i % 2 == 0 else "assistant"
        messages.append({"role": role, "content": f"m{i}"})

    result = await cm.maybe_compact(
        messages,
        llm=client,
        current_stage=4,
        call_metadata=call_meta,
    )
    assert result.stage_applied == 4
    assert result.strategy_name == "hard_truncate_keep_recent"


async def test_maybe_compact_tokens_after_less_than_before_smoke(
    client: LLMClient, call_meta: LLMCallMetadata, monkeypatch: pytest.MonkeyPatch
):
    """Smoke: real token counter (no monkeypatch) shows compaction shrinks tokens.

    We only patch context_window so the threshold is reliably crossed.
    """
    monkeypatch.setattr(client, "context_window", lambda **kw: 256)

    cm = ContextManager(threshold=0.1)  # easy to cross
    big_text = "the quick brown fox jumps over the lazy dog. " * 200
    messages: list[dict] = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "do it"},
        {
            "role": "tool",
            "tool_call_id": "c1",
            "name": "noisy",
            "content": big_text,
        },
        {"role": "assistant", "content": "done"},
    ]

    result = await cm.maybe_compact(
        messages,
        llm=client,
        current_stage=0,
        call_metadata=call_meta,
    )
    assert result.stage_applied == 1
    assert result.tokens_after < result.tokens_before


def test_ladder_names_property_round_trips():
    cm = ContextManager()
    assert cm.ladder_names == [
        "trim_large_tool_results",
        "drop_oldest_tool_messages",
        "summarize_oldest_half",
        "hard_truncate_keep_recent",
    ]


def test_custom_ladder_subset_is_honored():
    cm = ContextManager(
        ladder_strategy_names=[
            "trim_large_tool_results",
            "hard_truncate_keep_recent",
        ]
    )
    assert cm.ladder_names == [
        "trim_large_tool_results",
        "hard_truncate_keep_recent",
    ]
