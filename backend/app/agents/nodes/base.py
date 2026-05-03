"""Shared ReAct loop used by every node (supervisor, planner, diagram, researcher,
critic, explainer).

Owns:
  * :class:`NodeConfig` — the per-node config (system prompt, tools, executor,
    max_steps, optional structured-output schema, optional streaming).
  * :func:`compose_messages_for_llm` — builds the ``[system, ...recent]``
    message list passed to :class:`~app.agents.llm.LLMClient`.
  * :func:`run_react` — async generator that drives the ReAct step loop and
    yields :class:`NodeStreamEvent` events the runtime maps to SSE.

Does NOT own:
  * Pydantic-validated tool wrapping / ACL / audit — those live in
    ``app/agents/tools/base.py`` (task 026). The node-level ``tool_executor``
    callable provided by callers is treated as opaque.
  * Budget / turn enforcement — delegated to
    :class:`~app.agents.limits.LimitsEnforcer` (which the node receives).
  * Compaction policy — delegated to
    :class:`~app.agents.context_manager.ContextManager`.
  * Persistence of ``state['messages']`` — the runtime persists message rows;
    we only mutate the in-memory list for the duration of the node run.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any

from pydantic import BaseModel, ValidationError

from app.agents.context_manager import ContextManager
from app.agents.errors import BudgetExhausted, ContextOverflow, TurnLimitReached
from app.agents.limits import LimitsEnforcer
from app.agents.llm import LLMCallMetadata, LLMResult
from app.agents.state import AgentState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool execution callback type
# ---------------------------------------------------------------------------

# A tool call in OpenAI-shape: ``{"id", "name", "arguments"}``.
# ``arguments`` may be a JSON-encoded string (as the model emits it) or a
# pre-parsed dict (some test fixtures find it convenient).
ToolCall = dict[str, Any]

# Result of executing one tool call.
#   {"tool_call_id": str,
#    "status": "ok" | "error" | "denied",
#    "content": str,        # serialized result body to feed back to the LLM
#    "preview": str}        # short human-friendly preview for SSE
ToolExecutionResult = dict[str, Any]

ToolExecutor = Callable[[ToolCall, AgentState], Awaitable[ToolExecutionResult]]


# ---------------------------------------------------------------------------
# Stream events for SSE
# ---------------------------------------------------------------------------


@dataclass
class NodeStreamEvent:
    """Events emitted by :func:`run_react`. Caller (runtime) maps these to SSE.

    ``kind`` is one of:
      * ``'token'``               — assistant text delta (only when streaming).
      * ``'tool_call'``           — assistant requested a tool call.
      * ``'tool_result'``         — tool executor returned.
      * ``'compaction_applied'``  — :class:`ContextManager` ran a stage.
      * ``'budget_warning'``      — :class:`LimitsEnforcer` latched a warning.
      * ``'finished'``            — terminal; ``payload['output']`` is the
                                    :class:`NodeOutput`.
      * ``'forced_finalize'``     — abnormal exit; ``payload['reason']`` is
                                    ``'budget' | 'turns' | 'context_overflow' |
                                    'max_steps' | 'stuck' | 'cancelled'``.
                                    Followed by a ``'finished'`` event so
                                    callers always observe a single terminal
                                    sentinel.
    """

    kind: str
    payload: dict[str, Any]


# ---------------------------------------------------------------------------
# Node config
# ---------------------------------------------------------------------------


@dataclass
class NodeConfig:
    """Per-node configuration consumed by :func:`run_react`.

    Tool definitions are passed as OpenAI-shape dicts (the LLM-side schema).
    The node-side wrapping (Pydantic validation, ACL, audit) lives in
    ``tools/base.py`` (task 026) — :func:`run_react` treats ``tool_executor``
    as an opaque async callable.

    ``additional_system_blocks`` are callables that render extra markdown
    chunks (e.g., supervisor scratchpad render, applied_changes summary)
    appended after ``system_prompt`` as further ``role='system'`` messages.
    Each callable must be deterministic — it is invoked on every step.
    """

    name: str
    system_prompt: str
    tools: list[dict]
    tool_executor: ToolExecutor
    max_steps: int = 8
    output_schema: type[BaseModel] | None = None
    temperature: float | None = None
    enable_streaming: bool = False
    # Hard cap on output tokens per LLM call. Without this, Qwen / DeepSeek
    # routinely emit 3000-5500 tokens of reasoning_content + JSON for what
    # should be a one-tool-call decision — pushing latency from 5s to 100s
    # per step. Set per-node to something sensible (planner: bigger because
    # it produces a Plan; diagram: smaller because each step is a tool call).
    max_tokens: int | None = None
    additional_system_blocks: list[Callable[[AgentState], str]] = field(default_factory=list)
    # Tool names whose execution should terminate the ReAct loop *immediately*
    # after the tool result is appended — no follow-up LLM call. Used by the
    # supervisor for delegation/finalize tools where the next LLM turn must
    # happen on the *next* graph visit (after sub-agent results land in state).
    # Without this, the post-tool LLM step has no findings yet and emits filler
    # like "I'm waiting…" that pollutes final_message and triggers infinite
    # supervisor↔delegate loops.
    terminating_tool_names: set[str] | None = None


@dataclass
class NodeOutput:
    """What the node returns to the graph.

    Exactly one of ``text`` / ``structured`` is populated on a normal exit,
    depending on whether ``cfg.output_schema`` was set. On abnormal exit
    (``forced_finalize`` set) ``text`` may be ``None``.
    """

    text: str | None = None
    structured: BaseModel | None = None
    state_patch: dict[str, Any] = field(default_factory=dict)
    tool_calls_made: int = 0
    forced_finalize: str | None = None


# ---------------------------------------------------------------------------
# Composer
# ---------------------------------------------------------------------------


def compose_messages_for_llm(
    state: AgentState,
    cfg: NodeConfig,
    *,
    recent_history_limit: int = 20,
) -> list[dict]:
    """Build the message list passed to :class:`LLMClient`.

    Order:
      1. ``system``: ``cfg.system_prompt``
      2. for block in ``cfg.additional_system_blocks``: ``system: block(state)``
      3. last ``recent_history_limit`` items from ``state['messages']``

    ``state['messages']`` contain dicts in OpenAI shape (``role``, ``content``,
    optional ``tool_calls`` / ``tool_call_id``). Messages flagged with
    ``is_compacted=True`` are skipped — those exist only for UI history and
    must not be replayed to the LLM.
    """
    out: list[dict] = [{"role": "system", "content": cfg.system_prompt}]

    for block in cfg.additional_system_blocks:
        try:
            rendered = block(state)
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning(
                "additional_system_block raised in node %r: %s; skipping block",
                cfg.name,
                exc,
            )
            continue
        if rendered:
            out.append({"role": "system", "content": rendered})

    history = state.get("messages") or []
    visible = [m for m in history if not m.get("is_compacted")]
    if recent_history_limit > 0 and len(visible) > recent_history_limit:
        # Always keep the FIRST user message in the prompt — for sub-agents
        # (researcher / planner / diagram / critic) it carries the supervisor
        # brief, and several LLM templates (LM Studio jinja, llama.cpp's
        # default chat template) hard-fail with "No user query found in
        # messages" when they only see system + assistant + tool messages.
        # Without this guard, after a long ReAct loop (~20 tool turns) the
        # brief gets sliced off and the very next LLM call dies with a
        # cryptic 400 from the local model server.
        first_user_idx = next(
            (i for i, m in enumerate(visible) if m.get("role") == "user"),
            None,
        )
        tail = visible[-recent_history_limit:]
        if (
            first_user_idx is not None
            and visible[first_user_idx] not in tail
        ):
            visible = [visible[first_user_idx], *tail]
        else:
            visible = tail

    out.extend(visible)
    return out


# ---------------------------------------------------------------------------
# Helper: render sub-agent results as a system block
# ---------------------------------------------------------------------------


def render_subagent_results_block(state: AgentState) -> str:
    """Render a system block summarising what sub-agents have produced so far.

    Used by the supervisor on its 2nd+ visit so the LLM can build on prior
    delegate output instead of re-issuing the same delegation indefinitely.
    Returns an empty string when no sub-agent has produced results yet — the
    first supervisor visit then sees clean context.

    Sources surfaced (rendered in full so the supervisor has every piece of
    information it needs to decide the next action without re-delegation):
      * ``state['findings']`` — researcher's :class:`Findings` (or dict).
      * ``state['plan']`` — planner's :class:`Plan` (or dict).
      * ``state['applied_changes']`` — list of mutations applied by diagram.
      * ``state['critique']`` — critic's :class:`Critique` (or dict).
    """
    findings = state.get("findings")
    plan = state.get("plan")
    applied = state.get("applied_changes") or []
    critique = state.get("critique")

    if not (findings or plan or applied or critique):
        return ""

    lines: list[str] = [
        "## Sub-agent results so far",
        "_(authoritative — re-delegating to the same sub-agent with the "
        "**same subject** is forbidden. Re-delegate only with a different "
        "subject (object/diagram/connection), a new angle/hypothesis, or a "
        "concrete approach hint. Otherwise compose your reply from these "
        "artefacts and call `finalize`.)_",
    ]

    if findings is not None:
        summary = (
            getattr(findings, "summary", None)
            if not isinstance(findings, dict)
            else findings.get("summary")
        )
        confidence = (
            getattr(findings, "confidence", None)
            if not isinstance(findings, dict)
            else findings.get("confidence")
        ) or "medium"
        body = (summary or "").strip() or "(empty summary)"
        lines.append(f"\n### Findings from researcher (confidence: {confidence})")
        lines.append(body)

    if plan is not None:
        steps = (
            getattr(plan, "steps", None)
            if not isinstance(plan, dict)
            else plan.get("steps")
        ) or []
        goal = (
            getattr(plan, "goal", None)
            if not isinstance(plan, dict)
            else plan.get("goal")
        ) or ""
        lines.append("\n### Plan from planner")
        if goal:
            lines.append(f"**Goal:** {goal}")
        if steps:
            for i, step in enumerate(steps, 1):
                kind = (
                    getattr(step, "kind", None)
                    if not isinstance(step, dict)
                    else step.get("kind")
                ) or "?"
                rationale = (
                    getattr(step, "rationale", None)
                    if not isinstance(step, dict)
                    else step.get("rationale")
                ) or ""
                args = (
                    getattr(step, "args", None)
                    if not isinstance(step, dict)
                    else step.get("args")
                ) or {}
                args_preview = ""
                if isinstance(args, dict) and args:
                    bits = [f"{k}={v}" for k, v in list(args.items())[:3]]
                    args_preview = f" `{', '.join(bits)}`"
                line = f"{i}. **{kind}**{args_preview}"
                if rationale:
                    line += f" — {rationale}"
                lines.append(line)
        else:
            lines.append("(no steps)")

    if applied:
        lines.append(f"\n### Applied changes ({len(applied)} total)")
        for change in applied:
            action = change.get("action", "?")
            name = change.get("name") or "?"
            target_id = change.get("target_id")
            target_str = f" `{target_id}`" if target_id else ""
            lines.append(f"- {action}: **{name}**{target_str}")

    if critique is not None:
        verdict = (
            getattr(critique, "verdict", None)
            if not isinstance(critique, dict)
            else critique.get("verdict")
        ) or "?"
        issues = (
            getattr(critique, "issues", None)
            if not isinstance(critique, dict)
            else critique.get("issues")
        ) or []
        strengths = (
            getattr(critique, "strengths", None)
            if not isinstance(critique, dict)
            else critique.get("strengths")
        ) or []
        revision = (
            getattr(critique, "revision_request", None)
            if not isinstance(critique, dict)
            else critique.get("revision_request")
        )
        lines.append(f"\n### Critique from critic — **{verdict}**")
        if strengths:
            lines.append("**Strengths:**")
            for s in strengths:
                lines.append(f"- {s}")
        if issues:
            lines.append("**Issues:**")
            for i in issues:
                lines.append(f"- {i}")
        if revision:
            lines.append(f"**Revision request:** {revision}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helper: render a sub-agent's result into the matching tool result message
# ---------------------------------------------------------------------------


_DELEGATE_TOOL_TO_KIND: dict[str, str] = {
    "delegate_to_researcher": "researcher",
    "delegate_to_planner": "planner",
    "delegate_to_diagram": "diagram",
    "delegate_to_critic": "critic",
}


def _render_findings(findings: Any) -> str:
    summary = (
        getattr(findings, "summary", None)
        if not isinstance(findings, dict)
        else findings.get("summary")
    )
    confidence = (
        getattr(findings, "confidence", None)
        if not isinstance(findings, dict)
        else findings.get("confidence")
    ) or "medium"
    body = (summary or "").strip() or "(empty summary)"
    return f"### Findings from researcher (confidence: {confidence})\n{body}"


def _render_plan(plan: Any) -> str:
    steps = (
        getattr(plan, "steps", None)
        if not isinstance(plan, dict)
        else plan.get("steps")
    ) or []
    goal = (
        getattr(plan, "goal", None)
        if not isinstance(plan, dict)
        else plan.get("goal")
    ) or ""
    lines = ["### Plan from planner"]
    if goal:
        lines.append(f"**Goal:** {goal}")
    if steps:
        for i, step in enumerate(steps, 1):
            kind = (
                getattr(step, "kind", None)
                if not isinstance(step, dict)
                else step.get("kind")
            ) or "?"
            rationale = (
                getattr(step, "rationale", None)
                if not isinstance(step, dict)
                else step.get("rationale")
            ) or ""
            args = (
                getattr(step, "args", None)
                if not isinstance(step, dict)
                else step.get("args")
            ) or {}
            args_preview = ""
            if isinstance(args, dict) and args:
                bits = [f"{k}={v}" for k, v in list(args.items())[:3]]
                args_preview = f" `{', '.join(bits)}`"
            line = f"{i}. **{kind}**{args_preview}"
            if rationale:
                line += f" — {rationale}"
            lines.append(line)
    else:
        lines.append("(no steps)")
    return "\n".join(lines)


def _render_applied(applied: list[dict]) -> str:
    lines = [f"### Applied changes ({len(applied)} total)"]
    if not applied:
        lines.append("(no changes were applied)")
        return "\n".join(lines)
    for change in applied:
        action = change.get("action", "?")
        name = change.get("name") or "?"
        target_id = change.get("target_id")
        target_str = f" `{target_id}`" if target_id else ""
        lines.append(f"- {action}: **{name}**{target_str}")
    return "\n".join(lines)


def _render_critique(critique: Any) -> str:
    verdict = (
        getattr(critique, "verdict", None)
        if not isinstance(critique, dict)
        else critique.get("verdict")
    ) or "?"
    issues = (
        getattr(critique, "issues", None)
        if not isinstance(critique, dict)
        else critique.get("issues")
    ) or []
    strengths = (
        getattr(critique, "strengths", None)
        if not isinstance(critique, dict)
        else critique.get("strengths")
    ) or []
    revision = (
        getattr(critique, "revision_request", None)
        if not isinstance(critique, dict)
        else critique.get("revision_request")
    )
    lines = [f"### Critique from critic — **{verdict}**"]
    if strengths:
        lines.append("**Strengths:**")
        for s in strengths:
            lines.append(f"- {s}")
    if issues:
        lines.append("**Issues:**")
        for i in issues:
            lines.append(f"- {i}")
    if revision:
        lines.append(f"**Revision request:** {revision}")
    return "\n".join(lines)


def rewrite_subagent_tool_result(
    parent_messages: list[dict],
    *,
    kind: str,
    findings: Any | None = None,
    plan: Any | None = None,
    applied_changes: list[dict] | None = None,
    critique: Any | None = None,
) -> list[dict]:
    """Return a copy of ``parent_messages`` with the most recent ``delegate_to_<kind>``
    tool result rewritten to carry the actual sub-agent output.

    Without this, the supervisor's history shows the OpenAI tool-call protocol
    pair as ``[assistant: tool_call(delegate_to_researcher, args)]`` followed
    by ``[tool: {"action": "delegate.researcher", "question": "..."}]`` —
    the latter is just an echo of the supervisor's input, not the researcher's
    answer. With many local models (Qwen / DeepSeek) that mismatch causes the
    supervisor to re-issue the same delegation indefinitely.

    This helper finds the latest assistant message containing a
    ``delegate_to_<kind>`` tool call, then walks forward to the matching tool
    result (by ``tool_call_id``) and replaces its ``content`` with a markdown
    summary of the supplied artefact.

    No-op when no matching pair is found — guards against missing brief or
    out-of-order graph routing.
    """
    expected_tool = f"delegate_to_{kind}"
    if expected_tool not in _DELEGATE_TOOL_TO_KIND:
        return list(parent_messages)

    if findings is not None:
        new_content = _render_findings(findings)
    elif plan is not None:
        new_content = _render_plan(plan)
    elif applied_changes is not None:
        new_content = _render_applied(applied_changes)
    elif critique is not None:
        new_content = _render_critique(critique)
    else:
        return list(parent_messages)

    rewritten = list(parent_messages)
    # Walk backwards for the latest assistant turn with a matching delegate call.
    target_call_id: str | None = None
    for idx in range(len(rewritten) - 1, -1, -1):
        msg = rewritten[idx]
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            name = fn.get("name") or tc.get("name")
            if name == expected_tool:
                target_call_id = tc.get("id")
                break
        if target_call_id is not None:
            break

    if target_call_id is None:
        return rewritten

    # Find the matching tool result (forward search; usually next message).
    for idx, msg in enumerate(rewritten):
        if (
            msg.get("role") == "tool"
            and msg.get("tool_call_id") == target_call_id
        ):
            replaced = dict(msg)
            replaced["content"] = new_content
            rewritten[idx] = replaced
            break

    return rewritten


# ---------------------------------------------------------------------------
# Helper: render delegation brief + active chat context for sub-agents
# ---------------------------------------------------------------------------


def render_delegation_brief_block(state: AgentState) -> str:
    """Render the supervisor's brief for the current sub-agent.

    The supervisor passes a ``delegate_to_<sub>`` tool call with either
    ``question`` (researcher), ``focus`` + ``reason`` (planner), or
    ``action_hint`` (diagram). The supervisor adapter packs this into
    ``state['delegate_brief']`` before the graph hands control to the
    sub-agent, so the sub-agent can read its instruction directly instead of
    inferring intent from the raw user history.

    Returns an empty string when no brief is present (e.g. the standalone
    researcher graph that's invoked without a supervisor).
    """
    brief = state.get("delegate_brief") or {}
    if not isinstance(brief, dict):
        return ""
    instruction = (brief.get("instruction") or "").strip()
    if not instruction:
        return ""
    lines = ["## Supervisor brief"]
    lines.append(instruction)
    reason = (brief.get("reason") or "").strip()
    if reason:
        lines.append(f"\n_Reason:_ {reason}")
    lines.append(
        "\nFocus on this brief. The conversation history is provided for "
        "context only — answer the brief, not the raw user message."
    )
    return "\n".join(lines)


def isolated_state_for_subagent(
    state: AgentState,
    *,
    fallback_user_message: str | None = None,
    include_original_request: bool = False,
) -> AgentState:
    """Return a shallow copy of ``state`` with ``messages`` replaced by an
    isolated, **fully-contextualised** single user message.

    Sub-agents (researcher / planner / diagram / critic) run as *tools* of
    the supervisor — they don't see its ReAct chatter, its delegate tool
    calls, or its scratchpad. They get:

      1. The supervisor's specific brief for this delegation — what
         exactly the supervisor wants this sub-agent to do.
      2. Optional reason / hint that supervisor passed along.
      3. Only when ``include_original_request=True``: the user's verbatim
         ask. By default this is **omitted** — research / plan /
         diagram-execute sub-agents work better when they read the
         supervisor's distilled brief than when they re-interpret the
         raw user text (which often paraphrases, mentions things outside
         the current sub-task, or argues with itself). Critic (and any
         future validator) MUST set ``include_original_request=True``
         since their job is to verify the work against the original goal.

    All of the above is packed into ONE user message so the model sees a
    clean conversation: system prompt → context blocks → user (brief) →
    its own ReAct turns.

    Wrappers must NOT propagate ``patch['messages']`` back into global
    state — only structured outputs (findings / plan / applied_changes /
    critique) flow back.
    """
    brief = state.get("delegate_brief") or {}
    instruction = ""
    reason = ""
    if isinstance(brief, dict):
        raw_i = brief.get("instruction")
        raw_r = brief.get("reason")
        if isinstance(raw_i, str):
            instruction = raw_i.strip()
        if isinstance(raw_r, str):
            reason = raw_r.strip()

    # The original user request is the FIRST user-role message in the
    # supervisor's history. Surfaced only when the caller explicitly opted
    # in via ``include_original_request`` — used by the critic to verify
    # the work against the user's stated goal.
    original_user: str | None = None
    if include_original_request:
        for msg in (state.get("messages") or []):
            if msg.get("role") == "user" and isinstance(msg.get("content"), str):
                content = msg["content"].strip()
                if content:
                    original_user = content
                    break

    if not instruction and fallback_user_message:
        instruction = fallback_user_message.strip()

    # Compose the unified user message. Markdown headings let local models
    # cleanly distinguish "user goal" from "what supervisor wants from me"
    # when both are present.
    parts: list[str] = []
    if original_user:
        parts.append(f"## Original user request\n{original_user}")
    if instruction:
        parts.append(f"## Your specific task\n{instruction}")
    if reason:
        parts.append(f"_Supervisor's reasoning:_ {reason}")
    if not parts:
        parts.append("(no instruction provided — use the active context "
                     "block to determine what to do)")

    user_msg = "\n\n".join(parts)

    isolated: AgentState = dict(state)  # type: ignore[assignment]
    isolated["messages"] = [{"role": "user", "content": user_msg}]
    return isolated


def render_active_context_block(state: AgentState) -> str:
    """Render the chat_context (which diagram / object is open) for any node.

    Mirrors :func:`app.agents.builtin.general.nodes.diagram.render_active_diagram_block`
    but lives here so read-only sub-agents (researcher, critic) can consume
    it without importing the diagram module. Tells the LLM which workspace
    entity the user is currently viewing so it scopes its tool calls
    accordingly.
    """
    chat_context = state.get("chat_context") or {}

    def _attr(o: Any, key: str, default: Any = None) -> Any:
        if isinstance(o, dict):
            return o.get(key, default)
        return getattr(o, key, default)

    kind = _attr(chat_context, "kind", None) or "none"
    cid = _attr(chat_context, "id", None)
    parent_id = _attr(chat_context, "parent_diagram_id", None)
    draft_id = _attr(chat_context, "draft_id", None) or state.get("active_draft_id")

    lines = ["## Active context"]
    if kind == "diagram":
        primary = f"User is viewing diagram `{cid}`."
        if parent_id:
            primary += f" Parent diagram: `{parent_id}`."
        if draft_id:
            primary += f" Active draft: `{draft_id}`."
        lines.append(primary)
        lines.append(
            "When the user says 'this diagram' / 'тут' / 'на діаграмі', "
            "they mean this one. Start with `read_diagram` to see its "
            "placements and connections."
        )
    elif kind == "object":
        lines.append(f"User is viewing object `{cid}`.")
        lines.append("Use `read_object_full` to inspect it.")
    elif kind == "workspace":
        lines.append(f"User is at workspace scope (`{cid}`). No diagram pinned.")
        lines.append("Use `list_diagrams` to enumerate diagrams if needed.")
    else:
        lines.append("No diagram or object pinned in this chat context.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helper: parse structured output
# ---------------------------------------------------------------------------


_JSON_FENCE_RE = re.compile(
    r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```",
    re.DOTALL | re.IGNORECASE,
)


def _extract_json_blob(text: str) -> str | None:
    """Best-effort extract a JSON object/array from free-form LLM text.

    Tries (in order):
      1. The whole string, after stripping whitespace.
      2. The first ```json fenced block.
      3. The substring between the first ``{`` (or ``[``) and the matching
         last ``}`` (or ``]``) — naive but works on most "JSON wrapped in
         a sentence" outputs.
    """
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith(("{", "[")):
        return stripped

    fence_match = _JSON_FENCE_RE.search(text)
    if fence_match:
        return fence_match.group(1).strip()

    # Naive bracket-balanced fallback.
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = text.find(open_ch)
        end = text.rfind(close_ch)
        if start != -1 and end != -1 and end > start:
            return text[start : end + 1]
    return None


def _parse_structured_output(
    text: str | None, schema: type[BaseModel]
) -> tuple[BaseModel | None, str | None]:
    """Return ``(parsed_model, error_str)``.

    Tries to extract JSON from ``text`` (handles `````json`` fences and naked
    objects). Returns ``(None, error_str)`` on parse / validation failure;
    callers fall back to passing ``text`` through unparsed.
    """
    if not text:
        return None, "empty assistant text"
    blob = _extract_json_blob(text)
    if blob is None:
        return None, "no JSON object found in assistant text"
    try:
        payload = json.loads(blob)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"
    try:
        return schema.model_validate(payload), None
    except ValidationError as exc:
        return None, f"schema validation failed: {exc}"


# ---------------------------------------------------------------------------
# Helpers for ReAct loop bookkeeping
# ---------------------------------------------------------------------------


def _normalize_tool_arguments(arguments: Any) -> str:
    """Return a JSON string for the OpenAI assistant ``tool_calls`` shape.

    ``LLMResult.tool_calls`` may carry ``arguments`` as either a raw JSON
    string (the wire format) or a dict (some providers / our streaming
    accumulator). We normalize to a string before stashing on the assistant
    message so the on-wire shape stays consistent across providers.
    """
    if arguments is None:
        return ""
    if isinstance(arguments, str):
        return arguments
    try:
        return json.dumps(arguments)
    except (TypeError, ValueError):  # pragma: no cover — defensive
        return str(arguments)


def _build_assistant_tool_call_message(result: LLMResult) -> dict[str, Any]:
    """Build the assistant message stub that precedes the tool replies."""
    tool_calls_payload: list[dict[str, Any]] = []
    for tc in result.tool_calls or []:
        tool_calls_payload.append(
            {
                "id": tc.get("id") or "",
                "type": "function",
                "function": {
                    "name": tc.get("name") or "",
                    "arguments": _normalize_tool_arguments(tc.get("arguments")),
                },
            }
        )
    return {
        "role": "assistant",
        "content": result.text,
        "tool_calls": tool_calls_payload,
    }


def _build_tool_result_message(
    tool_call: ToolCall, result: ToolExecutionResult
) -> dict[str, Any]:
    """Build the ``role='tool'`` message appended after the assistant call."""
    return {
        "role": "tool",
        "tool_call_id": result.get("tool_call_id") or tool_call.get("id") or "",
        "name": tool_call.get("name"),
        "content": result.get("content") or "",
    }


# ---------------------------------------------------------------------------
# Main ReAct loop
# ---------------------------------------------------------------------------


async def run_react(
    state: AgentState,
    cfg: NodeConfig,
    *,
    enforcer: LimitsEnforcer,
    context_manager: ContextManager,
    call_metadata_base: LLMCallMetadata,
    current_compaction_stage: int = 0,
) -> AsyncIterator[NodeStreamEvent]:
    """Drive the ReAct loop and yield :class:`NodeStreamEvent` events.

    Algorithm per step:
      1. Compose messages.
      2. ``context_manager.maybe_compact`` → if applied, yield
         ``compaction_applied`` and update the local stage counter (also
         mirrored on the returned ``state_patch`` so the caller can persist).
      3. ``enforcer.acompletion`` (handles budget + turns + health-check).
      4. If response has no tool_calls → terminal. Yield ``finished`` with
         ``output.text`` (parse to ``cfg.output_schema`` if set; on JSON parse
         failure return ``text`` + log a warning).
      5. If response has tool_calls: yield one ``tool_call`` event per call,
         await ``cfg.tool_executor``, yield matching ``tool_result``, append
         the assistant + tool messages, continue.
      6. After the LLM call, drain any pending budget warning via
         ``enforcer.consume_budget_warning()``.
      7. On :class:`BudgetExhausted` / :class:`TurnLimitReached` /
         :class:`ContextOverflow` → yield ``forced_finalize`` then
         ``finished`` with the abnormal output.
      8. On reaching ``cfg.max_steps`` → yield ``forced_finalize`` with
         ``reason='max_steps'`` then ``finished``.

    The caller iterates::

        async for ev in run_react(...):
            if ev.kind == 'finished':
                output = ev.payload['output']
    """
    # Local working copy of state.messages — we mutate this list and surface
    # it back via NodeOutput.state_patch['messages'] so the caller can persist
    # the new turn rows.
    messages: list[dict] = list(state.get("messages") or [])
    working_state: AgentState = dict(state)  # type: ignore[assignment]
    working_state["messages"] = messages

    compaction_stage = current_compaction_stage
    tool_calls_made = 0
    # Local LLMs (Qwen reasoning, etc.) sometimes return a completion with
    # neither tool_calls nor visible content — usually after spending the whole
    # budget in their internal reasoning chain. Retry such empty replies up to
    # _MAX_EMPTY_RETRIES times before giving up. Each retry still counts as
    # a step so the budget/turn-limit catches genuinely broken loops.
    _MAX_EMPTY_RETRIES = 2
    empty_retries = 0

    for step in range(cfg.max_steps):
        prompt = compose_messages_for_llm(working_state, cfg)

        # --- compaction ---
        try:
            compaction = await context_manager.maybe_compact(
                prompt,
                llm=enforcer.llm,
                current_stage=compaction_stage,
                call_metadata=call_metadata_base,
                tools=cfg.tools or None,
            )
        except ContextOverflow as exc:
            logger.warning(
                "node %r: ContextOverflow during compaction: %s",
                cfg.name,
                exc,
            )
            output = NodeOutput(
                text=None,
                state_patch={
                    "messages": messages,
                    "compaction_stage": compaction_stage,
                },
                tool_calls_made=tool_calls_made,
                forced_finalize="context_overflow",
            )
            yield NodeStreamEvent(
                kind="forced_finalize",
                payload={"reason": "context_overflow", "node": cfg.name, "detail": str(exc)},
            )
            yield NodeStreamEvent(kind="finished", payload={"output": output})
            return

        if compaction.stage_applied > 0:
            compaction_stage = compaction.stage_applied
            prompt = compaction.compacted_messages
            yield NodeStreamEvent(
                kind="compaction_applied",
                payload={
                    "stage": compaction.stage_applied,
                    "strategy": compaction.strategy_name,
                    "tokens_before": compaction.tokens_before,
                    "tokens_after": compaction.tokens_after,
                    "node": cfg.name,
                },
            )

        # --- per-step metadata ---
        # Preserve every field on the base metadata; only override node-local
        # ones. Without this, fields added later (trace_id,
        # parent_observation_id) silently get lost on each step and Langfuse
        # creates a fresh trace per LLM call instead of grouping them.
        call_metadata = replace(
            call_metadata_base,
            node_name=cfg.name,
            step_index=step,
        )

        # --- LLM call (non-streaming Phase 1 path; streaming wired below) ---
        try:
            result = await enforcer.acompletion(
                prompt,
                tools=cfg.tools or None,
                metadata=call_metadata,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
            )
            logger.warning(
                "run_react[%s] step=%d result: text_len=%d tool_calls=%d finish=%s",
                cfg.name,
                step,
                len(result.text or ""),
                len(result.tool_calls or []),
                getattr(result, "finish_reason", "?"),
            )
        except BudgetExhausted as exc:
            yield NodeStreamEvent(
                kind="forced_finalize",
                payload={"reason": "budget", "node": cfg.name, "detail": str(exc)},
            )
            yield NodeStreamEvent(
                kind="finished",
                payload={
                    "output": NodeOutput(
                        text=None,
                        state_patch={
                            "messages": messages,
                            "compaction_stage": compaction_stage,
                        },
                        tool_calls_made=tool_calls_made,
                        forced_finalize="budget",
                    )
                },
            )
            return
        except TurnLimitReached as exc:
            yield NodeStreamEvent(
                kind="forced_finalize",
                payload={"reason": "turns", "node": cfg.name, "detail": str(exc)},
            )
            yield NodeStreamEvent(
                kind="finished",
                payload={
                    "output": NodeOutput(
                        text=None,
                        state_patch={
                            "messages": messages,
                            "compaction_stage": compaction_stage,
                        },
                        tool_calls_made=tool_calls_made,
                        forced_finalize="turns",
                    )
                },
            )
            return
        except ContextOverflow as exc:
            yield NodeStreamEvent(
                kind="forced_finalize",
                payload={"reason": "context_overflow", "node": cfg.name, "detail": str(exc)},
            )
            yield NodeStreamEvent(
                kind="finished",
                payload={
                    "output": NodeOutput(
                        text=None,
                        state_patch={
                            "messages": messages,
                            "compaction_stage": compaction_stage,
                        },
                        tool_calls_made=tool_calls_made,
                        forced_finalize="context_overflow",
                    )
                },
            )
            return

        # --- budget warning latch (one-shot) ---
        warning = enforcer.consume_budget_warning()
        if warning is not None:
            used, limit = warning
            yield NodeStreamEvent(
                kind="budget_warning",
                payload={
                    "used_usd": used,
                    "limit_usd": limit,
                    "scope": enforcer.limits.budget_scope,
                    "node": cfg.name,
                },
            )

        # --- streaming token surface (when enabled) ---
        # NOTE: Phase 1 default for nodes other than supervisor is non-streaming.
        # When ``enable_streaming`` is True, we emit a single 'token' event with
        # the full assistant text (concatenated). True per-token streaming via
        # ``llm.astream`` is wired by the supervisor node in task 018; doing it
        # here would force every node to choose streaming-vs-not.
        if cfg.enable_streaming and result.text:
            yield NodeStreamEvent(
                kind="token",
                payload={"delta": result.text, "node": cfg.name},
            )

        # --- empty-reply retry guard ---
        # Some local models occasionally return a completion with neither
        # tool_calls nor visible text. Retry up to _MAX_EMPTY_RETRIES times
        # before falling through to the terminal path (which would otherwise
        # surface an empty assistant message).
        if (
            not result.tool_calls
            and not (result.text or "").strip()
            and empty_retries < _MAX_EMPTY_RETRIES
        ):
            empty_retries += 1
            logger.warning(
                "run_react[%s] step=%d empty completion (retry %d/%d) — re-running",
                cfg.name,
                step,
                empty_retries,
                _MAX_EMPTY_RETRIES,
            )
            continue  # next iteration re-runs the LLM with the same history

        # --- terminal (no tool_calls) ---
        if not result.tool_calls:
            text = result.text
            structured: BaseModel | None = None
            if cfg.output_schema is not None:
                parsed, err = _parse_structured_output(text, cfg.output_schema)
                if parsed is not None:
                    structured = parsed
                else:
                    logger.warning(
                        "node %r: structured output parse failed: %s",
                        cfg.name,
                        err,
                    )

            # Append assistant message to the working history so the runtime
            # can persist it.
            messages.append({"role": "assistant", "content": text})

            output = NodeOutput(
                text=text,
                structured=structured,
                state_patch={
                    "messages": messages,
                    "compaction_stage": compaction_stage,
                },
                tool_calls_made=tool_calls_made,
                forced_finalize=None,
            )
            yield NodeStreamEvent(kind="finished", payload={"output": output})
            return

        # --- tool calls path ---
        # Append the assistant turn (with tool_calls) BEFORE the tool replies
        # so OpenAI-style chat history stays well-formed.
        assistant_msg = _build_assistant_tool_call_message(result)
        messages.append(assistant_msg)

        terminate_after_tools = False
        last_terminating_tool: str | None = None
        for tc in result.tool_calls:
            tool_call_evt: ToolCall = {
                "id": tc.get("id"),
                "name": tc.get("name"),
                "arguments": tc.get("arguments"),
            }
            yield NodeStreamEvent(
                kind="tool_call",
                payload={
                    "id": tool_call_evt["id"],
                    "name": tool_call_evt["name"],
                    "arguments": tool_call_evt["arguments"],
                    "node": cfg.name,
                },
            )

            try:
                tool_result = await cfg.tool_executor(tool_call_evt, working_state)
            except Exception as exc:  # pragma: no cover — defensive
                logger.exception(
                    "node %r: tool_executor raised for tool %r",
                    cfg.name,
                    tool_call_evt.get("name"),
                )
                tool_result = {
                    "tool_call_id": tool_call_evt.get("id") or "",
                    "status": "error",
                    "content": f"tool execution raised: {exc}",
                    "preview": "tool execution raised an exception",
                }

            tool_calls_made += 1
            yield NodeStreamEvent(
                kind="tool_result",
                payload={
                    "id": tool_result.get("tool_call_id") or tool_call_evt.get("id"),
                    "status": tool_result.get("status", "ok"),
                    "preview": tool_result.get("preview", ""),
                    # Full serialised tool result (e.g. JSON dump of the
                    # object/connection). Tracing layer surfaces this as the
                    # event's ``output`` so Langfuse shows the real data, not
                    # just an "<tool> ok" preview.
                    "content": tool_result.get("content", ""),
                    "node": cfg.name,
                },
            )

            messages.append(_build_tool_result_message(tool_call_evt, tool_result))

            # Terminating tool? Exit the ReAct loop without re-prompting the
            # LLM. The next LLM turn (if any) belongs to a downstream node or
            # a follow-up graph visit — calling the LLM again here would burn
            # a step on a context that has no useful new info.
            if (
                cfg.terminating_tool_names
                and (tool_call_evt.get("name") in cfg.terminating_tool_names)
            ):
                terminate_after_tools = True
                last_terminating_tool = tool_call_evt.get("name")

        if terminate_after_tools:
            # For ``finalize`` we keep the LLM's prose — the supervisor often
            # writes the user-facing reply alongside the finalize call and
            # only sets ``finalize.message`` when it wants to override it.
            # For ``delegate_to_*`` we drop the prose: it's typically filler
            # like "I'm asking the researcher now" that should not leak into
            # the user-facing transcript.
            preserved_text = (
                result.text if last_terminating_tool == "finalize" else None
            )
            output = NodeOutput(
                text=preserved_text,
                structured=None,
                state_patch={
                    "messages": messages,
                    "compaction_stage": compaction_stage,
                },
                tool_calls_made=tool_calls_made,
                forced_finalize=None,
            )
            yield NodeStreamEvent(kind="finished", payload={"output": output})
            return

        # Loop continues — next step composes fresh messages from updated history.

    # --- max_steps exhausted ---
    output = NodeOutput(
        text=None,
        state_patch={
            "messages": messages,
            "compaction_stage": compaction_stage,
        },
        tool_calls_made=tool_calls_made,
        forced_finalize="max_steps",
    )
    yield NodeStreamEvent(
        kind="forced_finalize",
        payload={
            "reason": "max_steps",
            "node": cfg.name,
            "max_steps": cfg.max_steps,
        },
    )
    yield NodeStreamEvent(kind="finished", payload={"output": output})
