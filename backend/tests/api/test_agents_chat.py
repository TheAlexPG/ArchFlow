"""Tests for ``POST /api/v1/agents/{agent_id}/chat`` (task agent-core-mvp-036).

The chat endpoint streams ``text/event-stream`` events out of
:func:`app.agents.runtime.stream`.  These tests substitute a fake runtime
generator + a fakeredis client so we exercise the API layer in isolation:

  * SSE wire format (``event:`` / ``id:`` / ``data:``).
  * Heartbeat insertion when the runtime stalls.
  * Mid-stream error mapping (always ends with ``done``, HTTP 200).
  * Pre-stream rate limit + auth → standard 4xx envelope.
  * Per-event ID monotonic increment.
  * Redis stream persistence + TTL after ``done``.
  * Headers (Cache-Control, Connection, X-Accel-Buffering).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.errors import BudgetExhausted
from app.agents.runtime import SSEEvent
from app.api.deps import get_current_user
from app.api.v1.agents import get_current_actor
from app.core.database import get_db
from app.main import app
from app.models.user import User
from app.models.workspace import AgentAccessLevel, WorkspaceMember
from app.services import agent_event_log_service

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_user(user_id: uuid.UUID | None = None) -> User:
    u = User()
    u.id = user_id or uuid.uuid4()
    u.email = f"chat-{u.id.hex[:8]}@example.com"
    u.name = "Chat User"
    u.hashed_password = "hashed"
    return u


def _make_membership(
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    access: AgentAccessLevel = AgentAccessLevel.FULL,
) -> WorkspaceMember:
    m = WorkspaceMember()
    m.workspace_id = workspace_id
    m.user_id = user_id
    m.agent_access = access
    return m


@pytest.fixture
async def fake_redis():
    """Fresh in-memory FakeRedis per test."""
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


@pytest.fixture(autouse=True)
def patch_redis(fake_redis):
    """Redirect both the API endpoint's redis_client and the event-log
    service's resolved client (it imports redis_client at call-time via the
    module path).
    """
    with patch("app.api.v1.agents.redis_client", fake_redis):
        yield


@pytest.fixture(autouse=True)
def patch_rate_limit_preflight():
    """Default to a no-op pre-flight so tests don't accidentally hit the real
    limiter.  Tests that want a 429 override this with their own patch.
    """
    async def _fake(actor, db, agent_id):  # noqa: ARG001
        return None

    with patch("app.api.v1.agents._rate_limit_preflight", side_effect=_fake):
        yield


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


def _override_actor(user: User, workspace_id: uuid.UUID) -> None:
    """Force get_current_actor to return a deterministic user actor."""

    async def _fake_actor():
        from app.agents.runtime import ActorRef

        return ActorRef(
            kind="user",
            id=user.id,
            workspace_id=workspace_id,
            agent_access="full",
        )

    app.dependency_overrides[get_current_actor] = _fake_actor
    app.dependency_overrides[get_current_user] = lambda: user

    async def _fake_db() -> AsyncGenerator:
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = _make_membership(
            user.id, workspace_id
        )
        db.execute = AsyncMock(return_value=result_mock)
        yield db

    app.dependency_overrides[get_db] = _fake_db


def _client() -> AsyncClient:
    transport = ASGITransport(app=app)
    return AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer fake-jwt"},
    )


# ---------------------------------------------------------------------------
# Fake runtime stream factories
# ---------------------------------------------------------------------------


def _make_runtime_stream(events: list[SSEEvent]):
    """Build a function compatible with ``runtime_stream(req, db=...)`` that
    yields the given canned events.
    """

    async def _gen(req, *, db) -> AsyncIterator[SSEEvent]:  # noqa: ARG001
        for ev in events:
            yield ev

    return _gen


def _parse_sse(text: str) -> list[dict]:
    """Parse an SSE wire stream into a list of {event, id, data} dicts."""
    out: list[dict] = []
    for raw in text.split("\n\n"):
        chunk = raw.strip()
        if not chunk:
            continue
        item: dict = {}
        for line in chunk.split("\n"):
            if ": " in line:
                key, _, val = line.partition(": ")
                item[key] = val
        if "data" in item:
            try:
                item["payload"] = json.loads(item["data"])
            except (TypeError, ValueError):
                item["payload"] = None
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# 1. Happy path — session → message → done
# ---------------------------------------------------------------------------


async def test_chat_emits_session_message_done_in_order(fake_redis):  # noqa: ARG001
    user = _make_user()
    workspace_id = uuid.uuid4()
    session_id = uuid.uuid4()
    _override_actor(user, workspace_id)

    events = [
        SSEEvent("session", {"session_id": str(session_id), "agent_id": "general"}),
        SSEEvent("message", {"text": "hello"}),
        SSEEvent("usage", {"tokens_in": 10, "tokens_out": 5, "cost_usd": "0.001"}),
        SSEEvent("done", {"session_id": str(session_id)}),
    ]

    with patch(
        "app.api.v1.agents.runtime_stream",
        side_effect=_make_runtime_stream(events),
    ):
        async with _client() as ac:
            r = await ac.post(
                "/api/v1/agents/general/chat",
                json={"message": "hi"},
            )

    assert r.status_code == 200
    parsed = _parse_sse(r.text)
    kinds = [p["event"] for p in parsed]
    assert kinds[0] == "session"
    assert kinds[-1] == "done"
    assert "message" in kinds
    # Each event has incrementing id starting at 0
    ids = [int(p["id"]) for p in parsed]
    assert ids == sorted(ids)
    assert ids[0] == 0


# ---------------------------------------------------------------------------
# 2. Heartbeat — runtime stalls → ping inserted
# ---------------------------------------------------------------------------


async def test_chat_emits_ping_when_runtime_idle():
    user = _make_user()
    workspace_id = uuid.uuid4()
    session_id = uuid.uuid4()
    _override_actor(user, workspace_id)

    async def _slow_stream(req, *, db):  # noqa: ARG001
        yield SSEEvent("session", {"session_id": str(session_id), "agent_id": "general"})
        # Sleep long enough to trip the heartbeat timeout (which we override to 0.05s).
        await asyncio.sleep(0.2)
        yield SSEEvent("message", {"text": "ok"})
        yield SSEEvent("done", {"session_id": str(session_id)})

    # Shrink the heartbeat to keep the test fast.
    with patch("app.api.v1.agents._HEARTBEAT_INTERVAL_SECONDS", 0.05), patch(
        "app.api.v1.agents.runtime_stream", side_effect=_slow_stream
    ):
        async with _client() as ac:
            r = await ac.post(
                "/api/v1/agents/general/chat",
                json={"message": "hi"},
            )

    assert r.status_code == 200
    parsed = _parse_sse(r.text)
    kinds = [p["event"] for p in parsed]
    assert "ping" in kinds, f"expected at least one heartbeat, got {kinds}"
    # session must remain first; done must remain last
    assert kinds[0] == "session"
    assert kinds[-1] == "done"


# ---------------------------------------------------------------------------
# 3. Mid-stream BudgetExhausted → error event then done, HTTP 200
# ---------------------------------------------------------------------------


async def test_chat_budget_exhausted_midstream_yields_error_then_done():
    user = _make_user()
    workspace_id = uuid.uuid4()
    session_id = uuid.uuid4()
    _override_actor(user, workspace_id)

    async def _exploding(req, *, db):  # noqa: ARG001
        yield SSEEvent("session", {"session_id": str(session_id), "agent_id": "general"})
        yield SSEEvent("node", {"name": "planner"})
        raise BudgetExhausted("budget hit")

    with patch("app.api.v1.agents.runtime_stream", side_effect=_exploding):
        async with _client() as ac:
            r = await ac.post(
                "/api/v1/agents/general/chat",
                json={"message": "hi"},
            )

    assert r.status_code == 200
    parsed = _parse_sse(r.text)
    kinds = [p["event"] for p in parsed]
    err_idx = kinds.index("error")
    done_idx = kinds.index("done")
    assert err_idx < done_idx
    err_payload = parsed[err_idx]["payload"]
    assert err_payload["code"] == "budget_exhausted"


# ---------------------------------------------------------------------------
# 4. Mid-stream generic AgentError → mapped to agent_error code
# ---------------------------------------------------------------------------


async def test_chat_generic_agent_error_midstream():
    from app.agents.errors import AgentError

    user = _make_user()
    workspace_id = uuid.uuid4()
    session_id = uuid.uuid4()
    _override_actor(user, workspace_id)

    async def _bad(req, *, db):  # noqa: ARG001
        yield SSEEvent("session", {"session_id": str(session_id), "agent_id": "general"})
        raise AgentError("oops")

    with patch("app.api.v1.agents.runtime_stream", side_effect=_bad):
        async with _client() as ac:
            r = await ac.post(
                "/api/v1/agents/general/chat",
                json={"message": "hi"},
            )

    assert r.status_code == 200
    parsed = _parse_sse(r.text)
    err = next(p for p in parsed if p["event"] == "error")
    assert err["payload"]["code"] == "agent_error"
    assert parsed[-1]["event"] == "done"


# ---------------------------------------------------------------------------
# 5. Pre-stream rate-limit → 429 standard envelope
# ---------------------------------------------------------------------------


async def test_chat_pre_stream_rate_limit_returns_429():
    from app.services.rate_limit_service import RateLimitExceeded

    user = _make_user()
    workspace_id = uuid.uuid4()
    _override_actor(user, workspace_id)

    async def _exceed(actor, db, agent_id):  # noqa: ARG001
        raise RateLimitExceeded(scope="user:day", limit=1000, retry_after_seconds=3600)

    with patch("app.api.v1.agents._rate_limit_preflight", side_effect=_exceed):
        async with _client() as ac:
            r = await ac.post(
                "/api/v1/agents/general/chat",
                json={"message": "hi"},
            )

    assert r.status_code == 429
    body = r.json()
    assert body["error"]["code"] == "rate_limited"
    assert "Retry-After" in r.headers


# ---------------------------------------------------------------------------
# 6. Pre-stream auth fail → 401
# ---------------------------------------------------------------------------


async def test_chat_no_auth_returns_401():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/api/v1/agents/general/chat", json={"message": "hi"})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# 7. Each event has incrementing id (already partially covered in #1; here we
#    assert the strict 0,1,2,3,... contract).
# ---------------------------------------------------------------------------


async def test_chat_event_ids_are_strictly_sequential():
    user = _make_user()
    workspace_id = uuid.uuid4()
    session_id = uuid.uuid4()
    _override_actor(user, workspace_id)

    events = [
        SSEEvent("session", {"session_id": str(session_id)}),
        SSEEvent("node", {"name": "planner"}),
        SSEEvent("node", {"name": "researcher"}),
        SSEEvent("applied_change", {"action": "create_object", "name": "DB"}),
        SSEEvent("message", {"text": "done"}),
        SSEEvent("done", {"session_id": str(session_id)}),
    ]

    with patch(
        "app.api.v1.agents.runtime_stream",
        side_effect=_make_runtime_stream(events),
    ):
        async with _client() as ac:
            r = await ac.post(
                "/api/v1/agents/general/chat",
                json={"message": "hi"},
            )

    parsed = _parse_sse(r.text)
    ids = [int(p["id"]) for p in parsed]
    assert ids == list(range(len(parsed)))


# ---------------------------------------------------------------------------
# 8. Redis stream is populated after the run completes
# ---------------------------------------------------------------------------


async def test_chat_persists_events_to_redis_stream(fake_redis):
    user = _make_user()
    workspace_id = uuid.uuid4()
    session_id = uuid.uuid4()
    _override_actor(user, workspace_id)

    events = [
        SSEEvent("session", {"session_id": str(session_id)}),
        SSEEvent("message", {"text": "hi"}),
        SSEEvent("done", {"session_id": str(session_id)}),
    ]

    with patch(
        "app.api.v1.agents.runtime_stream",
        side_effect=_make_runtime_stream(events),
    ):
        async with _client() as ac:
            r = await ac.post(
                "/api/v1/agents/general/chat",
                json={"message": "hi"},
            )
    assert r.status_code == 200

    # Read back via XRANGE.
    key = agent_event_log_service.stream_key(session_id)
    entries = await fake_redis.xrange(key)
    assert entries, "expected at least one event to land in the Redis stream"
    kinds = [fields["kind"] for _id, fields in entries]
    assert kinds[0] == "session"
    assert kinds[-1] == "done"


# ---------------------------------------------------------------------------
# 9. Stream TTL is set after `done`
# ---------------------------------------------------------------------------


async def test_chat_sets_ttl_on_stream_after_done(fake_redis):
    user = _make_user()
    workspace_id = uuid.uuid4()
    session_id = uuid.uuid4()
    _override_actor(user, workspace_id)

    events = [
        SSEEvent("session", {"session_id": str(session_id)}),
        SSEEvent("done", {"session_id": str(session_id)}),
    ]

    with patch(
        "app.api.v1.agents.runtime_stream",
        side_effect=_make_runtime_stream(events),
    ):
        async with _client() as ac:
            r = await ac.post(
                "/api/v1/agents/general/chat",
                json={"message": "hi"},
            )
    assert r.status_code == 200

    key = agent_event_log_service.stream_key(session_id)
    ttl = await fake_redis.ttl(key)
    # TTL should be set (>0). Exact value is agent_event_log_service.TTL_SECONDS
    # but FakeRedis returns the remaining seconds which can be slightly less.
    assert ttl > 0
    assert ttl <= agent_event_log_service.TTL_SECONDS


# ---------------------------------------------------------------------------
# 10. Required SSE headers are set
# ---------------------------------------------------------------------------


async def test_chat_sets_sse_headers():
    user = _make_user()
    workspace_id = uuid.uuid4()
    session_id = uuid.uuid4()
    _override_actor(user, workspace_id)

    events = [
        SSEEvent("session", {"session_id": str(session_id)}),
        SSEEvent("done", {"session_id": str(session_id)}),
    ]

    with patch(
        "app.api.v1.agents.runtime_stream",
        side_effect=_make_runtime_stream(events),
    ):
        async with _client() as ac:
            r = await ac.post(
                "/api/v1/agents/general/chat",
                json={"message": "hi"},
            )

    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-cache"
    assert r.headers.get("connection") == "keep-alive"
    assert r.headers.get("x-accel-buffering") == "no"
    assert r.headers.get("content-type", "").startswith("text/event-stream")


# ---------------------------------------------------------------------------
# 11. Replay helper round-trip — ensures event_log_service plays the role
#     task 037 will rely on for reconnect.
# ---------------------------------------------------------------------------


async def test_event_log_service_replay_since_filters_correctly(fake_redis):
    sid = uuid.uuid4()
    for i, kind in enumerate(["session", "token", "token", "message", "done"]):
        await agent_event_log_service.append_event(
            fake_redis, sid, i, kind, {"i": i}
        )
    out = []
    async for ev_id, kind, payload in agent_event_log_service.replay_since(
        fake_redis, sid, since_id=1
    ):
        out.append((ev_id, kind, payload["i"]))
    # Should include events 2, 3, 4 only
    assert out == [(2, "token", 2), (3, "message", 3), (4, "done", 4)]
