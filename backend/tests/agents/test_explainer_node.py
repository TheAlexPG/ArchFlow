"""Tests for app/agents/builtin/diagram_explainer/graph.py.

6 test cases:
  1. Explanation model validation (valid + invalid inputs).
  2. make_explainer_config: max_steps=5, output_schema=Explanation.
  3. EXPLAINER_TOOLS are read-only (no mutating hints in names).
  4. Standalone graph builds — langgraph smoke test.
  5. get_descriptor: surfaces, required_scope, supported_modes.
  6. Stub run with simple LLM response → state_patch contains explanation field.
"""

from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agents.builtin.diagram_explainer.graph import (
    EXPLAINER_TOOLS,
    Explanation,
    build,
    get_descriptor,
    make_explainer_config,
)
from app.agents.context_manager import CompactionResult
from app.agents.llm import LLMCallMetadata, LLMResult
from app.agents.nodes.base import NodeStreamEvent, run_react

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_llm_result(
    *,
    text: str | None = None,
    tool_calls: list[dict] | None = None,
    cost_usd: Decimal = Decimal("0.0005"),
) -> LLMResult:
    return LLMResult(
        text=text,
        tool_calls=tool_calls,
        finish_reason="stop",
        tokens_in=10,
        tokens_out=20,
        cost_usd=cost_usd,
        raw=MagicMock(),
    )


def _make_enforcer(completion_result: LLMResult) -> MagicMock:
    enforcer = MagicMock()
    enforcer.llm = MagicMock()
    enforcer.llm.model = "openai/gpt-4o-mini"
    enforcer.limits = MagicMock()
    enforcer.limits.budget_scope = "per_invocation"
    enforcer.acompletion = AsyncMock(return_value=completion_result)
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


def _make_call_meta() -> LLMCallMetadata:
    return LLMCallMetadata(
        workspace_id=uuid4(),
        agent_id="diagram-explainer",
        session_id=uuid4(),
        actor_id=uuid4(),
        analytics_consent="off",
    )


async def _make_tool_executor(tool_call: dict, state: dict) -> dict:
    return {
        "tool_call_id": tool_call.get("id") or "",
        "status": "ok",
        "content": "{}",
        "preview": "ok",
    }


def _make_state() -> dict:
    return {
        "workspace_id": uuid4(),
        "session_id": uuid4(),
        "messages": [],
        "iteration": 0,
        "tokens_in": 0,
        "tokens_out": 0,
    }


# ---------------------------------------------------------------------------
# 1. Explanation model validation
# ---------------------------------------------------------------------------


class TestExplanationModel:
    def test_valid_minimal(self):
        expl = Explanation(summary="Short summary.")
        assert expl.summary == "Short summary."
        assert expl.relations == []
        assert expl.drill_path == []

    def test_valid_with_relations_and_drill_path(self):
        rel = {"kind": "upstream", "id": str(uuid4()), "name": "Auth Service"}
        expl = Explanation(
            summary="Full explanation.",
            relations=[rel],
            drill_path=["diag-1", "diag-2"],
        )
        assert len(expl.relations) == 1
        assert expl.drill_path == ["diag-1", "diag-2"]

    def test_summary_max_length_enforced(self):
        with pytest.raises(ValidationError):
            Explanation(summary="x" * 16001)

    def test_from_json(self):
        data = {
            "summary": "Explains the API gateway.",
            "relations": [{"kind": "child", "id": "abc", "name": "Child Svc"}],
            "drill_path": ["d1"],
        }
        expl = Explanation.model_validate(data)
        assert expl.relations[0]["kind"] == "child"


# ---------------------------------------------------------------------------
# 2. make_explainer_config: max_steps=5, output_schema=Explanation
# ---------------------------------------------------------------------------


class TestMakeExplainerConfig:
    def test_max_steps_is_5(self):
        cfg = make_explainer_config(_make_tool_executor)
        assert cfg.max_steps == 5

    def test_output_schema_is_explanation(self):
        cfg = make_explainer_config(_make_tool_executor)
        assert cfg.output_schema is Explanation

    def test_name_is_explainer(self):
        cfg = make_explainer_config(_make_tool_executor)
        assert cfg.name == "explainer"

    def test_system_prompt_is_non_empty(self):
        cfg = make_explainer_config(_make_tool_executor)
        assert len(cfg.system_prompt) > 50

    def test_tools_list_set(self):
        cfg = make_explainer_config(_make_tool_executor)
        assert cfg.tools is EXPLAINER_TOOLS


# ---------------------------------------------------------------------------
# 3. EXPLAINER_TOOLS are read-only
# ---------------------------------------------------------------------------


