"""Tests for app/agents/runtime.py — AgentRuntime invoke + stream + helpers.

Design notes:
  * No real LangGraph / LiteLLM / Redis / Postgres calls.
  * Stub graphs honour the ``ainvoke(initial_state, config=...)`` contract so
    the runtime's fallback path drives them.
  * A FakeSession gives us in-memory storage for ``AgentChatSession`` +
    ``AgentChatMessage`` rows.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.agents import registry
from app.agents.errors import AgentError
from app.agents.registry import AgentDescriptor
from app.agents.runtime import (
    ActorRef,
    ChatContext,
    InvokeRequest,
    SSEEvent,
    _clamp_mode,
    _load_or_create_session,
    _resolve_active_draft_id,
    invoke,
    stream,
)
from app.models.agent_chat_message import AgentChatMessage
from app.models.agent_chat_session import AgentChatSession
from app.services.agent_settings_service import ResolvedAgentSettings

# ---------------------------------------------------------------------------
# Fake DB session
# ---------------------------------------------------------------------------


class FakeSession:
    """In-memory AsyncSession.  Stores AgentChatSession + AgentChatMessage rows."""

    def __init__(self) -> None:
        self.sessions: list[AgentChatSession] = []
        self.messages: list[AgentChatMessage] = []
        self.others: list[Any] = []

    def add(self, obj: Any) -> None:
        if isinstance(obj, AgentChatSession):
            self.sessions.append(obj)
        elif isinstance(obj, AgentChatMessage):
            self.messages.append(obj)
        else:
            self.others.append(obj)

    async def flush(self) -> None:
        return None

    async def execute(self, stmt):
        # Inspect the statement to figure out which entity is being queried.
        # The runtime uses simple ``select(Model).where(Model.col == val)`` so
        # we look at the first FROM table.
        try:
            entity = list(stmt.columns_clause_froms)[0].entity_zero.mapper.class_
        except Exception:
            entity = None

        rows: list[Any]
        if entity is AgentChatSession:
            rows = list(self.sessions)
        elif entity is AgentChatMessage:
            rows = list(self.messages)
        else:
            rows = []

        # Apply WHERE conditions — best effort. Look at the whereclause and
        # extract simple ``col == value`` expressions.
        wc = getattr(stmt, "whereclause", None)
        filters: dict = {}
        if wc is not None:
            _walk_where(wc, filters)
        rows = [r for r in rows if _row_matches(r, filters)]
        return _FakeResult(rows)


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        if not self._rows:
            return None
        return self._rows[0]


def _walk_where(clause, filters: dict) -> None:
    type_name = type(clause).__name__
    if type_name == "BinaryExpression":
        left = clause.left
        right = clause.right
        op_name = getattr(clause.operator, "__name__", str(clause.operator))
        col_name = getattr(left, "key", None) or getattr(left, "name", None)
        if col_name is None:
            return
        if op_name in ("eq", "_eq"):
            val = getattr(right, "value", None)
            filters[col_name] = val
        # Unhandled ops are ignored — tests don't exercise them.
    elif type_name in ("BooleanClauseList", "ClauseList"):
        for sub in clause.clauses:
            _walk_where(sub, filters)


def _row_matches(row: Any, filters: dict) -> bool:
    return all(getattr(row, col, None) == expected for col, expected in filters.items())


# ---------------------------------------------------------------------------
# Stub graph + descriptor
# ---------------------------------------------------------------------------


class _StubGraph:
    """Minimal compiled-graph stand-in.

    Honours either ``ainvoke(state, config=...)`` (preferred — runtime falls
    back to it when ``astream_events`` raises) or yields a single
    ``on_chain_end`` event via the fallback in ``_drive_graph``.
    """

    def __init__(self, returned_state: dict[str, Any]) -> None:
        self._returned_state = returned_state

    def get_graph(self):
        graph_obj = MagicMock()
        graph_obj.nodes = {"__start__": None, "__end__": None}
        return graph_obj

    async def ainvoke(self, state: dict, config: dict | None = None) -> dict:  # noqa: ARG002
        # Echo the input messages, then append the canned final state.
        out = dict(state)
        out.update(self._returned_state)
        return out


def _stub_descriptor(graph: Any) -> AgentDescriptor:
    return AgentDescriptor(
        id="stub-agent",
        name="Stub agent",
        description="for tests",
        graph=graph,
        surfaces=frozenset({"a2a"}),
        allowed_contexts=frozenset({"workspace"}),
        supported_modes=("full", "read_only"),
        required_scope="agents:invoke",
        tools_overview=(),
    )


@pytest.fixture(autouse=True)
def _patch_resolve_for_agent():
    """Stub out ``resolve_for_agent`` so we don't hit DB rows."""

    async def _fake(db, workspace_id: UUID, agent_id: str) -> ResolvedAgentSettings:  # noqa: ARG001
        return ResolvedAgentSettings(workspace_id=workspace_id, agent_id=agent_id)

    with patch(
        "app.agents.runtime.resolve_for_agent", side_effect=_fake
    ):
        yield


