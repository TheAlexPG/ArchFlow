"""Diagram-agent node — mutating ReAct loop.

Executes the planner's plan steps via mutating tools (create/update/delete +
view-layer placement + diagrams + layout + drafts), recovers from tool errors,
and surfaces applied changes back to the supervisor.

Owns:
  * :data:`DIAGRAM_TOOLS` — OpenAI-shape tool schemas exposed to the LLM. The
    tool *implementations* live in ``app/agents/tools/{model,view,search,
    drafts}_tools.py`` (tasks 026–031). ``run_react`` only sees the schemas
    here and dispatches via ``tool_executor`` (task 026 wraps the Tool
    dataclass-based handlers behind a uniform async callable).
  * :func:`render_pending_changes_block` / :func:`render_active_diagram_block`
    — system-block renderers attached to ``NodeConfig.additional_system_blocks``
    so the LLM always sees the current plan progress and active draft target.
  * :func:`make_diagram_config` — composes a ``NodeConfig`` with ``max_steps=200``
    per spec §3.3 ("Diagram-agent: ReAct loop, max 10 steps").
  * :func:`run` — async generator wrapping :func:`run_react`. After the loop
    finishes, parses tool results to accumulate ``applied_changes`` and marks
    plan steps done.

Does NOT own:
  * Tool execution / ACL / audit — delegated to the runtime's ``tool_executor``
    (task 026 wires those).
  * Plan generation — that's the planner node (task 019).
  * Final user-facing message — that's the finalize node (already implemented).
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from app.agents.context_manager import ContextManager
from app.agents.limits import LimitsEnforcer
from app.agents.llm import LLMCallMetadata
from app.agents.nodes.base import (
    NodeConfig,
    NodeStreamEvent,
    ToolExecutor,
    run_react,
)
from app.agents.state import AgentState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# OpenAI-shape tool schemas
# ---------------------------------------------------------------------------
#
# These are the ``tools`` field passed into LiteLLM via ``LLMClient.acompletion``.
# Every entry must be ``{"type": "function", "function": {name, description,
# parameters}}`` with a JSON Schema in ``parameters``. Mirrors the Pydantic
# ``input_schema`` declared on the corresponding ``Tool`` instance in
# ``app/agents/tools/*_tools.py``.
#
# Categories tagged in the description prefix so tests / introspection can
# assert coverage:
#   [READ]   read_*, list_*, dependencies, search_*
#   [WRITE]  create_*, update_*, delete_*, place_*, move_*, unplace_*,
#            link_*, unlink_*, auto_layout_*
#   [DRAFTS] fork_diagram_to_draft, list_active_drafts
#
# Reasoning tools (delegate_*, write_scratchpad, finalize) are explicitly
# NOT included — those belong to the supervisor only (spec §3.3 / §4.6).


def _fn(name: str, description: str, parameters: dict) -> dict:
    """Wrap one OpenAI-shape function tool definition."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


# ---- READ tools (verify-after-mutate) ------------------------------------

_READ_OBJECT = _fn(
    "read_object",
    "[READ] Return basic projection of an object by ID.",
    {
        "type": "object",
        "properties": {"object_id": {"type": "string", "format": "uuid"}},
        "required": ["object_id"],
    },
)

_READ_OBJECT_FULL = _fn(
    "read_object_full",
    "[READ] Return full object details (description plain-text, tags, owner).",
    {
        "type": "object",
        "properties": {"object_id": {"type": "string", "format": "uuid"}},
        "required": ["object_id"],
    },
)

_READ_DIAGRAM = _fn(
    "read_diagram",
    "[READ] Return diagram metadata with placements and connections.",
    {
        "type": "object",
        "properties": {"diagram_id": {"type": "string", "format": "uuid"}},
        "required": ["diagram_id"],
    },
)

_READ_CANVAS_STATE = _fn(
    "read_canvas_state",
    "[READ] Return canvas coords + dimensions for all placed objects on a diagram. "
    "Use this to verify placements after a batch of mutations.",
    {
        "type": "object",
        "properties": {"diagram_id": {"type": "string", "format": "uuid"}},
        "required": ["diagram_id"],
    },
)

