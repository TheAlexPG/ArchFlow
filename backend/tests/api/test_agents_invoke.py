"""Tests for POST /api/v1/agents/{agent_id}/invoke (task agent-core-mvp-035).

Uses dependency overrides + ``unittest.mock.patch`` so no real DB, Redis, or
runtime calls are made.  All ~10 cases listed in the task brief are covered.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: F401

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents import registry as agent_registry
from app.agents.errors import AgentError, BudgetExhausted, ContextOverflow, TurnLimitReached
from app.agents.runtime import ActorRef, InvokeResult
from app.api.deps import get_current_user
from app.api.v1.agents import get_current_actor
from app.core.database import get_db
from app.main import app
from app.models.user import User
from app.services.rate_limit_service import RateLimitExceeded

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_AGENT_ID = "test-agent"
_INVOKE_URL = f"/api/v1/agents/{_AGENT_ID}/invoke"

_GOOD_BODY = {
    "message": "hello",
    "context": {"kind": "none"},
    "mode": "read_only",
}


def _canned_result(
    *,
    final_message: str = "done",
    applied_changes: list | None = None,
    tokens_in: int = 10,
    tokens_out: int = 5,
) -> InvokeResult:
    return InvokeResult(
        session_id=uuid.uuid4(),
        agent_id=_AGENT_ID,
        final_message=final_message,
        applied_changes=applied_changes or [],
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=Decimal("0.001"),
        duration_ms=123,
        forced_finalize=None,
        warnings=[],
    )


def _make_user() -> User:
    u = User()
    u.id = uuid.uuid4()
    u.email = f"test-{u.id.hex[:8]}@example.com"
    u.name = "Test User"
    return u


def _make_actor(user: User, *, kind: str = "user", agent_access: str = "full") -> ActorRef:
    return ActorRef(
        kind=kind,  # type: ignore[arg-type]
        id=user.id,
        workspace_id=uuid.uuid4(),
        agent_access=agent_access,  # type: ignore[arg-type]
        scopes=("agents:read",) if kind == "api_key" else (),
    )


def _fake_db_override():
    async def _fake_db() -> AsyncGenerator:
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)
        yield db

    return _fake_db


def _build_client(user: User, actor: ActorRef) -> AsyncClient:
    """Return an AsyncClient with auth + actor + DB fully stubbed out."""
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_actor] = lambda: actor
    app.dependency_overrides[get_db] = _fake_db_override()
    transport = ASGITransport(app=app)
    return AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer fake-token"},
    )


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def reset_registry():
    agent_registry.clear()
    yield
    agent_registry.clear()


# ---------------------------------------------------------------------------
# fakeredis fixture — patch redis_client globally during each test
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_redis():
    """Replace redis_client in agents.py with an in-memory fakeredis instance."""
    import fakeredis.aioredis as fakeredis_aio

    r = fakeredis_aio.FakeRedis()
    with patch("app.api.v1.agents.redis_client", r):
        yield r


# ---------------------------------------------------------------------------
# 1. Happy path: 200 with correct response envelope
# ---------------------------------------------------------------------------


async def test_invoke_happy_path(fake_redis):
    user = _make_user()
    actor = _make_actor(user)
    result = _canned_result(final_message="all good", tokens_in=7, tokens_out=3)

    async with _build_client(user, actor) as ac:
        with patch("app.api.v1.agents.invoke", new=AsyncMock(return_value=result)):
            r = await ac.post(_INVOKE_URL, json=_GOOD_BODY)

    assert r.status_code == 200
    body = r.json()
    assert body["agent_id"] == _AGENT_ID
    assert body["final_message"] == "all good"
    assert body["tokens"] == {"in": 7, "out": 3}
    assert "session_id" in body
    assert "cost_usd" in body
    assert "duration_ms" in body
    assert isinstance(body["warnings"], list)


# ---------------------------------------------------------------------------
# 2. Unknown agent → 404 agent_not_found
# ---------------------------------------------------------------------------


async def test_invoke_unknown_agent_404(fake_redis):
    user = _make_user()
    actor = _make_actor(user)

    async with _build_client(user, actor) as ac:
        with patch(
            "app.api.v1.agents.invoke",
            new=AsyncMock(side_effect=AgentError("Agent 'test-agent' not found")),
        ):
            r = await ac.post(_INVOKE_URL, json=_GOOD_BODY)

    assert r.status_code == 404
    err = r.json()["error"]
    assert err["code"] == "agent_not_found"
    assert err["agent_id"] == _AGENT_ID


# ---------------------------------------------------------------------------
# 3. Rate limit → 429 with Retry-After header
# ---------------------------------------------------------------------------


async def test_invoke_rate_limited_429(fake_redis):
    user = _make_user()
    actor = _make_actor(user)

    async with _build_client(user, actor) as ac:
        with patch(
            "app.api.v1.agents.invoke",
            new=AsyncMock(
                side_effect=RateLimitExceeded(
                    scope="api_key:hour", limit=600, retry_after_seconds=42
                )
            ),
        ):
            r = await ac.post(_INVOKE_URL, json=_GOOD_BODY)

    assert r.status_code == 429
    assert r.headers.get("retry-after") == "42"
    err = r.json()["error"]
    assert err["code"] == "rate_limited"
    assert err["agent_id"] == _AGENT_ID


# ---------------------------------------------------------------------------
# 4. BudgetExhausted → 402
# ---------------------------------------------------------------------------


async def test_invoke_budget_exhausted_402(fake_redis):
    user = _make_user()
    actor = _make_actor(user)

    async with _build_client(user, actor) as ac:
        with patch(
            "app.api.v1.agents.invoke",
            new=AsyncMock(side_effect=BudgetExhausted("budget limit reached")),
        ):
            r = await ac.post(_INVOKE_URL, json=_GOOD_BODY)

    assert r.status_code == 402
    err = r.json()["error"]
    assert err["code"] == "agent_budget_exhausted"


# ---------------------------------------------------------------------------
# 5. TurnLimitReached → 409 turn_limit_reached
# ---------------------------------------------------------------------------


async def test_invoke_turn_limit_409(fake_redis):
    user = _make_user()
    actor = _make_actor(user)

    async with _build_client(user, actor) as ac:
        with patch(
            "app.api.v1.agents.invoke",
            new=AsyncMock(side_effect=TurnLimitReached("turn limit")),
        ):
            r = await ac.post(_INVOKE_URL, json=_GOOD_BODY)

    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "turn_limit_reached"


# ---------------------------------------------------------------------------
# 6. ContextOverflow → 413
# ---------------------------------------------------------------------------


async def test_invoke_context_overflow_413(fake_redis):
    user = _make_user()
    actor = _make_actor(user)

    async with _build_client(user, actor) as ac:
        with patch(
            "app.api.v1.agents.invoke",
            new=AsyncMock(side_effect=ContextOverflow("context too large")),
        ):
            r = await ac.post(_INVOKE_URL, json=_GOOD_BODY)

    assert r.status_code == 413
    err = r.json()["error"]
    assert err["code"] == "context_overflow"


# ---------------------------------------------------------------------------
# 7. ValidationError on body → 422 (FastAPI/Pydantic validation)
# ---------------------------------------------------------------------------


async def test_invoke_validation_error_missing_message(fake_redis):
    """Omitting 'message' should trigger Pydantic validation → 422."""
    user = _make_user()
    actor = _make_actor(user)

    bad_body = {"context": {"kind": "none"}}  # missing required 'message'

    async with _build_client(user, actor) as ac:
        r = await ac.post(_INVOKE_URL, json=bad_body)

    assert r.status_code == 422


# ---------------------------------------------------------------------------
# 8. Idempotency-Key: first call cached, second same body → cached response
# ---------------------------------------------------------------------------


async def test_invoke_idempotency_key_same_body_returns_cached(fake_redis):
    user = _make_user()
    actor = _make_actor(user)
    result = _canned_result(final_message="first run")
    idem_key = str(uuid.uuid4())

    invoke_mock = AsyncMock(return_value=result)

    async with _build_client(user, actor) as ac:
        with patch("app.api.v1.agents.invoke", new=invoke_mock):
            # First call — should run the agent and cache
            r1 = await ac.post(
                _INVOKE_URL,
                json=_GOOD_BODY,
                headers={"Idempotency-Key": idem_key},
            )
            assert r1.status_code == 200
            assert r1.json()["final_message"] == "first run"

            # Second call — same key + same body → returns cached, invoke NOT called again
            r2 = await ac.post(
                _INVOKE_URL,
                json=_GOOD_BODY,
                headers={"Idempotency-Key": idem_key},
            )
            assert r2.status_code == 200
            assert r2.json()["final_message"] == "first run"

    # invoke() called exactly once despite two HTTP calls
    assert invoke_mock.call_count == 1


# ---------------------------------------------------------------------------
# 9. Idempotency-Key: same key + different body → 409 idempotency_conflict
# ---------------------------------------------------------------------------


async def test_invoke_idempotency_key_different_body_409(fake_redis):
    user = _make_user()
    actor = _make_actor(user)
    result = _canned_result()
    idem_key = str(uuid.uuid4())

    different_body = {**_GOOD_BODY, "message": "a completely different message"}

    invoke_mock = AsyncMock(return_value=result)

    async with _build_client(user, actor) as ac:
        with patch("app.api.v1.agents.invoke", new=invoke_mock):
            # First call — normal
            r1 = await ac.post(
                _INVOKE_URL,
                json=_GOOD_BODY,
                headers={"Idempotency-Key": idem_key},
            )
            assert r1.status_code == 200

            # Second call — same key, different body → conflict
            r2 = await ac.post(
                _INVOKE_URL,
                json=different_body,
                headers={"Idempotency-Key": idem_key},
            )

    assert r2.status_code == 409
    err = r2.json()["error"]
    assert err["code"] == "idempotency_conflict"


# ---------------------------------------------------------------------------
# 10. ApiKey actor with only agents:read scope → read_only is allowed,
#     requesting 'full' mode gets clamped (PermissionError from runtime) → 403
# ---------------------------------------------------------------------------


async def test_invoke_permission_denied_403(fake_redis):
    """PermissionError raised by runtime → 403 permission_denied."""
    user = _make_user()
    # api_key actor with only read scope
    actor = ActorRef(
        kind="api_key",
        id=user.id,
        workspace_id=uuid.uuid4(),
        scopes=("agents:read",),
    )

    async with _build_client(user, actor) as ac:
        with patch(
            "app.api.v1.agents.invoke",
            new=AsyncMock(side_effect=PermissionError("permission denied")),
        ):
            # Request full mode — runtime will raise PermissionError
            r = await ac.post(_INVOKE_URL, json={**_GOOD_BODY, "mode": "full"})

    assert r.status_code == 403
    err = r.json()["error"]
    assert err["code"] == "permission_denied"
    assert err["agent_id"] == _AGENT_ID


# ---------------------------------------------------------------------------
# 11. Error envelope shape is correct on all failures
# ---------------------------------------------------------------------------


async def test_error_envelope_has_required_fields(fake_redis):
    user = _make_user()
    actor = _make_actor(user)

    async with _build_client(user, actor) as ac:
        with patch(
            "app.api.v1.agents.invoke",
            new=AsyncMock(side_effect=BudgetExhausted("no budget")),
        ):
            r = await ac.post(_INVOKE_URL, json=_GOOD_BODY)

    assert r.status_code == 402
    body = r.json()
    assert "error" in body
    err = body["error"]
    assert "code" in err
    assert "message" in err
    assert "agent_id" in err
    assert "details" in err
    assert err["agent_id"] == _AGENT_ID