@pytest.fixture(autouse=True)
def _patch_rate_limit():
    """Stub out the rate-limit service to a no-op."""

    async def _fake(*args, **kwargs):  # noqa: ARG001
        return None

    with patch(
        "app.agents.runtime.check_and_consume", side_effect=_fake
    ):
        yield


@pytest.fixture(autouse=True)
def _clear_registry():
    """Snapshot + restore the registry across tests."""
    snapshot = list(registry.all_agents())
    registry.clear()
    yield
    registry.clear()
    for d in snapshot:
        registry.register(d)


# ---------------------------------------------------------------------------
# _clamp_mode
# ---------------------------------------------------------------------------


def test_clamp_mode_user_none_raises():
    actor = ActorRef(
        kind="user",
        id=uuid4(),
        workspace_id=uuid4(),
        agent_access="none",
    )
    with pytest.raises(PermissionError):
        _clamp_mode("full", actor)


def test_clamp_mode_user_read_only_clamps_full_to_read_only():
    actor = ActorRef(
        kind="user",
        id=uuid4(),
        workspace_id=uuid4(),
        agent_access="read_only",
    )
    assert _clamp_mode("full", actor) == "read_only"
    assert _clamp_mode("read_only", actor) == "read_only"


def test_clamp_mode_user_full_keeps_requested():
    actor = ActorRef(
        kind="user",
        id=uuid4(),
        workspace_id=uuid4(),
        agent_access="full",
    )
    assert _clamp_mode("full", actor) == "full"
    assert _clamp_mode("read_only", actor) == "read_only"


def test_clamp_mode_api_key_read_scope_clamps_full():
    actor = ActorRef(
        kind="api_key",
        id=uuid4(),
        workspace_id=uuid4(),
        scopes=("agents:read",),
    )
    assert _clamp_mode("full", actor) == "read_only"


def test_clamp_mode_api_key_write_scope_keeps_full():
    actor = ActorRef(
        kind="api_key",
        id=uuid4(),
        workspace_id=uuid4(),
        scopes=("agents:write",),
    )
    assert _clamp_mode("full", actor) == "full"


# ---------------------------------------------------------------------------
# _resolve_active_draft_id
# ---------------------------------------------------------------------------


async def test_resolve_active_draft_explicit_draft_wins():
    db = FakeSession()
    explicit = uuid4()
    actor = ActorRef(kind="user", id=uuid4(), workspace_id=uuid4(), agent_access="full")
    ctx = ChatContext(kind="diagram", id=uuid4(), draft_id=explicit)

    draft_id, choice = await _resolve_active_draft_id(
        db,
        chat_context=ctx,
        agent_edits_policy="ask",
        mode="full",
        actor=actor,
    )
    assert draft_id == explicit
    assert choice is None


