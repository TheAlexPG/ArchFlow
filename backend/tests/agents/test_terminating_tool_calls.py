"""Tests for the ``terminating_tool_names`` knob on :class:`NodeConfig`.

Once a terminating tool's reply has been appended, ``run_react`` must exit
without making another LLM call. The supervisor node uses this for delegation
tools (``delegate_to_*``) and ``finalize`` so the post-tool turn happens on
the *next* graph visit (after sub-agent results land in state) instead of
being immediately re-prompted with stale context.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.context_manager import CompactionResult
from app.agents.llm import LLMCallMetadata, LLMResult
from app.agents.nodes.base import NodeConfig, NodeStreamEvent, run_react


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
    text: str | None = None,
    tool_calls: list[dict] | None = None,
    finish_reason: str = "tool_calls",
) -> LLMResult:
    return LLMResult(
        text=text,
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        tokens_in=10,
        tokens_out=10,
        cost_usd=Decimal("0.001"),
        raw=MagicMock(),
    )


def _make_enforcer(completion_results: list[LLMResult]) -> MagicMock:
    enforcer = MagicMock()
    enforcer.llm = MagicMock()
    enforcer.llm.model = "openai/gpt-4o-mini"
    enforcer.limits = MagicMock()
    enforcer.limits.budget_scope = "per_invocation"
    enforcer.acompletion = AsyncMock(side_effect=completion_results)
    enforcer.consume_budget_warning = MagicMock(return_value=None)
    return enforcer


def _make_context_manager() -> MagicMock:
    cm = MagicMock()

    async def _maybe_compact(messages, **kwargs):
        return CompactionResult(
            compacted_messages=messages,
            stage_applied=0,
            strategy_name=None,
            tokens_before=100,
            tokens_after=100,
        )

    cm.maybe_compact = AsyncMock(side_effect=_maybe_compact)
    return cm


def _make_executor(
    canned: dict[str, dict] | None = None,
) -> Callable[[dict, dict], Awaitable[dict]]:
    """Return-by-tool-name executor."""
    canned = canned or {}

    async def _executor(tool_call: dict, state: dict) -> dict:
        name = tool_call.get("name") or ""
        reply = canned.get(name) or {
            "tool_call_id": tool_call.get("id") or "",
            "status": "ok",
            "content": "{}",
            "preview": "ok",
        }
        return reply

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


async def _collect(gen) -> list[NodeStreamEvent]:
    return [ev async for ev in gen]


@pytest.mark.asyncio
async def test_terminating_tool_call_exits_loop_without_second_llm_call():
    """A tool call whose name is in ``cfg.terminating_tool_names`` must exit
    the ReAct loop immediately after the tool reply is appended — no second
    LLM round-trip."""
    delegate_call = {
        "id": "call_d",
        "name": "delegate_to_researcher",
        "arguments": json.dumps({"question": "?"}),
    }
    enforcer = _make_enforcer(
        completion_results=[
            _make_llm_result(text=None, tool_calls=[delegate_call]),
            # If run_react incorrectly re-prompted, it would consume this:
            _make_llm_result(text="I should never be sent", tool_calls=None),
        ]
    )
    cm = _make_context_manager()
    executor = _make_executor(
        canned={
            "delegate_to_researcher": {
                "tool_call_id": "call_d",
                "status": "ok",
                "content": json.dumps(
                    {"action": "delegate.researcher", "question": "?"}
                ),
                "preview": "delegated",
            }
        }
    )
    cfg = NodeConfig(
        name="supervisor",
        system_prompt="ROOT",
        tools=[{"name": "delegate_to_researcher"}],
        tool_executor=executor,
        max_steps=8,
        terminating_tool_names={"delegate_to_researcher"},
    )
    state = _make_state(messages=[{"role": "user", "content": "explain X"}])

    events = await _collect(
        run_react(
            state,
            cfg,
            enforcer=enforcer,
            context_manager=cm,
            call_metadata_base=_make_call_meta(),
        )
    )

    finished = [ev for ev in events if ev.kind == "finished"]
    assert len(finished) == 1
    output = finished[0].payload["output"]

    # The tool was executed exactly once.
    assert output.tool_calls_made == 1
    # And the LLM was called exactly once — no second round-trip after the
    # terminating tool. This is the load-bearing assertion.
    assert enforcer.acompletion.await_count == 1
    # Output text must be None so the supervisor adapter does NOT promote
    # any pre-tool assistant filler into final_message.
    assert output.text is None
    # The tool reply lands in messages so the LangGraph router can pick it up.
    tool_msgs = [m for m in output.state_patch["messages"] if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_call_id"] == "call_d"


@pytest.mark.asyncio
async def test_non_terminating_tool_call_continues_loop_as_before():
    """Sanity check: a tool not listed in ``terminating_tool_names`` keeps
    the prior behaviour of looping back for another LLM turn."""
    tool_call = {
        "id": "call_r",
        "name": "read_diagram",
        "arguments": json.dumps({"diagram_id": "d-1"}),
    }
    enforcer = _make_enforcer(
        completion_results=[
            _make_llm_result(text=None, tool_calls=[tool_call]),
            _make_llm_result(text="2 nodes", tool_calls=None),
        ]
    )
    cm = _make_context_manager()
    executor = _make_executor()
    cfg = NodeConfig(
        name="supervisor",
        system_prompt="ROOT",
        tools=[{"name": "read_diagram"}],
        tool_executor=executor,
        max_steps=8,
        terminating_tool_names={"delegate_to_researcher"},  # not the called tool
    )
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

    finished = [ev for ev in events if ev.kind == "finished"]
    output = finished[0].payload["output"]
    # Both LLM calls were made.
    assert enforcer.acompletion.await_count == 2
    assert output.text == "2 nodes"
    assert output.tool_calls_made == 1
