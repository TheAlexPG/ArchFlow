"""Diagram-explainer micro-agent: ReAct loop with drill-into-children read tools.
Single-node graph. Used by inline 'AI explain' button + A2A surfaces.
Recommended cheap model (haiku, gpt-4o-mini) per AGENT_DEFAULTS."""

from __future__ import annotations

import importlib.resources
from collections.abc import AsyncIterator, Callable
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, Field

from app.agents.nodes.base import NodeConfig, NodeStreamEvent, ToolExecutor, run_react
from app.agents.registry import AgentDescriptor
from app.agents.state import AgentState

if TYPE_CHECKING:
    from langgraph.types import RunnableConfig


# ---------------------------------------------------------------------------
# Tool definitions (OpenAI-shape dicts)
# ---------------------------------------------------------------------------

EXPLAINER_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "read_object",
            "description": "Return quick metadata for an object (name, type, description).",
            "parameters": {
                "type": "object",
                "properties": {
                    "object_id": {
                        "type": "string",
                        "format": "uuid",
                        "description": "UUID of the object to read.",
                    }
                },
                "required": ["object_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_object_full",
            "description": (
                "Return full object detail including technologies, status, "
                "and linked child diagram."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "object_id": {
                        "type": "string",
                        "format": "uuid",
                        "description": "UUID of the object to read.",
                    }
                },
                "required": ["object_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_diagram",
            "description": (
                "Return diagram metadata including all placements and connections."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "diagram_id": {
                        "type": "string",
                        "format": "uuid",
                        "description": "UUID of the diagram to read.",
                    }
                },
                "required": ["diagram_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dependencies",
            "description": (
                "Return upstream and downstream connections for an object up to a given depth."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "object_id": {
                        "type": "string",
                        "format": "uuid",
                        "description": "UUID of the object whose dependencies to fetch.",
                    },
                    "depth": {
                        "type": "integer",
                        "default": 1,
                        "description": "How many hops to traverse (1–3).",
                    },
                },
                "required": ["object_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_child_diagrams",
            "description": (
                "List diagrams linked as children of an object (drill-down targets)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "object_id": {
                        "type": "string",
                        "format": "uuid",
                        "description": "UUID of the parent object.",
                    }
                },
                "required": ["object_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_child_diagram",
            "description": (
                "Read a child diagram one level deeper (drill-down). "
                "Only call when the parent has child diagrams and drilling adds "
                "significant detail. Maximum 2 drill levels total."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "diagram_id": {
                        "type": "string",
                        "format": "uuid",
                        "description": "UUID of the child diagram to read.",
                    }
                },
                "required": ["diagram_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_existing_objects",
            "description": (
                "Full-text search workspace objects by name or keyword. "
                "Use to locate related objects referenced by the focus object."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query string.",
                    },
                    "types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional object type filter.",
                    },
                    "scope": {
                        "type": "string",
                        "default": "workspace",
                        "description": "Search scope: 'workspace' (default).",
                    },
                },
                "required": ["query"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


class Explanation(BaseModel):
    summary: str = Field(..., max_length=4000)
    relations: list[dict] = Field(
        default_factory=list,
        description=(
            "[{kind:'parent'|'child'|'upstream'|'downstream', id, name}]"
        ),
    )
    drill_path: list[str] = Field(
        default_factory=list,
        description="diagram_ids visited during drill-down (audit)",
    )


# ---------------------------------------------------------------------------
# Prompt loader
# ---------------------------------------------------------------------------


def load_explainer_prompt() -> str:
    """Load the system prompt from the adjacent prompts directory.

    Falls back to reading via a direct path when the package traversal is
    unavailable (e.g. editable installs without __spec__).
    """
    try:
        pkg = importlib.resources.files("app.agents.prompts.diagram_explainer")
        return (pkg / "system.md").read_text(encoding="utf-8")
    except (TypeError, ModuleNotFoundError, FileNotFoundError):
        import pathlib

        here = pathlib.Path(__file__).parent
        prompt_path = here.parent.parent / "prompts" / "diagram_explainer" / "system.md"
        return prompt_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# NodeConfig factory
# ---------------------------------------------------------------------------


def make_explainer_config(
    tool_executor: ToolExecutor,
    *,
    tool_filter: Callable[[list[dict]], list[dict]] | None = None,
) -> NodeConfig:
    """Return a NodeConfig for the diagram-explainer with max_steps=5 and Explanation schema.

    ``tool_filter`` — optional callable applied to ``EXPLAINER_TOOLS`` for
    scope/mode filtering by the runtime.
    """
    tools = tool_filter(EXPLAINER_TOOLS) if tool_filter is not None else EXPLAINER_TOOLS
    return NodeConfig(
        name="explainer",
        system_prompt=load_explainer_prompt(),
        tools=tools,
        tool_executor=tool_executor,
        max_steps=5,
        output_schema=Explanation,
    )


# ---------------------------------------------------------------------------
# Node run function
# ---------------------------------------------------------------------------


async def run(
    state: AgentState,
    *,
    enforcer: Any,
    context_manager: Any,
    tool_executor: ToolExecutor,
    call_metadata_base: Any,
) -> AsyncIterator[NodeStreamEvent]:
    """ReAct loop for the diagram-explainer node.

    Delegates entirely to :func:`run_react` with the explainer config.
    Yields :class:`NodeStreamEvent` events; the caller collects the
    ``'finished'`` event to extract ``NodeOutput``.
    """
    cfg = make_explainer_config(tool_executor)
    async for event in run_react(
        state,
        cfg,
        enforcer=enforcer,
        context_manager=context_manager,
        call_metadata_base=call_metadata_base,
    ):
        yield event


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build() -> Any:
    """Build and compile the standalone diagram-explainer graph.

    Graph topology: START → explainer → END.

    The node is a thin async wrapper that runs the explainer ReAct loop and
    returns a state patch. Injected dependencies (enforcer, context_manager,
    tool_executor, call_metadata_base) are passed via LangGraph's ``config``
    dict at invoke time.
    """
    from langgraph.graph import END, START, StateGraph

    from app.agents.state import AgentState

    async def _explainer_node(state: AgentState, config: Optional[RunnableConfig] = None) -> dict:
        cfg_vals = (config or {}).get("configurable", {})
        enforcer = cfg_vals.get("enforcer")
        context_manager = cfg_vals.get("context_manager")
        tool_executor = cfg_vals.get("tool_executor")
        call_metadata_base = cfg_vals.get("call_metadata_base")

        node_cfg = make_explainer_config(tool_executor)

        output = None
        async for event in run_react(
            state,
            node_cfg,
            enforcer=enforcer,
            context_manager=context_manager,
            call_metadata_base=call_metadata_base,
        ):
            if event.kind == "finished":
                output = event.payload["output"]

        if output is None:
            return {}

        patch = dict(output.state_patch)
        if output.structured is not None:
            patch["explanation"] = output.structured
        elif output.text is not None:
            patch["explanation"] = output.text
        return patch

    builder: StateGraph = StateGraph(AgentState)
    builder.add_node("explainer", _explainer_node)
    builder.add_edge(START, "explainer")
    builder.add_edge("explainer", END)
    return builder.compile()


# ---------------------------------------------------------------------------
# Descriptor
# ---------------------------------------------------------------------------


def get_descriptor() -> AgentDescriptor:
    """Return the AgentDescriptor for the diagram-explainer agent.

    Surfaces: ('inline_button', 'a2a').
    required_scope='agents:read'.
    supported_modes=('read_only',).
    Default budget $0.05, turns=20.
    tools_overview: ('read_object_full', 'dependencies', 'list_child_diagrams',
    'read_child_diagram').
    """
    return AgentDescriptor(
        id="diagram-explainer",
        name="Diagram Explainer",
        description=(
            "Explains a single architecture object or diagram concisely. "
            "Drills into child diagrams up to two levels to provide meaningful context."
        ),
        surfaces=frozenset({"inline_button", "a2a"}),
        allowed_contexts=frozenset({"diagram", "object"}),
        supported_modes=("read_only",),
        required_scope="agents:read",
        tools_overview=(
            "read_object_full",
            "dependencies",
            "list_child_diagrams",
            "read_child_diagram",
        ),
        default_turn_limit=20,
        default_budget_usd=Decimal("0.05"),
        default_budget_scope="per_invocation",
        streaming=False,
        graph=build(),
    )