async def test_resolve_active_draft_drafts_only_no_draft_returns_choice_payload():
    db = FakeSession()
    actor = ActorRef(kind="user", id=uuid4(), workspace_id=uuid4(), agent_access="full")
    ctx = ChatContext(kind="diagram", id=uuid4(), draft_id=None)

    draft_id, choice = await _resolve_active_draft_id(
        db,
        chat_context=ctx,
        agent_edits_policy="drafts_only",
        mode="full",
        actor=actor,
    )
    assert draft_id is None
    assert choice is not None
    assert choice["kind"] == "draft_required"
    assert isinstance(choice["options"], list)


async def test_resolve_active_draft_live_only_returns_none():
    db = FakeSession()
    actor = ActorRef(kind="user", id=uuid4(), workspace_id=uuid4(), agent_access="full")
    ctx = ChatContext(kind="diagram", id=uuid4(), draft_id=None)

    draft_id, choice = await _resolve_active_draft_id(
        db,
        chat_context=ctx,
        agent_edits_policy="live_only",
        mode="full",
        actor=actor,
    )
    assert draft_id is None
    assert choice is None


# ---------------------------------------------------------------------------
# _load_or_create_session
# ---------------------------------------------------------------------------


async def test_load_or_create_session_creates_new_when_no_session_id():
    db = FakeSession()
    actor = ActorRef(kind="user", id=uuid4(), workspace_id=uuid4(), agent_access="full")
    req = InvokeRequest(
        agent_id="stub-agent",
        actor=actor,
        workspace_id=actor.workspace_id,
        chat_context=ChatContext(kind="workspace", id=actor.workspace_id),
        message="hi",
        session_id=None,
    )
    session = await _load_or_create_session(db, req=req)
    assert isinstance(session, AgentChatSession)
    assert session.actor_user_id == actor.id
    assert session.workspace_id == actor.workspace_id
    assert session.agent_id == "stub-agent"
    assert len(db.sessions) == 1


async def test_load_or_create_session_rejects_session_owned_by_other_actor():
    db = FakeSession()
    other_user = uuid4()
    workspace_id = uuid4()
    existing = AgentChatSession(
        id=uuid4(),
        workspace_id=workspace_id,
        agent_id="stub-agent",
        actor_user_id=other_user,
        actor_api_key_id=None,
        context_kind="workspace",
        compaction_stage=0,
        cancel_requested=False,
    )
    db.add(existing)

    actor = ActorRef(
        kind="user",
        id=uuid4(),
        workspace_id=workspace_id,
        agent_access="full",
    )
    req = InvokeRequest(
        agent_id="stub-agent",
        actor=actor,
        workspace_id=workspace_id,
        chat_context=ChatContext(kind="workspace", id=workspace_id),
        message="hi",
        session_id=existing.id,
    )
    with pytest.raises(PermissionError):
        await _load_or_create_session(db, req=req)


# ---------------------------------------------------------------------------
# invoke smoke tests
# ---------------------------------------------------------------------------


async def test_invoke_unknown_agent_raises_agent_error():
    db = FakeSession()
    actor = ActorRef(kind="user", id=uuid4(), workspace_id=uuid4(), agent_access="full")
    req = InvokeRequest(
        agent_id="does-not-exist",
        actor=actor,
        workspace_id=actor.workspace_id,
        chat_context=ChatContext(kind="workspace", id=actor.workspace_id),
        message="hi",
    )
    with pytest.raises(AgentError):
        await invoke(req, db=db)


async def test_invoke_returns_result_with_final_message_from_stub_graph():
    db = FakeSession()
    actor = ActorRef(kind="user", id=uuid4(), workspace_id=uuid4(), agent_access="full")
    graph = _StubGraph(
        returned_state={
            "final_message": "hi",
            "applied_changes": [],
            "tokens_in": 5,
            "tokens_out": 3,
        }
    )
    registry.register(_stub_descriptor(graph))

    req = InvokeRequest(
        agent_id="stub-agent",
        actor=actor,
        workspace_id=actor.workspace_id,
        chat_context=ChatContext(kind="workspace", id=actor.workspace_id),
        message="hello",
    )
    result = await invoke(req, db=db)

    assert result.final_message == "hi"
    assert result.agent_id == "stub-agent"
    assert isinstance(result.session_id, UUID)
    assert result.applied_changes == []
    assert result.tokens_in == 5
    assert result.tokens_out == 3


