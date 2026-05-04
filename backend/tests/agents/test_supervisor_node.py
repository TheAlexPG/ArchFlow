"""Tests for the supervisor node (app/agents/builtin/general/nodes/supervisor.py).

These follow the FakeLLM/stub patterns from test_run_react.py. We mock
LimitsEnforcer + ContextManager + tool_executor and drive run() with scripted
LLMResults. The point of this file is to assert:

  * the system-block renderers produce the expected markdown shapes,
  * make_supervisor_config wires the right knobs,
  * scratchpad writes survive into the NodeOutput state_patch,
  * delegation tool calls land in the message history (so the runtime can
    read them to make routing decisions).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.builtin.general.nodes.supervisor import (
    SUPERVISOR_TOOLS,
    load_supervisor_prompt,
    make_supervisor_config,
    render_applied_changes_block,
    render_resources_block,
    render_scratchpad_block,
    run,
)
from app.agents.context_manager import CompactionResult
from app.agents.llm import LLMCallMetadata, LLMResult
from app.agents.nodes.base import NodeOutput, NodeStreamEvent

# ---------------------------------------------------------------------------
# Shared fixtures
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


def _make_enforcer(
    completion_results: list[LLMResult] | None = None,
) -> MagicMock:
    enforcer = MagicMock()
    enforcer.llm = MagicMock()
    enforcer.llm.model = "openai/gpt-4o-mini"
    enforcer.limits = MagicMock()
    enforcer.limits.budget_scope = "per_invocation"
    enforcer.acompletion = AsyncMock(
        side_effect=completion_results or [_make_llm_result()]
    )
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
    results: list[dict] | None = None,
) -> Callable[[dict, dict], Awaitable[dict]]:
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


def _make_state(**overrides: Any) -> dict:
    base: dict[str, Any] = {
        "workspace_id": uuid4(),
        "session_id": uuid4(),
        "messages": [{"role": "user", "content": "hi"}],
        "iteration": 0,
        "tokens_in": 0,
        "tokens_out": 0,
    }
    base.update(overrides)
    return base


async def _collect(gen) -> list[NodeStreamEvent]:
    return [ev async for ev in gen]


def _terminal_output(events: list[NodeStreamEvent]) -> NodeOutput:
    finished = [ev for ev in events if ev.kind == "finished"]
    assert len(finished) == 1
    return finished[0].payload["output"]


# ---------------------------------------------------------------------------
# render_scratchpad_block
# ---------------------------------------------------------------------------


def test_render_scratchpad_block_empty_state():
    state = _make_state()
    out = render_scratchpad_block(state)
    assert out == "## Scratchpad\n_(empty)_"


def test_render_scratchpad_block_with_content():
    state = _make_state(scratchpad="- [ ] task A\n- [x] task B")
    out = render_scratchpad_block(state)
    assert out.startswith("## Scratchpad\n")
    assert "task A" in out
    assert "task B" in out
    assert "_(empty)_" not in out


# ---------------------------------------------------------------------------
# render_resources_block
# ---------------------------------------------------------------------------


def test_render_resources_block_with_budget_counters():
    state = _make_state(
        budget_counters={
            "general": {"cost_usd": Decimal("0.0341"), "turns_used": 7},
            "planner": {"cost_usd": Decimal("0.0102"), "turns_used": 3},
        }
    )
    out = render_resources_block(state)
    assert "## Resources" in out
    assert "general" in out
    assert "planner" in out
    assert "0.0341" in out
    assert "turns=7" in out


def test_render_resources_block_read_only_mode_signals_in_text():
    state = _make_state(runtime_mode="read_only")
    out = render_resources_block(state)
    assert "read-only" in out.lower()


def test_render_resources_block_no_counters_falls_back():
    state = _make_state()
    out = render_resources_block(state)
    assert "## Resources" in out
    assert "not yet populated" in out


# ---------------------------------------------------------------------------
# render_applied_changes_block
# ---------------------------------------------------------------------------


def test_render_applied_changes_block_empty():
    state = _make_state(applied_changes=[])
    out = render_applied_changes_block(state)
    assert "## Recent applied changes" in out
    assert "no changes yet" in out


def test_render_applied_changes_block_caps_to_five():
    applied = [
        {"action": "object.created", "target_type": "object",
         "name": f"Obj{i}", "target_id": str(uuid4())}
        for i in range(8)
    ]
    state = _make_state(applied_changes=applied)
    out = render_applied_changes_block(state)
    # We render the most recent 5 + an "omitted" line.
    assert "Obj7" in out  # last item rendered
    assert "Obj0" not in out  # first item dropped
    assert "earlier change" in out
    # Bullet count: 1 ellipsis + 5 items (plus the heading line).
    bullet_lines = [ln for ln in out.splitlines() if ln.startswith("- ")]
    assert len(bullet_lines) == 6


# ---------------------------------------------------------------------------
# make_supervisor_config
# ---------------------------------------------------------------------------


def test_make_supervisor_config_sets_expected_knobs():
    cfg = make_supervisor_config(_make_executor())
    assert cfg.name == "supervisor"
    assert cfg.max_steps == 200
    assert cfg.enable_streaming is True
    assert cfg.output_schema is None
    # All declared SUPERVISOR_TOOLS land on the config.
    assert len(cfg.tools) == len(SUPERVISOR_TOOLS)
    tool_names = {t["function"]["name"] for t in cfg.tools}
    assert {
        "write_scratchpad",
        "read_scratchpad",
        "delegate_to_planner",
        "delegate_to_diagram",
        "delegate_to_researcher",
        "delegate_to_critic",
        "finalize",
        "fork_diagram_to_draft",
        "web_fetch",
        "list_active_drafts",
    } <= tool_names
    # Four additional system blocks: scratchpad, resources, applied changes,
    # repo manifest. ``render_subagent_results_block`` was retired once the
    # graph started rewriting the matching delegate_to_* tool result with
    # the actual findings/plan/applied/critique payload.
    assert len(cfg.additional_system_blocks) == 4


def test_load_supervisor_prompt_returns_real_content():
    text = load_supervisor_prompt()
    # Sanity-check: the prompt should mention key concepts.
    lowered = text.lower()
    assert "supervisor" in lowered
    assert "delegate" in lowered or "sub-agent" in lowered
    assert "scratchpad" in lowered
    assert "finalize" in lowered
    # And it should not be the placeholder.
    assert "placeholder" not in lowered


# ---------------------------------------------------------------------------
# Smoke runs through run()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_finalize_tool_returns_finished_with_message_in_state_patch():
    """Stub LLM calls finalize → run yields finished, final_message landed
    in state_patch when message argument was provided."""
    finalize_call = {
        "id": "call_fin",
        "name": "finalize",
        "arguments": json.dumps({"message": "all done"}),
    }
    enforcer = _make_enforcer(
        completion_results=[
            _make_llm_result(text=None, tool_calls=[finalize_call]),
            # After the tool result, the LLM emits a terminal text turn.
            _make_llm_result(text="bye", tool_calls=None),
        ]
    )
    cm = _make_context_manager()
    executor = _make_executor(
        results=[
            {
                "tool_call_id": "call_fin",
                "status": "ok",
                "content": "ok",
                "preview": "finalized",
            }
        ]
    )
    state = _make_state(messages=[{"role": "user", "content": "wrap up"}])

    events = await _collect(
        run(
            state,
            enforcer=enforcer,
            context_manager=cm,
            tool_executor=executor,
            call_metadata_base=_make_call_meta(),
        )
    )

    output = _terminal_output(events)
    assert output.forced_finalize is None
    assert output.state_patch.get("final_message") == "all done"


@pytest.mark.asyncio
async def test_run_write_scratchpad_then_finalize_updates_state_patch():
    write_call = {
        "id": "call_w",
        "name": "write_scratchpad",
        "arguments": json.dumps({"content": "- [ ] step one"}),
    }
    finalize_call = {
        "id": "call_f",
        "name": "finalize",
        "arguments": json.dumps({}),
    }
    enforcer = _make_enforcer(
        completion_results=[
            _make_llm_result(text=None, tool_calls=[write_call]),
            _make_llm_result(text=None, tool_calls=[finalize_call]),
            _make_llm_result(text="done", tool_calls=None),
        ]
    )
    cm = _make_context_manager()
    executor = _make_executor()
    state = _make_state()

    events = await _collect(
        run(
            state,
            enforcer=enforcer,
            context_manager=cm,
            tool_executor=executor,
            call_metadata_base=_make_call_meta(),
        )
    )

    output = _terminal_output(events)
    assert output.state_patch.get("scratchpad") == "- [ ] step one"


@pytest.mark.asyncio
async def test_run_delegate_tool_call_is_recoverable_from_messages():
    """When the supervisor calls delegate_to_planner, the runtime's routing
    layer reads the last assistant tool call from state_patch['messages']
    to decide where to go next. We assert the delegation call is preserved
    in the message history."""
    delegate_call = {
        "id": "call_plan",
        "name": "delegate_to_planner",
        "arguments": json.dumps(
            {"reason": "needs decomposition", "focus": "build auth flow"}
        ),
    }
    # The tool executor's reply ends the turn from run_react's perspective
    # only if the LLM doesn't emit another tool call. We feed a terminal
    # text turn after the delegation reply.
    enforcer = _make_enforcer(
        completion_results=[
            _make_llm_result(text=None, tool_calls=[delegate_call]),
            _make_llm_result(text="awaiting planner", tool_calls=None),
        ]
    )
    cm = _make_context_manager()
    executor = _make_executor(
        results=[
            {
                "tool_call_id": "call_plan",
                "status": "ok",
                "content": "delegated",
                "preview": "delegated",
            }
        ]
    )
    state = _make_state()

    events = await _collect(
        run(
            state,
            enforcer=enforcer,
            context_manager=cm,
            tool_executor=executor,
            call_metadata_base=_make_call_meta(),
        )
    )

    output = _terminal_output(events)
    # The assistant message containing the delegate tool call is in the
    # messages stream so the runtime can read it.
    assistant_msgs_with_tools = [
        m for m in output.state_patch["messages"]
        if m.get("role") == "assistant" and m.get("tool_calls")
    ]
    assert assistant_msgs_with_tools, "expected an assistant tool-call message"
    last_call = assistant_msgs_with_tools[-1]["tool_calls"][-1]
    assert last_call["function"]["name"] == "delegate_to_planner"
    args = json.loads(last_call["function"]["arguments"])
    assert args["focus"] == "build auth flow"
