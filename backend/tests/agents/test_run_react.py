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
    isolated_state_for_subagent,
    rewrite_subagent_tool_result,
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


def test_compose_messages_truncates_but_keeps_first_user_message():
    """When trimming, the first user message is always kept on top of the
    tail. For sub-agents this carries the supervisor brief — without it the
    LLM template fails with "No user query found in messages"."""
    cfg = _make_cfg()
    history = [{"role": "user", "content": f"m{i}"} for i in range(30)]
    state = _make_state(messages=history)
    out = compose_messages_for_llm(state, cfg, recent_history_limit=5)
    # 1 system + first-user (m0) + 5 tail (m25..m29) = 7 items.
    assert len(out) == 7
    assert out[1]["content"] == "m0"  # first user message preserved
    assert out[2]["content"] == "m25"
    assert out[-1]["content"] == "m29"


def _supervisor_history_with_delegate(
    *, kind: str, call_id: str = "call-1", question: str = "Find Redis"
) -> list[dict]:
    """Build a minimal supervisor history showing one delegate_to_<kind> call
    plus its echo-shaped tool result."""
    return [
        {"role": "user", "content": "describe diagram"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": f"delegate_to_{kind}",
                        "arguments": f'{{"question": "{question}"}}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": call_id,
            "content": '{"action": "delegate.researcher", "question": "..."}',
        },
    ]


def test_rewrite_subagent_tool_result_findings_replaces_echo_content():
    """After researcher returns, the supervisor's matching tool message must
    carry the actual findings.summary — not the echo of its own input."""
    history = _supervisor_history_with_delegate(kind="researcher")
    findings = {"summary": "Redis exists at id `r-1`.", "confidence": "high"}

    out = rewrite_subagent_tool_result(history, kind="researcher", findings=findings)

    # The history is intact except the tool message at index 2.
    assert len(out) == 3
    assert out[0] is history[0]
    assert out[1] is history[1]
    tool_msg = out[2]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "call-1"
    assert "Redis exists at id `r-1`." in tool_msg["content"]
    assert "confidence: high" in tool_msg["content"]
    # Original list isn't mutated in place.
    assert history[2]["content"].startswith('{"action"')


def test_rewrite_subagent_tool_result_applied_changes_renders_list():
    history = _supervisor_history_with_delegate(kind="diagram")
    applied = [
        {"action": "object.created", "name": "Redis", "target_id": "obj-1"},
        {"action": "object.placed", "name": "Redis"},
    ]
    out = rewrite_subagent_tool_result(
        history, kind="diagram", applied_changes=applied
    )
    body = out[2]["content"]
    assert "Applied changes (2 total)" in body
    assert "object.created" in body
    assert "obj-1" in body


def test_rewrite_subagent_tool_result_no_matching_call_is_noop():
    """Without a delegate_to_planner in history, requesting a planner rewrite
    must return the input unchanged."""
    history = _supervisor_history_with_delegate(kind="researcher")
    plan = {"goal": "noop", "steps": []}
    out = rewrite_subagent_tool_result(history, kind="planner", plan=plan)
    # Identical content — no rewrite happened.
    assert [m.get("content") for m in out] == [
        m.get("content") for m in history
    ]


def test_rewrite_subagent_tool_result_no_artefact_is_noop():
    history = _supervisor_history_with_delegate(kind="researcher")
    out = rewrite_subagent_tool_result(history, kind="researcher")
    assert out == history


def _state_with_user_and_brief() -> dict:
    return {
        "messages": [
            {"role": "user", "content": "BIG VAGUE USER REQUEST IN UKRAINIAN"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "x", "function": {"name": "delegate_to_researcher",
                                          "arguments": "{}"}}
            ]},
        ],
        "delegate_brief": {
            "kind": "researcher",
            "instruction": "List objects on diagram d-1.",
            "reason": None,
        },
    }


