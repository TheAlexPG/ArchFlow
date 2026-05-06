"""Tests for the planner node + Plan/PlanStep Pydantic models.

These tests cover three concerns:

1. ``Plan`` / ``PlanStep`` schema validation (round-trip, bounds, depends_on).
2. ``Plan.topological_order`` correctness (Kahn's algorithm + cycle detection).
3. The planner node's :func:`run` / :func:`make_planner_config` wiring,
   driven with the same scripted-LLM scaffolding used by ``test_run_react``.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agents.builtin.general.nodes import planner
from app.agents.context_manager import CompactionResult
from app.agents.llm import LLMCallMetadata, LLMResult
from app.agents.nodes.base import NodeStreamEvent
from app.agents.state import Plan, PlanStep

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _step(
    *,
    index: int,
    kind: str = "create_object",
    args: dict | None = None,
    depends_on: list[int] | None = None,
    rationale: str = "because",
) -> PlanStep:
    return PlanStep(
        index=index,
        kind=kind,  # type: ignore[arg-type]
        args=args or {},
        depends_on=depends_on or [],
        rationale=rationale,
    )


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


def _make_enforcer(*, completion_results: list[LLMResult]) -> MagicMock:
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


def _make_tool_executor() -> Callable[[dict, dict], Awaitable[dict]]:
    async def _executor(tool_call: dict, state: dict) -> dict:
        return {
            "tool_call_id": tool_call.get("id") or "",
            "status": "ok",
            "content": "[]",
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


async def _collect(gen) -> list[NodeStreamEvent]:
    return [ev async for ev in gen]


# ---------------------------------------------------------------------------
# 1. Plan / PlanStep schema validation
# ---------------------------------------------------------------------------


def test_plan_round_trips_through_json():
    """A valid Plan serialises to JSON and parses back identical."""
    plan = Plan(
        goal="add a redis cache",
        steps=[
            _step(index=0, kind="search_existing_object", args={"query": "redis"}),
            _step(
                index=1,
                kind="create_object",
                args={"name": "Redis", "kind": "store"},
                depends_on=[0],
            ),
        ],
        reuse_findings=["reuses API id=o-api"],
    )
    blob = plan.model_dump_json()
    restored = Plan.model_validate_json(blob)
    assert restored == plan


def test_plan_rejects_empty_steps():
    """min_length=1 → empty steps list must fail validation."""
    with pytest.raises(ValidationError) as excinfo:
        Plan(goal="empty", steps=[], reuse_findings=[])
    assert "steps" in str(excinfo.value)


def test_plan_rejects_more_than_40_steps():
    """max_length=40 enforces the planner's hard cap."""
    too_many = [_step(index=i) for i in range(41)]
    with pytest.raises(ValidationError):
        Plan(goal="huge", steps=too_many)


def test_plan_step_rejects_invalid_kind():
    """``kind`` is a Literal; unknown values fail validation."""
    with pytest.raises(ValidationError):
        PlanStep(
            index=0,
            kind="frob_widget",  # type: ignore[arg-type]
            args={},
            depends_on=[],
            rationale="bogus",
        )


def test_plan_step_rejects_negative_index():
    """``index`` has ge=0."""
    with pytest.raises(ValidationError):
        PlanStep(
            index=-1,
            kind="create_object",
            args={},
            depends_on=[],
            rationale="bad",
        )


# ---------------------------------------------------------------------------
# 2. Plan.topological_order
# ---------------------------------------------------------------------------


def test_topological_order_returns_valid_linear_order():
    """A simple chain 0 → 1 → 2 should resolve in index order."""
    plan = Plan(
        goal="chain",
        steps=[
            _step(index=2, depends_on=[1]),
            _step(index=0, depends_on=[]),
            _step(index=1, depends_on=[0]),
        ],
    )
    ordered = plan.topological_order()
    assert [s.index for s in ordered] == [0, 1, 2]


def test_topological_order_handles_diamond():
    """Diamond graph: 0 fans out to 1 and 2, both feed 3."""
    plan = Plan(
        goal="diamond",
        steps=[
            _step(index=0),
            _step(index=1, depends_on=[0]),
            _step(index=2, depends_on=[0]),
            _step(index=3, depends_on=[1, 2]),
        ],
    )
    ordered = [s.index for s in plan.topological_order()]
    # 0 first, 3 last; 1 and 2 in deterministic (sorted) order between.
    assert ordered[0] == 0
    assert ordered[-1] == 3
    assert set(ordered[1:3]) == {1, 2}


def test_topological_order_raises_on_cycle():
    """Direct two-step cycle: 0 ↔ 1."""
    plan = Plan(
        goal="cycle",
        steps=[
            _step(index=0, depends_on=[1]),
            _step(index=1, depends_on=[0]),
        ],
    )
    with pytest.raises(ValueError, match="cycle"):
        plan.topological_order()


def test_topological_order_raises_on_out_of_range_dep():
    """depends_on referencing an unknown index is rejected."""
    plan = Plan(
        goal="bad-ref",
        steps=[_step(index=0, depends_on=[99])],
    )
    with pytest.raises(ValueError, match="unknown index"):
        plan.topological_order()


def test_topological_order_raises_on_self_dependency():
    """A step that depends on itself is a degenerate cycle."""
    plan = Plan(goal="self", steps=[_step(index=0, depends_on=[0])])
    with pytest.raises(ValueError, match="cannot depend on itself"):
        plan.topological_order()