_DEPENDENCIES = _fn(
    "dependencies",
    "[READ] Return upstream + downstream dependencies of an object up to depth hops.",
    {
        "type": "object",
        "properties": {
            "object_id": {"type": "string", "format": "uuid"},
            "depth": {"type": "integer", "default": 1},
        },
        "required": ["object_id"],
    },
)

_LIST_OBJECTS = _fn(
    "list_objects",
    "[READ] Paginated list of workspace objects, optional type/parent filters.",
    {
        "type": "object",
        "properties": {
            "types": {"type": "array", "items": {"type": "string"}},
            "parent_id": {"type": "string", "format": "uuid"},
            "limit": {"type": "integer", "default": 50},
            "cursor": {"type": "string"},
        },
    },
)

_LIST_DIAGRAMS = _fn(
    "list_diagrams",
    "[READ] Paginated list of diagrams, optional level/parent filters.",
    {
        "type": "object",
        "properties": {
            "level": {"type": "string", "enum": ["L1", "L2", "L3", "L4"]},
            "parent_object_id": {"type": "string", "format": "uuid"},
            "limit": {"type": "integer", "default": 50},
        },
    },
)

_SEARCH_EXISTING_OBJECTS = _fn(
    "search_existing_objects",
    "[READ] Search workspace objects by name. ALWAYS call before create_object.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "types": {"type": "array", "items": {"type": "string"}},
            "scope": {"type": "string", "default": "workspace"},
        },
        "required": ["query"],
    },
)

_SEARCH_EXISTING_TECHNOLOGIES = _fn(
    "search_existing_technologies",
    "[READ] Search the technology catalog. ALWAYS call before attaching technology_ids.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "kind": {"type": "string"},
        },
        "required": ["query"],
    },
)

_LIST_OBJECT_TYPE_DEFINITIONS = _fn(
    "list_object_type_definitions",
    "[READ] List valid object type definitions with C4 level constraints.",
    {"type": "object", "properties": {}},
)

_LIST_CONNECTION_PROTOCOLS = _fn(
    "list_connection_protocols",
    "[READ] List available connection protocol / technology options.",
    {"type": "object", "properties": {}},
)


# ---- WRITE tools — model layer -------------------------------------------

_CREATE_OBJECT = _fn(
    "create_object",
    "[WRITE] Create a NEW model-level object. The object will exist in the "
    "workspace model but won't appear on any diagram until you call "
    "place_on_diagram. ALWAYS call search_existing_objects first to avoid "
    "duplicates.",
    {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "type": {"type": "string"},
            "parent_id": {"type": "string", "format": "uuid"},
            "technology_ids": {
                "type": "array",
                "items": {"type": "string", "format": "uuid"},
            },
            "description": {"type": "string"},
            "status": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["name", "type"],
    },
)

_UPDATE_OBJECT = _fn(
    "update_object",
    "[WRITE] Apply a partial patch to an existing object.",
    {
        "type": "object",
        "properties": {
            "object_id": {"type": "string", "format": "uuid"},
            "patch": {"type": "object"},
        },
        "required": ["object_id", "patch"],
    },
)

_DELETE_OBJECT = _fn(
    "delete_object",
    "[WRITE] Delete an object. First call without confirmed returns impact preview; "
    "re-call with confirmed=True to execute.",
    {
        "type": "object",
        "properties": {
            "object_id": {"type": "string", "format": "uuid"},
            "confirmed": {"type": "boolean", "default": False},
        },
        "required": ["object_id"],
    },
)

_CREATE_CONNECTION = _fn(
    "create_connection",
    "[WRITE] Create a new model-level connection between two objects.",
    {
        "type": "object",
        "properties": {
            "source_object_id": {"type": "string", "format": "uuid"},
            "target_object_id": {"type": "string", "format": "uuid"},
            "label": {"type": "string"},
            "direction": {"type": "string", "default": "outgoing"},
            "technology_ids": {
                "type": "array",
                "items": {"type": "string", "format": "uuid"},
            },
            "description": {"type": "string"},
        },
        "required": ["source_object_id", "target_object_id"],
    },
)

