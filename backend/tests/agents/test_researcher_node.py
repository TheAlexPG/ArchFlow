"""Tests for the researcher node and standalone graph.

Covers:
1. Findings model validation (valid / invalid fields).
2. make_researcher_config: max_steps=6, output_schema=Findings, enable_streaming=False.
3. RESEARCHER_TOOLS contains ONLY read-only tools (no create/update/delete/place).
4. Stub LLM returns valid Findings JSON → output.structured set correctly.
5. Standalone graph builds without error (smoke test using langgraph).
6. get_descriptor: surfaces, required_scope, supported_modes.
7. load_researcher_prompt returns non-empty string.
8. run() sets findings on state_patch when structured output is valid.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agents.builtin.general.nodes.researcher import (
    RESEARCHER_TOOLS,
    Findings,
    load_researcher_prompt,
    make_researcher_config,
    run,
)
from app.agents.context_manager import CompactionResult
from app.agents.llm import LLMCallMetadata, LLMResult
from app.agents.nodes.base import NodeStreamEvent

# ---------------------------------------------------------------------------
# Helpers shared with run_react tests
# ---------------------------------------------------------------------------


def _make_call_meta() -> LLMCallMetadata:
    return LLMCallMetadata(
        workspace_id=uuid4(),
        agent_id="researcher",
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
) -> MagicMock:
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


async def _noop_tool_executor(tool_call: dict, state: dict) -> dict:
    return {
        "tool_call_id": tool_call.get("id") or "",
        "status": "ok",
        "content": "{}",
        "preview": "ok",
    }


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
# 1. Findings model validation
# ---------------------------------------------------------------------------


def test_findings_valid_minimal():
    f = Findings(summary="Found 3 services.")
    assert f.summary == "Found 3 services."
    assert f.citations == []
    assert f.confidence == "medium"


def test_findings_valid_full():
    uid = str(uuid4())
    f = Findings(
        summary="## Overview\nSee [Auth](archflow://object/{uid}).",
        citations=[{"type": "object", "id_or_url": uid, "note": "main service"}],
        confidence="high",
    )
    assert f.confidence == "high"
    assert len(f.citations) == 1


def test_findings_summary_max_length_exceeded():
    """summary has max_length=4000; Pydantic v2 enforces this with a ValidationError."""
    with pytest.raises(ValidationError):
        Findings(summary="x" * 4001)


def test_findings_default_confidence_is_medium():
    f = Findings(summary="short")
    assert f.confidence == "medium"


def test_findings_missing_summary_raises():
    with pytest.raises(ValidationError):
        Findings()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# 2. make_researcher_config
# ---------------------------------------------------------------------------


def test_make_researcher_config_max_steps():  # noqa: D103
    """Lowered from 6 → 4 in 2026-05 to stop qwen looping on tool calls (it
    would resolve technology_ids as object_ids, get not-found, retry, and so
    on for the full step budget)."""
    cfg = make_researcher_config(_noop_tool_executor)
    assert cfg.max_steps == 4


def test_make_researcher_config_output_schema():
    cfg = make_researcher_config(_noop_tool_executor)
    assert cfg.output_schema is Findings


def test_make_researcher_config_streaming_disabled():
    cfg = make_researcher_config(_noop_tool_executor)
    assert cfg.enable_streaming is False


def test_make_researcher_config_name():
    cfg = make_researcher_config(_noop_tool_executor)
    assert cfg.name == "researcher"


# ---------------------------------------------------------------------------
# 3. RESEARCHER_TOOLS contains ONLY read-only tools
# ---------------------------------------------------------------------------

_FORBIDDEN_PREFIXES = (
    "create_",
    "update_",
    "delete_",
    "place_",
    "move_",
    "unplace_",
    "link_",
    "unlink_",
    "auto_layout_",
)


def test_researcher_tools_no_mutating_names():
    tool_names = [t["name"] for t in RESEARCHER_TOOLS]
    for name in tool_names:
        for prefix in _FORBIDDEN_PREFIXES:
            assert not name.startswith(prefix), (
                f"RESEARCHER_TOOLS contains mutating tool {name!r} "
                f"(starts with {prefix!r})"
            )


def test_researcher_tools_contains_required_read_tools():
    """Spec mandates these tools are present."""
    required = {
        "read_object_full",
        "dependencies",
        "search_existing_objects",
        "web_fetch",
    }
    tool_names = {t["name"] for t in RESEARCHER_TOOLS}
    assert required.issubset(tool_names), (
        f"Missing required tools: {required - tool_names}"
    )


def test_researcher_tools_is_nonempty():
    assert len(RESEARCHER_TOOLS) > 0


# ---------------------------------------------------------------------------
# 4. Stub LLM returns valid Findings JSON → output.structured set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_findings_json_populates_structured():
    findings_payload = {
        "summary": "## Auth Service\nSingle instance, no replicas.",
        "citations": [{"type": "object", "id_or_url": str(uuid4()), "note": "auth"}],
        "confidence": "high",
    }
    enforcer = _make_enforcer(
        completion_results=[_make_llm_result(text=json.dumps(findings_payload))]
    )
    cm = _make_context_manager()
    state = _make_state(messages=[{"role": "user", "content": "describe auth service"}])

    events = await _collect(
        run(
            state,
            enforcer=enforcer,
            context_manager=cm,
            tool_executor=_noop_tool_executor,
            call_metadata_base=_make_call_meta(),
        )
    )

    finished = [ev for ev in events if ev.kind == "finished"]
    assert len(finished) == 1
    output = finished[0].payload["output"]

    assert output.structured is not None
    assert isinstance(output.structured, Findings)
    assert output.structured.confidence == "high"
    assert "Auth Service" in output.structured.summary


@pytest.mark.asyncio
async def test_findings_injected_into_state_patch():
    """run() must set state_patch['findings'] to the structured Findings."""
    findings_payload = {
        "summary": "Minimal answer.",
        "confidence": "low",
    }
    enforcer = _make_enforcer(
        completion_results=[_make_llm_result(text=json.dumps(findings_payload))]
    )
    cm = _make_context_manager()
    state = _make_state(messages=[{"role": "user", "content": "quick question"}])

    events = await _collect(
        run(
            state,
            enforcer=enforcer,
            context_manager=cm,
            tool_executor=_noop_tool_executor,
            call_metadata_base=_make_call_meta(),
        )
    )

    finished = [ev for ev in events if ev.kind == "finished"]
    output = finished[0].payload["output"]

    assert "findings" in output.state_patch
    assert isinstance(output.state_patch["findings"], Findings)
    assert output.state_patch["findings"].confidence == "low"


@pytest.mark.asyncio
async def test_invalid_json_salvages_text_as_findings_summary():
    """When the LLM returns markdown instead of Findings JSON, the prose is
    salvaged as ``findings.summary`` at low confidence. Discarding it caused
    the supervisor to fall back to "No changes were applied" when the user
    asked a read-only question (qwen and other local models routinely emit
    raw markdown instead of the JSON envelope)."""
    enforcer = _make_enforcer(
        completion_results=[_make_llm_result(text="The diagram has a Web app and a DB.")]
    )
    cm = _make_context_manager()
    state = _make_state(messages=[{"role": "user", "content": "q"}])

    events = await _collect(
        run(
            state,
            enforcer=enforcer,
            context_manager=cm,
            tool_executor=_noop_tool_executor,
            call_metadata_base=_make_call_meta(),
        )
    )

    finished = [ev for ev in events if ev.kind == "finished"]
    output = finished[0].payload["output"]

    assert output.structured is None
    assert "findings" in output.state_patch
    findings = output.state_patch["findings"]
    assert isinstance(findings, Findings)
    assert findings.summary == "The diagram has a Web app and a DB."
    assert findings.confidence == "low"


# ---------------------------------------------------------------------------
# 5. Standalone graph builds without error (smoke test)
# ---------------------------------------------------------------------------


def test_standalone_graph_builds():
    """build() must return a CompiledStateGraph without raising."""
    from app.agents.builtin.researcher.graph import build

    graph = build()
    # CompiledStateGraph is what LangGraph returns after .compile()
    assert graph is not None
    assert hasattr(graph, "invoke") or hasattr(graph, "ainvoke"), (
        "Expected a compiled LangGraph graph with invoke/ainvoke"
    )


# ---------------------------------------------------------------------------
# 6. get_descriptor
# ---------------------------------------------------------------------------


def test_get_descriptor_surfaces():
    from app.agents.builtin.researcher.graph import get_descriptor

    desc = get_descriptor()
    assert "inline_button" in desc.surfaces
    assert "a2a" in desc.surfaces


def test_get_descriptor_required_scope():
    from app.agents.builtin.researcher.graph import get_descriptor

    desc = get_descriptor()
    assert desc.required_scope == "agents:read"


def test_get_descriptor_supported_modes():
    from app.agents.builtin.researcher.graph import get_descriptor

    desc = get_descriptor()
    assert "read_only" in desc.supported_modes


def test_get_descriptor_budget_and_turns():
    from app.agents.builtin.researcher.graph import get_descriptor

    desc = get_descriptor()
    assert desc.default_budget_usd == Decimal("0.20")
    assert desc.default_turn_limit == 50


def test_get_descriptor_tools_overview():
    from app.agents.builtin.researcher.graph import get_descriptor

    desc = get_descriptor()
    assert "read_object_full" in desc.tools_overview
    assert "dependencies" in desc.tools_overview
    assert "search_existing_objects" in desc.tools_overview
    assert "web_fetch" in desc.tools_overview


def test_get_descriptor_id():
    from app.agents.builtin.researcher.graph import get_descriptor

    desc = get_descriptor()
    assert desc.id == "researcher"


# ---------------------------------------------------------------------------
# 7. load_researcher_prompt
# ---------------------------------------------------------------------------


def test_load_researcher_prompt_nonempty():
    prompt = load_researcher_prompt()
    assert isinstance(prompt, str)
    assert len(prompt) > 50  # non-trivial content


def test_load_researcher_prompt_contains_role():
    prompt = load_researcher_prompt()
    # The prompt must describe the researcher role.
    assert "Researcher" in prompt or "researcher" in prompt
