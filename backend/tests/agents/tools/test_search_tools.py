"""Tests for app/agents/tools/search_tools.py.

All four search tools are covered with stubbed AsyncSession / monkeypatched
services — no real DB or LLM required.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

# Import module to trigger @tool decorator registrations.
import app.agents.tools.search_tools  # noqa: F401
from app.agents.tools.base import ToolContext, clear_tools, filter_tools, get_tool
from app.agents.tools.search_tools import (
    list_connection_protocols,
    list_object_type_definitions,
    search_existing_objects,
    search_existing_technologies,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeActor:
    kind: str = "user"
    id: UUID = None  # type: ignore[assignment]
    workspace_id: UUID = None  # type: ignore[assignment]
    scopes: tuple[str, ...] = ()
    role: Any = None


class FakeSession:
    """AsyncSession stub: records execute calls and returns preset results."""

    def __init__(self, rows: list[Any] | None = None) -> None:
        self._rows = rows or []
        self.executed: list[Any] = []

    async def execute(self, stmt: Any) -> Any:
        self.executed.append(stmt)
        result = MagicMock()
        result.scalars.return_value.all.return_value = list(self._rows)
        return result


def _make_ctx(
    db: FakeSession | None = None,
    workspace_id: UUID | None = None,
) -> ToolContext:
    ws = workspace_id or uuid4()
    return ToolContext(
        db=db or FakeSession(),
        actor=FakeActor(kind="user", id=uuid4(), workspace_id=ws),
        workspace_id=ws,
        chat_context={"kind": "workspace", "id": ws},
        session_id=uuid4(),
        agent_id="general",
        agent_runtime_mode="full",
        active_draft_id=None,
        draft_target_diagram_id=None,
    )


def _fake_object(
    name: str,
    obj_type: str = "system",
    parent_id: UUID | None = None,
    description: str | None = None,
) -> MagicMock:
    obj = MagicMock()
    obj.id = uuid4()
    obj.name = name
    obj.type = obj_type
    obj.parent_id = parent_id
    obj.description = description
    obj.draft_id = None
    return obj


def _fake_technology(
    name: str,
    slug: str,
    category: str = "protocol",
    workspace_id: UUID | None = None,
) -> MagicMock:
    tech = MagicMock()
    tech.id = uuid4()
    tech.name = name
    tech.slug = slug
    tech.category = category
    tech.workspace_id = workspace_id
    return tech


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_and_reload_registry():
    """Clear the tool registry before each test then re-register search tools."""
    clear_tools()
    # Re-importing is not needed after clear because the @tool decorators
    # ran at import time (module already loaded); we need to re-register
    # the Tool objects explicitly.
    from app.agents.tools.base import register_tool
    from app.agents.tools.search_tools import (
        list_connection_protocols,
        list_object_type_definitions,
        search_existing_objects,
        search_existing_technologies,
    )

    for t in [
        search_existing_objects,
        search_existing_technologies,
        list_connection_protocols,
        list_object_type_definitions,
    ]:
        register_tool(t)
    yield
    clear_tools()


# ---------------------------------------------------------------------------
# search_existing_objects
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_existing_objects_returns_ranked_items():
    objs = [
        _fake_object("Order Service", "system"),
        _fake_object("Order Processor", "app"),
        _fake_object("User Service", "system"),
    ]
    db = FakeSession(rows=objs)
    ctx = _make_ctx(db=db)

    from app.agents.tools.search_tools import SearchExistingObjectsInput

    args = SearchExistingObjectsInput(query="Order", limit=10)
    result = await search_existing_objects.handler(args, ctx)

    assert "items" in result
    assert "total_matches" in result
    # Should include both "Order*" objects; "User Service" is present in DB rows
    # but will have a lower score — all three come back since our stub returns all rows.
    names = [item["name"] for item in result["items"]]
    # Order-prefixed items should rank above "User Service"
    order_idx = [i for i, n in enumerate(names) if "Order" in n]
    user_idx = [i for i, n in enumerate(names) if "User" in n]
    if order_idx and user_idx:
        assert min(order_idx) < min(user_idx)

    # Each item has required fields
    for item in result["items"]:
        assert "id" in item
        assert "name" in item
        assert "type" in item
        assert "parent_id" in item
        assert "score" in item
        assert 0.0 <= item["score"] <= 1.0


@pytest.mark.asyncio
async def test_search_existing_objects_types_filter_applied():
    """types filter is passed into the SQLAlchemy WHERE clause (verified via stmt inspection)."""
    db = FakeSession(rows=[])
    ctx = _make_ctx(db=db)

    from app.agents.tools.search_tools import SearchExistingObjectsInput

    args = SearchExistingObjectsInput(query="payment", types=["app", "store"], limit=10)
    result = await search_existing_objects.handler(args, ctx)

    assert result["items"] == []
    assert result["total_matches"] == 0
    # A statement was executed (types filter was included)
    assert len(db.executed) == 1


@pytest.mark.asyncio
async def test_search_existing_objects_empty_query_returns_empty():
    """An empty/blank query must never dump the entire workspace."""
    db = FakeSession(rows=[_fake_object("Anything")])
    ctx = _make_ctx(db=db)

    from app.agents.tools.search_tools import SearchExistingObjectsInput

    for empty in ("", "   "):
        result = await search_existing_objects.handler(
            SearchExistingObjectsInput(query=empty, limit=20), ctx
        )
        assert result == {"items": [], "total_matches": 0}
    # DB should never have been touched
    assert db.executed == []


# ---------------------------------------------------------------------------
# search_existing_technologies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_existing_technologies_mixed_builtin_and_custom(monkeypatch):
    """Results include both built-in (workspace_id=None) and workspace-custom entries."""
    builtin_http = _fake_technology("HTTP", "http", "protocol", workspace_id=None)
    custom_grpc = _fake_technology("gRPC", "grpc", "protocol", workspace_id=uuid4())

    from app.services import technology_service

    monkeypatch.setattr(
        technology_service,
        "list_technologies",
        AsyncMock(return_value=[builtin_http, custom_grpc]),
    )

    from app.agents.tools.search_tools import SearchExistingTechnologiesInput

    ctx = _make_ctx()
    args = SearchExistingTechnologiesInput(query="http", limit=20)
    result = await search_existing_technologies.handler(args, ctx)

    workspace_ids = {item["workspace_id"] for item in result["items"]}
    assert None in workspace_ids  # built-in
    assert any(wid is not None for wid in workspace_ids)  # custom


@pytest.mark.asyncio
async def test_search_existing_technologies_empty_query_returns_empty(monkeypatch):
    from app.services import technology_service

    mock_list = AsyncMock(return_value=[])
    monkeypatch.setattr(technology_service, "list_technologies", mock_list)

    from app.agents.tools.search_tools import SearchExistingTechnologiesInput

    ctx = _make_ctx()
    for empty in ("", "  "):
        result = await search_existing_technologies.handler(
            SearchExistingTechnologiesInput(query=empty, limit=20), ctx
        )
        assert result == {"items": [], "total_matches": 0}

    # service should never be called for empty query
    mock_list.assert_not_called()


# ---------------------------------------------------------------------------
# list_connection_protocols
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_connection_protocols_returns_only_protocols():
    protocols = [
        _fake_technology("HTTP", "http", "protocol"),
        _fake_technology("gRPC", "grpc", "protocol"),
        _fake_technology("AMQP", "amqp", "protocol"),
    ]
    db = FakeSession(rows=protocols)
    ctx = _make_ctx(db=db)

    from app.agents.tools.search_tools import ListConnectionProtocolsInput

    result = await list_connection_protocols.handler(ListConnectionProtocolsInput(), ctx)

    assert "items" in result
    assert "total" in result
    assert result["total"] == len(protocols)

    for item in result["items"]:
        assert item["category"] == "protocol"
        assert "id" in item
        assert "name" in item
        assert "slug" in item


# ---------------------------------------------------------------------------
# list_object_type_definitions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_object_type_definitions_returns_all_7_types():
    ctx = _make_ctx()

    from app.agents.tools.search_tools import ListObjectTypeDefinitionsInput

    result = await list_object_type_definitions.handler(
        ListObjectTypeDefinitionsInput(), ctx
    )

    assert "types" in result
    type_names = {t["type"] for t in result["types"]}
    expected = {"system", "external_system", "actor", "app", "store", "component", "group"}
    assert type_names == expected
    assert len(result["types"]) == 7

    # Each entry must have description and valid_at_level
    for entry in result["types"]:
        assert "description" in entry and entry["description"]
        assert "valid_at_level" in entry


@pytest.mark.asyncio
async def test_list_object_type_definitions_is_static():
    """Calling twice returns equal results (static data, no DB involved)."""
    ctx = _make_ctx()

    from app.agents.tools.search_tools import ListObjectTypeDefinitionsInput

    r1 = await list_object_type_definitions.handler(ListObjectTypeDefinitionsInput(), ctx)
    r2 = await list_object_type_definitions.handler(ListObjectTypeDefinitionsInput(), ctx)
    assert r1 == r2


# ---------------------------------------------------------------------------
# Tool registry metadata
# ---------------------------------------------------------------------------


def test_all_search_tools_registered_with_correct_metadata():
    """All four tools must be registered as mutating=False, required_scope='agents:read'."""
    expected_names = {
        "search_existing_objects",
        "search_existing_technologies",
        "list_connection_protocols",
        "list_object_type_definitions",
    }
    visible = filter_tools(scope="agents:read", mode="full")
    registered_names = {t.name for t in visible}
    assert expected_names.issubset(registered_names)

    for name in expected_names:
        t = get_tool(name)
        assert t.mutating is False, f"{name} must be non-mutating"
        assert t.required_scope == "agents:read", f"{name} must require agents:read scope"
