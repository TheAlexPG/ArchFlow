"""Tests for /api/v1/agents/sessions/* (task agent-core-mvp-037).

Pattern mirrors :mod:`tests.api.test_agents_discovery`:
  * Dependency overrides for ``get_db`` + ``get_current_user``.
  * In-memory ``FakeSession`` storing :class:`AgentChatSession` +
    :class:`AgentChatMessage` rows.
  * ``fakeredis.aioredis.FakeRedis`` for cancel flag / event log / choice
    response stash; we patch the module-level ``redis_client`` symbols
    where the endpoint imports them.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import fakeredis.aioredis
import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user
from app.core.database import get_db
from app.main import app
from app.models.agent_chat_message import AgentChatMessage, MessageRole
from app.models.agent_chat_session import AgentChatSession
from app.models.user import User
from app.services import agent_event_log_service, agent_session_service

# ---------------------------------------------------------------------------
# Fake DB
# ---------------------------------------------------------------------------


class FakeSession:
    """In-memory AsyncSession.  Stores AgentChatSession + AgentChatMessage rows."""

    def __init__(self) -> None:
        self.sessions: list[AgentChatSession] = []
        self.messages: list[AgentChatMessage] = []
        self.deleted_session_ids: set[UUID] = set()
        self.deleted_messages_for: set[UUID] = set()

    def add(self, obj: Any) -> None:
        if isinstance(obj, AgentChatSession):
            self.sessions.append(obj)
        elif isinstance(obj, AgentChatMessage):
            self.messages.append(obj)

    async def delete(self, obj: Any) -> None:
        if isinstance(obj, AgentChatSession):
            self.sessions = [s for s in self.sessions if s.id != obj.id]
            self.deleted_session_ids.add(obj.id)
        elif isinstance(obj, AgentChatMessage):
            self.messages = [m for m in self.messages if m.id != obj.id]

    async def flush(self) -> None:
        return None

    async def execute(self, stmt):
        # Detect SELECT vs DELETE by inspecting the statement class.
        is_delete = type(stmt).__name__ == "Delete"
        entity = None
        if not is_delete:
            descs = getattr(stmt, "column_descriptions", None)
            if descs:
                entity = descs[0].get("entity")
        if entity is None:
            # Core delete or fallback: identify by table name.
            tname = ""
            try:
                tname = stmt.table.name
            except Exception:
                try:
                    tname = list(stmt.columns_clause_froms)[0].name
                except Exception:
                    tname = ""
            if tname == "agent_chat_session":
                entity = AgentChatSession
            elif tname == "agent_chat_message":
                entity = AgentChatMessage

        if is_delete:
            wc = getattr(stmt, "whereclause", None)
            filters: dict = {}
            if wc is not None:
                _walk_where(wc, filters)
            tname = getattr(getattr(stmt, "table", None), "name", "")
            if tname == "agent_chat_session" or entity is AgentChatSession:
                victim_id = filters.get("id")
                if victim_id is not None:
                    self.sessions = [
                        s for s in self.sessions if s.id != victim_id
                    ]
                    self.deleted_session_ids.add(victim_id)
            elif tname == "agent_chat_message" or entity is AgentChatMessage:
                sid = filters.get("session_id")
                if sid is not None:
                    self.messages = [
                        m for m in self.messages if m.session_id != sid
                    ]
                    self.deleted_messages_for.add(sid)
            return _FakeResult([])

        # SELECT path
        rows: list[Any]
        if entity is AgentChatSession:
            rows = list(self.sessions)
        elif entity is AgentChatMessage:
            rows = list(self.messages)
        else:
            rows = []

        wc = getattr(stmt, "whereclause", None)
        filters: dict = {}
        if wc is not None:
            _walk_where(wc, filters)
        rows = [r for r in rows if _row_matches(r, filters)]

        # Apply order_by best-effort
        order_clauses = getattr(stmt, "_order_by_clauses", None)
        if order_clauses:
            for clause in reversed(list(order_clauses)):
                col_name = getattr(getattr(clause, "element", None), "key", None)
                if col_name is None:
                    col_name = getattr(clause, "key", None)
                desc = "DESC" in str(clause).upper()
                if col_name:
                    rows.sort(
                        key=lambda r: (getattr(r, col_name) is None, getattr(r, col_name)),
                        reverse=desc,
                    )

        # Apply limit
        limit_clause = getattr(stmt, "_limit_clause", None)
        if limit_clause is not None:
            try:
                lim = int(limit_clause.value)
            except Exception:
                lim = None
            if lim is not None:
                rows = rows[:lim]

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
    elif type_name in ("BooleanClauseList", "ClauseList"):
        for sub in clause.clauses:
            _walk_where(sub, filters)


def _row_matches(row: Any, filters: dict) -> bool:
    return all(
        getattr(row, col, None) == expected for col, expected in filters.items()
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_user(user_id: UUID | None = None) -> User:
    u = User()
    u.id = user_id or uuid4()
    u.email = f"test-{u.id.hex[:8]}@example.com"
    u.name = "Test User"
    u.hashed_password = "hashed"
    return u


def _make_session(
    *,
    actor_user_id: UUID | None = None,
    actor_api_key_id: UUID | None = None,
    workspace_id: UUID | None = None,
    agent_id: str = "general",
    context_kind: str = "workspace",
    last_message_at: datetime | None = None,
    title: str | None = None,
) -> AgentChatSession:
    s = AgentChatSession(
        id=uuid4(),
        workspace_id=workspace_id or uuid4(),
        agent_id=agent_id,
        actor_user_id=actor_user_id,
        actor_api_key_id=actor_api_key_id,
        context_kind=context_kind,
        title=title,
        compaction_stage=0,
        cancel_requested=False,
    )
    s.last_message_at = last_message_at or datetime.now(UTC)
    s.created_at = s.last_message_at
    s.updated_at = s.last_message_at
    s.context_id = None
    s.context_draft_id = None
    return s


def _make_message(
    session_id: UUID,
    *,
    sequence: int,
    role: MessageRole = MessageRole.USER,
    text: str | None = None,
    is_compacted: bool = False,
) -> AgentChatMessage:
    m = AgentChatMessage(
        id=uuid4(),
        session_id=session_id,
        sequence=sequence,
        role=role,
        content_text=text,
        is_compacted=is_compacted,
    )
    m.created_at = datetime.now(UTC)
    return m


@pytest.fixture
async def fake_redis():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


@pytest.fixture
def fake_db():
    return FakeSession()


@pytest.fixture(autouse=True)
def patch_redis_client(fake_redis):
    """Redirect the module-level redis_client to FakeRedis everywhere it's used.

    Both the API endpoint and the runtime ``cancel()`` symbol read from
    ``app.core.redis.redis_client`` — the API at module import, the runtime
    at function call time via ``from app.core.redis import redis_client``.
    Patching at the source covers both.
    """
    targets = [
        "app.core.redis.redis_client",
        "app.api.v1.agent_sessions.redis_client",
    ]
    patches = [patch(t, fake_redis) for t in targets]
    for p in patches:
        p.start()
    yield fake_redis
    for p in patches:
        p.stop()


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


def _jwt_client(user: User, db: FakeSession):
    """AsyncClient with JWT-style auth."""
    async def _fake_db():
        yield db

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _fake_db
    transport = ASGITransport(app=app)
    return AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer fake-jwt"},
    )


def _apikey_client(user: User, db: FakeSession, api_key_id: UUID):
    """AsyncClient simulating an API-key actor (with request.state.api_key set)."""
    api_key = MagicMock()
    api_key.id = api_key_id
    api_key.permissions = ["agents:read", "agents:write"]

    # Annotate ``request`` as ``Request`` so FastAPI injects it instead of
    # treating it as a query parameter (mirrors test_agents_discovery).
    async def _fake_user(request: Request):
        request.state.api_key = api_key
        return user

    async def _fake_db():
        yield db

    app.dependency_overrides[get_current_user] = _fake_user
    app.dependency_overrides[get_db] = _fake_db
    transport = ASGITransport(app=app)
    return AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer ak_fake"},
    )


# ---------------------------------------------------------------------------
# Tests — list_sessions
# ---------------------------------------------------------------------------


async def test_list_sessions_filters_by_user_actor(fake_db):
    user = _make_user()
    other_user = _make_user()
    api_key_id = uuid4()

    fake_db.sessions = [
        _make_session(actor_user_id=user.id),
        _make_session(actor_user_id=user.id),
        _make_session(actor_user_id=other_user.id),
        _make_session(actor_api_key_id=api_key_id),
    ]

    async with _jwt_client(user, fake_db) as ac:
        r = await ac.get("/api/v1/agents/sessions")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 2
    assert all(
        UUID(item["id"]) in {s.id for s in fake_db.sessions if s.actor_user_id == user.id}
        for item in items
    )


async def test_list_sessions_filters_by_api_key_actor(fake_db):
    user = _make_user()
    api_key_id = uuid4()
    other_api_key_id = uuid4()

    fake_db.sessions = [
        _make_session(actor_user_id=user.id),  # user-owned, must NOT appear
        _make_session(actor_api_key_id=api_key_id),
        _make_session(actor_api_key_id=other_api_key_id),
    ]

    async with _apikey_client(user, fake_db, api_key_id) as ac:
        r = await ac.get("/api/v1/agents/sessions")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1
    assert UUID(items[0]["id"]) == fake_db.sessions[1].id


async def test_list_sessions_filter_by_agent_id_and_context_kind(fake_db):
    user = _make_user()
    fake_db.sessions = [
        _make_session(actor_user_id=user.id, agent_id="general", context_kind="workspace"),
        _make_session(actor_user_id=user.id, agent_id="researcher", context_kind="workspace"),
        _make_session(actor_user_id=user.id, agent_id="general", context_kind="diagram"),
    ]

    async with _jwt_client(user, fake_db) as ac:
        r = await ac.get("/api/v1/agents/sessions?agent_id=general")
        assert r.status_code == 200
        ids = {item["agent_id"] for item in r.json()["items"]}
        assert ids == {"general"}
        assert len(r.json()["items"]) == 2

        r = await ac.get(
            "/api/v1/agents/sessions?agent_id=general&context_kind=diagram"
        )
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) == 1
        assert items[0]["context_kind"] == "diagram"


# ---------------------------------------------------------------------------
# Tests — get_session
# ---------------------------------------------------------------------------


async def test_get_session_owner_sees_messages_in_order(fake_db):
    user = _make_user()
    s = _make_session(actor_user_id=user.id)
    fake_db.sessions = [s]
    fake_db.messages = [
        _make_message(s.id, sequence=2, role=MessageRole.ASSISTANT, text="b"),
        _make_message(s.id, sequence=0, role=MessageRole.USER, text="a"),
        _make_message(s.id, sequence=1, role=MessageRole.TOOL, text="t"),
    ]

    async with _jwt_client(user, fake_db) as ac:
        r = await ac.get(f"/api/v1/agents/sessions/{s.id}")
    assert r.status_code == 200, r.text
    body = r.json()
    seqs = [m["sequence"] for m in body["messages"]]
    assert seqs == [0, 1, 2], seqs


async def test_get_session_other_user_returns_404(fake_db):
    user = _make_user()
    other = _make_user()
    s = _make_session(actor_user_id=other.id)
    fake_db.sessions = [s]

    async with _jwt_client(user, fake_db) as ac:
        r = await ac.get(f"/api/v1/agents/sessions/{s.id}")
    assert r.status_code == 404


async def test_get_session_user_cannot_see_api_key_session(fake_db):
    user = _make_user()
    api_key_id = uuid4()
    s = _make_session(actor_api_key_id=api_key_id)
    fake_db.sessions = [s]

    async with _jwt_client(user, fake_db) as ac:
        r = await ac.get(f"/api/v1/agents/sessions/{s.id}")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Tests — cancel
# ---------------------------------------------------------------------------


async def test_cancel_sets_redis_flag(fake_db, fake_redis):
    user = _make_user()
    s = _make_session(actor_user_id=user.id)
    fake_db.sessions = [s]

    async with _jwt_client(user, fake_db) as ac:
        r = await ac.post(f"/api/v1/agents/sessions/{s.id}/cancel")
    assert r.status_code == 202, r.text
    val = await fake_redis.get(f"cancel:{s.id}")
    assert val == "1"
    ttl = await fake_redis.ttl(f"cancel:{s.id}")
    assert 0 < ttl <= agent_session_service.CANCEL_TTL_SECONDS


async def test_cancel_404_for_other_actor(fake_db, fake_redis):
    user = _make_user()
    other = _make_user()
    s = _make_session(actor_user_id=other.id)
    fake_db.sessions = [s]

    async with _jwt_client(user, fake_db) as ac:
        r = await ac.post(f"/api/v1/agents/sessions/{s.id}/cancel")
    assert r.status_code == 404
    val = await fake_redis.get(f"cancel:{s.id}")
    assert val is None


async def test_runtime_cancel_helper_sets_flag(fake_redis):
    """``app.agents.runtime.cancel`` is the public symbol that wires up the flag."""
    from app.agents import runtime

    sid = uuid4()
    await runtime.cancel(sid)
    assert await fake_redis.get(f"cancel:{sid}") == "1"


# ---------------------------------------------------------------------------
# Tests — respond
# ---------------------------------------------------------------------------


async def test_respond_stores_choice_in_redis(fake_db, fake_redis):
    user = _make_user()
    s = _make_session(actor_user_id=user.id)
    fake_db.sessions = [s]

    async with _jwt_client(user, fake_db) as ac:
        r = await ac.post(
            f"/api/v1/agents/sessions/{s.id}/respond",
            json={
                "tool_call_id": "tc-abc",
                "choice_id": "use_existing_draft",
                "extra": {"draft_id": "01j-draft"},
            },
        )
    assert r.status_code == 200, r.text
    raw = await fake_redis.get(f"choice_response:{s.id}:tc-abc")
    assert raw is not None
    decoded = json.loads(raw)
    assert decoded["choice_id"] == "use_existing_draft"
    assert decoded["extra"]["draft_id"] == "01j-draft"


# ---------------------------------------------------------------------------
# Tests — delete
# ---------------------------------------------------------------------------


async def test_delete_session_cascades_messages(fake_db):
    user = _make_user()
    s = _make_session(actor_user_id=user.id)
    fake_db.sessions = [s]
    fake_db.messages = [
        _make_message(s.id, sequence=0, text="hi"),
        _make_message(s.id, sequence=1, text="ok"),
    ]

    async with _jwt_client(user, fake_db) as ac:
        r = await ac.delete(f"/api/v1/agents/sessions/{s.id}")
    assert r.status_code == 204
    assert s.id in fake_db.deleted_messages_for
    assert s.id in fake_db.deleted_session_ids


async def test_delete_session_other_actor_404(fake_db):
    user = _make_user()
    other = _make_user()
    s = _make_session(actor_user_id=other.id)
    fake_db.sessions = [s]

    async with _jwt_client(user, fake_db) as ac:
        r = await ac.delete(f"/api/v1/agents/sessions/{s.id}")
    assert r.status_code == 404
    assert s.id not in fake_db.deleted_session_ids


# ---------------------------------------------------------------------------
# Tests — stream reconnect
# ---------------------------------------------------------------------------


async def test_stream_replays_events_after_since(fake_db, fake_redis):
    user = _make_user()
    s = _make_session(actor_user_id=user.id)
    fake_db.sessions = [s]

    # Seed event log with sequences 1..3 + done(4).
    for i, kind in enumerate(("session", "node", "message", "done"), start=1):
        await agent_event_log_service.append_event(
            fake_redis, s.id, i, kind, {"i": i}
        )
    # finalize so it's "completed but replayable"
    await agent_event_log_service.finalize_stream(fake_redis, s.id)

    async with (
        _jwt_client(user, fake_db) as ac,
        ac.stream(
            "GET",
            f"/api/v1/agents/sessions/{s.id}/stream?since=1",
        ) as resp,
    ):
        assert resp.status_code == 200
        body = b""
        async for chunk in resp.aiter_bytes():
            body += chunk
            if b"event: done" in body:
                break
    text = body.decode()
    # We should have replayed 2, 3, and 4 (done) — but NOT 1.
    assert "id: 1\n" not in text
    assert "id: 2\n" in text
    assert "id: 3\n" in text
    assert "id: 4\n" in text
    assert "event: done" in text


async def test_stream_410_when_ttl_expired(fake_db, fake_redis):
    user = _make_user()
    s = _make_session(actor_user_id=user.id)
    fake_db.sessions = [s]

    # No stream entries → expired.
    async with _jwt_client(user, fake_db) as ac:
        r = await ac.get(f"/api/v1/agents/sessions/{s.id}/stream")
    assert r.status_code == 410


async def test_stream_404_for_non_owner(fake_db, fake_redis):
    user = _make_user()
    other = _make_user()
    s = _make_session(actor_user_id=other.id)
    fake_db.sessions = [s]
    await agent_event_log_service.append_event(
        fake_redis, s.id, 1, "session", {}
    )

    async with _jwt_client(user, fake_db) as ac:
        r = await ac.get(f"/api/v1/agents/sessions/{s.id}/stream")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Tests — runtime-side cancel flag honour
# ---------------------------------------------------------------------------


class _ChattyGraph:
    """Stub graph that yields many small ``on_chain_start`` events so the
    cancel-poll-every-5-events branch in ``_drive_graph`` can fire."""

    def __init__(self, num_events: int = 30) -> None:
        self.num_events = num_events

    def get_graph(self):
        g = MagicMock()
        g.nodes = {"__start__": None, "__end__": None, "supervisor": None}
        return g

    async def astream_events(self, state, version=None, config=None):  # noqa: ARG002
        for i in range(self.num_events):
            yield {
                "event": "on_chain_start",
                "name": "supervisor",
                "data": {"i": i},
            }
        yield {
            "event": "on_chain_end",
            "name": "__graph__",
            "data": {
                "output": {
                    "final_message": "interrupted",
                    "applied_changes": [],
                    "tokens_in": 0,
                    "tokens_out": 0,
                    "messages": list(state.get("messages") or []),
                }
            },
        }


async def test_runtime_sees_cancel_flag_emits_cancelled_then_done(fake_redis):
    """End-to-end: set the cancel flag → drive ``stream`` → see ``cancelled``
    + ``done`` events, with ``forced_finalize='cancelled'`` in usage."""
    from app.agents import registry, runtime
    from app.agents.runtime import (
        ActorRef,
        ChatContext,
        InvokeRequest,
    )
    from app.services.agent_settings_service import ResolvedAgentSettings

    workspace_id = uuid4()
    actor = ActorRef(
        kind="user", id=uuid4(), workspace_id=workspace_id, agent_access="full"
    )
    sess_id = uuid4()
    # Pre-set the cancel flag so the very first poll (after 5 events) catches it.
    await runtime.cancel(sess_id)

    graph = _ChattyGraph(num_events=20)
    desc = registry.AgentDescriptor(
        id="cancel-test-agent",
        name="cancel test",
        description="",
        graph=graph,
        surfaces=frozenset({"a2a"}),
        allowed_contexts=frozenset({"workspace"}),
        supported_modes=("full", "read_only"),
        required_scope="agents:invoke",
    )
    registry.clear()
    registry.register(desc)

    db = FakeSession()
    pre = AgentChatSession(
        id=sess_id,
        workspace_id=workspace_id,
        agent_id="cancel-test-agent",
        actor_user_id=actor.id,
        actor_api_key_id=None,
        context_kind="workspace",
        compaction_stage=0,
        cancel_requested=False,
    )
    db.add(pre)

    req = InvokeRequest(
        agent_id="cancel-test-agent",
        actor=actor,
        workspace_id=workspace_id,
        chat_context=ChatContext(kind="workspace", id=workspace_id),
        message="hi",
        session_id=sess_id,
    )

    # Stub out resolve_for_agent + check_and_consume so we don't hit DB / rate.
    async def _fake_resolve(db, ws, aid):  # noqa: ARG001
        return ResolvedAgentSettings(workspace_id=ws, agent_id=aid)

    async def _fake_consume(*a, **kw):  # noqa: ARG001
        return None

    with (
        patch("app.agents.runtime.resolve_for_agent", side_effect=_fake_resolve),
        patch("app.agents.runtime.check_and_consume", side_effect=_fake_consume),
    ):
        events = []
        async for ev in runtime.stream(req, db=db):
            events.append(ev)

    kinds = [e.kind for e in events]
    assert "cancelled" in kinds, f"expected cancelled in {kinds}"
    assert kinds[-1] == "done"
    # forced_finalize on the usage event should reflect the cancel.
    usage = next(e for e in events if e.kind == "usage")
    assert usage.payload.get("forced_finalize") == "cancelled"
    # The cancel flag should have been cleared after the run.
    assert await fake_redis.get(f"cancel:{sess_id}") is None