def test_isolated_state_omits_user_request_by_default():
    """Default path strips the original user message — the sub-agent gets
    only the supervisor's distilled brief."""
    state = _state_with_user_and_brief()
    iso = isolated_state_for_subagent(state)
    msgs = iso["messages"]
    assert len(msgs) == 1
    body = msgs[0]["content"]
    assert "BIG VAGUE USER REQUEST" not in body
    assert "Original user request" not in body
    assert "List objects on diagram d-1." in body
    assert "## Your specific task" in body


def test_isolated_state_includes_user_request_when_opted_in():
    """Critic-style path opts in via include_original_request=True."""
    state = _state_with_user_and_brief()
    iso = isolated_state_for_subagent(state, include_original_request=True)
    body = iso["messages"][0]["content"]
    assert "BIG VAGUE USER REQUEST" in body
    assert "## Original user request" in body
    assert "## Your specific task" in body


def test_compose_messages_skips_first_user_prepend_when_tail_includes_it():
    """If the tail already covers the first user message we shouldn't
    duplicate it on top — only prepend when truly trimmed away."""
    cfg = _make_cfg()
    history = [
        {"role": "user", "content": "u0"},
        {"role": "assistant", "content": "a"},
        {"role": "tool", "tool_call_id": "x", "content": "{}"},
    ]
    state = _make_state(messages=history)
    out = compose_messages_for_llm(state, cfg, recent_history_limit=5)
    # 1 system + 3 history (no trim, no duplication).
    assert len(out) == 4
    assert out[1]["content"] == "u0"


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
# Per-tool commit + asyncio.Lock serialisation
# ---------------------------------------------------------------------------


class _RecordingSession:
    """Stand-in for AsyncSession that records commit ordering & lock state."""

    def __init__(self, lock) -> None:
        self.lock = lock
        self.commit_count = 0
        # Whether the lock was held by SOMEONE while each commit ran.  We
        # check ``lock.locked()``: holding the lock from inside the same
        # coroutine still counts as "held" so this proves the per-tool
        # commit acquired the lock for its critical section.
        self.lock_held_during_commit: list[bool] = []

    async def commit(self) -> None:
        self.commit_count += 1
        self.lock_held_during_commit.append(self.lock.locked())


@pytest.mark.asyncio
async def test_per_tool_commit_runs_under_db_lock():
    """When ``enforcer.db_lock`` is set, the per-tool commit at base.py:1175
    must hold the lock across ``await db.commit()``. Without this, a
    concurrent path that briefly touches the same session can trip
    asyncpg's "concurrent operations are not permitted" error and leave
    the session in an aborted state — manifesting downstream as a spurious
    FK violation on the next mutating tool call."""
    import asyncio

    lock = asyncio.Lock()
    db = _RecordingSession(lock)

    tool_call = {"id": "call_1", "name": "create_object", "arguments": "{}"}
    enforcer = _make_enforcer(
        completion_results=[
            _make_llm_result(text=None, tool_calls=[tool_call]),
            _make_llm_result(text="done", tool_calls=None),
        ]
    )
    enforcer.db = db
    enforcer.db_lock = lock
    cm = _make_context_manager()
    executor = _make_tool_executor(
        results=[
            {
                "tool_call_id": "call_1",
                "status": "ok",
                "content": "ok",
                "preview": "ok",
            }
        ]
    )
    cfg = _make_cfg(tool_executor=executor, tools=[{"name": "create_object"}])
    state = _make_state(messages=[{"role": "user", "content": "create one"}])

    await _collect(
        run_react(
            state,
            cfg,
            enforcer=enforcer,
            context_manager=cm,
            call_metadata_base=_make_call_meta(),
        )
    )

    # One commit happened (one ok tool call) and the lock was held during
    # that commit — i.e. the new code path is engaged, not the unlocked
    # legacy fallback.
    assert db.commit_count == 1
    assert db.lock_held_during_commit == [True]
    # Lock released back after the commit completes.
    assert not lock.locked()


