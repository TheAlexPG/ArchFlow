"""Tests for app/agents/nodes/base.py.

We mock LimitsEnforcer + ContextManager + tool_executor and drive run_react
with a FakeLLM that returns scripted LLMResults. The enforcer's pre-flight
and post-call accounting are exercised by tests/test_limits.py — here we
treat enforcer.acompletion as a thin pipe whose side-effects we control via
the LimitsEnforcer mock.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import BaseModel

from app.agents.context_manager import CompactionResult
from app.agents.errors import BudgetExhausted, ContextOverflow, TurnLimitReached
from app.agents.llm import LLMCallMetadata, LLMResult
from app.agents.nodes.base import (
    NodeConfig,
    NodeOutput,
    NodeStreamEvent,
    compose_messages_for_llm,
    run_react,
)

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


def _make_llm_result(
    *,
    text: str | None = "ok",
    tool_calls: list[dict] | None = None,
    finish_reason: str = "stop",
    cost_usd: Decimal | None = Decimal("0.001"),
) -> LLMResult:
    return LLMResult(
        text=text,
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        tokens_in=10,
        tokens_out=10,
        cost_usd=cost_usd,
        raw=MagicMock(),
    )


def _make_enforcer(
    *,
    completion_results: list[LLMResult] | None = None,
    completion_side_effect: list[Any] | None = None,
    budget_warning: tuple[Decimal, Decimal] | None = None,
) -> MagicMock:
    """Build a LimitsEnforcer mock.

    ``completion_side_effect`` lets a test mix raw LLMResults with exceptions.
    ``completion_results`` is the simpler form when no exceptions are needed.
    """
    enforcer = MagicMock()
    enforcer.llm = MagicMock()
    enforcer.llm.model = "openai/gpt-4o-mini"
    enforcer.limits = MagicMock()
    enforcer.limits.budget_scope = "per_invocation"

    if completion_side_effect is not None:
        enforcer.acompletion = AsyncMock(side_effect=completion_side_effect)
    elif completion_results is not None:
        enforcer.acompletion = AsyncMock(side_effect=completion_results)
    else:
        enforcer.acompletion = AsyncMock(return_value=_make_llm_result())

    # Default: no warning. Test can override by setting consume_budget_warning.
    warning_iter = iter([budget_warning, None, None, None, None, None])
    enforcer.consume_budget_warning = MagicMock(side_effect=lambda: next(warning_iter, None))
    return enforcer


def _make_context_manager(
    *,
    stages_to_apply: list[int] | None = None,
    raise_overflow_at: int | None = None,
) -> MagicMock:
    """Build a ContextManager mock.

    ``stages_to_apply`` — list aligned with maybe_compact call ordinal: ``0``
    means no-op for that step, a positive int means "stage N applied".
    ``raise_overflow_at`` — index at which maybe_compact raises ContextOverflow.
    """
    cm = MagicMock()
    call_index = {"i": 0}
    stages = list(stages_to_apply or [])

    async def _maybe_compact(messages, **kwargs):
        idx = call_index["i"]
        call_index["i"] += 1
        if raise_overflow_at is not None and idx == raise_overflow_at:
            raise ContextOverflow("simulated overflow")
        stage = stages[idx] if idx < len(stages) else 0
        return CompactionResult(
            compacted_messages=messages,
            stage_applied=stage,
            strategy_name=("trim_large_tool_results" if stage > 0 else None),
            tokens_before=100,
            tokens_after=80 if stage > 0 else 100,
        )

    cm.maybe_compact = AsyncMock(side_effect=_maybe_compact)
    return cm


def _make_tool_executor(
    results: list[dict] | None = None,
) -> Callable[[dict, dict], Awaitable[dict]]:
    """Build a tool_executor that returns scripted ToolExecutionResults."""
    queue = list(results or [])

    async def _executor(tool_call: dict, state: dict) -> dict:
        if queue:
            return queue.pop(0)
        return {
            "tool_call_id": tool_call.get("id") or "",
            "status": "ok",
            "content": "default-tool-content",
            "preview": "ok",
        }

    return _executor


def _make_state(messages: list[dict] | None = None) -> dict:
    return {
        "workspace_id": uuid4(),
        "session_id": uuid4(),
        "messages": list(messages or []),
        "iteration": 0,
        "tokens_in": 0,
        "tokens_out": 0,
    }


def _make_cfg(
    *,
    name: str = "test-node",
    system_prompt: str = "You are a test agent.",
    tools: list[dict] | None = None,
    tool_executor: Callable | None = None,
    max_steps: int = 8,
    output_schema: type[BaseModel] | None = None,
    enable_streaming: bool = False,
    additional_system_blocks: list[Callable] | None = None,
) -> NodeConfig:
    return NodeConfig(
        name=name,
        system_prompt=system_prompt,
        tools=tools or [],
        tool_executor=tool_executor or _make_tool_executor(),
        max_steps=max_steps,
        output_schema=output_schema,
        enable_streaming=enable_streaming,
        additional_system_blocks=additional_system_blocks or [],
    )


async def _collect(gen) -> list[NodeStreamEvent]:
    return [ev async for ev in gen]


def _terminal_output(events: list[NodeStreamEvent]) -> NodeOutput:
    finished = [ev for ev in events if ev.kind == "finished"]
    assert len(finished) == 1, f"expected exactly one 'finished' event, got {len(finished)}"
    return finished[0].payload["output"]


# ---------------------------------------------------------------------------
# compose_messages_for_llm
# ---------------------------------------------------------------------------


def test_compose_messages_includes_system_then_history():
    cfg = _make_cfg(system_prompt="ROOT")
    state = _make_state(
        messages=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
    )
    out = compose_messages_for_llm(state, cfg)
    assert out[0] == {"role": "system", "content": "ROOT"}
    assert out[1]["role"] == "user"
    assert out[2]["role"] == "assistant"
    assert len(out) == 3


def test_compose_messages_renders_additional_system_blocks():
    def block_a(state: dict) -> str:
        return "## Scratchpad\nfoo"

    def block_b(state: dict) -> str:
        return "## Resources\nbar"

    cfg = _make_cfg(additional_system_blocks=[block_a, block_b])
    state = _make_state(messages=[{"role": "user", "content": "hi"}])
    out = compose_messages_for_llm(state, cfg)

    assert out[0]["role"] == "system"
    assert out[1] == {"role": "system", "content": "## Scratchpad\nfoo"}
    assert out[2] == {"role": "system", "content": "## Resources\nbar"}
    assert out[3]["role"] == "user"


def test_compose_messages_skips_compacted_messages():
    cfg = _make_cfg()
    state = _make_state(
        messages=[
            {"role": "user", "content": "old", "is_compacted": True},
            {"role": "assistant", "content": "old reply", "is_compacted": True},
            {"role": "user", "content": "current"},
        ]
    )
    out = compose_messages_for_llm(state, cfg)
    # Only system + the non-compacted user message survive.
    assert len(out) == 2
    assert out[1] == {"role": "user", "content": "current"}


def test_compose_messages_truncates_to_recent_history_limit():
    cfg = _make_cfg()
    history = [{"role": "user", "content": f"m{i}"} for i in range(30)]
    state = _make_state(messages=history)
    out = compose_messages_for_llm(state, cfg, recent_history_limit=5)
    # 1 system + 5 history.
    assert len(out) == 6
    assert out[1]["content"] == "m25"
    assert out[-1]["content"] == "m29"


# ---------------------------------------------------------------------------
# Happy path — no tools, single step
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_one_step_no_tools_returns_text():
    enforcer = _make_enforcer(
        completion_results=[_make_llm_result(text="final answer", tool_calls=None)]
    )
    cm = _make_context_manager()
    cfg = _make_cfg()
    state = _make_state(messages=[{"role": "user", "content": "hello"}])

    events = await _collect(
        run_react(
            state,
            cfg,
            enforcer=enforcer,
            context_manager=cm,
            call_metadata_base=_make_call_meta(),
        )
    )

    output = _terminal_output(events)
    assert output.text == "final answer"
    assert output.forced_finalize is None
    assert output.tool_calls_made == 0
    # Assistant turn appended to messages.
    assert any(m.get("role") == "assistant" and m.get("content") == "final answer"
               for m in output.state_patch["messages"])


# ---------------------------------------------------------------------------
# 2 steps with one tool call between
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_steps_with_one_tool_call_between():
    tool_call = {
        "id": "call_1",
        "name": "read_diagram",
        "arguments": json.dumps({"diagram_id": "d-1"}),
    }
    enforcer = _make_enforcer(
        completion_results=[
            _make_llm_result(text=None, tool_calls=[tool_call]),
            _make_llm_result(text="diagram has 2 nodes", tool_calls=None),
        ]
    )
    cm = _make_context_manager()
    executor = _make_tool_executor(
        results=[
            {
                "tool_call_id": "call_1",
                "status": "ok",
                "content": '{"nodes": 2}',
                "preview": "2 nodes",
            }
        ]
    )
    cfg = _make_cfg(tool_executor=executor, tools=[{"name": "read_diagram"}])
    state = _make_state(messages=[{"role": "user", "content": "explain"}])

    events = await _collect(
        run_react(
            state,
            cfg,
            enforcer=enforcer,
            context_manager=cm,
            call_metadata_base=_make_call_meta(),
        )
    )

    kinds = [ev.kind for ev in events]
    assert "tool_call" in kinds
    assert "tool_result" in kinds
    assert kinds[-1] == "finished"

    output = _terminal_output(events)
    assert output.text == "diagram has 2 nodes"
    assert output.tool_calls_made == 1

    # The tool reply must have landed in messages with the right tool_call_id.
    tool_msgs = [m for m in output.state_patch["messages"] if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_call_id"] == "call_1"
    assert tool_msgs[0]["content"] == '{"nodes": 2}'


# ---------------------------------------------------------------------------
# max_steps reached
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_steps_reached_emits_forced_finalize():
    # Every step asks for a tool call → we never hit a terminal LLM response.
    forever_tool_call = {
        "id": "call_x",
        "name": "noop",
        "arguments": "{}",
    }
    results = [
        _make_llm_result(text=None, tool_calls=[forever_tool_call]) for _ in range(20)
    ]
    enforcer = _make_enforcer(completion_results=results)
    cm = _make_context_manager()
    cfg = _make_cfg(max_steps=3, tools=[{"name": "noop"}])
    state = _make_state(messages=[{"role": "user", "content": "loop forever"}])

    events = await _collect(
        run_react(
            state,
            cfg,
            enforcer=enforcer,
            context_manager=cm,
            call_metadata_base=_make_call_meta(),
        )
    )

    forced = [ev for ev in events if ev.kind == "forced_finalize"]
    assert len(forced) == 1
    assert forced[0].payload["reason"] == "max_steps"

    output = _terminal_output(events)
    assert output.forced_finalize == "max_steps"
    assert output.tool_calls_made == 3
    # acompletion was called exactly max_steps times.
    assert enforcer.acompletion.await_count == 3


# ---------------------------------------------------------------------------
# BudgetExhausted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_exhausted_emits_forced_finalize_budget():
    enforcer = _make_enforcer(
        completion_side_effect=[BudgetExhausted("over budget")]
    )
    cm = _make_context_manager()
    cfg = _make_cfg()
    state = _make_state(messages=[{"role": "user", "content": "spend"}])

    events = await _collect(
        run_react(
            state,
            cfg,
            enforcer=enforcer,
            context_manager=cm,
            call_metadata_base=_make_call_meta(),
        )
    )

    forced = [ev for ev in events if ev.kind == "forced_finalize"]
    assert len(forced) == 1
    assert forced[0].payload["reason"] == "budget"
    output = _terminal_output(events)
    assert output.forced_finalize == "budget"


# ---------------------------------------------------------------------------
# TurnLimitReached
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_turn_limit_reached_emits_forced_finalize_turns():
    enforcer = _make_enforcer(
        completion_side_effect=[TurnLimitReached("too many turns")]
    )
    cm = _make_context_manager()
    cfg = _make_cfg()
    state = _make_state(messages=[{"role": "user", "content": "loop"}])

    events = await _collect(
        run_react(
            state,
            cfg,
            enforcer=enforcer,
            context_manager=cm,
            call_metadata_base=_make_call_meta(),
        )
    )

    forced = [ev for ev in events if ev.kind == "forced_finalize"]
    assert len(forced) == 1
    assert forced[0].payload["reason"] == "turns"
    output = _terminal_output(events)
    assert output.forced_finalize == "turns"


# ---------------------------------------------------------------------------
# ContextOverflow (raised by the LLM call)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_overflow_emits_forced_finalize_context_overflow():
    enforcer = _make_enforcer(
        completion_side_effect=[ContextOverflow("window blown")]
    )
    cm = _make_context_manager()
    cfg = _make_cfg()
    state = _make_state(messages=[{"role": "user", "content": "huge"}])

    events = await _collect(
        run_react(
            state,
            cfg,
            enforcer=enforcer,
            context_manager=cm,
            call_metadata_base=_make_call_meta(),
        )
    )

    forced = [ev for ev in events if ev.kind == "forced_finalize"]
    assert len(forced) == 1
    assert forced[0].payload["reason"] == "context_overflow"
    output = _terminal_output(events)
    assert output.forced_finalize == "context_overflow"


# ---------------------------------------------------------------------------
# Structured output: schema=PydanticModel, valid JSON
# ---------------------------------------------------------------------------


class _SamplePlan(BaseModel):
    goal: str
    steps: list[str]


@pytest.mark.asyncio
async def test_structured_output_valid_json_populates_structured():
    payload = {"goal": "build x", "steps": ["a", "b"]}
    enforcer = _make_enforcer(
        completion_results=[
            _make_llm_result(text=json.dumps(payload), tool_calls=None)
        ]
    )
    cm = _make_context_manager()
    cfg = _make_cfg(output_schema=_SamplePlan)
    state = _make_state(messages=[{"role": "user", "content": "plan"}])

    events = await _collect(
        run_react(
            state,
            cfg,
            enforcer=enforcer,
            context_manager=cm,
            call_metadata_base=_make_call_meta(),
        )
    )

    output = _terminal_output(events)
    assert output.structured is not None
    assert isinstance(output.structured, _SamplePlan)
    assert output.structured.goal == "build x"
    assert output.structured.steps == ["a", "b"]


@pytest.mark.asyncio
async def test_structured_output_valid_json_in_fenced_code_block():
    """JSON wrapped in ```json``` fences should still parse."""
    payload = {"goal": "ship", "steps": ["one"]}
    fenced = f"Here is the plan:\n```json\n{json.dumps(payload)}\n```"
    enforcer = _make_enforcer(
        completion_results=[_make_llm_result(text=fenced, tool_calls=None)]
    )
    cm = _make_context_manager()
    cfg = _make_cfg(output_schema=_SamplePlan)
    state = _make_state(messages=[{"role": "user", "content": "plan"}])

    events = await _collect(
        run_react(
            state,
            cfg,
            enforcer=enforcer,
            context_manager=cm,
            call_metadata_base=_make_call_meta(),
        )
    )

    output = _terminal_output(events)
    assert output.structured is not None
    assert output.structured.goal == "ship"


# ---------------------------------------------------------------------------
# Structured output: invalid JSON falls back to text + warning logged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_structured_output_invalid_json_keeps_text_and_logs_warning(caplog):
    enforcer = _make_enforcer(
        completion_results=[
            _make_llm_result(text="this is not JSON at all", tool_calls=None)
        ]
    )
    cm = _make_context_manager()
    cfg = _make_cfg(output_schema=_SamplePlan)
    state = _make_state(messages=[{"role": "user", "content": "plan"}])

    with caplog.at_level("WARNING", logger="app.agents.nodes.base"):
        events = await _collect(
            run_react(
                state,
                cfg,
                enforcer=enforcer,
                context_manager=cm,
                call_metadata_base=_make_call_meta(),
            )
        )

    output = _terminal_output(events)
    assert output.text == "this is not JSON at all"
    assert output.structured is None
    assert any("structured output parse failed" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# Compaction event emission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compaction_event_yielded_when_stage_applied():
    enforcer = _make_enforcer(
        completion_results=[_make_llm_result(text="done", tool_calls=None)]
    )
    cm = _make_context_manager(stages_to_apply=[2])  # stage 2 applied on first call
    cfg = _make_cfg()
    state = _make_state(messages=[{"role": "user", "content": "long"}])

    events = await _collect(
        run_react(
            state,
            cfg,
            enforcer=enforcer,
            context_manager=cm,
            call_metadata_base=_make_call_meta(),
            current_compaction_stage=1,
        )
    )

    compactions = [ev for ev in events if ev.kind == "compaction_applied"]
    assert len(compactions) == 1
    assert compactions[0].payload["stage"] == 2
    assert compactions[0].payload["strategy"] == "trim_large_tool_results"

    output = _terminal_output(events)
    # state_patch surfaces the new stage so the runtime can persist.
    assert output.state_patch["compaction_stage"] == 2


# ---------------------------------------------------------------------------
# Tool executor returns error → tool_result event has status='error', loop continues
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_executor_error_continues_loop():
    tool_call = {"id": "call_err", "name": "broken", "arguments": "{}"}
    enforcer = _make_enforcer(
        completion_results=[
            _make_llm_result(text=None, tool_calls=[tool_call]),
            _make_llm_result(text="recovered", tool_calls=None),
        ]
    )
    cm = _make_context_manager()
    executor = _make_tool_executor(
        results=[
            {
                "tool_call_id": "call_err",
                "status": "error",
                "content": "tool blew up",
                "preview": "error",
            }
        ]
    )
    cfg = _make_cfg(tool_executor=executor, tools=[{"name": "broken"}])
    state = _make_state(messages=[{"role": "user", "content": "try"}])

    events = await _collect(
        run_react(
            state,
            cfg,
            enforcer=enforcer,
            context_manager=cm,
            call_metadata_base=_make_call_meta(),
        )
    )

    tool_results = [ev for ev in events if ev.kind == "tool_result"]
    assert len(tool_results) == 1
    assert tool_results[0].payload["status"] == "error"

    output = _terminal_output(events)
    # Loop continued: we got terminal text on step 2.
    assert output.text == "recovered"
    assert output.forced_finalize is None
    assert output.tool_calls_made == 1
    # The tool reply with status=error landed in messages with content carried through.
    tool_msgs = [m for m in output.state_patch["messages"] if m.get("role") == "tool"]
    assert tool_msgs[0]["content"] == "tool blew up"


# ---------------------------------------------------------------------------
# Budget warning latch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_warning_event_emitted_when_latch_pending():
    enforcer = _make_enforcer(
        completion_results=[_make_llm_result(text="done", tool_calls=None)],
        budget_warning=(Decimal("0.85"), Decimal("1.00")),
    )
    cm = _make_context_manager()
    cfg = _make_cfg()
    state = _make_state(messages=[{"role": "user", "content": "spend"}])

    events = await _collect(
        run_react(
            state,
            cfg,
            enforcer=enforcer,
            context_manager=cm,
            call_metadata_base=_make_call_meta(),
        )
    )

    warnings = [ev for ev in events if ev.kind == "budget_warning"]
    assert len(warnings) == 1
    assert warnings[0].payload["used_usd"] == Decimal("0.85")
    assert warnings[0].payload["limit_usd"] == Decimal("1.00")
    assert warnings[0].payload["scope"] == "per_invocation"


# ---------------------------------------------------------------------------
# additional_system_blocks rendered in messages passed to enforcer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_additional_system_blocks_passed_to_llm():
    captured: dict[str, Any] = {}

    async def _capture_messages(messages, **kwargs):
        captured["messages"] = list(messages)
        return _make_llm_result(text="ok", tool_calls=None)

    enforcer = _make_enforcer()
    enforcer.acompletion = AsyncMock(side_effect=_capture_messages)
    cm = _make_context_manager()

    def render_pad(state: dict) -> str:
        return "## Scratchpad\nremember X"

    cfg = _make_cfg(
        system_prompt="ROOT PROMPT",
        additional_system_blocks=[render_pad],
    )
    state = _make_state(messages=[{"role": "user", "content": "hi"}])

    await _collect(
        run_react(
            state,
            cfg,
            enforcer=enforcer,
            context_manager=cm,
            call_metadata_base=_make_call_meta(),
        )
    )

    msgs = captured["messages"]
    assert msgs[0] == {"role": "system", "content": "ROOT PROMPT"}
    assert msgs[1] == {"role": "system", "content": "## Scratchpad\nremember X"}
    assert msgs[2] == {"role": "user", "content": "hi"}


# ---------------------------------------------------------------------------
# ContextOverflow raised by ContextManager (compaction itself overflows)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_overflow_during_compaction_emits_forced_finalize():
    enforcer = _make_enforcer(
        completion_results=[_make_llm_result(text="never reached")]
    )
    cm = _make_context_manager(raise_overflow_at=0)
    cfg = _make_cfg()
    state = _make_state(messages=[{"role": "user", "content": "huge"}])

    events = await _collect(
        run_react(
            state,
            cfg,
            enforcer=enforcer,
            context_manager=cm,
            call_metadata_base=_make_call_meta(),
        )
    )

    forced = [ev for ev in events if ev.kind == "forced_finalize"]
    assert len(forced) == 1
    assert forced[0].payload["reason"] == "context_overflow"
    # LLM was never called.
    assert enforcer.acompletion.await_count == 0


# ---------------------------------------------------------------------------
# Streaming token event surface
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_streaming_mode_emits_token_event_with_full_text():
    enforcer = _make_enforcer(
        completion_results=[_make_llm_result(text="streamed answer", tool_calls=None)]
    )
    cm = _make_context_manager()
    cfg = _make_cfg(enable_streaming=True)
    state = _make_state(messages=[{"role": "user", "content": "hi"}])

    events = await _collect(
        run_react(
            state,
            cfg,
            enforcer=enforcer,
            context_manager=cm,
            call_metadata_base=_make_call_meta(),
        )
    )

    tokens = [ev for ev in events if ev.kind == "token"]
    assert len(tokens) == 1
    assert tokens[0].payload["delta"] == "streamed answer"


@pytest.mark.asyncio
async def test_non_streaming_mode_emits_no_token_events():
    enforcer = _make_enforcer(
        completion_results=[_make_llm_result(text="quiet answer", tool_calls=None)]
    )
    cm = _make_context_manager()
    cfg = _make_cfg(enable_streaming=False)
    state = _make_state(messages=[{"role": "user", "content": "hi"}])

    events = await _collect(
        run_react(
            state,
            cfg,
            enforcer=enforcer,
            context_manager=cm,
            call_metadata_base=_make_call_meta(),
        )
    )

    tokens = [ev for ev in events if ev.kind == "token"]
    assert tokens == []
