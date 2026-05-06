"""Compaction eval suite — deterministic (Stage 3 uses fake LLM, no real call).

Drives ContextManager.maybe_compact through all four ladder stages and
verifies the correct strategy fires and the message list transforms correctly.

No LLM calls: the fake LLM returns a preset summary string for Stage 3.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.context_manager import (
    DROPPED_TOOL_RESULT_PLACEHOLDER,
    ContextManager,
)
from app.agents.llm import LLMCallMetadata, LLMClient, LLMResult
from app.services.agent_settings_service import ResolvedAgentSettings

GOLDEN = json.loads((Path(__file__).parent / "golden" / "compaction.json").read_text())


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_call_meta() -> LLMCallMetadata:
    return LLMCallMetadata(
        workspace_id=uuid4(),
        agent_id="general",
        session_id=uuid4(),
        actor_id=uuid4(),
        analytics_consent="off",
    )


def _make_client() -> LLMClient:
    settings = ResolvedAgentSettings(workspace_id=uuid4(), agent_id="general")
    return LLMClient(settings)


def _make_messages_with_big_tool_result(char_count: int) -> list[dict]:
    """Messages where one tool result has ``char_count`` characters (>> 2000 tokens)."""
    big_text = "x" * char_count
    return [
        {"role": "system", "content": "You are an agent."},
        {"role": "user", "content": "Run the tool."},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "tc-1", "function": {"name": "list_objects", "arguments": "{}"}}],
        },
        {"role": "tool", "name": "list_objects", "content": big_text, "tool_call_id": "tc-1"},
    ]


def _make_many_turn_messages(num_pairs: int) -> list[dict]:
    """Build ``num_pairs`` (user, assistant+tool) turn-pair messages."""
    messages: list[dict] = [{"role": "system", "content": "Agent instructions."}]
    for i in range(num_pairs):
        tc_id = f"tc-{i}"
        messages.append({"role": "user", "content": f"Turn {i} question."})
        messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": tc_id, "function": {"name": "list_objects", "arguments": "{}"}}
                ],
            }
        )
        messages.append(
            {
                "role": "tool",
                "name": "list_objects",
                "content": f"Result {i}",
                "tool_call_id": tc_id,
            }
        )
    return messages


def _make_plain_messages(n: int) -> list[dict]:
    """Alternate user/assistant messages totalling ``n`` non-system messages."""
    messages: list[dict] = [{"role": "system", "content": "Instructions."}]
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        messages.append({"role": role, "content": f"Message {i}"})
    return messages


def _fake_llm_with_summary(summary_text: str, token_count: int = 50) -> LLMClient:
    """Return a mock LLMClient that always reports ``token_count`` tokens and
    returns ``summary_text`` from acompletion."""
    client = MagicMock(spec=LLMClient)
    client.model = "openai/gpt-4o-mini"
    client.count_tokens = MagicMock(return_value=token_count)
    client.context_window = MagicMock(return_value=100)  # tiny window → always over threshold
    result = LLMResult(
        text=summary_text,
        tool_calls=None,
        finish_reason="stop",
        tokens_in=10,
        tokens_out=20,
        cost_usd=None,
        raw=MagicMock(),
    )
    client.acompletion = AsyncMock(return_value=result)
    return client


# ---------------------------------------------------------------------------
# Parametrized tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", GOLDEN, ids=lambda c: c["id"])
@pytest.mark.asyncio
async def test_compaction_case(case: dict) -> None:
    current_stage: int = case["current_stage"]
    threshold: float = case["threshold_fraction"]
    expected_stage_applied: int = case["expected_stage_applied"]
    expected_strategy: str | None = case.get("expected_strategy")
    fake_summary: str = case.get("fake_summary", "summary text")

    # Build messages based on case spec.
    if case.get("big_content_placeholder"):
        messages = _make_messages_with_big_tool_result(case["big_content_char_count"])
    elif case.get("num_turn_pairs"):
        messages = _make_many_turn_messages(case["num_turn_pairs"])
    else:
        messages = _make_plain_messages(case.get("num_messages", 6))

    # Build LLM mock
    llm = _fake_llm_with_summary(fake_summary)

    cm = ContextManager(
        threshold=threshold,
        tool_result_trim_threshold_tokens=2000,
        summarizer_model_override=None,
    )
    meta = _make_call_meta()

    result = await cm.maybe_compact(
        messages,
        llm=llm,
        current_stage=current_stage,
        call_metadata=meta,
    )

    assert result.stage_applied == expected_stage_applied, (
        f"[{case['id']}] stage_applied: expected {expected_stage_applied},"
        f" got {result.stage_applied}"
    )
    assert result.strategy_name == expected_strategy, (
        f"[{case['id']}] strategy_name: expected {expected_strategy!r},"
        f" got {result.strategy_name!r}"
    )

    compacted = result.compacted_messages

    if case.get("assert_placeholder_in_tool_messages"):
        tool_msgs = [m for m in compacted if m.get("role") == "tool"]
        truncated = [
            m for m in tool_msgs if (m.get("content") or "").startswith("<truncated:")
        ]
        assert len(truncated) >= 1, (
            f"[{case['id']}] Expected at least one truncated tool result, "
            f"got tool messages: {[m.get('content', '')[:60] for m in tool_msgs]}"
        )

    if case.get("assert_sentinel_in_old_tool_messages"):
        tool_msgs = [m for m in compacted if m.get("role") == "tool"]
        sentinel_msgs = [
            m for m in tool_msgs if m.get("content") == DROPPED_TOOL_RESULT_PLACEHOLDER
        ]
        assert len(sentinel_msgs) >= 1, (
            f"[{case['id']}] Expected at least one sentinel tool message, "
            f"found content: {[m.get('content', '')[:60] for m in tool_msgs]}"
        )

    if case.get("assert_summary_message"):
        summary_msgs = [
            m for m in compacted
            if m.get("role") == "system"
            and "Earlier in this session" in (m.get("content") or "")
        ]
        sys_previews = [
            m.get("content", "")[:60]
            for m in compacted
            if m.get("role") == "system"
        ]
        assert len(summary_msgs) >= 1, (
            f"[{case['id']}] Expected '## Earlier in this session' summary message,"
            f" got system messages: {sys_previews}"
        )

    if "assert_max_non_system" in case:
        max_ns = case["assert_max_non_system"]
        non_sys = [m for m in compacted if m.get("role") != "system"]
        assert len(non_sys) <= max_ns, (
            f"[{case['id']}] Expected <= {max_ns} non-system messages, got {len(non_sys)}"
        )
