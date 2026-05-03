"""Tests for GET /api/v1/agents and GET /api/v1/agents/{id} (task agent-core-mvp-034).

Uses dependency overrides to avoid a live database while still running the
real FastAPI routing layer.  The registry is reset between tests so
descriptors registered by one case cannot leak into another.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient

from app.agents import registry as agent_registry
from app.agents.registry import AgentDescriptor
from app.api.deps import get_current_user
from app.core.database import get_db
from app.main import app
from app.models.user import User
from app.models.workspace import AgentAccessLevel, WorkspaceMember

# ---------------------------------------------------------------------------
# Descriptor factories
# ---------------------------------------------------------------------------


def _make_descriptor(
    agent_id: str,
    *,
    required_scope: str = "agents:read",
    supported_modes: tuple = ("read_only",),
    surfaces: frozenset | None = None,
) -> AgentDescriptor:
    return AgentDescriptor(
        id=agent_id,
        name=f"Agent {agent_id}",
        description=f"Description for {agent_id}",
        schema_version="v1",
        surfaces=surfaces if surfaces is not None else frozenset({"chat_bubble", "a2a"}),
        allowed_contexts=frozenset({"workspace"}),
        supported_modes=supported_modes,
        required_scope=required_scope,
        tools_overview=("tool_a",),
        default_turn_limit=200,
        default_budget_usd=Decimal("1.00"),
        default_budget_scope="per_invocation",
        streaming=True,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_user(user_id: uuid.UUID | None = None) -> User:
    u = User()
    u.id = user_id or uuid.uuid4()
    u.email = f"test-{u.id.hex[:8]}@example.com"
    u.name = "Test User"
    u.hashed_password = "hashed"
    return u


def _make_membership(
    user_id: uuid.UUID,
    access: AgentAccessLevel = AgentAccessLevel.FULL,
) -> WorkspaceMember:
    m = WorkspaceMember()
    m.workspace_id = uuid.uuid4()
    m.user_id = user_id
    m.agent_access = access
    return m


@pytest.fixture(autouse=True)
def reset_registry():
    """Clear the registry before and after every test."""
    agent_registry.clear()
    yield
    agent_registry.clear()


@pytest.fixture
def three_agents():
    """Register three canonical descriptors used across most tests."""
    agent_registry.register(_make_descriptor("general", required_scope="agents:invoke",
                                             supported_modes=("full", "read_only")))
    agent_registry.register(_make_descriptor("researcher", required_scope="agents:read",
                                             supported_modes=("read_only",)))
    agent_registry.register(_make_descriptor("diagram-explainer", required_scope="agents:read",
                                             supported_modes=("read_only",)))


def _jwt_client(user: User, membership: WorkspaceMember | None):
    """Return an AsyncClient with JWT-style auth overrides."""
    async def _fake_db() -> AsyncGenerator:
        db = AsyncMock()
        # Simulate db.execute returning a result that has scalar_one_or_none()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = membership
        db.execute = AsyncMock(return_value=result_mock)
        yield db

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _fake_db
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test",
                       headers={"Authorization": "Bearer fake-jwt-token"})


def _apikey_client(user: User, scopes: list[str]):
    """Return an AsyncClient simulating an API-key actor."""
    api_key = MagicMock()
    api_key.permissions = scopes

    # Must annotate `request` as `Request` so FastAPI treats it as a special
    # dependency injection (not a query/body parameter).
    async def _fake_user(request: Request):
        request.state.api_key = api_key
        return user

    async def _fake_db() -> AsyncGenerator:
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)
        yield db

    app.dependency_overrides[get_current_user] = _fake_user
    app.dependency_overrides[get_db] = _fake_db
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test",
                       headers={"Authorization": "Bearer ak_fake"})


@pytest.fixture(autouse=True)
def clear_overrides():
    """Always clean up dependency overrides after each test."""
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 1. No auth → 401
# ---------------------------------------------------------------------------


async def test_list_agents_no_auth(three_agents):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/agents")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# 2. User with agent_access=full → returns all 3 agents
# ---------------------------------------------------------------------------


async def test_list_agents_user_full_access(three_agents):
    user = _make_user()
    membership = _make_membership(user.id, AgentAccessLevel.FULL)
    async with _jwt_client(user, membership) as ac:
        r = await ac.get("/api/v1/agents")
    assert r.status_code == 200
    data = r.json()
    assert len(data["agents"]) == 3
    ids = {a["id"] for a in data["agents"]}
    assert ids == {"general", "researcher", "diagram-explainer"}


# ---------------------------------------------------------------------------
# 3. User with agent_access=read_only → only read_only-supporting agents
# ---------------------------------------------------------------------------


async def test_list_agents_user_read_only_access(three_agents):
    user = _make_user()
    membership = _make_membership(user.id, AgentAccessLevel.READ_ONLY)
    async with _jwt_client(user, membership) as ac:
        r = await ac.get("/api/v1/agents")
    assert r.status_code == 200
    data = r.json()
    # general has supported_modes=("full","read_only") — included
    # researcher has read_only — included
    # diagram-explainer has read_only — included
    assert len(data["agents"]) == 3
    ids = {a["id"] for a in data["agents"]}
    assert "general" in ids


async def test_list_agents_user_read_only_excludes_full_only_agent(three_agents):
    """An agent that supports ONLY 'full' mode must be excluded for read_only users."""
    agent_registry.register(
        _make_descriptor("full-only", required_scope="agents:invoke",
                         supported_modes=("full",))
    )
    user = _make_user()
    membership = _make_membership(user.id, AgentAccessLevel.READ_ONLY)
    async with _jwt_client(user, membership) as ac:
        r = await ac.get("/api/v1/agents")
    assert r.status_code == 200
    ids = {a["id"] for a in r.json()["agents"]}
    assert "full-only" not in ids


# ---------------------------------------------------------------------------
# 4. User with agent_access=none → returns empty list
# ---------------------------------------------------------------------------


async def test_list_agents_user_none_access(three_agents):
    user = _make_user()
    membership = _make_membership(user.id, AgentAccessLevel.NONE)
    async with _jwt_client(user, membership) as ac:
        r = await ac.get("/api/v1/agents")
    assert r.status_code == 200
    assert r.json()["agents"] == []


# ---------------------------------------------------------------------------
# 5. ApiKey with scopes=['agents:read'] → only agents requiring agents:read
# ---------------------------------------------------------------------------


async def test_list_agents_apikey_read_scope(three_agents):
    """API key with agents:read should see researcher and diagram-explainer but NOT general
    (which requires agents:invoke)."""
    user = _make_user()
    async with _apikey_client(user, ["agents:read"]) as ac:
        r = await ac.get("/api/v1/agents")
    assert r.status_code == 200
    data = r.json()
    ids = {a["id"] for a in data["agents"]}
    assert "researcher" in ids
    assert "diagram-explainer" in ids
    assert "general" not in ids


# ---------------------------------------------------------------------------
# 6. GET /agents?surface=a2a → only agents with 'a2a' surface
# ---------------------------------------------------------------------------


async def test_list_agents_surface_filter(three_agents):
    # Replace three_agents with custom surface config
    agent_registry.clear()
    agent_registry.register(_make_descriptor("chat-only", surfaces=frozenset({"chat_bubble"})))
    agent_registry.register(_make_descriptor("a2a-only", surfaces=frozenset({"a2a"})))
    agent_registry.register(_make_descriptor("multi", surfaces=frozenset({"chat_bubble", "a2a"})))

    user = _make_user()
    membership = _make_membership(user.id, AgentAccessLevel.FULL)
    async with _jwt_client(user, membership) as ac:
        r = await ac.get("/api/v1/agents?surface=a2a")
    assert r.status_code == 200
    ids = {a["id"] for a in r.json()["agents"]}
    assert "a2a-only" in ids
    assert "multi" in ids
    assert "chat-only" not in ids


# ---------------------------------------------------------------------------
# 7. GET /agents/{id} → 200 with correct descriptor
# ---------------------------------------------------------------------------


async def test_get_agent_returns_descriptor(three_agents):
    user = _make_user()
    membership = _make_membership(user.id, AgentAccessLevel.FULL)
    async with _jwt_client(user, membership) as ac:
        r = await ac.get("/api/v1/agents/researcher")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "researcher"
    assert body["schema_version"] == "v1"
    assert "limits" in body
    assert body["limits"]["turn_limit"] == 200
    assert body["limits"]["budget_usd"] == "1.00"
    assert body["streaming"] is True


# ---------------------------------------------------------------------------
# 8. GET /agents/{id} for ApiKey with insufficient scope → 404
# ---------------------------------------------------------------------------


async def test_get_agent_apikey_insufficient_scope(three_agents):
    """ApiKey with only agents:read cannot see 'general' (requires agents:invoke) → 404."""
    user = _make_user()
    async with _apikey_client(user, ["agents:read"]) as ac:
        r = await ac.get("/api/v1/agents/general")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 9. GET /agents/unknown → 404
# ---------------------------------------------------------------------------


async def test_get_agent_unknown(three_agents):
    user = _make_user()
    membership = _make_membership(user.id, AgentAccessLevel.FULL)
    async with _jwt_client(user, membership) as ac:
        r = await ac.get("/api/v1/agents/unknown-agent-xyz")
    assert r.status_code == 404