def test_topological_order_raises_on_duplicate_indices():
    """Two steps sharing the same ``index`` is ambiguous and rejected."""
    plan = Plan(goal="dup", steps=[_step(index=0), _step(index=0)])
    with pytest.raises(ValueError, match="duplicate step index"):
        plan.topological_order()


# ---------------------------------------------------------------------------
# 3. Planner config + tool surface
# ---------------------------------------------------------------------------


def test_make_planner_config_uses_plan_schema_and_high_step_ceiling():
    cfg = planner.make_planner_config(_make_tool_executor())
    assert cfg.name == "planner"
    assert cfg.max_steps == 200
    assert cfg.output_schema is Plan
    assert cfg.enable_streaming is False
    names = [b.__name__ for b in cfg.additional_system_blocks]
    assert names == ["render_active_context_block", "render_delegation_brief_block"]
    # System prompt was loaded from disk and is non-trivial.
    assert "Planner" in cfg.system_prompt
    assert len(cfg.system_prompt) > 200


def test_planner_tools_are_read_only():
    """No tool in PLANNER_TOOLS should mutate state.

    We assert by tool name — every entry must start with ``read_``,
    ``search_``, ``list_``, or ``dependencies``. Any name containing
    ``create``, ``update``, ``delete``, ``move``, ``place``, or ``link``
    is rejected.
    """
    forbidden_substrings = (
        "create",
        "update",
        "delete",
        "move",
        "place",
        "link",
        "auto_layout",
        "fork",
    )
    allowed_prefixes = ("read_", "search_", "list_", "dependencies")
    names = [t["function"]["name"] for t in planner.PLANNER_TOOLS]
    assert names, "PLANNER_TOOLS must not be empty"
    for name in names:
        assert not any(bad in name for bad in forbidden_substrings), (
            f"forbidden mutation verb in tool name: {name!r}"
        )
        assert any(name.startswith(p) or name == p for p in allowed_prefixes), (
            f"tool {name!r} doesn't match a read-only naming convention"
        )


def test_load_planner_prompt_is_cached():
    """Repeated calls return the same string instance (module-level cache)."""
    a = planner.load_planner_prompt()
    b = planner.load_planner_prompt()
    assert a is b
    assert "STRICT JSON" in a or "STRICT" in a


# ---------------------------------------------------------------------------
# 4. End-to-end: run() with stub LLM
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_returns_plan_when_llm_emits_valid_json():
    """A valid Plan JSON in the assistant's terminal turn is parsed into ``output.structured``."""
    payload: dict[str, Any] = {
        "goal": "add redis",
        "steps": [
            {
                "index": 0,
                "kind": "search_existing_object",
                "args": {"query": "redis"},
                "depends_on": [],
                "rationale": "check first",
            },
            {
                "index": 1,
                "kind": "create_object",
                "args": {"name": "Redis", "kind": "store"},
                "depends_on": [0],
                "rationale": "no existing redis",
            },
        ],
        "reuse_findings": [],
    }
    enforcer = _make_enforcer(
        completion_results=[_make_llm_result(text=json.dumps(payload), tool_calls=None)]
    )
    cm = _make_context_manager()
    state = _make_state(messages=[{"role": "user", "content": "add redis"}])

    events = await _collect(
        planner.run(
            state,
            enforcer=enforcer,
            context_manager=cm,
            tool_executor=_make_tool_executor(),
            call_metadata_base=_make_call_meta(),
        )
    )

    finished = [ev for ev in events if ev.kind == "finished"]
    assert len(finished) == 1
    output = finished[0].payload["output"]
    assert isinstance(output.structured, Plan)
    assert output.structured.goal == "add redis"
    assert len(output.structured.steps) == 2
    assert output.structured.steps[1].depends_on == [0]
    assert output.forced_finalize is None


@pytest.mark.asyncio
async def test_run_returns_none_structured_on_invalid_json(caplog):
    """Garbage in → ``output.structured`` is None, ``output.text`` retained, warning logged."""
    bad = "this is not JSON, sorry"
    enforcer = _make_enforcer(
        completion_results=[_make_llm_result(text=bad, tool_calls=None)]
    )
    cm = _make_context_manager()
    state = _make_state(messages=[{"role": "user", "content": "plan"}])

    with caplog.at_level("WARNING", logger="app.agents.nodes.base"):
        events = await _collect(
            planner.run(
                state,
                enforcer=enforcer,
                context_manager=cm,
                tool_executor=_make_tool_executor(),
                call_metadata_base=_make_call_meta(),
            )
        )

    output = next(ev for ev in events if ev.kind == "finished").payload["output"]
    assert output.structured is None
    assert output.text == bad
    assert any("structured output parse failed" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_run_returns_none_structured_on_schema_violation():
    """Valid JSON that violates the Plan schema (e.g. empty steps) → structured=None."""
    bad_payload = {"goal": "x", "steps": [], "reuse_findings": []}
    enforcer = _make_enforcer(
        completion_results=[
            _make_llm_result(text=json.dumps(bad_payload), tool_calls=None)
        ]
    )
    cm = _make_context_manager()
    state = _make_state(messages=[{"role": "user", "content": "plan"}])

    events = await _collect(
        planner.run(
            state,
            enforcer=enforcer,
            context_manager=cm,
            tool_executor=_make_tool_executor(),
            call_metadata_base=_make_call_meta(),
        )
    )
    output = next(ev for ev in events if ev.kind == "finished").payload["output"]
    assert output.structured is None
    # Raw text retained for inspection.
    assert output.text is not None
