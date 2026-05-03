"""Tests for app/agents/builtin/general/graph.py — general agent LangGraph wiring.

Covers:

  1. ``build()`` returns a CompiledStateGraph and registers all expected nodes.
  2. ``_supervisor_routes_next`` dispatches on the last assistant tool call.
  3. ``_critic_routes_next`` honours APPROVE / REVISE + iteration cap.
  4. ``_planner_routes_next`` / ``_diagram_routes_next`` / ``_researcher_routes_next``
     are stable (no surprises).
  5. ``get_descriptor`` shape — id, surfaces, modes, scope, budget.
  6. ``register_builtin_agents`` registers the three builtins.
  7. ``critic_node`` increments ``iteration`` on REVISE verdicts.
  8. ``finalize_node`` populates ``final_message`` from state.
  9. Smoke: an instrumented invocation through the supervisor finalize path.

No real LLM calls — enforcer, context_manager, tool_executor are stubbed.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.builtin.general.graph import (
    MAX_CRITIQUE_LOOPS,
    MAX_TOTAL_STEPS,
    _critic_routes_next,
    _diagram_routes_next,
    _planner_routes_next,
    _researcher_routes_next,
    _supervisor_routes_next,
    build,
    critic_node,
    finalize_node,
    get_descriptor,
    supervisor_node,
)
from app.agents.context_manager import CompactionResult
from app.agents.llm import LLMCallMetadata, LLMResult
from app.agents.state import Critique

# ---------------------------------------------------------------------------
# Shared stub helpers (mirrors test_supervisor_node patterns)
# ---------------------------------------------------------------------------


def _make_llm_result(
    *,
    text: str | None = None,
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
    results: list[dict] | None = None,
) -> Callable[[dict, dict], Awaitable[dict]]:
    queue = list(results or [])

    async def _executor(tool_call: dict, state: dict) -> dict:
        if queue:
            return queue.pop(0)
        return {
            "tool_call_id": tool_call.get("id") or "",
            "status": "ok",
            "content": "ok",
            "preview": "ok",
        }

    return _executor


def _make_call_meta() -> LLMCallMetadata:
    return LLMCallMetadata(
        workspace_id=uuid4(),
        agent_id="general",
        session_id=uuid4(),
        actor_id=uuid4(),
        analytics_consent="off",
    )


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


def _config(**deps: Any) -> dict:
    """Build a LangGraph-style config dict with injected dependencies."""
    return {"configurable": deps}


# ---------------------------------------------------------------------------
# 1. Loop-bound constants
# ---------------------------------------------------------------------------


def test_loop_bound_constants_match_spec():
    assert MAX_TOTAL_STEPS == 15
    assert MAX_CRITIQUE_LOOPS == 2


# ---------------------------------------------------------------------------
# 2. build() returns a compiled graph with expected nodes
# ---------------------------------------------------------------------------


def test_build_returns_compiled_graph_with_expected_nodes():
    graph = build()
    assert graph is not None
    assert hasattr(graph, "ainvoke") or hasattr(graph, "invoke")

    node_names = set(graph.get_graph().nodes.keys())
    # LangGraph adds __start__ / __end__ sentinels — strip them.
    real_nodes = {n for n in node_names if not n.startswith("__")}
    assert real_nodes == {
        "supervisor",
        "planner",
        "diagram",
        "researcher",
        "critic",
        "finalize",
    }


# ---------------------------------------------------------------------------
# 3. Supervisor routing — last tool call drives the next node
# ---------------------------------------------------------------------------


def _state_with_supervisor_tool_call(tool_name: str) -> dict:
    return _make_state(
        messages=[
            {"role": "user", "content": "do the thing"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": json.dumps({}),
                        },
                    }
                ],
            },
        ]
    )


@pytest.mark.parametrize(
    "tool_name,expected_node",
    [
        ("delegate_to_planner", "planner"),
        ("delegate_to_diagram", "diagram"),
        ("delegate_to_researcher", "researcher"),
        ("delegate_to_critic", "critic"),
        ("finalize", "finalize"),
    ],
)
def test_supervisor_routes_next_dispatches_on_tool_call(tool_name, expected_node):
    state = _state_with_supervisor_tool_call(tool_name)
    assert _supervisor_routes_next(state) == expected_node


def test_supervisor_routes_next_unknown_tool_falls_back_to_finalize():
    state = _state_with_supervisor_tool_call("definitely_not_a_real_tool")
    assert _supervisor_routes_next(state) == "finalize"


def test_supervisor_routes_next_no_tool_calls_falls_back_to_finalize():
    state = _make_state(
        messages=[{"role": "assistant", "content": "no calls here"}]
    )
    assert _supervisor_routes_next(state) == "finalize"


def test_supervisor_routes_next_uses_most_recent_assistant_tool_call():
    """When multiple assistant tool calls exist, the *last* one wins."""
    state = _make_state(
        messages=[
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "old",
                        "type": "function",
                        "function": {"name": "delegate_to_planner", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "old", "content": "ok"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "new",
                        "type": "function",
                        "function": {"name": "delegate_to_critic", "arguments": "{}"},
                    }
                ],
            },
        ]
    )
    assert _supervisor_routes_next(state) == "critic"


def test_supervisor_routes_next_text_after_delegate_goes_to_finalize():
    """Regression: previously the router skipped past a text-only assistant
    turn looking for an older tool_call, and re-launched the same sub-agent
    after supervisor already wrote the final reply."""
    state = _make_state(
        messages=[
            # supervisor visit 1: delegated to researcher
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "del1",
                        "type": "function",
                        "function": {"name": "delegate_to_researcher", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "del1", "content": "ok"},
            # researcher returned, supervisor visit 2: wrote prose, no tool_calls
            {"role": "assistant", "content": "На жаль, нічого не знайшов..."},
        ]
    )
    assert _supervisor_routes_next(state) == "finalize"


# ---------------------------------------------------------------------------
# 4. Critic routing
# ---------------------------------------------------------------------------


def test_critic_routes_next_approve_goes_to_finalize():
    state = _make_state(
        critique=Critique(verdict="APPROVE"),
        iteration=0,
    )
    assert _critic_routes_next(state) == "finalize"


def test_critic_routes_next_revise_under_limit_goes_to_planner():
    state = _make_state(
        critique=Critique(verdict="REVISE", revision_request="redo step 2"),
        iteration=0,
    )
    assert _critic_routes_next(state) == "planner"


def test_critic_routes_next_revise_at_limit_goes_to_finalize():
    state = _make_state(
        critique=Critique(verdict="REVISE", revision_request="redo"),
        iteration=MAX_CRITIQUE_LOOPS,  # 2
    )
    assert _critic_routes_next(state) == "finalize"


def test_critic_routes_next_no_critique_defaults_to_finalize():
    state = _make_state(critique=None, iteration=0)
    assert _critic_routes_next(state) == "finalize"


def test_critic_routes_next_accepts_dict_critique():
    state = _make_state(critique={"verdict": "REVISE"}, iteration=1)
    assert _critic_routes_next(state) == "planner"


# ---------------------------------------------------------------------------
# 5. Static post-node edges (sanity)
# ---------------------------------------------------------------------------


def test_planner_routes_next_always_diagram():
    assert _planner_routes_next(_make_state()) == "diagram"


def test_diagram_routes_next_always_supervisor():
    assert _diagram_routes_next(_make_state()) == "supervisor"


def test_researcher_routes_next_always_supervisor():
    assert _researcher_routes_next(_make_state()) == "supervisor"


# ---------------------------------------------------------------------------
# 6. get_descriptor shape
# ---------------------------------------------------------------------------


def test_get_descriptor_id_and_basics():
    desc = get_descriptor()
    assert desc.id == "general"
    assert desc.required_scope == "agents:invoke"
    assert desc.streaming is True
    assert desc.default_budget_usd == Decimal("1.00")
    assert desc.default_budget_scope == "per_invocation"
    assert desc.default_turn_limit == 200


def test_get_descriptor_surfaces_chat_bubble_and_a2a():
    desc = get_descriptor()
    assert "chat_bubble" in desc.surfaces
    assert "a2a" in desc.surfaces


def test_get_descriptor_supports_full_and_read_only_modes():
    desc = get_descriptor()
    assert "full" in desc.supported_modes
    assert "read_only" in desc.supported_modes


def test_get_descriptor_tools_overview_lists_expected_tools():
    desc = get_descriptor()
    expected = {
        "search_existing_objects",
        "create_object",
        "create_connection",
        "create_diagram",
        "place_on_diagram",
        "fork_diagram_to_draft",
    }
    assert expected <= set(desc.tools_overview)
    # At least one delegation tool surfaces in the overview as well.
    assert any(t.startswith("delegate_to_") for t in desc.tools_overview)


def test_get_descriptor_graph_is_compiled():
    desc = get_descriptor()
    assert desc.graph is not None


# ---------------------------------------------------------------------------
# 7. register_builtin_agents
# ---------------------------------------------------------------------------


def test_register_builtin_agents_registers_three_agents():
    from app.agents import registry
    from app.agents.builtin import register_builtin_agents

    registry.clear()
    register_builtin_agents()

    ids = {d.id for d in registry.all_agents()}
    assert ids == {"general", "researcher", "diagram-explainer"}


def test_register_builtin_agents_is_idempotent():
    from app.agents import registry
    from app.agents.builtin import register_builtin_agents

    registry.clear()
    register_builtin_agents()
    register_builtin_agents()  # second call must not double-register

    assert len(registry.all_agents()) == 3


# ---------------------------------------------------------------------------
# 8. critic_node bumps iteration on REVISE
# ---------------------------------------------------------------------------


async def test_critic_node_increments_iteration_on_revise(monkeypatch):
    """When the critic returns REVISE, the LangGraph wrapper should bump
    ``iteration`` so the next routing call sees the new count."""
    from app.agents.builtin.general.nodes import critic as critic_module
    from app.agents.nodes.base import NodeOutput, NodeStreamEvent

    revise_critique = Critique(verdict="REVISE", revision_request="redo")

    async def _fake_run(state, **kwargs):
        # Mimic what critic.run() yields: a single 'finished' event with the
        # parsed Critique injected into state_patch.
        yield NodeStreamEvent(
            kind="finished",
            payload={
                "output": NodeOutput(
                    text="(stub)",
                    structured=revise_critique,
                    state_patch={
                        "messages": list(state.get("messages") or []),
                        "critique": revise_critique,
                    },
                )
            },
        )

    monkeypatch.setattr(critic_module, "run", _fake_run)

    state = _make_state(iteration=0)
    cfg = _config(
        enforcer=MagicMock(),
        context_manager=MagicMock(),
        tool_executor=lambda *a, **k: None,  # not invoked
        call_metadata_base=_make_call_meta(),
    )

    patch = await critic_node(state, cfg)
    assert patch.get("iteration") == 1
    assert patch.get("critique") == revise_critique


async def test_critic_node_does_not_bump_iteration_on_approve(monkeypatch):
    from app.agents.builtin.general.nodes import critic as critic_module
    from app.agents.nodes.base import NodeOutput, NodeStreamEvent

    approve_critique = Critique(verdict="APPROVE")

    async def _fake_run(state, **kwargs):
        yield NodeStreamEvent(
            kind="finished",
            payload={
                "output": NodeOutput(
                    text="(stub)",
                    structured=approve_critique,
                    state_patch={
                        "messages": list(state.get("messages") or []),
                        "critique": approve_critique,
                    },
                )
            },
        )

    monkeypatch.setattr(critic_module, "run", _fake_run)

    state = _make_state(iteration=0)
    cfg = _config(
        enforcer=MagicMock(),
        context_manager=MagicMock(),
        tool_executor=lambda *a, **k: None,
        call_metadata_base=_make_call_meta(),
    )

    patch = await critic_node(state, cfg)
    assert "iteration" not in patch  # APPROVE → no bump


# ---------------------------------------------------------------------------
# 9. finalize_node populates final_message
# ---------------------------------------------------------------------------


async def test_finalize_node_builds_final_message():
    state = _make_state(applied_changes=[])
    patch = await finalize_node(state, None)
    assert "final_message" in patch
    assert isinstance(patch["final_message"], str)
    assert patch["final_message"]  # non-empty


# ---------------------------------------------------------------------------
# 10. Smoke: supervisor_node drives a finalize call end-to-end
# ---------------------------------------------------------------------------


async def test_supervisor_node_finalize_path_yields_state_patch():
    """Drive the supervisor through one finalize tool call and assert the
    LangGraph wrapper returns a usable state patch.

    We cannot easily compile-and-invoke the full graph here because the
    supervisor → conditional → finalize transition expects state mutation
    propagation that LangGraph normally handles internally; instead we run
    each wrapper individually and check their state-patch shapes.
    """
    finalize_call = {
        "id": "call_fin",
        "name": "finalize",
        "arguments": json.dumps({"message": "all done"}),
    }
    enforcer = _make_enforcer(
        completion_results=[
            _make_llm_result(text=None, tool_calls=[finalize_call]),
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
    cfg = _config(
        enforcer=enforcer,
        context_manager=cm,
        tool_executor=executor,
        call_metadata_base=_make_call_meta(),
    )

    patch = await supervisor_node(state, cfg)
    assert isinstance(patch, dict)
    # final_message comes from the supervisor's own finalize-arg lift.
    assert patch.get("final_message") == "all done"

    # The runtime layer (task 016) inspects state['messages'] from the patch
    # to make routing decisions. The finalize tool call must be present.
    msgs = patch.get("messages") or []
    assistant_with_calls = [
        m for m in msgs if m.get("role") == "assistant" and m.get("tool_calls")
    ]
    assert assistant_with_calls
    # The router should now choose 'finalize' from this state.
    assert _supervisor_routes_next({"messages": msgs}) == "finalize"


async def test_supervisor_node_raises_when_deps_missing():
    """The wrapper must refuse to run without injected dependencies."""
    state = _make_state()
    with pytest.raises(RuntimeError, match="config\\['configurable'\\]"):
        await supervisor_node(state, {"configurable": {}})
