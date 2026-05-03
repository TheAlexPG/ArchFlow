"""Tests for app/agents/builtin/general/nodes/finalize.py.

Covers:
- empty applied_changes, no forced_finalize → short "no changes" message
- happy path: 3 mixed actions → all rendered with archflow:// links
- 7 actions of the same type → collapsed to a count string
- forced_finalize='budget' → lead matches spec wording
- critique.issues present → "Warnings" section included
- pending_changes present → "Next steps" section included
- cost footnote rendered when tokens / budget_counters present
- archflow:// link schemes: object, connection, diagram
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from app.agents.builtin.general.nodes.finalize import (
    build_final_message,
    collapse_changes,
    render_action_line,
    run,
)
from app.agents.state import Critique

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state(**kwargs) -> dict:
    """Build a minimal AgentState-compatible dict."""
    defaults: dict = {
        "workspace_id": uuid4(),
        "session_id": uuid4(),
        "applied_changes": [],
        "pending_changes": [],
        "critique": None,
        "forced_finalize": None,
        "tokens_in": 0,
        "tokens_out": 0,
        "budget_counters": {},
    }
    defaults.update(kwargs)
    return defaults


def _change(
    *,
    action: str = "object.created",
    target_type: str = "object",
    name: str = "Foo",
    target_id: UUID | None = None,
    **extras,
) -> dict:
    return {
        "action": action,
        "target_type": target_type,
        "name": name,
        "target_id": target_id or uuid4(),
        **extras,
    }


# ---------------------------------------------------------------------------
# Case 1: empty applied_changes, no forced_finalize
# ---------------------------------------------------------------------------


def test_empty_applied_changes_returns_no_changes_message():
    state = _state(applied_changes=[])
    msg = build_final_message(state)
    assert "no changes" in msg.lower()


def test_findings_summary_used_when_no_changes_and_no_forced_finalize():
    """Read-only path: researcher produced Findings, no mutations were applied,
    supervisor didn't write a final reply (e.g. empty completions on local
    models). build_final_message must surface findings.summary instead of the
    placeholder "No changes were applied." — that placeholder is what was
    showing up in the chat for "explain this diagram" / "що в мене на діаграмі"
    questions."""
    from app.agents.state import Findings as FindingsModel

    summary = "На діаграмі **Base System**: Web app → API → Postgres."
    state = _state(
        applied_changes=[],
        findings=FindingsModel(summary=summary, details="", sources=[]),
    )
    msg = build_final_message(state)
    assert msg == summary


# ---------------------------------------------------------------------------
# Case 2: 3 mixed actions → rendered with archflow:// links
# ---------------------------------------------------------------------------


def test_three_mixed_actions_all_rendered():
    obj_id = uuid4()
    conn_id = uuid4()
    diag_id = uuid4()

    state = _state(
        applied_changes=[
            _change(
                action="object.created", target_type="object",
                name="Order Service", target_id=obj_id,
            ),
            _change(
                action="connection.created", target_type="connection",
                name="API → Postgres", target_id=conn_id,
            ),
            _change(
                action="diagram.created", target_type="diagram",
                name="Payment Components", target_id=diag_id,
            ),
        ]
    )
    msg = build_final_message(state)

    assert f"archflow://object/{obj_id}" in msg
    assert f"archflow://connection/{conn_id}" in msg
    assert f"archflow://diagram/{diag_id}" in msg
    assert "Order Service" in msg
    assert "API → Postgres" in msg
    assert "Payment Components" in msg


# ---------------------------------------------------------------------------
# Case 3: 7 actions same type → collapsed to count (no bullet list)
# ---------------------------------------------------------------------------


def test_seven_same_type_collapsed():
    state = _state(
        applied_changes=[
            _change(action="object.created", target_type="object", name=f"Svc{i}")
            for i in range(7)
        ]
    )
    msg = build_final_message(state)

    # The individual names should NOT appear (collapsed view)
    assert "Svc0" not in msg
    # The count should appear
    assert "7" in msg
    # Expect the word "object" in the collapsed summary
    assert "object" in msg.lower()


def test_collapse_changes_returns_count_string():
    changes = [_change(action="object.created", target_type="object") for _ in range(5)]
    result = collapse_changes(changes)
    assert "5" in result
    assert "object created" in result


def test_four_actions_not_collapsed():
    """Below the threshold (5), individual bullet lines are rendered."""
    state = _state(
        applied_changes=[
            _change(action="object.created", name=f"Item{i}") for i in range(4)
        ]
    )
    msg = build_final_message(state)
    assert "Item0" in msg
    assert "Item3" in msg


# ---------------------------------------------------------------------------
# Case 4: forced_finalize='budget' → lead matches spec
# ---------------------------------------------------------------------------


def test_budget_lead_line():
    state = _state(forced_finalize="budget", applied_changes=[])
    msg = build_final_message(state)
    assert "budget" in msg.lower()
    # Spec wording: "I ran out of budget"
    assert "ran out of budget" in msg.lower()


def test_turns_lead_line():
    state = _state(forced_finalize="turns", applied_changes=[])
    msg = build_final_message(state)
    assert "turn limit" in msg.lower()


def test_stuck_lead_line():
    state = _state(forced_finalize="stuck", applied_changes=[])
    msg = build_final_message(state)
    assert "looping" in msg.lower()


def test_cancelled_lead_line():
    state = _state(forced_finalize="cancelled", applied_changes=[])
    msg = build_final_message(state)
    assert "request" in msg.lower()


# ---------------------------------------------------------------------------
# Case 5: critique.issues → "Warnings" section present
# ---------------------------------------------------------------------------


def test_critique_issues_warnings_section():
    critique = Critique(
        verdict="APPROVE",
        strengths=["Good naming"],
        issues=["Missing security layer", "DB has no replica"],
    )
    state = _state(critique=critique)
    msg = build_final_message(state)

    assert "Warnings" in msg
    assert "Missing security layer" in msg
    assert "DB has no replica" in msg


def test_critique_no_issues_no_warnings_section():
    critique = Critique(verdict="APPROVE", strengths=["All good"], issues=[])
    state = _state(critique=critique)
    msg = build_final_message(state)
    assert "Warnings" not in msg


def test_critique_as_dict_issues_rendered():
    """critique stored as plain dict (state is TypedDict, dict form is valid)."""
    state = _state(critique={"verdict": "REVISE", "issues": ["Needs auth service"]})
    msg = build_final_message(state)
    assert "Warnings" in msg
    assert "Needs auth service" in msg


# ---------------------------------------------------------------------------
# Case 6: pending_changes → "Next steps" section present
# ---------------------------------------------------------------------------


def test_pending_changes_next_steps_section():
    state = _state(
        pending_changes=[
            {"action": "object.created", "name": "Cache Layer"},
            {"action": "connection.created", "name": "API → Cache"},
        ]
    )
    msg = build_final_message(state)
    assert "Next steps" in msg
    assert "2" in msg


def test_no_pending_changes_no_next_steps():
    state = _state(pending_changes=[])
    msg = build_final_message(state)
    assert "Next steps" not in msg


# ---------------------------------------------------------------------------
# Case 7: cost footnote rendered when tokens present
# ---------------------------------------------------------------------------


def test_cost_footnote_with_tokens():
    state = _state(tokens_in=1200, tokens_out=300)
    msg = build_final_message(state)
    assert "1200" in msg
    assert "300" in msg
    # Footnote should be italic (wrapped in *)
    assert "*" in msg


def test_cost_footnote_with_budget_counters():
    state = _state(
        tokens_in=500,
        tokens_out=100,
        budget_counters={
            "general": {"cost_usd": Decimal("0.0341")},
        },
    )
    msg = build_final_message(state)
    assert "0.0341" in msg
    assert "500" in msg


def test_no_cost_footnote_when_no_tokens():
    state = _state(tokens_in=0, tokens_out=0, budget_counters={})
    msg = build_final_message(state)
    # No "*Used … tokens" line
    assert "tokens" not in msg.lower() or "next steps" in msg.lower()
    # Make sure we didn't accidentally inject a footnote
    lines = msg.splitlines()
    assert not any(line.strip().startswith("*Used") for line in lines)


# ---------------------------------------------------------------------------
# Case 8: archflow:// link schemes are correct per target_type
# ---------------------------------------------------------------------------


def test_archflow_link_object():
    uid = uuid4()
    line = render_action_line(
        {"action": "object.created", "target_type": "object", "name": "Auth", "target_id": uid}
    )
    assert f"archflow://object/{uid}" in line


def test_archflow_link_connection():
    uid = uuid4()
    line = render_action_line(
        {
            "action": "connection.created", "target_type": "connection",
            "name": "A→B", "target_id": uid,
        }
    )
    assert f"archflow://connection/{uid}" in line


def test_archflow_link_diagram():
    uid = uuid4()
    line = render_action_line(
        {
            "action": "diagram.created", "target_type": "diagram",
            "name": "C4 Context", "target_id": uid,
        }
    )
    assert f"archflow://diagram/{uid}" in line


def test_archflow_link_deleted_object_uses_id():
    """Deleted objects still get archflow:// links — UI handles 404 gracefully."""
    uid = uuid4()
    line = render_action_line(
        {"action": "object.deleted", "target_type": "object", "name": "OldSvc", "target_id": uid}
    )
    assert f"archflow://object/{uid}" in line
    assert "OldSvc" in line


def test_render_updated_with_fields_changed():
    uid = uuid4()
    line = render_action_line(
        {
            "action": "object.updated",
            "target_type": "object",
            "name": "Payment Service",
            "target_id": uid,
            "fields_changed": "description, status",
        }
    )
    assert "description, status" in line
    assert f"archflow://object/{uid}" in line


# ---------------------------------------------------------------------------
# run() — LangGraph async node wrapper
# ---------------------------------------------------------------------------


async def test_run_returns_final_message_in_state_patch():
    state = _state(
        applied_changes=[_change(action="object.created", name="Svc")],
    )
    result = await run(state, config=None)
    assert "final_message" in result
    assert isinstance(result["final_message"], str)
    assert len(result["final_message"]) > 0


async def test_run_does_not_raise_on_empty_state():
    result = await run(_state(), config=MagicMock())
    assert "final_message" in result