class TestExplainerTools:
    def test_all_tools_have_type_function(self):
        for tool in EXPLAINER_TOOLS:
            assert tool["type"] == "function", f"tool {tool} missing type=function"

    def test_tool_names_are_read_only(self):
        """All tool names must start with 'read_', 'list_', 'dependencies', or 'search_'."""
        read_only_prefixes = ("read_", "list_", "dependencies", "search_")
        for tool in EXPLAINER_TOOLS:
            name = tool["function"]["name"]
            assert name.startswith(read_only_prefixes), (
                f"tool '{name}' does not look read-only"
            )

    def test_expected_tools_present(self):
        names = {t["function"]["name"] for t in EXPLAINER_TOOLS}
        for expected in (
            "read_object",
            "read_object_full",
            "read_diagram",
            "dependencies",
            "list_child_diagrams",
            "read_child_diagram",
            "search_existing_objects",
        ):
            assert expected in names, f"expected tool '{expected}' not found"

    def test_no_mutating_tools(self):
        """No create/update/delete tools should appear in the explainer tool list."""
        mutating_prefixes = ("create_", "update_", "delete_", "place_", "move_", "unplace_")
        for tool in EXPLAINER_TOOLS:
            name = tool["function"]["name"]
            assert not name.startswith(mutating_prefixes), (
                f"mutating tool '{name}' found in EXPLAINER_TOOLS"
            )


# ---------------------------------------------------------------------------
# 4. Standalone graph builds — langgraph smoke test
# ---------------------------------------------------------------------------


class TestBuildGraph:
    def test_build_returns_compiled_graph(self):
        graph = build()
        assert graph is not None

    def test_compiled_graph_has_nodes(self):
        graph = build()
        # LangGraph CompiledStateGraph exposes .nodes or .graph.nodes
        nodes = getattr(graph, "nodes", None) or getattr(
            getattr(graph, "graph", None), "nodes", {}
        )
        node_names = set(nodes.keys()) if nodes else set()
        assert "explainer" in node_names, f"expected 'explainer' node, got: {node_names}"


# ---------------------------------------------------------------------------
# 5. get_descriptor: surfaces, required_scope, supported_modes
# ---------------------------------------------------------------------------


class TestGetDescriptor:
    def test_surfaces(self):
        desc = get_descriptor()
        assert "inline_button" in desc.surfaces
        assert "a2a" in desc.surfaces

    def test_required_scope(self):
        desc = get_descriptor()
        assert desc.required_scope == "agents:read"

    def test_supported_modes(self):
        desc = get_descriptor()
        assert desc.supported_modes == ("read_only",)

    def test_default_budget(self):
        desc = get_descriptor()
        assert desc.default_budget_usd == Decimal("0.05")

    def test_default_turn_limit(self):
        desc = get_descriptor()
        assert desc.default_turn_limit == 20

    def test_tools_overview(self):
        desc = get_descriptor()
        for expected in (
            "read_object_full",
            "dependencies",
            "list_child_diagrams",
            "read_child_diagram",
        ):
            assert expected in desc.tools_overview, (
                f"'{expected}' missing from tools_overview"
            )

    def test_id(self):
        desc = get_descriptor()
        assert desc.id == "diagram-explainer"


# ---------------------------------------------------------------------------
# 6. Stub run — simple LLM response → state_patch contains explanation field
# ---------------------------------------------------------------------------


class TestRunExplainerNode:
    @pytest.mark.asyncio
    async def test_run_produces_explanation_in_state_patch(self):
        explanation_payload = {
            "summary": "This is the API Gateway — entry point for all external traffic.",
            "relations": [{"kind": "downstream", "id": str(uuid4()), "name": "Auth Service"}],
            "drill_path": [],
        }
        llm_result = _make_llm_result(text=json.dumps(explanation_payload))
        enforcer = _make_enforcer(llm_result)
        context_manager = _make_context_manager()
        state = _make_state()
        call_meta = _make_call_meta()

        cfg = make_explainer_config(_make_tool_executor)

        events: list[NodeStreamEvent] = []
        async for ev in run_react(
            state,
            cfg,
            enforcer=enforcer,
            context_manager=context_manager,
            call_metadata_base=call_meta,
        ):
            events.append(ev)

        finished_events = [e for e in events if e.kind == "finished"]
        assert len(finished_events) == 1

        output = finished_events[0].payload["output"]
        assert output.structured is not None, "expected structured Explanation output"
        assert isinstance(output.structured, Explanation)
        assert "API Gateway" in output.structured.summary
        assert output.state_patch is not None
        assert "messages" in output.state_patch

    @pytest.mark.asyncio
    async def test_run_handles_permission_denied_gracefully(self):
        """If the LLM decides not to call any tools after a permission denied scenario,
        it still produces a valid text output (the node should not crash)."""
        sorry_text = json.dumps({
            "summary": "Further details require additional permissions.",
            "relations": [],
            "drill_path": [],
        })
        llm_result = _make_llm_result(text=sorry_text)
        enforcer = _make_enforcer(llm_result)
        context_manager = _make_context_manager()
        state = _make_state()
        call_meta = _make_call_meta()
        cfg = make_explainer_config(_make_tool_executor)

        events: list[NodeStreamEvent] = []
        async for ev in run_react(
            state,
            cfg,
            enforcer=enforcer,
            context_manager=context_manager,
            call_metadata_base=call_meta,
        ):
            events.append(ev)

        finished_events = [e for e in events if e.kind == "finished"]
        assert len(finished_events) == 1
        output = finished_events[0].payload["output"]
        assert output.structured is not None
        assert "additional permissions" in output.structured.summary
