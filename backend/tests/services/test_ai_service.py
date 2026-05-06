"""Tests for app/services/ai_service.py — Phase 1 diagram-explainer delegation.

Mocks runtime.invoke to avoid real DB / LLM calls.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.runtime import ActorRef, InvokeResult
from app.services.ai_service import _parse_legacy_shape, _system_actor, get_insights, is_available

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_invoke_result(final_message: str) -> InvokeResult:
    return InvokeResult(
        session_id=uuid.uuid4(),
        agent_id="diagram-explainer",
        final_message=final_message,
        applied_changes=[],
        tokens_in=10,
        tokens_out=20,
        cost_usd=Decimal("0.001"),
        duration_ms=100,
        forced_finalize=None,
    )


def _make_actor() -> ActorRef:
    return ActorRef(
        kind="user",
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        agent_access="read_only",
    )


# ---------------------------------------------------------------------------
# _system_actor
# ---------------------------------------------------------------------------


def test_system_actor_is_zero_uuid():
    actor = _system_actor()
    assert actor.kind == "user"
    assert actor.id == uuid.UUID(int=0)
    assert actor.workspace_id == uuid.UUID(int=0)
    assert actor.agent_access == "read_only"


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------


def test_is_available_true_when_registered():
    from app.agents import registry
    from app.agents.registry import AgentDescriptor

    descriptor = AgentDescriptor(
        id="diagram-explainer",
        name="Diagram Explainer",
        description="test",
        graph=None,
        surfaces=frozenset(),
        allowed_contexts=frozenset(),
        supported_modes=("read_only",),
    )
    registry.register(descriptor)
    assert is_available() is True


def test_is_available_false_when_not_registered():
    from app.agents import registry

    registry.clear()
    assert is_available() is False


# ---------------------------------------------------------------------------
# _parse_legacy_shape — structured markdown
# ---------------------------------------------------------------------------


def test_parse_full_structured_markdown():
    text = """
## Summary
This is the API Gateway component that routes requests.

## Observations
- Missing authentication configuration
- No rate limiting described
- Unknown downstream dependencies

## Recommendations
- Add authentication details
- Document rate limits
"""
    result = _parse_legacy_shape(text)
    assert "API Gateway" in result["summary"]
    assert len(result["observations"]) == 3
    assert "Missing authentication" in result["observations"][0]
    assert len(result["recommendations"]) == 2
    assert "Add authentication" in result["recommendations"][0]


def test_parse_bold_headers():
    text = """
**Summary**
Short summary here.

**Observations**
- Observation one
- Observation two

**Recommendations**
- Recommendation one
"""
    result = _parse_legacy_shape(text)
    assert "Short summary" in result["summary"]
    assert len(result["observations"]) == 2
    assert len(result["recommendations"]) == 1


def test_parse_numbered_bullets():
    text = """
## Summary
A numbered example.

## Observations
1. First observation
2. Second observation
3. Third observation

## Recommendations
1. First recommendation
2. Second recommendation
"""
    result = _parse_legacy_shape(text)
    assert "numbered" in result["summary"]
    assert len(result["observations"]) == 3
    assert len(result["recommendations"]) == 2


def test_parse_caps_limit_five_observations():
    text = """
## Summary
Summary text.

## Observations
- Obs 1
- Obs 2
- Obs 3
- Obs 4
- Obs 5
- Obs 6 (should be dropped)

## Recommendations
- Rec 1
"""
    result = _parse_legacy_shape(text)
    assert len(result["observations"]) == 5


def test_parse_caps_limit_four_recommendations():
    text = """
## Summary
Summary text.

## Observations
- Obs 1

## Recommendations
- Rec 1
- Rec 2
- Rec 3
- Rec 4
- Rec 5 (should be dropped)
"""
    result = _parse_legacy_shape(text)
    assert len(result["recommendations"]) == 4


def test_parse_summary_truncated_at_500():
    long_text = "x" * 600
    text = f"## Summary\n{long_text}\n\n## Observations\n- obs\n\n## Recommendations\n- rec\n"
    result = _parse_legacy_shape(text)
    assert len(result["summary"]) <= 500


def test_parse_partial_only_summary():
    text = """
## Summary
Only a summary here, no other sections.
"""
    result = _parse_legacy_shape(text)
    assert "Only a summary" in result["summary"]
    assert result["observations"] == []
    assert result["recommendations"] == []


def test_parse_free_form_fallback():
    text = "This is just free-form text without any section headers at all."
    result = _parse_legacy_shape(text)
    assert result["summary"] == text
    assert result["observations"] == []
    assert result["recommendations"] == []


def test_parse_empty_string_fallback():
    result = _parse_legacy_shape("")
    assert result == {"summary": "", "observations": [], "recommendations": []}


def test_parse_case_insensitive_headers():
    text = """