_UPDATE_CONNECTION = _fn(
    "update_connection",
    "[WRITE] Apply a partial patch to an existing connection.",
    {
        "type": "object",
        "properties": {
            "connection_id": {"type": "string", "format": "uuid"},
            "patch": {"type": "object"},
        },
        "required": ["connection_id", "patch"],
    },
)

_DELETE_CONNECTION = _fn(
    "delete_connection",
    "[WRITE] Delete a connection. First call without confirmed returns preview.",
    {
        "type": "object",
        "properties": {
            "connection_id": {"type": "string", "format": "uuid"},
            "confirmed": {"type": "boolean", "default": False},
        },
        "required": ["connection_id"],
    },
)

# ---- WRITE tools — view layer (per diagram) ------------------------------

_PLACE_ON_DIAGRAM = _fn(
    "place_on_diagram",
    "[WRITE] Place an existing model object on a diagram. If x/y are omitted, "
    "the layout engine computes a non-overlapping position. Pair with "
    "create_object to make a new object visible.",
    {
        "type": "object",
        "properties": {
            "diagram_id": {"type": "string", "format": "uuid"},
            "object_id": {"type": "string", "format": "uuid"},
            "x": {"type": "number"},
            "y": {"type": "number"},
            "width": {"type": "number"},
            "height": {"type": "number"},
        },
        "required": ["diagram_id", "object_id"],
    },
)

_MOVE_ON_DIAGRAM = _fn(
    "move_on_diagram",
    "[WRITE] Move an already-placed object to new coordinates on a diagram.",
    {
        "type": "object",
        "properties": {
            "diagram_id": {"type": "string", "format": "uuid"},
            "object_id": {"type": "string", "format": "uuid"},
            "x": {"type": "number"},
            "y": {"type": "number"},
        },
        "required": ["diagram_id", "object_id", "x", "y"],
    },
)

_UNPLACE_FROM_DIAGRAM = _fn(
    "unplace_from_diagram",
    "[WRITE] Remove an object's placement from a diagram (does not delete the object). "
    "Requires confirmed=True.",
    {
        "type": "object",
        "properties": {
            "diagram_id": {"type": "string", "format": "uuid"},
            "object_id": {"type": "string", "format": "uuid"},
            "confirmed": {"type": "boolean", "default": False},
        },
        "required": ["diagram_id", "object_id"],
    },
)

# ---- WRITE tools — diagrams + hierarchy ----------------------------------

_CREATE_DIAGRAM = _fn(
    "create_diagram",
    "[WRITE] Create a new diagram at the given C4 level.",
    {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "level": {"type": "string", "enum": ["L1", "L2", "L3", "L4"]},
            "parent_object_id": {"type": "string", "format": "uuid"},
            "description": {"type": "string"},
        },
        "required": ["name", "level"],
    },
)

_UPDATE_DIAGRAM = _fn(
    "update_diagram",
    "[WRITE] Apply a patch to an existing diagram's metadata.",
    {
        "type": "object",
        "properties": {
            "diagram_id": {"type": "string", "format": "uuid"},
            "patch": {"type": "object"},
        },
        "required": ["diagram_id", "patch"],
    },
)

_DELETE_DIAGRAM = _fn(
    "delete_diagram",
    "[WRITE] Delete a diagram. First call returns impact preview; re-call with confirmed=True.",
    {
        "type": "object",
        "properties": {
            "diagram_id": {"type": "string", "format": "uuid"},
            "confirmed": {"type": "boolean", "default": False},
        },
        "required": ["diagram_id"],
    },
)

_LINK_OBJECT_TO_CHILD_DIAGRAM = _fn(
    "link_object_to_child_diagram",
    "[WRITE] Link an object to a child diagram (drill-down relationship).",
    {
        "type": "object",
        "properties": {
            "object_id": {"type": "string", "format": "uuid"},
            "child_diagram_id": {"type": "string", "format": "uuid"},
        },
        "required": ["object_id", "child_diagram_id"],
    },
)

