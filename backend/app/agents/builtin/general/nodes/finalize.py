"""Non-LLM aggregator: builds the final assistant message from state.applied_changes
+ critique + warnings. Used as the terminal node of the general agent graph."""

from __future__ import annotations

import contextlib
from collections import Counter
from typing import Any

from app.agents.state import AgentState

# ---------------------------------------------------------------------------
# Lead-line mapping
# ---------------------------------------------------------------------------

_LEAD_LINES: dict[str | None, str] = {
    None: "Done. Applied {n} change{s}:",
    "completed": "Done. Applied {n} change{s}:",
    "budget": "I ran out of budget. Here's what I got done:",
    "turns": "I hit the turn limit. Here's what I got done:",
    "stuck": "I detected I was looping and stopped. Partial result:",
    "cancelled": "Stopped at your request. Done so far:",
    "context_overflow": "The context grew too large to continue. Partial result:",
    "max_steps": "I reached max steps for a node. Partial result:",
}

# Reasons that don't use the "{n} change{s}" interpolation
_STATIC_LEAD = frozenset({"budget", "turns", "stuck", "cancelled", "context_overflow", "max_steps"})

# Threshold for switching to collapsed view
_COLLAPSE_THRESHOLD = 5

# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def render_action_line(change: dict) -> str:
    """Render a single applied_change dict to a markdown bullet line.

    change shape::

        {
            action: 'object.created' | 'connection.created' | 'diagram.created' |
                    'object.updated' | 'object.deleted' | 'connection.updated' |
                    'connection.deleted' | 'diagram.updated' | 'diagram.deleted' | ...,
            target_id: UUID,
            name: str,
            target_type: str,   # 'object' | 'connection' | 'diagram'
            ...extras           # e.g. fields_changed for 'updated' actions
        }
    """
    action: str = change.get("action", "")
    target_id = change.get("target_id", "")
    name: str = change.get("name") or str(target_id)

    # Determine the link scheme from target_type or fall back to parsing action
    target_type: str = change.get("target_type", "")
    if not target_type:
        # derive from action prefix: "object.created" → "object"
        target_type = action.split(".")[0] if "." in action else "object"

    link = f"archflow://{target_type}/{target_id}"
    label = f"[{name}]({link})"

    # Derive verb and extra text
    if action.endswith(".created"):
        verb = "Created"
        # Include target_type hint
        _known = ("object", "connection", "diagram")
        kind_hint = f"`{target_type}`" if target_type not in _known else ""
        line = f"✓ Created {target_type} {label}" + (f" ({kind_hint})" if kind_hint else "")
    elif action.endswith(".updated"):
        verb = "Updated"  # noqa: F841
        fields_changed: str = change.get("fields_changed", "")
        suffix = f": {fields_changed}" if fields_changed else ""
        line = f"✓ Updated {target_type} {label}{suffix}"
    elif action.endswith(".deleted"):
        line = f"✓ Deleted {target_type} {label}"
    else:
        # Generic fallback for unknown action verbs
        line = f"✓ {action} {label}"

    return f"- {line}"


def collapse_changes(applied: list[dict]) -> str:
    """When len(applied) >= _COLLAPSE_THRESHOLD, group by action type.

    Example output: '5 objects created, 3 connections created, 1 diagram updated'
    """
    counts: Counter[str] = Counter()
    for change in applied:
        action: str = change.get("action", "unknown")
        # Normalise e.g. 'object.created' → 'object created'
        label = action.replace(".", " ")
        counts[label] += 1

    parts = []
    for label, count in counts.most_common():
        noun = label  # already readable
        parts.append(f"{count} {noun}")
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Core builder
# ---------------------------------------------------------------------------