@pytest.mark.asyncio
async def test_per_tool_commit_skipped_when_no_lock_attribute():
    """Defensive: when ``enforcer`` has no ``db_lock`` (older callers /
    test stubs), the commit still runs unguarded — no AttributeError."""
    import asyncio  # noqa: F401 — used by the recording session

    class _BareSession:
        def __init__(self) -> None:
            self.commit_count = 0

        async def commit(self) -> None:
            self.commit_count += 1

    db = _BareSession()

    tool_call = {"id": "call_x", "name": "create_object", "arguments": "{}"}
    enforcer = _make_enforcer(
        completion_results=[
            _make_llm_result(text=None, tool_calls=[tool_call]),
            _make_llm_result(text="done", tool_calls=None),
        ]
    )
    enforcer.db = db
    # Explicitly DELETE db_lock so getattr returns None — proves the legacy
    # path still works.
    if hasattr(enforcer, "db_lock"):
        del enforcer.db_lock
    cm = _make_context_manager()
    executor = _make_tool_executor(
        results=[
            {
                "tool_call_id": "call_x",
                "status": "ok",
                "content": "ok",
                "preview": "ok",
            }
        ]
    )
    cfg = _make_cfg(tool_executor=executor, tools=[{"name": "create_object"}])
    state = _make_state(messages=[{"role": "user", "content": "create one"}])

    await _collect(
        run_react(
            state,
            cfg,
            enforcer=enforcer,
            context_manager=cm,
            call_metadata_base=_make_call_meta(),
        )
    )
    assert db.commit_count == 1


@pytest.mark.asyncio
async def test_per_tool_commit_lock_serialises_concurrent_db_user():
    """End-to-end repro: while the per-tool commit is mid-await, a parallel
    coroutine that needs ``db`` must wait until the commit releases the
    lock. Without the lock, a real asyncpg session would raise "concurrent
    operations are not permitted" and corrupt the session state."""
    import asyncio

    lock = asyncio.Lock()
    sequence: list[str] = []

    class _SequencingSession:
        async def commit(self) -> None:
            sequence.append("commit-enter")
            # Simulate the asyncpg ``await self.connection.execute("COMMIT")``
            # round-trip — yields control to the loop.
            await asyncio.sleep(0)
            sequence.append("commit-exit")

        async def execute(self, *_a, **_kw):
            sequence.append("execute")

    db = _SequencingSession()

    async def _competitor():
        # Wait until the commit is in-flight, then attempt to use the
        # session. The lock must force this to queue up after the commit.
        while "commit-enter" not in sequence:
            await asyncio.sleep(0)
        async with lock:
            await db.execute("SELECT 1")

    tool_call = {"id": "call_z", "name": "create_object", "arguments": "{}"}
    enforcer = _make_enforcer(
        completion_results=[
            _make_llm_result(text=None, tool_calls=[tool_call]),
            _make_llm_result(text="done", tool_calls=None),
        ]
    )
    enforcer.db = db
    enforcer.db_lock = lock
    cm = _make_context_manager()
    executor = _make_tool_executor(
        results=[
            {
                "tool_call_id": "call_z",
                "status": "ok",
                "content": "ok",
                "preview": "ok",
            }
        ]
    )
    cfg = _make_cfg(tool_executor=executor, tools=[{"name": "create_object"}])
    state = _make_state(messages=[{"role": "user", "content": "x"}])

    competitor_task = asyncio.create_task(_competitor())
    try:
        await _collect(
            run_react(
                state,
                cfg,
                enforcer=enforcer,
                context_manager=cm,
                call_metadata_base=_make_call_meta(),
            )
        )
    finally:
        await asyncio.wait_for(competitor_task, timeout=1.0)

    # The competitor's execute() must come AFTER commit-exit — proves the
    # lock serialised them. Without the lock you'd see ``execute`` appear
    # between commit-enter and commit-exit.
    assert sequence.index("commit-exit") < sequence.index("execute")


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
