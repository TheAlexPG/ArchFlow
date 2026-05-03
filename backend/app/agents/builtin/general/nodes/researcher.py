"""Researcher node: read-only ReAct loop returning structured findings.
Used as a node in the `general` graph AND as the sole node in the `researcher` standalone graph."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from app.agents.nodes.base import (
    NodeConfig,
    NodeStreamEvent,
    ToolExecutor,
    render_active_context_block,
    render_delegation_brief_block,
    run_react,
)
from app.agents.state import AgentState

if TYPE_CHECKING:
    from app.agents.context_manager import ContextManager
    from app.agents.limits import LimitsEnforcer
    from app.agents.llm import LLMCallMetadata

# ---------------------------------------------------------------------------
# Phase 1: read-only tool set — NO create/update/delete/place.
# Tool definitions are LLM-side OpenAI-schema dicts; handlers registered
# separately in task agent-core-mvp-026/027.  We declare names here so the
# RESEARCHER_TOOLS list is the authoritative read-only allow-list.
# ---------------------------------------------------------------------------

# Phase 1: NO git tools. Read + search only.
# Names of the tools the researcher can call.  The full OpenAI-schema dicts
# are built lazily in ``make_researcher_config`` from the global tool
# registry — that way descriptions/parameters stay in sync with the actual
# handlers and we don't have to repeat the schema by hand here.
RESEARCHER_TOOL_NAMES: list[str] = [
    "read_object",
    "read_object_full",
    "read_connection",
    "read_diagram",
    "dependencies",
    "list_objects",
    "list_diagrams",
    "list_child_diagrams",
    "search_existing_objects",
    "search_existing_technologies",
    # web_fetch: text/markdown only — no image_describe by default (cost)
    "web_fetch",
]

# Back-compat for existing tests that import RESEARCHER_TOOLS — list of bare
# ``{"name": ...}`` dicts, the same lookup token tests need to verify the
# read-only allow-list. The actual OpenAI schemas sent to the LLM are built
# in ``make_researcher_config`` via the registry.
RESEARCHER_TOOLS: list[dict] = [{"name": n} for n in RESEARCHER_TOOL_NAMES]

# Set of tool names that are forbidden in the researcher (mutation detection).
_FORBIDDEN_TOOL_PREFIXES = frozenset(
    [
        "create_",
        "update_",
        "delete_",
        "place_",
        "move_",
        "unplace_",
        "link_",
        "unlink_",
        "auto_layout_",
    ]
)


# ---------------------------------------------------------------------------
# Findings output schema
# ---------------------------------------------------------------------------


class Findings(BaseModel):
    """What researcher returns. Free-form markdown body + structured citations."""

    summary: str = Field(
        ...,
        max_length=4000,
        description="Markdown body, primary deliverable",
    )
    citations: list[dict] = Field(
        default_factory=list,
        description=(
            "[{type:'object'|'diagram'|'connection'|'url', id_or_url:..., note:...}]"
        ),
    )
    confidence: str = Field(
        "medium",
        description="'low' | 'medium' | 'high'",
    )


# ---------------------------------------------------------------------------
# Prompt loader
# ---------------------------------------------------------------------------

_PROMPT_CACHE: str | None = None


def load_researcher_prompt() -> str:
    """Load and cache the researcher system prompt from the prompts directory."""
    global _PROMPT_CACHE
    if _PROMPT_CACHE is not None:
        return _PROMPT_CACHE

    try:
        # Resolve relative to the agents package's prompts directory:
        # app/agents/builtin/general/nodes/researcher.py
        #   parents[0]=nodes  [1]=general  [2]=builtin  [3]=agents
        import pathlib

        prompts_path = (
            pathlib.Path(__file__).resolve().parents[3]
            / "prompts"
            / "researcher"
            / "system.md"
        )
        _PROMPT_CACHE = prompts_path.read_text(encoding="utf-8")
    except (OSError, FileNotFoundError):
        # Fallback so tests that don't care about prompt content still pass.
        _PROMPT_CACHE = (
            "You are the Researcher. Read-only fact-finder over the workspace's C4 model."
        )
    return _PROMPT_CACHE


# ---------------------------------------------------------------------------
# NodeConfig factory
# ---------------------------------------------------------------------------


def make_researcher_config(
    tool_executor: ToolExecutor,
    *,
    tool_filter: Callable[[list[dict]], list[dict]] | None = None,
) -> NodeConfig:
    """Build the NodeConfig for the researcher node.

    Spec: max_steps=6, output_schema=Findings, enable_streaming=False.

    Tool definitions are pulled from the global registry and serialised via
    ``Tool.to_openai_schema`` — names that aren't registered yet are skipped
    silently (so importing the module before tool registration runs doesn't
    blow up).

    ``tool_filter`` — optional callable applied to the resolved OpenAI-shape
    list for scope/mode filtering by the runtime.
    """
    from app.agents.tools.base import _TOOLS

    tools: list[dict] = []
    for name in RESEARCHER_TOOL_NAMES:
        t = _TOOLS.get(name)
        if t is not None:
            tools.append(t.to_openai_schema())
    if tool_filter is not None:
        tools = tool_filter(tools)
    return NodeConfig(
        name="researcher",
        system_prompt=load_researcher_prompt(),
        tools=tools,
        tool_executor=tool_executor,
        # Local models (qwen) tend to loop on tool calls when something
        # surprises them (e.g. resolving technology_ids as object_ids,
        # getting "not found", retrying with the same uuid in a different
        # tool, etc). 4 steps is enough for a sensible read-diagram-then-
        # describe path; anything longer is almost always wandering.
        max_steps=4,
        output_schema=Findings,
        enable_streaming=False,
        additional_system_blocks=[
            render_active_context_block,
            render_delegation_brief_block,
        ],
    )


# ---------------------------------------------------------------------------
# Node entry point
# ---------------------------------------------------------------------------


async def run(  # type: ignore[return]
    state: AgentState,
    *,
    enforcer: LimitsEnforcer,
    context_manager: ContextManager,
    tool_executor: ToolExecutor,
    call_metadata_base: LLMCallMetadata,
) -> AsyncIterator[NodeStreamEvent]:
    """Drive the researcher ReAct loop.

    On normal exit sets state_patch.findings = output.structured (a Findings
    instance). The caller (runtime or standalone graph runner) is responsible
    for persisting state_patch back to AgentState.
    """
    cfg = make_researcher_config(tool_executor)

    async for event in run_react(
        state,
        cfg,
        enforcer=enforcer,
        context_manager=context_manager,
        call_metadata_base=call_metadata_base,
    ):
        if event.kind == "finished":
            output = event.payload["output"]
            # Inject findings into state_patch so callers can merge it.
            if output.structured is not None:
                output.state_patch["findings"] = output.structured
            elif (output.text or "").strip():
                # JSON parse failed but the LLM did produce a meaningful
                # answer — local models (qwen, llama) frequently emit raw
                # markdown instead of the Findings JSON envelope. Salvage
                # the prose as findings.summary at low confidence so the
                # supervisor can surface it to the user instead of falling
                # back to "No changes were applied".
                output.state_patch["findings"] = Findings(
                    summary=output.text.strip(),
                    citations=[],
                    confidence="low",
                )
            else:
                # No structured output AND no text — usually because the LLM
                # ran out of steps (forced_finalize='max_steps') or returned
                # empty completions. We almost always have *some* tool
                # results in the working messages already; salvage them as a
                # rough findings summary so the supervisor can answer from
                # real data instead of seeing an empty placeholder.
                tool_msgs = [
                    m for m in (output.state_patch.get("messages") or [])
                    if isinstance(m, dict) and m.get("role") == "tool"
                ]
                summary = _synthesise_findings_from_tools(tool_msgs)
                output.state_patch["findings"] = Findings(
                    summary=summary,
                    citations=[],
                    confidence="low",
                )
        yield event


def _synthesise_findings_from_tools(tool_messages: list[dict]) -> str:
    """Build a fallback Findings.summary from the raw tool results we already
    have. Used when the researcher ran out of steps before producing a real
    Findings JSON.

    Walks tool messages in order, parses each as JSON when possible, and
    extracts the most useful field (``name`` for objects/diagrams,
    ``label`` / source/target for connections, list lengths for collections).
    Returns a markdown-ish bullet list of what we found, or a generic
    "no information collected" string when nothing parseable is present.
    """
    import json as _json

    if not tool_messages:
        return (
            "Research could not collect any data — the researcher ran out of "
            "steps before any tool returned successfully. Answer based on the "
            "user's question alone."
        )

    seen_objects: list[str] = []
    seen_diagrams: list[str] = []
    seen_connections: list[str] = []
    list_summaries: list[str] = []

    for msg in tool_messages:
        content = msg.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        # Skip "<tool> not found" error strings — they have no useful info.
        if " not found" in content or content.startswith("denied:"):
            continue
        try:
            payload = _json.loads(content)
        except (ValueError, TypeError):
            continue
        if isinstance(payload, dict):
            name = payload.get("name")
            placements = payload.get("placements")
            connections = payload.get("connections")
            items = payload.get("items")
            if isinstance(placements, list) and name:
                seen_diagrams.append(f"`{name}` ({len(placements)} object(s))")
            elif isinstance(connections, list) and name and isinstance(placements, list):
                seen_diagrams.append(
                    f"`{name}` ({len(placements)} obj, {len(connections)} conn)"
                )
            elif name:
                obj_type = payload.get("type") or "object"
                seen_objects.append(f"`{name}` ({obj_type})")
            elif "source_id" in payload and "target_id" in payload:
                lbl = payload.get("label") or "unnamed"
                seen_connections.append(f"`{lbl}`")
            elif isinstance(items, list):
                list_summaries.append(f"{len(items)} item(s)")

    parts: list[str] = []
    if seen_diagrams:
        parts.append("**Diagrams:** " + ", ".join(seen_diagrams))
    if seen_objects:
        parts.append("**Objects:** " + ", ".join(seen_objects))
    if seen_connections:
        parts.append("**Connections:** " + ", ".join(seen_connections))
    if list_summaries:
        parts.append("**Lookups:** " + ", ".join(list_summaries))

    if not parts:
        return (
            "Research collected partial data but nothing recognisable was "
            "extracted. Answer cautiously."
        )
    return (
        "Research did not finish formatting a structured Findings response, "
        "but here is what was observed before the step budget ran out:\n\n"
        + "\n".join(f"- {p}" for p in parts)
    )