def build_final_message(state: AgentState) -> str:
    """Construct a markdown summary string from state.

    Sections (each only included if non-empty):

    1. **Lead line** — based on state.forced_finalize.
    2. **Applied changes** — bullet list (or collapsed count when ≥ 5).
    3. **Warnings** — from state.critique.issues.
    4. **Next steps** — from state.pending_changes.
    5. **Cost footnote** — italic, with tokens and cost.

    Returns the markdown string. The caller stores it in state.final_message.
    Does NOT call any LLM. Does NOT touch the DB.
    """
    forced: str | None = state.get("forced_finalize")
    applied: list[dict] = state.get("applied_changes") or []
    n = len(applied)

    # ------------------------------------------------------------------
    # 0. Read-only short-circuit: if the researcher produced a Findings and
    # no mutations were applied, surface the findings.summary as the user
    # reply instead of the placeholder "No changes were applied." This is
    # the common path for "explain X" / "what's on this diagram?" questions
    # where the supervisor delegates to the researcher and then can't
    # decide what to say (or returns empty completions on local models).
    # ------------------------------------------------------------------
    if not forced and n == 0:
        findings = state.get("findings")
        summary = (
            getattr(findings, "summary", None)
            if not isinstance(findings, dict)
            else findings.get("summary")
        )
        if summary and summary.strip():
            return summary.strip()

    # ------------------------------------------------------------------
    # 1. Lead line
    # ------------------------------------------------------------------
    lead_template = _LEAD_LINES.get(forced, _LEAD_LINES[None])
    if forced in _STATIC_LEAD:
        lead = lead_template
    elif n == 0:
        lead = "No changes were applied."
    else:
        s = "" if n == 1 else "s"
        lead = lead_template.format(n=n, s=s)

    sections: list[str] = [lead]

    # ------------------------------------------------------------------
    # 2. Applied changes
    # ------------------------------------------------------------------
    if applied:
        if n >= _COLLAPSE_THRESHOLD:
            collapsed = collapse_changes(applied)
            sections.append(f"\n{collapsed}")
        else:
            lines = [render_action_line(c) for c in applied]
            sections.append("\n" + "\n".join(lines))

    # ------------------------------------------------------------------
    # 3. Warnings (from critique.issues)
    # ------------------------------------------------------------------
    critique: Any = state.get("critique")
    issues: list[str] = []
    if critique is not None:
        if hasattr(critique, "issues"):
            issues = critique.issues or []
        elif isinstance(critique, dict):
            issues = critique.get("issues") or []

    if issues:
        warning_lines = "\n".join(f"- {issue}" for issue in issues)
        sections.append(f"\n**Warnings**\n{warning_lines}")

    # ------------------------------------------------------------------
    # 4. Next steps (from pending_changes)
    # ------------------------------------------------------------------
    pending: list[dict] = state.get("pending_changes") or []
    if pending:
        pending_count = len(pending)
        noun = "change" if pending_count == 1 else "changes"
        sections.append(
            f"\n**Next steps**\n"
            f"{pending_count} {noun} could not be completed in this session. "
            "Start a new conversation to continue."
        )

    # ------------------------------------------------------------------
    # 5. Cost footnote
    # ------------------------------------------------------------------
    tokens_in: int = state.get("tokens_in") or 0
    tokens_out: int = state.get("tokens_out") or 0
    budget_counters: dict = state.get("budget_counters") or {}

    # Sum cost across all sub-agents tracked in budget_counters
    cost_usd: float | None = None
    if budget_counters:
        total = 0.0
        for counters in budget_counters.values():
            if isinstance(counters, dict):
                v = counters.get("cost_usd", 0)
            elif hasattr(counters, "cost_usd"):
                v = counters.cost_usd
            else:
                v = 0
            with contextlib.suppress(TypeError, ValueError):
                total += float(v)
        cost_usd = total

    if tokens_in or tokens_out or cost_usd is not None:
        cost_str = f"${cost_usd:.4f}" if cost_usd is not None else "n/a"
        sections.append(f"\n*Used {tokens_in}/{tokens_out} tokens, {cost_str}.*")

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# LangGraph node entry point
# ---------------------------------------------------------------------------


async def run(state: AgentState, config: Any) -> dict:  # type: ignore[override]
    """LangGraph terminal node: build final_message and return state patch.

    If the supervisor already set a final_message (either via the explicit
    ``finalize`` tool call or the casual-chat fallback in the supervisor
    adapter), preserve it — don't overwrite with the synthetic summary that
    only describes structural state changes.
    """
    existing = state.get("final_message")
    if existing:
        return {}
    final_message = build_final_message(state)
    return {"final_message": final_message}
