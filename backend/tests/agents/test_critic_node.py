"""Tests for the Critic node (agent-core-mvp-022).

Covers:
1. Critique model validation — fields, defaults, max_length constraints.
2. revision_request is optional (None for APPROVE) but strongly recommended for REVISE.
3. CRITIC_TOOLS are all read-only (no mutating tool names).
4. make_critic_config: max_steps=6, output_schema=Critique.
5. render_goal_block extracts the first user message.
6. render_applied_changes_for_critic with 0 changes → "(no changes to review)".
7. Stub LLM returns valid APPROVE Critique → output.structured.verdict == 'APPROVE'.
8. Stub LLM returns REVISE with revision_request → output.structured.verdict == 'REVISE'.
"""

from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agents.builtin.general.nodes.critic import (
    CRITIC_TOOLS,
    make_critic_config,
    render_applied_changes_for_critic,
    render_goal_block,
    run,
)
from app.agents.context_manager import CompactionResult
from app.agents.llm import LLMCallMetadata, LLMResult
from app.agents.nodes.base import NodeStreamEvent
from app.agents.state import Critique

# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------

_MUTATING_PREFIXES = (
    "create_",
    "update_",
    "delete_",
    "place_",
    "move_",
    "unplace_",
    "fork_",
    "discard_",
    "auto_layout_",
    "link_",
)

_READ_ONLY_NAMES = {
    "read_object",
    "read_object_full",
    "read_diagram",
    "dependencies",
    "list_objects",
    "list_diagrams",
    "list_child_diagrams",
    "search_existing_objects",
}