_CREATE_CHILD_DIAGRAM_FOR_OBJECT = _fn(
    "create_child_diagram_for_object",
    "[WRITE] Composite: create a diagram and immediately link it to an object as its child.",
    {
        "type": "object",
        "properties": {
            "object_id": {"type": "string", "format": "uuid"},
            "name": {"type": "string"},
            "level": {"type": "string", "enum": ["L1", "L2", "L3", "L4"]},
        },
        "required": ["object_id"],
    },
)

# ---- WRITE tools — layout ------------------------------------------------

_AUTO_LAYOUT_DIAGRAM = _fn(
    "auto_layout_diagram",
    "[WRITE] Run the C4-aware layout engine on a diagram. scope='new_only' "
    "(default) only repositions objects without explicit positions. scope='all' "
    "repositions everything — only when user explicitly requests. Use this once "
    "after a batch of placements if the diagram looks tight.",
    {
        "type": "object",
        "properties": {
            "diagram_id": {"type": "string", "format": "uuid"},
            "scope": {"type": "string", "enum": ["new_only", "all"], "default": "new_only"},
            "dry_run": {"type": "boolean", "default": False},
            "confirmed": {"type": "boolean", "default": False},
        },
        "required": ["diagram_id"],
    },
)

# ---- DRAFTS tools (only fork; merge is manual UI) ------------------------

_FORK_DIAGRAM_TO_DRAFT = _fn(
    "fork_diagram_to_draft",
    "[DRAFTS] Fork a diagram to a new draft for safe editing. Only call when "
    "the user explicitly requests a draft. Frontend will navigate to the new "
    "draft via view_change event.",
    {
        "type": "object",
        "properties": {
            "diagram_id": {"type": "string", "format": "uuid"},
            "draft_name": {"type": "string"},
        },
        "required": ["diagram_id"],
    },
)

_LIST_ACTIVE_DRAFTS = _fn(
    "list_active_drafts",
    "[DRAFTS] List active (unmerged) drafts for a diagram, or for the whole workspace.",
    {
        "type": "object",
        "properties": {
            "diagram_id": {"type": "string", "format": "uuid"},
        },
    },
)

# Final exported list — ordered by category for prompt readability.
DIAGRAM_TOOLS: list[dict] = [
    # READ
    _READ_OBJECT,
    _READ_OBJECT_FULL,
    _READ_DIAGRAM,
    _READ_CANVAS_STATE,
    _DEPENDENCIES,
    _LIST_OBJECTS,
    _LIST_DIAGRAMS,
    _SEARCH_EXISTING_OBJECTS,
    _SEARCH_EXISTING_TECHNOLOGIES,
    _LIST_OBJECT_TYPE_DEFINITIONS,
    _LIST_CONNECTION_PROTOCOLS,
    # WRITE — model layer
    _CREATE_OBJECT,
    _UPDATE_OBJECT,
    _DELETE_OBJECT,
    _CREATE_CONNECTION,
    _UPDATE_CONNECTION,
    _DELETE_CONNECTION,
    # WRITE — view layer
    _PLACE_ON_DIAGRAM,
    _MOVE_ON_DIAGRAM,
    _UNPLACE_FROM_DIAGRAM,
    # WRITE — diagrams + hierarchy
    _CREATE_DIAGRAM,
    _UPDATE_DIAGRAM,
    _DELETE_DIAGRAM,
    _LINK_OBJECT_TO_CHILD_DIAGRAM,
    _CREATE_CHILD_DIAGRAM_FOR_OBJECT,
    # WRITE — layout
    _AUTO_LAYOUT_DIAGRAM,
    # DRAFTS
    _FORK_DIAGRAM_TO_DRAFT,
    _LIST_ACTIVE_DRAFTS,
]


# ---------------------------------------------------------------------------
# System block renderers (attached via NodeConfig.additional_system_blocks)
# ---------------------------------------------------------------------------

