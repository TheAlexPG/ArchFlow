"""Standalone researcher agent: single-node graph wrapping the same node function."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

from app.agents.registry import AgentDescriptor
from app.agents.state import AgentState


def build() -> CompiledStateGraph:
    """Build standalone researcher graph: START → researcher → END.

    Reuses general/nodes/researcher.run as the single node.  The node is
    wrapped in a thin async adapter that matches the LangGraph
    ``async (state) -> dict`` signature expected by StateGraph.add_node.

    The actual ReAct driving (run_react), enforcer, context_manager, and
    tool_executor are injected at invocation time by the runtime via
    LangGraph's RunnableConfig ``configurable`` namespace — the graph itself
    is stateless.
    """
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import RunnableConfig

    from app.agents.builtin.general.nodes.researcher import run as _researcher_run

    async def _researcher_node(
        state: AgentState, config: Optional[RunnableConfig] = None
    ) -> dict:
        """Thin LangGraph adapter: pulls runtime deps from config.configurable
        and collects NodeStreamEvents, returning the final state_patch."""
        cfg_extras: dict = {}
        if config is not None and hasattr(config, "get") or isinstance(config, dict):
            cfg_extras = config.get("configurable", {}) or {}

        enforcer = cfg_extras.get("enforcer")
        context_manager = cfg_extras.get("context_manager")
        tool_executor = cfg_extras.get("tool_executor")
        call_metadata_base = cfg_extras.get("call_metadata_base")

        if any(
            dep is None
            for dep in [enforcer, context_manager, tool_executor, call_metadata_base]
        ):
            raise RuntimeError(
                "Standalone researcher graph requires 'enforcer', 'context_manager', "
                "'tool_executor', and 'call_metadata_base' in config['configurable']. "
                "These must be injected by the runtime before invoking the graph."
            )

        state_patch: dict = {}
        async for event in _researcher_run(
            state,
            enforcer=enforcer,
            context_manager=context_manager,
            tool_executor=tool_executor,
            call_metadata_base=call_metadata_base,
        ):
            if event.kind == "finished":
                output = event.payload["output"]
                state_patch.update(output.state_patch)
        return state_patch

    builder: StateGraph = StateGraph(AgentState)
    builder.add_node("researcher", _researcher_node)
    builder.add_edge(START, "researcher")
    builder.add_edge("researcher", END)
    return builder.compile()


# ---------------------------------------------------------------------------
# AgentDescriptor
# ---------------------------------------------------------------------------


def get_descriptor() -> AgentDescriptor:
    """Return AgentDescriptor for the standalone researcher agent.

    Surfaces: ('inline_button', 'a2a').
    required_scope: 'agents:read'.
    Default budget $0.20, turns=50.
    tools_overview: ('read_object_full', 'dependencies', 'search_existing_objects', 'web_fetch').
    """
    return AgentDescriptor(
        id="researcher",
        name="Researcher",
        description=(
            "Read-only fact-finder. Explores the workspace C4 model and public URLs "
            "to answer questions and surface structured findings — without making any changes."
        ),
        schema_version="v1",
        graph=build(),
        surfaces=frozenset({"inline_button", "a2a"}),
        allowed_contexts=frozenset({"workspace", "diagram", "object", "none"}),
        supported_modes=("read_only",),
        required_scope="agents:read",
        tools_overview=(
            "read_object_full",
            "dependencies",
            "search_existing_objects",
            "web_fetch",
        ),
        default_turn_limit=50,
        default_budget_usd=Decimal("0.20"),
        default_budget_scope="per_invocation",
        streaming=False,
    )
