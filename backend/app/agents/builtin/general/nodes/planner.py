"""Planner node — read-only ReAct loop that produces a structured :class:`Plan`.

The planner is invoked by the supervisor when the user's request needs more
than a one-shot tool call. It investigates the workspace via read-only tools
and emits a single ``Plan`` (validated by the :class:`Plan` Pydantic model)
that the diagram-agent will later execute.

Boundaries:
  * Read-only — :data:`PLANNER_TOOLS` lists only ``search_*`` and ``read_*``
    schemas. Any mutating tool here is a bug; ``test_planner_tools_are_read_only``
    pins this invariant.
  * Output is structured — :func:`make_planner_config` sets ``output_schema=Plan``
    so :func:`run_react` parses the assistant's final JSON. On parse failure,
    ``output.structured`` is ``None`` and the caller (supervisor) decides
    whether to retry; we still return ``output.text`` so a downstream node can
    inspect the raw response.
  * No streaming, no scratchpad blocks — the planner thinks privately and
    returns one JSON document.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from pathlib import Path

from app.agents.context_manager import ContextManager
from app.agents.limits import LimitsEnforcer
from app.agents.llm import LLMCallMetadata
from app.agents.nodes.base import (
    NodeConfig,
    NodeStreamEvent,
    ToolExecutor,
    render_active_context_block,
    render_delegation_brief_block,
    run_react,
)
from app.agents.state import AgentState, Plan

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool schemas (OpenAI shape) — read-only set for the planner.
# ---------------------------------------------------------------------------
#
# These are placeholders that match what the actual tool wrappers (tasks
# 026/027/028) will register at runtime. The schemas here are deliberately
# minimal — the diagram-agent's tool wrapper does the strict Pydantic
# validation at execution time. The planner only needs enough description
# for the LLM to pick a tool and fill its arguments.
#
# IMPORTANT: every tool listed here MUST be read-only. The unit test
# ``test_planner_tools_are_read_only`` greps for forbidden verbs and will
# fail if a mutating tool sneaks in.

PLANNER_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_existing_objects",
            "description": (
                "Semantic + name search over objects already in the workspace. "
                "Always call this before planning a create_object step to avoid "
                "creating duplicates."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "description": (
                            "Optional filter: 'actor', 'system', 'application', "
                            "'store', 'external_dependency', 'component'."
                        ),
                    },
                    "level": {
                        "type": "string",
                        "description": "Optional C4 level filter: 'L1', 'L2', 'L3'.",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_existing_technologies",
            "description": (
                "Search known technology tags (e.g. 'Postgres', 'Redis') so the "
                "planner can reuse them rather than coining new strings."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_object_type_definitions",
            "description": (
                "Return the object kinds and levels the workspace allows. Use "
                "this when unsure whether a kind is permitted."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_object",
            "description": "Return summary metadata for one object by id.",
            "parameters": {
                "type": "object",
                "properties": {"object_id": {"type": "string"}},
                "required": ["object_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_object_full",
            "description": (
                "Return full metadata for one object: relations, tags, "
                "child diagrams, technology, level."
            ),
            "parameters": {
                "type": "object",
                "properties": {"object_id": {"type": "string"}},
                "required": ["object_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_diagram",
            "description": (
                "Return a diagram's nodes, edges, and metadata. Read-only."
            ),
            "parameters": {
                "type": "object",
                "properties": {"diagram_id": {"type": "string"}},
                "required": ["diagram_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dependencies",
            "description": (
                "Return upstream + downstream connections for a single object."
            ),
            "parameters": {
                "type": "object",
                "properties": {"object_id": {"type": "string"}},
                "required": ["object_id"],
                "additionalProperties": False,
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Prompt loader
# ---------------------------------------------------------------------------

# The prompt lives next to the other ``general`` agent prompts. Resolve once
# at import time so unit tests don't pay re-read cost on every config build.
_PROMPT_PATH = (
    Path(__file__).resolve().parents[3] / "prompts" / "general" / "planner.md"
)
_PROMPT_CACHE: str | None = None


def load_planner_prompt() -> str:
    """Return the planner system prompt (cached after first read).

    Reads ``app/agents/prompts/general/planner.md``. The cache is module-level
    so repeated calls (each LangGraph invocation) don't re-touch the disk.
    """
    global _PROMPT_CACHE
    if _PROMPT_CACHE is None:
        _PROMPT_CACHE = _PROMPT_PATH.read_text(encoding="utf-8")
    return _PROMPT_CACHE


# ---------------------------------------------------------------------------
# Config factory
# ---------------------------------------------------------------------------


def make_planner_config(
    tool_executor: ToolExecutor,
    *,
    tool_filter: Callable[[list[dict]], list[dict]] | None = None,
) -> NodeConfig:
    """Build the :class:`NodeConfig` for the planner node.

    - ``max_steps=6`` matches the spec's planner budget (§3.2).
    - ``output_schema=Plan`` so :func:`run_react` parses the final JSON.
    - ``enable_streaming=False`` — the planner returns one JSON object.
    - No ``additional_system_blocks`` — the planner has no scratchpad.
    - ``tool_filter`` — optional callable applied to ``PLANNER_TOOLS`` before
      handing the list to the node (scope/mode filtering by the runtime).

    The caller wires ``tool_executor`` (the dispatcher built by ``tools/base.py``
    in task 026) and is responsible for restricting it to the read-only set
    in :data:`PLANNER_TOOLS`.
    """
    tools = tool_filter(PLANNER_TOOLS) if tool_filter is not None else PLANNER_TOOLS
    return NodeConfig(
        name="planner",
        system_prompt=load_planner_prompt(),
        tools=tools,
        tool_executor=tool_executor,
        max_steps=6,
        output_schema=Plan,
        enable_streaming=False,
        additional_system_blocks=[
            render_active_context_block,
            render_delegation_brief_block,
        ],
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def run(
    state: AgentState,
    *,
    enforcer: LimitsEnforcer,
    context_manager: ContextManager,
    tool_executor: ToolExecutor,
    call_metadata_base: LLMCallMetadata,
) -> AsyncIterator[NodeStreamEvent]:
    """Drive the planner ReAct loop and forward events to the caller.

    Yields the same events :func:`run_react` produces. The terminal
    ``finished`` event carries a :class:`~app.agents.nodes.base.NodeOutput`
    whose ``structured`` field is the parsed :class:`Plan` (or ``None`` on
    parse failure — the supervisor decides whether to retry).

    The caller is expected to apply ``output.structured`` to
    ``state['plan']`` once the loop completes; this node intentionally does
    not mutate state in place so the LangGraph node wrapper stays the only
    place that writes the shared dict.
    """
    cfg = make_planner_config(tool_executor)
    async for event in run_react(
        state,
        cfg,
        enforcer=enforcer,
        context_manager=context_manager,
        call_metadata_base=call_metadata_base,
    ):
        yield event
