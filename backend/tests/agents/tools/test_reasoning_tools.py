"""Tests for app/agents/tools/reasoning_tools.py.

Verifies that every reasoning tool:
  - executes without error (handlers are no longer NotImplementedError stubs),
  - returns the expected action envelope,
  - is registered with mutating=False (no domain data mutation).

These tools are SUPERVISOR-ONLY — no ACL checks, no real DB calls.
All tests call the handler directly (bypassing execute_tool) to stay
independent of the ACL/audit machinery.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import pytest

from app.agents.tools.base import ToolContext
from app.agents.tools.reasoning_tools import (
    DELEGATE_TO_CRITIC,
    DELEGATE_TO_DIAGRAM,
    DELEGATE_TO_PLANNER,
    DELEGATE_TO_RESEARCHER,
    FINALIZE,
    READ_SCRATCHPAD,
    WRITE_SCRATCHPAD,
    DelegateToCriticInput,
    DelegateToDiagramInput,
    DelegateToPlannerInput,
    DelegateToResearcherInput,
    FinalizeInput,
    ReadScratchpadInput,
    WriteScratchpadInput,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@dataclass
class _FakeActor:
    kind: str = "user"
    id: Any = None


@pytest.fixture()
def ctx() -> ToolContext:
    ws = uuid4()
    return ToolContext(
        db=None,
        actor=_FakeActor(kind="user", id=uuid4()),
        workspace_id=ws,
        chat_context={"kind": "workspace", "id": ws},
        session_id=uuid4(),
        agent_id="supervisor",
        agent_runtime_mode="full",
        active_draft_id=None,
        draft_target_diagram_id=None,
    )


# ---------------------------------------------------------------------------
# Scratchpad tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_scratchpad_returns_content(ctx: ToolContext) -> None:
    """write_scratchpad echoes content back; runtime copies it into state.scratchpad."""
    args = WriteScratchpadInput(content="## TODO\n- step 1\n- step 2")
    result = await WRITE_SCRATCHPAD.handler(args, ctx)

    assert result["action"] == "scratchpad.written"
    assert result["content"] == "## TODO\n- step 1\n- step 2"


@pytest.mark.asyncio
async def test_read_scratchpad_returns_placeholder(ctx: ToolContext) -> None:
    """read_scratchpad returns empty string in Phase 1 (no direct state access)."""
    args = ReadScratchpadInput()
    result = await READ_SCRATCHPAD.handler(args, ctx)

    assert result["action"] == "scratchpad.read"
    assert "scratchpad" in result
    # Phase 1 limitation: placeholder is an empty string
    assert result["scratchpad"] == ""


# ---------------------------------------------------------------------------
# Delegation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delegate_to_planner_returns_action(ctx: ToolContext) -> None:
    args = DelegateToPlannerInput(reason="multi-step refactor needed", focus="system context")
    result = await DELEGATE_TO_PLANNER.handler(args, ctx)

    assert result["action"] == "delegate.planner"
    assert result["reason"] == "multi-step refactor needed"
    assert result["focus"] == "system context"


@pytest.mark.asyncio
async def test_delegate_to_diagram_returns_action(ctx: ToolContext) -> None:
    args = DelegateToDiagramInput(action_hint="add Order Service to C2 diagram")
    result = await DELEGATE_TO_DIAGRAM.handler(args, ctx)

    assert result["action"] == "delegate.diagram"
    assert result["action_hint"] == "add Order Service to C2 diagram"


@pytest.mark.asyncio
async def test_delegate_to_researcher_returns_action(ctx: ToolContext) -> None:
    args = DelegateToResearcherInput(question="What is the SLA for the payment service?")
    result = await DELEGATE_TO_RESEARCHER.handler(args, ctx)

    assert result["action"] == "delegate.researcher"
    assert result["question"] == "What is the SLA for the payment service?"


@pytest.mark.asyncio
async def test_delegate_to_critic_returns_action(ctx: ToolContext) -> None:
    args = DelegateToCriticInput()
    result = await DELEGATE_TO_CRITIC.handler(args, ctx)

    assert result["action"] == "delegate.critic"


@pytest.mark.asyncio
async def test_finalize_with_message(ctx: ToolContext) -> None:
    args = FinalizeInput(message="Here is your updated architecture diagram.")
    result = await FINALIZE.handler(args, ctx)

    assert result["action"] == "finalize"
    assert result["message"] == "Here is your updated architecture diagram."


@pytest.mark.asyncio
async def test_finalize_without_message(ctx: ToolContext) -> None:
    """finalize message is optional — None is a valid payload."""
    args = FinalizeInput()
    result = await FINALIZE.handler(args, ctx)

    assert result["action"] == "finalize"
    assert result["message"] is None


# ---------------------------------------------------------------------------
# Registration / mutating=False invariant
# ---------------------------------------------------------------------------


def test_all_reasoning_tools_have_mutating_false() -> None:
    """Reasoning tools must not declare mutating=True — they only mutate state,
    not domain data, and must not trigger the audit-log or mode-guard paths."""
    tools = [
        WRITE_SCRATCHPAD,
        READ_SCRATCHPAD,
        DELEGATE_TO_PLANNER,
        DELEGATE_TO_DIAGRAM,
        DELEGATE_TO_RESEARCHER,
        DELEGATE_TO_CRITIC,
        FINALIZE,
    ]
    for t in tools:
        assert t.mutating is False, f"{t.name} must have mutating=False"
