"""Tests for app/agents/builtin/general/nodes/diagram.py.

Mirrors the test pattern in tests/agents/test_run_react.py: stubbed
LimitsEnforcer + ContextManager + tool_executor; no real LLM, no DB.

Coverage:
- DIAGRAM_TOOLS exposes both READ and WRITE categories.
- DIAGRAM_TOOLS does NOT include reasoning tools (delegate_*, write_scratchpad,
  read_scratchpad, finalize).
- DIAGRAM_TOOLS includes drafts tools (fork_diagram_to_draft, list_active_drafts).
- render_pending_changes_block: empty plan vs. plan with mixed done/pending.
- render_active_diagram_block: diagram context + draft, object context, no context.
- make_diagram_config: max_steps=10, output_schema=None, two system blocks.
- run() success path: 3 successful tool calls → applied_changes contains 3 entries.
- run() with one tool error in the middle → assistant message reflects, no crash.
- run() reaches max_steps cleanly with 5+ tool calls.
- load_diagram_prompt() pulls non-empty markdown.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.agents.builtin.general.nodes.diagram import (
    DIAGRAM_TOOLS,
    load_diagram_prompt,
    make_diagram_config,
    render_active_diagram_block,
    render_pending_changes_block,
    run,
)
from app.agents.context_manager import CompactionResult
from app.agents.llm import LLMCallMetadata, LLMResult
from app.agents.nodes.base import NodeStreamEvent
from app.agents.state import Plan, PlanStep

# ---------------------------------------------------------------------------
# Helpers (mirroring tests/agents/test_run_react.py)
# ---------------------------------------------------------------------------


def _tool_names() -> set[str]:
    return {t["function"]["name"] for t in DIAGRAM_TOOLS}


def _tool_descriptions() -> dict[str, str]:
    return {t["function"]["name"]: t["function"]["description"] for t in DIAGRAM_TOOLS}


def _make_call_meta() -> LLMCallMetadata:
    return LLMCallMetadata(
        workspace_id=uuid4(),
        agent_id="general",
        session_id=uuid4(),
        actor_id=uuid4(),
        analytics_consent="off",
    )


def _llm_result(
    *,
    text: str | None = "ok",
    tool_calls: list[dict] | None = None,
) -> LLMResult:
    return LLMResult(
        text=text,
        tool_calls=tool_calls,
        finish_reason="stop",
        tokens_in=10,
        tokens_out=10,
        cost_usd=Decimal("0.001"),
        raw=MagicMock(),
    )


def _make_enforcer(*, results: list[LLMResult]) -> MagicMock:
    enforcer = MagicMock()
    enforcer.llm = MagicMock()
    enforcer.llm.model = "openai/gpt-4o-mini"
    enforcer.limits = MagicMock()
    enforcer.limits.budget_scope = "per_invocation"
    enforcer.acompletion = AsyncMock(side_effect=results)
    enforcer.consume_budget_warning = MagicMock(return_value=None)
    return enforcer


def _make_context_manager() -> MagicMock:
    cm = MagicMock()

    async def _maybe_compact(messages, **kwargs):
        return CompactionResult(
            compacted_messages=messages,
            stage_applied=0,
            strategy_name=None,
            tokens_before=100,
            tokens_after=100,
        )

    cm.maybe_compact = AsyncMock(side_effect=_maybe_compact)
    return cm


def _make_tool_executor(
    results: list[dict] | None = None,
) -> Callable[[dict, dict], Awaitable[dict]]:
    queue = list(results or [])

    async def _executor(tool_call: dict, state: dict) -> dict:
        if queue:
            return queue.pop(0)
        return {
            "tool_call_id": tool_call.get("id") or "",
            "status": "ok",
            "content": "{}",
            "preview": "ok",
        }

    return _executor


def _make_state(
    *,
    messages: list[dict] | None = None,
    plan: Plan | None = None,
    chat_context: dict | None = None,
    active_draft_id: UUID | None = None,
    applied_changes: list[dict] | None = None,
) -> dict:
    return {
        "workspace_id": uuid4(),
        "session_id": uuid4(),
        "messages": list(messages or []),
        "iteration": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "plan": plan,
        "chat_context": chat_context or {},
        "active_draft_id": active_draft_id,
        "applied_changes": list(applied_changes or []),
    }


async def _collect(gen) -> list[NodeStreamEvent]:
    return [ev async for ev in gen]


def _terminal_output(events: list[NodeStreamEvent]):
    finished = [ev for ev in events if ev.kind == "finished"]
    assert len(finished) == 1, f"expected exactly one 'finished' event, got {len(finished)}"
    return finished[0].payload["output"]


# ---------------------------------------------------------------------------
# DIAGRAM_TOOLS shape
# ---------------------------------------------------------------------------


def test_diagram_tools_includes_read_and_write_categories():
    """READ + WRITE mix — verify per spec §3.3 'full read+write set'."""
    descriptions = _tool_descriptions()

    read_tools = [name for name, desc in descriptions.items() if desc.startswith("[READ]")]
    write_tools = [name for name, desc in descriptions.items() if desc.startswith("[WRITE]")]

    assert len(read_tools) >= 5, f"expected >= 5 READ tools, got {read_tools}"
    assert len(write_tools) >= 8, f"expected >= 8 WRITE tools, got {write_tools}"

    # Spot-check the canonical set per spec §4.3 / §4.5.
    names = _tool_names()
    for required in (
        "read_object",
        "read_diagram",
        "read_canvas_state",
        "search_existing_objects",
        "create_object",
        "create_connection",
        "place_on_diagram",
        "create_diagram",
        "auto_layout_diagram",
    ):
        assert required in names, f"missing required tool {required!r}"


def test_diagram_tools_excludes_reasoning_tools():
    """Reasoning + delegation belong to supervisor only (spec §3.3 / §4.6)."""
    names = _tool_names()
    forbidden = {
        "delegate_to_planner",
        "delegate_to_diagram",
        "delegate_to_researcher",
        "delegate_to_critic",
        "write_scratchpad",
        "read_scratchpad",
        "finalize",
    }
    leaked = forbidden & names
    assert not leaked, f"reasoning tools must not appear in DIAGRAM_TOOLS: {leaked}"


def test_diagram_tools_includes_drafts_tools():
    """Per spec §4.5 — diagram-agent can fork drafts and list them, but not discard."""
    names = _tool_names()
    assert "fork_diagram_to_draft" in names
    assert "list_active_drafts" in names
    # Discard is NOT a planned diagram-agent tool — it's destructive and routed
    # via supervisor / explicit user UI.
    assert "discard_draft" not in names


def test_diagram_tools_have_openai_function_shape():
    """Every entry must conform to {type:'function', function:{name, description, parameters}}."""
    for entry in DIAGRAM_TOOLS:
        assert entry["type"] == "function"
        fn = entry["function"]
        assert isinstance(fn["name"], str) and fn["name"]
        assert isinstance(fn["description"], str) and fn["description"]
        params = fn["parameters"]
        assert params["type"] == "object"
        assert "properties" in params


# ---------------------------------------------------------------------------
# render_pending_changes_block
# ---------------------------------------------------------------------------


def test_render_pending_changes_empty_plan_returns_empty_string():
    """No plan → empty string (compose_messages_for_llm drops empty blocks)."""
    state = _make_state(plan=None)
    out = render_pending_changes_block(state)
    assert out == ""


def test_render_pending_changes_plan_with_mixed_done_and_pending():
    plan = Plan(
        goal="Add Postgres + connect API",
        steps=[
            PlanStep(
                index=0,
                kind="create_object",
                args={"name": "Postgres", "type": "store"},
                depends_on=[],
                rationale="user asked for a DB",
            ),
            PlanStep(
                index=1,
                kind="create_connection",
                args={"label": "reads"},
                depends_on=[0],
                rationale="API needs DB access",
            ),
        ],
        reuse_findings=[],
    )
    applied = [
        {
            "action": "object.created",
            "target_type": "object",
            "target_id": str(uuid4()),
            "name": "Postgres",
        },
    ]
    state = _make_state(plan=plan, applied_changes=applied)
    block = render_pending_changes_block(state)

    assert "## Plan" in block
    assert "Add Postgres + connect API" in block
    # Topo order: step 0 first, step 1 second (depends_on=[0]).
    pos_step0 = block.find("create_object")
    pos_step1 = block.find("create_connection")
    assert 0 <= pos_step0 < pos_step1, "topological order broken"
    # Step 0 done, step 1 pending.
    assert "✓" in block
    assert "⏳" in block
    # Sanity: the done marker appears on the create_object line.
    create_object_line = next(
        ln for ln in block.splitlines() if "create_object" in ln
    )
    assert "✓" in create_object_line
    create_conn_line = next(
        ln for ln in block.splitlines() if "create_connection" in ln
    )
    assert "⏳" in create_conn_line


def test_render_pending_changes_plan_with_no_steps_says_so():
    """When the plan dict carries an empty steps list (e.g. constructed
    bypassing schema validation by the runtime), the renderer must still
    produce a sensible block rather than crash. The schema enforces
    min_length=1 in normal flow; here we exercise the dict fallback path.
    """
    plan_dict = {"goal": "Empty plan", "steps": [], "reuse_findings": []}
    state = _make_state(plan=plan_dict)
    block = render_pending_changes_block(state)
    assert "## Plan" in block
    assert "no plan" in block.lower()


# ---------------------------------------------------------------------------
# render_active_diagram_block
# ---------------------------------------------------------------------------


def test_render_active_diagram_block_diagram_kind():
    diag_id = uuid4()
    state = _make_state(chat_context={"kind": "diagram", "id": diag_id})
    block = render_active_diagram_block(state)
    assert "## Active context" in block
    assert "Working on diagram" in block
    assert str(diag_id) in block
    # No draft mentioned when there isn't one.
    assert "draft" not in block.lower() or "do not" in block.lower()


def test_render_active_diagram_block_with_active_draft():
    diag_id = uuid4()
    draft_id = uuid4()
    state = _make_state(
        chat_context={"kind": "diagram", "id": diag_id},
        active_draft_id=draft_id,
    )
    block = render_active_diagram_block(state)
    assert "Working on diagram" in block
    assert str(diag_id) in block
    assert f"via draft {draft_id}" in block
    # Auto-route hint must appear so the LLM doesn't pass draft_id explicitly.
    assert "auto-route" in block.lower()


def test_render_active_diagram_block_object_context_no_diagram_pinned():
    obj_id = uuid4()
    state = _make_state(chat_context={"kind": "object", "id": obj_id})
    block = render_active_diagram_block(state)
    assert "Working on object" in block
    assert str(obj_id) in block


def test_render_active_diagram_block_no_chat_context():
    state = _make_state(chat_context={})
    block = render_active_diagram_block(state)
    assert "No diagram context" in block


# ---------------------------------------------------------------------------
# make_diagram_config
# ---------------------------------------------------------------------------


def test_make_diagram_config_shape():
    executor = _make_tool_executor()
    cfg = make_diagram_config(executor)

    assert cfg.name == "diagram"
    assert cfg.max_steps == 200
    assert cfg.output_schema is None
    assert cfg.tools is DIAGRAM_TOOLS
    assert cfg.tool_executor is executor
    assert cfg.system_prompt  # non-empty
    # Both system blocks attached.
    assert len(cfg.additional_system_blocks) == 2
    block_names = [b.__name__ for b in cfg.additional_system_blocks]
    assert "render_pending_changes_block" in block_names
    assert "render_active_diagram_block" in block_names


def test_load_diagram_prompt_returns_real_content():
    text = load_diagram_prompt()
    assert isinstance(text, str)
    # Sanity: the prompt body must include the IcePanel rules header so a
    # truncated / placeholder file fails the test.
    assert "Diagram-Agent" in text
    assert "search_existing_objects" in text
    assert "place_on_diagram" in text
    # Hierarchy rule must be present.
    assert "component" in text.lower()


# ---------------------------------------------------------------------------
# run() — happy path: 3 successful tool calls then terminal text
# ---------------------------------------------------------------------------


def _tool_call(name: str, args: dict, *, call_id: str = "call_x") -> dict:
    return {"id": call_id, "name": name, "arguments": json.dumps(args)}


@pytest.mark.asyncio
async def test_run_three_successful_tool_calls_accumulates_applied_changes():
    obj_id = str(uuid4())
    diag_id = str(uuid4())
    conn_id = str(uuid4())

    create_call = _tool_call(
        "create_object", {"name": "Postgres", "type": "store"}, call_id="c1"
    )
    place_call = _tool_call(
        "place_on_diagram",
        {"diagram_id": diag_id, "object_id": obj_id},
        call_id="c2",
    )
    connect_call = _tool_call(
        "create_connection",
        {"source_object_id": obj_id, "target_object_id": obj_id},
        call_id="c3",
    )
    enforcer = _make_enforcer(
        results=[
            _llm_result(text=None, tool_calls=[create_call]),
            _llm_result(text=None, tool_calls=[place_call]),
            _llm_result(text=None, tool_calls=[connect_call]),
            _llm_result(
                text="Done. Created Postgres + placement + connection.",
                tool_calls=None,
            ),
        ]
    )
    cm = _make_context_manager()
    executor = _make_tool_executor(
        results=[
            {
                "tool_call_id": "c1",
                "status": "ok",
                "content": json.dumps({
                    "ok": True,
                    "action": "object.created",
                    "target_type": "object",
                    "target_id": obj_id,
                    "name": "Postgres",
                }),
                "preview": "created Postgres",
            },
            {
                "tool_call_id": "c2",
                "status": "ok",
                "content": json.dumps({
                    "ok": True,
                    "action": "diagram.placed",
                    "target_type": "object",
                    "target_id": obj_id,
                    "diagram_id": diag_id,
                    "name": "Postgres",
                }),
                "preview": "placed",
            },
            {
                "tool_call_id": "c3",
                "status": "ok",
                "content": json.dumps({
                    "ok": True,
                    "action": "connection.created",
                    "target_type": "connection",
                    "target_id": conn_id,
                    "name": "Postgres → Postgres",
                }),
                "preview": "connected",
            },
        ]
    )

    state = _make_state(
        messages=[{"role": "user", "content": "Add Postgres + connect."}],
        chat_context={"kind": "diagram", "id": uuid4()},
    )

    events = await _collect(
        run(
            state,
            enforcer=enforcer,
            context_manager=cm,
            tool_executor=executor,
            call_metadata_base=_make_call_meta(),
        )
    )

    output = _terminal_output(events)
    assert output.forced_finalize is None
    assert output.text and "Done" in output.text
    assert output.tool_calls_made == 3

    applied = output.state_patch.get("applied_changes")
    assert isinstance(applied, list)
    assert len(applied) == 3
    actions = [c["action"] for c in applied]
    assert actions == ["object.created", "diagram.placed", "connection.created"]
    # target_id passes through as-is from the tool result.
    assert applied[0]["target_id"] == obj_id
    assert applied[2]["target_id"] == conn_id


@pytest.mark.asyncio
async def test_run_preserves_pre_existing_applied_changes():
    """run() must merge — not overwrite — incoming applied_changes."""
    pre_existing = [
        {
            "action": "object.created",
            "target_type": "object",
            "target_id": str(uuid4()),
            "name": "Old",
        },
    ]
    new_id = str(uuid4())
    create_call = _tool_call(
        "create_object", {"name": "New", "type": "app"}, call_id="cc1"
    )
    enforcer = _make_enforcer(
        results=[
            _llm_result(text=None, tool_calls=[create_call]),
            _llm_result(text="ok", tool_calls=None),
        ]
    )
    cm = _make_context_manager()
    executor = _make_tool_executor(
        results=[
            {
                "tool_call_id": "cc1",
                "status": "ok",
                "content": json.dumps({
                    "ok": True,
                    "action": "object.created",
                    "target_type": "object",
                    "target_id": new_id,
                    "name": "New",
                }),
                "preview": "created",
            }
        ]
    )

    state = _make_state(
        applied_changes=pre_existing,
        messages=[{"role": "user", "content": "another"}],
    )

    events = await _collect(
        run(
            state,
            enforcer=enforcer,
            context_manager=cm,
            tool_executor=executor,
            call_metadata_base=_make_call_meta(),
        )
    )

    output = _terminal_output(events)
    applied = output.state_patch["applied_changes"]
    assert len(applied) == 2
    assert applied[0]["name"] == "Old"
    assert applied[1]["name"] == "New"


@pytest.mark.asyncio
async def test_run_marks_plan_steps_done_in_state_patch():
    plan = Plan(
        goal="Add DB",
        steps=[
            PlanStep(
                index=0,
                kind="create_object",
                args={"name": "Postgres", "type": "store"},
                depends_on=[],
                rationale="DB",
            ),
        ],
        reuse_findings=[],
    )
    obj_id = str(uuid4())
    create_call = _tool_call(
        "create_object", {"name": "Postgres", "type": "store"}, call_id="p1"
    )
    enforcer = _make_enforcer(
        results=[
            _llm_result(text=None, tool_calls=[create_call]),
            _llm_result(text="done", tool_calls=None),
        ]
    )
    cm = _make_context_manager()
    executor = _make_tool_executor(
        results=[
            {
                "tool_call_id": "p1",
                "status": "ok",
                "content": json.dumps({
                    "ok": True,
                    "action": "object.created",
                    "target_type": "object",
                    "target_id": obj_id,
                    "name": "Postgres",
                }),
                "preview": "created",
            }
        ]
    )
    state = _make_state(plan=plan, messages=[{"role": "user", "content": "go"}])

    events = await _collect(
        run(
            state,
            enforcer=enforcer,
            context_manager=cm,
            tool_executor=executor,
            call_metadata_base=_make_call_meta(),
        )
    )

    output = _terminal_output(events)
    assert output.state_patch.get("plan_steps_done") == [0]


# ---------------------------------------------------------------------------
# Error path: tool returns error, loop continues, no crash.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_tool_error_does_not_crash_assistant_continues():
    create_call = _tool_call(
        "create_object", {"name": "X", "type": "app"}, call_id="err1"
    )
    enforcer = _make_enforcer(
        results=[
            _llm_result(text=None, tool_calls=[create_call]),
            _llm_result(
                text="Couldn't create X — permission denied. Skipping.",
                tool_calls=None,
            ),
        ]
    )
    cm = _make_context_manager()
    executor = _make_tool_executor(
        results=[
            {
                "tool_call_id": "err1",
                "status": "error",
                "content": json.dumps({
                    "ok": False,
                    "error": "permission_denied",
                    "code": "ACL",
                }),
                "preview": "denied",
            }
        ]
    )
    state = _make_state(messages=[{"role": "user", "content": "try"}])

    events = await _collect(
        run(
            state,
            enforcer=enforcer,
            context_manager=cm,
            tool_executor=executor,
            call_metadata_base=_make_call_meta(),
        )
    )

    output = _terminal_output(events)
    assert output.forced_finalize is None
    assert output.text is not None
    assert "permission denied" in output.text.lower()
    # Failed tool result must NOT show up in applied_changes.
    applied = output.state_patch.get("applied_changes") or []
    assert applied == []
    # The tool_result event was still emitted with status=error.
    statuses = [ev.payload["status"] for ev in events if ev.kind == "tool_result"]
    assert statuses == ["error"]


# ---------------------------------------------------------------------------
# Long path: 5+ tool calls — must hit max_steps cleanly.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_long_path_reaches_max_steps_cleanly(monkeypatch):
    """Every step asks for a tool — never terminal → max_steps trips.

    The diagram node ships with a generous ``max_steps=200`` so the workspace
    budget — not this counter — is the real cost guard. Re-running the loop
    test against 200 iterations would be slow and brittle; we instead patch
    the config to a small ceiling and verify run_react still terminates
    cleanly with ``forced_finalize='max_steps'``.
    """
    from app.agents.builtin.general.nodes import diagram as diagram_node

    real_make = diagram_node.make_diagram_config

    def small_ceiling_config(*args, **kwargs):
        cfg = real_make(*args, **kwargs)
        # Replace the dataclass with a small max_steps via dataclasses.replace.
        from dataclasses import replace as _replace

        return _replace(cfg, max_steps=10)

    monkeypatch.setattr(
        diagram_node, "make_diagram_config", small_ceiling_config
    )

    # Vary diagram_id per step so the tool-loop detector (4 identical calls
    # in a row → forced_finalize="stuck") doesn't fire — this test exercises
    # the max_steps ceiling, not the cycle break.
    forever_calls = [
        {
            "id": f"loop-{i}",
            "name": "read_diagram",
            "arguments": json.dumps({"diagram_id": str(uuid4())}),
        }
        for i in range(12)
    ]
    # 12 successive tool-call results — patched max_steps=10 traps the loop.
    results = [_llm_result(text=None, tool_calls=[fc]) for fc in forever_calls]
    enforcer = _make_enforcer(results=results)
    cm = _make_context_manager()

    executor = _make_tool_executor(
        results=[
            {
                "tool_call_id": fc["id"],
                "status": "ok",
                "content": json.dumps({"ok": True, "echo": True}),
                "preview": "ok",
            }
            for fc in forever_calls
        ]
    )

    state = _make_state(messages=[{"role": "user", "content": "loop"}])

    events = await _collect(
        run(
            state,
            enforcer=enforcer,
            context_manager=cm,
            tool_executor=executor,
            call_metadata_base=_make_call_meta(),
        )
    )

    output = _terminal_output(events)
    assert output.forced_finalize == "max_steps"
    # Patched max_steps=10 → exactly 10 tool calls executed.
    assert output.tool_calls_made == 10
    # Read-only tool results carry no canonical 'action' → no applied_changes.
    assert output.state_patch.get("applied_changes", []) == []

    # forced_finalize event must precede the finished event.
    kinds = [ev.kind for ev in events]
    assert "forced_finalize" in kinds
    assert kinds[-1] == "finished"


@pytest.mark.asyncio
async def test_run_breaks_out_of_identical_tool_call_cycle(monkeypatch):
    """Same (name, args) repeated 4× → forced_finalize='stuck'.

    Trace d885971d showed delete_object retried 6× with identical incomplete
    args; without a cycle detector the agent burns the entire max_steps
    ceiling on a non-progressing loop. The detector should fire on the
    fourth identical call and surface ``forced_finalize='stuck'`` with a
    tool-loop detail.
    """
    from app.agents.builtin.general.nodes import diagram as diagram_node

    real_make = diagram_node.make_diagram_config

    def small_ceiling_config(*args, **kwargs):
        cfg = real_make(*args, **kwargs)
        from dataclasses import replace as _replace

        return _replace(cfg, max_steps=10)

    monkeypatch.setattr(diagram_node, "make_diagram_config", small_ceiling_config)

    fixed_args = json.dumps({"diagram_id": str(uuid4())})
    same_call = {"id": "same", "name": "read_diagram", "arguments": fixed_args}
    results = [_llm_result(text=None, tool_calls=[same_call]) for _ in range(8)]
    enforcer = _make_enforcer(results=results)
    cm = _make_context_manager()

    executor = _make_tool_executor(
        results=[
            {
                "tool_call_id": "same",
                "status": "ok",
                "content": json.dumps({"ok": True}),
                "preview": "ok",
            }
            for _ in range(8)
        ]
    )

    state = _make_state(messages=[{"role": "user", "content": "loop"}])

    events = await _collect(
        run(
            state,
            enforcer=enforcer,
            context_manager=cm,
            tool_executor=executor,
            call_metadata_base=_make_call_meta(),
        )
    )

    output = _terminal_output(events)
    assert output.forced_finalize == "stuck"
    assert output.tool_calls_made == 4

    forced = [ev for ev in events if ev.kind == "forced_finalize"]
    assert forced and forced[0].payload.get("reason") == "stuck"
    assert "tool-loop" in (forced[0].payload.get("detail") or "")