# Recognise a "this plan step is satisfied" mapping from action verb to
# PlanStep.kind. e.g. action='object.created' → matches kind='create_object'.
_ACTION_TO_KIND: dict[str, str] = {
    "object.created": "create_object",
    "object.updated": "update_object",
    "object.deleted": "delete_object",
    "connection.created": "create_connection",
    "connection.updated": "update_connection",
    "connection.deleted": "delete_connection",
    "diagram.created": "create_diagram",
    "diagram.updated": "update_diagram",
    "diagram.deleted": "delete_diagram",
    "diagram.placed": "place_on_diagram",
    "diagram.linked_child": "link_object_to_child_diagram",
    "diagram.auto_layout": "auto_layout_diagram",
}


def _topo_order_steps(plan: Any) -> list[Any]:
    """Return the plan's steps in topological order.

    Prefers :meth:`Plan.topological_order` (Kahn's algorithm with
    cycle/self-dep validation). Falls back to input order on:
      - dict-shaped plans (no method);
      - validation errors raised by the model (defensive — planner is
        responsible for emitting acyclic plans).
    """
    steps = _get_attr(plan, "steps", []) or []
    if hasattr(plan, "topological_order"):
        try:
            return list(plan.topological_order())
        except (ValueError, TypeError) as exc:
            logger.warning("plan.topological_order failed: %s; falling back to input order", exc)
    return list(steps)


def _get_attr(obj: Any, name: str, default: Any = None) -> Any:
    """Read ``name`` off either a Pydantic model (attr) or a dict (key)."""
    if hasattr(obj, name):
        return getattr(obj, name, default)
    if isinstance(obj, dict):
        return obj.get(name, default)
    return default


def _step_satisfied_by_changes(step: Any, applied: list[dict]) -> bool:
    """Return True if any applied change covers this plan step.

    Match heuristic:
      1. ``action`` maps to ``step.kind`` via ``_ACTION_TO_KIND``.
      2. If the step's args mention a ``name``, prefer matches by name.
      3. Otherwise the action+kind match is enough.
    """
    kind = _get_attr(step, "kind", None)
    if kind is None:
        return False
    args = _get_attr(step, "args", {}) or {}
    target_name = args.get("name") if isinstance(args, dict) else None

    for change in applied:
        action = change.get("action", "")
        mapped_kind = _ACTION_TO_KIND.get(action)
        if mapped_kind != kind:
            continue
        if target_name and change.get("name") and change["name"] != target_name:
            continue
        return True
    return False


def render_pending_changes_block(state: AgentState) -> str:
    """Render the planner's plan in topological order with done/pending markers.

    Returns an empty string when there's no plan — the runtime drops empty
    blocks (see ``compose_messages_for_llm``) so the LLM prompt stays compact.
    """
    plan = state.get("plan")
    if plan is None:
        return ""

    steps = _get_attr(plan, "steps", []) or []
    if not steps:
        return "## Plan\n_no plan steps — nothing to execute._"

    applied: list[dict] = state.get("applied_changes") or []
    ordered_steps = _topo_order_steps(plan)

    lines = ["## Plan"]
    goal = _get_attr(plan, "goal", None)
    if goal:
        lines.append(f"**Goal:** {goal}")
    lines.append("")

    for ordinal, step in enumerate(ordered_steps, start=1):
        kind = _get_attr(step, "kind", "?")
        args = _get_attr(step, "args", {}) or {}
        rationale = _get_attr(step, "rationale", "") or ""
        done = _step_satisfied_by_changes(step, applied)
        marker = "✓" if done else "⏳"
        status = "done" if done else "pending"

        # Concise one-line summary
        name = ""
        if isinstance(args, dict):
            name = args.get("name") or args.get("object_id") or args.get("diagram_id") or ""
        suffix = f" — {rationale}" if rationale else ""
        lines.append(f"{marker} [{ordinal}] ({status}) {kind} {name}{suffix}".rstrip())

    return "\n".join(lines)


