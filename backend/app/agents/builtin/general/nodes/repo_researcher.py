"""Repo Researcher node — universal text-worker scoped to a single GitHub repo.

Architecturally identical to ``researcher.py`` but:
  * Tool surface is the 9 ``repo_*`` tools registered in
    ``app.agents.tools.repo_tools``.
  * System prompt is parameterised with the repo URL / branch / node name
    that the runtime injects via ``state['repo_context']``.
  * Returns free-form markdown text — no Pydantic ``Findings`` schema.
  * Read-only by contract: any forbidden tool name (create_/update_/...)
    is filtered out of the schema before it reaches the LLM.
"""
from __future__ import annotations

import logging
import pathlib
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from app.agents.nodes.base import (
    NodeConfig,
    NodeStreamEvent,
    ToolExecutor,
    render_active_context_block,
    render_delegation_brief_block,
    run_react,
)
from app.agents.state import AgentState
from app.agents.tools.repo_tools import (
    REPO_TOOL_NAMES,
    _is_forbidden_tool_name,  # noqa: PLC2701 — package-internal helper
)

if TYPE_CHECKING:
    from app.agents.context_manager import ContextManager
    from app.agents.limits import LimitsEnforcer
    from app.agents.llm import LLMCallMetadata

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants — same shape as researcher.RESEARCHER_TOOL_NAMES
# ---------------------------------------------------------------------------

REPO_RESEARCHER_TOOL_NAMES: list[str] = list(REPO_TOOL_NAMES)


# ---------------------------------------------------------------------------
# Prompt loader (parameterised)
# ---------------------------------------------------------------------------


_PROMPT_PATH = (
    pathlib.Path(__file__).resolve().parents[3]
    / "prompts"
    / "general"
    / "repo_researcher.md"
)

_PROMPT_TEMPLATE_CACHE: str | None = None


def load_repo_researcher_prompt() -> str:
    """Read the un-rendered template from disk (cached for the process)."""
    global _PROMPT_TEMPLATE_CACHE
    if _PROMPT_TEMPLATE_CACHE is None:
        try:
            _PROMPT_TEMPLATE_CACHE = _PROMPT_PATH.read_text(encoding="utf-8")
        except (OSError, FileNotFoundError):
            _PROMPT_TEMPLATE_CACHE = (
                "You are the Repo Researcher. Read-only. Repo: {repo_url} "
                "on {repo_branch_display}."
            )
    return _PROMPT_TEMPLATE_CACHE


def render_repo_researcher_prompt(
    *,
    repo_url: str,
    repo_branch: str | None,
    repo_node_name: str,
    repo_node_type: str,
) -> str:
    """Substitute the four runtime placeholders in the prompt template.

    Uses ``str.replace`` (not ``str.format``) so curly-brace examples in
    the markdown body don't trip on KeyError.
    """
    branch_display = repo_branch or "(default branch)"
    template = load_repo_researcher_prompt()
    return (
        template.replace("{repo_url}", repo_url)
        .replace("{repo_branch_display}", branch_display)
        .replace("{repo_node_name}", repo_node_name)
        .replace("{repo_node_type}", repo_node_type)
    )


# ---------------------------------------------------------------------------
# Read-only enforcer / tool list builder
# ---------------------------------------------------------------------------


def _build_repo_tool_schemas() -> list[dict]:
    """Resolve the 9 ``repo_*`` tools from the global registry into the
    OpenAI-shape dicts the LLM sees. Forbidden / mutating tool names are
    filtered out as defence in depth — even if a future refactor accidentally
    adds a write tool to ``REPO_TOOL_NAMES``, it will be silently stripped.
    """
    from app.agents.tools.base import _TOOLS

    schemas: list[dict] = []
    for name in REPO_RESEARCHER_TOOL_NAMES:
        if _is_forbidden_tool_name(name):
            logger.warning(
                "repo_researcher: dropping forbidden tool %r from registry", name
            )
            continue
        t = _TOOLS.get(name)
        if t is None:
            # Tool isn't registered yet — happens in test scaffolds that
            # import the node before tools/__init__.py runs.
            continue
        if t.mutating:
            logger.warning(
                "repo_researcher: dropping mutating tool %r from registry", name
            )
            continue
        schemas.append(t.to_openai_schema())
    return schemas


# ---------------------------------------------------------------------------
# NodeConfig factory
# ---------------------------------------------------------------------------


def make_repo_researcher_config(
    tool_executor: ToolExecutor,
    *,
    repo_url: str,
    repo_branch: str | None,
    repo_node_name: str,
    repo_node_type: str,
) -> NodeConfig:
    """Build the per-invocation ``NodeConfig``.

    The system prompt is rendered with the four runtime placeholders so
    the LLM sees the repo URL / branch directly in its context.
    """
    return NodeConfig(
        name="repo_researcher",
        system_prompt=render_repo_researcher_prompt(
            repo_url=repo_url,
            repo_branch=repo_branch,
            repo_node_name=repo_node_name,
            repo_node_type=repo_node_type,
        ),
        tools=_build_repo_tool_schemas(),
        tool_executor=tool_executor,
        max_steps=200,
        output_schema=None,  # free-form markdown
        enable_streaming=False,
        additional_system_blocks=[
            render_active_context_block,
            render_delegation_brief_block,
        ],
    )


# ---------------------------------------------------------------------------
# Node entry point
# ---------------------------------------------------------------------------


def _extract_repo_context(state: AgentState) -> dict[str, str]:
    """Pull the repo context the runtime injected when routing here.

    Source of truth: ``state['repo_context']`` (a dict with ``repo_url``,
    ``repo_branch``, ``repo_node_name``, ``repo_node_type``, ``slug``).
    Falls back to defaults so the node still composes a usable system
    prompt during dev / tests when the runtime hasn't wired the context.
    """
    rc = state.get("repo_context")
    if not isinstance(rc, dict):
        return {
            "repo_url": "",
            "repo_branch": "",
            "repo_node_name": "(unknown)",
            "repo_node_type": "system",
        }
    return {
        "repo_url": str(rc.get("repo_url") or ""),
        "repo_branch": str(rc.get("repo_branch") or "") or "",
        "repo_node_name": str(rc.get("repo_node_name") or "(unknown)"),
        "repo_node_type": str(rc.get("repo_node_type") or "system"),
    }


async def run(  # type: ignore[return]
    state: AgentState,
    *,
    enforcer: LimitsEnforcer,
    context_manager: ContextManager,
    tool_executor: ToolExecutor,
    call_metadata_base: LLMCallMetadata,
) -> AsyncIterator[NodeStreamEvent]:
    """Drive the repo-researcher ReAct loop.

    The terminal output is free-form markdown text. We surface it on
    ``state_patch['repo_response']`` so the supervisor's
    ``rewrite_supervisor_tool_result`` knows how to render the answer
    back into the supervisor's history.
    """
    rc = _extract_repo_context(state)
    cfg = make_repo_researcher_config(
        tool_executor,
        repo_url=rc["repo_url"],
        repo_branch=rc["repo_branch"] or None,
        repo_node_name=rc["repo_node_name"],
        repo_node_type=rc["repo_node_type"],
    )

    async for event in run_react(
        state,
        cfg,
        enforcer=enforcer,
        context_manager=context_manager,
        call_metadata_base=call_metadata_base,
    ):
        if event.kind == "finished":
            output = event.payload["output"]
            text = (output.text or "").strip()
            if text:
                output.state_patch["repo_response"] = text
        yield event