## SUMMARY
Uppercase summary.

## OBSERVATIONS
- Uppercase obs

## RECOMMENDATIONS
- Uppercase rec
"""
    result = _parse_legacy_shape(text)
    assert "Uppercase summary" in result["summary"]
    assert len(result["observations"]) == 1
    assert len(result["recommendations"]) == 1


# ---------------------------------------------------------------------------
# get_insights — integration (mocked runtime.invoke)
# ---------------------------------------------------------------------------


CANNED_MARKDOWN = """
## Summary
The Payment Service handles all billing flows.

## Observations
- No retry logic documented
- Missing SLA targets

## Recommendations
- Add retry configuration
- Document SLAs
"""


@pytest.mark.asyncio
async def test_get_insights_delegates_to_runtime():
    """get_insights calls runtime.invoke and maps its final_message to the legacy shape."""
    object_id = uuid.uuid4()
    actor = _make_actor()

    from app.agents import registry
    from app.agents.registry import AgentDescriptor

    # Ensure diagram-explainer is registered so is_available() is True.
    registry.register(
        AgentDescriptor(
            id="diagram-explainer",
            name="Diagram Explainer",
            description="test",
            graph=None,
            surfaces=frozenset(),
            allowed_contexts=frozenset(),
            supported_modes=("read_only",),
        )
    )

    mock_result = _make_invoke_result(CANNED_MARKDOWN)

    mock_invoke_cm = patch(
        "app.services.ai_service.invoke", new=AsyncMock(return_value=mock_result)
    )
    with mock_invoke_cm as mock_invoke:
        result = await get_insights(object_id=object_id, db=None, actor=actor)  # type: ignore[arg-type]

    mock_invoke.assert_awaited_once()
    call_req = mock_invoke.call_args[0][0]
    assert call_req.agent_id == "diagram-explainer"
    assert call_req.mode == "read_only"
    assert call_req.chat_context.kind == "object"
    assert call_req.chat_context.id == object_id
    assert call_req.actor is actor

    assert "Payment Service" in result["summary"]
    assert len(result["observations"]) == 2
    assert len(result["recommendations"]) == 2


@pytest.mark.asyncio
async def test_get_insights_uses_system_actor_when_none_provided():
    object_id = uuid.uuid4()

    from app.agents import registry
    from app.agents.registry import AgentDescriptor

    registry.register(
        AgentDescriptor(
            id="diagram-explainer",
            name="Diagram Explainer",
            description="test",
            graph=None,
            surfaces=frozenset(),
            allowed_contexts=frozenset(),
            supported_modes=("read_only",),
        )
    )

    mock_result = _make_invoke_result("free form fallback text")

    with patch("app.services.ai_service.invoke", new=AsyncMock(return_value=mock_result)):
        result = await get_insights(object_id=object_id, db=None)  # type: ignore[arg-type]

    # fallback: summary is the whole text, lists empty
    assert result["summary"] == "free form fallback text"
    assert result["observations"] == []
    assert result["recommendations"] == []


@pytest.mark.asyncio
async def test_get_insights_raises_when_agent_not_registered():
    from app.agents import registry

    registry.clear()

    with pytest.raises(RuntimeError, match="diagram-explainer agent not registered"):
        await get_insights(object_id=uuid.uuid4(), db=None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_get_insights_workspace_id_from_actor():
    """workspace_id on the InvokeRequest is taken from the actor."""
    ws_id = uuid.uuid4()
    actor = ActorRef(kind="user", id=uuid.uuid4(), workspace_id=ws_id, agent_access="read_only")
    object_id = uuid.uuid4()

    from app.agents import registry
    from app.agents.registry import AgentDescriptor

    registry.register(
        AgentDescriptor(
            id="diagram-explainer",
            name="Diagram Explainer",
            description="test",
            graph=None,
            surfaces=frozenset(),
            allowed_contexts=frozenset(),
            supported_modes=("read_only",),
        )
    )

    mock_result = _make_invoke_result("")

    mock_invoke_cm = patch(
        "app.services.ai_service.invoke", new=AsyncMock(return_value=mock_result)
    )
    with mock_invoke_cm as mock_invoke:
        await get_insights(object_id=object_id, db=None, actor=actor)  # type: ignore[arg-type]

    call_req = mock_invoke.call_args[0][0]
    assert call_req.workspace_id == ws_id