async def test_invoke_emits_applied_change_events_for_each_record():
    db = FakeSession()
    actor = ActorRef(kind="user", id=uuid4(), workspace_id=uuid4(), agent_access="full")
    graph = _StubGraph(
        returned_state={
            "final_message": "ok",
            "applied_changes": [
                {"action": "create_object", "target_id": str(uuid4()), "name": "Postgres"},
                {"action": "place_on_diagram", "target_id": str(uuid4()), "name": "Postgres"},
            ],
            "tokens_in": 1,
            "tokens_out": 1,
        }
    )
    registry.register(_stub_descriptor(graph))

    req = InvokeRequest(
        agent_id="stub-agent",
        actor=actor,
        workspace_id=actor.workspace_id,
        chat_context=ChatContext(kind="workspace", id=actor.workspace_id),
        message="add postgres",
    )
    result = await invoke(req, db=db)
    assert len(result.applied_changes) == 2


# ---------------------------------------------------------------------------
# stream smoke
# ---------------------------------------------------------------------------


async def test_stream_yields_session_first_and_done_last():
    db = FakeSession()
    actor = ActorRef(kind="user", id=uuid4(), workspace_id=uuid4(), agent_access="full")
    graph = _StubGraph(
        returned_state={"final_message": "bye", "applied_changes": []}
    )
    registry.register(_stub_descriptor(graph))

    req = InvokeRequest(
        agent_id="stub-agent",
        actor=actor,
        workspace_id=actor.workspace_id,
        chat_context=ChatContext(kind="workspace", id=actor.workspace_id),
        message="hi",
    )

    events: list[SSEEvent] = []
    async for ev in stream(req, db=db):
        events.append(ev)

    assert events, "stream produced no events"
    assert events[0].kind == "session"
    assert events[-1].kind == "done"

    kinds = [e.kind for e in events]
    assert "message" in kinds
    assert "usage" in kinds


async def test_stream_usage_event_carries_state_token_totals():
    """Stub graphs that pre-populate ``state['tokens_in/out']`` (the historic
    contract for unit tests) must still surface non-zero totals on the wire.
    Real runs source totals from ``RuntimeCounters`` — see test_limits.py
    ``test_acompletion_aggregates_tokens_across_calls`` for the live path."""
    db = FakeSession()
    actor = ActorRef(kind="user", id=uuid4(), workspace_id=uuid4(), agent_access="full")
    graph = _StubGraph(
        returned_state={
            "final_message": "done",
            "applied_changes": [],
            "tokens_in": 312,
            "tokens_out": 87,
        }
    )
    registry.register(_stub_descriptor(graph))

    req = InvokeRequest(
        agent_id="stub-agent",
        actor=actor,
        workspace_id=actor.workspace_id,
        chat_context=ChatContext(kind="workspace", id=actor.workspace_id),
        message="hi",
    )

    usage_events = [ev async for ev in stream(req, db=db) if ev.kind == "usage"]
    assert len(usage_events) == 1
    payload = usage_events[0].payload
    assert payload["tokens_in"] == 312
    assert payload["tokens_out"] == 87
    # Field names the frontend reads: tokens_in / tokens_out (not
    # prompt_tokens / completion_tokens).
    assert "prompt_tokens" not in payload
    assert "completion_tokens" not in payload


class _StubGraphWithCustomEvents:
    """Compiled-graph stub that exposes ``astream_events`` and yields a few
    pre-canned events — including the ``on_custom_event`` frames our
    ``_drain_with_tracing`` helper dispatches when a node calls
    ``adispatch_custom_event``. Lets us pin the runtime's mapping from
    ``agent_tool_call`` / ``agent_tool_result`` custom events onto the SSE
    wire without spinning up the real LangGraph + LLM stack.
    """

    def __init__(self, returned_state: dict[str, Any], events: list[dict]) -> None:
        self._returned_state = returned_state
        self._events = events

    def get_graph(self):
        graph_obj = MagicMock()
        graph_obj.nodes = {"__start__": None, "__end__": None, "supervisor": None}
        return graph_obj

    async def astream_events(self, state: dict, version: str = "v2", config=None):  # noqa: ARG002
        for ev in self._events:
            yield ev