def render_active_diagram_block(state: AgentState) -> str:
    """Render the chat_context + active_draft so the agent knows where to mutate.

    Examples of output (one of):
      ``Working on diagram <uuid>``
      ``Working on diagram <uuid> (via draft <draft_uuid>)``
      ``Working on object <uuid> — open its diagram or use list_diagrams.``
      ``Working on workspace <uuid> — no diagram pinned.``
    """
    chat_context = state.get("chat_context") or {}
    active_draft_id = state.get("active_draft_id")

    # ChatContext may arrive as the Pydantic model or a plain dict.
    kind = _get_attr(chat_context, "kind", None) or "none"
    cid = _get_attr(chat_context, "id", None)
    draft_id = _get_attr(chat_context, "draft_id", None) or active_draft_id

    lines = ["## Active context"]
    if kind == "diagram":
        primary = f"Working on diagram {cid}"
        if draft_id:
            primary += f" (via draft {draft_id})"
        primary += "."
        lines.append(primary)
        lines.append(
            "All mutating tool calls auto-route to the active draft — do NOT "
            "pass draft_id explicitly."
        )
    elif kind == "object":
        lines.append(
            f"Working on object {cid}. Use list_diagrams or "
            "create_child_diagram_for_object to scope to a diagram."
        )
        if draft_id:
            lines.append(f"Active draft: {draft_id}.")
    elif kind == "workspace":
        lines.append(f"Working at workspace scope ({cid}). No diagram pinned.")
    else:
        lines.append("No diagram context — ask the user which diagram to edit.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompt loader
# ---------------------------------------------------------------------------

_PROMPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "prompts"
    / "general"
    / "diagram.md"
)


def load_diagram_prompt() -> str:
    """Read the diagram-agent system prompt from ``prompts/general/diagram.md``.

    Cached implicitly because callers build ``NodeConfig`` once at startup.
    """
    return _PROMPT_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# NodeConfig factory
# ---------------------------------------------------------------------------


def make_diagram_config(
    tool_executor: ToolExecutor,
    *,
    tool_filter: Callable[[list[dict]], list[dict]] | None = None,
) -> NodeConfig:
    """Build the ``NodeConfig`` used by the diagram-agent ReAct loop.

    Parameters
    ----------
    tool_executor:
        Async callable that executes one OpenAI-shape tool call against the
        current ``AgentState``. Provided by the runtime (task 026 wraps the
        catalogued ``Tool`` handlers behind ACL/audit/projection).
    tool_filter:
        Optional callable applied to ``DIAGRAM_TOOLS`` before handing the
        list to the node.  The runtime passes a scope/mode filter; direct
        callers and tests may omit it.
    """
    tools = tool_filter(DIAGRAM_TOOLS) if tool_filter is not None else DIAGRAM_TOOLS
    return NodeConfig(
        name="diagram",
        system_prompt=load_diagram_prompt(),
        tools=tools,
        tool_executor=tool_executor,
        max_steps=200,
        output_schema=None,
        additional_system_blocks=[
            render_pending_changes_block,
            render_active_diagram_block,
        ],
    )


# ---------------------------------------------------------------------------
# Tool-result parsing → applied_changes accumulation
# ---------------------------------------------------------------------------


def _parse_tool_content(content: Any) -> dict | None:
    """Normalize ``tool_result.content`` (str or dict) into a dict, or None."""
    if content is None:
        return None
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _change_from_tool_result(payload: dict) -> dict | None:
    """Build a ``ChangeRecord``-shaped dict from a structured tool result.

    The runtime tool wrapper (task 026) emits results of shape::

        {
            "ok": True,
            "action": "object.created",        # canonical action verb
            "target_type": "object",            # 'object' | 'connection' | 'diagram'
            "target_id": "<uuid>",
            "name": "Order Service",            # optional
            "diagram_id": "<uuid>",             # optional
            "extras": {...},                    # optional metadata
        }

    Returns None if the payload doesn't carry the minimum keys (action +
    target_id) — e.g. read-only results, errors, or reasoning-tool results.
    """
    if not isinstance(payload, dict):
        return None
    action = payload.get("action")
    target_id = payload.get("target_id")
    if not action or not target_id:
        return None
    record: dict[str, Any] = {
        "action": action,
        "target_type": payload.get("target_type")
        or (action.split(".")[0] if "." in action else "object"),
        "target_id": target_id,
    }
    if payload.get("name"):
        record["name"] = payload["name"]
    if payload.get("diagram_id"):
        record["diagram_id"] = payload["diagram_id"]
    extras = payload.get("extras")
    if isinstance(extras, dict) and extras:
        record["metadata"] = extras
    return record


