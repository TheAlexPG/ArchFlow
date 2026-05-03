"""
Critic node — read-only ReAct loop that reviews applied_changes against the
original user goal and emits a structured Critique (APPROVE | REVISE).

If REVISE and ``state['iteration'] < MAX_CRITIQUE_LOOPS``, the graph routes
back to the planner with the revision_request.  Otherwise the supervisor
finalises with issues listed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from app.agents.nodes.base import (
    NodeConfig,
    NodeStreamEvent,
    ToolExecutor,
    render_active_context_block,
    render_delegation_brief_block,
    run_react,
)
from app.agents.state import AgentState, Critique

# ---------------------------------------------------------------------------
# Tool list — read-only subset (same as researcher, minus web_fetch)
# ---------------------------------------------------------------------------

CRITIC_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "read_object",
            "description": (
                "Read basic projection of a single model-level object "
                "(id, name, type, parent_id, has_child_diagram, technology_ids)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "object_id": {
                        "type": "string",
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
                "Read full projection of a model-level object including "
                "plain-text description, tags, and owner."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "object_id": {
                        "type": "string",
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
                "Read diagram metadata, placements, and connections. "
                "Returns objects placed on the diagram and their connections."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "diagram_id": {
                        "type": "string",
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
                "Return upstream and downstream objects for a given object. "
                "Depth 1 = direct connections only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "object_id": {
                        "type": "string",
                        "description": "UUID of the object to inspect.",
                    },
                    "depth": {
                        "type": "integer",
                        "description": "How many hops to traverse (default 1).",
                        "default": 1,
                    },
                },
                "required": ["object_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_objects",
            "description": (
                "List model-level objects in the workspace. Supports filtering "
                "by type, parent_id, with pagination."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by object types (empty = all).",
                        "default": [],
                    },
                    "parent_id": {
                        "type": "string",
                        "description": "Optional parent object UUID to filter children.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results per page (default 50).",
                        "default": 50,
                    },
                    "cursor": {
                        "type": "string",
                        "description": "Pagination cursor from a previous response.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_diagrams",
            "description": (
                "List diagrams in the workspace. Supports filtering by level "
                "and parent_object_id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "level": {
                        "type": "string",
                        "enum": ["L1", "L2", "L3", "L4"],
                        "description": "Filter by diagram level.",
                    },
                    "parent_object_id": {
                        "type": "string",
                        "description": "Filter diagrams that are children of this object.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results per page (default 50).",
                        "default": 50,
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_child_diagrams",
            "description": (
                "List child diagrams attached to a specific parent object."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_object_id": {
                        "type": "string",
                        "description": "UUID of the parent object.",
                    }
                },
                "required": ["parent_object_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_existing_objects",
            "description": (
                "Full-text search for existing objects in the workspace. "
                "Always call this before creating a new object to avoid duplicates."
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
                        "description": "Optionally filter by object type.",
                        "default": [],
                    },
                    "scope": {
                        "type": "string",
                        "enum": ["workspace", "diagram"],
                        "description": "Search scope (default 'workspace').",
                        "default": "workspace",
                    },
                },
                "required": ["query"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Prompt loader
# ---------------------------------------------------------------------------

_PROMPT_CACHE: str | None = None


def load_critic_prompt() -> str:
    """Load and cache the critic system prompt from prompts/general/critic.md."""
    global _PROMPT_CACHE
    if _PROMPT_CACHE is not None:
        return _PROMPT_CACHE

    # Resolve relative to this file: backend/app/agents/prompts/general/critic.md
    prompt_path = (
        Path(__file__).parent.parent.parent.parent  # app/agents/
        / "prompts"
        / "general"
        / "critic.md"
    )
    _PROMPT_CACHE = prompt_path.read_text(encoding="utf-8")
    return _PROMPT_CACHE


# ---------------------------------------------------------------------------
# System block renderers
# ---------------------------------------------------------------------------


def render_goal_block(state: AgentState) -> str:
    """Return the original user goal (first user message) as a system block.

    The critic compares applied_changes against this goal to assess coverage.
    Returns an empty string when no user messages are found (defensive).
    """
    messages: list[dict] = state.get("messages") or []
    for msg in messages:
        if msg.get("role") == "user":
            content = msg.get("content") or ""
            if content:
                return f"## Original user goal\n{content}"
    return ""


def render_applied_changes_for_critic(state: AgentState) -> str:
    """Render state.applied_changes as a structured markdown block for review.

    Returns a sentinel string when the list is empty so the critic prompt
    can explicitly detect the no-changes case.
    """
    applied: list[dict] = state.get("applied_changes") or []
    if not applied:
        return "## Applied changes\n(no changes to review)"

    lines = ["## Applied changes"]
    for i, change in enumerate(applied, start=1):
        action = change.get("action", "unknown")
        target_type = change.get("target_type", "")
        name = change.get("name") or str(change.get("target_id", ""))
        target_id = change.get("target_id", "")
        metadata = change.get("metadata")
        parent_id = metadata.get("parent_id") if isinstance(metadata, dict) else None

        line = f"{i}. `{action}` — {target_type} **{name}** (id={target_id})"
        if parent_id:
            line += f", parent={parent_id}"
        lines.append(line)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# NodeConfig factory
# ---------------------------------------------------------------------------


def make_critic_config(
    tool_executor: ToolExecutor,
    *,
    tool_filter: Callable[[list[dict]], list[dict]] | None = None,
) -> NodeConfig:
    """Build the NodeConfig for the critic ReAct loop.

    - max_steps=6 (enough to gather evidence + produce verdict)
    - output_schema=Critique (structured JSON output)
    - additional_system_blocks render the original goal and applied changes
    - ``tool_filter`` — optional callable applied to ``CRITIC_TOOLS`` for
      scope/mode enforcement by the runtime.
    """
    tools = tool_filter(CRITIC_TOOLS) if tool_filter is not None else CRITIC_TOOLS
    return NodeConfig(
        name="critic",
        system_prompt=load_critic_prompt(),
        tools=tools,
        tool_executor=tool_executor,
        max_steps=6,
        output_schema=Critique,
        additional_system_blocks=[
            render_active_context_block,
            render_delegation_brief_block,
            render_goal_block,
            render_applied_changes_for_critic,
        ],
    )


# ---------------------------------------------------------------------------
# Node entry point
# ---------------------------------------------------------------------------


async def run(
    state: AgentState,
    *,
    enforcer: Any,
    context_manager: Any,
    tool_executor: ToolExecutor,
    call_metadata_base: Any,
) -> AsyncIterator[NodeStreamEvent]:
    """Execute the critic ReAct loop.

    Yields :class:`NodeStreamEvent` events.  The terminal ``'finished'`` event
    carries a :class:`NodeOutput` whose ``structured`` field is the parsed
    :class:`Critique` instance.

    The **caller** (graph wiring, task 025) is responsible for:
    - Storing ``output.structured`` as ``state_patch['critique']``.
    - Routing: if ``critique.verdict == 'REVISE'`` and
      ``state['iteration'] < MAX_CRITIQUE_LOOPS`` → increment iteration and
      route back to planner. Otherwise → finalize.
    """
    cfg = make_critic_config(tool_executor)
    async for event in run_react(
        state,
        cfg,
        enforcer=enforcer,
        context_manager=context_manager,
        call_metadata_base=call_metadata_base,
    ):
        # Intercept 'finished' to stash structured output into state_patch.
        if event.kind == "finished":
            output = event.payload.get("output")
            if output is not None and output.structured is not None:
                output.state_patch["critique"] = output.structured
        yield event