async def test_stream_maps_custom_events_to_tool_call_and_tool_result():
    """A node that dispatches ``agent_tool_call`` / ``agent_tool_result``
    custom events should surface them to the SSE consumer as ``tool_call``
    and ``tool_result`` frames with the exact field names the frontend
    expects (id / name / args  -+-  id / status / preview / content)."""
    db = FakeSession()
    actor = ActorRef(kind="user", id=uuid4(), workspace_id=uuid4(), agent_access="full")

    # Pre-canned event tape mirroring what _drain_with_tracing emits inside a
    # real run: chain_start (supervisor) → custom tool_call → custom tool_result
    # → chain_end with the final state.
    canned_events: list[dict] = [
        {
            "event": "on_chain_start",
            "name": "supervisor",
            "data": {},
        },
        {
            "event": "on_custom_event",
            "name": "agent_tool_call",
            "data": {
                "id": "call_42",
                "name": "read_diagram",
                "args": {"diagram_id": "abc"},
                "agent": "supervisor",
            },
        },
        {
            "event": "on_custom_event",
            "name": "agent_tool_result",
            "data": {
                "id": "call_42",
                "status": "ok",
                "preview": "1 placement",
                "content": '{"placements": []}',
                "agent": "supervisor",
            },
        },
        {
            "event": "on_chain_end",
            "name": "__graph__",
            "data": {"output": {"final_message": "done", "applied_changes": []}},
        },
    ]

    graph = _StubGraphWithCustomEvents(
        returned_state={"final_message": "done", "applied_changes": []},
        events=canned_events,
    )
    registry.register(_stub_descriptor(graph))

    req = InvokeRequest(
        agent_id="stub-agent",
        actor=actor,
        workspace_id=actor.workspace_id,
        chat_context=ChatContext(kind="workspace", id=actor.workspace_id),
        message="check the diagram",
    )

    events: list[SSEEvent] = []
    async for ev in stream(req, db=db):
        events.append(ev)

    kinds = [e.kind for e in events]
    assert "tool_call" in kinds, f"expected tool_call SSE event, got {kinds}"
    assert "tool_result" in kinds, f"expected tool_result SSE event, got {kinds}"

    tc = next(e for e in events if e.kind == "tool_call")
    assert tc.payload["id"] == "call_42"
    assert tc.payload["name"] == "read_diagram"
    # Frontend's build-render-items.ts reads payload.args (not payload.arguments).
    assert tc.payload["args"] == {"diagram_id": "abc"}
    assert tc.payload["agent"] == "supervisor"

    tr = next(e for e in events if e.kind == "tool_result")
    assert tr.payload["id"] == "call_42"
    assert tr.payload["status"] == "ok"
    assert tr.payload["preview"] == "1 placement"
    # ChatHistory.tsx reads result?.result ?? result?.content.
    assert tr.payload["content"] == '{"placements": []}'

    # Order: tool_call must precede its matching tool_result so the frontend
    # pairs them correctly.
    tc_idx = kinds.index("tool_call")
    tr_idx = kinds.index("tool_result")
    assert tc_idx < tr_idx


async def test_stream_emits_error_event_for_unknown_agent():
    db = FakeSession()
    actor = ActorRef(kind="user", id=uuid4(), workspace_id=uuid4(), agent_access="full")
    req = InvokeRequest(
        agent_id="missing-agent",
        actor=actor,
        workspace_id=actor.workspace_id,
        chat_context=ChatContext(kind="workspace", id=actor.workspace_id),
        message="hi",
    )

    events: list[SSEEvent] = []
    async for ev in stream(req, db=db):
        events.append(ev)

    kinds = [e.kind for e in events]
    assert "error" in kinds
    err = next(e for e in events if e.kind == "error")
    assert err.payload["code"] == "agent_not_found"
    assert kinds[0] == "session"
    assert kinds[-1] == "done"