def _collect_applied_changes(messages: list[dict]) -> list[dict]:
    """Walk the message history and collect applied changes from tool results.

    Looks at ``role='tool'`` messages whose ``content`` parses to JSON with
    the canonical shape (see :func:`_change_from_tool_result`).
    """
    out: list[dict] = []
    for msg in messages:
        if msg.get("role") != "tool":
            continue
        payload = _parse_tool_content(msg.get("content"))
        if payload is None:
            continue
        if payload.get("ok") is False:
            continue
        record = _change_from_tool_result(payload)
        if record is not None:
            out.append(record)
    return out


def _mark_plan_steps_done(plan: Any, applied: list[dict]) -> dict | None:
    """Return a state-patch fragment marking plan steps as done.

    The Plan model in :mod:`app.agents.state` does not currently carry a
    per-step ``done`` flag, so we surface progress via a sibling list
    ``plan_steps_done: list[int]`` in the state patch. This is consumed by the
    finalize node + supervisor to render progress; the planner remains the
    sole source of truth for the steps themselves.
    """
    if plan is None:
        return None
    steps = _get_attr(plan, "steps", []) or []
    if not steps:
        return None
    done_indices: list[int] = []
    for fallback_idx, step in enumerate(steps):
        if not _step_satisfied_by_changes(step, applied):
            continue
        # Prefer the explicit `index` field when present (Plan model contract).
        explicit = _get_attr(step, "index", None)
        done_indices.append(explicit if isinstance(explicit, int) else fallback_idx)
    return {"plan_steps_done": done_indices} if done_indices else None


# ---------------------------------------------------------------------------
# Node entry — async generator wrapping run_react
# ---------------------------------------------------------------------------


async def run(
    state: AgentState,
    *,
    enforcer: LimitsEnforcer,
    context_manager: ContextManager,
    tool_executor: ToolExecutor,
    call_metadata_base: LLMCallMetadata,
) -> AsyncIterator[NodeStreamEvent]:
    """Run the diagram-agent ReAct loop and yield :class:`NodeStreamEvent`.

    On the terminal ``finished`` event, augments ``output.state_patch``:

      * ``applied_changes``: merged list of ``ChangeRecord``-shaped dicts
        parsed from successful tool results during this run, appended to
        any pre-existing ``applied_changes`` carried into the state.
      * ``plan_steps_done`` (optional): indices of plan steps satisfied
        by the accumulated ``applied_changes``.

    Re-emits all run_react events untouched except the final ``finished``,
    whose ``output.state_patch`` we extend.
    """
    cfg = make_diagram_config(tool_executor)

    pre_existing_applied: list[dict] = list(state.get("applied_changes") or [])

    async for event in run_react(
        state,
        cfg,
        enforcer=enforcer,
        context_manager=context_manager,
        call_metadata_base=call_metadata_base,
    ):
        if event.kind != "finished":
            yield event
            continue

        output = event.payload["output"]
        messages: list[dict] = output.state_patch.get("messages") or []

        # Only walk messages appended during this node run — strip the prefix
        # that already existed in state.messages.
        prior_count = len(state.get("messages") or [])
        new_messages = messages[prior_count:]

        new_changes = _collect_applied_changes(new_messages)
        if pre_existing_applied or new_changes:
            output.state_patch["applied_changes"] = pre_existing_applied + new_changes

        plan = state.get("plan")
        plan_patch = _mark_plan_steps_done(
            plan, output.state_patch.get("applied_changes") or []
        )
        if plan_patch is not None:
            output.state_patch.update(plan_patch)

        yield event