def _tool_name(tool: dict) -> str:
    """Extract function name from OpenAI-shape tool dict."""
    return tool.get("function", {}).get("name", "")


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
    cost_usd: Decimal = Decimal("0.001"),
) -> LLMResult:
    return LLMResult(
        text=text,
        tool_calls=tool_calls,
        finish_reason="stop",
        tokens_in=10,
        tokens_out=10,
        cost_usd=cost_usd,
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

    async def _noop_compact(messages, **kwargs):
        return CompactionResult(
            compacted_messages=messages,
            stage_applied=0,
            strategy_name=None,
            tokens_before=100,
            tokens_after=100,
        )

    cm.maybe_compact = AsyncMock(side_effect=_noop_compact)
    return cm


async def _noop_tool_executor(tool_call: dict, state: dict) -> dict:
    return {
        "tool_call_id": tool_call.get("id") or "",
        "status": "ok",
        "content": "{}",
        "preview": "ok",
    }


def _make_state(
    messages: list[dict] | None = None,
    applied_changes: list[dict] | None = None,
) -> dict:
    return {
        "workspace_id": uuid4(),
        "session_id": uuid4(),
        "messages": list(messages or []),
        "applied_changes": list(applied_changes or []),
        "iteration": 0,
        "tokens_in": 0,
        "tokens_out": 0,
    }


async def _collect(gen) -> list[NodeStreamEvent]:
    return [ev async for ev in gen]


def _terminal_output(events: list[NodeStreamEvent]):
    finished = [ev for ev in events if ev.kind == "finished"]
    assert len(finished) == 1, f"expected one 'finished' event, got {len(finished)}"
    return finished[0].payload["output"]


# ---------------------------------------------------------------------------
# 1. Critique model validation
# ---------------------------------------------------------------------------


def test_critique_approve_minimal():
    c = Critique(verdict="APPROVE")
    assert c.verdict == "APPROVE"
    assert c.strengths == []
    assert c.issues == []
    assert c.revision_request is None


def test_critique_revise_with_revision_request():
    c = Critique(
        verdict="REVISE",
        strengths=["Good naming"],
        issues=["Object X is orphaned"],
        revision_request="Add parent_id to object X",
    )
    assert c.verdict == "REVISE"
    assert c.revision_request == "Add parent_id to object X"
    assert "orphaned" in c.issues[0]


def test_critique_invalid_verdict_raises():
    with pytest.raises(ValidationError):
        Critique(verdict="MAYBE")  # type: ignore[arg-type]


def test_critique_strengths_max_length():
    """More than 10 strengths should fail validation."""
    with pytest.raises(ValidationError):
        Critique(verdict="APPROVE", strengths=[f"s{i}" for i in range(11)])


def test_critique_issues_max_length():
    """More than 10 issues should fail validation."""
    with pytest.raises(ValidationError):
        Critique(verdict="REVISE", issues=[f"i{i}" for i in range(11)])


def test_critique_revision_request_max_length():
    """revision_request > 2000 chars should fail validation."""
    with pytest.raises(ValidationError):
        Critique(verdict="REVISE", revision_request="x" * 2001)


# ---------------------------------------------------------------------------
# 2. revision_request optional but recommended
# ---------------------------------------------------------------------------


def test_critique_revise_without_revision_request_is_valid():
    """The schema allows REVISE without revision_request (optional field).
    In practice the prompt instructs the model to always supply it for REVISE.
    """
    c = Critique(verdict="REVISE", issues=["Missing parent"])
    assert c.revision_request is None


def test_critique_approve_null_revision_request():
    c = Critique(verdict="APPROVE")
    assert c.revision_request is None


# ---------------------------------------------------------------------------
# 3. CRITIC_TOOLS are all read-only
# ---------------------------------------------------------------------------


def test_critic_tools_not_empty():
    assert len(CRITIC_TOOLS) > 0, "CRITIC_TOOLS should not be empty"


def test_critic_tools_no_mutating_names():
    """None of the tool names should start with a mutating prefix."""
    names = [_tool_name(t) for t in CRITIC_TOOLS]
    for name in names:
        for prefix in _MUTATING_PREFIXES:
            assert not name.startswith(prefix), (
                f"CRITIC_TOOLS contains mutating tool '{name}' (prefix '{prefix}')"
            )


def test_critic_tools_no_web_fetch():
    """Critic does not need external data — web_fetch must not be present."""
    names = {_tool_name(t) for t in CRITIC_TOOLS}
    assert "web_fetch" not in names


def test_critic_tools_contain_expected_read_only_tools():
    names = {_tool_name(t) for t in CRITIC_TOOLS}
    for expected in _READ_ONLY_NAMES:
        assert expected in names, f"Expected read-only tool '{expected}' not in CRITIC_TOOLS"


def test_critic_tools_are_openai_shape():
    """Every tool must have the correct OpenAI function-calling shape."""
    for tool in CRITIC_TOOLS:
        assert tool.get("type") == "function", f"Tool missing 'type': {tool}"
        fn = tool.get("function", {})
        assert "name" in fn, f"Tool function missing 'name': {fn}"
        assert "parameters" in fn, f"Tool function missing 'parameters': {fn}"


# ---------------------------------------------------------------------------
# 4. make_critic_config: max_steps=6, output_schema=Critique
# ---------------------------------------------------------------------------


def test_make_critic_config_max_steps():
    cfg = make_critic_config(_noop_tool_executor)
    assert cfg.max_steps == 6


def test_make_critic_config_output_schema():
    cfg = make_critic_config(_noop_tool_executor)
    assert cfg.output_schema is Critique


def test_make_critic_config_name():
    cfg = make_critic_config(_noop_tool_executor)
    assert cfg.name == "critic"


def test_make_critic_config_has_expected_system_blocks():
    """Config must include the active-context, delegation-brief, goal and
    applied-changes renderers (in that order)."""
    cfg = make_critic_config(_noop_tool_executor)
    names = [b.__name__ for b in cfg.additional_system_blocks]
    assert names == [
        "render_active_context_block",
        "render_delegation_brief_block",
        "render_goal_block",
        "render_applied_changes_for_critic",
    ]


def test_make_critic_config_tools_match_critic_tools():
    cfg = make_critic_config(_noop_tool_executor)
    assert cfg.tools is CRITIC_TOOLS


# ---------------------------------------------------------------------------
# 5. render_goal_block extracts first user message
# ---------------------------------------------------------------------------


def test_render_goal_block_returns_first_user_message():
    state = _make_state(
        messages=[
            {"role": "system", "content": "You are..."},
            {"role": "user", "content": "Add Redis to the diagram"},
            {"role": "assistant", "content": "Sure"},
            {"role": "user", "content": "Also add a queue"},
        ]
    )
    block = render_goal_block(state)
    assert "Add Redis to the diagram" in block
    assert "Also add a queue" not in block  # only FIRST user message


def test_render_goal_block_no_user_messages_returns_empty():
    state = _make_state(messages=[{"role": "assistant", "content": "hi"}])
    block = render_goal_block(state)
    assert block == ""


def test_render_goal_block_empty_messages_returns_empty():
    state = _make_state(messages=[])
    block = render_goal_block(state)
    assert block == ""


def test_render_goal_block_contains_header():
    state = _make_state(messages=[{"role": "user", "content": "Do something"}])
    block = render_goal_block(state)
    assert "## Original user goal" in block


# ---------------------------------------------------------------------------
# 6. render_applied_changes_for_critic: 0 changes → sentinel
# ---------------------------------------------------------------------------


def test_render_applied_changes_empty_returns_sentinel():
    state = _make_state(applied_changes=[])
    block = render_applied_changes_for_critic(state)
    assert "(no changes to review)" in block


def test_render_applied_changes_lists_each_change():
    oid = uuid4()
    state = _make_state(
        applied_changes=[
            {
                "action": "object.created",
                "target_type": "object",
                "name": "Auth Service",
                "target_id": oid,
            }
        ]
    )
    block = render_applied_changes_for_critic(state)
    assert "Auth Service" in block
    assert str(oid) in block
    assert "object.created" in block


def test_render_applied_changes_contains_header():
    state = _make_state(applied_changes=[])
    block = render_applied_changes_for_critic(state)
    assert "## Applied changes" in block


def test_render_applied_changes_multiple_items_numbered():
    state = _make_state(
        applied_changes=[
            {
                "action": "object.created",
                "target_type": "object",
                "name": "A",
                "target_id": uuid4(),
            },
            {
                "action": "connection.created",
                "target_type": "connection",
                "name": "A→B",
                "target_id": uuid4(),
            },
        ]
    )
    block = render_applied_changes_for_critic(state)
    assert "1." in block
    assert "2." in block


# ---------------------------------------------------------------------------
# 7. Stub LLM returns APPROVE → output.structured.verdict == 'APPROVE'
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_approve_critique_populated_in_state_patch():
    approve_payload = {
        "verdict": "APPROVE",
        "strengths": ["Good structure", "No orphans"],
        "issues": [],
        "revision_request": None,
    }
    enforcer = _make_enforcer(
        completion_results=[_make_llm_result(text=json.dumps(approve_payload))]
    )
    cm = _make_context_manager()
    state = _make_state(
        messages=[{"role": "user", "content": "Add a Redis cache"}],
        applied_changes=[
            {
                "action": "object.created",
                "target_type": "object",
                "name": "Redis Cache",
                "target_id": uuid4(),
            }
        ],
    )

    events = await _collect(
        run(
            state,
            enforcer=enforcer,
            context_manager=cm,
            tool_executor=_noop_tool_executor,
            call_metadata_base=_make_call_meta(),
        )
    )

    output = _terminal_output(events)
    assert output.structured is not None
    assert isinstance(output.structured, Critique)
    assert output.structured.verdict == "APPROVE"
    assert "critique" in output.state_patch
    assert output.state_patch["critique"] is output.structured


# ---------------------------------------------------------------------------
# 8. Stub LLM returns REVISE with revision_request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_revise_critique_populated_in_state_patch():
    revise_payload = {
        "verdict": "REVISE",
        "strengths": ["Some progress"],
        "issues": ["object Redis Cache is an orphan — no parent_id"],
        "revision_request": "Add parent_id to Redis Cache pointing to Order Service.",
    }
    enforcer = _make_enforcer(
        completion_results=[_make_llm_result(text=json.dumps(revise_payload))]
    )
    cm = _make_context_manager()
    state = _make_state(
        messages=[{"role": "user", "content": "Add a Redis cache under Order Service"}],
        applied_changes=[
            {
                "action": "object.created",
                "target_type": "object",
                "name": "Redis Cache",
                "target_id": uuid4(),
            }
        ],
    )

    events = await _collect(
        run(
            state,
            enforcer=enforcer,
            context_manager=cm,
            tool_executor=_noop_tool_executor,
            call_metadata_base=_make_call_meta(),
        )
    )

    output = _terminal_output(events)
    assert output.structured is not None
    assert isinstance(output.structured, Critique)
    assert output.structured.verdict == "REVISE"
    assert output.structured.revision_request is not None
    assert "parent_id" in output.structured.revision_request
    assert "critique" in output.state_patch
    assert output.state_patch["critique"].verdict == "REVISE"
