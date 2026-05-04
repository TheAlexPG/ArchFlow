"""Supervisor node: orchestrates the general agent via ReAct loop with scratchpad.

The supervisor is the user-facing voice of the general agent. It:

  * Runs a ReAct loop (via :func:`app.agents.nodes.base.run_react`) with the
    supervisor's tool surface exposed: scratchpad mutators, delegation tools,
    ``finalize``, and a couple of composite helpers (``fork_diagram_to_draft``,
    ``list_active_drafts``, ``web_fetch``).
  * Renders three system blocks on every step: the markdown scratchpad, a
    resources / mode summary, and a short ``applied_changes`` recap so it
    knows what's already been done in the session.
  * Translates ``write_scratchpad`` tool calls into a state patch so the
    runtime can persist the new scratchpad value.

Routing decisions (which sub-agent to enter on the next graph step) are
determined by the runtime by inspecting the *last* tool call in
``state['messages']`` after this node returns. This module does not make those
decisions itself — it only declares the tool schemas and pipes them through
the shared ReAct loop.
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
    NodeOutput,
    NodeStreamEvent,
    ToolExecutor,
    run_react,
)
from app.agents.state import AgentState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool schemas (OpenAI function format) for the supervisor
# ---------------------------------------------------------------------------

SUPERVISOR_TOOLS: list[dict] = [
    # --- scratchpad ----------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "write_scratchpad",
            "description": (
                "Replace the supervisor's working notes (markdown). Use as a "
                "TODO list, plan tracker, or open-questions log. Update freely "
                "as you progress."
            ),
            "parameters": {
                "type": "object",
                "properties": {"content": {"type": "string"}},
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_scratchpad",
            "description": (
                "Read current scratchpad. Usually rendered in your context "
                "already, so prefer reading inline."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    # --- delegation (terminating tool calls) ---------------------------
    {
        "type": "function",
        "function": {
            "name": "delegate_to_planner",
            "description": (
                "Hand off complex multi-step tasks to the Planner agent for "
                "decomposition. Use when the user request requires creating "
                "multiple objects, building hierarchical structure, or "
                "coordinating dependent changes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string"},
                    "focus": {
                        "type": "string",
                        "description": "Sub-goal for the planner to decompose",
                    },
                },
                "required": ["reason", "focus"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delegate_to_diagram",
            "description": (
                "Hand off direct diagram mutations to the Diagram-Agent. Use "
                "for simple one-shot changes (rename, add single object) when "
                "no planning is needed."
            ),
            "parameters": {
                "type": "object",
                "properties": {"action_hint": {"type": "string"}},
                "required": ["action_hint"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delegate_to_researcher",
            "description": (
                "Ask the Researcher for read-only structural facts about the "
                "diagram/object. Use when the user asks 'explain', 'what is', "
                "'how does X relate to Y'."
            ),
            "parameters": {
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delegate_to_critic",
            "description": (
                "Ask the Critic to review applied_changes and decide APPROVE "
                "or REVISE."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    # --- finalize ------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "finalize",
            "description": (
                "End this turn and return the final message to the user. Call "
                "this exactly once when the work is complete or you cannot "
                "proceed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": (
                            "Optional override of the auto-generated summary. "
                            "Usually leave empty."
                        ),
                    }
                },
            },
        },
    },
    # --- composite helpers --------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "fork_diagram_to_draft",
            "description": (
                "Fork the active diagram into a new draft. ONLY call this "
                "when the user EXPLICITLY asks ('create a draft', 'fork "
                "this', 'work in draft'). DO NOT call to be safe — the system "
                "handles draft policy on its own."
            ),
            "parameters": {
                "type": "object",
                "properties": {"draft_name": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": (
                "Fetch an http(s) URL the user pasted. Returns text content "
                "(or an image description). Use sparingly."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "render": {
                        "type": "string",
                        "enum": ["text", "markdown", "image_describe"],
                        "default": "text",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_active_drafts",
            "description": (
                "List currently-open drafts for a diagram (or all your "
                "drafts)."
            ),
            "parameters": {
                "type": "object",
                "properties": {"diagram_id": {"type": "string"}},
            },
        },
    },
]


# Names of tools that mutate the scratchpad — tracked here so the post-run
# state-patch builder can extract the latest content without re-parsing all
# tool call shapes.
_SCRATCHPAD_WRITE_TOOL = "write_scratchpad"
_FINALIZE_TOOL = "finalize"

# Tool calls that hand control off — once any of these is executed, the
# supervisor's ReAct loop exits without re-prompting the LLM. The LangGraph
# router then routes to the corresponding sub-agent (or to the finalize node).
# See :class:`NodeConfig.terminating_tool_names` for why this is necessary.
#
# ``delegate_to_repo_<slug>`` tools are added dynamically per-turn from the
# repo manifest; the supervisor's ``run`` builds a per-call set that includes
# them so they too terminate the ReAct loop.
_TERMINATING_TOOL_NAMES: set[str] = {
    "delegate_to_planner",
    "delegate_to_diagram",
    "delegate_to_researcher",
    "delegate_to_critic",
    "finalize",
}


# Prefix for the dynamically-added per-repo delegation tools.
DELEGATE_REPO_PREFIX = "delegate_to_repo_"

# Cap on how many recent applied_changes we render in the system block —
# anything larger gets noisy and starts to crowd the LLM's context.
_APPLIED_CHANGES_RENDER_LIMIT = 5


# ---------------------------------------------------------------------------
# System-block renderers
# ---------------------------------------------------------------------------


def render_scratchpad_block(state: AgentState) -> str:
    """System block: render the supervisor's scratchpad markdown.

    Empty scratchpad surfaces as ``_(empty)_`` so the LLM can still see the
    section header (and therefore knows the scratchpad exists and can be
    written to).
    """
    raw = (state.get("scratchpad") or "").strip()
    body = raw if raw else "_(empty)_"
    return f"## Scratchpad\n{body}"


def render_resources_block(state: AgentState) -> str:
    """System block: budget summary + turns + subagent budgets.

    ``state['budget_counters']`` is a mapping of ``agent_id -> {cost_usd,
    turns_used, ...}``. We render whichever sub-agent counters are present;
    the supervisor doesn't need to know the exact shape — finalize.py handles
    the same dict.

    When ``state['runtime_mode'] == 'read_only'`` we surface ``Mode:
    read-only`` so the supervisor's prompt and the rendered context both
    agree on the constraint.
    """
    lines: list[str] = ["## Resources"]

    mode = state.get("runtime_mode")
    if mode == "read_only":
        lines.append("- Mode: read-only (no mutations allowed; researcher only)")
    elif mode:
        lines.append(f"- Mode: {mode}")

    counters = state.get("budget_counters") or {}
    if counters:
        for agent_id, c in counters.items():
            if isinstance(c, dict):
                cost = c.get("cost_usd")
                turns = c.get("turns_used")
            else:
                cost = getattr(c, "cost_usd", None)
                turns = getattr(c, "turns_used", None)
            parts: list[str] = []
            if turns is not None:
                parts.append(f"turns={turns}")
            if cost is not None:
                try:
                    parts.append(f"cost=${float(cost):.4f}")
                except (TypeError, ValueError):
                    parts.append(f"cost={cost}")
            suffix = f" ({', '.join(parts)})" if parts else ""
            lines.append(f"- {agent_id}{suffix}")
    else:
        lines.append("- (counters not yet populated)")

    return "\n".join(lines)


def render_repo_manifest_block(state: AgentState) -> str:
    """System block: list the repos visible on the active diagram.

    Renders nothing when the manifest is empty so the supervisor's prompt
    stays clean for workspaces that haven't linked any repos. The block
    intentionally lives next to the other supervisor blocks (vs. inside
    the static prompt) so the manifest can shift across turns as the
    user navigates between diagrams.
    """
    from app.agents.builtin.general.manifest import (
        RepoLink,
        render_repo_manifest_block as _render_block,
    )

    raw = state.get("repo_manifest")
    if not raw:
        return ""
    manifest: list[RepoLink] = []
    for entry in raw:
        if isinstance(entry, RepoLink):
            manifest.append(entry)
        elif isinstance(entry, dict):
            try:
                manifest.append(RepoLink.model_validate(entry))
            except Exception:  # noqa: BLE001 — malformed entry: skip silently
                logger.debug("repo manifest contained malformed entry: %r", entry)
    return _render_block(manifest)


def build_repo_delegation_tools(state: AgentState) -> list[dict]:
    """Build one ``delegate_to_repo_<slug>`` tool schema per manifest entry.

    The tool's ``description`` carries the repo's display info so the
    LLM doesn't need to consult the system block to decide *when* to
    invoke it (which models routinely fail to cross-reference).
    """
    from app.agents.builtin.general.manifest import RepoLink

    raw = state.get("repo_manifest") or []
    out: list[dict] = []
    for entry in raw:
        if isinstance(entry, RepoLink):
            slug = entry.slug
            short = entry.repo_url
            if short.startswith("https://github.com/"):
                short = short[len("https://github.com/") :]
            node_name = entry.node_name
            node_type = entry.node_type
            branch = entry.repo_branch or "(default)"
        elif isinstance(entry, dict):
            slug = str(entry.get("slug") or "")
            if not slug:
                continue
            short = entry.get("repo_url") or ""
            if isinstance(short, str) and short.startswith("https://github.com/"):
                short = short[len("https://github.com/") :]
            node_name = entry.get("node_name") or "(unknown)"
            node_type = entry.get("node_type") or "system"
            branch = entry.get("repo_branch") or "(default)"
        else:
            continue
        out.append(
            {
                "type": "function",
                "function": {
                    "name": f"{DELEGATE_REPO_PREFIX}{slug}",
                    "description": (
                        f"Delegate a free-form question to the repo "
                        f"researcher for `{short}` on `{branch}` (the "
                        f"{node_name} {node_type}). Returns markdown."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "question": {
                                "type": "string",
                                "description": (
                                    "What you want the repo researcher to "
                                    "find out. Be specific."
                                ),
                            }
                        },
                        "required": ["question"],
                    },
                },
            }
        )
    return out


def render_applied_changes_block(state: AgentState) -> str:
    """System block: short summary of applied_changes so the supervisor
    knows what's already been done in this session.

    Renders at most ``_APPLIED_CHANGES_RENDER_LIMIT`` items (most recent),
    with an ellipsis line when truncated.
    """
    applied = state.get("applied_changes") or []
    lines: list[str] = ["## Recent applied changes"]

    if not applied:
        lines.append("- (no changes yet)")
        return "\n".join(lines)

    visible = applied[-_APPLIED_CHANGES_RENDER_LIMIT:]
    omitted = len(applied) - len(visible)
    if omitted > 0:
        lines.append(f"- ... ({omitted} earlier change{'s' if omitted != 1 else ''} omitted)")
    for change in visible:
        action = change.get("action", "?")
        target_type = change.get("target_type") or (
            action.split(".")[0] if "." in action else "?"
        )
        name = change.get("name") or change.get("target_id") or "?"
        lines.append(f"- {action} {target_type} \"{name}\"")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# System prompt loader
# ---------------------------------------------------------------------------


_PROMPT_PATH = (
    Path(__file__).resolve().parents[3] / "prompts" / "general" / "supervisor.md"
)


def load_supervisor_prompt() -> str:
    """Read the supervisor system prompt from
    ``app/agents/prompts/general/supervisor.md``.

    Stored as markdown so prompt-engineering iterations show up cleanly in
    git diffs. The file is read on every call (not cached) — these calls
    happen once per node activation, and the file system cost is trivial
    next to the LLM round-trip.
    """
    return _PROMPT_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# NodeConfig factory
# ---------------------------------------------------------------------------


def make_supervisor_config(
    tool_executor: ToolExecutor,
    *,
    tool_filter: Callable[[list[dict]], list[dict]] | None = None,
    extra_tools: list[dict] | None = None,
    extra_terminating_names: set[str] | None = None,
) -> NodeConfig:
    """Build the :class:`NodeConfig` for the supervisor node.

    Knobs:

      * ``max_steps=200`` — generous ceiling so the supervisor never aborts
        with ``forced_finalize=max_steps`` during a real architecture-design
        session. The actual cost guard lives in
        :class:`LimitsEnforcer` (turn / budget caps), not in this counter.
      * ``enable_streaming=True`` — supervisor speaks to the user.
      * ``output_schema=None`` — free-form text; structured output is for
        sub-agents (planner, critic).
      * ``additional_system_blocks`` — scratchpad / resources / applied
        changes / repo manifest, in that order.
      * ``tool_filter`` — optional callable ``(schemas) -> schemas`` applied
        before handing the tool list to the node.  The runtime passes a real
        filter for scope/mode enforcement; tests and direct callers may omit
        it (identity filter is used).
      * ``extra_tools`` — per-call additions to the static ``SUPERVISOR_TOOLS``
        list. Used for the dynamic ``delegate_to_repo_<slug>`` tools built
        from the per-turn repo manifest.
      * ``extra_terminating_names`` — names that join ``_TERMINATING_TOOL_NAMES``
        for this run so the dynamic delegation tools also exit the ReAct loop.
    """
    base_tools = list(SUPERVISOR_TOOLS)
    if extra_tools:
        base_tools.extend(extra_tools)
    tools = tool_filter(base_tools) if tool_filter is not None else base_tools
    terminating = set(_TERMINATING_TOOL_NAMES)
    if extra_terminating_names:
        terminating |= extra_terminating_names
    return NodeConfig(
        name="supervisor",
        system_prompt=load_supervisor_prompt(),
        tools=tools,
        tool_executor=tool_executor,
        max_steps=200,
        output_schema=None,
        enable_streaming=True,
        additional_system_blocks=[
            render_scratchpad_block,
            render_resources_block,
            render_applied_changes_block,
            render_repo_manifest_block,
            # NOTE: ``render_subagent_results_block`` was previously appended
            # here as a workaround for the OpenAI tool-call protocol gap —
            # the supervisor's ``delegate_to_*`` tool result only echoed the
            # input args, so the supervisor couldn't see what the sub-agent
            # actually produced. The graph-level helper
            # ``rewrite_subagent_tool_result`` now patches the matching tool
            # message with the real findings/plan/applied/critique payload,
            # making this system block redundant. Re-adding it would double
            # the same content in the LLM's context.
        ],
        terminating_tool_names=terminating,
    )


# ---------------------------------------------------------------------------
# Helper: scrape state mutations from the message history produced by run_react
# ---------------------------------------------------------------------------


def _coerce_arguments(arguments: Any) -> dict[str, Any]:
    """Tool calls in ``state['messages']`` carry ``arguments`` as a JSON
    string (OpenAI on-wire shape). Decode defensively — malformed payloads
    surface as an empty dict so the caller can keep going.
    """
    if isinstance(arguments, dict):
        return arguments
    if not arguments:
        return {}
    try:
        decoded = json.loads(arguments)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _extract_scratchpad_writes_and_finalize(messages: list[dict]) -> tuple[
    str | None, str | None
]:
    """Walk the assistant messages emitted during the node run and return:

      * the most recent ``write_scratchpad`` content (or ``None`` if none),
      * the ``finalize`` ``message`` argument (or ``None`` if not called).

    We scan in document order so the *last* scratchpad write wins, which
    matches the ``write_scratchpad`` semantics ("full replace").
    """
    latest_scratchpad: str | None = None
    finalize_message: str | None = None

    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            name = fn.get("name") or tc.get("name")
            if name == _SCRATCHPAD_WRITE_TOOL:
                args = _coerce_arguments(fn.get("arguments") or tc.get("arguments"))
                content = args.get("content")
                if isinstance(content, str):
                    latest_scratchpad = content
            elif name == _FINALIZE_TOOL:
                args = _coerce_arguments(fn.get("arguments") or tc.get("arguments"))
                msg_arg = args.get("message")
                if isinstance(msg_arg, str) and msg_arg:
                    finalize_message = msg_arg

    return latest_scratchpad, finalize_message


# Map delegation tool names → (sub-agent kind, instruction-arg-key, optional reason key).
_DELEGATE_TOOL_TO_BRIEF: dict[str, tuple[str, str, str | None]] = {
    "delegate_to_researcher": ("researcher", "question", None),
    "delegate_to_planner": ("planner", "focus", "reason"),
    "delegate_to_diagram": ("diagram", "action_hint", None),
    "delegate_to_critic": ("critic", "", None),
}


def _extract_delegate_brief(messages: list[dict]) -> dict | None:
    """Find the supervisor's most recent ``delegate_to_*`` tool call and pack
    its args into a ``delegate_brief`` dict the sub-agent can render.

    Returns ``None`` when the supervisor's last action was ``finalize`` or
    something other than a delegation — in that case the sub-agent (if any)
    should fall back to the raw conversation.

    Recognises both the static delegation tools and the per-turn
    ``delegate_to_repo_<slug>`` family. For the latter, ``kind`` is set to
    ``"repo:<slug>"`` so the graph router can resolve the manifest entry.
    """
    for msg in reversed(messages):
        if msg.get("role") != "assistant":
            continue
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            continue
        last = tool_calls[-1]
        fn = last.get("function") or {}
        name = fn.get("name") or last.get("name") or ""
        # Static delegation tools.
        mapping = _DELEGATE_TOOL_TO_BRIEF.get(name)
        if mapping is not None:
            kind, instr_key, reason_key = mapping
            args = _coerce_arguments(fn.get("arguments") or last.get("arguments"))
            instruction = args.get(instr_key) if instr_key else None
            if not isinstance(instruction, str):
                instruction = ""
            reason = args.get(reason_key) if reason_key else None
            if not isinstance(reason, str):
                reason = None
            return {"kind": kind, "instruction": instruction, "reason": reason}
        # Dynamic per-repo delegation tools.
        if name.startswith(DELEGATE_REPO_PREFIX):
            slug = name[len(DELEGATE_REPO_PREFIX) :]
            args = _coerce_arguments(fn.get("arguments") or last.get("arguments"))
            instruction = args.get("question")
            if not isinstance(instruction, str):
                instruction = ""
            return {
                "kind": f"repo:{slug}",
                "instruction": instruction,
                "reason": None,
            }
        return None
    return None


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
    """Run the supervisor for one node activation.

    Yields the same :class:`NodeStreamEvent` stream as :func:`run_react`. The
    terminal ``finished`` event carries a :class:`NodeOutput` whose
    ``state_patch`` includes:

      * ``messages`` — the new turn rows (already populated by ``run_react``).
      * ``compaction_stage`` — surfaced for runtime persistence.
      * ``scratchpad`` — present iff the LLM wrote to the scratchpad.
      * ``final_message`` — present iff the LLM passed a non-empty ``message``
        to ``finalize`` (otherwise the finalize node builds the summary).

    Routing decisions belong to the runtime layer: it inspects the last
    tool call in ``state_patch['messages']`` to pick the next graph step.
    """
    # Per-turn dynamic tools: one ``delegate_to_repo_<slug>`` per entry in
    # the workspace manifest. We rebuild on every visit so the supervisor
    # always sees an up-to-date list (even if the user navigates between
    # diagrams mid-turn — D3 will revisit this).
    extra_tools = build_repo_delegation_tools(state)
    extra_terminating = {
        (t.get("function") or {}).get("name") or ""
        for t in extra_tools
    }
    extra_terminating.discard("")
    cfg = make_supervisor_config(
        tool_executor,
        extra_tools=extra_tools or None,
        extra_terminating_names=extra_terminating or None,
    )

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

        # Augment the NodeOutput's state_patch with supervisor-specific
        # mutations gleaned from the message history. We do not modify the
        # original NodeOutput — we copy the patch dict and re-wrap it.
        output: NodeOutput = event.payload["output"]
        patch = dict(output.state_patch)

        scratchpad, finalize_msg = _extract_scratchpad_writes_and_finalize(
            patch.get("messages") or []
        )
        if scratchpad is not None:
            patch["scratchpad"] = scratchpad
        if finalize_msg:
            patch["final_message"] = finalize_msg
        elif output.text and output.text.strip():
            # The LLM wrote prose alongside its finalize/delegate call.
            # ``run_react`` already discarded the text for delegate_to_*
            # (filler), so a non-empty ``output.text`` here means either:
            #   (a) the supervisor called finalize(message="") and put its
            #       reply in the assistant content — use it as final_message,
            #   (b) zero tool calls (casual chat: "привіт" → reply) — same.
            # Either way we want the user to see the prose.
            patch["final_message"] = output.text
        # Pack the supervisor's most recent delegate_to_* tool call so the
        # downstream sub-agent receives the supervisor's specific instruction
        # via the delegation-brief system block.
        brief = _extract_delegate_brief(patch.get("messages") or [])
        if brief is not None:
            patch["delegate_brief"] = brief
        # Fallback: if the LLM emitted plain text WITHOUT making any tool
        # calls (pure casual-chat path: "привіт" → text reply), surface
        # output.text as final_message so the user sees a reply.
        # GUARD: ``tool_calls_made == 0`` is critical. When the supervisor
        # delegates (e.g. delegate_to_researcher), run_react now exits
        # immediately after the tool — but historically the post-tool LLM
        # turn produced filler like "I'm waiting for the researcher" that
        # leaked into final_message and short-circuited the user reply.
        elif output.text and output.tool_calls_made == 0:
            patch["final_message"] = output.text

        logger.warning(
            "supervisor adapter: text_len=%d tool_calls=%d finalize_msg=%r → final_message=%r",
            len(output.text or ""),
            output.tool_calls_made,
            (finalize_msg or "")[:60],
            (patch.get("final_message") or "")[:60],
        )

        new_output = NodeOutput(
            text=output.text,
            structured=output.structured,
            state_patch=patch,
            tool_calls_made=output.tool_calls_made,
            forced_finalize=output.forced_finalize,
        )
        yield NodeStreamEvent(
            kind="finished",
            payload={"output": new_output},
        )
